# chat/rag/agent.py

import os
import logging
from openai import OpenAI
from dotenv import load_dotenv
import json
from chat.opensearch_client import search_financial_products

# 각 Tool의 실제 실행 함수들을 모두 import 합니다.
from .retriever_chain import run_rag_chain, _detect_product_type_ko
from .screener_tool import run_stock_screener
from .profile_tool import get_profile_summary
from .lookup_tool import run_specific_stock_lookup
from chat.gpt_service import handle_chitchat

logger = logging.getLogger(__name__)
load_dotenv()

ALLOWED_TYPES = {"예금", "적금", "연금", "국내주식", "해외주식"}
GENERIC_FIN_KEYWORDS = ["금융 상품", "금융상품", "투자 상품", "투자상품", "상품 추천", "무슨 금융", "어떤 금융", "무슨 투자", "어떤 투자"]

def route_query(query: str, session_id: str) -> str:
    """
    LLM을 라우터로 사용하여 사용자 질문의 의도를 파악하고,
    필요 시 여러 함수를 순차적으로 호출하여 답변을 생성합니다.
    """
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # --- 1단계: 프로필 컨텍스트 확보 (기존 로직 유지) ---
    profile_keywords = [
        "내 프로필", "내 정보", "나를 기반으로", "제 정보", "제 프로필",
        "내 프로필을 기반", "내 정보를 기반", "내 정보를 바탕", "프로필 기반", "나를 바탕"
    ]
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

    # 모호한 '금융 상품'류 표현이면 반드시 financial_recommendation 포함
    if any(k in query.lower() for k in GENERIC_FIN_KEYWORDS):
        if "financial_recommendation" not in intents:
            intents.append("financial_recommendation")

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
            enriched_query = (f"{query}\n\n[사용자 프로필 참고]\n{profile_context}" if uses_profile else query)
            detected = _detect_product_type_ko(enriched_query)

            if detected:
                tool_outputs["financial_recommendation"] = run_rag_chain(enriched_query)
            else:
                decision = _decide_product_types(enriched_query, profile_context)
                types = decision.get("product_types", [])
                k = int(decision.get("top_k_per_type", 4))

                hits = []
                for t in types:
                    _hits = search_financial_products(query=enriched_query, top_k=k, product_type=t) or []
                    for h in _hits:
                        h.setdefault("product_type", t)
                    hits.extend(_hits)

                # 폴백: 0건이면 위험성향 기반 기본 타입으로 재시도
                if not hits:
                    fb = _fallback_decision(enriched_query, profile_context)
                    for t in fb.get("product_types", []):
                        _hits = search_financial_products(query=enriched_query, top_k=k, product_type=t) or []
                        for h in _hits:
                            h.setdefault("product_type", t)
                        hits.extend(_hits)

                if hits:
                    ctx = json.dumps(hits, ensure_ascii=False, indent=2)
                    prompt = f"""당신은 금융상담사입니다.
        아래 후보를 카테고리별로 2~3문장씩 요약해 추천해주세요.
        - 왜 이 카테고리를 권하는지 '결정 이유'를 먼저 2문장으로 설명
        - 숫자는 원문 값만 사용(추정 금지)
        [결정 이유] {decision.get('reason', '')}
        [후보]
        {ctx}"""
                    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                    out = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=1200
                    )
                    tool_outputs["financial_recommendation"] = out.choices[0].message.content
                else:
                    tool_outputs["financial_recommendation"] = "조건에 맞는 후보를 찾지 못했습니다."

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

def _decide_product_types(query: str, profile_context: str) -> dict:
    prompt = f"""
아래 사용자 질문과 프로필 요약을 보고, 추천할 금융 카테고리(예금/적금/연금/국내주식/해외주식) 중 1~3개를 고르세요.
반드시 JSON만, 그리고 허용 리스트에 있는 값만 돌려주세요. 최소 1개는 반드시 포함하세요.

허용 리스트: ["예금","적금","연금","국내주식","해외주식"]

[사용자 질문]
{query}

[프로필 요약(없으면 '없음')]
{profile_context or '없음'}

반환 형식 예시:
{{"product_types": ["연금","국내주식"], "reason": "장기·중간위험 → 연금/국내", "top_k_per_type": 4}}
"""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=200
    )
    text = (r.choices[0].message.content or "").strip()

    try:
        raw = json.loads(text)
        types = _normalize_types(raw.get("product_types", []))
        if not types:
            return _fallback_decision(query, profile_context)
        return {
            "product_types": types,
            "reason": raw.get("reason", ""),
            "top_k_per_type": raw.get("top_k_per_type", 4)
        }
    except Exception:
        return _fallback_decision(query, profile_context)


def _normalize_types(types):
    mapping = {
        "예금": "예금", "정기예금": "예금", "deposit": "예금",
        "적금": "적금", "정기적금": "적금", "savings": "적금",
        "연금": "연금", "연금저축": "연금", "연금보험": "연금", "irp": "연금", "annuity": "연금",
        "국내주식": "국내주식", "국내 주식": "국내주식", "주식": "국내주식",
        "해외주식": "해외주식", "해외 주식": "해외주식", "미국주식": "해외주식", "nasdaq": "해외주식", "us": "해외주식",
        "금융상품": None, "금융 상품": None
    }
    norm = []
    for t in (types or []):
        key = str(t).strip().lower()
        mapped = mapping.get(key, None)
        if mapped in ALLOWED_TYPES and mapped not in norm:
            norm.append(mapped)
    return norm[:3]  # 최대 3개까지만

def _fallback_decision(query: str, profile_context: str) -> dict:
    txt = f"{query}\n{profile_context or ''}".lower()
    # 위험 성향 추정 (아주 단순 휴리스틱)
    risk = "중간"
    if any(k in txt for k in ["낮음", "보수", "안정"]):
        risk = "낮음"
    elif any(k in txt for k in ["높음", "공격", "적극"]):
        risk = "높음"

    # 주식 언급 시 우선 처리
    if "주식" in txt:
        if any(k in txt for k in ["해외", "미국", "나스닥", "nasdaq", "us"]):
            types = ["해외주식"]
            reason = "질문에 주식(해외) 선호 표현이 있어 해외주식을 우선 고려"
        else:
            types = ["국내주식"]
            reason = "질문에 주식 선호 표현이 있어 국내주식을 우선 고려"
        # 보조 카테고리 추가
        if risk == "낮음":
            types += ["연금", "적금"]
        elif risk == "중간":
            types += ["연금", "국내주식"]
        else:
            types += ["해외주식", "연금"]
        return {"product_types": list(dict.fromkeys(types))[:3], "reason": reason, "top_k_per_type": 4}

    # 일반 금융상품(비특정)일 때 위험 성향 기반
    if risk == "낮음":
        types = ["예금", "적금", "연금"]
        reason = "보수적/안정 성향으로 예금·적금·연금 우선"
    elif risk == "중간":
        types = ["적금", "연금", "국내주식"]
        reason = "중간 성향으로 적금·연금·국내주식 균형"
    else:
        types = ["국내주식", "해외주식", "연금"]
        reason = "공격 성향으로 주식 비중을 높이고 연금 보조"
    return {"product_types": types, "reason": reason, "top_k_per_type": 4}


# services.py에서 이 함수를 호출하도록 run_agent 이름을 유지합니다.
run_agent = route_query
