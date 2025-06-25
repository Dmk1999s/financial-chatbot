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
