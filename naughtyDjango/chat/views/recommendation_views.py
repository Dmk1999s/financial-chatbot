# chat/views/recommendation_views.py
import os
import json
from dotenv import load_dotenv
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from chat.gpt_service import get_session_id
from main.utils.custom_response import CustomResponse
from main.constants.error_codes import GeneralErrorCode
from main.constants.success_codes import GeneralSuccessCode
from chat.services import RecommendationService

load_dotenv()

# ===== 금융상품 추천 엔드포인트 =====
@swagger_auto_schema(
    method="post",
    operation_description="사용자의 질문 의도를 파악하여 금융상품을 추천하거나 일반 대화를 수행합니다",
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
    사용자 질문의 의도를 파악하여 '상품추천' 또는 '일반대화'로 분기하여 처리합니다.
    """
    try:
        body = json.loads(request.body)
        username = body.get("username", "")
        session_id = body.get("session_id") or get_session_id(body)
        query = (body.get("query") or "").strip()
        top_k = int(body.get("top_k", 3))

        if not query:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.BAD_REQUEST[0],
                message="`query` 파라미터가 필요합니다.",
                result={},
                status=GeneralErrorCode.BAD_REQUEST[2]
            )

        final_response, _ = RecommendationService.recommend_or_chitchat(
            username=username,
            session_id=session_id,
            query=query,
            top_k=top_k,
        )

        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result={"response": final_response, "session_id": session_id},
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
