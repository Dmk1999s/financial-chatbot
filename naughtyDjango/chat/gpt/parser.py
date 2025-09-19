# chat/gpt/parser.py (최종 수정본)

import json
import re

# session_store를 import하여 마지막 질문이 무엇이었는지 알 수 있도록 합니다.
from .session_store import get_session_data


def extract_json_from_response(text: str):
    """OpenAI 응답에서 JSON 부분만 안전하게 추출"""
    try:
        cleaned_text = re.sub(r"```json|```", "", text).strip()
        match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        else:
            return {}
    except Exception:
        return {}


def _parse_currency_kr_to_won(text: str):
    """'500만원', '2억 3천만', '3,000,000원' 같은 표현을 숫자로 변환합니다."""
    if not text:
        return None
    s = str(text).replace(",", "")

    total = 0
    worked = False

    # '억', '만' 단위를 먼저 처리
    m_uk = re.search(r"(\d+)\s*억", s)
    if m_uk:
        total += int(m_uk.group(1)) * 100000000
        worked = True

    m_man = re.search(r"(\d+)\s*만", s)
    if m_man:
        total += int(m_man.group(1)) * 10000
        worked = True

    if worked:
        return total

    # '만원' 단위가 없을 경우, 순수 숫자만 추출
    digits = re.sub(r"[^0-9]", "", s)
    if digits:
        try:
            return int(digits)
        except (ValueError, TypeError):
            return None

    return None


def extract_fields_from_natural_response(response_text: str, session_id: str) -> dict:
    """
    자연어 문장에서 주요 필드를 정규식으로 추출합니다.
    특히 숫자/금액 필드는 마지막 질문(`_last_asked_key`)을 참고하여 처리합니다.
    """
    fields = {}
    text_lower = response_text.lower()

    # --- 1. 항상 독립적으로 추출 가능한 필드 ---
    # 나이 추출 (예: "25살", "제 나이는 25세")
    age_match = re.search(r'(\d+)\s*(살|세)', text_lower)
    if age_match:
        fields['age'] = int(age_match.group(1))

    # 위험 성향 추출
    if any(word in text_lower for word in ['안전', '보수적', '낮음']):
        fields['risk_tolerance'] = '낮음'
    elif any(word in text_lower for word in ['적극적', '높음', '공격적']):
        fields['risk_tolerance'] = '높음'
    elif '중간' in text_lower or '보통' in text_lower:
        fields['risk_tolerance'] = '중간'

    # --- 2. 마지막 질문의 맥락이 필요한 숫자/금액 필드 ---
    session_data = get_session_data(session_id)
    last_asked = session_data.get("_last_asked_key")

    # 숫자 답변이 필요한 질문 목록
    numeric_keys = {
        "monthly_income", "investment_horizon", "expected_return",
        "expected_loss", "asset_allocation_type", "value_growth",
        "risk_acceptance_level"
    }

    if last_asked in numeric_keys:
        # 금액 표현(예: 200만원) 또는 단순 숫자를 파싱
        parsed_value = _parse_currency_kr_to_won(response_text)
        if parsed_value is not None:
            # 파싱에 성공하면, 마지막으로 질문했던 키에 값을 저장
            fields[last_asked] = parsed_value
        else:
            # 금액 표현이 아닐 경우, 단순 숫자(예: '4' for asset_allocation_type)라도 추출
            value_match = re.search(r'(\d+)', response_text)
            if value_match:
                try:
                    fields[last_asked] = int(value_match.group(1))
                except (ValueError, TypeError):
                    pass  # 변환 실패 시 무시

    return fields