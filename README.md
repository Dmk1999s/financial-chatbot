# Naughty BE Django

투자 성향을 이해하고 개인화된 금융 상품을 추천하는 2025년 졸업 프로젝트 백엔드입니다. Django, Celery, Redis, OpenSearch, LangChain, OpenAI를 결합해 **투자 프로필 수집 → 충돌 검증 → RAG 기반 추천**을 한 번에 처리할 수 있는 API를 제공합니다.

## 목차
- [프로젝트 소개](#프로젝트-소개)
- [핵심 기능](#핵심-기능)
- [시스템 구성](#시스템-구성)
- [디렉터리 구조](#디렉터리-구조)
- [빠른 시작](#빠른-시작)
  - [환경 변수](#환경-변수)
  - [로컬 개발 (Python)](#로컬-개발-python)
  - [Docker Compose 실행](#docker-compose-실행)
- [주요 API](#주요-api)
- [운영 및 배포 팁](#운영-및-배포-팁)
- [테스트 및 유틸리티](#테스트-및-유틸리티)
- [기여 가이드](#기여-가이드)

## 프로젝트 소개
- 이름: **Naughty BE Django** (a.k.a NauhtyComputer 백엔드)
- 목적: 투자자 프로필을 기반으로 AI가 맞춤 금융 상품을 추천해 주는 대화형 서비스
- 주요 기술: `Django 4.2`, `Django REST Framework`, `Celery`, `Redis`, `OpenAI`, `LangChain`, `OpenSearch`, `MySQL`
- 배포 대상: GitHub Public 레포지터리 (팀/외부 협업자 열람용)

## 핵심 기능
- **GPT 기반 투자 프로필 수집**  
  - `POST /chats/chat_profile_gather/`  
  - Celery 비동기 처리로 응답 지연 없이 빠른 UX 제공  
  - LLM이 감지한 필드와 DB 값이 다르면 실시간 충돌을 반환 (`code = COMMON2001`)

- **충돌 관리 워크플로**  
  - 프로필 업데이트 충돌 시 캐시로 pending 상태 보관  
  - `POST /chats/profile/conflict/`에서 사용자의 의사를 다시 확인해 안전하게 DB 반영

- **LangChain + OpenAI 기반 RAG 추천**  
  - `POST /chats/chat/`  
  - LangChain Agent가 Profile Tool, Stock Screener, OpenSearch Lookup Tool을 조합해 답변  
  - 재무 지표, 조건 스크리닝, 간단 잡담을 한 번에 처리

- **OpenSearch 금융 상품 인덱싱**  
  - 내부 관리 명령 `python manage.py index_to_opensearch`  
  - `POST /chats/opensearch/index/`로 원격에서 Celery 작업으로 인덱싱 트리거

- **API 문서 & 관측성**  
  - 자동 문서: `https://<도메인>/swagger/`, `https://<도메인>/redoc/`  
  - `chat/observability/tracing.py`를 통해 추적, 로거, 성능 로그 (`performance.log`)

## 시스템 구성
- **Django (Gunicorn)**: 메인 REST API 서버 (`main` 모듈)
- **Celery Worker**: GPT 호출, 추천, OpenSearch 인덱싱을 비동기 처리  
- **Redis**: Celery 브로커 & 캐시 (세션, 충돌 Pending 데이터 저장)
- **MySQL**: 사용자/금융 데이터 저장 (`user`, `deposit`, `savings`, `annuity`, `krx_stock_info`, `nasdaq_stock_info` 등)
- **OpenSearch**: 금융 상품/주식 데이터 RAG 검색 인덱스
- **Docker Compose**: `web`, `celery`, `redis`, `nginx` 서비스 배포
- **Nginx**: Reverse Proxy, 정적 파일 (`static_volume`, `media_volume`) 제공

## 디렉터리 구조
```text
naughtyDjango/
├── chat/                  # 챗봇, RAG, OpenSearch 관련 앱
│   ├── views/             # DRF 뷰 (chat, recommend, conflict, opensearch)
│   ├── gpt/               # GPT 대화 흐름, 세션 저장소, 프롬프트
│   ├── rag/               # LangChain Agent & Tool 모듈
│   ├── tasks.py           # Celery 비동기 작업 (chat, recommend, indexing)
│   └── services.py        # 비즈니스 로직 (프로필/추천 서비스)
├── main/                  # Django 프로젝트 설정 및 공통 유틸
│   ├── settings.py        # 환경 설정 (DB, Redis, Celery, CORS)
│   ├── urls.py            # 전역 URL 라우팅 (Swagger 포함)
│   └── utils/             # 공통 응답, 로깅 등 유틸리티
├── config/                # Docker, Nginx, Scripts, Systemd 설정
├── docker-compose.yml     # 로컬/서버 Docker 오케스트레이션
├── requirements.txt       # Python 종속성 (pip install)
└── test_conflict_detection.py
```

## 빠른 시작

### 환경 변수
`.env` 파일을 레포지터리 루트에 생성해 다음 값을 채워주세요.

```env
# Django
SECRET_KEY=django-insecure-...
DEBUG=True

# Database (MySQL)
DB_USER=your_user
DB_PASSWORD=your_password
DB_HOST=127.0.0.1
LOCAL_PORT=3306

# Redis / Celery
REDIS_HOST=redis
REDIS_PORT=6379

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_AGENT_MODEL=gpt-4o-mini

# OpenSearch
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_USER=admin
OPENSEARCH_PASS=admin
OPENSEARCH_INDEX=financial-products
ENVIRONMENT=local
```

> 운영 환경에서는 `DEBUG=False`, 비밀 값은 안전한 저장소/배포 플랫폼에서 관리하세요.

### 로컬 개발 (Python)
```bash
# 1. 가상환경 생성
python -m venv .venv
source .venv/bin/activate

# 2. 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt

# 3. Django 준비
cd naughtyDjango
python manage.py migrate
python manage.py collectstatic --noinput  # 필요 시

# 4. 개발 서버 실행
python manage.py runserver 0.0.0.0:8000
```

필요 소재:
- MySQL 8+ (스키마: `ncdb`, `config`)
- Redis 7+
- OpenSearch 2.x (선택, 추천 기능에 필요)
- `.tsv` 데이터 (`krx_stock_info.tsv`, `nasdaq_stock_info.tsv`)는 OpenSearch 인덱싱 시 사용

### Docker Compose 실행
```bash
# 최초 실행
docker compose up --build

# 백그라운드 실행
docker compose up -d

# 로그 보기
docker compose logs -f web

# Celery 워커 로그
docker compose logs -f celery
```

서비스 포트:
- Django (Gunicorn): `8000`
- Nginx: `80`, `443`
- Redis: `6379`

## 주요 API
| Method | Endpoint | 설명 |
| ------ | -------- | ---- |
| `POST` | `/chats/chat_profile_gather/` | GPT가 투자 프로필 질문을 진행하고 Celery로 비동기 응답 |
| `GET`  | `/chats/task/<task_id>/` | Celery 작업 상태/결과 조회 (충돌 감지 포함) |
| `POST` | `/chats/profile/conflict/` | 충돌 발생 시 사용자 선택(yes/no)을 반영 |
| `DELETE` | `/chats/session/<session_id>/end/` | 세션 캐시 및 GPT 스토어 정리 |
| `POST` | `/chats/chat/` | LangChain Agent 기반 금융 상품 상담/추천 |
| `POST` | `/chats/opensearch/index/` | 금융 데이터 OpenSearch 인덱싱 작업 큐잉 |
| `GET`  | `/swagger/` | Swagger UI (자동 문서) |
| `GET`  | `/redoc/` | ReDoc UI |

### Celery 태스크 요약
- `process_chat_async`: 투자 프로필 수집, LLM 충돌 감지, 최종 답변 저장
- `process_recommend_async`: LangChain Agent 실행 (추천/잡담/거절)
- `index_financial_products`: `manage.py index_to_opensearch` 호출

## 운영 및 배포 팁
- Gunicorn 옵션은 `config/docker/entrypoint.prod.sh`에서 설정 (worker 4, timeout 30s)  
- Celery는 메모리 사용을 고려해 `--max-memory-per-child=350MB` 등으로 제한  
- 정적/미디어 파일은 Docker Volume (`static_volume`, `media_volume`)으로 분리  
- CORS 설정은 `main/settings.py`에서 관리 (프론트엔드 도메인 추가 필요)  
- DB Router(`main/db_routers.py`)는 `main` 앱 모델 일부를 보조 DB로 라우팅할 수 있도록 준비됨  
- 성능 로그는 레포 루트의 `performance.log`에 기록됨

## 테스트 및 유틸리티
- `test_conflict_detection.py`: API 통합 시나리오 테스트 (나이/소득 충돌 감지 포함).  
  ```bash
  python test_conflict_detection.py  # localhost:8000 기준
  ```
- `chat/observability/tracing.py`: 시나리오별 트레이싱 확장 포인트
- `chat/performance_settings.py`: 대량 트래픽 대비 설정 모음

## 기여 가이드
1. 이슈를 먼저 등록하고 논의합니다.
2. 새 브랜치를 생성해 작업합니다. (`feature/`, `bugfix/` 등)
3. Django 코드는 `black` 또는 `isort` 등 스타일 가이드에 맞춰 정리합니다. (필요 시 추가)
4. 단위/통합 테스트를 작성하고 통과 여부를 공유합니다.
5. Pull Request에 변경 내용, 테스트 결과, 관련 이슈를 명시합니다.

---
프로젝트 관련 질문이나 이슈는 Issues 탭을 활용해 주세요. 좋은 투자 경험을 만드는 Naughty 팀을 응원합니다! 🙌
