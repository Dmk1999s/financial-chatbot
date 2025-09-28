from rest_framework import serializers

class ChatRequestSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    session_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    message = serializers.CharField(required=True)

class InvestmentProfileSerializer(serializers.Serializer):
    risk_tolerance = serializers.CharField()
    age = serializers.IntegerField()
    income_stability = serializers.CharField()
    income_sources = serializers.CharField()
    monthly_income = serializers.FloatField()
    investment_horizon = serializers.CharField()
    expected_return = serializers.CharField()
    expected_loss = serializers.CharField()
    investment_purpose = serializers.CharField()

class SaveInvestmentProfileRequestSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    user_id = serializers.CharField()
    investment_profile = InvestmentProfileSerializer()

class RecommendProductRequestSerializer(serializers.Serializer):
    message = serializers.CharField()