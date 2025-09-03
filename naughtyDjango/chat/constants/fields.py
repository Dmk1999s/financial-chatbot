"""
chat/constants/fields.py

필드 상수/매핑을 관리합니다.
"""

# 수집이 필요한 프로필 키 집합
REQUIRED_KEYS = {
    "age", "risk_tolerance", "income_stability", "income_sources",
    "monthly_income", "investment_horizon", "expected_return", "expected_loss",
    "investment_purpose", "asset_allocation_type", "value_growth",
    "risk_acceptance_level", "investment_concern"
}

# 질문 순서를 고정하기 위한 키 목록
REQUIRED_KEYS_ORDER = [
    "age",
    "risk_tolerance",
    "monthly_income",
    "income_stability",
    "income_sources",
    "investment_horizon",
    "expected_return",
    "expected_loss",
    "investment_purpose",
    "asset_allocation_type",
    "value_growth",
    "risk_acceptance_level",
    "investment_concern",
]

# 각 키의 한국어 질문 문구
QUESTION_KO = {
    "age": "나이를 알려주세요.",
    "risk_tolerance": "위험 허용 정도는 어느 수준인가요? (낮음/중간/높음)",
    "monthly_income": "월 소득은 얼마인가요? (원 단위 숫자)",
    "income_stability": "소득 안정성은 어떤가요? (안정적/불안정)",
    "income_sources": "주요 소득원은 무엇인가요?",
    "investment_horizon": "투자 기간은 얼마나 계획하시나요? (일 단위 숫자)",
    "expected_return": "기대 수익 금액은 어느 정도인가요? (원)",
    "expected_loss": "허용 가능한 예상 손실 금액은 어느 정도인가요? (원)",
    "investment_purpose": "투자 목적을 알려주세요.",
    "asset_allocation_type": "자산 배분 유형(0~4)을 선택해주세요. (0:<10%, 1:10~20%, 2:20~30%, 3:30~40%, 4:40%+)",
    "value_growth": "가치/성장 중 어느 성향에 더 가깝나요? (0:가치, 1:성장)",
    "risk_acceptance_level": "위험 수용 수준(1~4)을 선택해주세요.",
    "investment_concern": "투자 관련 어떤 고민이 있으신가요?",
}

# 트리거/세션 키 → DB User 필드 매핑
FIELD_TO_DB = {
    'age': 'age',
    'monthly_income': 'income',
    'risk_tolerance': 'risk_tolerance',
    'income_stability': 'income_stability',
    'income_sources': 'income_source',
    'investment_horizon': 'period',
    'expected_return': 'expected_income',
    'expected_loss': 'expected_loss',
    'investment_purpose': 'purpose',
    'asset_allocation_type': 'asset_allocation_type',
    'value_growth': 'value_growth',
    'risk_acceptance_level': 'risk_acceptance_level',
    'investment_concern': 'investment_concern',
}


