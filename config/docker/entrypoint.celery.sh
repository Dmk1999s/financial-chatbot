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
exec celery -A main worker -l info --concurrency=2