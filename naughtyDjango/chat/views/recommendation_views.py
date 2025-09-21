# chat/views/recommendation_views.py
import json
import logging
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
from chat.tasks import process_recommend_async

load_dotenv()

# ===== 금융상품 추천 엔드포인트 =====
@swagger_auto_schema(
    method="post",
    operation_description="사용자의 질문 의도를 파악하여 금융상품을 추천하거나 일반 대화를 수행합니다",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "username": openapi.Schema(type=openapi.TYPE_STRING, description="사용자 ID"),
            "product_type": openapi.Schema(type=openapi.TYPE_STRING, description="상품 유형 (예금, 적금, 연금, stock 중 하나)"),
            "session_id": openapi.Schema(type=openapi.TYPE_STRING, description="세션 ID (선택사항, 없으면 서버에서 생성)"),
            "message": openapi.Schema(type=openapi.TYPE_STRING, description="추천을 위한 사용자 질문/요청"),
            "top_k": openapi.Schema(type=openapi.TYPE_INTEGER, description="추천할 결과 개수 (기본값: 3)", default=3),
            "index": openapi.Schema(type=openapi.TYPE_STRING, description="검색에 사용할 OpenSearch 인덱스 이름 (기본값: 'financial-products')", default="financial-products"),
            "async": openapi.Schema(type=openapi.TYPE_BOOLEAN, description="true면 비동기로 처리하고 task_id 반환", default=False),
        },
        required=["message"],
    ),
    responses={
        202: openapi.Response(
            "Accepted - 비동기 처리 시작",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "code": openapi.Schema(type=openapi.TYPE_STRING),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "task_id": openapi.Schema(type=openapi.TYPE_STRING),
                            "session_id": openapi.Schema(type=openapi.TYPE_STRING),
                            "status": openapi.Schema(type=openapi.TYPE_STRING, description="processing"),
                        }
                    )
                }
            )
        ),
        400: openapi.Response(
            "Bad Request",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "code": openapi.Schema(type=openapi.TYPE_STRING),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "result": openapi.Schema(type=openapi.TYPE_OBJECT),
                }
            )
        ),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_exempt
def recommend_products(request):
    """
    사용자 질문의 의도를 파악하여 '상품추천' 또는 '일반대화'로 분기하여 처리합니다.
    async=true 이면 Celery로 비동기 처리하고 task_id를 반환합니다.
    """
    try:
        body = json.loads(request.body or "{}")

        username   = (body.get("username") or "").strip()
        session_id = (body.get("session_id") or get_session_id(body)).strip()
        message    = (body.get("message") or "").strip()
        if not message:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.BAD_REQUEST[0],
                message="`message` 파라미터가 필요합니다.",
                result={},
                status=GeneralErrorCode.BAD_REQUEST[2],
            )

        # 선택 파라미터(기본값 적용)
        product_type = (body.get("product_type") or "").strip()
        index        = (body.get("index") or "financial-products").strip()
        try:
            top_k = int(body.get("top_k") or 3)
            top_k = max(1, min(50, top_k))
        except Exception:
            top_k = 3

        # 항상 태스크로 처리
        task = process_recommend_async.delay(
            session_id, username, message, product_type, top_k, index
        )

        logging.getLogger(__name__).info(
            "recommend: enqueued",
            extra={"session_id": session_id, "username": username, "task_id": task.id, "top_k": top_k, "index": index, "product_type": product_type}
        )

        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message="처리 중입니다...",
            result={"task_id": task.id, "session_id": session_id, "status": "processing"},
            status=202,
        )

    except Exception as e:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            result={"error": repr(e)},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2],
        )