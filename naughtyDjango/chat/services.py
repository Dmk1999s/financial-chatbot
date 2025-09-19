# chat/services.py
import os
import io
from typing import Dict, Optional, Tuple
from chat.rag.retriever_chain import run_rag_chain
from openai import OpenAI
from django.core.management import call_command
from chat.models import ChatMessage
from main.models import User
from chat.gpt_service import handle_chitchat
from chat.gpt.session_store import set_conflict_pending_cache
from chat.rag.agent import run_agent
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
        set_conflict_pending_cache({field: value})


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
    @staticmethod
    def recommend_or_chitchat(username: str, session_id: str, query: str) -> Tuple[str, str]:
        # run_agent를 호출할 때 session_id를 함께 전달합니다.
        response_text = run_agent(query=query, session_id=session_id)

        intent = "agent_processed"
        product_type = "recommend_or_general"

        ChatMessage.objects.create(session_id=session_id, username=username, role="user", message=query)
        ChatMessage.objects.create(session_id=session_id, username=username, product_type=product_type, role="assistant", message=response_text)

        return response_text, intent

class OpenSearchService:
    """Utility wrapper for OpenSearch indexing."""

    @staticmethod
    def index_now() -> str:
        buf = io.StringIO()
        call_command('index_to_opensearch', stdout=buf)
        return buf.getvalue()
