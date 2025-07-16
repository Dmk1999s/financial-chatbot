#!/bin/sh

# 진입점 경로 수정
cd /app


echo "==== [WORKDIR] 현재 작업 디렉토리 ===="
pwd

echo "==== [/app] 디렉토리 구조 ===="
ls -al /app

echo "==== [/app/naughtyDjango] 디렉토리 구조 ===="
ls -al /app/naughtyDjango

echo "==== Python 패키지 경로(sys.path) ===="
python -c "import sys; print(sys.path)"

echo "==== 파이썬 주요 패키지 현황(pip list) ===="
pip list

# 마이그레이션, collectstatic 등 필요한 커맨드
python manage.py migrate
python manage.py collectstatic --noinput

export PYTHONPATH=/app

# gunicorn 실행
exec gunicorn naughtyDjango.main.wsgi:application --bind 0.0.0.0:8000