from celery import shared_task
from openai import OpenAI
import os
from .models import ChatMessage
from main.models import User
from .gpt_service import extract_json_from_response, handle_chat

DETECTION_SYSTEM = """
당신은 '투자 프로필 변경 트리거'를 감지하는 어시스턴트입니다.
사용자 발화를 보고, 아래 필드 중 변경 의도가 있는지 JSON으로 반환하세요.

감지할 필드:
- age: 나이 (예: "25살", "30세", "나이 25" 등)
- monthly_income: 월 수입 (예: "300만원", "월급 500만원" 등)
- risk_tolerance: 위험 허용 정도 (예: "보수적", "적극적", "중간" 등)
- income_stability: 소득 안정성 (예: "안정적", "불안정" 등)
- income_sources: 소득원 (예: "월급", "아르바이트" 등)
- investment_horizon: 투자 기간 (예: "1년", "3개월" 등)
- expected_return: 기대 수익 (예: "10%", "100만원" 등)
- expected_loss: 예상 손실 (예: "5%", "50만원" 등)
- investment_purpose: 투자 목적 (예: "안정적 수익", "성장" 등)
- asset_allocation_type: 자산 배분 유형 (0-4)
- value_growth: 가치/성장 구분 (0: 가치, 1: 성장)
- risk_acceptance_level: 위험 수용 수준 (1-4)
- investment_concern: 투자 관련 고민 (문자열)

응답 형식:
{"field": "필드명", "value": "값"}

예시:
- "저는 25살이에요" → {"field": "age", "value": 25}
- "월급이 300만원이에요" → {"field": "monthly_income", "value": 3000000}
- "보수적으로 투자하고 싶어요" → {"field": "risk_tolerance", "value": "낮음"}

변경 의도가 없으면 {} 만 반환하세요.
"""

@shared_task
def process_chat_async(session_id, username, message, product_type):
    """Async task for heavy GPT processing"""
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
                # DB에서 사용자 정보 가져오기
                try:
                    user = User.objects.get(email=username)
                    current_data = {}
                    
                    # DB 필드와 매핑
                    field_mapping = {
                        'age': user.age,
                        'monthly_income': user.income,
                        'risk_tolerance': user.risk_tolerance,
                        'income_stability': user.income_stability,
                        'income_sources': user.income_source,
                        'investment_horizon': user.period,
                        'expected_return': user.expected_income,
                        'expected_loss': user.expected_loss,
                        'investment_purpose': user.purpose,
                        'asset_allocation_type': user.asset_allocation_type,
                        'value_growth': user.value_growth,
                        'risk_acceptance_level': user.risk_acceptance_level,
                        'investment_concern': user.investment_concern,
                    }
                    
                    # 현재 DB 값 가져오기
                    current_value = field_mapping.get(field)
                    
                    # 충돌 확인 (DB 값이 있고, 새 값과 다를 때)
                    if current_value is not None and current_value != value:
                        return {
                            "type": "conflict_detected",
                            "field": field,
                            "value": value,
                            "db_value": current_value,
                            "message": f"프로필 변경이 감지되었습니다: {field} = {value} (기존: {current_value})"
                        }
                    else:
                        # 충돌이 없으면 DB 업데이트
                        if field in field_mapping:
                            setattr(user, field, value)
                            user.save(update_fields=[field])
                
                except User.DoesNotExist:
                    pass
        
        # Regular chat flow
        gpt_reply, _ = handle_chat(message, session_id, user_id=username)
        
        ChatMessage.objects.create(
            session_id=session_id,
            username=username,
            product_type=product_type,
            role="assistant",
            message=gpt_reply,
        )
        
        return {"type": "chat_response", "response": gpt_reply}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"type": "error", "error": str(e)}