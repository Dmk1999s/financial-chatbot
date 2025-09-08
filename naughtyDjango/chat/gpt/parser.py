import json
import re


def extract_json_from_response(text: str):
    """OpenAI 응답에서 JSON 부분만 안전하게 추출"""
    try:
        # 백틱 블럭 제거 (```json ~ ```)
        cleaned_text = re.sub(r"```json|```", "", text).strip()

        # 중괄호 감싸진 JSON 텍스트 추출
        match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        else:
            return {}
    except Exception:
        # 파싱 중 에러나면 빈 dict 반환
        return {}


def extract_fields_from_natural_response(response_text: str, session_id: str) -> dict:
    """
    자연어 문장(사용자/모델 응답)에서 나이, 소득 등 주요 필드를 정규식으로 추출
    """
    fields = {}
    text_lower = response_text.lower()

    # 나이 추출
    age_match = re.search(r'(\d+)살|나이.*?(\d+)|age.*?(\d+)', text_lower)
    if age_match:
        fields['age'] = int(age_match.group(1) or age_match.group(2) or age_match.group(3))

    # 월 소득 추출 (만원 단위 등을 원 단위로 변환)
    income_match = re.search(r'(\d+)만원|월급.*?(\d+)|수입.*?(\d+)', text_lower)
    if income_match:
        fields['monthly_income'] = int(income_match.group(1) or income_match.group(2) or income_match.group(3)) * 10000

    # 위험 성향 추출
    if any(word in text_lower for word in ['안전', '보수적', '낮음']):
        fields['risk_tolerance'] = '낮음'
    elif any(word in text_lower for word in ['적극적', '높음', '공격적']):
        fields['risk_tolerance'] = '높음'
    elif '중간' in text_lower:
        fields['risk_tolerance'] = '중간'

    return fields


