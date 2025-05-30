FROM python:3.9.6-slim

RUN chmod +x /home/app/entrypoint.prod.sh

# 시스템 패키지 설치
RUN apt-get update
RUN apt-get install -y gcc
RUN apt-get install -y default-libmysqlclient-dev
RUN apt-get update && apt-get install -y pkg-config

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