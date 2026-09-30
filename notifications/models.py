from django.db import models
from django.conf import settings
from common.models import OwnedModel


class Notification(OwnedModel):
    text = models.CharField(max_length=500)
    read = models.BooleanField(default=False)
    key = models.CharField(max_length=150)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "key"], name="unique_notification_key")]
