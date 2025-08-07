from celery.result import AsyncResult
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from main.utils.custom_response import CustomResponse
from main.constants.success_codes import GeneralSuccessCode
from main.constants.error_codes import GeneralErrorCode

@api_view(["GET"])
@permission_classes([AllowAny])
def get_task_status(request, task_id):
    """Get async task status and result"""
    try:
        result = AsyncResult(task_id)
        
        if result.ready():
            if result.successful():
                task_result = result.get()
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
                    code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
                    message="Task failed",
                    result={"status": "failed", "error": str(result.info)},
                    status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2],
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
        return CustomResponse(
            is_success=False,
            code=GeneralErrorCode.INTERNAL_SERVER_ERROR[0],
            message=str(e),
            result={},
            status=GeneralErrorCode.INTERNAL_SERVER_ERROR[2],
        )