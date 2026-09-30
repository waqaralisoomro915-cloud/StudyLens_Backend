from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from accounts.models import Profile
from planning.models import PlannedSession
from exams.models import Exam
from .models import Notification
from .services import notify


@shared_task
def reminders():
    now = timezone.now()
    for profile in Profile.objects.filter(reminders_enabled=True):
        for s in PlannedSession.objects.filter(
            owner=profile.user, plan__status="accepted", status="pending", starts_at__lt=now + timedelta(hours=1)
        ):
            if s.ends_at < now:
                key = f"missed:{s.pk}"
                if not Notification.objects.filter(owner=profile.user, key=key).exists():
                    from planning.services import propose_if_needed

                    propose_if_needed(profile.user, "Missed study session")
                    notify(profile.user_id, key, f"Overdue: {s.topic.title}. Review your proposed updated plan.")
            else:
                notify(profile.user_id, f"session:{s.pk}", f"Upcoming study session: {s.topic.title}")
        for exam in Exam.objects.filter(
            owner=profile.user, confirmed=True, starts_at__range=(now, now + timedelta(days=1))
        ):
            notify(profile.user_id, f"exam:{exam.pk}:{exam.starts_at.isoformat()}", f"Upcoming exam: {exam.title}")
    from exports.models import ExportJob

    ExportJob.objects.filter(created_at__lt=now - timedelta(days=1)).delete()
