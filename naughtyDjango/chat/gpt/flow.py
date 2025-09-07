from typing import Dict, Optional, Tuple
from main.models import User
from chat.models import ChatMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory

from chat.constants.fields import REQUIRED_KEYS, REQUIRED_KEYS_ORDER, QUESTION_KO
from chat.gpt.prompts import finetune_prompt
from chat.gpt.openai_client import client
from chat.gpt.parser import extract_fields_from_natural_response
from chat.gpt.session_store import (
    get_session_data,
    set_session_data,
    delete_session_data,
    get_conflict_pending,
    pop_conflict_pending,
)


# 세션별 대화 이력 저장소 (LangChain용)
store: Dict[str, ChatMessageHistory] = {}


def get_session_history(session_id: str) -> ChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]


def convert_history_to_openai_format(history):
    role_map = {"human": "user", "ai": "assistant", "system": "system"}
    return [{"role": role_map.get(msg.type, msg.type), "content": msg.content} for msg in history]


def run_gpt(input_data, config, ai_model):
    user_input = input_data["input"]
    session_id = config.get("configurable", {}).get("session_id")

    if user_input.strip() in ["네", "아니오"] and get_conflict_pending() is not None:
        pending = pop_conflict_pending() or {}
        if user_input.strip() == "네":
            current = get_session_data(session_id)
            current.update(pending)
            set_session_data(session_id, current)
            return {"output": "프로필이 성공적으로 업데이트되었습니다. 계속 진행할게요."}
        else:
            return {"output": "기존 프로필 정보를 유지합니다. 계속 진행할게요."}

    current_data = get_session_data(session_id)
    missing_keys = [key for key in REQUIRED_KEYS if key not in current_data or current_data[key] is None]

    base_prompt = input_data.get("system_prompt", finetune_prompt)
    prompt_addition = ""
    if missing_keys:
        prompt_addition = (
            "아직 수집되지 않은 정보는 다음과 같습니다:\n"
            f"{', '.join(missing_keys)}\n"
            "이 정보를 자연스럽게 대화를 통해 질문해 주세요. 질문은 반드시 한 번에 하나씩 하세요."
        )

    full_prompt = base_prompt + prompt_addition

    history = get_session_history(session_id).messages
    formatted_history = convert_history_to_openai_format(history)

    messages = [{"role": "system", "content": full_prompt}] + formatted_history + [
        {"role": "user", "content": user_input}
    ]

    response = client.create_completion(
        messages=messages,
        model=ai_model,
        temperature=0.0,
        max_tokens=150,
    )
    return {"output": response.choices[0].message.content}


# Runnable 구성
from functools import partial

fine_tuned_model = "ft:gpt-3.5-turbo-0125:personal::BDpYRjbn"
run_gpt_with_model = partial(run_gpt, ai_model=fine_tuned_model)
runnable = RunnableLambda(run_gpt_with_model)
with_message_history = RunnableWithMessageHistory(
    runnable,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)


def save_profile_from_gpt(parsed_data, user_id, session_id):
    """수집 완료된 프로필을 User DB에 저장 (필드 타입 정규화 포함)"""
    import re
    def to_int_maybe(value):
        if value is None:
            return None
        if isinstance(value, int):
            return value
        s = str(value)
        digits = re.sub(r"[^0-9-]", "", s)
        try:
            return int(digits) if digits != "" else None
        except Exception:
            return None

    try:
        # 1차: 전달된 user_id(email)로 조회
        try:
            user = User.objects.get(email=user_id)
        except Exception:
            # 2차: 세션의 최근 메시지에서 username(email) 추론
            recent = ChatMessage.objects.filter(session_id=session_id).order_by('-timestamp').first()
            if not recent or not recent.username:
                raise
            user = User.objects.get(email=recent.username)
        # 정수형
        age = to_int_maybe(parsed_data.get("age"))
        if age is not None:
            user.age = age

        monthly_income = to_int_maybe(parsed_data.get("monthly_income"))
        if monthly_income is not None:
            user.income = monthly_income

        investment_horizon = to_int_maybe(parsed_data.get("investment_horizon"))
        if investment_horizon is not None:
            user.period = investment_horizon

        expected_return = to_int_maybe(parsed_data.get("expected_return"))
        if expected_return is not None:
            user.expected_income = expected_return

        expected_loss = to_int_maybe(parsed_data.get("expected_loss"))
        if expected_loss is not None:
            user.expected_loss = expected_loss

        asset_allocation_type = to_int_maybe(parsed_data.get("asset_allocation_type"))
        if asset_allocation_type is not None:
            user.asset_allocation_type = asset_allocation_type

        value_growth = to_int_maybe(parsed_data.get("value_growth"))
        if value_growth is not None:
            user.value_growth = value_growth

        risk_acceptance_level = to_int_maybe(parsed_data.get("risk_acceptance_level"))
        if risk_acceptance_level is not None:
            user.risk_acceptance_level = risk_acceptance_level

        # 문자열형
        for key, dest in [
            ("income_stability", "income_stability"),
            ("risk_tolerance", "risk_tolerance"),
            ("income_sources", "income_source"),
            ("investment_purpose", "purpose"),
            ("investment_concern", "investment_concern"),
        ]:
            val = parsed_data.get(key)
            if val is not None:
                setattr(user, dest, str(val))

        user.save()
        import logging
        logging.getLogger(__name__).info(
            "profile_saved",
            extra={
                "session_id": session_id,
                "user_email": user_id,
                "saved_keys": [
                    k for k in parsed_data.keys()
                    if parsed_data.get(k) is not None
                ],
            },
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"save_profile_from_gpt failed: {e}")


def handle_chat(user_input, session_id, user_id=None):
    # 직전 질문 키 추적 및 입력 반영
    current = get_session_data(session_id)
    last_asked_key = current.get("_last_asked_key")

    # 사용자 입력에서 우선 필드 추출 시도 (파싱 성공 시 세션 반영)
    user_extracted = extract_fields_from_natural_response(user_input, session_id)
    if user_extracted:
        valid_fields = {k: v for k, v in user_extracted.items() if k in REQUIRED_KEYS and v is not None}
        if valid_fields:
            current.update(valid_fields)
            set_session_data(session_id, current)
    else:
        # 파서가 값을 못 뽑은 경우: 자유형 텍스트 필드에 한해 의미 있는 답변이면 수용
        free_text_fields = {"investment_purpose", "investment_concern", "income_sources"}
        if last_asked_key in free_text_fields and user_input.strip():
            text = user_input.strip()
            is_trivial = text in {"네", "아니오", "모름", "몰라", "잘 몰라요"}
            looks_numeric = text.replace(",", "").replace(" ", "").isdigit()
            concern_signals = ["고민", "걱정", "불안", "궁금", "어렵", "손실", "리스크", "추천", "수익", "손해", "떨어", "하락", "변동", "불확실"]
            seems_concern = any(sig in text for sig in concern_signals) or "?" in text or len(text) >= 6
            if last_asked_key != "investment_concern":
                # 목적/소득원 등은 너무 짧지 않고 숫자만 아니면 수용
                if not is_trivial and not looks_numeric and len(text) >= 2:
                    current[last_asked_key] = text
                    set_session_data(session_id, current)
            else:
                # 투자 고민은 실제 고민스러운 표현일 때만 수용
                if not is_trivial and not looks_numeric and seems_concern:
                    current[last_asked_key] = text
                    set_session_data(session_id, current)

    # 누락된 키(질문해야 할 항목)를 순서대로 계산
    current_data = get_session_data(session_id)
    missing_ordered = [k for k in REQUIRED_KEYS_ORDER if k not in current_data or current_data.get(k) is None]

    # 직전에 물었던 키가 아직 비어 있으면, 프롬프트를 활용해 LLM이 간단 설명 + 재질문 생성
    if last_asked_key and (last_asked_key in missing_ordered):
        field_desc = {
            "age": "나이는 투자 적합성 판단에 필요한 기본 정보입니다.",
            "monthly_income": "월 소득은 투자 여력과 적합한 상품군 판단에 쓰입니다.",
            "risk_tolerance": "위험 허용 정도는 손실 가능성에 대한 감내 수준을 뜻합니다.",
            "income_stability": "소득 안정성은 수입의 꾸준함을 나타냅니다.",
            "income_sources": "소득원은 월급, 아르바이트 등 주된 수입의 종류입니다.",
            "investment_horizon": "투자 기간은 자금을 얼마나 오래 투자할지의 계획입니다.",
            "expected_return": "기대 수익은 일정 기간 기대하는 수익 규모입니다.",
            "expected_loss": "예상 손실은 감수 가능한 손실 규모입니다.",
            "investment_purpose": "투자 목적은 안정적 수익, 성장 등 달성 목표입니다.",
            "asset_allocation_type": "자산 배분 유형은 주식 비중 구간을 의미합니다.",
            "value_growth": "가치/성장은 가치주 중심인지 성장주 중심인지의 선호입니다.",
            "risk_acceptance_level": "위험 수용 수준은 보수적~공격적 단계의 위험 감내 정도입니다.",
            "investment_concern": "투자 고민은 현재 가장 걱정되거나 궁금한 점입니다.",
        }.get(last_asked_key, "이 항목은 투자 적합성 판단에 필요한 정보입니다.")

        numeric_keys = {"age","monthly_income","investment_horizon","expected_return","expected_loss","asset_allocation_type","value_growth","risk_acceptance_level"}
        field_type = "numeric" if last_asked_key in numeric_keys else "text"

        system_prompt = (
            finetune_prompt
            + "\n\n아래 지침만 따르세요. 지침을 인용하거나 설명하지 마세요.\n"
            + "- 출력은 정확히 2줄\n"
            + "  1) 첫 줄: 필드 설명 1문장 (자연스러운 한국어 존댓말, 질문 금지, 물음표 금지)\n"
            + "  2) 둘째 줄: 해당 항목을 직설적으로 다시 질문 (물음표로 끝남)\n"
            + f"- 필드: {last_asked_key}\n"
            + f"- 타입: {field_type}\n"
            + f"- 설명 힌트: {field_desc}\n"
            + ("- 타입이 숫자형이면, 둘째 줄 질문에서 물음표 앞에 ' (숫자만 입력해 주세요)'를 괄호로 덧붙이세요. 예: '... (숫자만 입력해 주세요)?'\n" if field_type == "numeric" else "")
        )

        input_data = {
            "input": f"사용자 마지막 발화: '{user_input}'. 위 규칙에 따라 설명 1문장과 질문 1문장을 생성해 주세요.",
            "system_prompt": system_prompt,
        }
        config = {"configurable": {"session_id": session_id}}
        result = run_gpt_with_model(input_data, config)
        output_text = (result.get("output") or "").strip()
        lines = [ln.strip().strip('"\'') for ln in output_text.splitlines() if ln.strip()]
        if len(lines) >= 2:
            first, second = lines[0], lines[1]
            # 첫 줄이 질문처럼 보이면(물음표 포함/끝남), 설명으로 교체
            if first.endswith("?") or "?" in first:
                first = field_desc
            # 숫자형 힌트 정규화: 질문부와 힌트부를 분리해 문장부호를 정리
            if field_type == "numeric":
                import re
                # 힌트 구문 제거(문장부호 포함) 후 별도 보관
                hint_pattern = r"\s*숫자만 입력해 주세요[\.?]?\s*"
                has_hint = re.search(hint_pattern, second) is not None
                second_core = re.sub(hint_pattern, " ", second).strip()
                # 질문부는 반드시 물음표로 종료
                if not second_core.endswith("?"):
                    second_core = second_core.rstrip(".") + "?"
                # 힌트는 온점으로 종료하여 별도 부가
                if has_hint:
                    second = second_core + " 숫자만 입력해 주세요."
                else:
                    second = second_core
            else:
                # 숫자형이 아니면 둘째 줄은 질문부만, 물음표 보장
                if not second.endswith("?"):
                    second = second.rstrip(".") + "?"
            return first + "\n" + second, session_id
        # 폴백: 질문이 없으면 고정 질문 사용
        question = QUESTION_KO.get(last_asked_key, "해당 항목을 알려주세요.")
        if field_type == "numeric" and "숫자" not in question:
            if not question.endswith("?"):
                question = question.rstrip(".") + "?"
            question = question + " 숫자만 입력해 주세요."
        explanation = lines[0] if lines else field_desc
        return f"{explanation}\n{question}", session_id

    # 누락 항목이 있으면 다음 하나만 질문으로 반환
    if missing_ordered:
        next_key = missing_ordered[0]
        current = get_session_data(session_id)
        current["_last_asked_key"] = next_key
        set_session_data(session_id, current)
        return QUESTION_KO[next_key], session_id

    # 여기까지 왔다면 모든 항목이 채워진 상태
    if REQUIRED_KEYS.issubset(current_data.keys()):
        if user_id:
            save_profile_from_gpt(current_data, user_id, session_id)
        delete_session_data(session_id)
        return "이제 금융상품을 추천해줄게요!", session_id

    # 필요 시 모델 기반 대화로 폴백
    result = with_message_history.invoke(
        {"input": user_input},
        config={"configurable": {"session_id": session_id}},
    )
    gpt_reply = result["output"]

    extracted_fields = extract_fields_from_natural_response(gpt_reply, session_id)
    if extracted_fields:
        valid_fields = {k: v for k, v in extracted_fields.items() if k in REQUIRED_KEYS and v is not None}
        current = get_session_data(session_id)
        current.update(valid_fields)
        set_session_data(session_id, current)

    current_data = get_session_data(session_id)
    if REQUIRED_KEYS.issubset(current_data.keys()):
        if user_id:
            save_profile_from_gpt(current_data, user_id, session_id)
        delete_session_data(session_id)

    return gpt_reply, session_id


