#!/bin/bash

echo "🔍 Checking Docker..."

# Docker 설치 확인 및 설치
if ! command -v docker > /dev/null; then
  echo "🚫 Docker not found. Installing Docker..."
  sudo apt-get update
  sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
  sudo add-apt-repository \
    "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
  sudo apt-get update
  sudo apt-get install -y docker-ce
else
  echo "✅ Docker already installed."
fi

echo "🔍 Checking Docker Compose..."

# Docker Compose 설치 확인 및 설치 (v2+)
if ! command -v docker-compose > /dev/null && ! docker compose version > /dev/null 2>&1; then
  echo "🚫 Docker Compose not found. Installing Docker Compose..."
  DOCKER_COMPOSE_VERSION="2.24.6"
  sudo curl -SL "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
    -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
else
  echo "✅ Docker Compose already installed."
fi

echo "🚀 Starting Docker Compose..."

cd /home/ubuntu/srv/ubuntu

# 최신 컨테이너 재빌드 및 실행
sudo docker compose down
sudo docker compose up --build -d