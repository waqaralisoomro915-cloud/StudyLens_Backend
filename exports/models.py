from django.db import models
from django.conf import settings
from common.models import OwnedModel
import uuid


def export_path(instance, name):
    return f"exports/{instance.owner_id}/{uuid.uuid4().hex}"


class ExportJob(OwnedModel):
    kind = models.CharField(max_length=10, choices=[("data", "All data"), ("pdf", "Plan PDF"), ("ics", "Calendar")])
    plan = models.ForeignKey("planning.Plan", null=True, blank=True, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default="queued")
    error = models.TextField(blank=True)
    file = models.FileField(upload_to=export_path, blank=True)
