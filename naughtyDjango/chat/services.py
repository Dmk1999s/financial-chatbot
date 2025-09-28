# chat/services.py
import re
from typing import Dict, Optional, Tuple

from chat.gpt_service import handle_chitchat
from chat.models import ChatMessage
from main.models import User
from chat.gpt.session_store import set_conflict_pending_cache
from chat.rag.agent import run_agent
from celery.result import AsyncResult

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
    def _looks_like_smalltalk(q: str) -> bool:
        ql = (q or "").strip().lower()
        return ql in {"안녕", "안녕하세요", "하이", "ㅎㅇ", "고마워", "감사", "뭐해", "테스트"}

    @staticmethod
    def _asks_realtime_quote(q: str) -> bool:
        ql = (q or "").lower()
        # 실시간/당일/현재가·호가 키워드
        realtime_keywords = [
            "실시간", "지금", "현재가", "주가", "호가", "틱", "오늘 가격", "오늘 주가",
            "금일", "분봉", "초봉"
        ]
        tickers = re.findall(r"[A-Z]{1,5}", q)  # 간단 티커 패턴(해외)
        return any(k in ql for k in realtime_keywords) or bool(tickers and ("주가" in ql or "현재" in ql))

    @staticmethod
    def recommend_or_chitchat(username: str, session_id: str, query: str) -> Tuple[str, str]:
        # 1) 초저비용 프리-체크: 잡담
        if RecommendationService._looks_like_smalltalk(query):
            reply = handle_chitchat(query)
            ChatMessage.objects.create(session_id=session_id, username=username, role="user", message=query)
            ChatMessage.objects.create(session_id=session_id, username=username, product_type="chitchat", role="assistant", message=reply)
            return reply, "quick_chitchat"

        # 2) 초저비용 프리-체크: 실시간 시세 거절
        if RecommendationService._asks_realtime_quote(query):
            msg = (
                "실시간 시세(현재가/호가/당일)는 제공하지 않아요. "
                "대신 저장된 재무 지표(PER/PBR/EPS)나 조건 스크리너는 도와드릴 수 있어요.\n"
                "예) '국내 PBR 1 미만 상위 5개', '삼성전자 정보(지표) 알려줘'"
            )
            ChatMessage.objects.create(session_id=session_id, username=username, role="user", message=query)
            ChatMessage.objects.create(session_id=session_id, username=username, product_type="realtime_refusal", role="assistant", message=msg)
            return msg, "quick_refusal"

        # 3) 나머지는 에이전트(툴-퍼스트)에게 위임
        response_text = run_agent(query=query, session_id=session_id)
        intent = "agent_tool_first"

        ChatMessage.objects.create(session_id=session_id, username=username, role="user", message=query)
        ChatMessage.objects.create(session_id=session_id, username=username, product_type="recommend_or_general", role="assistant", message=response_text)

        return response_text, intent

class OpenSearchService:
    """Utility wrapper for OpenSearch indexing."""

    @staticmethod
    def index_async() -> str:
        """Enqueue indexing as a Celery task and return task_id."""
        from chat.tasks import index_financial_products
        async_result = index_financial_products.delay()
        return async_result.id

    @staticmethod
    def index_status(task_id: str) -> dict:
        """Query celery task status/result."""
        r = AsyncResult(task_id)
        data = {"task_id": task_id, "state": r.state}
        if r.failed():
            data["error"] = str(r.result)
        elif r.successful():
            data["result"] = r.result  # index_to_opensearch 출력
        return data