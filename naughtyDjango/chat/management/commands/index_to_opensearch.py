import os
from pathlib import Path

import boto3
import pymysql
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from openai import OpenAI
from opensearchpy import OpenSearch, helpers, RequestsHttpConnection
from requests_aws4auth import AWS4Auth


# ── AWS IAM 자격 증명 세팅 ──
session     = boto3.Session()
creds       = session.get_credentials().get_frozen_credentials()
region      = "ap-northeast-2"
awsauth     = AWS4Auth(creds.access_key, creds.secret_key, region, "es", session_token=creds.token)

class Command(BaseCommand):
    help = "RDS에서 금융상품과 주식 데이터를 읽어 OpenSearch Service에 k-NN 벡터 색인합니다."

    def handle(self, *args, **options):
        # ───────────────────────────────────────────────────────
        # 1) 환경 변수 로드
        # ───────────────────────────────────────────────────────
        BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
        load_dotenv(BASE_DIR / ".env")

        # ───────────────────────────────────────────────────────
        # 2) RDS 접속 정보
        # ───────────────────────────────────────────────────────
        db_conf = {
            "host":        os.getenv("DB_HOST"),
            "port":        int(os.getenv("DB_PORT", 3306)),
            "user":        os.getenv("DB_USER"),
            "password":    os.getenv("DB_PASSWORD"),
            "database":    os.getenv("DB_NAME"),
            "cursorclass": pymysql.cursors.DictCursor
        }

        # ───────────────────────────────────────────────────────
        # 3) OpenAI 클라이언트 (임베딩)
        # ───────────────────────────────────────────────────────
        openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # ───────────────────────────────────────────────────────
        # 4) OpenSearch 클라이언트 (SigV4 인증)
        # ───────────────────────────────────────────────────────
        os_client = OpenSearch(
            hosts=[{
                "host": os.getenv("OPENSEARCH_HOST"),
                "port": int(os.getenv("OPENSEARCH_PORT"))
            }],
            http_auth=awsauth,
            use_ssl=True,
            verify_certs=False,
            ssl_assert_hostname=False,
            connection_class=RequestsHttpConnection
        )

        # ───────────────────────────────────────────────────────
        # 5) 색인 이름 및 매핑(한 번만 생성)
        # ───────────────────────────────────────────────────────
        index_name = "financial-products"
        if not os_client.indices.exists(index=index_name):
            self.stdout.write(f"Creating k-NN index '{index_name}' …")
            os_client.indices.create(
                index=index_name,
                body={"settings": {"index": { "knn": True }},
                    "mappings": {"_source": {"excludes": ["embedding"]},
                     "properties": {
                         "text": {"type": "text"},
                         "product_type": {"type": "keyword"},
                         "table": {"type": "keyword"},
                         "embedding": {"type": "knn_vector", "dimension": 1536}
                        }
                    }
                }
            )
            self.stdout.write(self.style.SUCCESS(f"Index '{index_name}' created."))

        # ───────────────────────────────────────────────────────
        # 6) RDS → OpenSearch Bulk 색인
        # ───────────────────────────────────────────────────────
        tables = {"deposit": "예금", "savings": "적금", "annuity": "연금"}

        actions = []
        with pymysql.connect(**db_conf) as conn:
            with conn.cursor() as cur:
                for tbl, korean in tables.items():
                    self.stdout.write(f"▶️  Fetching rows from RDS table '{tbl}' …")
                    cur.execute(f"SELECT * FROM {tbl};")
                    rows = cur.fetchall()

                    # (1) 각 row → 단일 텍스트
                    texts = [
                        "\n".join(f"{col}: {val}" for col, val in row.items())
                        for row in rows
                    ]

                    # (2) OpenAI Embeddings 배치 호출
                    resp = openai.embeddings.create(
                        model="text-embedding-3-small",
                        input=texts
                    )
                    vectors = [e.embedding for e in resp.data]

                    # (3) bulk 액션 준비
                    for row, vec, txt in zip(rows, vectors, texts):
                        doc = {
                            "text":         txt,
                            "embedding":    vec,
                            "table":        tbl,
                            "product_type": korean
                        }
                        actions.append({
                            "_op_type": "index",
                            "_index":   index_name,
                            "_id":      f"{tbl}-{row['id']}",
                            "_source":  doc
                        })

        # (4) bulk 전송
        self.stdout.write(f"Indexing a total of {len(actions)} docs into '{index_name}' …")
        success, _ = helpers.bulk(
            os_client,
            actions,
            chunk_size=500,
            request_timeout=60
        )
        self.stdout.write(self.style.SUCCESS(f"✅ Successfully indexed {success} documents."))
