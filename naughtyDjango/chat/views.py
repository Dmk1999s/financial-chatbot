from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.decorators import api_view
from chat.models import ChatMessage, InvestmentProfile
from openai import OpenAI
from naughtyDjango.utils.custom_response import CustomResponse
from naughtyDjango.constants.error_codes import GeneralErrorCode
from naughtyDjango.constants.success_codes import GeneralSuccessCode
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from chat.gpt_service import handle_chat, get_session_id, extract_json_from_response
import uuid
import json

print("✅ DEBUG: InvestmentProfile =", InvestmentProfile)

# swagger설정 - 채팅
@swagger_auto_schema(
    method="post",
    operation_description="GPT와 대화합니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "username": openapi.Schema(type=openapi.TYPE_STRING, description="사용자 이름"),
            "session_id": openapi.Schema(type=openapi.TYPE_STRING, description="세션 아이디"),
            "message": openapi.Schema(type=openapi.TYPE_STRING, description="사용자의 입력 메시지"),
        },
        required=["message"],
    ),
    responses={
        200: openapi.Response(
            "성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, description="성공 여부"),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, description="응답 코드"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, description="응답 메시지"),
                "result": openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "session_id": openapi.Schema(type=openapi.TYPE_STRING, description="세션 ID"),
                        "response": openapi.Schema(type=openapi.TYPE_STRING, description="GPT의 응답"),},),},))})

@api_view(["POST"])
@csrf_exempt
def chat_with_gpt(request):
    try:
        data = json.loads(request.body)
        user_input = data.get("message")
        user_id = data.get("user_id")
        session_id = get_session_id(data)

        gpt_reply, session_id = handle_chat(user_input, session_id, user_id)

        # GPT 응답에서 JSON 파싱 시도
        extracted_data = extract_json_from_response(gpt_reply)

        return JsonResponse({
            "isSuccess": True,
            "code": "OK",
            "message": "대화 성공",
            "result": {
                "session_id": session_id,
                "response": gpt_reply
            }
        }, status=200)

    except Exception as e:
        return JsonResponse({
            "isSuccess": False,
            "code": "COMMON500",
            "message": "서버 오류 발생",
            "result": {"error": str(e)}
        }, status=500)

# 사용자별 대화 이력 조회
@swagger_auto_schema(
    method="get",
    operation_description="사용자의 대화 이력을 조회합니다.",
    responses={200: openapi.Response("성공", openapi.Schema(type=openapi.TYPE_OBJECT, properties={
        "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, description="성공 여부"),
        "code": openapi.Schema(type=openapi.TYPE_STRING, description="응답 코드"),
        "message": openapi.Schema(type=openapi.TYPE_STRING, description="응답 메시지"),
        "result": openapi.Schema(
            type=openapi.TYPE_ARRAY,
            description="채팅 내역 리스트",
            items=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "role": openapi.Schema(type=openapi.TYPE_STRING, description="메시지의 역할 (user/assistant)"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, description="채팅 메시지 내용"),
                    "timestamp": openapi.Schema(type=openapi.TYPE_STRING, format="date-time", description="메시지 타임스탬프"),
                })),})),

            500: openapi.Response(
                "서버 오류",
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, description="성공 여부 (항상 false)"),
                        "code": openapi.Schema(type=openapi.TYPE_STRING, description="에러 코드"),
                        "message": openapi.Schema(type=openapi.TYPE_STRING, description="에러 메시지"),
                        "result": openapi.Schema(type=openapi.TYPE_STRING, description="에러 발생 시 결과 없음"),
})),})
@csrf_exempt
@api_view(["GET"])
def get_chat_history(request, username):
    try:
        chats = ChatMessage.objects.filter(username=username).order_by("timestamp")
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
            result={"response": gpt_reply},
            status=GeneralSuccessCode.OK[2]
        )

    except Exception as e:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            result={"error": str(e)},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2]
        )


# 투자 프로필 저장
@swagger_auto_schema(
    method="post",
    operation_description="사용자의 투자 정보를 데이터베이스에 저장합니다.",
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

        InvestmentProfile.objects.create(
            #session_id=session_id,
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
        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result={"response": GeneralSuccessCode.OK[1]},
            status=GeneralSuccessCode.OK[2]
        )

    except Exception as e:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            result={"error": str(e)},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2]
        )