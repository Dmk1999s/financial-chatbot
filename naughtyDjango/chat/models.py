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
    username     = models.CharField(max_length=100, db_index=True)
    product_type = models.CharField(max_length=20, choices=PRODUCT_CHOICES, null=True, blank=True)
    role         = models.CharField(max_length=10, choices=ROLE_CHOICES, db_index=True)
    message      = models.TextField()
    timestamp    = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['session_id', 'timestamp']),
            models.Index(fields=['username', 'timestamp']),
        ]

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] ({self.product_type}) {self.role}: {self.message[:30]}"


