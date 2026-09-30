from django.db import models
from django.conf import settings
from common.models import OwnedModel
import uuid


def private_path(instance, name):
    return f"uploads/{instance.owner_id}/{uuid.uuid4().hex}"


class Document(OwnedModel):
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=200)
    kind = models.CharField(
        max_length=20,
        choices=[("material", "Material"), ("syllabus", "Syllabus"), ("timetable", "Timetable")],
        default="material",
    )
    file = models.FileField(upload_to=private_path)
    status = models.CharField(max_length=20, default="uploaded")
    error = models.TextField(blank=True)
    confirmed = models.BooleanField(default=False)
    generation = models.PositiveIntegerField(default=0)


class DocumentPage(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    confidence = models.FloatField(default=1)
    warning = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "number"], name="unique_document_page")]
        ordering = ["number"]


class TopicMapping(OwnedModel):
    topic = models.ForeignKey("courses.Topic", on_delete=models.CASCADE)
    page = models.ForeignKey(DocumentPage, on_delete=models.CASCADE)
    score = models.FloatField()
    reason = models.TextField()
    confirmed = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["topic", "page"], name="unique_topic_page")]
