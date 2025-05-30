FROM python:3.9.6-slim

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    build-essential \
    gcc \
    python3-dev \
    libmariadb-dev-compat \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 출력 버퍼링 제거
ENV PYTHONUNBUFFERED 1

# 작업 디렉토리 생성 및 설정
RUN mkdir /app
WORKDIR /app

# requirements 먼저 복사하고 설치 (캐시 최적화)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# 코드 복사
COPY . /app/