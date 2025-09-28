from main.models import User
from django.core.cache import cache
from typing import Optional


SESSION_TTL = 3600  # 1시간
def set_session_data(session_id: str, data: dict) -> None:
    cache.set(_session_key(session_id), data, timeout=SESSION_TTL)

def _session_key(session_id: str) -> str:
    return f"chat:session:{session_id}"


def get_session_data(session_id: str) -> dict:
    return cache.get(_session_key(session_id)) or {}


def set_session_data(session_id: str, data: dict) -> None:
    cache.set(_session_key(session_id), data, timeout=None)


def delete_session_data(session_id: str) -> None:
    cache.delete(_session_key(session_id))


def get_conflict_pending() -> Optional[dict]:
    return cache.get("chat:conflict_pending")


def set_conflict_pending_cache(data: dict) -> None:
    cache.set("chat:conflict_pending", data, timeout=600)


def pop_conflict_pending() -> Optional[dict]:
    data = cache.get("chat:conflict_pending")
    if data is not None:
        cache.delete("chat:conflict_pending")
    return data


def load_user_profile_to_session(user_id: str, session_id: str):
    """
    대화 시작 시, DB에 저장된 사용자 프로필을
    세션 캐시로 미리 불러옵니다.
    """
    try:
        user = User.objects.get(email=user_id)
        session_data = get_session_data(session_id)

        # User 모델 필드와 세션 키를 매핑
        profile_data = {
            "age": user.age,
            "risk_tolerance": user.risk_tolerance,
            "income_stability": user.income_stability,
            "income_sources": user.income_source,
            "monthly_income": user.income,
            "investment_horizon": user.period,
            "expected_return": user.expected_income,
            "expected_loss": user.expected_loss,
            "investment_purpose": user.purpose,
            "value_growth": user.value_growth,
            "risk_acceptance_level": user.risk_acceptance_level,
            "investment_concern": user.investment_concern,
            "asset_allocation_type": user.asset_allocation_type
        }

        # 값이 있는 항목만 세션 데이터에 업데이트
        for key, value in profile_data.items():
            if value is not None:
                session_data[key] = value

        set_session_data(session_id, session_data)
        print(f"✅ Profile loaded for session {session_id}")

    except User.DoesNotExist:
        print(f"ℹ️ New user session {session_id}, starting with empty profile.")
    except Exception as e:
        print(f"❗️Error loading profile for session {session_id}: {e}")