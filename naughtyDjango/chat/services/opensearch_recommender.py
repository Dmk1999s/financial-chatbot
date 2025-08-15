import os, json
from openai import OpenAI
from chat.gpt_service import fine_tuned_model
from chat.opensearch_client import OPENSEARCH_CLIENT as os_client

def recommend_with_knn(query: str, top_k: int = 3, index_name: str = None) -> str:
    """
    쿼리 -> 임베딩 -> kNN 검색 -> 요약/추천까지 한 번에 수행.
    문자열을 '바로' 반환하므로 뷰에서 곧바로 응답 가능.
    """
    openai = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    index = index_name or os.getenv('OPENSEARCH_INDEX', 'financial-products')

    # 1) 임베딩
    emb = openai.embeddings.create(
        model='text-embedding-3-small',
        input=[query]
    ).data[0].embedding

    # 2) kNN 검색
    body = {'size': top_k, 'query': {'knn': {'embedding': {'vector': emb, 'k': top_k}}}}
    hits = os_client.search(index=index, body=body)['hits']['hits']
    payload = [{
        "id": h["_id"],
        "score": round(h["_score"], 3),
        "type": h["_source"].get("product_type"),
        "text": h["_source"].get("text", "").replace("\n", " ")
    } for h in hits]

    # 3) 요약/추천 (짧고 결정적인 프롬프트, max_tokens로 상한 설정)
    chat = openai.chat.completions.create(
        model=fine_tuned_model,
        messages=[
            {"role": "system", "content": "금융 상담사처럼 간결하고 정확하게. 각 항목 2~3문장."},
            {"role": "user", "content": f"이 검색 결과를 바탕으로 추천문 작성:\n{json.dumps(payload, ensure_ascii=False)}"}
        ],
        temperature=0.5,
        max_tokens=350,
    )
    return chat.choices[0].message.content
