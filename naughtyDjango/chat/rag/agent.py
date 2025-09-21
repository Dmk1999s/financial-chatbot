# chat/rag/agent.py
"""
툴-퍼스트(Agent-first) 구조의 금융 상담 에이전트.

- 에이전트가 Tool 설명을 바탕으로 어떤 툴을 언제/how 호출할지 스스로 결정.
- create_*_tool 팩토리로 만든 도구들을 등록.
- OpenAI Functions 제약: tool.name 은 ^[a-zA-Z0-9_-]+$ 여야 하므로
  빌더에서 자동으로 이름을 정규화(_sanitize_tool_names)한다.
"""

import os
import re
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, AgentType

# 기존 Tool 팩토리 재사용
from .profile_tool import create_profile_summary_tool
from .screener_tool import create_stock_recommender_tool
from .lookup_tool import create_stock_lookup_tool
from .retriever_chain import create_self_query_rag_tool

load_dotenv()

SYSTEM_MSG = (
    "당신은 금융 상담 에이전트입니다. 제공된 도구를 꼭 활용해 답하세요. "
    "사용자가 추천, 상품, 프로필 기반 추천을 요청하면 다음 중 최소 1개 도구를 반드시 호출하세요: "
    "`financial_product_recommender`, `stock_screener`. "
    "결과는 한국어로 친절하고 간결하게 정리하세요."
)

def _sanitize_tool_names(tools):
    """
    OpenAI Functions 제약 충족: tool.name 은 ^[a-zA-Z0-9_-]+$ 만 허용.
    - 공백/특수문자 → '_' 로 치환
    - 소문자 통일
    - 중복 시 접미사로 고유화
    """
    seen = set()
    sanitized = []
    for i, t in enumerate(tools):
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", (t.name or f"tool_{i}")).strip("_").lower()
        if not safe:
            safe = f"tool_{i}"
        base = safe
        k = 1
        while safe in seen:
            safe = f"{base}_{k}"
            k += 1
        t.name = safe
        seen.add(safe)
        sanitized.append(t)
    return sanitized

def build_finrec_agent(session_id: str):
    """
    금융 상담 에이전트 인스턴스를 생성한다.
    - 함수콜 기반 에이전트(OPENAI_FUNCTIONS)로 Tool 사용 신뢰성을 높임
    - 반복 폭주 방지를 위해 max_iterations 제한
    - Tool 이름 자동 정규화
    """
    tools = [
        create_profile_summary_tool(session_id),
        create_stock_recommender_tool(),
        create_stock_lookup_tool(),
        create_self_query_rag_tool(),
    ]
    tools = _sanitize_tool_names(tools)

    llm = ChatOpenAI(
        model=os.getenv("OPENAI_AGENT_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )

    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.OPENAI_FUNCTIONS,
        verbose=False,
        max_iterations=4,
        agent_kwargs={"system_message": SYSTEM_MSG},
        handle_parsing_errors="죄송합니다. 다시 시도해 주세요.",
        return_intermediate_steps=False,
    )
    return agent

def run_agent(query: str, session_id: str) -> str:
    """
    외부에서 호출하는 진입점.
    - 서비스 레이어(RecommendationService)에서 이 함수를 호출한다.
    """
    agent = build_finrec_agent(session_id)
    try:
        result = agent.invoke({"input": query})
        if isinstance(result, dict):
            return (result.get("output") or "").strip()
        return str(result).strip()
    except Exception as e:
        return f"에이전트를 실행하는 중 오류가 발생했어요: {e}"