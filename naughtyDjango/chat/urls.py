from django.urls import path
from .views import chat_with_gpt, get_chat_history, save_investment_profile

urlpatterns = [
    path("chat/", chat_with_gpt, name="chat_with_gpt"),
    path("history/<str:username>/", get_chat_history, name="get_chat_history"),
    path("save_data/", save_investment_profile, name="save_investment_profile"),
]
