from django.db import models
from django.conf import settings
from common.models import OwnedModel


class Quiz(OwnedModel):
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE)
    topic = models.ForeignKey("courses.Topic", null=True, blank=True, on_delete=models.CASCADE)
    title = models.CharField(max_length=200, default="Practice quiz")
    difficulty = models.CharField(max_length=20, default="medium")
    length = models.PositiveSmallIntegerField(default=5)
    status = models.CharField(max_length=20, default="queued")
    error = models.TextField(blank=True)
    questions = models.JSONField(default=list)


class Attempt(OwnedModel):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    answers = models.JSONField()
    correct = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    results = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "quiz"], name="one_scored_attempt_per_quiz")]
