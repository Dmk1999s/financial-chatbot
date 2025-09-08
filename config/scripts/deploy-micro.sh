#!/bin/bash

echo "🚀 Deploying to t2.micro instance..."

cd /home/ubuntu/srv/ubuntu

# 기존 컨테이너 정리
echo "🧹 Cleaning up existing containers..."
docker compose down
docker system prune -f

# 이미지 빌드 (캐시 무효화)
echo "🔨 Building images with no cache..."
docker compose build --no-cache web celery

# 메모리 상태 확인
echo "📊 Memory status:"
free -h

# 단계별 배포
echo "📦 Step 1: Starting Redis only..."
docker compose up -d redis
sleep 10

echo "📦 Step 2: Starting Web application..."
docker compose up -d web
sleep 15

echo "📦 Step 3: Starting Celery worker..."
docker compose up -d celery
sleep 10

echo "📦 Step 4: Starting Nginx..."
docker compose up -d nginx
sleep 5

# 상태 확인
echo "📊 Container status:"
docker compose ps

echo "📊 Memory usage:"
free -h

echo "✅ Deployment complete!"
