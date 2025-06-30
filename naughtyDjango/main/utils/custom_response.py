from rest_framework.response import Response

class CustomResponse(Response):
    def __init__(self, is_success: bool, code: str, message: str, result=None, status=None):
        data = {
            "isSuccess": is_success,
            "code": code,
            "message": message,
            "result": result
        }
        super().__init__(data, status=status)

class BadRequestException(Exception):
    def __init__(self, message="잘못된 요청입니다."):
        self.message = message
        super().__init__(self.message)