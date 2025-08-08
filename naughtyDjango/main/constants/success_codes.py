from rest_framework import status

class GeneralSuccessCode:
    OK = ("COMMON200", "성공적으로 처리했습니다.", status.HTTP_200_OK)
    CREATED = ("COMMON201", "성공적으로 생성했습니다.", status.HTTP_201_CREATED)
    NO_CONTENT = ("COMMON204", "성공했지만 콘텐츠는 없습니다.", status.HTTP_204_NO_CONTENT)
    
    CONFLICTS = ("COMMON2001", "프로필 변경이 감지되었습니다.", status.HTTP_200_OK)
