from openai import OpenAI
from dotenv import load_dotenv
import os
from functools import partial
from typing import Optional
from chat.gpt.session_store import (
    get_session_data,
    set_session_data,
    delete_session_data,
    get_conflict_pending,
    set_conflict_pending_cache,
    pop_conflict_pending,
)
from chat.constants.fields import REQUIRED_KEYS, REQUIRED_KEYS_ORDER, QUESTION_KO
from chat.gpt.prompts import finetune_prompt, gpt_prompt
from chat.gpt.parser import extract_json_from_response, extract_fields_from_natural_response
from chat.gpt.flow import (
    get_session_history,
    convert_history_to_openai_format,
    run_gpt,
    with_message_history,
    save_profile_from_gpt,
)

load_dotenv()

from chat.gpt.openai_client import client
fine_tuned_model = "ft:gpt-3.5-turbo-0125:personal::BDpYRjbn"
store = {}

load_dotenv()

def get_session_id(request_data):
    session_id = request_data.get("session_id")
    if not session_id:
        # 처음 대화하는 user에 대해서 세션 발급
        username = request_data.get("username", "anonymous")
        session_id = f"new_{username}_{hash(str(request_data)) % 10000}"
    return session_id


def call_gpt_model(prompt: str, session_id: str) -> str:
    input_data = {
        "input": prompt,
        "system_prompt": gpt_prompt
    }

    config = {
        "configurable": {
            "session_id": session_id
        }
    }

    return _run_gpt_parser(input_data, config, "gpt-3.5-turbo")["output"]

def _run_gpt_parser(input_data, config, model):
    messages = [
        {"role": "system", "content": input_data["system_prompt"]},
        {"role": "user", "content": input_data["input"]}
    ]
    response = client.create_completion(
        messages=messages,
        model=model,
        temperature=0.0,
    )
    return {"output": response.choices[0].message.content}

run_gpt_with_model = partial(run_gpt, ai_model=fine_tuned_model)

# ==========================================================
# ✅ 일반 대화 처리를 위한 함수 추가
# ==========================================================
def handle_chitchat(query: str) -> str:
    """
    RAG 검색 없이 일반적인 대화를 처리합니다.
    """
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "당신은 친절한 금융 상담 챗봇입니다."},
            {"role": "user", "content": query}
        ],
        temperature=0.7,
        max_tokens=500
    )
    return response.choices[0].message.content