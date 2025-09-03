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
from chat.gpt_service import SESSION_TEMP_STORE

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

        # profile 업로드
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
                        
                        SESSION_TEMP_STORE["conflict_pending"] = {field: value}
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
        
        if result.ready():
            if result.successful():
                task_result = result.get()
                
                if task_result.get("type") == "conflict_detected":
                    field = task_result.get("field")
                    value = task_result.get("value")
                    
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
        if session_id in SESSION_TEMP_STORE:
            del SESSION_TEMP_STORE[session_id]
        
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
