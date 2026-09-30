from django.db import models
from django.conf import settings
from common.models import OwnedModel


class Exam(OwnedModel):
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE)
    all_topics = models.BooleanField(default=True)
    topics = models.ManyToManyField("courses.Topic", blank=True)
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    confirmed = models.BooleanField(default=False)
    source = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    source_quote = models.TextField(blank=True)
    warning = models.TextField(blank=True)
