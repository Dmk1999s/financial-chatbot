#!/bin/bash

echo "🚀 Setting up Celery as Systemd service..."

# 서비스 파일 복사
sudo cp config/systemd/celery.service /etc/systemd/system/

# 서비스 활성화 및 시작
sudo systemctl daemon-reload
sudo systemctl enable celery
sudo systemctl start celery

# 상태 확인
echo "📊 Celery service status:"
sudo systemctl status celery

echo "✅ Systemd setup complete!"
echo "📋 Useful commands:"
echo "  - Check status: sudo systemctl status celery"
echo "  - Start service: sudo systemctl start celery"
echo "  - Stop service: sudo systemctl stop celery"
echo "  - Restart service: sudo systemctl restart celery"
echo "  - View logs: sudo journalctl -u celery -f"
