import os
import time
import pymysql
from pathlib import Path
from django.core.management.base import BaseCommand
from openai import OpenAI
from opensearchpy import OpenSearch, helpers, exceptions
from chat.opensearch_client import OPENSEARCH_CLIENT as default_os_client

KOR_LABELS = {
    "deposit": {
        "kor_co_nm": "금융회사",
        "fin_prdt_nm": "상품명",
        "spcl_cnd": "우대조건",
        "join_member": "가입대상",
        "join_way": "가입방법",
        "mtrt_int": "만기후이자",
        "etc_note": "비고",
    },
    "savings": {
        "kor_co_nm": "금융회사",
        "fin_prdt_nm": "상품명",
        "spcl_cnd": "우대조건",
        "join_member": "가입대상",
        "join_way": "가입방법",
        "mtrt_int": "만기후이자",
        "etc_note": "비고",
    },
    "annuity": {
        "kor_co_nm": "운용회사",
        "fin_prdt_nm": "상품명",
        "pnsn_kind_nm": "연금종류",
        "prdt_type_nm": "상품유형",
        "avg_prft_rate": "평균수익률(%)",
        "btrm_prft_rate1": "전년도수익률(%)",
        "guar_rate": "최저보증이율(%)",
        "sale_co": "판매사",
        "join_way": "가입방법",
        "sale_strt_day": "판매시작일",
    },
    "krx_stock_info": {
        "bstp_kor_isnm": "종목명",
        "prdt_abrv_name": "약식명",
        "stck_shrn_iscd": "종목코드",
        "stck_prpr": "현재가(원)",
        "per": "PER",
        "pbr": "PBR",
        "eps": "EPS",
    },
    "nasdaq_stock_info": {
        "prdt_abrv_name": "약식명",
        "code": "티커",
        "last": "현재가($)",
        "perx": "PER",
        "pbrx": "PBR",
        "epsx": "EPS",
        "e_icod": "섹터",
    },
}

SYNONYM_TAGS = {
    "deposit": "키워드: 예금, 정기예금, 금리, 이율, 우대조건",
    "savings": "키워드: 적금, 정기적금, 자유적금, 금리, 이율, 우대",
    "annuity": "키워드: 연금, 연금저축, 연금보험, IRP, 보증이율, 최저보증",
    "krx_stock_info": "키워드: 국내주식, PER, PBR, EPS",
    "nasdaq_stock_info": "키워드: 해외주식, PER, PBR, EPS, 나스닥",
}

def _readable_text(row: dict, tbl: str, product_type_ko: str) -> str:
    """
    한글 라벨을 적용해 사람이 읽기 쉬운 요약 텍스트를 생성.
    임베딩 품질을 위해 [상품유형] 토큰과 유의어 키워드를 포함.
    """
    labels = KOR_LABELS.get(tbl, {})
    parts = [f"[{product_type_ko}]"]  # 예: [예금], [적금], [연금], [국내주식], [해외주식]

    # 라벨 순서대로 먼저 출력하고, 남은 컬럼은 원래 컬럼명으로 보강
    used = set()
    for col in labels.keys():
        if col in row and row[col] not in (None, ""):
            parts.append(f"{labels[col]}: {row[col]}")
            used.add(col)

    for col, val in row.items():
        if col in used or val in (None, ""):
            continue
        parts.append(f"{col}: {val}")

    # 유의어 키워드 라인 추가(시맨틱 매칭 강화를 위한 약한 프롬프트)
    syn = SYNONYM_TAGS.get(tbl)
    if syn:
        parts.append(syn)

    return "\n".join(parts)

class Command(BaseCommand):
    help = "RDS에서 금융상품과 주식 데이터를 읽어 OpenSearch Service에 k-NN 벡터 색인합니다."

    def handle(self, *args, **options):
        ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
        os_client = None

        if ENVIRONMENT == "local":
            # --- 로컬 환경 (SSH 터널) 설정 ---
            self.stdout.write(self.style.WARNING("Running in LOCAL environment mode, connecting via SSH tunnel..."))
            os_client = OpenSearch(
                hosts=[{"host": "localhost", "port": 9200}],
                http_auth=(os.getenv("OPENSEARCH_USER"), os.getenv("OPENSEARCH_PASS")),
                use_ssl=True,
                verify_certs=False,
                ssl_assert_hostname=False,
                timeout=60
            )
        else:
            # --- 서버 환경 (EC2) 설정 ---
            self.stdout.write(self.style.SUCCESS("Running in PRODUCTION environment mode, connecting via IAM role..."))
            os_client = default_os_client

        # 2) RDS 접속 정보
        db_conf = {
            "host": os.getenv("DB_HOST"),
            "port": int(os.getenv("DB_PORT", 3306)),
            "user": os.getenv("DB_USER"),
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
                            "text": {"type": "text"},
                            "product_type": {"type": "keyword"},
                            "table": {"type": "keyword"},
                            "embedding": {"type": "knn_vector", "dimension": 1536},
                            "per": {"type": "float"},
                            "pbr": {"type": "float"},
                            "eps": {"type": "float"},
                            "perx": {"type": "float"},
                            "pbrx": {"type": "float"},
                            "epsx": {"type": "float"},
                            "avg_prft_rate": {"type": "float"},
                            "btrm_prft_rate1": {"type": "float"},
                            "guar_rate": {"type": "float"}
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
                    _readable_text(row, tbl, korean)
                    for row in rows
                ]

                # (2) OpenAI Embeddings: 배치 호출
                batch_size = 500
                vectors = []
                for i in range(0, len(texts), batch_size):
                    batch = texts[i: i + batch_size]
                    self.stdout.write(f" ▶️ Embedding batch {i}~{i+len(batch)} …")
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
                    numeric_fields = [
                        'per', 'pbr', 'eps', 'perx', 'pbrx', 'epsx',
                        'avg_prft_rate', 'btrm_prft_rate1', 'guar_rate'
                    ]
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
                        "_index": index_name,
                        "_id": f"{tbl}-{row['id']}",
                        "_source": {
                            **row,  # DB에서 읽어온 모든 컬럼(per, pbr 등)을 여기에 포함
                            "text": txt,
                            "embedding": vec,
                            "table": tbl,
                            "product_type": korean
                        }
                    })

        # 6) bulk 색인 with retry/backoff
        def bulk_with_retry(client, actions, chunk_size=100, max_retries=5):
            total = 0
            for i in range(0, len(actions), chunk_size):
                batch = actions[i: i + chunk_size]
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
                            self.stdout.write(f"⚠️ 429 Too Many Requests, retrying in {wait}s…")
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
