import os
from functools import lru_cache
from langchain.callbacks.tracers import LangChainTracer
from langchain_core.callbacks import CallbackManager

@lru_cache(maxsize=1024)
def _project_name():
    return os.getenv("LANGCHAIN_PROJECT", "naughty-default")

def get_callback_manager(session_id: str | None = None) -> CallbackManager | None:
    # LANGSMITH(구 LangChain tracing) 비활성 환경이면 None
    if not os.getenv("LANGCHAIN_API_KEY"):
        return None

    tracer = LangChainTracer(project=_project_name())
    tags = []
    if session_id:
        tags.append(f"session:{session_id}")
    # 환경변수로 공통 태그 추가(옵션): LANGSMITH_TAGS="prod,finbot"
    if os.getenv("LANGSMITH_TAGS"):
        tags += [t.strip() for t in os.getenv("LANGSMITH_TAGS").split(",") if t.strip()]
    tracer.tags = tags

    return CallbackManager([tracer])