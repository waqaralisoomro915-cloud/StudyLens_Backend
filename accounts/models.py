from django.db import models
from django.conf import settings
from common.models import OwnedModel


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    institution = models.CharField(max_length=200, blank=True)
    program = models.CharField(max_length=200, blank=True)
    department = models.CharField(max_length=200, blank=True)
    academic_year = models.CharField(max_length=30, blank=True)
    semester = models.CharField(max_length=30, blank=True)
    goals = models.TextField(blank=True)
    language = models.CharField(max_length=50, default="English")
    timezone = models.CharField(max_length=80, default="UTC")
    memory_enabled = models.BooleanField(default=False)
    reminders_enabled = models.BooleanField(default=True)
    daily_limit = models.PositiveIntegerField(default=120)
    session_minutes = models.PositiveIntegerField(default=30)
    break_minutes = models.PositiveIntegerField(default=10)
    availability = models.JSONField(default=list)


class MemoryItem(OwnedModel):
    text = models.TextField()
    kind = models.CharField(
        max_length=20, choices=[("fact", "Student fact"), ("inference", "AI inference")], default="fact"
    )
