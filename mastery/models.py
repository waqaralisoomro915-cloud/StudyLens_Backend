from django.db import models
from django.conf import settings
from common.models import OwnedModel


class TopicMastery(OwnedModel):
    topic = models.OneToOneField("courses.Topic", on_delete=models.CASCADE)
    correct = models.PositiveIntegerField(default=0)
    answered = models.PositiveIntegerField(default=0)
