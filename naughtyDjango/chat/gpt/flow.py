from typing import Dict, Optional, Tuple
import re
import logging

from main.models import User
from chat.models import ChatMessage

from chat.constants.fields import REQUIRED_KEYS, REQUIRED_KEYS_ORDER, QUESTION_KO, FIELD_TO_DB
from chat.gpt.openai_client import client
from chat.gpt.parser import extract_fields_from_natural_response

# [수정] session_store에서 load_user_profile_to_session 함수를 추가로 import 합니다.
from chat.gpt.session_store import (
    get_session_data,
    set_session_data,
    delete_session_data,
    load_user_profile_to_session,
)

logger = logging.getLogger(__name__)


# --- 헬퍼 함수 정의 ---

def _update_session_with_input(user_input: str, session_id: str) -> Optional[str]:
    """사용자의 입력을 파싱하여 세션 데이터를 업데이트하고, 직전 질문 키를 반환합니다."""
    current = get_session_data(session_id)
    last_asked_key = current.get("_last_asked_key")

    user_extracted = extract_fields_from_natural_response(user_input, session_id)
    if user_extracted:
        valid_fields = {k: v for k, v in user_extracted.items() if k in REQUIRED_KEYS and v is not None}
        if valid_fields:
            current.update(valid_fields)
            set_session_data(session_id, current)
            return last_asked_key

    # 파서가 값을 못 뽑은 경우, 특정 자유 텍스트 필드에 대한 답변인지 확인
    free_text_fields = {"investment_purpose", "investment_concern", "income_sources"}
    if last_asked_key in free_text_fields and len(user_input.strip()) >= 2:
        current[last_asked_key] = user_input.strip()
        set_session_data(session_id, current)

    return last_asked_key


def _find_next_question_key(session_id: str) -> Optional[str]:
    """세션 데이터를 기반으로 다음에 질문해야 할 키를 순서대로 찾습니다."""
    current_data = get_session_data(session_id)
    for key in REQUIRED_KEYS_ORDER:
        if key not in current_data or current_data.get(key) is None:
            return key
    return None


def _rephrase_question_with_llm(last_asked_key: str, user_input: str) -> str:
    """사용자가 잘못된 답변을 했을 때, LLM을 사용해 설명을 덧붙여 재질문합니다."""
    field_desc = QUESTION_KO.get(last_asked_key, "해당 항목은 투자 적합성 판단에 필요한 정보입니다.")
    system_prompt = (
        "당신은 사용자에게 프로필 정보를 질문하는 친절한 챗봇입니다. "
        "사용자가 이전에 질문한 항목에 대해 적절하지 않은 답변을 했습니다. "
        f"'{last_asked_key}' 항목에 대해 간단히 설명하고, 다시 질문해주세요. "
        "설명과 질문을 합쳐 자연스러운 한두 문장으로 만드세요. "
        f"힌트: {field_desc}"
    )

    response = client.create_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"이전 제 답변은 '{user_input}' 입니다."}
        ],
        model="gpt-3.5-turbo",
        temperature=0.3,
        max_tokens=150,
    )
    return (response.choices[0].message.content or "").strip()


def save_profile_to_db(session_id: str, user_id: Optional[str]) -> None:
    """세션에 수집된 데이터를 DB에 저장합니다."""
    if not user_id:
        return

    try:
        user = User.objects.get(email=user_id)
        profile_data = get_session_data(session_id)

        for key, db_field in FIELD_TO_DB.items():
            if key in profile_data and profile_data[key] is not None:
                # 숫자형 필드 타입 변환 로직 추가
                if db_field in ['age', 'income', 'period', 'expected_income', 'expected_loss', 'asset_allocation_type',
                                'value_growth', 'risk_acceptance_level']:
                    try:
                        value = int(profile_data[key])
                        setattr(user, db_field, value)
                    except (ValueError, TypeError):
                        logger.warning(f"Could not convert {key} to int for user {user_id}. Value: {profile_data[key]}")
                else:
                    setattr(user, db_field, profile_data[key])

        user.save()
        logger.info(f"✅ Profile saved for user: {user_id}")
    except User.DoesNotExist:
        logger.error(f"❗️User not found while saving profile: {user_id}")
    except Exception as e:
        logger.error(f"❗️Failed to save profile for user {user_id}: {e}")


# --- 메인 핸들러 함수 (오케스트레이터) ---

def handle_chat(user_input: str, session_id: str, user_id: Optional[str] = None) -> Tuple[str, str]:
    """
    사용자 입력을 받아 프로필 수집 대화 흐름을 관리하는 메인 함수입니다.
    """
    # 단계 1: 세션이 비어있으면 DB에서 기존 프로필 로드
    if user_id:
        load_user_profile_to_session(user_id, session_id)

    # 단계 2: 사용자 입력을 처리하여 세션 업데이트
    last_asked_key = _update_session_with_input(user_input, session_id)

    # 단계 3: 다음에 질문할 내용 결정
    next_question_key = _find_next_question_key(session_id)

    # 단계 4: 모든 정보가 수집된 경우
    if next_question_key is None:
        save_profile_to_db(session_id, user_id)
        #delete_session_data(session_id)
        return "모든 정보를 입력해주셔서 감사합니다. 이제 금융상품을 추천해드릴 준비가 되었습니다. 무엇을 추천해드릴까요?", session_id

    # 단계 5: 사용자가 이전 질문에 제대로 답하지 않은 경우, 재질문
    if last_asked_key == next_question_key:
        response_text = _rephrase_question_with_llm(last_asked_key, user_input)
        return response_text, session_id

    # 단계 6: 다음 질문 진행
    current = get_session_data(session_id)
    current["_last_asked_key"] = next_question_key
    set_session_data(session_id, current)
    return QUESTION_KO[next_question_key], session_id