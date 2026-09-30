from django.db import models
from django.conf import settings
from common.models import OwnedModel


class Feedback(OwnedModel):
    category = models.CharField(max_length=30)
    description = models.TextField()
    reference = models.CharField(max_length=200, blank=True)
    response = models.TextField(blank=True)
    resolved = models.BooleanField(default=False)
