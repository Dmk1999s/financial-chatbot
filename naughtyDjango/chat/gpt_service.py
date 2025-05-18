import uuid
from openai import OpenAI
from dotenv import load_dotenv
import os
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from naughtyDjango.models import User
import re
import json
from django.db import transaction


load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
fine_tuned_model = "ft:gpt-3.5-turbo-0125:personal::BDpYRjbn"
store = {}

def get_session_id(request_data):
    return request_data.get("session_id", str(uuid.uuid4()))

def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

def convert_history_to_openai_format(history):
    role_map = {"human": "user", "ai": "assistant", "system": "system"}
    return [{"role": role_map.get(msg.type, msg.type), "content": msg.content} for msg in history]
prompt = f"""
1. 너는 금융상품 추천 어플에 탑재된 챗봇이며, 이름은 '챗봇'이다.
2. 한국어로 존댓말을 사용해야 한다.
3. 사용자에게 다음 항목을 순서대로 물어봐야 한다:
- age: 나이 (정수)
- risk_tolerance: 위험 허용 정도 (예: 낮음, 중간, 높음)
- income: 연소득 (정수, 단위는 원)
- income_stability: 소득 안정성 (예: 안정적, 불안정)
- income_sources: 소득원 (예: 아르바이트, 월급 등)
- period: 투자 기간 (예: 정수, 단위는 일)
- expected_income: 기대 수익 (정수, 단위는 원)
- expected_loss: 예상 손실 (정수, 단위는 원)
- purpose: 투자 목적 (예: 안정적인 주식 추천)
- asset_allocation_type: 자산 배분 유형 (0~4의 정수. 0: 10% 미만, 1: 10~20%, 2: 20~30%, 3: 30~40%, 4: 40% 이상)
- value_growth: 가치 또는 성장 (0~1의 정수. 0: 가치, 1: 성장)
- risk_acceptance_level: 위험 수용 수준 (1~4의 정수. 1: 무조건 투자원금 보존, 2: 이자율 수준의 수익 및 손실 기대, 3: 시장에 비례한 수익 및 손실 기대, 4: 시장수익률 초과 수익 및 손실 기대) 
- investment_concern: 투자 관련 고민 (예: 어떤 주식을 살지 모름)

4. 각 항목을 사용자가 모두 응답하면 아래 JSON형식으로 모든 정보를 정리해서 보여줘야 한다.
    {{
        "age": <int>,
        "risk_tolerance": "<string>",
        "income_stability": "<string>",
        "income_sources": "<string>",
        "income": <int>,
        "period": "<int>",
        "expected_income": "<int>",
        "expected_loss": "<int>",
        "purpose": "<string>",
        "asset_allocation_type": "<int>",
        "value_growth": "<int>",
        "risk_acceptance_level": "<int>",
        "investment_concern": "<string>",
    }}
"""


def run_gpt(input_data, config):
    user_input = input_data["input"]
    system_prompt = input_data.get("system_prompt", prompt)

    session_id = config.get("configurable", {}).get("session_id")
    history = get_session_history(session_id).messages
    formatted_history = convert_history_to_openai_format(history)

    messages = [{"role": "system", "content": system_prompt}] + formatted_history + [
        {"role": "user", "content": user_input}
    ]

    response = client.chat.completions.create(
        model=fine_tuned_model,
        messages=messages
    )
    return {"output": response.choices[0].message.content}

def extract_json_from_response(text: str):
    try:
        cleaned_text = re.sub(r"```json|```", "", text).strip()

        match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
        if match:
            json_str = match.group()
            return json.loads(json_str)
        else:
            print("[⚠️] JSON 형식이 아님")
            return {}
    except Exception as e:
        return {}

# Runnable 구성
runnable = RunnableLambda(run_gpt)

with_message_history = RunnableWithMessageHistory(
    runnable,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history"
)

"""
정보를 DB에 저장하는 함수
"""
def save_profile_from_gpt(parsed_data, user_id, session_id):
    print("DEBUG: save the data")
    try:
        user = User.objects.get(email=user_id)  # 기존 유저 조회
        user.age = parsed_data.get("age")
        user.income_stability = parsed_data.get("income_stability")
        user.expected_loss = parsed_data.get("expected_loss")
        #session_id=session_id,
        user.risk_tolerance=parsed_data.get("risk_tolerance")
        user.income_source=parsed_data.get("income_sources")
        user.income=parsed_data.get("income")
        user.period=parsed_data.get("period")
        user.expected_income=parsed_data.get("expected_income")
        user.expected_loss=parsed_data.get("expected_loss")
        user.purpose=parsed_data.get("purpose")
        user.save()
        print(f"🔍 저장된 user: {user.__dict__}")
    except Exception as e:
        print(f"DB 저장 실패: {e}")


"""
views.py에 제공하는 함수
"""
def handle_chat(user_input, session_id, user_id=None):
    result = with_message_history.invoke(
        {"input": user_input},
        config={"configurable": {"session_id": session_id}}
    )
    gpt_reply = result["output"]


    if "{" in gpt_reply and "}" in gpt_reply:
        parsed = extract_json_from_response(gpt_reply)

        required_keys = [
            "age", "risk_tolerance", "income_stability", "income_sources",
            "income", "period", "expected_income", "expected_loss",
            "purpose", "asset_allocation_type", "value_growth",
            "risk_acceptance_level", "investment_concern"
        ]

        if all(k in parsed and parsed[k] is not None for k in required_keys):
            if user_id:
                save_profile_from_gpt(parsed, user_id, session_id)

    return gpt_reply, session_id