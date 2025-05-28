### chat/views.py ###
from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from chat.rag.financial_product_rag import answer_financial_question
from chat.models import ChatMessage, InvestmentProfile

from main.models import User
from openai import OpenAI
from main.utils.custom_response import CustomResponse
from main.constants.error_codes import GeneralErrorCode
from main.constants.success_codes import GeneralSuccessCode
from chat.gpt_service import handle_chat, get_session_id, extract_json_from_response
from chat.serializers import ChatRequestSerializer, InvestmentProfileSerializer, SaveInvestmentProfileRequestSerializer, RecommendProductRequestSerializer

import json

load_dotenv()

# ===== GPT 채팅 엔드포인트 =====
@swagger_auto_schema(
    operation_description="GPT와 대화합니다. - ✅ 구현 완료!",
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
@authentication_classes([])    # 인증 비활성화
@permission_classes([AllowAny])   # 모든 사용자 허용
def chat_with_gpt(request):
    try:
        # 1) 입력 검증: ChatRequestSerializer 사용
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2) 주요 파라미터 추출
        username     = data.get("username")
        product_type = data.get("product_type")
        session_id   = get_session_id(data)
        user_input   = data.get("message")

        # 3) User 메시지 저장 (feature 로직)
        ChatMessage.objects.create(
            session_id    = session_id,
            username      = username,
            product_type  = product_type,
            role          = "user",
            message       = user_input,
        )

        # 4) GPT 호출
        gpt_reply, session_id = handle_chat(user_input, session_id, user_id=username)

        # 5) Assistant 메시지 저장 (feature 로직)
        ChatMessage.objects.create(
            session_id    = session_id,
            username      = username,
            product_type  = product_type,
            role          = "assistant",
            message       = gpt_reply,
        )

        # 6) 응답 반환
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
                "message":   GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
                "result":    {"error": str(e)},
            },
            status=500
        )



# ===== 대화 이력 조회 엔드포인트 =====
@swagger_auto_schema(
    operation_description="사용자의 대화 이력을 조회합니다. - ❎ 보완 필요",
    method="get",
    responses={
        200: openapi.Response(
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
        ),
    },
)
@api_view(["GET"])
@csrf_exempt
@authentication_classes([])  # 인증 비활성화
@permission_classes([AllowAny])  # 모든 사용자 허용
def get_chat_history(request, id):
    try:
        chats = ChatMessage.objects.filter(username=id).order_by("timestamp")
        history = [
            {
                "role": c.role,
                "message": c.message,
                "timestamp": c.timestamp,
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
@swagger_auto_schema(
    operation_description="사용자의 투자 정보를 데이터베이스에 저장합니다. - ❎ 보완 필요",
    method="post",
    request_body=SaveInvestmentProfileRequestSerializer,
    responses={
        200: openapi.Response(
            "성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(type=openapi.TYPE_STRING)
                }
            )
        )
    },
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
@authentication_classes([])       # 인증 비활성화 (main 기준)
@permission_classes([AllowAny])   # 모든 사용자 허용 (main 기준)
@csrf_exempt
def save_investment_profile(request):
    try:
        # 1) 입력 검증
        serializer = SaveInvestmentProfileRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2) payload 언팩
        session_id = data["session_id"]
        user_id    = data["user_id"]
        profile    = data["investment_profile"]

        # 3) InvestmentProfile 모델에 저장 (feature 기준)
        InvestmentProfile.objects.create(
            session_id=session_id,
            user_id=user_id,
            risk_tolerance       = profile.get("risk_tolerance"),
            age                  = profile.get("age"),
            income_stability     = profile.get("income_stability"),
            income_sources       = profile.get("income_sources"),
            monthly_income       = profile.get("monthly_income"),
            investment_horizon   = profile.get("investment_horizon"),
            expected_return      = profile.get("expected_return"),
            expected_loss        = profile.get("expected_loss"),
            investment_purpose   = profile.get("investment_purpose"),
            # asset_allocation_type, value_growth, risk_acceptance_level, investment_concern
            # 등 추가 필드가 필요하면 이곳에 채워 주세요.
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
    operation_description="사용자 질문에 따라 금융상품을 추천합니다. - ❎ 보완 필요",
    method="post",
    request_body=RecommendProductRequestSerializer,
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
        serializer = RecommendProductRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"].strip()

        rec = answer_financial_question(query)
        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result={"recommendation": rec},
            status=GeneralSuccessCode.OK[2],
        )

    except Exception as e:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            result={"error": repr(e)},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2],
        )