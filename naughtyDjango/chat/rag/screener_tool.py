# chat/rag/screener_tool.py
import os
import re
from typing import Dict, List, Tuple
from langchain.tools import Tool
from chat.opensearch_client import OPENSEARCH_CLIENT as default_os_client
from opensearchpy import OpenSearch, exceptions as os_exceptions

INDEX = os.getenv("OPENSEARCH_INDEX", "financial-products")

def _get_os_client():
    env = os.getenv("ENVIRONMENT", "production")
    if env == "local":
        # ✅ 로컬 터널(https://localhost:9200)용 클라이언트
        return OpenSearch(
            hosts=[{"host": "localhost", "port": 9200}],
            http_auth=(os.getenv("OPENSEARCH_USER"), os.getenv("OPENSEARCH_PASS")),
            use_ssl=True, verify_certs=False, ssl_assert_hostname=False, timeout=60
        )
    # ✅ 서버(IAM 등)용 기본 클라이언트
    return default_os_client

# --- 유틸: 질의에서 시장/필드명 추론 (국내/해외에 따라 per/pbr 필드명이 다름) ---
def _infer_market_and_fields(query: str) -> Dict[str, str]:
    q = query.lower()
    is_overseas = any(k in q for k in ["해외", "미국", "nasdaq", "us", "나스닥"])
    if is_overseas:
        return {
            "product_type": "해외주식",
            "pbr": "pbrx",
            "per": "perx",
            "eps": "epsx",
            "name": "prdt_abrv_name",
            "code": "code",
            "extra_sector": "e_icod",
        }
    else:
        return {
            "product_type": "국내주식",
            "pbr": "pbr",
            "per": "per",
            "eps": "eps",
            # [수정] 두 가지 이름 필드를 모두 사용하도록 추가
            "name": "bstp_kor_isnm",
            "name_alt": "prdt_abrv_name",  # 종목 약식명 필드 추가
            "code": "stck_shrn_iscd",
            "extra_sector": None,
        }

# --- 유틸: Top N 추출 ---
def _extract_topn(query: str, default_n: int = 5) -> int:
    m = re.search(r"(상위|top)\s*(\d+)", query, flags=re.I)
    if m:
        return max(1, min(50, int(m.group(2))))  # 과도한 N 방지
    m2 = re.search(r"(\d+)\s*개", query)
    if m2:
        return max(1, min(50, int(m2.group(1))))
    return default_n

# --- 프리셋 규칙: 장기 안정/가치/성장 등 ---
def _preset_from_query(query: str, fields: Dict[str, str]) -> Tuple[List[dict], List[dict]]:
    """
    반환: (filters, sorts)
    - filters: OpenSearch bool.filter 배열 요소들
    - sorts:   OpenSearch sort 스펙 배열
    """
    pbr_f, per_f, eps_f = fields["pbr"], fields["per"], fields["eps"]
    q = query.lower()

    # 1) 장기적으로 안정적인/보수적/배당/바이앤홀드 등 키워드
    if any(k in q for k in ["장기", "안정", "보수", "defensive", "바이앤홀드", "리스크 낮", "변동성 낮"]):
        filters = [
            {"term": {"product_type": fields["product_type"]}},
            {"range": {eps_f: {"gt": 0}}},                # 이익 양수
            {"range": {pbr_f: {"gte": 0.5, "lte": 2.0}}}, # 과도하게 낮거나 높은 PBR 배제
            {"range": {per_f: {"gte": 5, "lte": 20}}},    # 너무 낮은 PER(디스트레스)·너무 높은 PER(고성장) 배제
        ]
        sorts = [
            {pbr_f: {"order": "asc"}},
            {per_f: {"order": "asc"}},
            {eps_f: {"order": "desc"}},
        ]
        return filters, sorts

    # 2) 가치/저평가(PBR 낮은/1 미만 등)
    if any(k in q for k in ["가치", "저평가", "pbr 1", "낮은 pbr", "value"]):
        filters = [
            {"term": {"product_type": fields["product_type"]}},
            {"range": {pbr_f: {"gte": 0, "lt": 1.0}}},
            {"range": {eps_f: {"gt": 0}}},
        ]
        sorts = [
            {pbr_f: {"order": "asc"}},
            {per_f: {"order": "asc"}},
            {eps_f: {"order": "desc"}},
        ]
        return filters, sorts

    # 3) 성장주 선호 (PER 다소 높아도 수용)
    if any(k in q for k in ["성장", "growth", "모멘텀"]):
        filters = [
            {"term": {"product_type": fields["product_type"]}},
            {"range": {eps_f: {"gt": 0}}},              # 실적 양수
            {"range": {per_f: {"gte": 15, "lte": 40}}}, # 성장 프리미엄
        ]
        sorts = [
            {per_f: {"order": "asc"}},  # 상대적으로 덜 비싼 성장
            {pbr_f: {"order": "asc"}},
            {eps_f: {"order": "desc"}},
        ]
        return filters, sorts

    # 4) 기본값: 단순히 PBR 가장 낮은/정렬 요청
    filters = [
        {"term": {"product_type": fields["product_type"]}},
        {"range": {pbr_f: {"gte": 0}}},
    ]
    sorts = [{pbr_f: {"order": "asc"}}, {per_f: {"order": "asc"}}]
    return filters, sorts


def _search_with_filters(filters: List[dict], sorts: List[dict], fields: Dict[str, str], top_n: int):
    _source = [fields["name"], fields.get("name_alt"), fields["code"], fields["pbr"], fields["per"], fields["eps"],
               "product_type", "table"]
    _source = [f for f in _source if f]
    body = {
        "size": top_n,
        "_source": _source,
        "query": {"bool": {"filter": filters}},
        "sort": sorts,
    }
    client = _get_os_client()
    return client.search(index=INDEX, body=body)

def run_stock_screener(query: str) -> str:
    try:
        fields = _infer_market_and_fields(query)
        top_n = _extract_topn(query, default_n=5)
        filters, sorts = _preset_from_query(query, fields)

        res = _search_with_filters(filters, sorts, fields, top_n)
        hits = res.get("hits", {}).get("hits", [])
        if not hits:
            return "조건에 맞는 종목을 찾지 못했습니다. (필터가 너무 엄격할 수 있어요)"

        lines = []
        for h in hits:
            s = h.get("_source", {})
            name = s.get(fields.get("name_alt")) or s.get(fields.get("name"), "(종목명없음)")
            code = s.get(fields["code"], "")
            pbr  = s.get(fields["pbr"])
            per  = s.get(fields["per"])
            eps  = s.get(fields["eps"])
            lines.append(f"- {name}({code}) | PBR {pbr}, PER {per}, EPS {eps}")

        # 추천 톤 가이드: 장기/안정 키워드가 있으면 추천 코멘트에 반영
        q = query.lower()
        if any(k in q for k in ["장기", "안정", "보수", "defensive", "바이앤홀드", "리스크 낮", "변동성 낮"]):
            header = "장기·안정 선호 기준으로 스크리닝한 후보입니다:\n"
        elif any(k in q for k in ["가치", "저평가", "value"]):
            header = "가치(저평가) 기준으로 스크리닝한 후보입니다:\n"
        elif any(k in q for k in ["성장", "growth"]):
            header = "성장 선호 기준으로 스크리닝한 후보입니다:\n"
        else:
            header = "조건 기반으로 스크리닝한 상위 후보입니다:\n"

        return header + "\n".join(lines)

    except Exception as e:
        return f"[Screening Error] {e}"

def create_stock_recommender_tool():
    return Tool(
        name="Stock Screener & Recommender (numeric filter/sort)",
        func=run_stock_screener,
        description=(
            "PBR, PER, EPS 등 **숫자 조건/정렬**로 종목을 추려 추천 후보를 반환합니다. "
            "예: '장기적으로 안정적인 국내주식 상위 5개', 'PBR 1 미만 저평가 국내 10개', "
            "'해외 성장주 추천', 'PBR 가장 낮은 종목' 등."
        ),
    )
