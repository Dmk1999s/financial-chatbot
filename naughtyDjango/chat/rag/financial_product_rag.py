# chat/financial_product_rag.py

import os
from pathlib import Path
from dotenv import load_dotenv
import pymysql
from langchain.docstore.document import Document
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import CharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain.tools import Tool
from langchain.agents import initialize_agent, AgentType
from langchain_community.chat_models import ChatOpenAI

# .env 로드
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# OpenAI 임베딩 설정
embeddings = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))

# 컬럼 설명 정의
schema_defs = {
    "deposit": {
        "id":        "레코드 고유 ID (auto_increment)",
        "etc_note":  "기타 메모 (가입기간·부가설명 등)",
        "mtrt_int":  "만기 후 이자 계산 방식",
        "spcl_cnd":  "특별 우대 조건",
        "fin_prdt_nm": "금융상품명",
        "join_member": "가입 대상",
        "join_way": "가입 방법",
        "kor_co_nm": "은행/운용사 이름",
    },
    "savings": {
        "id":        "레코드 고유 ID (auto_increment)",
        "etc_note":  "기타 메모 (가입기간·부가설명 등)",
        "mtrt_int":  "만기 후 이자 계산 방식",
        "spcl_cnd":  "특별 우대 조건",
        "fin_prdt_nm": "금융상품명",
        "join_member": "가입 대상",
        "join_way": "가입 방법",
        "kor_co_nm": "은행/운용사 이름",
    },
    "annuity": {
        "id":             "레코드 고유 ID (auto_increment)",
        "avg_prft_rate":  "평균 수익률(%)",
        "btrm_prft_rate1": "전년도 보유기간별 수익률(%)",
        "guar_rate":      "최저 보증이율",
        "fin_prdt_nm":    "연금상품명",
        "join_way":       "가입 방법",
        "kor_co_nm":      "운용사 이름",
        "pnsn_kind_nm":   "연금 종류명",
        "prdt_type_nm":   "상품 유형명",
        "sale_co":        "판매사",
        "sale_strt_day":  "판매 개시일",
    }
}

# 공통 프롬프트 베이스
base_template = """
당신은 금융상품(연금/예금/저축) 전문가입니다.

[컬럼 설명]
{schema_explanation}

[Context]
{context}

[질문]
{question}

[답변]
"""

def _build_index(table_name: str) -> FAISS:
    """
    로컬에 faiss_{table_name}_index 폴더가 있으면 로드,
    없으면 RDS에서 데이터를 읽어 인덱스를 생성하고 저장.
    """
    idx_dir = f"faiss_{table_name}_index"
    if os.path.isdir(idx_dir):
        return FAISS.load_local(idx_dir, embeddings, allow_dangerous_deserialization=True)

    # 1) 스키마 설명 문서 생성
    schema_text = "\n".join(
        f"{col}: {desc}" for col, desc in schema_defs[table_name].items()
    )
    raw = [Document(
        page_content=f"## {table_name} 테이블 컬럼 설명 ##\n{schema_text}",
        metadata={"table": table_name, "type": "schema"}
    )]

    # 2) 실제 데이터 로딩
    conn = pymysql.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 3306)),
        cursorclass=pymysql.cursors.DictCursor
    )
    with conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table_name};")
        for row in cur.fetchall():
            text = "\n".join(f"{k}: {v}" for k, v in row.items())
            raw.append(Document(page_content=text, metadata={"table": table_name}))

    splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = splitter.split_documents(raw)

    idx = FAISS.from_documents(docs, embeddings)
    idx.save_local(idx_dir)
    return idx


def answer_financial_question(question: str) -> str:
    """
    Agent + Tool을 사용해 deposit/ savings/ annuity
    세 테이블 색인 로딩 후 RAG 답변 생성
    """
    table_map = {"deposit": "예금", "savings": "적금", "annuity": "연금"}
    tools = []

    for tbl, korean in table_map.items():
        idx = _build_index(tbl)
        retriever = idx.as_retriever(search_kwargs={"k": 5})

        # 테이블별 프롬프트 생성
        schema_explanation = "\n".join(
            f"{col}: {desc}" for col, desc in schema_defs[tbl].items()
        )
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=base_template.replace("{schema_explanation}", schema_explanation)
        )

        qa = RetrievalQA.from_chain_type(
            llm=ChatOpenAI(temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")),
            chain_type="stuff",
            retriever=retriever,
            chain_type_kwargs={"prompt": prompt}
        )
        tools.append(
            Tool(
                name=f"{korean}QA",
                func=qa.run,
                description=f"{korean} 상품 데이터({tbl} 테이블) 기반 질문 응답 도구"
            )
        )

    agent = initialize_agent(
        tools=tools,
        llm=ChatOpenAI(temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")),
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=False
    )
    return agent.run(question)
