# chat/annuity_rag.py

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

# 1) 환경 변수 로드
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# 2) MySQL 연결 및 데이터 로드
conn = pymysql.connect(
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    port=int(os.getenv("DB_PORT", 3306)),
    cursorclass=pymysql.cursors.DictCursor
)
raw_docs = []
with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM annuity;")
        for row in cur.fetchall():
            content = "\n".join(f"{k}: {v}" for k, v in row.items())
            raw_docs.append(Document(page_content=content, metadata={"id": row["id"]}))

# 3) 텍스트 청크 분할
splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
docs = splitter.split_documents(raw_docs)

# 4) 임베딩 및 FAISS 인덱스 생성/로딩
embeddings = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))
vectorstore = FAISS.from_documents(docs, embeddings)
vectorstore.save_local("faiss_annuity_index")
vectorstore = FAISS.load_local(
    "../faiss_annuity_index", embeddings,
    allow_dangerous_deserialization=True
)

# 5) QA용 프롬프트 템플릿 정의
prompt = PromptTemplate(
    input_variables=["context", "question"],
    template="""
당신은 금융상품(연금) 전문가입니다.
주어진 context에서 필요한 정보만을 사용하여 질문에 답하십시오.
해당 내용이 없으면 "죄송합니다 해당 정보가 없습니다."라고 대응하세요.
질문에 최대한 자세히 답하십시오.

Context:
{context}

질문: {question}
답변:
"""
)

# 6) RetrievalQA 체인 초기화
qa_chain = RetrievalQA.from_chain_type(
    llm=ChatOpenAI(temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")),
    chain_type="stuff",
    retriever=vectorstore.as_retriever(search_kwargs={"k": 5}),
    chain_type_kwargs={"prompt": prompt}
)

# 7) Tool으로 래핑
annuity_tool = Tool(
    name="AnnuityQA",
    func=qa_chain.run,
    description="FAISS에 저장된 annuity 테이블 데이터를 기반으로 사용자의 질문에 답합니다. 입력: 질문 문자열"
)

# 8) Agent 초기화
agent = initialize_agent(
    tools=[annuity_tool],
    llm=ChatOpenAI(temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")),
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

# 9) 질문-응답 함수

def answer_financial_question(question: str) -> str:
    """
    annuity 테이블 기반 RAG 답변 생성 (Agent + Tool 사용)
    """
    return agent.run(question)

# 테스트용
if __name__ == "__main__":
    # 사용 중인 Tool 목록 및 템플릿 확인
    print("Tools:", [t.name for t in [annuity_tool]])
    print("Prompt Template:\n", prompt.template)

    query = ("금융상품이 모두 몇개야?"
             "그리고 평균 수익률이 높은 순으로 나열해줘")
    print("질문:", query)
    print("응답:", answer_financial_question(query))
