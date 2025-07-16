FROM python:3.9.6-slim

# 필수 시스템 패키지 설치 (한 줄로 묶기)
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python 출력 버퍼링 제거
ENV PYTHONUNBUFFERED=1

# 작업 디렉토리 설정 (HOME 기반으로 수정 가능)
WORKDIR /app

# 종속성 먼저 복사하고 설치 (캐시 최적화)
COPY requirements.txt .

RUN pip install --upgrade pip && pip install -r requirements.txt

# 전체 코드 복사
COPY . .

COPY ./config/docker/entrypoint.prod.sh /entrypoint.prod.sh

# 실행 권한 부여
RUN chmod +x /entrypoint.prod.sh

RUN echo '[DEBUG] /app/naughtyDjango:' && ls -al /app/naughtyDjango
RUN echo '[DEBUG] /app 전체:' && ls -al /app
RUN echo '[DEBUG] Python 패키지:' && pip list
RUN python -c "import sys; print('[DEBUG] sys.path:', sys.path)"


# 엔트리포인트 지정
ENTRYPOINT ["/entrypoint.prod.sh"]
