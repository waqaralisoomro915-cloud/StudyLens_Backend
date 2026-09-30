from django.db import models
from django.conf import settings
from common.models import OwnedModel


class ChatSession(OwnedModel):
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE)
    mode = models.CharField(
        max_length=20,
        choices=[("material", "Ask My Material"), ("tutor", "Tutor Me"), ("guidance", "Study and Career Guidance")],
        default="material",
    )
    title = models.CharField(max_length=200, default="New conversation")


class ChatMessage(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20)
    text = models.TextField()
    citations = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
