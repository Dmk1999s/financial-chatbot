from django.urls import path
from .views import chat_with_gpt, api_index_opensearch, end_chat_session, recommend_products
from .views_async import get_task_status

urlpatterns = [
    # 챗봇 관련
    path('chat/', chat_with_gpt, name='chat_with_gpt'), # (1) 챗봇 서비스 시작
    path('task/<str:task_id>/', get_task_status, name='get_task_status'), # (2) 챗봇과 대화
    path('session/<str:session_id>/end/', end_chat_session, name='end_chat_session'), # (3) 챗봇 세션 종료
    
    # RAG 관련
    path('recommend/', recommend_products, name='recommend_products'),
    path('opensearch/index/', api_index_opensearch, name='api_index_opensearch'),
]