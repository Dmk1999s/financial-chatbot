from django.urls import path
from .views import chat_with_gpt, get_chat_history, save_investment_profile
from .views import recommend_products
from .views import product_search
from .views import api_index_opensearch
from .views import api_search_opensearch
urlpatterns = [
    path("chats/", chat_with_gpt, name="chat_with_gpt"),
    path("histories/<int:id>/", get_chat_history, name="get_chat_history"),
    path("datas/", save_investment_profile, name="save_investment_profile"),
    path("recommend/", recommend_products, name="recommend_products"),
    path("search/stock/", product_search, name="product_search"),
    path('api/opensearch/index/',  api_index_opensearch, name='api_index_opensearch'),
    path('api/opensearch/search/', api_search_opensearch, name='api_search_opensearch'),
]
