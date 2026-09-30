from django.db.models import Q
from django.utils import timezone
from courses.models import Topic
from .models import Exam


def next_exam(owner, topic):
    return (
        Exam.objects.filter(owner=owner, course=topic.course, confirmed=True, starts_at__gt=timezone.now())
        .filter(Q(all_topics=True) | Q(topics=topic))
        .order_by("starts_at")
        .first()
    )


def topic_deadlines(owner, now):
    deadlines = {}
    courses = {}
    for topic in Topic.objects.filter(owner=owner):
        courses.setdefault(topic.course_id, []).append(topic.pk)
    for exam in (
        Exam.objects.filter(owner=owner, confirmed=True, starts_at__gt=now)
        .prefetch_related("topics")
        .order_by("starts_at")
    ):
        ids = (
            courses.get(exam.course_id, [])
            if exam.all_topics
            else [t.pk for t in exam.topics.all() if t.owner_id == owner.pk and t.course_id == exam.course_id]
        )
        for topic_id in ids:
            deadlines.setdefault(topic_id, exam.starts_at)
    return deadlines
