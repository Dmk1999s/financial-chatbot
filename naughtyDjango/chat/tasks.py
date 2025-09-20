#chat/tasks.py

from celery import shared_task
from openai import OpenAI
import os
import re
import io
from .models import ChatMessage
from main.models import User
from chat.gpt.parser import extract_json_from_response
from chat.gpt.flow import handle_chat
from chat.gpt.session_store import get_session_data, set_session_data
from django.core.management import call_command

DETECTION_SYSTEM = """
당신은 '투자 프로필 변경 트리거'를 감지하는 어시스턴트입니다.
사용자 발화를 보고, 아래 필드 중 변경 의도가 있는지 JSON으로 반환하세요.

감지할 필드:
- age: 나이 (예: "25살", "30세", "나이 25" 등)
- monthly_income: 월 수입 (예: "300만원", "월급 500만원" 등)
- annual_income: 연 수입 (예: "3600만원", "연봉 4000만원" 등)
- risk_tolerance: 위험 허용 정도 (예: "보수적", "적극적", "중간" 등)
- income_stability: 소득 안정성 (예: "안정적", "불안정" 등)
- income_sources: 소득원 (예: "월급", "아르바이트" 등)
- investment_horizon: 투자 기간 (예: "1년", "3개월" 등)
- expected_income: 기대 수익 (예: "10%", "100만원" 등)
- expected_loss: 예상 손실 (예: "5%", "50만원" 등)
- investment_purpose: 투자 목적 (예: "안정적 수익", "성장" 등)
- asset_allocation_type: 자산 배분 유형 (0-4)
- value_growth: 가치/성장 구분 (0: 가치, 1: 성장)
- risk_acceptance_level: 위험 수용 수준 (1-4)
- investment_concern: 투자 관련 고민 (문자열)

응답 형식:
{"field": "필드명", "value": "값"}

예시:
- "저는 25살이에요" → {"field": "age", "value": 25}
- "월급이 300만원이에요" → {"field": "monthly_income", "value": 3000000}
- "연봉으로 5000만원 정도 벌어요" → {"field": "annual_income", "value": 50000000}
- "보수적으로 투자하고 싶어요" → {"field": "risk_tolerance", "value": "낮음"}

변경 의도가 없으면 {} 만 반환하세요.
"""


@shared_task
def process_chat_async(session_id, username, message, product_type):
    """Async task for heavy GPT processing"""
    try:
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        session_snapshot = get_session_data(session_id) or {}
        last_asked_key = session_snapshot.get("_last_asked_key")

        detection_messages = [
            {"role": "system", "content": DETECTION_SYSTEM},
        ]
        if last_asked_key:
            detection_messages.append({
                "role": "system",
                "content": f"현재 질문 중인 필드: {last_asked_key}. 사용자가 수치/금액만 말하더라도 해당 필드로 간주하여 감지하세요.",
            })
        detection_messages.append({"role": "user", "content": message})

        detect_resp = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=detection_messages,
            temperature=0,
            max_tokens=200,
        )

        trigger = extract_json_from_response(detect_resp.choices[0].message.content)

        if isinstance(trigger, dict) and trigger:
            field = trigger.get("field")
            value = _normalize_trigger_value(field, trigger.get("value"))

            if field and value is not None:
                # DB에서 사용자 정보 가져오기
                try:
                    user = User.objects.get(email=username)
                    current_data = {}

                    # DB 필드와 매핑
                    field_mapping = {
                        'age': user.age,
                        'monthly_income': user.income,
                        'risk_tolerance': user.risk_tolerance,
                        'income_stability': user.income_stability,
                        'income_sources': user.income_source,
                        'investment_horizon': user.period,
                        'expected_income': user.expected_income,
                        'expected_loss': user.expected_loss,
                        'investment_purpose': user.purpose,
                        'asset_allocation_type': user.asset_allocation_type,
                        'value_growth': user.value_growth,
                        'risk_acceptance_level': user.risk_acceptance_level,
                        'investment_concern': user.investment_concern,
                    }

                    # 현재 DB 값 가져오기
                    current_value = field_mapping.get(field)

                    # 충돌 확인 (DB 값이 있고, 새 값과 다를 때)
                    if current_value is not None and current_value != value:
                        return {
                            "type": "conflict_detected",
                            "field": field,
                            "value": value,
                            "db_value": current_value,
                            "message": f"프로필 변경이 감지되었습니다: {field} = {value} (기존: {current_value})"
                        }
                    else:
                        # 충돌이 없으면 '세션 캐시'에만 반영하고,
                        # 모든 키가 채워지는 시점에 handle_chat에서 일괄 저장
                        session_data = get_session_data(session_id)
                        session_data[field] = value
                        set_session_data(session_id, session_data)

                except User.DoesNotExist:
                    pass

        # If detection failed, fallback by field type
        if (not isinstance(trigger, dict) or not trigger):
            # numeric fields: parse currency
            if last_asked_key in {"monthly_income", "expected_return", "expected_loss"}:
                parsed_val = _parse_currency_kr_to_won(message)
                if parsed_val is not None:
                    session_data = get_session_data(session_id)
                    session_data[last_asked_key] = parsed_val
                    set_session_data(session_id, session_data)
            # free-text fields: accept meaningful user text to break loops
            elif last_asked_key in {"investment_purpose", "investment_concern", "income_sources"}:
                text = (message or "").strip()
                if text:
                    trivial = {"네", "아니오", "모름", "몰라", "잘 몰라요"}
                    looks_numeric = text.replace(",", "").replace(" ", "").isdigit()
                    concern_signals = ["고민", "걱정", "불안", "궁금", "어렵", "손실", "리스크", "추천", "수익", "손해", "떨어", "하락", "변동", "불확실", "공포"]
                    seems_concern = any(sig in text for sig in concern_signals) or "?" in text or len(text) >= 6

                    accept = False
                    if last_asked_key != "investment_concern":
                        accept = (text not in trivial) and (not looks_numeric) and len(text) >= 2
                    else:
                        accept = (text not in trivial) and (not looks_numeric) and seems_concern

                    if accept:
                        session_data = get_session_data(session_id)
                        session_data[last_asked_key] = text
                        set_session_data(session_id, session_data)

        # Regular chat flow
        gpt_reply, _ = handle_chat(message, session_id, user_id=username)

        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="assistant",
            message=gpt_reply,
        )

        return {"type": "chat_response", "response": gpt_reply}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"type": "error", "error": str(e)}

@shared_task(name="index_financial_products")
def index_financial_products():
    """Run 'python manage.py index_to_opensearch' in background."""
    buf = io.StringIO()
    call_command("index_to_opensearch", stdout=buf)
    return buf.getvalue()

def _normalize_trigger_value(field: str, value):
    """Normalize LLM-detected values to canonical forms (lightweight safety net)."""
    if value is None:
        return value

    text = str(value).strip()

    # income_stability → {안정적, 불안정}
    if field == "income_stability":
        if "안정" in text:
            return "안정적"
        if "불안" in text:
            return "불안정"
        return text

    # risk_tolerance → {낮음, 중간, 높음}
    if field == "risk_tolerance":
        if any(k in text for k in ["보수", "안정"]):
            return "낮음"
        if any(k in text for k in ["중간", "보통"]):
            return "중간"
        if any(k in text for k in ["공격", "적극", "높"]):
            return "높음"
        return text

    # Money-like fields → integer won
    if field in {"monthly_income", "expected_return", "expected_loss"}:
        parsed = _parse_currency_kr_to_won(text)
        return parsed if parsed is not None else value

    return value


def _parse_currency_kr_to_won(text: str):
    """Parse KR currency phrases (e.g., '500만원', '2억 3천만 원', '3,000,000원') → int won."""
    if not text:
        return None
    s = str(text)

    # Plain digits with optional commas + '원'
    m_plain = re.search(r"([0-9][0-9,]{0,12})\s*원", s)
    if m_plain:
        try:
            return int(m_plain.group(1).replace(",", ""))
        except Exception:
            pass

    total = 0
    worked = False

    # 억 단위
    m_uk = re.search(r"([0-9]+)\s*억", s)
    if m_uk:
        total += int(m_uk.group(1)) * 100_000_000
        worked = True

    # 천만, 백만, 십만, 만 단위
    m_cheonman = re.search(r"([0-9]+)\s*천\s*만", s)
    if m_cheonman:
        total += int(m_cheonman.group(1)) * 10_000_000
        worked = True

    m_baekman = re.search(r"([0-9]+)\s*백\s*만", s)
    if m_baekman:
        total += int(m_baekman.group(1)) * 1_000_000
        worked = True

    m_shipman = re.search(r"([0-9]+)\s*십\s*만", s)
    if m_shipman:
        total += int(m_shipman.group(1)) * 100_000
        worked = True

    m_man = re.search(r"([0-9]+)\s*만(\s*원)?", s)
    if m_man:
        total += int(m_man.group(1)) * 10_000
        worked = True

    if worked:
        return total

    # Fallback: extract digits only
    digits = re.sub(r"[^0-9]", "", s)
    if digits:
        try:
            return int(digits)
        except Exception:
            return None
    return None
