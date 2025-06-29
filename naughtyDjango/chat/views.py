# chat/views.py
from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.decorators import api_view

from chat.rag.financial_product_rag import answer_financial_question
from chat.models import ChatMessage, InvestmentProfile

from main.models import User
from openai import OpenAI
from main.utils.custom_response import CustomResponse
from main.constants.error_codes import GeneralErrorCode
from main.constants.success_codes import GeneralSuccessCode
from chat.gpt_service import handle_chat, get_session_id
from chat.serializers import ChatRequestSerializer, InvestmentProfileSerializer, SaveInvestmentProfileRequestSerializer, RecommendProductRequestSerializer

import json

load_dotenv()

# ===== GPT 채팅 엔드포인트 =====
@swagger_auto_schema(
    method="post",
    operation_description="GPT와 대화합니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "username":     openapi.Schema(type=openapi.TYPE_STRING),
            "product_type": openapi.Schema(type=openapi.TYPE_STRING),
            "session_id":   openapi.Schema(type=openapi.TYPE_STRING),
            "message":      openapi.Schema(type=openapi.TYPE_STRING),
        },
        required=["message"],
    ),
    responses={200: openapi.Response(
        "성공",
        openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                "code":      openapi.Schema(type=openapi.TYPE_STRING),
                "message":   openapi.Schema(type=openapi.TYPE_STRING),
                "result": openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "session_id": openapi.Schema(type=openapi.TYPE_STRING),
                        "response":   openapi.Schema(type=openapi.TYPE_STRING),
                    },
                ),
            },
        ),
    )},
)
@api_view(["POST"])
@csrf_exempt
def chat_with_gpt(request):
    try:
        data          = json.loads(request.body)
        username      = data.get("username", "")
        product_type  = data.get("product_type", "")
        session_id    = get_session_id(data)
        user_message  = data.get("message")

        # (1) User 메시지 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="user",
            message=user_message,
        )

        # (2) GPT 호출
        gpt_reply, session_id = handle_chat(user_message, session_id, user_id=username)

        # (3) Assistant 메시지 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="assistant",
            message=gpt_reply,
        )

        return JsonResponse(
            {
                "isSuccess": True,
                "code":      GeneralSuccessCode.OK[0],
                "message":   GeneralSuccessCode.OK[1],
                "result":    {"session_id": session_id, "response": gpt_reply},
            },
            status=200
        )

    except Exception as e:
        return JsonResponse(
            {
                "isSuccess": False,
                "code":      GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
                "message":   str(e),
                "result":    {"error": str(e)},
            },
            status=500
        )


# ===== 대화 이력 조회 엔드포인트 =====
@swagger_auto_schema(
    method="get",
    operation_description="사용자의 대화 이력을 조회합니다.",
    responses={200: openapi.Response(
        "성공",
        openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                "code":      openapi.Schema(type=openapi.TYPE_STRING),
                "message":   openapi.Schema(type=openapi.TYPE_STRING),
                "result": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "role":         openapi.Schema(type=openapi.TYPE_STRING),
                            "message":      openapi.Schema(type=openapi.TYPE_STRING),
                            "timestamp":    openapi.Schema(type=openapi.TYPE_STRING, format="date-time"),
                            "product_type": openapi.Schema(type=openapi.TYPE_STRING),
                        },
                    ),
                ),
            },
        ),
    )},
)
@api_view(["GET"])
@csrf_exempt
def get_chat_history(request, username):
    try:
        chats = ChatMessage.objects.filter(username=username).order_by("timestamp")
        history = [
            {
                "role":         c.role,
                "message":      c.message,
                "timestamp":    c.timestamp,
                "product_type": c.product_type,
            }
            for c in chats
        ]
        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result=history,
            status=GeneralSuccessCode.OK[2],
        )
    except Exception as e:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            result={"error": str(e)},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2],
        )


# ===== 투자 프로필 저장 엔드포인트 =====
# (변경 없음)


# ===== 금융상품 추천 엔드포인트 =====
@swagger_auto_schema(
    method="post",
    operation_description="사용자의 투자 정보를 데이터베이스에 저장합니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "session_id": openapi.Schema(type=openapi.TYPE_STRING),
            "user_id":    openapi.Schema(type=openapi.TYPE_STRING),
            "investment_profile": openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "risk_tolerance": openapi.Schema(type=openapi.TYPE_STRING),
                    "age":            openapi.Schema(type=openapi.TYPE_INTEGER),
                    "income_stability": openapi.Schema(type=openapi.TYPE_STRING),
                    "income_sources":   openapi.Schema(type=openapi.TYPE_STRING),
                    "monthly_income":   openapi.Schema(type=openapi.TYPE_NUMBER),
                    "investment_horizon": openapi.Schema(type=openapi.TYPE_STRING),
                    "expected_return":   openapi.Schema(type=openapi.TYPE_STRING),
                    "expected_loss":     openapi.Schema(type=openapi.TYPE_STRING),
                    "investment_purpose": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        },
        required=["session_id", "user_id", "investment_profile"],
    ),
    responses={200: openapi.Response("성공", openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={"message": openapi.Schema(type=openapi.TYPE_STRING)}
    ))},
)
@api_view(["POST"])
def recommend_products(request):
    try:
        data          = json.loads(request.body)
        username      = data.get("username", "")
        product_type  = data.get("product_type", "")
        session_id    = data.get("session_id", "")
        q             = data.get("query", "").strip()
        if not q:
            return JsonResponse({"error": "query 파라미터가 필요합니다."}, status=400)

        # (1) User 쿼리도 ChatMessage로 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="user",
            message=q,
        )

        # (2) RAG 호출
        rec = answer_financial_question(q)

        # (3) Assistant 추천 응답도 ChatMessage로 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="assistant",
            message=rec,
        )

        return JsonResponse({"query": q, "recommendation": rec}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@api_view(["POST"])
@csrf_exempt
def save_investment_profile(request):
    try:
        data    = json.loads(request.body)
        profile = data.get("investment_profile", {})
        InvestmentProfile.objects.create(
            user_id=data.get("user_id"),
            risk_tolerance=profile.get("risk_tolerance"),
            age=profile.get("age"),
            income_stability=profile.get("income_stability"),
            income_sources=profile.get("income_sources"),
            monthly_income=profile.get("monthly_income"),
            investment_horizon=profile.get("investment_horizon"),
            expected_return=profile.get("expected_return"),
            expected_loss=profile.get("expected_loss"),
            investment_purpose=profile.get("investment_purpose"),
        )
        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result={"message": GeneralSuccessCode.OK[1]},
            status=GeneralSuccessCode.OK[2],
        )
    except Exception as e:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            result={"error": str(e)},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2],
        )