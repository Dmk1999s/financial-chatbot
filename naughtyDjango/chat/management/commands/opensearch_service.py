import os
import json
from pathlib import Path
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from openai import OpenAI
import boto3
from requests_aws4auth import AWS4Auth
from opensearchpy import OpenSearch, RequestsHttpConnection
from chat.gpt_service import fine_tuned_model

# ── 환경 변수 로드 (.env 위치를 manage.py 위치 기준으로 탐색) ──
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(BASE_DIR / ".env")

# ── AWS IAM 자격 증명 및 SigV4 인증 세팅 ──
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

        # 2) OpenSearch 클라이언트 초기화 (SigV4)
        host = os.getenv('OPENSEARCH_HOST')
        port = int(os.getenv('OPENSEARCH_PORT', 443))
        client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=awsauth,
            use_ssl=True,
            verify_certs=False,
            ssl_assert_hostname=False,
            connection_class=RequestsHttpConnection
        )

        # 3) k-NN 검색 실행
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
        result = client.search(index=index_name, body=body)

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
                {"role": "system", "content": "당신은 금융 전문가로, 추천된 금융상품을 사용자가 이해하기 쉬운 자연스러운 문장으로 설명해주는 역할을 합니다."},
                {
                    "role": "user",
                    "content": (
                        "아래 검색 결과를 바탕으로, 각 금융상품을 추천하듯 자연스럽고 친절한 한국어 문장으로 설명해주세요."
                        f"\n{json.dumps(hits, ensure_ascii=False, indent=2)}"
                    )
                }
            ]
        )

        formatted = chat_resp.choices[0].message.content
        self.stdout.write(formatted)
