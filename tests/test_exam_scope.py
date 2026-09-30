from datetime import timedelta
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from courses.models import Course, Topic
from exams.models import Exam
from exams.services import next_exam, topic_deadlines
from planning.services import generate_plan, accept


def test_topic_deadlines_and_legacy_whole_course(student, course, topic):
    other = Topic.objects.create(owner=student, course=course, title="Transactions")
    now = timezone.now()
    early = Exam.objects.create(
        owner=student,
        course=course,
        title="Midterm",
        starts_at=now + timedelta(days=3),
        confirmed=True,
        all_topics=False,
    )
    early.topics.add(topic)
    final = Exam.objects.create(
        owner=student, course=course, title="Final", starts_at=now + timedelta(days=10), confirmed=True
    )
    assert topic_deadlines(student, now) == {topic.pk: early.starts_at, other.pk: final.starts_at}
    assert next_exam(student, topic) == early
    assert next_exam(student, other) == final
    early.topics.clear()
    assert next_exam(student, topic) == final


def test_scope_validation_and_ownership(client, student, course, topic):
    other_course = Course.objects.create(owner=student, title="Physics")
    wrong = Topic.objects.create(owner=student, course=other_course, title="Motion")
    stranger = User.objects.create_user("stranger")
    private = Topic.objects.create(owner=stranger, course=other_course, title="Private")
    payload = {"course": course.pk, "title": "Midterm", "all_topics": False}
    for ids in ([], [wrong.pk], [private.pk]):
        assert client.post("/api/exams/", {**payload, "topics": ids}, format="json").status_code == 400
    response = client.post("/api/exams/", {**payload, "topics": [topic.pk]}, format="json")
    assert response.status_code == 201
    assert response.data["topics"] == [topic.pk]
    assert (
        client.patch(f"/api/exams/{response.data['id']}/", {"course": other_course.pk}, format="json").status_code
        == 400
    )


def test_scope_changes_reject_stale_plan_and_preserve_locked_conflict(client, student, course, topic):
    exam = Exam.objects.create(
        owner=student, course=course, title="Exam", starts_at=timezone.now() + timedelta(days=10), confirmed=True
    )
    plan = generate_plan(student)
    assert plan.sessions.exists()
    accept(plan)
    locked = plan.sessions.first()
    locked.locked = True
    locked.save()
    stale = generate_plan(student)
    other = Topic.objects.create(owner=student, course=course, title="Other")
    response = client.patch(f"/api/exams/{exam.pk}/", {"all_topics": False, "topics": [other.pk]}, format="json")
    assert response.status_code == 200 and not response.data["confirmed"]
    assert client.post(f"/api/exams/{exam.pk}/confirm/").status_code == 200
    with pytest.raises(ValidationError):
        accept(stale)
    revision = generate_plan(student)
    assert revision.conflicts
    assert revision.sessions.filter(topic=topic, locked=True).exists()
    assert any(row["topic"] == topic.pk for row in revision.unscheduled)
    # A selected exam with its last topic deleted never expands to the whole course.
    other.delete()
    assert topic.pk not in topic_deadlines(student, timezone.now())
    assert client.post(f"/api/exams/{exam.pk}/confirm/").status_code == 400


def test_upload_suggestions_are_private_and_explained(client, course):
    stranger = User.objects.create_user("stranger")
    Course.objects.create(owner=stranger, title="Database Systems", code="CS402")
    response = client.post("/api/courses/suggest/", {"text": "CS402_database-notes.pdf"}, format="json")
    assert response.status_code == 200
    assert response.data == [{"course": course.pk, "title": course.title, "evidence": ["cs402", "database"]}]
    assert client.post("/api/courses/suggest/", {"text": "unrelated"}, format="json").data == []
    assert client.post("/api/courses/suggest/", {"text": "x" * 2001}, format="json").status_code == 400


def test_selected_exam_excludes_other_topics_and_reschedule_rechecks_scope(client, student, course, topic):
    other = Topic.objects.create(owner=student, course=course, title="Transactions")
    exam = Exam.objects.create(
        owner=student,
        course=course,
        title="Midterm",
        starts_at=timezone.now() + timedelta(days=10),
        confirmed=True,
        all_topics=False,
    )
    exam.topics.add(topic)
    plan = generate_plan(student)
    assert plan.sessions.filter(topic=topic).exists()
    assert not plan.sessions.filter(topic=other).exists()
    assert any(row["topic"] == other.pk for row in plan.unscheduled)
    accept(plan)
    session = plan.sessions.first()
    exam.topics.set([other])
    response = client.post(
        f"/api/sessions/{session.pk}/reschedule/", {"starts_at": session.starts_at.isoformat()}, format="json"
    )
    assert response.status_code == 400
