# chat/rag/agent.py

import os
import logging
from openai import OpenAI
from dotenv import load_dotenv

# 각 Tool의 실제 실행 함수들을 모두 import 합니다.
from .retriever_chain import run_rag_chain
from .screener_tool import run_stock_screener
from .profile_tool import get_profile_summary
from .lookup_tool import run_specific_stock_lookup
from chat.gpt_service import handle_chitchat

logger = logging.getLogger(__name__)
load_dotenv()


def route_query(query: str, session_id: str) -> str:
    """
    LLM을 라우터로 사용하여 사용자 질문의 의도를 파악하고,
    필요 시 여러 함수를 순차적으로 호출하여 답변을 생성합니다.
    """
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # --- 1단계: 프로필 컨텍스트 확보 (기존 로직 유지) ---
    profile_keywords = ["내 프로필", "내 정보", "나를 기반으로", "제 정보", "제 프로필"]
    uses_profile = any(keyword in query for keyword in profile_keywords)
    profile_context = ""
    if uses_profile:
        profile_context = get_profile_summary(query, session_id)
        logger.info(f"Profile context retrieved for query: {query}")

    # --- 2단계: 라우팅 프롬프트 수정 (복수 의도 탐지) ---
    routing_prompt = f"""
    사용자 질문의 의도를 분석하여, 아래 키워드 중 관련된 모든 것을 쉼표(,)로 구분하여 나열하세요.
    만약 해당하는 의도가 없다면 'chitchat'만 반환하세요. 순서는 중요하지 않습니다.

    [키워드 목록]
    - profile_summary: 사용자가 자신의 프로필, 입력한 정보 등 '자신'에 대해 물어볼 때.
      (예: "내 정보 알아?", "내가 입력한 내용 요약해줘", "내 월 소득 알려줘")
    - stock_screener: 'PBR', 'PER', '가치주' 등 특정 조건에 맞는 '여러 주식 목록'을 찾아달라고 할 때.
      (예: "PBR 1 미만 주식 찾아줘", "안정적인 성장주 추천해줘")
    - specific_stock_lookup: '삼성전자', '애플'처럼 '특정 회사 이름 하나'를 언급하며 '현재가', '주가', '정보' 등을 물어볼 때.
      (예: "삼성전자 주가 알려줘", "테슬라 PBR 얼마야?")
    - financial_recommendation: '주식' 외 다른 금융 상품(예금, 적금, 연금)을 추천해달라고 하거나,
      의미가 복합적인 추천 질문일 때.
      (예: "신한은행 예금 추천해줘", "20대 사회초년생에게 맞는 투자 상품 알려줘")
    - chitchat: 위 네 가지에 해당하지 않는 모든 일반 대화, 인사, 잡담.

    [사용자 질문]: {query}
    [분류]:
    """

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": routing_prompt}],
        temperature=0,
        max_tokens=50
    )
    intents_str = (response.choices[0].message.content or "chitchat").strip().lower()
    intents = [intent.strip() for intent in intents_str.split(',')]
    logger.info(f"Query: '{query}' -> Routed to intents: {intents}")

    # --- 3단계: 복수 의도 처리 로직 ---
    tool_outputs = {}

    # chitchat이 유일한 의도가 아닐 경우, 다른 의도 먼저 처리
    if "chitchat" in intents and len(intents) > 1:
        intents.remove("chitchat")

    if not intents or intents == ['chitchat']:
        return handle_chitchat(query)

    for intent in intents:
        if intent == "profile_summary":
            tool_outputs["profile_summary"] = get_profile_summary(query, session_id)
        elif intent == "specific_stock_lookup":
            tool_outputs["specific_stock_lookup"] = run_specific_stock_lookup(query)
        elif intent == "stock_screener":
            enriched_query = (
                f"{query}\n\n[사용자 프로필 참고]\n{profile_context}"
                if uses_profile else query
            )
            tool_outputs["stock_screener"] = run_stock_screener(enriched_query)
        elif intent == "financial_recommendation":
            enriched_query = (
                f"{query}\n\n[사용자 프로필 참고]\n{profile_context}"
                if uses_profile else query
            )
            tool_outputs["financial_recommendation"] = run_rag_chain(enriched_query)

    # --- 4단계: 결과 종합 및 최종 답변 생성 ---
    combined_tool_output = "\n\n".join(
        f"[{tool_name} 결과]:\n{output}"
        for tool_name, output in tool_outputs.items()
    )
    return _format_final_answer(query, combined_tool_output)


def _format_final_answer(query, tool_output):
    """Tool의 결과를 받아 사용자에게 보여줄 최종 답변으로 가공합니다."""
    if not tool_output:
        return "죄송합니다, 요청하신 내용에 대한 답변을 생성할 수 없습니다."

    final_prompt = f"""
    당신은 전문 금융 애널리스트이자 친절한 상담원입니다.
    사용자의 [요청 질문]에 대해, 아래 [분석 결과]를 종합하여 하나의 자연스러운 답변으로 생성해주세요.

    # 지침:
    - 각 분석 결과를 모두 반영하여 완전한 답변을 만드세요.
    - 만약 특정 정보(예: 사용자 정보)를 찾지 못했다면, 그 사실을 명확히 언급해주세요.
    - 결과를 친절하고 명확한 문장으로 설명하며 시작하세요.
    - 리스트 형태의 데이터는 글머리 기호(-)를 사용하여 보기 좋게 정리해주세요.
    - 답변에는 '\\n' 같은 줄바꿈 제어 문자를 절대 포함하지 마세요.
    - 최종 답변은 완결된 하나의 문단이나 글로 제공되어야 합니다.

    [요청 질문]: {query}
    [분석 결과]: {tool_output}
    [최종 답변]:
    """

    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    final_resp = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.1,
        max_tokens=1000,
    )
    return (final_resp.choices[0].message.content or "").strip()


# services.py에서 이 함수를 호출하도록 run_agent 이름을 유지합니다.
run_agent = route_query
