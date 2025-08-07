from celery import shared_task
from openai import OpenAI
import os
from .models import ChatMessage, InvestmentProfile
from .gpt_service import extract_json_from_response, handle_chat

DETECTION_SYSTEM = """
당신은 '투자 프로필 변경 트리거'를 감지하는 어시스턴트입니다.
사용자 발화를 보고, 아래 필드 중 변경 의도가 있는지 JSON으로 반환하세요.
필드: age, monthly_income, risk_tolerance, income_stability,
income_sources, investment_horizon, expected_return,
expected_loss, investment_purpose, asset_allocation_type,
value_growth, risk_acceptance_level, investment_concern

예시) {"field":"monthly_income","value":4500000}

변경 의도가 없으면 {} 만 반환하세요.
"""

@shared_task
def process_chat_async(session_id, username, message, product_type):
    """Async task for heavy GPT processing"""
    print(f"Starting task for session {session_id}, user {username}, message: {message}")
    try:
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Change detection
        detect_resp = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": DETECTION_SYSTEM},
                {"role": "user", "content": message},
            ],
            temperature=0,
            max_tokens=100
        )
        
        trigger = extract_json_from_response(detect_resp.choices[0].message.content)
        
        if isinstance(trigger, dict) and trigger:
            field = trigger.get("field")
            value = trigger.get("value")
            if field and value is not None:
                label_map = {
                    "risk_tolerance": "위험 허용 정도",
                    "age": "나이",
                    "income_stability": "소득 안정성",
                    "income_sources": "소득원",
                    "monthly_income": "월 수입",
                    "investment_horizon": "투자 기간",
                    "expected_return": "기대 수익",
                    "expected_loss": "예상 손실",
                    "investment_purpose": "투자 목적",
                    "asset_allocation_type": "자산 배분 유형",
                    "value_growth": "가치/성장 구분",
                    "risk_acceptance_level": "위험 수용 수준",
                    "investment_concern": "투자 관련 고민",
                }
                label = label_map.get(field, field)
                propose_msg = f"{label}이(가) {value}으로 변경된 것 같아요. 프로필에도 업데이트해 드릴까요?"
                
                ChatMessage.objects.create(
                    session_id=session_id,
                    username=username,
                    product_type=product_type,
                    role="assistant",
                    message=propose_msg,
                )
                return {
                    "type": "profile_update",
                    "response": propose_msg,
                    "field": field,
                    "value": value
                }
        
        # Regular chat flow
        gpt_reply, _ = handle_chat(message, session_id, user_id=username)
        
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="assistant",
            message=gpt_reply,
        )
        
        print(f"Task completed successfully: {gpt_reply}")
        return {"type": "chat_response", "response": gpt_reply}
        
    except Exception as e:
        print(f"Task failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"type": "error", "error": str(e)}