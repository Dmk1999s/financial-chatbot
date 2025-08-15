# chat/opensearch_client.py
import os
from dotenv import load_dotenv
from openai import OpenAI
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3

load_dotenv()

# ── AWS 자격증명 & SigV4 설정 ──
session = boto3.Session()
creds   = session.get_credentials().get_frozen_credentials()
region  = os.getenv("AWS_REGION", "ap-northeast-2")
awsauth = AWS4Auth(
    creds.access_key,
    creds.secret_key,
    region,
    "es",
    session_token=creds.token
)

# ── 싱글턴 OpenSearch 클라이언트 ──
OPENSEARCH_CLIENT = OpenSearch(
    hosts=[{
        "host": os.getenv("OPENSEARCH_HOST"),
        "port": int(os.getenv("OPENSEARCH_PORT", 443))
    }],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=False,
    connection_class=RequestsHttpConnection,
    # ↓ 커넥션 풀 크기 (동시 소켓 연결 개수)
    pool_maxsize=25,
    # ↓ 타임아웃·재시도 옵션
    timeout=30,
    max_retries=3,
    retry_on_timeout=True,
    # ↓ HTTP 헤더에 Keep‑Alive 명시
    headers={"Connection": "keep-alive"},
)

def search_financial_products(
    query: str,
    top_k: int = 5,
    index_name: str = None,
    product_type: str = None,
):
    # (1) 임베딩 생성
    openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = openai.embeddings.create(
        model="text-embedding-3-small",
        input=[query]
    )
    emb = resp.data[0].embedding

    # (2) 싱글턴 클라이언트 사용
    client = OPENSEARCH_CLIENT
    body = {
        "size": top_k,
        "query": {
            "bool": {
                **({"filter": [{"term": {"product_type": product_type}}]} if product_type else {}),
                "knn": {
                    "embedding": {"vector": emb, "k": top_k}
                }
            }
        }
    }
    result = client.search(index=index_name or os.getenv("OPENSEARCH_INDEX"), body=body)

    return [
        {
            "id": hit["_id"],
            "score": hit["_score"],
            "text": hit["_source"]["text"].replace("\n", " "),
            "type": hit["_source"]["product_type"],
        }
        for hit in result["hits"]["hits"]
    ]