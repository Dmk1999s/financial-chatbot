# chat/services.py
import os
import json
import io
from typing import Dict, Optional, Tuple

from openai import OpenAI
from django.core.management import call_command

from chat.models import ChatMessage
from chat.gpt_service import get_session_id
from main.utils.custom_response import CustomResponse
from main.constants.error_codes import GeneralErrorCode
from main.constants.success_codes import GeneralSuccessCode
from main.models import User
from chat.management.commands.opensearch_recommender import recommend_with_knn
from chat.gpt_service import handle_chitchat
import logging


class ChatService:
    """Encapsulates business logic for chat interactions."""

    SIMPLE_RESPONSES = {
        '안녕': '안녕하세요! 무엇을 도와드릴까요?',
        '네': '네, 말씀해 주세요.',
        '아니오': '알겠습니다. 다른 도움이 필요하시면 말씀해 주세요.',
    }

    @staticmethod
    def get_or_validate_user(username: str) -> Optional[User]:
        try:
            return User.objects.get(email=username)
        except User.DoesNotExist:
            return None

    @staticmethod
    def save_user_message(session_id: str, username: str, message: str, product_type: str = "") -> None:
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="user",
            message=message,
        )

    @staticmethod
    def save_assistant_message(session_id: str, username: str, message: str, product_type: str = "") -> None:
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="assistant",
            message=message,
        )

    @classmethod
    def maybe_quick_reply(cls, message: str) -> Optional[str]:
        key = (message or "").lower()
        return cls.SIMPLE_RESPONSES.get(key)

    @staticmethod
    def set_conflict_pending(field: str, value):
        SESSION_TEMP_STORE["conflict_pending"] = {field: value}


class ProfileService:
    """Handles reading/writing user investment profile details."""

    @staticmethod
    def save_profile(user: User, profile: Dict) -> None:
        user.risk_tolerance = profile.get("risk_tolerance")
        user.age = profile.get("age")
        user.income_stability = profile.get("income_stability")
        user.income_source = profile.get("income_sources")
        user.income = profile.get("monthly_income")
        user.expected_income = profile.get("expected_return")
        user.expected_loss = profile.get("expected_loss")
        user.purpose = profile.get("investment_purpose")
        user.save()


class RecommendationService:
    """Routes recommendation vs smalltalk and persists messages."""

    @staticmethod
    def classify_intent(query: str) -> str:
        prompt = f"""
        사용자의 질문 의도를 "상품추천" 또는 "일반대화" 둘 중 하나로 분류하세요.
        오직 키워드 하나만 답변해야 합니다.

        질문: "{query}"
        분류:
        """
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        return (resp.choices[0].message.content or "").strip()

    @staticmethod
    def recommend_or_chitchat(username: str, session_id: str, query: str, top_k: int) -> Tuple[str, str]:
        intent = RecommendationService.classify_intent(query)
        if "상품추천" in intent:
            response_text = recommend_with_knn(query=query, top_k=top_k)
            product_type = "recommend"
        else:
            response_text = handle_chitchat(query)
            product_type = "general"
        # persist messages
        ChatMessage.objects.create(session_id=session_id, username=username, role="user", message=query)
        ChatMessage.objects.create(session_id=session_id, username=username, product_type=product_type, role="assistant", message=response_text)
        # intent도 함께 반환하여 로깅에 활용
        return response_text, ("상품추천" if "상품추천" in intent else "일반대화")


class OpenSearchService:
    """Utility wrapper for OpenSearch indexing."""

    @staticmethod
    def index_now() -> str:
        buf = io.StringIO()
        call_command('index_to_opensearch', stdout=buf)
        return buf.getvalue()
