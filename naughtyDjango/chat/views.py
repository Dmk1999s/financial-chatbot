from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.decorators import api_view
from .models import ChatMessage, InvestmentProfile
from openai import OpenAI
import json
import os

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_api_key)

fine_tuned_model = "ft:gpt-3.5-turbo-0125:personal::BDpYRjbn"

# swagger설정 - 채팅
@swagger_auto_schema(
    method="post",
    operation_description="GPT와 대화합니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "username": openapi.Schema(type=openapi.TYPE_STRING, description="사용자 이름"),
            "message": openapi.Schema(type=openapi.TYPE_STRING, description="사용자의 입력 메시지"),
        },
        required=["message"],
    ),
    responses={200: openapi.Response("성공", openapi.Schema(type=openapi.TYPE_OBJECT, properties={
        "response": openapi.Schema(type=openapi.TYPE_STRING, description="GPT의 응답")
    }))},
)
@csrf_exempt
@api_view(["POST"])
def chat_with_gpt(request):
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

# 사용자별 대화 이력 조회
@swagger_auto_schema(
    method="get",
    operation_description="특정 사용자의 대화 이력을 조회합니다.",
    responses={200: openapi.Response("성공", openapi.Schema(type=openapi.TYPE_OBJECT, properties={
        "history": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "role": openapi.Schema(type=openapi.TYPE_STRING, description="메시지 역할 (user/assistant)"),
                "message": openapi.Schema(type=openapi.TYPE_STRING, description="대화 메시지 내용"),
                "timestamp": openapi.Schema(type=openapi.TYPE_STRING, description="대화 발생 시간"),
            }
        ))
    }))},
)
@api_view(["GET"])
def get_chat_history(request, username):
    chats = ChatMessage.objects.filter(username=username).order_by("timestamp")
    data = [
        {
            "role": chat.role,
            "message": chat.message,
            "timestamp": chat.timestamp
        }
        for chat in chats
    ]
    return JsonResponse({"history": data})

# 투자 프로필 저장
@swagger_auto_schema(
    method="post",
    operation_description="사용자의 투자 프로필을 저장합니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "session_id": openapi.Schema(type=openapi.TYPE_STRING, description="세션 ID"),
            "user_id": openapi.Schema(type=openapi.TYPE_STRING, description="사용자 ID"),
            "investment_profile": openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "risk_tolerance": openapi.Schema(type=openapi.TYPE_STRING, description="위험 감수 성향"),
                    "age": openapi.Schema(type=openapi.TYPE_INTEGER, description="사용자 나이"),
                    "income_stability": openapi.Schema(type=openapi.TYPE_STRING, description="소득 안정성"),
                    "income_sources": openapi.Schema(type=openapi.TYPE_STRING, description="소득 원천"),
                    "monthly_income": openapi.Schema(type=openapi.TYPE_NUMBER, description="월 소득"),
                    "investment_horizon": openapi.Schema(type=openapi.TYPE_STRING, description="투자 기간"),
                    "expected_return": openapi.Schema(type=openapi.TYPE_STRING, description="예상 수익률"),
                    "expected_loss": openapi.Schema(type=openapi.TYPE_STRING, description="예상 손실"),
                    "investment_purpose": openapi.Schema(type=openapi.TYPE_STRING, description="투자 목적"),
                }
            ),
        },
        required=["session_id", "user_id", "investment_profile"],
    ),
    responses={200: openapi.Response("성공", openapi.Schema(type=openapi.TYPE_OBJECT, properties={
        "message": openapi.Schema(type=openapi.TYPE_STRING, description="성공 메시지")
    }))},
)
@csrf_exempt
@api_view(["POST"])
def save_investment_profile(request):
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
