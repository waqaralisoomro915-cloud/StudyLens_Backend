from django.db import models
from django.conf import settings
from common.models import OwnedModel


class Course(OwnedModel):
    title = models.CharField(max_length=200)
    code = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)


class Topic(OwnedModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="topics")
    title = models.CharField(max_length=200)
    unit = models.CharField(max_length=200, blank=True)
    estimated_minutes = models.PositiveIntegerField(default=90)
    difficulty = models.PositiveSmallIntegerField(default=3)
    estimate_override = models.BooleanField(default=False)
