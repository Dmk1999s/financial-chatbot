#!/bin/sh

cd /app/naughtyDjango

export PYTHONPATH=/app/naughtyDjango

# Wait for Redis to be ready
echo "Waiting for Redis..."
while ! nc -z redis 6379; do
  sleep 1
done
echo "Redis is ready!"

# Start Celery worker
#exec celery -A main worker -l info --concurrency=2

# Celery worker를 메모리 친화적으로 실행
exec celery -A main worker -l info \
  --concurrency=1 \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=1 \
  --max-memory-per-child=350000