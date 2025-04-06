import uuid
from openai import OpenAI
from dotenv import load_dotenv
import os
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from chat.models import ChatMessage, InvestmentProfile
import re
import json

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
- income_stability: 소득 안정성 (예: 안정적, 불안정)
- income_sources: 소득원 (예: 아르바이트, 월급 등)
- monthly_income: 한 달 수입 (정수, 단위는 원)
- investment_horizon: 투자 기간 (예: 단기, 중기, 장기)
- expected_return: 기대 수익 (예: 낮은 수익, 높은 수익)
- expected_loss: 예상 손실 (예: 적음, 많음)
- investment_purpose: 투자 목적 (예: 안정적인 주식 추천)
- asset_allocation_type: 자산 배분 유형 (0~4의 정수. 0: 10% 미만, 1: 10~20%, 2: 20~30%, 3: 30~40%, 4: 40% 이상)
- value_growth: 가치 또는 성장 (0~1의 정수. 0: 가치, 1: 성장)
- risk_acceptance_level: 위험 수용 수준 (1~4의 정수. 1: 무조건 투자원금 보존, 2: 이자율 수준의 수익 및 손실 기대, 3: 시장에 비례한 수익 및 손실 기대, 4: 시장수익률 초과 수익 및 손실 기대) 
- investment_concern: 투자 관련 고민 (예: 어떤 주식을 살지 모름)

4. 최종 출력은 반드시 아래 형식으로 제공해야 한다:
    {{
        "age": <int>,
        "risk_tolerance": "<string>",
        "income_stability": "<string>",
        "income_sources": "<string>",
        "monthly_income": <int>,
        "investment_horizon": "<string>",
        "expected_return": "<string>",
        "expected_loss": "<string>",
        "investment_purpose": "<string>",
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
        # 백틱 블럭 제거 (```json ~ ```)
        cleaned_text = re.sub(r"```json|```", "", text).strip()

        # 중괄호 감싸진 JSON 텍스트 추출
        match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
        if match:
            json_str = match.group()
            return json.loads(json_str)
        else:
            return {"error": "JSON 형식의 텍스트를 찾을 수 없습니다."}
    except Exception as e:
        return {"error": f"파싱 실패: {str(e)}"}

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
    try:
        InvestmentProfile.objects.create(
            user_id=user_id,
            session_id=session_id,
            risk_tolerance=parsed_data.get("risk_tolerance"),
            age=parsed_data.get("age"),
            income_stability=parsed_data.get("income_stability"),
            income_sources=parsed_data.get("income_sources"),
            monthly_income=parsed_data.get("monthly_income"),
            investment_horizon=parsed_data.get("investment_horizon"),
            expected_return=parsed_data.get("expected_return"),
            expected_loss=parsed_data.get("expected_loss"),
            investment_purpose=parsed_data.get("investment_purpose"),
        )
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

    # ✅ 응답에 특정 키워드가 포함되어 있다면 저장 시도
    if any(keyword in gpt_reply for keyword in ["추천", "모든 정보를 받았습니다"]):
        parsed = extract_json_from_response(gpt_reply)
        if parsed and user_id:
            save_profile_from_gpt(parsed, user_id, session_id)

    return gpt_reply, session_id