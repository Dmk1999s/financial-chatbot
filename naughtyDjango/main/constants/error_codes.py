from rest_framework import status

class GeneralErrorCode:
    BAD_REQUEST = ("COMMON400", "잘못된 요청입니다.", status.HTTP_400_BAD_REQUEST)
    UNAUTHORIZED = ("COMMON401", "인증이 필요합니다.", status.HTTP_401_UNAUTHORIZED)
    FORBIDDEN = ("COMMON403", "접근이 금지되었습니다.", status.HTTP_403_FORBIDDEN)
    NOT_FOUND = ("COMMON404", "요청한 자원을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    INTERNAL_SERVER_ERROR = ("COMMON500", "서버 내부 오류가 발생했습니다.", status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 채팅 관련 에러
    NOT_CONFLICTS = ("CHAT4000", "충돌 데이터를 찾을 수 없습니다.", status.HTTP_400_BAD_REQUEST)
    TASK_NOT_FOUND = ("CHAT4001", "작업을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    TASK_FAILED = ("CHAT4002", "작업 처리에 실패했습니다.", status.HTTP_500_INTERNAL_SERVER_ERROR)
    USER_NOT_FOUND = ("USER4000", "사용자를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    MESSAGE_REQUIRED = ("CHAT4003", "메시지가 필요합니다.", status.HTTP_400_BAD_REQUEST)
