# chat/rag/financial_product_rag.py

import os
from pathlib import Path
from dotenv import load_dotenv
from langchain.docstore.document import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import OpenSearchVectorSearch
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain.tools import Tool
from langchain.agents import initialize_agent, AgentType
from langchain_community.chat_models import ChatOpenAI

# 1) 환경 변수 로드
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# 2) OpenAI 임베딩 세팅 (OpenAI text-embedding-3-small: 1536 차원)
embeddings = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))

# 3) 각 테이블 컬럼 설명 정의
schema_defs = {
    "deposit": {
        "id":        "레코드 고유 ID (auto_increment)",
        "etc_note":  "기타 메모 (가입기간·부가설명 등)",
        "mtrt_int":  "만기 후 이자 계산 방식",
        "spcl_cnd":  "특별 우대 조건",
        "fin_prdt_nm": "금융상품명",
        "join_member": "가입 대상",
        "join_way":  "가입 방법",
        "kor_co_nm": "은행/운용사 이름",
    },
    "savings": {
        "id":        "레코드 고유 ID (auto_increment)",
        "etc_note":  "기타 메모",
        "mtrt_int":  "만기 후 이자 계산 방식",
        "spcl_cnd":  "특별 우대 조건",
        "fin_prdt_nm": "금융상품명",
        "join_member": "가입 대상",
        "join_way":  "가입 방법",
        "kor_co_nm": "은행/운용사 이름",
    },
    "annuity": {
        "id":             "레코드 고유 ID (auto_increment)",
        "avg_prft_rate":  "평균 수익률(%)",
        "btrm_prft_rate1":"전년도 보유기간별 수익률(%)",
        "guar_rate":      "최저 보증이율",
        "fin_prdt_nm":    "연금상품명",
        "join_way":       "가입 방법",
        "kor_co_nm":      "운용사 이름",
        "pnsn_kind_nm":   "연금 종류명",
        "prdt_type_nm":   "상품 유형명",
        "sale_co":        "판매사",
        "sale_strt_day":  "판매 개시일",
    },
    "krx_stock_info": {
        "id":             "레코드 고유 ID",
        "bstp_kor_isnm":  "한글 종목명",
        "eps":            "EPS",
        "pbr":            "PBR",
        "per":            "PER",
        "stck_prpr":      "현재가",
        "stck_shrn_iscd": "종목 코드",
        "prdt_abrv_name": "종목 약식명"
    },
    "nasdaq_stock_info": {
        "id": "레코드 고유 ID",
        "code": "종목 코드",
        "e_icod": "업종(섹터)",
        "epsx": "EPS",
        "pbrx": "PBR",
        "perx": "PER",
        "prdt_abrv_name": "종목 약식명",
        "last": "현재가"
    }
}

# 4) 공통 프롬프트 템플릿
base_template = """
당신은 금융상품(연금/예금/저축/주식) 전문가입니다.

[컬럼 설명]
{schema_explanation}

[Context]
{context}

[질문]
{question}

[답변]
"""

def _make_opensearch_retriever(table_name: str):
    """
    OpenSearchVectorSearch retriever 생성.
    'table' 필드로 필터링해서 해당 테이블 문서만 검색하도록 설정합니다.
    """
    os_url  = os.getenv("OPENSEARCH_HOST")
    os_port = int(os.getenv("OPENSEARCH_PORT", 443))
    retriever = OpenSearchVectorSearch.from_existing_index(
        index_name="financial-products",
        embedding=embeddings,
        es_url=os_url,
        es_port=os_port,
        es_user=os.getenv("OPENSEARCH_USER"),
        es_password=os.getenv("OPENSEARCH_PASS"),
        use_ssl=True,
        verify_certs=True,
        connection_scheme="https",
    ).as_retriever(
        search_kwargs={
            "k":      5,
            "filter": {"term": {"table": table_name}}
        }
    )
    return retriever

def answer_financial_question(question: str) -> str:
    """
    OpenSearch k-NN 인덱스만 사용해서
    deposit/savings/annuity/stock 네 개 테이블을
    RetrievalQA + Agent 로 묶어 RAG 응답을 생성합니다.
    """
    table_map = {
        "deposit": "예금",
        "savings": "적금",
        "annuity": "연금",
        "krx_stock_info":   "국내주식",
        "nasdaq_stock_info":"해외주식",
    }

    tools = []
    for tbl, korean in table_map.items():
        # (1) OpenSearch retriever
        retriever = _make_opensearch_retriever(tbl)

        # (2) PromptTemplate 에 테이블별 스키마 설명
        schema_explanation = "\n".join(
            f"{col}: {desc}" for col, desc in schema_defs[tbl].items()
        )
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=base_template.format(
                schema_explanation=schema_explanation,
                context="{context}",
                question="{question}"
            )
        )

        # (3) RetrievalQA 체인
        qa = RetrievalQA.from_chain_type(
            llm=ChatOpenAI(
                temperature=0,
                openai_api_key=os.getenv("OPENAI_API_KEY")
            ),
            chain_type="stuff",
            retriever=retriever,
            chain_type_kwargs={"prompt": prompt}
        )

        # (4) LangChain Tool 로 래핑
        tools.append(
            Tool(
                name=f"{korean}QA",
                func=qa.run,
                description=f"{korean}({tbl}) 테이블 기반 질문 응답 도구"
            )
        )

    # (5) Agent 초기화 및 실행
    agent = initialize_agent(
        tools=tools,
        llm=ChatOpenAI(
            temperature=0,
            openai_api_key=os.getenv("OPENAI_API_KEY")
        ),
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=False
    )
    return agent.run(question)