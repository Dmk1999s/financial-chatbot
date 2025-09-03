from typing import Dict, Optional, Tuple
from django.contrib.auth.models import User
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
    """수집 완료된 프로필을 User DB에 저장"""
    try:
        user = User.objects.get(email=user_id)
        user.age = parsed_data.get("age")
        user.income_stability = parsed_data.get("income_stability")
        user.risk_tolerance = parsed_data.get("risk_tolerance")
        user.income_source = parsed_data.get("income_sources")
        monthly_income = parsed_data.get("monthly_income")
        if monthly_income is not None:
            user.income = monthly_income
        investment_horizon = parsed_data.get("investment_horizon")
        if investment_horizon is not None:
            user.period = investment_horizon
        expected_return = parsed_data.get("expected_return")
        if expected_return is not None:
            user.expected_income = expected_return
        expected_loss = parsed_data.get("expected_loss")
        if expected_loss is not None:
            user.expected_loss = expected_loss
        investment_purpose = parsed_data.get("investment_purpose")
        if investment_purpose is not None:
            user.purpose = investment_purpose
        if parsed_data.get("asset_allocation_type") is not None:
            user.asset_allocation_type = parsed_data.get("asset_allocation_type")
        if parsed_data.get("value_growth") is not None:
            user.value_growth = parsed_data.get("value_growth")
        if parsed_data.get("risk_acceptance_level") is not None:
            user.risk_acceptance_level = parsed_data.get("risk_acceptance_level")
        if parsed_data.get("investment_concern") is not None:
            user.investment_concern = parsed_data.get("investment_concern")
        user.save()
    except Exception:
        pass


def handle_chat(user_input, session_id, user_id=None):
    # 사용자 현재 입력에서 우선 필드를 추출하여 반영
    user_extracted = extract_fields_from_natural_response(user_input, session_id)
    if user_extracted:
        valid_fields = {k: v for k, v in user_extracted.items() if k in REQUIRED_KEYS and v is not None}
        if valid_fields:
            current = get_session_data(session_id)
            current.update(valid_fields)
            set_session_data(session_id, current)

    # 누락된 키(질문해야 할 항목)를 순서대로 계산
    current_data = get_session_data(session_id)
    missing_ordered = [k for k in REQUIRED_KEYS_ORDER if k not in current_data or current_data.get(k) is None]

    # 신규 세션이거나 수집 중이면, 다음 하나의 누락 항목만 질문으로 반환
    if session_id.startswith("new_") or missing_ordered:
        if missing_ordered:
            next_key = missing_ordered[0]
            return QUESTION_KO[next_key], session_id
        else:
            return "안녕하세요! 투자 상담을 도와드릴게요.", session_id

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


