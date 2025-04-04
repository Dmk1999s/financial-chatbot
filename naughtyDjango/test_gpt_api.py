import requests, os
from openai import OpenAI
from dotenv import load_dotenv
import json
import uuid

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=openai_api_key)

def classify_user_profile(message):
    prompt = f"""
    1. 너는 금융상품 추천 어플에 탑재된 챗봇이다. 한국어로 존댓말 대우해야 한다.
    2. 너는 다음 항목들을 알아내야 한다. 질문을 통해 항목을 이끌어 내라:
    - age: 나이 (정수)
    - risk_tolerance: 위험 허용 정도 (예: 낮음, 중간, 높음)
    - income_stability: 소득 안정성 (예: 안정적, 불안정)
    - income_sources: 소득원 (예: 아르바이트, 월급 등)
    - monthly_income: 한 달 수입 (정수, 단위는 원)
    - investment_horizon: 투자 기간 (예: 단기, 중기, 장기)
    - expected_return: 기대 수익 (예: 낮은 수익, 높은 수익)
    - expected_loss: 예상 손실 (예: 적음, 많음)
    - investment_purpose: 투자 목적 (예: 안정적인 주식 추천)

    사용자 입력: "{message}"

    응답은 반드시 아래 JSON 형식으로 출력하라:
    {{
        "age": <int>,
        "risk_tolerance": "<string>",
        "income_stability": "<string>",
        "income_sources": "<string>",
        "monthly_income": <int>,
        "investment_horizon": "<string>",
        "expected_return": "<string>",
        "expected_loss": "<string>",
        "investment_purpose": "<string>"
    }}
    """
      # 실제 API 키로 대체

    response = client.chat.completions.create(model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": prompt}],
    temperature=0)
    answer = response.choices[0].message.content
    try:
        profile = json.loads(answer)
    except json.JSONDecodeError as e:
        print("JSON 파싱 에러:", e)
        profile = {}
    return profile


def save_investment_profile(profile, user_id):
    """
    추출한 프로파일 데이터를 /chat/save_data API 엔드포인트로 전송하여 데이터베이스에 저장하는 함수.
    """
    url = "http://127.0.0.1:8000/datas/"  # 실제 서버 주소/포트에 맞게 수정
    session_id = str(uuid.uuid4())  # 예시로 UUID를 사용해 세션 ID 생성

    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "investment_profile": profile
    }

    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("속성 정보 저장 성공:", response.json())
    else:
        #print("저장 실패:", response.status_code, response.text)
        print("저장 실패:", response.status_code)


def chat_loop():
    """
    사용자로부터 입력을 받아 /api/chat/ 엔드포인트에 메시지를 반복적으로 전송하고,
    응답을 출력하며 동시에 GPT API를 사용해 입력 메시지에서 투자 관련 속성을 분류합니다.
    """
    chat_url = "http://127.0.0.1:8000/chats/"  # 챗봇 응답 API
    username = "dongminkim"

    print("=== 챗봇과 대화하기 ===")
    print("질문을 입력하세요. 종료하려면 'exit'를 입력하세요.")

    while True:
        message = input(">>> ")
        # 종료 조건
        if message.lower() == 'exit':
            print("대화를 종료합니다.")
            break

        # 사용자 입력 정리 (문제 문자 제거)
        clean_message = message.encode('utf-8', 'ignore').decode('utf-8')

        # 챗봇 대화 API 호출
        data = {
            "username": username,
            "message": clean_message
        }
        try:
            response = requests.post(chat_url, json=data)
            if response.status_code == 200:
                chat_result = response.json()
                print("챗봇 응답:", chat_result)
            else:
                print(f"챗봇 API 오류: {response.status_code}, {response.text}")
        except requests.exceptions.RequestException as e:
            print("챗봇 API 요청 중 오류가 발생했습니다:", e)
            continue

        # 사용자의 입력에서 투자 관련 속성 분류
        profile = classify_user_profile(clean_message)
        print("추출된 사용자 속성:", profile)

        # 조건에 따라, 예를 들어 회원가입 후 최초 한번 속성을 저장한다면 저장 API를 호출할 수 있음.
        # 아래는 저장 API 호출 예시.
        save_investment_profile(profile, user_id="unique_user_id")


if __name__ == "__main__":
    chat_loop()
