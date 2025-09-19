import os
import json
from django.core.management.base import BaseCommand
from openai import OpenAI
from chat.gpt_service import fine_tuned_model
from chat.opensearch_client import OPENSEARCH_CLIENT as os_client

class Command(BaseCommand):
    help = """
    OpenSearch에 인덱싱된 벡터를 활용해 k-NN 검색을 실행합니다.
    사용법: python manage.py opensearch_service <query> [--top_k=<num>] [--index=<index_name>]
    """

    def add_arguments(self, parser):
        parser.add_argument(
            'query',
            type=str,
            help='검색할 텍스트 쿼리'
        )
        parser.add_argument(
            '--top_k',
            type=int,
            default=3,
            help='가져올 결과 개수 (기본: 3)'
        )
        parser.add_argument(
            '--index',
            type=str,
            default=os.getenv('OPENSEARCH_INDEX', 'financial-products'),
            help='검색할 OpenSearch 인덱스명'
        )

    def handle(self, *args, **options):
        query      = options['query']
        top_k      = options['top_k']
        index_name = options['index']

        # 1) OpenAI 임베딩 생성
        openai = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        resp   = openai.embeddings.create(
            model='text-embedding-3-small',
            input=[query]
        )
        emb = resp.data[0].embedding

        # 2) k-NN 검색 실행
        body = {
            'size': top_k,
            'query': {
                'knn': {
                    'embedding': {
                        'vector': emb,
                        'k': top_k
                    }
                }
            }
        }
        result = os_client.search(index=index_name, body=body)

        hits = []
        for hit in result['hits']['hits']:
            hits.append({
                "id":    hit["_id"],
                "score": round(hit["_score"], 3),
                "type":  hit["_source"].get("product_type"),
                "text":  hit["_source"].get("text", "").replace("\n", " ")
            })

        chat_resp = openai.chat.completions.create(
            model=fine_tuned_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 금융 전문가입니다. "
                        "추천된 금융상품을 상담사가 고객에게 설명하듯이, "
                        "자연스럽고 부드러운 문장으로 풀어 설명해주세요."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        "아래 검색 결과를 참고하여, 각 상품별로 2~3문장 정도의 자연스러운 문단으로 추천 내용을 작성해주세요.\n "
                        f"\n{json.dumps(hits, ensure_ascii=False, indent=2)}"
                    )
                }
            ],
            temperature=0.7,
        )

        formatted = chat_resp.choices[0].message.content
        self.stdout.write(formatted)
