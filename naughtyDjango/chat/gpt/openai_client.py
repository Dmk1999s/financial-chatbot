import os
from dotenv import load_dotenv
from openai import OpenAI
from django.core.cache import cache


load_dotenv()


class OptimizedOpenAIClient:
    """OpenAI 호출에 간단 캐싱과 재시도/타임아웃을 적용한 래퍼"""

    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            max_retries=2,
            timeout=30.0,
        )

    def create_completion(self, messages, model="gpt-3.5-turbo", **kwargs):
        # 동일한 메시지 배열에 대해 캐시를 먼저 확인
        prompt_str = str(messages)
        cache_key = f"gpt_response_{hash(prompt_str)}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,
        )

        # 응답을 5분간 캐싱
        cache.set(cache_key, response, 300)
        return response


# 모듈 단일 인스턴스
client = OptimizedOpenAIClient()


