from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver
from django.db import transaction
from documents.models import Document
from exports.models import ExportJob
from quizzes.models import Attempt


@receiver(post_delete, sender=Attempt)
def remove_deleted_evidence(sender, instance, **kwargs):
    from mastery.services import recompute

    owner_id = instance.owner_id
    transaction.on_commit(lambda: recompute(owner_id))


@receiver(post_delete, sender=Document)
@receiver(post_delete, sender=ExportJob)
def remove_private_file(sender, instance, **kwargs):
    if instance.file:
        storage, name = instance.file.storage, instance.file.name
        transaction.on_commit(lambda: storage.delete(name))


@receiver(pre_delete)
def invalidate_bundles(sender, instance, **kwargs):
    if sender._meta.app_label in (
        "accounts",
        "courses",
        "documents",
        "tutoring",
        "quizzes",
        "mastery",
        "exams",
        "planning",
        "feedback",
    ):
        owner_id = getattr(instance, "owner_id", None)
        if owner_id:
            ExportJob.objects.filter(owner_id=owner_id).delete()


@receiver(pre_delete, sender=Document)
def purge_cited_derivatives(sender, instance, **kwargs):
    # Conservative course-wide invalidation avoids retaining copied excerpts from deleted files.
    from tutoring.models import ChatSession
    from quizzes.models import Quiz
    from mastery.models import TopicMastery

    ChatSession.objects.filter(owner=instance.owner, course=instance.course).delete()
    Quiz.objects.filter(owner=instance.owner, course=instance.course).delete()
    TopicMastery.objects.filter(owner=instance.owner, topic__course=instance.course).delete()
