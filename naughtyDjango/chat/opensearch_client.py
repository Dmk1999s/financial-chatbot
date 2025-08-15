import os
from dotenv import load_dotenv
from openai import OpenAI
from opensearchpy import OpenSearch, RequestsHttpConnection

load_dotenv()

def search_financial_products(
    query: str,
    top_k: int = 5,
    index_name: str = None,
    product_type: str = None,    # 예: "예금", "적금", "연금", "stock" 등
):
    # 1) 임베딩 생성
    openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = openai.embeddings.create(
        model="text-embedding-3-small",
        input=[query]
    )
    emb = resp.data[0].embedding

    # 2) OpenSearch 클라이언트 초기화
    host = os.getenv("OPENSEARCH_HOST")
    port = int(os.getenv("OPENSEARCH_PORT", 443))
    user = os.getenv("OPENSEARCH_USER")
    pwd  = os.getenv("OPENSEARCH_PASS")
    client = OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=(user, pwd),
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection
    )

    # 3) k-NN 쿼리 + (선택) product_type 필터
    body = {
        "size": top_k,
        "query": {
            "bool": {
                **({"filter": [{"term": {"product_type": product_type}}]} if product_type else {}),
                "knn": {
                    "embedding": {
                        "vector": emb,
                        "k": top_k
                    }
                }
            }
        }
    }
    idx = index_name or os.getenv("OPENSEARCH_INDEX", "financial-products")
    result = client.search(index=idx, body=body)

    # 4) 결과 파싱
    hits = []
    for hit in result["hits"]["hits"]:
        src = hit["_source"]
        hits.append({
            "id":    hit["_id"],
            "score": hit["_score"],
            "text":  src.get("text", "").replace("\n", " "),
            "type":  src.get("product_type"),
        })
    return hits
