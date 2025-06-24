#!/bin/sh

# DB가 준비될 때까지 대기 (옵션)
# ./wait-for-it.sh db:3306 --timeout=30 -- echo "DB is up"

echo "📦 Running migrations..."
python manage.py migrate --noinput

echo "🧹 Collecting static files..."
python manage.py collectstatic --noinput

echo "🚀 Starting application..."
exec "$@"