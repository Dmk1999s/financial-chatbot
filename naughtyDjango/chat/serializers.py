from rest_framework import serializers

class ChatRequestSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    session_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    message = serializers.CharField(required=True)