# chat/views.py
import os
from django.utils import timezone
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.core.paginator import Paginator, EmptyPage
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
from chat.gpt_service import handle_chitchat
from chat.models import ChatMessage

from chat.gpt_service import extract_json_from_response
from chat.models import ChatMessage
from main.models import User
from chat.opensearch_client import search_financial_products
from chat.rag.financial_product_rag import answer_financial_question
from main.utils.custom_response import CustomResponse
from main.constants.error_codes import GeneralErrorCode
from main.constants.success_codes import GeneralSuccessCode
from chat.gpt_service import handle_chat, get_session_id
from chat.serializers import ChatRequestSerializer, SaveInvestmentProfileRequestSerializer, RecommendProductRequestSerializer
from chat.tasks import process_chat_async
from celery.result import AsyncResult
import json
from rest_framework.decorators import api_view
from main.utils.custom_response import CustomResponse
from main.constants.success_codes import GeneralSuccessCode
from .gpt_service import SESSION_TEMP_STORE
from main.constants.error_codes import GeneralErrorCode
from main.utils.logging_decorator import chat_logger, api_logger
from chat.management.commands.opensearch_recommender import recommend_with_self_query

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

def _format_local(ts) -> str:
    """채팅 시간을 보기 편하게 변환"""
    try:
        tz = ZoneInfo("Asia/Seoul")
    except Exception:
        tz = ZoneInfo("UTC")

    if timezone.is_naive(ts):
        ts = timezone.make_aware(ts, timezone=ZoneInfo("UTC"))
    local_dt = timezone.localtime(ts, tz)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")

# ===== GPT 채팅 엔드포인트 =====
@swagger_auto_schema(
    method="post",
    operation_description="세션 ID를 기반으로 AI에게 질문을 보냅니다. task_id를 기반으로 task/ api를 호출해 ai의 대답을 가져올 수 있습니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "username":   openapi.Schema(type=openapi.TYPE_STRING),
            "session_id": openapi.Schema(type=openapi.TYPE_STRING),
            "message":    openapi.Schema(type=openapi.TYPE_STRING),
        },
        required=["message"],
    ),
    responses={
        200: openapi.Response(
            "성공 - 비동기 처리 시작",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="COMMON200"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="처리 중입니다..."),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "task_id": openapi.Schema(type=openapi.TYPE_STRING, example="abc-123-def"),
                            "session_id": openapi.Schema(type=openapi.TYPE_STRING, example="session_123"),
                            "status": openapi.Schema(type=openapi.TYPE_STRING, example="processing")
                        }
                    )
                }
            )
        ),
        "2001": openapi.Response(
            "충돌 감지 - 확인 필요",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="COMMON2001"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="프로필 변경이 감지되었습니다."),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "message": openapi.Schema(type=openapi.TYPE_STRING),
                            "conflict_data": openapi.Schema(type=openapi.TYPE_OBJECT),
                            "requires_confirmation": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True)
                        }
                    )
                }
            )
        ),
        400: openapi.Response(
            "잘못된 요청",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="CHAT4003"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="메시지가 필요합니다."),
                    "result": openapi.Schema(type=openapi.TYPE_OBJECT, example={})
                }
            )
        ),
        404: openapi.Response(
            "사용자 없음",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="USER4000"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="사용자를 찾을 수 없습니다."),
                    "result": openapi.Schema(type=openapi.TYPE_OBJECT, example={})
                }
            )
        ),
        500: openapi.Response(
            "서버 에러",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="COMMON500"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="서버 내부 오류가 발생했습니다."),
                    "result": openapi.Schema(type=openapi.TYPE_OBJECT, example={})
                }
            )
        )
    }
)

@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_exempt
@chat_logger
def chat_with_gpt(request):
    try:
        # 요청 로깅 추가
        print(f"=== Request from Swagger/curl ===")
        print(f"Method: {request.method}")
        print(f"Headers: {dict(request.headers)}")
        print(f"Body: {request.body}")
        print(f"Content-Type: {request.content_type}")
        
        body = json.loads(request.body)
        username = body.get("username", "")
        session_id = body.get("session_id") or get_session_id(body)
        message = (body.get("message") or "").strip()
        
        print(f"Parsed data - username: {username}, session_id: {session_id}, message: {message}")
        
        if not message:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.MESSAGE_REQUIRED[0],
                message=GeneralErrorCode.MESSAGE_REQUIRED[1],
                result={},
                status=GeneralErrorCode.MESSAGE_REQUIRED[2],
            )

        # profile 업로드
        try:
            user = User.objects.get(email=username)
        except User.DoesNotExist:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.USER_NOT_FOUND[0],
                message=GeneralErrorCode.USER_NOT_FOUND[1],
                result={},
                status=GeneralErrorCode.USER_NOT_FOUND[2],
            )

        # profile 업로드 확인
        if body.get("update_confirm"):
            field = body.get("field")
            value = body.get("value")
            if field and value is not None:
                setattr(user, field, value)
                user.save(update_fields=[field])
                
                confirm_msg = f"{field} 정보를 {value}으로 업데이트했습니다."
                ChatMessage.objects.create(
                    session_id=session_id,
                    username=username,
                    product_type="",
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

        # 메시지 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type="",
            role="user",
            message=message,
        )

        # 간단한 메시지는 빠르게 답변하도록 수정
        simple_responses = {
            '안녕': '안녕하세요! 무엇을 도와드릴까요?',
            '네': '네, 말씀해 주세요.',
            '아니오': '알겠습니다. 다른 도움이 필요하시면 말씀해 주세요.',
        }
        
        if message.lower() in simple_responses:
            quick_response = simple_responses[message.lower()]
            ChatMessage.objects.create(
                session_id=session_id,
                username=username,
                product_type="",
                role="assistant",
                message=quick_response,
            )
            return CustomResponse(
                is_success=True,
                code=GeneralSuccessCode.OK[0],
                message=GeneralSuccessCode.OK[1],
                result={"response": quick_response, "session_id": session_id},
                status=GeneralSuccessCode.OK[2],
            )

        # AI API 호출이 필요한 경우 celery로 비동기 처리
        task = process_chat_async.delay(
            session_id, username, message, ""
        )
        
        # Task 결과를 폴링하여 충돌 감지
        max_polling = 20  # 최대 10초 대기 (0.5초 * 20)
        polling_count = 0
        
        while polling_count < max_polling:
            result = AsyncResult(task.id)
            
            if result.ready():
                if result.successful():
                    task_result = result.get()
                    
                    # 충돌 감지 확인
                    if task_result.get("type") == "conflict_detected":
                        field = task_result.get("field")
                        value = task_result.get("value")
                        
                        # 충돌 데이터를 SESSION_TEMP_STORE에 저장
                        from .gpt_service import SESSION_TEMP_STORE
                        SESSION_TEMP_STORE["conflict_pending"] = {field: value}
                        
                        # 충돌 데이터 구성
                        conflict_data = {field: value}
                        
                        return CustomResponse(
                            is_success=True,
                            code=GeneralSuccessCode.CONFLICTS[0],
                            message=GeneralSuccessCode.CONFLICTS[1],
                            result={
                                "message": f"프로필 변경이 감지되었습니다: {field} = {value}",
                                "conflict_data": conflict_data,
                                "session_id": session_id,
                                "requires_confirmation": True
                            },
                            status=GeneralSuccessCode.CONFLICTS[2],
                        )
                    else:
                        # 일반 채팅 응답이면 task_id 반환
                        break
                else:
                    # Task 실패
                    break
            
            # 0.5초 대기 후 다시 폴링
            import time
            time.sleep(0.5)
            polling_count += 1
        
        # 폴링 완료 후 task_id 반환 (일반 채팅 또는 폴링 실패)
        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message="처리 중입니다...",
            result={
                "task_id": task.id,
                "session_id": session_id,
                "status": "processing"
            },
            status=GeneralSuccessCode.OK[2],
        )

    except Exception as e:
        # 로그에만 상세 에러 기록
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"chat_with_gpt 에러: {str(e)}")
        
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=GeneralErrorCode.INTERNAL_SERVER_ERROR[1],
            result={},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2],
        )


@swagger_auto_schema(
    method="get",
    operation_description="비동기 작업 상태를 확인합니다. chat/ API 호출 후 task_id로 결과를 폴링합니다.",
    manual_parameters=[
        openapi.Parameter(
            'task_id',
            openapi.IN_PATH,
            description="비동기 작업 ID",
            type=openapi.TYPE_STRING,
            required=True
        )
    ],
    responses={
        200: openapi.Response(
            "작업 상태 조회 성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="COMMON200"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="성공적으로 처리했습니다."),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "status": openapi.Schema(type=openapi.TYPE_STRING, example="completed", description="completed/pending/failed"),
                            "result": openapi.Schema(
                                type=openapi.TYPE_OBJECT,
                                properties={
                                    "type": openapi.Schema(type=openapi.TYPE_STRING, example="chat_response"),
                                    "response": openapi.Schema(type=openapi.TYPE_STRING, example="AI 답변 내용")
                                }
                            )
                        }
                    )
                }
            )
        ),
        404: openapi.Response(
            "작업 없음",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="CHAT4001"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="작업을 찾을 수 없습니다."),
                    "result": openapi.Schema(type=openapi.TYPE_OBJECT, example={})
                }
            )
        ),
        500: openapi.Response(
            "작업 실패",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="CHAT4002"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="작업 처리에 실패했습니다."),
                    "result": openapi.Schema(type=openapi.TYPE_OBJECT, properties={"status": openapi.Schema(type=openapi.TYPE_STRING, example="failed")})
                }
            )
        )
    }
)
@api_view(["GET"])
@permission_classes([AllowAny])
@api_logger
def get_task_status(request, task_id):
    try:
        result = AsyncResult(task_id)
        
        if result.ready():
            if result.successful():
                task_result = result.get()
                
                # 충돌 감지 확인
                if task_result.get("type") == "conflict_detected":
                    field = task_result.get("field")
                    value = task_result.get("value")
                    
                    # 충돌 데이터 구성
                    conflict_data = {field: value}
                    
                    return CustomResponse(
                        is_success=True,
                        code=GeneralSuccessCode.CONFLICTS[0],
                        message=GeneralSuccessCode.CONFLICTS[1],
                        result={
                            "message": f"프로필 변경이 감지되었습니다: {field} = {value}",
                            "conflict_data": conflict_data,
                            "requires_confirmation": True
                        },
                        status=GeneralSuccessCode.CONFLICTS[2],
                    )
                
                # 일반 채팅 응답
                return CustomResponse(
                    is_success=True,
                    code=GeneralSuccessCode.OK[0],
                    message=GeneralSuccessCode.OK[1],
                    result={
                        "status": "completed",
                        "result": task_result
                    },
                    status=GeneralSuccessCode.OK[2],
                )
            else:
                return CustomResponse(
                    is_success=False,
                    code=GeneralErrorCode.TASK_FAILED[0],
                    message=GeneralErrorCode.TASK_FAILED[1],
                    result={"status": "failed"},
                    status=GeneralErrorCode.TASK_FAILED[2],
                )
        else:
            return CustomResponse(
                is_success=True,
                code=GeneralSuccessCode.OK[0],
                message="Task in progress",
                result={"status": "pending"},
                status=GeneralSuccessCode.OK[2],
            )
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"get_task_status 에러: {str(e)}")
        
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.TASK_NOT_FOUND[0],
            message=GeneralErrorCode.TASK_NOT_FOUND[1],
            result={},
            status=GeneralErrorCode.TASK_NOT_FOUND[2],
        )
    


@swagger_auto_schema(
    method="post",
    operation_description="프로필 충돌 발생 시 사용자의 예/아니오 선택을 처리합니다. chat/ API에서 requires_confirmation: true 응답 후 호출합니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "session_id": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="세션 ID"
            ),
            "choice": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="사용자 선택 (yes/no)",
                enum=["yes", "no"]
            )
        },
        required=["session_id", "choice"]
    ),
    responses={
        200: openapi.Response(
            "충돌 해결 성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="COMMON200"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="성공적으로 처리했습니다."),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "message": openapi.Schema(type=openapi.TYPE_STRING, example="프로필이 성공적으로 업데이트되었습니다.")
                        }
                    )
                }
            )
        ),
        400: openapi.Response(
            "충돌 데이터 없음",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="CHAT4000"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="충돌 데이터를 찾을 수 없습니다."),
                    "result": openapi.Schema(type=openapi.TYPE_OBJECT, example={})
                }
            )
        )
    }
)

@api_view(['POST'])
def handle_profile_conflict(request):
    """프로필 충돌 시 사용자 선택 처리"""
    session_id = request.data.get('session_id')
    user_choice = request.data.get('choice')  # 'yes' or 'no'
    
    if not session_id or "conflict_pending" not in SESSION_TEMP_STORE:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.NOT_CONFLICTS[0],
            message=GeneralErrorCode.NOT_CONFLICTS[1],
            result={},
            status=GeneralErrorCode.NOT_CONFLICTS[2],
        )
    
    pending = SESSION_TEMP_STORE.pop("conflict_pending")
    
    if user_choice == 'yes':
        # 충돌 항목을 세션에 저장
        if session_id not in SESSION_TEMP_STORE:
            SESSION_TEMP_STORE[session_id] = {}
        SESSION_TEMP_STORE[session_id].update(pending)
        
        # DB 업데이트
        try:
            # session_id에서 username 추출 (예: "new_ehdgurdusdn@naver.com_8230" -> "ehdgurdusdn@naver.com")
            username = session_id.split('_')[1] if '_' in session_id else session_id
            
            from main.models import User
            user = User.objects.get(email=username)
            
            # 필드 매핑
            field_mapping = {
                'age': 'age',
                'monthly_income': 'income',
                'risk_tolerance': 'risk_tolerance',
                'income_stability': 'income_stability',
                'income_sources': 'income_source',
                'investment_horizon': 'period',
                'expected_return': 'expected_income',
                'expected_loss': 'expected_loss',
                'investment_purpose': 'purpose',
                'asset_allocation_type': 'asset_allocation_type',
                'value_growth': 'value_growth',
                'risk_acceptance_level': 'risk_acceptance_level',
                'investment_concern': 'investment_concern',
            }
            
            # DB 업데이트
            for field, value in pending.items():
                if field in field_mapping:
                    db_field = field_mapping[field]
                    setattr(user, db_field, value)
            
            user.save()
            print(f"DB updated: {pending}")
            
        except Exception as e:
            print(f"DB update failed: {e}")
        
        message = "프로필이 성공적으로 업데이트되었습니다."
    else:
        message = "기존 프로필 정보를 유지합니다."
    
    return CustomResponse(
        is_success=True,
        code=GeneralSuccessCode.OK[0],
        message=GeneralSuccessCode.OK[1],
        result={"message": message},
        status=GeneralSuccessCode.OK[2],
    )
# ===== 대화 이력 조회 엔드포인트 =====
@swagger_auto_schema(
    method="get",
    tags=["chat"],
    operation_id="chat_histories_read",
    operation_description="사용자의 대화 이력을 페이지네이션으로 조회합니다. (페이지 크기 20, 오름차순 고정, role/product_type 필터 제거)",
    manual_parameters=[
        openapi.Parameter('username',   openapi.IN_QUERY, type=openapi.TYPE_STRING,  required=True,  description="사용자 이메일"),
        openapi.Parameter('session_id', openapi.IN_QUERY, type=openapi.TYPE_STRING,  required=False, description="세션 ID(선택)"),
        openapi.Parameter('page',       openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False, description="페이지 번호(기본 1)"),
    ],
    responses={
        200: openapi.Response(
            "조회 성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                    "code":      openapi.Schema(type=openapi.TYPE_STRING,  example="COMMON200"),
                    "message":   openapi.Schema(type=openapi.TYPE_STRING,  example="성공"),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "page":         openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                            "page_size":    openapi.Schema(type=openapi.TYPE_INTEGER, example=20),
                            "total":        openapi.Schema(type=openapi.TYPE_INTEGER, example=123),
                            "total_pages":  openapi.Schema(type=openapi.TYPE_INTEGER, example=7),
                            "has_next":     openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                            "has_prev":     openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                            "items": openapi.Schema(
                                type=openapi.TYPE_ARRAY,
                                items=openapi.Schema(
                                    type=openapi.TYPE_OBJECT,
                                    properties={
                                        "session_id":   openapi.Schema(type=openapi.TYPE_STRING, example="new_user@naver.com_6645"),
                                        "role":         openapi.Schema(type=openapi.TYPE_STRING, example="assistant"),
                                        "message":      openapi.Schema(type=openapi.TYPE_STRING, example="안녕하세요! 무엇을 도와드릴까요?"),
                                        "timestamp":    openapi.Schema(type=openapi.TYPE_STRING, example="2025-09-09 22:54:26"),
                                        "product_type": openapi.Schema(type=openapi.TYPE_STRING, example=""),
                                    }
                                )
                            ),
                        }
                    ),
                }
            )
        ),
        400: openapi.Response(
            "잘못된 요청",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code":      openapi.Schema(type=openapi.TYPE_STRING,  example="CHAT4000"),
                    "message":   openapi.Schema(type=openapi.TYPE_STRING,  example="username 쿼리 파라미터가 필요합니다."),
                    "result":    openapi.Schema(type=openapi.TYPE_OBJECT,  example={}),
                }
            )
        ),
        500: openapi.Response(
            "서버 에러",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code":      openapi.Schema(type=openapi.TYPE_STRING,  example="COMMON500"),
                    "message":   openapi.Schema(type=openapi.TYPE_STRING,  example="서버 내부 오류가 발생했습니다."),
                    "result":    openapi.Schema(type=openapi.TYPE_OBJECT,  example={}),
                }
            )
        ),
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def histories(request):
    try:
        username = request.GET.get("username")
        if not username:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.BAD_REQUEST[0],
                message="username 쿼리 파라미터가 필요합니다.",
                result={},
                status=GeneralErrorCode.BAD_REQUEST[2],
            )

        # 필터 (role, product_type 필터 제거)
        filters = {"username": username}
        if request.GET.get("session_id"):
            filters["session_id"] = request.GET.get("session_id")

        # 오름차순 고정
        qs = ChatMessage.objects.filter(**filters).order_by("timestamp", "id")

        # 페이지네이션 (20 고정)
        PAGE_SIZE = 20
        try:
            page = max(int(request.GET.get("page", 1)), 1)
        except ValueError:
            page = 1

        paginator = Paginator(qs, PAGE_SIZE)

        if paginator.count == 0:
            payload = {
                "page": 1, "page_size": PAGE_SIZE, "total": 0, "total_pages": 0,
                "has_next": False, "has_prev": False, "items": [],
            }
            return CustomResponse(
                is_success=True,
                code=GeneralSuccessCode.OK[0],
                message=GeneralSuccessCode.OK[1],
                result=payload,
                status=GeneralSuccessCode.OK[2],
            )

        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        items = [{
            "session_id":   c.session_id,
            "role":         c.role,             # 필터는 없지만 누가 말했는지 보이게 유지
            "message":      c.message,
            "timestamp":    _format_local(c.timestamp),
            "product_type": c.product_type or "",  # 결과에서도 없애고 싶으면 이 줄 삭제
        } for c in page_obj.object_list]

        payload = {
            "page":        page_obj.number,
            "page_size":   PAGE_SIZE,
            "total":       paginator.count,
            "total_pages": paginator.num_pages,
            "has_next":    page_obj.has_next(),
            "has_prev":    page_obj.has_previous(),
            "items":       items,
        }

        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result=payload,
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




@swagger_auto_schema(
    method="delete",
    operation_description="채팅 세션을 종료하고 관련 데이터를 정리합니다. 대화 종료 시 호출합니다.",
    manual_parameters=[
        openapi.Parameter(
            'session_id',
            openapi.IN_PATH,
            description="종료할 세션 ID",
            type=openapi.TYPE_STRING,
            required=True
        )
    ],
    responses={
        200: openapi.Response(
            "세션 종료 성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="COMMON200"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="대화가 종료되었습니다."),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "session_id": openapi.Schema(type=openapi.TYPE_STRING, example="session_123"),
                            "deleted_rows": openapi.Schema(type=openapi.TYPE_INTEGER, example=12),
                        }
                    )
                }
            )
        ),
        500: openapi.Response(
            "세션 종료 실패",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                    "code": openapi.Schema(type=openapi.TYPE_STRING, example="COMMON500"),
                    "message": openapi.Schema(type=openapi.TYPE_STRING, example="서버 내부 오류가 발생했습니다."),
                    "result": openapi.Schema(type=openapi.TYPE_OBJECT, example={})
                }
            )
        )
    }
)
@api_view(["DELETE"])
@permission_classes([AllowAny])
@csrf_exempt
def end_chat_session(request, session_id):
    """대화 세션 종료"""
    try:
        from .gpt_service import SESSION_TEMP_STORE, store


        with transaction.atomic():

            # 메모리 정리
            SESSION_TEMP_STORE.pop(session_id, None)
            store.pop(session_id, None)

            # DB 기록삭제
            deleted_rows, _ = ChatMessage.objects.filter(session_id=session_id).delete()

        # 세션 데이터 정리
        if session_id in SESSION_TEMP_STORE:
            del SESSION_TEMP_STORE[session_id]
        
        if session_id in store:
            del store[session_id]
        
        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result={"session_id": session_id, "deleted_rows": deleted_rows},  # 몇 건 지웠는지 확인
            status=GeneralSuccessCode.OK[2],
        )
    except Exception as e:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=str(e),
            result={},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2],
        )



# ===== 투자 프로필 저장 엔드포인트 =====
# (변경 없음)


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

        if not query:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.BAD_REQUEST[0],
                message="`query` 파라미터가 필요합니다.",
                result={},
                status=GeneralErrorCode.BAD_REQUEST[2]
            )

        # 1. 의도 분류 (Intent Classification)
        intent_prompt = f"""
        사용자의 질문 의도를 "상품추천" 또는 "일반대화" 둘 중 하나로 분류하세요.
        오직 키워드 하나만 답변해야 합니다.

        질문: "{query}"
        분류:
        """
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": intent_prompt}],
            temperature=0,
            max_tokens=10
        )
        intent = response.choices[0].message.content.strip()

        # 2. 의도에 따라 분기 처리
        final_response = ""
        product_type = "general"

        if "상품추천" in intent:
            # [수정] 새로운 Self-Query Retriever 함수를 호출합니다.
            final_response = recommend_with_self_query(query=query)
            product_type = "recommend"
        else:  # "일반대화"
            final_response = handle_chitchat(query)

        # 메시지 저장
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            role="user",
            message=query,
        )
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="assistant",
            message=final_response,
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

@swagger_auto_schema(
    method="post",
    operation_description="사용자의 투자 프로필 정보를 저장합니다.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "user_id": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="사용자 이메일"
            ),
            "investment_profile": openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "risk_tolerance": openapi.Schema(type=openapi.TYPE_STRING),
                    "age": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "income_stability": openapi.Schema(type=openapi.TYPE_STRING),
                    "income_sources": openapi.Schema(type=openapi.TYPE_STRING),
                    "monthly_income": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "expected_return": openapi.Schema(type=openapi.TYPE_NUMBER),
                    "expected_loss": openapi.Schema(type=openapi.TYPE_NUMBER),
                    "investment_purpose": openapi.Schema(type=openapi.TYPE_STRING),
                }
            )
        },
        required=["user_id", "investment_profile"]
    ),
    responses={
        200: openapi.Response(
            "프로필 저장 성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "isSuccess": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "code": openapi.Schema(type=openapi.TYPE_STRING),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "result": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "message": openapi.Schema(type=openapi.TYPE_STRING)
                        }
                    )
                }
            )
        )
    }
)
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_exempt
def save_investment_profile(request):
    try:
        data    = json.loads(request.body)
        profile = data.get("investment_profile", {})
        try:
            user = User.objects.get(email=data.get("user_id"))
        except User.DoesNotExist:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.BAD_REQUEST[0],
                message="사용자를 찾을 수 없습니다.",
                result={},
                status=GeneralErrorCode.BAD_REQUEST[2],
            )
        user.risk_tolerance = profile.get("risk_tolerance")
        user.age = profile.get("age")
        user.income_stability = profile.get("income_stability")
        user.income_source = profile.get("income_sources")
        user.income = profile.get("monthly_income")
        user.expected_income = profile.get("expected_return")
        user.expected_loss = profile.get("expected_loss")
        user.purpose = profile.get("investment_purpose")
        user.save()
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
@swagger_auto_schema(
    method="post",
    operation_description="OpenSearch에 금융상품 데이터를 인덱싱합니다.",
    responses={
        200: openapi.Response(
            "인덱싱 성공",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="인덱싱 결과 메시지"
                    )
                }
            )
        ),
        500: openapi.Response(
            "인덱싱 실패",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "error": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="에러 메시지"
                    )
                }
            )
        )
    }
)
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