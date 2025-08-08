import logging
import time
from functools import wraps
from django.http import JsonResponse

# 로거 설정
logger = logging.getLogger(__name__)

def api_logger(func):
    """API 호출 로깅 데코레이터"""
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        start_time = time.time()
        
        # 요청 정보 로깅
        logger.info(f"[API 시작] {request.method} {request.path} - User: {getattr(request, 'user', 'Anonymous')}")
        
        try:
            # 실제 함수 실행
            response = func(request, *args, **kwargs)
            
            # 성공 로깅
            duration = time.time() - start_time
            logger.info(f"[API 성공] {request.method} {request.path} - {duration:.2f}초")
            
            return response
            
        except Exception as e:
            # 에러 로깅
            duration = time.time() - start_time
            logger.error(f"[API 에러] {request.method} {request.path} - {duration:.2f}초 - Error: {str(e)}")
            raise
    
    return wrapper

def chat_logger(func):
    """채팅 전용 로깅 데코레이터"""
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        start_time = time.time()
        
        # 채팅 요청 정보
        if hasattr(request, 'body'):
            import json
            try:
                body = json.loads(request.body)
                username = body.get('username', 'Unknown')
                message = body.get('message', '')[:50] + '...' if len(body.get('message', '')) > 50 else body.get('message', '')
                logger.info(f"[채팅 시작] User: {username} - Message: {message}")
            except:
                logger.info(f"[채팅 시작] {request.method} {request.path}")
        
        try:
            response = func(request, *args, **kwargs)
            duration = time.time() - start_time
            logger.info(f"[채팅 완료] {duration:.2f}초")
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[채팅 에러] {duration:.2f}초 - Error: {str(e)}")
            raise
    
    return wrapper