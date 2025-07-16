#!/bin/sh

# 진입점 경로 수정
cd /home/app/naughtyDjango

# 마이그레이션, collectstatic 등 필요한 커맨드
python manage.py migrate
python manage.py collectstatic --noinput

# gunicorn 실행
exec gunicorn --chdir /home/app/naughtyDjango naughtyDjango.main.wsgi:application --bind 0.0.0.0:8000