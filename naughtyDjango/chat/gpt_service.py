import uuid
from openai import OpenAI
from dotenv import load_dotenv
import os
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from main.models import User
from functools import partial
import re
import ast
import json
import openai


load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
fine_tuned_model = "ft:gpt-3.5-turbo-0125:personal::BDpYRjbn"
store = {}
SESSION_TEMP_STORE = {}  # session_id: dict

REQUIRED_KEYS = {
    "age", "risk_tolerance", "income_stability", "income_sources",
    "income", "period", "expected_income", "expected_loss",
    "purpose", "value_growth",
    "risk_acceptance_level", "investment_concern"
}

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

4. 각 항목을 사용자가 모두 응답하면 "이제 금융상품을 추천해줄게요!" 라는 말을 하며 대화를 끝낸다.
"""

def get_session_id(request_data):
    return request_data.get("session_id", str(uuid.uuid4()))

def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

def convert_history_to_openai_format(history):
    role_map = {"human": "user", "ai": "assistant", "system": "system"}
    return [{"role": role_map.get(msg.type, msg.type), "content": msg.content} for msg in history]

def has_required_keys(parsed: dict) -> bool:
    return all(k in parsed and parsed[k] is not None for k in REQUIRED_KEYS)

def run_gpt(input_data, config, ai_model):
    user_input = input_data["input"]
    session_id = config.get("configurable", {}).get("session_id")

    # 현재 누락된 필드 추적
    missing_keys = []
    if session_id in SESSION_TEMP_STORE:
        current_data = SESSION_TEMP_STORE[session_id]
        missing_keys = [key for key in REQUIRED_KEYS if key not in current_data or current_data[key] is None]

    # 기본 프롬프트 + 누락된 키에 대한 질문 유도
    base_prompt = input_data.get("system_prompt", prompt)
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

    response = client.chat.completions.create(
        model=ai_model,
        messages=messages,
        temperature=0.0,
    )
    return {"output": response.choices[0].message.content}


def call_gpt_model(prompt: str, session_id: str) -> str:
    input_data = {
        "input": prompt,
        "system_prompt": (
                "너는 오직 JSON 객체만 반환하는 파서야.\n"
                "절대 질문이나 설명 없이 JSON만 응답해. 이 외의 텍스트는 허용되지 않아.\n"
                "다음은 JSON 예시야:\n"
                "{\n"
                "  \"age\": 25,\n"
                "  \"income\": 4000000,\n"
                "  \"income_sources\": \"아르바이트\",\n"
                "  \"income_stability\": \"불안정\",\n"
                "  \"period\": 30,\n"
                "  \"expected_income\": 300000,\n"
                "  \"expected_loss\": 100000,\n"
                "  \"purpose\": \"단기 수익\",\n"
                "  \"asset_allocation_type\": 2,\n"
                "  \"value_growth\": 1,\n"
                "  \"risk_acceptance_level\": 3,\n"
                "  \"investment_concern\": \"무슨 주식을 사야 할지 모르겠어요\",\n"
                "  \"risk_tolerance\": \"중간\"\n"
                "}\n"
                "모든 항목이 없을 경우에는 반드시 빈 객체인 `{}` 만 출력해.\n"
                "JSON 외의 문장이 한 줄이라도 있으면 오류야. 반드시 지켜.\n"
        )
    }

    config = {
        "configurable": {
            "session_id": session_id
        }
    }

    return run_gpt(input_data, config, "gpt-3.5-turbo")["output"]

def extract_json_from_response(response_text: str) -> dict:
    try:
        # 중괄호로 둘러싸인 JSON 블록 추출
        json_text = re.search(r'{.*}', response_text, re.DOTALL).group()
        print(f"❗ JSON 추출 결과: {json.loads(json_text)}")
        return json.loads(json_text)
    except Exception as e:
        print(f"❗ JSON 추출 실패: {e}")
        return {}

def extract_fields_from_natural_response(response_text: str, session_id: str) -> dict:
    gpt_raw = call_gpt_model(response_text, session_id)
    print("📥 GPT raw repr:", repr(gpt_raw))
    print("📥 GPT 응답:", gpt_raw)

    try:
        match = re.search(r'\{.*\}', gpt_raw, re.DOTALL)
        if match:
            json_text = match.group().strip()
            parsed = json.loads(json_text)
            print(f"✅ 파싱된 JSON: {parsed}")
            (print(type(parsed)))
            return parsed
        else:
            print("❗ JSON 형식이 아님. 응답 없음으로 처리합니다.")
            return {}
    except Exception as e:
        print(f"❗ 예외 발생: {e}")
        return {}

run_gpt_with_model = partial(run_gpt, ai_model=fine_tuned_model)
# Runnable 구성
runnable = RunnableLambda(run_gpt_with_model)

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

    extracted_fields = extract_fields_from_natural_response(gpt_reply, session_id)

    if session_id not in SESSION_TEMP_STORE:
        SESSION_TEMP_STORE[session_id] = {}

    # 누적 저장 (None 값 + 오타 키 제거)
    valid_fields = {
        k: v for k, v in extracted_fields.items()
        if k in REQUIRED_KEYS and v is not None
    }
    SESSION_TEMP_STORE[session_id].update(valid_fields)

    current_data = SESSION_TEMP_STORE[session_id]

    # 모든 필드가 모이면 저장
    if REQUIRED_KEYS.issubset(current_data.keys()):
        if user_id:
            save_profile_from_gpt(current_data, user_id, session_id)
        del SESSION_TEMP_STORE[session_id]  # 저장 후 초기화

    return gpt_reply, session_id