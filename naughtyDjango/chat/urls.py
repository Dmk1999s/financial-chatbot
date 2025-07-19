from django.http import HttpResponse
from django.urls import path
from .views import chat_with_gpt, get_chat_history, save_investment_profile
from .views import recommend_products
urlpatterns = [
    path("", chat_with_gpt, name="chat_with_gpt"),
    #path("histories/<int:id>/", get_chat_history, name="get_chat_history"),
    #path("datas/", save_investment_profile, name="save_investment_profile"),
    path("recommend/", recommend_products, name="recommend_products"),
]