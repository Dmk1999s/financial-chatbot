# chat/rag/lookup_tool.py
import os
from langchain.tools import Tool
from opensearchpy import OpenSearch
from chat.opensearch_client import OPENSEARCH_CLIENT as default_os_client

INDEX = os.getenv("OPENSEARCH_INDEX", "financial-products")

BANK_TABLES = {"deposit": "예금", "savings": "적금", "annuity": "연금"}
STOCK_TABLES = {"krx_stock_info": "국내주식", "nasdaq_stock_info": "해외주식"}

def _get_os_client():
    # screener_tool.py의 _get_os_client와 동일하게 정리
    env = os.getenv("ENVIRONMENT", "production")
    if env == "local":
        return OpenSearch(
            hosts=[{"host": "localhost", "port": 9200}],
            http_auth=(os.getenv("OPENSEARCH_USER"), os.getenv("OPENSEARCH_PASS")),
            use_ssl=True,
            verify_certs=False,
            ssl_assert_hostname=False,
            timeout=60,
        )
    return default_os_client


def run_specific_stock_lookup(query: str) -> str:
    """사용자 질문에서 종목명을 추출하여 OpenSearch에서 해당 종목의 상세 정보를 찾습니다."""
    # 간단한 종목명 추출 (실제로는 LLM을 사용하면 더 정교해짐)
    # 예: "삼성전자 현재가" -> "삼성전자"
    # 지금은 간단하게 query 전체를 종목명으로 가정합니다.
    stock_name = query.replace("현재가", "").replace("주가", "").strip()

    client = _get_os_client()
    body = {
        "size": 1,
        "query": {
            "bool": {
                "should": [
                    {"match": {"bstp_kor_isnm": stock_name}},
                    {"match": {"prdt_abrv_name": stock_name}}
                ],
                "minimum_should_match": 1
            }
        }
    }

    try:
        res = client.search(index=INDEX, body=body)
        hits = res.get("hits", {}).get("hits", [])
        if not hits:
            return f"'{stock_name}'에 대한 정보를 찾을 수 없습니다."

        source = hits[0].get("_source", {})

        # 국내 주식/해외 주식 구분하여 정보 포맷팅
        if source.get("table") == "krx_stock_info":
            name = source.get("bstp_kor_isnm")
            price = source.get("stck_prpr")
            pbr = source.get("pbr")
            per = source.get("per")
            eps = source.get("eps")
            return f"{name}의 정보는 다음과 같습니다: 현재가 {price}원, PBR {pbr}, PER {per}, EPS {eps}"
        elif source.get("table") == "nasdaq_stock_info":
            name = source.get("prdt_abrv_name")
            price = source.get("last")
            pbr = source.get("pbrx")
            per = source.get("perx")
            epsx = source.get("epsx")
            return f"{name}의 정보는 다음과 같습니다: 현재가 {price}달러, PBR {pbr}, PER {per}, EPS {epsx}"
        else:
            return f"'{stock_name}'에 대한 정보를 찾았지만, 주식 정보가 아닙니다."

    except Exception as e:
        return f"[Lookup Error] {e}"


def create_stock_lookup_tool():
    return Tool(
        name="Specific Stock Lookup",
        func=run_specific_stock_lookup,
        description="""
        # 사용해야 할 때:
        - 사용자가 '삼성전자'나 '애플'처럼 **특정 회사 이름 하나**를 언급하며 '현재가', '주가', 'PBR', '정보' 등을 물어볼 때 사용합니다.

        # 사용하면 안 될 때:
        - 'PBR 낮은 주식'처럼 여러 종목을 찾아달라는 요청에는 사용하지 마세요.
        """
    )