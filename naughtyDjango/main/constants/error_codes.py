from rest_framework import status

class GeneralErrorCode:
    BAD_REQUEST = ("COMMON400", "잘못된 요청입니다.", status.HTTP_400_BAD_REQUEST)
    UNAUTHORIZED = ("COMMON401", "인증이 필요합니다.", status.HTTP_401_UNAUTHORIZED)
    FORBIDDEN = ("COMMON403", "접근이 금지되었습니다.", status.HTTP_403_FORBIDDEN)
    NOT_FOUND = ("COMMON404", "요청한 자원을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    INTERNAL_SERVER_ERROR = ("COMMON500", "서버 내부 오류가 발생했습니다.", status.HTTP_500_INTERNAL_SERVER_ERROR)
