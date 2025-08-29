#!/usr/bin/env python3
"""
충돌 감지 기능 테스트 스크립트
"""

import requests
import json
import time
import sys

# API 기본 URL
BASE_URL = "http://localhost:8000"

def test_simple_chat():
    """간단한 채팅 테스트"""
    print("=== 간단한 채팅 테스트 ===")
    
    url = f"{BASE_URL}/chats/chat/"
    data = {
        "username": "ehdgurdusdn@naver.com",
        "message": "안녕하세요"
    }
    
    try:
        response = requests.post(url, json=data)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get("isSuccess") and "task_id" in result.get("result", {}):
                return result["result"]["task_id"]
        
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def test_task_status(task_id):
    """태스크 상태 확인"""
    print(f"\n=== 태스크 상태 확인 (task_id: {task_id}) ===")
    
    url = f"{BASE_URL}/chats/task/{task_id}/"
    
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        
        return response.json()
    except Exception as e:
        print(f"Error: {e}")
        return None

def test_conflict_detection():
    """충돌 감지 테스트"""
    print("\n=== 충돌 감지 테스트 ===")
    
    # 1. 첫 번째 메시지 (나이 설정)
    print("\n1. 첫 번째 메시지 전송 (나이: 25세)")
    url = f"{BASE_URL}/chats/chat/"
    data = {
        "username": "ehdgurdusdn@naver.com",
        "message": "저는 25살이에요"
    }
    
    try:
        response = requests.post(url, json=data)
        print(f"Status Code: {response.status_code}")
        result = response.json()
        print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        if result.get("isSuccess") and "task_id" in result.get("result", {}):
            task_id = result["result"]["task_id"]
            
            # 2. 태스크 완료 대기
            print(f"\n2. 태스크 완료 대기 중... (task_id: {task_id})")
            max_wait = 30  # 최대 30초 대기
            wait_time = 0
            
            while wait_time < max_wait:
                task_result = test_task_status(task_id)
                if task_result and task_result.get("result", {}).get("status") == "completed":
                    print("태스크 완료!")
                    break
                elif task_result and task_result.get("result", {}).get("status") == "failed":
                    print("태스크 실패!")
                    break
                
                time.sleep(2)
                wait_time += 2
                print(f"대기 중... ({wait_time}초)")
            
            # 3. 두 번째 메시지 (나이 변경 - 충돌 유발)
            print("\n3. 두 번째 메시지 전송 (나이: 30세 - 충돌 유발)")
            data = {
                "username": "ehdgurdusdn@naver.com",
                "message": "아, 제가 30살이에요"
            }
            
            response = requests.post(url, json=data)
            print(f"Status Code: {response.status_code}")
            result = response.json()
            print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            if result.get("isSuccess") and "task_id" in result.get("result", {}):
                task_id2 = result["result"]["task_id"]
                
                # 4. 두 번째 태스크 완료 대기
                print(f"\n4. 두 번째 태스크 완료 대기 중... (task_id: {task_id2})")
                wait_time = 0
                
                while wait_time < max_wait:
                    task_result = test_task_status(task_id2)
                    if task_result:
                        print(f"Task Result: {json.dumps(task_result, indent=2, ensure_ascii=False)}")
                        
                        # 충돌 감지 확인
                        if (task_result.get("isSuccess") and 
                            task_result.get("code") == "COMMON2001" and
                            task_result.get("result", {}).get("requires_confirmation")):
                            print("\n✅ 충돌 감지 성공! 2001 응답을 받았습니다.")
                            return True
                        elif task_result.get("result", {}).get("status") == "completed":
                            print("태스크 완료 (충돌 없음)")
                            break
                        elif task_result.get("result", {}).get("status") == "failed":
                            print("태스크 실패!")
                            break
                    
                    time.sleep(2)
                    wait_time += 2
                    print(f"대기 중... ({wait_time}초)")
        
    except Exception as e:
        print(f"Error: {e}")
    
    return False

def test_income_conflict():
    """소득 충돌 감지 테스트"""
    print("\n=== 소득 충돌 감지 테스트 ===")
    
    # 1. 첫 번째 메시지 (소득 설정)
    print("\n1. 첫 번째 메시지 전송 (소득: 300만원)")
    url = f"{BASE_URL}/chats/chat/"
    data = {
        "username": "ehdgurdusdn@naver.com",
        "message": "월급이 300만원이에요"
    }
    
    try:
        response = requests.post(url, json=data)
        result = response.json()
        print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        if result.get("isSuccess") and "task_id" in result.get("result", {}):
            task_id = result["result"]["task_id"]
            
            # 태스크 완료 대기
            print(f"\n2. 태스크 완료 대기 중... (task_id: {task_id})")
            max_wait = 30
            wait_time = 0
            
            while wait_time < max_wait:
                task_result = test_task_status(task_id)
                if task_result and task_result.get("result", {}).get("status") == "completed":
                    print("첫 번째 태스크 완료!")
                    break
                time.sleep(2)
                wait_time += 2
            
            # 3. 두 번째 메시지 (소득 변경 - 충돌 유발)
            print("\n3. 두 번째 메시지 전송 (소득: 500만원 - 충돌 유발)")
            data = {
                "username": "ehdgurdusdn@naver.com",
                "message": "아, 월급이 500만원이에요"
            }
            
            response = requests.post(url, json=data)
            result = response.json()
            print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            if result.get("isSuccess") and "task_id" in result.get("result", {}):
                task_id2 = result["result"]["task_id"]
                
                # 두 번째 태스크 완료 대기
                print(f"\n4. 두 번째 태스크 완료 대기 중... (task_id: {task_id2})")
                wait_time = 0
                
                while wait_time < max_wait:
                    task_result = test_task_status(task_id2)
                    if task_result:
                        print(f"Task Result: {json.dumps(task_result, indent=2, ensure_ascii=False)}")
                        
                        # 충돌 감지 확인
                        if (task_result.get("isSuccess") and 
                            task_result.get("code") == "COMMON2001" and
                            task_result.get("result", {}).get("requires_confirmation")):
                            print("\n✅ 소득 충돌 감지 성공! 2001 응답을 받았습니다.")
                            return True
                        elif task_result.get("result", {}).get("status") == "completed":
                            print("태스크 완료 (충돌 없음)")
                            break
                    
                    time.sleep(2)
                    wait_time += 2
        
    except Exception as e:
        print(f"Error: {e}")
    
    return False

def main():
    """메인 테스트 함수"""
    print("🚀 충돌 감지 기능 테스트 시작")
    print("=" * 50)
    
    # 1. 간단한 채팅 테스트
    task_id = test_simple_chat()
    if task_id:
        print(f"✅ 간단한 채팅 테스트 성공 (task_id: {task_id})")
        
        # 태스크 완료 대기
        print("\n태스크 완료 대기 중...")
        time.sleep(5)
        test_task_status(task_id)
    else:
        print("❌ 간단한 채팅 테스트 실패")
        return
    
    print("\n" + "=" * 50)
    
    # 2. 나이 충돌 감지 테스트
    if test_conflict_detection():
        print("✅ 나이 충돌 감지 테스트 성공")
    else:
        print("❌ 나이 충돌 감지 테스트 실패")
    
    print("\n" + "=" * 50)
    
    # 3. 소득 충돌 감지 테스트
    if test_income_conflict():
        print("✅ 소득 충돌 감지 테스트 성공")
    else:
        print("❌ 소득 충돌 감지 테스트 실패")
    
    print("\n" + "=" * 50)
    print("🏁 테스트 완료!")

if __name__ == "__main__":
    main()
