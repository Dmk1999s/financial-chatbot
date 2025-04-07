from django.db import models

# Create your models here.

class ChatMessage(models.Model):
    username = models.CharField(max_length=100)  # 사용자 식별
    role = models.CharField(max_length=10)       # user or assistant
    message = models.TextField()                 # 메시지 내용
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.timestamp}] {self.username} ({self.role}): {self.message}"


class InvestmentProfile(models.Model):
    session_id = models.CharField(max_length=255)
    user_id = models.CharField(max_length=255)
    risk_tolerance = models.CharField(max_length=50, null=True, blank=True)
    age = models.IntegerField(null=True, blank=True)
    income_stability = models.CharField(max_length=50, null=True, blank=True)
    income_sources = models.CharField(max_length=255, null=True, blank=True)
    monthly_income = models.IntegerField(null=True, blank=True)  # 한 달 수입 (정수)
    investment_horizon = models.CharField(max_length=50, null=True, blank=True)
    expected_return = models.CharField(max_length=50, null=True, blank=True)
    expected_loss = models.CharField(max_length=50, null=True, blank=True)
    investment_purpose = models.CharField(max_length=255, null=True, blank=True)
    asset_allocation_type = models.IntegerField(null=True, blank=True)
    value_growth = models.IntegerField(null=True, blank=True)
    risk_acceptance_level = models.IntegerField(null=True, blank=True)
    investment_concern = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_id}'s Investment Profile (Session: {self.session_id})"
