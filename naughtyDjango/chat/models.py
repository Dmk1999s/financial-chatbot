# chat/models.py
from django.db import models

# 금융상품 타입 선택지
PRODUCT_CHOICES = [
    ("stock",   "주식"),
    ("deposit", "예금"),
    ("saving",  "적금"),
    ("annuity", "연금"),
]
# 메시지 발신자 선택지
ROLE_CHOICES = [
    ("user",      "User"),
    ("assistant", "Assistant"),
]

class ChatMessage(models.Model):
    session_id   = models.CharField(max_length=255, db_index=True, null=True, blank=True)
    username     = models.CharField(max_length=100)
    product_type = models.CharField(max_length=20, choices=PRODUCT_CHOICES, null=True, blank=True)
    role         = models.CharField(max_length=10, choices=ROLE_CHOICES)
    message      = models.TextField()
    timestamp    = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] ({self.product_type}) {self.role}: {self.message[:30]}"

class InvestmentProfile(models.Model):
    session_id              = models.CharField(max_length=255)
    user_id                 = models.CharField(max_length=255)
    risk_tolerance          = models.CharField(max_length=50,  null=True, blank=True)
    age                     = models.IntegerField(null=True, blank=True)
    income_stability        = models.CharField(max_length=50,  null=True, blank=True)
    income_sources          = models.CharField(max_length=255, null=True, blank=True)
    monthly_income          = models.IntegerField(null=True, blank=True)
    investment_horizon      = models.CharField(max_length=50,  null=True, blank=True)
    expected_return         = models.CharField(max_length=50,  null=True, blank=True)
    expected_loss           = models.CharField(max_length=50,  null=True, blank=True)
    investment_purpose      = models.CharField(max_length=255, null=True, blank=True)
    asset_allocation_type   = models.IntegerField(null=True, blank=True)
    value_growth            = models.IntegerField(null=True, blank=True)
    risk_acceptance_level   = models.IntegerField(null=True, blank=True)
    investment_concern      = models.CharField(max_length=255, null=True, blank=True)
    created_at              = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_id}'s Investment Profile (Session: {self.session_id})"
