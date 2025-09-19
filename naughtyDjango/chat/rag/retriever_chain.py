#chat/rag/retrieve_chain.py

import os
import json
from openai import OpenAI
from dotenv import load_dotenv
import logging
import re

from langchain.chains.query_constructor.base import AttributeInfo
from langchain.retrievers.self_query.base import SelfQueryRetriever
from langchain_openai import OpenAI as LangChainOpenAI
from langchain_community.vectorstores import OpenSearchVectorSearch
from langchain_openai import OpenAIEmbeddings
from langchain.tools import Tool
from chat.opensearch_client import search_financial_products
from chat.opensearch_client import OPENSEARCH_CLIENT as os_client

load_dotenv()
logger = logging.getLogger(__name__)


_PT_SYNONYMS = {
    r"(정기)?예금|deposit": "예금",
    r"(정기)?적금|자유적금|savings?": "적금",
    r"연금저축|연금보험|퇴직연금|irp|annuity|연금": "연금",   # ← '연금' 단독 추가
    r"국내\s*주식": "국내주식",
    r"(해외|미국|나스닥|nasdaq|us)\s*주식": "해외주식",
}

# 필터링 가능한 메타데이터 필드 상세 정의
metadata_field_info = [
    AttributeInfo(
        name="product_type",
        description=(
            "금융 상품의 한글 종류값. 반드시 다음 중 하나를 정확히 사용: "
            "'예금', '적금', '연금', '국내주식', '해외주식'. "
            "유의어: deposit→예금, savings→적금, annuity/연금저축/IRP→연금."
        ),
        type="string"
    ),
    AttributeInfo(name="kor_co_nm", description="금융 회사의 이름. 예를 들어 '신한은행', '삼성생명보험' 등.", type="string"),
    AttributeInfo(name="bstp_kor_isnm", description="국내 주식의 한글 종목명. 예를 들어 '삼성전자', '현대자동차' 등.", type="string"),
    AttributeInfo(name="pbr", description="주가순자산비율 (Price-to-Book Ratio). 낮을수록 저평가된 주식. 국내 주식에만 해당.", type="float"),
    AttributeInfo(name="per", description="주가수익비율 (Price-to-Earnings Ratio). 낮을수록 저평가된 주식. 국내 주식에만 해당.", type="float"),
    AttributeInfo(name="pbrx", description="주가순자산비율 (Price-to-Book Ratio). 해외 주식에만 해당.", type="float"),
    AttributeInfo(name="perx", description="주가수익비율 (Price-to-Earnings Ratio). 해외 주식에만 해당.", type="float"),
    AttributeInfo(name="avg_prft_rate", description="연금 상품의 평균 수익률 (단위: %).", type="float"),
    AttributeInfo(name="stck_prpr", description="국내 주식의 현재가 (단위: 원).", type="float"),
    AttributeInfo(name="last", description="해외 주식의 현재가 (단위: 달러).",type="float")
]

# 컬럼 정보 정의
SCHEMA_DEFS = {
    "deposit": {
        "kor_co_nm": "금융 회사명",
        "fin_prdt_nm": "예금 상품명",
        "mtrt_int": "만기 후 이자 계산 방식",
        "spcl_cnd": "특별 우대 조건",
        "join_member": "가입 대상",
        "join_way": "가입 방법",
        "etc_note": "기타 참고사항"
    },
    "savings": {
        "kor_co_nm": "금융 회사명",
        "fin_prdt_nm": "적금 상품명",
        "mtrt_int": "만기 후 이자 계산 방식",
        "spcl_cnd": "특별 우대 조건",
        "join_member": "가입 대상",
        "join_way": "가입 방법",
        "etc_note": "기타 참고사항"
    },
    "annuity": {
        "kor_co_nm": "운용 회사명",
        "fin_prdt_nm": "연금 상품명",
        "pnsn_kind_nm": "연금 종류",
        "prdt_type_nm": "상품 유형",
        "avg_prft_rate": "평균 수익률 (%)",
        "btrm_prft_rate1": "전년도 수익률 (%)",
        "guar_rate": "최저 보증 이율",
        "sale_co": "판매사",
        "join_way": "가입 방법",
        "sale_strt_day": "판매 시작일"
    },
    "krx_stock_info": {
        "bstp_kor_isnm": "한글 종목명",
        "prdt_abrv_name": "종목 약식명",
        "stck_shrn_iscd": "종목 코드",
        "stck_prpr": "현재가",
        "per": "주가수익비율 (PER)",
        "pbr": "주가순자산비율 (PBR)",
        "eps": "주당순이익 (EPS)"
    },
    "nasdaq_stock_info": {
        "prdt_abrv_name": "종목 약식명",
        "code": "종목 코드 (티커)",
        "last": "현재가",
        "perx": "주가수익비율 (PER)",
        "pbrx": "주가순자산비율 (PBR)",
        "epsx": "주당순이익 (EPS)",
        "e_icod": "업종 (섹터)"
    }
}

# --- 모듈 로드 시점에 Retriever를 한 번만 생성 (싱글턴) ---
try:
    _llm = LangChainOpenAI(temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY"))
    _embeddings = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))

    ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

    if ENVIRONMENT == "local":
        _vectorstore = OpenSearchVectorSearch(
            index_name=os.getenv('OPENSEARCH_INDEX', 'financial-products'),
            embedding_function=_embeddings,
            opensearch_url="https://localhost:9200",
            http_auth=(os.getenv("OPENSEARCH_USER"), os.getenv("OPENSEARCH_PASS")),
            use_ssl=True, verify_certs=False, ssl_assert_hostname=False,
        )
    else:
        _vectorstore = OpenSearchVectorSearch(
            index_name=os.getenv('OPENSEARCH_INDEX', 'financial-products'),
            embedding_function=_embeddings,
            opensearch_client=os_client
        )

    _document_contents = "금융 상품 또는 주식에 대한 정보"

    SELF_QUERY_RETRIEVER = SelfQueryRetriever.from_llm(
        llm=_llm,
        vectorstore=_vectorstore,
        document_contents=_document_contents,
        metadata_field_info=metadata_field_info,
        enable_limit=True,
        verbose=True
    )
    print(f"✅ Self-Query Retriever initialized successfully for {ENVIRONMENT.upper()} environment.")
except Exception as e:
    logger.error(f"❗️Failed to initialize Self-Query Retriever: {e}")
    SELF_QUERY_RETRIEVER = None

def run_rag_chain(query: str) -> str:
    try:
        pt = _detect_product_type_ko(query)

        if pt in {"예금", "적금", "연금", "국내주식", "해외주식", "주식"}:
            target_types = ["국내주식", "해외주식"] if pt == "주식" else [pt]
            hits = []
            for t in target_types:
                _hits = search_financial_products(query=query, top_k=5, product_type=t) or []
                for h in _hits:
                    h.setdefault("product_type", t)
                hits.extend(_hits)
            if hits:
                context = json.dumps(hits, ensure_ascii=False, indent=2)
                prompt = f"""당신은 금융상담사입니다.
아래 검색 결과를 바탕으로 사용자의 질문에 답하세요.
- 항목별로 핵심만 2~3문장씩 정리
- '왜 이 상품이 적합한지'를 간단히 근거 제시
- 숫자는 원문에 있는 값만 사용(추정 금지)
[검색결과]
{context}
[사용자질문]
{query}"""
                chat = OpenAI(api_key=os.getenv('OPENAI_API_KEY')).chat.completions.create(
                    model="gpt-3.5-turbo",
                    temperature=0.2,
                    max_tokens=1200,
                    messages=[{"role": "user", "content": prompt}]
                )
                return chat.choices[0].message.content

        if SELF_QUERY_RETRIEVER is None:
            return "죄송합니다, 현재 추천 시스템에 문제가 발생하여 답변할 수 없습니다."

        retrieved_docs = SELF_QUERY_RETRIEVER.invoke(query)
        if not retrieved_docs:
            return "죄송하지만, 문의하신 조건에 맞는 정보를 찾을 수 없었습니다."

        payload = [doc.metadata for doc in retrieved_docs]
        tables_in_result = {doc.metadata.get("table") for doc in retrieved_docs}

        schema_explanation = ""
        for table_name in sorted(list(tables_in_result)):
            if table_name in SCHEMA_DEFS:
                schema_explanation += f"--- [{table_name} 컬럼 설명] ---\n"
                for col, desc in SCHEMA_DEFS[table_name].items():
                    schema_explanation += f"- `{col}`: {desc}\n"
                schema_explanation += "\n"

        RAG_PROMPT_TEMPLATE = """당신은 금융상담사입니다.
아래 컨텍스트를 바탕으로 사용자의 질문에 답하세요.
- 표기된 컬럼 설명을 참고해 한국어로 자연스럽게 설명
- 상품별로 2~3문장씩 요약, 비교 포인트 제시
- 과장/추정 금지, 컨텍스트 밖 정보 확언 금지

[컬럼설명]
{schema_explanation}
[컨텍스트]
{context}
[질문]
{question}
"""
        context_str = json.dumps(payload, ensure_ascii=False, indent=2)
        final_prompt = RAG_PROMPT_TEMPLATE.format(
            schema_explanation=schema_explanation,
            context=context_str,
            question=query
        )

        chat = OpenAI(api_key=os.getenv('OPENAI_API_KEY')).chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.2,
            max_tokens=2000,
        )
        return chat.choices[0].message.content

    except Exception as e:
        logger.error(f"❗ run_rag_chain error: {e}")
        return "죄송합니다, 질문을 처리하는 중 오류가 발생했습니다. 더 간단한 질문으로 다시 시도해주세요."

# Agent가 사용할 Tool 객체를 생성하는 함수
def create_self_query_rag_tool():
    """RAG 체인을 실행하는 LangChain Tool 객체를 생성합니다."""
    return Tool(
        name="Financial Product Recommender",
        func=run_rag_chain,
        description="""
        # 이 도구는 언제 사용해야 하는가:
        - 사용자가 '주식', '예금', '적금', '연금'과 같은 특정 금융 상품에 대한 추천을 요청할 때 사용합니다.
        - 'PBR이 1 미만인', '안정적인', '수익률이 가장 높은' 등 구체적인 조건이 포함된 질문에 가장 적합합니다.

        # 이 도구는 언제 사용하면 안 되는가:
        - 단순한 인사("안녕하세요"), 안부 또는 일반적인 대화에는 절대로 사용하지 마세요.
        - 'PBR이 무엇인가요?' 또는 '주식이란?' 과 같이 금융 용어에 대한 정의나 설명을 묻는 질문에는 사용하지 마세요.
        - '삼성전자 현재 주가 알려줘' 와 같이 데이터베이스에 없는 실시간 정보를 묻는 질문에는 사용하지 마세요.

        # 이 도구에 무엇을 입력해야 하는가:
        - 반드시 사용자의 원래 질문 전체를 그대로 입력해야 합니다.
        """
    )

def _detect_product_type_ko(query: str) -> str | None:
    q = query.lower()
    if "연금" in q:
        return "연금"
    if "예금" in q:
        return "예금"
    if "적금" in q:
        return "적금"
    if "주식" in q:
        return "주식"
    for pat, val in _PT_SYNONYMS.items():
        if re.search(pat, q):
            return val
    return None