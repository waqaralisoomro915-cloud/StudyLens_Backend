from django.db import models
from django.conf import settings
from common.models import OwnedModel


class Plan(OwnedModel):
    status = models.CharField(max_length=20, default="draft")
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.TextField(default="Initial plan")
    unscheduled = models.JSONField(default=list)
    conflicts = models.JSONField(default=list)


class PlannedSession(OwnedModel):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="sessions")
    topic = models.ForeignKey("courses.Topic", on_delete=models.CASCADE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    kind = models.CharField(max_length=20, default="learn")
    status = models.CharField(max_length=20, default="pending")
    locked = models.BooleanField(default=False)
    actual_minutes = models.PositiveIntegerField(default=0)
