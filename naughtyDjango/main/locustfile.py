from locust import HttpUser, task, between
import json
import uuid


class WebsiteTestUser(HttpUser):
    wait_time = between(1, 3)  # 대기 시간을 줄여서 더 많은 요청 생성
    host = "http://localhost:8000"
    connection_timeout = 10.0  # 연결 타임아웃 설정
    network_timeout = 10.0  # 네트워크 타임아웃 설정

    def on_start(self):
        """각 사용자 세션 시작 시 실행"""
        self.session_id = str(uuid.uuid4())
        # 실제 존재하는 사용자명 사용 (예: admin 또는 기존 사용자)
        self.username = "string"  # 또는 실제 DB에 존재하는 사용자명

    @task(2)
    def chat_test(self):
        """채팅 API 테스트"""
        payload = {
            "username": self.username,
            "session_id": self.session_id,
            "message": "안녕하세요, 투자 상담을 받고 싶습니다."
        }
        with self.client.post("/chats/chat/", 
                            json=payload,
                            headers={"Content-Type": "application/json"},
                            catch_response=True) as response:
            print(f"Response status: {response.status_code}, URL: /chats/chat/")
            print(f"Response text: {response.text[:202]}")
            if response.status_code == 202:
                response.success()
            elif response.status_code == 500:
                response.failure(f"Server Error: {response.status_code}")
            else:
                response.failure(f"Unexpected status: {response.status_code} - {response.text[:100]}")

    @task(1)
    def health_check(self):
        """헬스체크 - 가장 간단한 요청"""
        with self.client.get("/", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")