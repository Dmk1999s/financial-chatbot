# chat/views/chat_views.py
import os
import json
import io
import logging
from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from celery.result import AsyncResult
from django.core.management import call_command
from chat.models import ChatMessage
from main.models import User
from main.utils.custom_response import CustomResponse
from main.constants.error_codes import GeneralErrorCode
from main.constants.success_codes import GeneralSuccessCode
from main.utils.logging_decorator import chat_logger, api_logger
from chat.gpt_service import get_session_id
from chat.tasks import process_chat_async
from chat.gpt.session_store import get_session_data, set_session_data, delete_session_data, set_conflict_pending_cache, get_conflict_pending, pop_conflict_pending
from chat.services import ChatService

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
    operation_description="챗봇이 사용자의 프로필 정보를 수집합니다.",
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
        body = json.loads(request.body)
        username = body.get("username", "")
        session_id = body.get("session_id") or get_session_id(body)
        message = (body.get("message") or "").strip()
        logger = logging.getLogger(__name__)
        logger.info(
            "chat_with_gpt: received request",
            extra={"session_id": session_id, "username": username, "msg_len": len(message)}
        )
        
        if not message:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.MESSAGE_REQUIRED[0],
                message=GeneralErrorCode.MESSAGE_REQUIRED[1],
                result={},
                status=GeneralErrorCode.MESSAGE_REQUIRED[2],
            )

        # user 확인
        user = ChatService.get_or_validate_user(username)
        if not user:
            return CustomResponse(
                is_success=False,
                code=GeneralErrorCode.USER_NOT_FOUND[0],
                message=GeneralErrorCode.USER_NOT_FOUND[1],
                result={},
                status=GeneralErrorCode.USER_NOT_FOUND[2],
            )

        # 사용자 메시지 저장
        ChatService.save_user_message(session_id, username, message)

        # 세션 스냅샷 로깅 (디버깅용)
        try:
            session_snapshot = get_session_data(session_id)
            # 디버깅용 error 로그
            logger.error(f"[chat_with_gpt][session={session_id}] snapshot_keys={list(session_snapshot.keys()) if isinstance(session_snapshot, dict) else []}")
            logger.error(f"[chat_with_gpt][session={session_id}] snapshot={json.dumps(session_snapshot, ensure_ascii=False, default=str)}")
            print(f"[chat_with_gpt][session={session_id}] snapshot={json.dumps(session_snapshot, ensure_ascii=False, default=str)}")
        except Exception:
            pass

        # 간단한 메시지 빠른 응답
        quick = ChatService.maybe_quick_reply(message)
        if quick:
            ChatService.save_assistant_message(session_id, username, quick)
            logger.info(
                "chat_with_gpt: quick_reply",
                extra={"session_id": session_id, "username": username}
            )
            return CustomResponse(
                is_success=True,
                code=GeneralSuccessCode.OK[0],
                message=GeneralSuccessCode.OK[1],
                result={"response": quick, "session_id": session_id},
                status=GeneralSuccessCode.OK[2],
            )

        # AI API 호출이 필요한 경우 celery로 비동기 처리
        task = process_chat_async.delay(
            session_id, username, message, ""
        )
        logger.info(
            "chat_with_gpt: task_enqueued",
            extra={"task_id": task.id, "session_id": session_id, "username": username}
        )
        
        # Task 결과를 폴링하여 충돌 감지
        max_polling = 20
        polling_count = 0
        
        while polling_count < max_polling:
            result = AsyncResult(task.id)
            
            if result.ready():
                if result.successful():
                    task_result = result.get()
                    
                    if task_result.get("type") == "conflict_detected":
                        field = task_result.get("field")
                        value = task_result.get("value")
                        
                        set_conflict_pending_cache({field: value})
                        conflict_data = {field: value}
                        logger.info(
                            "chat_with_gpt: conflict_detected",
                            extra={"session_id": session_id, "username": username, "conflict": conflict_data}
                        )
                        
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
                        break
                else:
                    break
            
            import time
            time.sleep(0.5)
            polling_count += 1
        
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
        logger = logging.getLogger(__name__)
        logger.info("get_task_status: polled", extra={"task_id": task_id, "ready": result.ready()})
        
        if result.ready():
            if result.successful():
                task_result = result.get()
      
                if task_result.get("type") == "conflict_detected":
                    field = task_result.get("field")
                    value = task_result.get("value")
                    logger.info("get_task_status: conflict_detected", extra={"task_id": task_id, "field": field})
                    
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
                logger.warning("get_task_status: task_failed", extra={"task_id": task_id})
                return CustomResponse(
                    is_success=False,
                    code=GeneralErrorCode.TASK_FAILED[0],
                    message=GeneralErrorCode.TASK_FAILED[1],
                    result={"status": "failed"},
                    status=GeneralErrorCode.TASK_FAILED[2],
                )
        else:
            logger.info("get_task_status: pending", extra={"task_id": task_id})
            return CustomResponse(
                is_success=True,
                code=GeneralSuccessCode.OK[0],
                message="Task in progress",
                result={"status": "pending"},
                status=GeneralSuccessCode.OK[2],
            )
            
    except Exception as e:
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
    
    if not session_id or get_conflict_pending() is None:
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.NOT_CONFLICTS[0],
            message=GeneralErrorCode.NOT_CONFLICTS[1],
            result={},
            status=GeneralErrorCode.NOT_CONFLICTS[2],
        )
    
    pending = pop_conflict_pending() or {}
    
    if user_choice == 'yes':
        # 충돌 항목을 세션에 저장 (캐시)
        current = get_session_data(session_id)
        current.update(pending)
        set_session_data(session_id, current)
        
        try:
            email = request.data.get('username')
            if not email:
                chat = ChatMessage.objects.filter(session_id=session_id).order_by('-timestamp').first()
                email = chat.username if chat else None
            if email:
                user = User.objects.get(email=email)
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
                for field, value in pending.items():
                    if field in field_mapping:
                        setattr(user, field_mapping[field], value)
                user.save()
        except Exception:
            pass
        
        message = "프로필이 성공적으로 업데이트되었습니다. 계속 진행할게요."
    else:
        message = "기존 프로필 정보를 유지합니다. 계속 진행할게요."
    
    return CustomResponse(
        is_success=True,
        code=GeneralSuccessCode.OK[0],
        message=GeneralSuccessCode.OK[1],
        result={"message": message},
        status=GeneralSuccessCode.OK[2],
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
                            "session_id": openapi.Schema(type=openapi.TYPE_STRING, example="session_123")
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
        from chat.gpt_service import store
        
        # 세션 데이터 정리
        delete_session_data(session_id)
        
        if session_id in store:
            del store[session_id]
        
        return CustomResponse(
            is_success=True,
            code=GeneralSuccessCode.OK[0],
            message=GeneralSuccessCode.OK[1],
            result={"session_id": session_id},
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
