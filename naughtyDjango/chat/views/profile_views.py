# chat/views/profile_views.py
import json
from dotenv import load_dotenv
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from main.models import User
from main.utils.custom_response import CustomResponse
from main.constants.error_codes import GeneralErrorCode
from main.constants.success_codes import GeneralSuccessCode
from chat.services import ProfileService

load_dotenv()

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
        ProfileService.save_profile(user, profile)
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
