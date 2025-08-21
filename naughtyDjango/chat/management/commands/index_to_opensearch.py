# chat/management/commands/index_to_opensearch.py
import os
import time
from pathlib import Path

import pymysql
from django.core.management.base import BaseCommand
from dotenv import load_dotenv
from openai import OpenAI
from opensearchpy import helpers, exceptions
from chat.opensearch_client import OPENSEARCH_CLIENT as os_client

class Command(BaseCommand):
    help = "RDS에서 금융상품과 주식 데이터를 읽어 OpenSearch Service에 k-NN 벡터 색인합니다."

    def handle(self, *args, **options):
        # 1) 환경 변수 로드
        BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
        load_dotenv(BASE_DIR / ".env")

        # 2) RDS 접속 정보
        db_conf = {
            "host":     os.getenv("DB_HOST"),
            "port":     int(os.getenv("DB_PORT", 3306)),
            "user":     os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "database": os.getenv("DB_NAME"),
            "cursorclass": pymysql.cursors.DictCursor
        }
        openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        index_name = "financial-products"

        # 3) 인덱스가 없으면 생성
        if not os_client.indices.exists(index=index_name):
            self.stdout.write(f"Creating k-NN index '{index_name}' …")
            os_client.indices.create(
                index=index_name,
                body={
                    "settings": {"index": {"knn": True}},
                    "mappings": {
                        "_source": {"excludes": ["embedding"]},
                        "properties": {
                            "text":         {"type": "text"},
                            "product_type": {"type": "keyword"},
                            "table":        {"type": "keyword"},
                            "embedding":    {"type": "knn_vector", "dimension": 1536},
                            # 숫자 필드들의 타입을 float로 명시
                            "per": {"type": "float"},
                            "pbr": {"type": "float"},
                            "eps": {"type": "float"},
                            "perx": {"type": "float"},
                            "pbrx": {"type": "float"},
                            "epsx": {"type": "float"}
                        }
                    }
                }
            )
            self.stdout.write(self.style.SUCCESS(f"Index '{index_name}' created."))

        # 4) 색인 전 refresh_interval 비활성화
        self.stdout.write("▶️ Disabling refresh for bulk indexing…")
        os_client.indices.put_settings(
            index=index_name,
            body={"index": {"refresh_interval": "-1"}}
        )

        # 5) RDS에서 데이터 로드 후 문서 준비
        tables = {
            "deposit": "예금",
            "savings": "적금",
            "annuity": "연금",
            "krx_stock_info": "국내주식",
            "nasdaq_stock_info": "해외주식",
        }
        actions = []

        with pymysql.connect(**db_conf) as conn, conn.cursor() as cur:
            for tbl, korean in tables.items():
                self.stdout.write(f"▶️ Fetching rows from '{tbl}' …")
                cur.execute(f"SELECT * FROM {tbl};")
                rows = cur.fetchall()
                if not rows:
                    self.stdout.write(f"⚠️ '{tbl}' has no data, skipping.")
                    continue

                # (1) 각 row → 텍스트
                texts = [
                    "\n".join(f"{col}: {val}" for col, val in row.items())
                    for row in rows
                ]

                # (2) OpenAI Embeddings: 배치 호출
                batch_size = 500
                vectors = []
                for i in range(0, len(texts), batch_size):
                    batch = texts[i : i + batch_size]
                    self.stdout.write(f"   ▶️ Embedding batch {i}~{i+len(batch)} …")
                    resp = openai.embeddings.create(
                        model="text-embedding-3-small",
                        input=batch
                    )
                    vectors.extend([e.embedding for e in resp.data])

                # (3) bulk 액션 생성
                for row, vec, txt in zip(rows, vectors, texts):
                    # ==========================================================
                    # ✅ 숫자 필드를 float으로 변환하는 로직 추가
                    # ==========================================================
                    numeric_fields = ['per', 'pbr', 'eps', 'perx', 'pbrx', 'epsx', 'avg_prft_rate', 'btrm_prft_rate1', 'guar_rate']
                    for field in numeric_fields:
                        if field in row and row[field] is not None:
                            try:
                                # 쉼표(,)가 포함된 숫자 문자열 처리 (예: "1,234.5")
                                if isinstance(row[field], str):
                                    row[field] = row[field].replace(',', '')
                                row[field] = float(row[field])
                            except (ValueError, TypeError):
                                # 숫자로 변환할 수 없는 값(예: 'N/A')은 None으로 처리
                                row[field] = None
                    # ==========================================================
                    actions.append({
                        "_op_type": "index",
                        "_index":   index_name,
                        "_id":      f"{tbl}-{row['id']}",
                        "_source": {
                            **row,  # DB에서 읽어온 모든 컬럼(per, pbr 등)을 여기에 포함
                            "text":         txt,
                            "embedding":    vec,
                            "table":        tbl,
                            "product_type": korean
                        }
                    })

        # 6) bulk 색인 with retry/backoff
        def bulk_with_retry(client, actions, chunk_size=100, max_retries=5):
            total = 0
            for i in range(0, len(actions), chunk_size):
                batch = actions[i : i + chunk_size]
                retries = 0
                while True:
                    try:
                        success, _ = helpers.bulk(
                            client,
                            batch,
                            chunk_size=chunk_size,
                            request_timeout=60
                        )
                        total += success
                        break
                    except exceptions.TransportError as e:
                        if e.status_code == 429 and retries < max_retries:
                            wait = 2 ** retries
                            self.stdout.write(f"⚠️  429 Too Many Requests, retrying in {wait}s…")
                            time.sleep(wait)
                            retries += 1
                        else:
                            raise
            return total

        self.stdout.write(f"▶️ Indexing {len(actions)} documents with retry logic…")
        success_count = bulk_with_retry(os_client, actions, chunk_size=100)
        self.stdout.write(self.style.SUCCESS(f"✅ Successfully indexed {success_count} documents."))

        # 7) 색인 후 refresh_interval 복원
        os_client.indices.put_settings(
            index=index_name,
            body={"index": {"refresh_interval": "1s"}}
        )
        self.stdout.write("▶️ Restored refresh_interval to 1s.")
