import uuid
from openai import OpenAI
from dotenv import load_dotenv
import os
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from django.core.cache import cache
from django.contrib.auth.models import User
import re
import ast
import json
from functools import partial, lru_cache

load_dotenv()

# Optimized OpenAI client with caching
class OptimizedOpenAIClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            max_retries=2,
            timeout=30.0
        )
    
    def create_completion(self, messages, model="gpt-3.5-turbo", **kwargs):
        # Check cache first for repeated queries
        prompt_str = str(messages)
        cache_key = f"gpt_response_{hash(prompt_str)}"
        cached = cache.get(cache_key)
        if cached:
            return cached
            
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )
        
        # Cache for 5 minutes
        cache.set(cache_key, response, 300)
        return response

client = OptimizedOpenAIClient()
fine_tuned_model = "ft:gpt-3.5-turbo-0125:personal::BDpYRjbn"
store = {}
SESSION_TEMP_STORE = {}
REQUIRED_KEYS = {
    "age", "risk_tolerance", "income_stability", "income_sources",
    "income", "period", "expected_income", "expected_loss",
    "purpose", "value_growth",
    "risk_acceptance_level", "investment_concern"
}

finetune_prompt = f"""
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

gpt_prompt = """
너는 오직 JSON 객체만 반환하는 파서야.
절대 질문이나 대답 없이 JSON만 응답해. 이 외의 텍스트는 허용되지 않아.
다음은 JSON 예시야:
{
  "age": 25,
  "income": 4000000,
  "income_sources": "아르바이트",
  "income_stability": "불안정",
  "period": 30,
  "expected_income": 300000,
  "expected_loss": 100000,
  "purpose": "단기 수익",
  "asset_allocation_type": 2,
  "value_growth": 1,
  "risk_acceptance_level": 3,
  "investment_concern": "무슨 주식을 사야 할지 모르겠어요",
  "risk_tolerance": "중간"
}
모든 항목이 없을 경우에는 반드시 빈 객체만 출력해: {}
JSON 외의 문장이 한 줄이라도 있으면 오류야. 반드시 지켜.
"""

@lru_cache(maxsize=1000)
def get_cached_session_id():
    return str(uuid.uuid4())

def get_session_id(request_data):
    session_id = request_data.get("session_id")
    if not session_id:
        # Use a deterministic session ID for first-time users to enable caching
        username = request_data.get("username", "anonymous")
        session_id = f"new_{username}_{hash(str(request_data)) % 10000}"
    return session_id

def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

def convert_history_to_openai_format(history):
    role_map = {"human": "user", "ai": "assistant", "system": "system"}
    return [{"role": role_map.get(msg.type, msg.type), "content": msg.content} for msg in history]

def check_conflict(current_data, new_fields):
    conflicting_fields = []
    for key, new_value in new_fields.items():
        if key in current_data and current_data[key] != new_value:
            conflicting_fields.append((key, current_data[key], new_value))
    return conflicting_fields




def extract_json_from_response(text: str):
    try:
        # 백틱 블럭 제거 (```json ~ ```)
        cleaned_text = re.sub(r"```json|```", "", text).strip()

        # 중괄호 감싸진 JSON 텍스트 추출
        match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        else:
            print("❗ JSON 형식이 아님. 응답 없음으로 처리합니다.")
            return {}
    except Exception:
        # 파싱 중 에러나면 빈 dict 반환
        return {}


def extract_fields_from_natural_response(response_text: str, session_id: str) -> dict:
    # Skip extraction for new sessions to avoid slow GPT-4 calls
    if session_id not in SESSION_TEMP_STORE:
        return {}
    
    # Use faster regex patterns for common cases
    fields = {}
    text_lower = response_text.lower()
    
    # Age extraction
    age_match = re.search(r'(\d+)살|나이.*?(\d+)|age.*?(\d+)', text_lower)
    if age_match:
        fields['age'] = int(age_match.group(1) or age_match.group(2) or age_match.group(3))
    
    # Income extraction
    income_match = re.search(r'(\d+)만원|월급.*?(\d+)|수입.*?(\d+)', text_lower)
    if income_match:
        fields['monthly_income'] = int(income_match.group(1) or income_match.group(2) or income_match.group(3)) * 10000
    
    # Risk tolerance
    if any(word in text_lower for word in ['안전', '보수적', '낮음']):
        fields['risk_tolerance'] = '낮음'
    elif any(word in text_lower for word in ['적극적', '높음', '공격적']):
        fields['risk_tolerance'] = '높음'
    elif '중간' in text_lower:
        fields['risk_tolerance'] = '중간'
    
    return fields

def run_gpt(input_data, config, ai_model):
    user_input = input_data["input"]
    session_id = config.get("configurable", {}).get("session_id")
    user_id = config.get("configurable", {}).get("user_id")

    if user_input.strip() in ["네", "아니오"] and "conflict_pending" in SESSION_TEMP_STORE:
        pending = SESSION_TEMP_STORE.pop("conflict_pending")
        if user_input.strip() == "네":
            # 충돌 항목을 저장
            SESSION_TEMP_STORE[session_id].update(pending)
            return {"output": "프로필이 성공적으로 업데이트되었습니다. 계속 진행할게요."}
        else:
            return {"output": "기존 프로필 정보를 유지합니다. 계속 진행할게요."}

    current_data = SESSION_TEMP_STORE.get(session_id, {})
    new_fields = extract_fields_from_natural_response(user_input, session_id)

    # 프로필 충돌 확인
    conflicts = check_conflict(current_data, new_fields)
    if conflicts:
        # 사용자에게 업데이트 여부 질문 유도
        conflict_messages = "\n".join(
            f"- {k}: 기존 '{old}' vs 입력 '{new}'"
            for k, old, new in conflicts
        )
        clarification = (
            f"입력하신 정보가 기존 프로필과 다릅니다:\n{conflict_messages}\n"
            "프로필을 업데이트할까요? '네' 또는 '아니오'로 답해주세요."
        )
        SESSION_TEMP_STORE["conflict_pending"] = {
            k: new for k, _, new in conflicts
        }
        return {"output": clarification}

    # 현재 누락된 필드 추적
    missing_keys = [key for key in REQUIRED_KEYS if key not in current_data or current_data[key] is None]

    # 기본 프롬프트 + 누락된 키에 대한 질문 유도
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
        max_tokens=150  # Limit response length for faster processing
    )
    return {"output": response.choices[0].message.content}


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
        session_id=session_id,
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
    # Fast path for new sessions - use lighter processing
    if session_id.startswith("new_"):
        # Initialize session store
        if session_id not in SESSION_TEMP_STORE:
            SESSION_TEMP_STORE[session_id] = {}
        
        # Use simplified prompt for first interaction
        simple_prompt = "안녕하세요! 투자 상담을 도와드릴게요. 먼저 나이를 알려주세요."
        
        # Extract basic info from user input
        extracted_fields = extract_fields_from_natural_response(user_input, session_id)
        valid_fields = {
            k: v for k, v in extracted_fields.items()
            if k in REQUIRED_KEYS and v is not None
        }
        SESSION_TEMP_STORE[session_id].update(valid_fields)
        
        return simple_prompt, session_id
    
    # Regular processing for existing sessions
    result = with_message_history.invoke(
        {"input": user_input},
        config={"configurable": {"session_id": session_id}}
    )

    gpt_reply = result["output"]
    extracted_fields = extract_fields_from_natural_response(gpt_reply, session_id)

    if session_id not in SESSION_TEMP_STORE:
        SESSION_TEMP_STORE[session_id] = {}

    valid_fields = {
        k: v for k, v in extracted_fields.items()
        if k in REQUIRED_KEYS and v is not None
    }
    SESSION_TEMP_STORE[session_id].update(valid_fields)

    current_data = SESSION_TEMP_STORE[session_id]

    if REQUIRED_KEYS.issubset(current_data.keys()):
        if user_id:
            save_profile_from_gpt(current_data, user_id, session_id)
        del SESSION_TEMP_STORE[session_id]

    return gpt_reply, session_id
