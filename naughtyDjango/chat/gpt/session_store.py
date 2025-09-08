from django.core.cache import cache
from typing import Optional


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


