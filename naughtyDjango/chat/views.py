from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import ChatMessage
from openai import OpenAI
import json
import os
from .models import InvestmentProfile
from .models import ChatMessage  # 👈 모델 임포트

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_api_key)

fine_tuned_model = "ft:gpt-3.5-turbo-0125:personal::BDpYRjbn"

@csrf_exempt
def chat_with_gpt(request):
    if request.method == "POST":
        data = json.loads(request.body)
        username = data.get("username", "anonymous")  # 기본값: anonymous
        user_input = data.get("message")

        try:
            # 사용자 메시지 저장
            ChatMessage.objects.create(username=username, role="user", message=user_input)

            # GPT 응답 생성
            response = client.chat.completions.create(
                model=fine_tuned_model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": user_input}
                ]
            )
            gpt_reply = response.choices[0].message.content

            # GPT 응답 저장
            ChatMessage.objects.create(username=username, role="assistant", message=gpt_reply)

            return JsonResponse({"response": gpt_reply})

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request"}, status=400)

# 사용자별 대화 이력 조회
def get_chat_history(request, username):
    chats = ChatMessage.objects.filter(username=username).order_by('timestamp')
    data = [
        {
            "role": chat.role,
            "message": chat.message,
            "timestamp": chat.timestamp
        }
        for chat in chats
    ]
    return JsonResponse({"history": data})


@csrf_exempt
def save_investment_profile(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            session_id = data.get("session_id")
            user_id = data.get("user_id")
            investment_profile = data.get("investment_profile", {})

            # InvestmentProfile 모델에 데이터 저장
            InvestmentProfile.objects.create(
                session_id=session_id,
                user_id=user_id,
                risk_tolerance=investment_profile.get("risk_tolerance"),
                age=investment_profile.get("age"),
                income_stability=investment_profile.get("income_stability"),
                income_sources=investment_profile.get("income_sources"),
                monthly_income=investment_profile.get("monthly_income"),
                investment_horizon=investment_profile.get("investment_horizon"),
                expected_return=investment_profile.get("expected_return"),
                expected_loss=investment_profile.get("expected_loss"),
                investment_purpose=investment_profile.get("investment_purpose"),
            )
            return JsonResponse({"message": "Investment profile successfully saved"}, status=200)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)