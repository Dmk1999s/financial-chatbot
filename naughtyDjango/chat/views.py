### chat/views.py ###
from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from chat.rag.financial_product_rag import answer_financial_question

from naughtyDjango.models import User
from openai import OpenAI
from naughtyDjango.utils.custom_response import CustomResponse
from naughtyDjango.constants.error_codes import GeneralErrorCode
from naughtyDjango.constants.success_codes import GeneralSuccessCode
from chat.gpt_service import handle_chat, get_session_id, extract_json_from_response
from chat.serializers import ChatRequestSerializer

import json

# 환경변수 로드 (OpenAI 등)
load_dotenv()

# ===== GPT 채팅 엔드포인트 =====
@swagger_auto_schema(
    operation_description="GPT와 대화합니다.",
    request_body=ChatRequestSerializer,
    method='post',
    responses={
        200: openapi.Response(
            "성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "code": openapi.Schema(type=openapi.TYPE_STRING),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "session_id": openapi.Schema(type=openapi.TYPE_STRING),
                            "response": openapi.Schema(type=openapi.TYPE_STRING),
                        },
                    ),
                },
            ),
        ),
    },
)
@api_view(["POST"])
@authentication_classes([])  # 인증 비활성화
@permission_classes([AllowAny])  # 모든 사용자 허용
def chat_with_gpt(request):
    try:
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_id = data.get("id")
        session_id = get_session_id(data)
        user_input = data.get("message")

        gpt_reply, session_id = handle_chat(user_input, session_id, user_id)
        extracted_data = extract_json_from_response(gpt_reply)

        return JsonResponse({
            "isSuccess": True,
            "code": GeneralSuccessCode.OK[0],
            "message": GeneralSuccessCode.OK[1],
            "result": {"session_id": session_id, "response": gpt_reply},
        }, status=200)

    except Exception as e:
        return JsonResponse({
            "isSuccess": False,
            "code": GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            "message": GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            "result": {"error": repr(e)},
        }, status=500)


# ===== 대화 이력 조회 엔드포인트 =====
@swagger_auto_schema(
    operation_description="사용자의 대화 이력을 조회합니다.",
    method="get",
    responses={
        200: openapi.Response(
            "성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "code": openapi.Schema(type=openapi.TYPE_STRING),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "result": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                "role": openapi.Schema(type=openapi.TYPE_STRING),
                                "message": openapi.Schema(type=openapi.TYPE_STRING),
                                "timestamp": openapi.Schema(type=openapi.TYPE_STRING, format="date-time"),
                            },
                        ),
                    ),
                },
            ),
        ),
    },
)
@api_view(["GET"])
@authentication_classes([])  # 인증 비활성화
@permission_classes([AllowAny])  # 모든 사용자 허용
def get_chat_history(request, id):
    try:
        chats = User.objects.filter(id=id).order_by("timestamp")
        data = [
            {
                "role": chat.role,
                "message": chat.message,
                "timestamp": chat.timestamp
            }
            for chat in chats
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
@swagger_auto_schema(
    operation_description="사용자의 투자 정보를 데이터베이스에 저장합니다.",
    method="post",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "session_id": openapi.Schema(type=openapi.TYPE_STRING),
            "user_id": openapi.Schema(type=openapi.TYPE_STRING),
            "investment_profile": openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "risk_tolerance": openapi.Schema(type=openapi.TYPE_STRING),
                    "age": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "income_stability": openapi.Schema(type=openapi.TYPE_STRING),
                    "income_sources": openapi.Schema(type=openapi.TYPE_STRING),
                    "monthly_income": openapi.Schema(type=openapi.TYPE_NUMBER),
                    "investment_horizon": openapi.Schema(type=openapi.TYPE_STRING),
                    "expected_return": openapi.Schema(type=openapi.TYPE_STRING),
                    "expected_loss": openapi.Schema(type=openapi.TYPE_STRING),
                    "investment_purpose": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        },
        required=["session_id", "user_id", "investment_profile"],
    ),
    responses={200: openapi.Response("성공", openapi.Schema(type=openapi.TYPE_OBJECT, properties={"message": openapi.Schema(type=openapi.TYPE_STRING)}))},
)
@api_view(["POST"])
@authentication_classes([])  # 인증 비활성화
@permission_classes([AllowAny])  # 모든 사용자 허용
def save_investment_profile(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        session_id = data.get("session_id")
        id = data.get("id")
        investment_profile = data.get("investment_profile", {})

        User.objects.create(
            session_id=session_id,
            id=id,
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


# ===== 금융상품 추천 엔드포인트 =====
@swagger_auto_schema(
    operation_description="사용자 질문에 따라 금융상품을 추천합니다.",
    method="post",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "query": openapi.Schema(type=openapi.TYPE_STRING, description="추천을 원하는 질문"),
        },
        required=["query"],
    ),
    responses={200: openapi.Response(
        "성공",
        openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "query": openapi.Schema(type=openapi.TYPE_STRING),
                "recommendation": openapi.Schema(type=openapi.TYPE_STRING),
            },
        ),
    )},
)
@api_view(["POST"])
@authentication_classes([])  # 인증 비활성화
@permission_classes([AllowAny])  # 모든 사용자 허용
def recommend_products(request):
    """
    POST /recommend/
    body: {"query": "<사용자 질문>"}
    """
    try:
        data = json.loads(request.body)
        q = data.get("query", "").strip()
        if not q:
            return JsonResponse({"error": "query 파라미터가 필요합니다."}, status=400)

        rec = answer_financial_question(q)
        return JsonResponse({"recommendation": rec}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)