"""
URL configuration for naughtyDjango project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include, re_path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

# 스웨거 설정
schema_view = get_schema_view(
    openapi.Info(
        title="NauhtyComputer Django API 문서",
        default_version='v1',
        description="컴퓨터가 말을 안드류 팀의 Django API 명세서입니다.",
        terms_of_service="https://www.nauhtydjango.cloud/terms/",
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
    url='https://nauhtydjango.cloud',
    #authentication_classes=[],
)

urlpatterns = [
    #path('admin/', admin.site.urls),
    path('chats/', include('chat.urls')),

    # 헬스체킹용 urlk
    path('', lambda request: HttpResponse("Hello from Django!")),

    # Swagger 설정
    re_path(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]
