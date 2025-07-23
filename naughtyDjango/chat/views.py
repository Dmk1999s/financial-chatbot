# chat/views.py
import os

from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from openai import OpenAI
from rest_framework.decorators import api_view, permission_classes
import io
from django.core.management import call_command
from rest_framework.decorators import api_view
from rest_framework.permissions import AllowAny

from chat.gpt_service import extract_json_from_response
from chat.models import ChatMessage, InvestmentProfile

from chat.opensearch_client import search_financial_products
from chat.rag.financial_product_rag import answer_financial_question
from chat.models import ChatMessage, InvestmentProfile
from main.utils.custom_response import CustomResponse
from main.constants.error_codes import GeneralErrorCode
from main.constants.success_codes import GeneralSuccessCode

from chat.gpt_service import handle_chat, get_session_id
from chat.serializers import ChatRequestSerializer, InvestmentProfileSerializer, SaveInvestmentProfileRequestSerializer, RecommendProductRequestSerializer

import json

load_dotenv()

# ── 변경 감지용 프롬프트 ──
DETECTION_SYSTEM = """
당신은 '투자 프로필 변경 트리거'를 감지하는 어시스턴트입니다.
사용자 발화를 보고, 아래 필드 중 변경 의도가 있는지 JSON으로 반환하세요.
필드: age, monthly_income, risk_tolerance, income_stability,
income_sources, investment_horizon, expected_return,
expected_loss, investment_purpose, asset_allocation_type,
value_growth, risk_acceptance_level, investment_concern

예시) {"field":"monthly_income","value":4500000}

변경 의도가 없으면 {} 만 반환하세요.
"""


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
@permission_classes([AllowAny])
@csrf_exempt
def chat_with_gpt(request):
    """
    1) 사용자 메시지 저장
    2) 변경감지 → 제안 → 확정
    3) 일반 챗 흐름(handle_chat)
    """
    try:
        body       = json.loads(request.body)
        username   = body.get("username", "")
        session_id = body.get("session_id") or get_session_id(body)
        InvestmentProfile.objects.get_or_create(
            session_id=session_id,
            user_id=username,
            defaults={} # 필요한 경우에 기본값 지정 가능
        )
        message    = (body.get("message") or "").strip()
        if not message:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.BAD_REQUEST[0],
                message="`message` 파라미터가 필요합니다.",
                result={},
                status=GeneralErrorCode.BAD_REQUEST[2],
            )

        # 1) 사용자 메시지 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=body.get("product_type", ""),
            role="user",
            message=message,
        )

        # 2) 변경 확정 처리 (프론트가 update_confirm 플래그로 전송할 때)
        if body.get("update_confirm"):
            field = body.get("field")
            value = body.get("value")
            if field and value is not None:
                InvestmentProfile.objects.update_or_create(
                    session_id=session_id,
                    user_id=username,
                    defaults={field: value}
                )
                confirm_msg = f"{field} 정보를 {value}으로 업데이트했습니다."
                ChatMessage.objects.create(
                    session_id=session_id,
                    username=username,
                    product_type=body.get("product_type", ""),
                    role="assistant",
                    message=confirm_msg,
                )
                return CustomResponse(
                    is_success=True,
                    code=GeneralSuccessCode.OK[0],
                    message=GeneralSuccessCode.OK[1],
                    result={"response": confirm_msg},
                    status=GeneralSuccessCode.OK[2],
                )

        # 3) 변경 감지 호출
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        detect_resp = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": DETECTION_SYSTEM},
                {"role": "user",   "content": message},
            ],
            temperature=0
        )
        trigger = extract_json_from_response(detect_resp.choices[0].message.content)

        if isinstance(trigger, dict) and trigger:
            field = trigger.get("field")
            value = trigger.get("value")
            if field and value is not None:
                # 사용자에게 제안할 메시지 구성
                label_map = {
                    "risk_tolerance": "위험 허용 정도",
                    "age": "나이",
                    "income_stability": "소득 안정성",
                    "income_sources": "소득원",
                    "monthly_income": "월 수입",
                    "investment_horizon": "투자 기간",
                    "expected_return": "기대 수익",
                    "expected_loss": "예상 손실",
                    "investment_purpose": "투자 목적",
                    "asset_allocation_type": "자산 배분 유형",
                    "value_growth": "가치/성장 구분",
                    "risk_acceptance_level": "위험 수용 수준",
                    "investment_concern": "투자 관련 고민",
                }
                label = label_map.get(field, field)
                propose_msg = f"{label}이(가) {value}으로 변경된 것 같아요. 프로필에도 업데이트해 드릴까요?"

                ChatMessage.objects.create(
                    session_id=session_id,
                    username=username,
                    product_type=body.get("product_type", ""),
                    role="assistant",
                    message=propose_msg,
                )
                return CustomResponse(
                    is_success=True,
                    code=GeneralSuccessCode.OK[0],
                    message=GeneralSuccessCode.OK[1],
                    result={
                        "propose_update": propose_msg,
                        "field": field,
                        "value": value
                    },
                    status=GeneralSuccessCode.OK[2],
                )

        # 4) 일반 챗 흐름 (초기 프로필 수집 & Q&A)
        gpt_reply, session_id = handle_chat(message, session_id, user_id=username)

        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=body.get("product_type", ""),
            role="assistant",
            message=gpt_reply,
        )
        
        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result={"response": gpt_reply, "session_id": session_id},
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
    operation_description="사용자의 투자 정보를 기반으로 금융상품을 추천합니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "username": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="사용자 ID"
            ),
            "product_type": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="상품 유형 (예금, 적금, 연금, stock 중 하나)"
            ),
            "session_id": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="세션 ID (선택사항, 없으면 서버에서 생성)"
            ),
            "query": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="추천을 위한 사용자 질문/요청"
            ),
            "top_k": openapi.Schema(
                type=openapi.TYPE_INTEGER,
                description="추천할 결과 개수 (기본값: 3)",
                default=3
            ),
            "index": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="검색에 사용할 OpenSearch 인덱스 이름 (기본값: 'financial-products')",
                default="financial-products"
            ),
        },
    ),
    responses={200: openapi.Response("성공", openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={"message": openapi.Schema(type=openapi.TYPE_STRING)}
    ))},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_exempt
def recommend_products(request):
    """
    POST /recommend/
    {
      "username":     "<사용자ID>",
      "product_type": "<예금|적금|연금|stock>",
      "session_id":   "<세션ID>",         # 선택사항
      "query":        "<검색어>",
      "top_k":        5,                 # optional, 기본 3
      "index":        "financial-products"  # optional
    }
    """
    try:
        body = json.loads(request.body)
        username     = body.get("username", "")
        product_type = body.get("product_type", "")
        session_id   = body.get("session_id") or get_session_id(body)
        query        = (body.get("query") or "").strip()
        top_k        = int(body.get("top_k", 3))
        index_name   = body.get("index", os.getenv("OPENSEARCH_INDEX", "financial-products"))

        if not query:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.BAD_REQUEST[0],
                message="`query` 파라미터가 필요합니다.",
                result={},
                status=GeneralErrorCode.BAD_REQUEST[2]
            )

        # (1) 사용자 메시지 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="user",
            message=query,
        )

        buf = io.StringIO()
        cmd_args = ['opensearch_service', query, f'--top_k={top_k}']
        if index_name:
            cmd_args.append(f'--index={index_name}')

        call_command(*cmd_args, stdout=buf)
        recommendation = buf.getvalue().strip()

        # (3) 어시스턴트 메시지 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="assistant",
            message=recommendation,
        )

        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result={"response": recommendation},
            status=GeneralSuccessCode.OK[2]
        )

    except Exception as e:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            result={"error": repr(e)},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2]
        )


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


# ===== OpenSearch 인덱싱 즉시 실행 =====
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_exempt
def api_index_opensearch(request):
    try:
        buf = io.StringIO()
        call_command('index_to_opensearch', stdout=buf)
        return JsonResponse(
            {"message": buf.getvalue()},
            status=200,
            json_dumps_params={"ensure_ascii": False}
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)