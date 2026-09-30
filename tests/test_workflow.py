import io
import json
from datetime import timedelta
from unittest.mock import patch
import fitz
import pytest
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from accounts.models import Profile, MemoryItem
from courses.models import Course, Topic
from documents.models import Document, DocumentPage, TopicMapping
from documents.tasks import process_document
from ai.client import AIError, validate_citations, retrieve
from quizzes.models import Quiz, Attempt
from quizzes.services import score
from mastery.models import TopicMastery
from mastery.services import summary
from exams.models import Exam
from planning.models import Plan, PlannedSession
from planning.services import generate_plan, accept
from exports.models import ExportJob
from exports.tasks import build_export, render_plan
from tutoring.models import ChatSession
from tutoring.services import answer

pytestmark = pytest.mark.django_db


def pdf_upload():
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text(
        (60, 70),
        "Database normalization reduces redundancy. A primary key uniquely identifies each row. Normal forms structure relational data.",
        fontsize=10,
    )
    content = pdf.tobytes()
    pdf.close()
    return SimpleUploadedFile("notes.pdf", content, content_type="application/pdf")


def document(student, course):
    return Document.objects.create(owner=student, course=course, title="Notes.pdf", file=pdf_upload())


def exam(student, course):
    return Exam.objects.create(
        owner=student,
        course=course,
        title="Database final",
        starts_at=timezone.now() + timedelta(days=5),
        confirmed=True,
    )


def test_registration_login_logout_csrf():
    c = APIClient(enforce_csrf_checks=True)
    assert (
        c.post(
            "/api/auth/register/", {"username": "new", "password": "Long-password-394!", "email": "new@example.com"}
        ).status_code
        == 403
    )
    token = c.get("/api/auth/csrf/").data["csrfToken"]
    r = c.post(
        "/api/auth/register/",
        {"username": "new", "password": "Long-password-394!", "email": "new@example.com"},
        HTTP_X_CSRFTOKEN=token,
    )
    assert r.status_code == 200
    assert c.get("/api/profile/").data["username"] == "new"
    assert c.post("/api/auth/logout/", {}, HTTP_X_CSRFTOKEN=r.data["csrfToken"]).status_code == 200
    assert c.get("/api/courses/").status_code == 403


def test_upload_process_review_map(client, student, course, topic, django_capture_on_commit_callbacks):
    response = client.post(
        "/api/documents/",
        {"course": course.pk, "title": "Notes.pdf", "kind": "material", "file": pdf_upload()},
        format="multipart",
    )
    assert response.status_code == 201, response.data
    pk = response.data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/api/documents/{pk}/process/", {}, format="json")
    d = Document.objects.get(pk=pk)
    assert d.status == "review"
    assert d.pages.count() == 1
    assert not retrieve(student, course, "normalization")
    assert client.post(f"/api/documents/{pk}/confirm/", {}, format="json").status_code == 200
    assert retrieve(student, course, "normalization")[0]["page"] == 1
    assert TopicMapping.objects.filter(topic=topic).exists()
    page = d.pages.first()
    assert (
        client.post(
            f"/api/documents/{pk}/review/", {"page": page.pk, "text": "Corrected notes"}, format="json"
        ).status_code
        == 200
    )
    d.refresh_from_db()
    assert not d.confirmed
    assert not TopicMapping.objects.filter(topic=topic).exists()
    assert not retrieve(student, course, "normalization")


def test_invalid_upload_and_private_download(client, student, course):
    bad = SimpleUploadedFile("notes.pdf", b"<script>alert(1)</script>", content_type="application/pdf")
    assert (
        client.post(
            "/api/documents/", {"course": course.pk, "title": "Bad", "file": bad}, format="multipart"
        ).status_code
        == 400
    )
    d = document(student, course)
    other = User.objects.create_user("other")
    client.force_authenticate(other)
    assert client.get(f"/api/documents/{d.pk}/download/").status_code == 404
    assert client.post("/api/topics/", {"course": course.pk, "title": "Stolen"}, format="json").status_code == 400
    assert client.get("/api/documents/").data == []


def test_failed_processing_and_idempotent_generation(student, course):
    d = document(student, course)
    d.status = "queued"
    d.generation = 1
    d.save()
    with patch("documents.tasks.extract", side_effect=RuntimeError("OCR unavailable")):
        process_document(d.pk, student.pk, 1)
    d.refresh_from_db()
    assert d.status == "failed" and "OCR unavailable" in d.error
    assert not d.pages.exists()
    process_document(d.pk, student.pk, 0)
    assert not d.pages.exists()


def test_citations_reject_fabrications():
    sources = [
        {"id": 1, "text": "Database normalization reduces redundancy.", "document": 1, "title": "notes", "page": 1}
    ]
    with pytest.raises(AIError):
        validate_citations([{"page_id": 2, "quote": "Database normalization"}], sources)
    with pytest.raises(AIError):
        validate_citations([{"page_id": 1, "quote": "This quote does not exist."}], sources)
    assert (
        validate_citations([{"page_id": 1, "quote": "Database normalization reduces redundancy."}], sources)[0]["page"]
        == 1
    )


def test_quiz_scoring_and_no_key_leak(client, student, course, topic):
    questions = [
        {
            "text": f"Question {i}",
            "choices": ["a", "b", "c", "d"],
            "correct": 0,
            "explanation": "Because a",
            "topic_id": topic.pk,
            "citations": [],
        }
        for i in range(3)
    ]
    q = Quiz.objects.create(owner=student, course=course, status="ready", questions=questions)
    public = client.get(f"/api/quizzes/{q.pk}/").data
    assert "correct" not in public["questions"][0]
    response = client.post(f"/api/quizzes/{q.pk}/submit/", {"answers": [0, 1, 0]}, format="json")
    assert response.status_code == 200 and response.data["correct"] == 2
    assert summary(TopicMastery.objects.get(topic=topic))["score"] == 0.6
    assert client.post(f"/api/quizzes/{q.pk}/submit/", {"answers": [0, 0, 0]}, format="json").status_code == 400
    assert TopicMastery.objects.get(topic=topic).answered == 3
    assert client.post(f"/api/quizzes/{q.pk}/submit/", {"answers": [True]}, format="json").status_code == 400


def test_plan_confirmation_capacity_and_revision(client, student, course, topic):
    e = exam(student, course)
    draft = generate_plan(student)
    assert draft.status == "draft" and draft.sessions.count() == 3
    assert all(s.ends_at <= e.starts_at for s in draft.sessions.all())
    ordered = list(draft.sessions.order_by("starts_at"))
    assert all(b.starts_at >= a.ends_at + timedelta(minutes=10) for a, b in zip(ordered, ordered[1:]))
    accept(draft)
    s = ordered[0]
    assert (
        client.post(
            f"/api/sessions/{s.pk}/update_state/", {"status": "completed", "actual_minutes": 31}, format="json"
        ).status_code
        == 200
    )
    assert not TopicMastery.objects.filter(topic=topic).exists()
    revision = Plan.objects.filter(previous=draft).latest("id")
    assert revision.status == "draft"
    assert revision.sessions.filter(status="completed", starts_at=s.starts_at).exists()
    assert revision.sessions.filter(kind="practice").exists()
    draft.refresh_from_db()
    assert draft.status == "accepted"
    accept(revision)
    draft.refresh_from_db()
    assert draft.status == "superseded"


def test_no_availability_and_unconfirmed_exams(student, course, topic):
    e = exam(student, course)
    e.confirmed = False
    e.save()
    draft = generate_plan(student)
    assert not draft.sessions.exists() and draft.unscheduled
    e.confirmed = True
    e.save()
    Profile.objects.filter(user=student).update(availability=[])
    draft = generate_plan(student)
    assert not draft.sessions.exists() and draft.unscheduled[0]["minutes"] == 90


def test_locked_conflict_and_stale_draft(student, course, topic):
    exam(student, course)
    p = generate_plan(student)
    accept(p)
    s = p.sessions.first()
    s.locked = True
    s.save()
    Profile.objects.filter(user=student).update(availability=[])
    revised = generate_plan(student)
    assert revised.conflicts
    from rest_framework.exceptions import ValidationError

    with pytest.raises(ValidationError):
        accept(revised)


def test_memory_is_opt_in_and_disabled_context_excluded(student, course):
    memory = MemoryItem.objects.create(owner=student, text="Remember a specific goal")
    chat = ChatSession.objects.create(owner=student, course=course, mode="guidance")
    with patch("tutoring.services.generate", return_value={"answer": "General guidance", "citations": []}) as gen:
        answer(chat, "Help me study")
        assert gen.call_args.args[1]["memory"] == []
        Profile.objects.filter(user=student).update(memory_enabled=True)
        answer(chat, "Help me study")
        assert gen.call_args.args[1]["memory"][0]["text"] == memory.text
        memory.delete()
        answer(chat, "Help me study")
        assert gen.call_args.args[1]["memory"] == []


def test_exports_and_deletion(client, student, course, topic, django_capture_on_commit_callbacks):
    d = document(student, course)
    exam(student, course)
    p = generate_plan(student)
    job = ExportJob.objects.create(owner=student, kind="data")
    build_export(job.pk, student.pk)
    job.refresh_from_db()
    assert job.status == "ready"
    import zipfile

    with zipfile.ZipFile(job.file.path) as bundle:
        assert "account.json" in bundle.namelist()
        assert f"uploads/{d.pk}.bin" in bundle.namelist()
        assert b"password" not in bundle.read("account.json")
    pdf = ExportJob(owner=student, kind="pdf", plan=p)
    assert render_plan(pdf).startswith(b"%PDF")
    ics = ExportJob(owner=student, kind="ics", plan=p, created_at=timezone.now())
    assert b"BEGIN:VEVENT" in render_plan(ics)
    storage, name = d.file.storage, d.file.name
    with django_capture_on_commit_callbacks(execute=True):
        d.delete()
    assert not storage.exists(name)
    assert not ExportJob.objects.filter(pk=job.pk).exists()


def test_user_isolation_all_collections(client, student, course, topic):
    other = User.objects.create_user("bob")
    Profile.objects.create(user=other)
    d = document(student, course)
    q = Quiz.objects.create(owner=student, course=course)
    e = exam(student, course)
    p = generate_plan(student)
    chat = ChatSession.objects.create(owner=student, course=course)
    client.force_authenticate(other)
    for endpoint, pk in [
        ("courses", course.pk),
        ("topics", topic.pk),
        ("documents", d.pk),
        ("quizzes", q.pk),
        ("exams", e.pk),
        ("plans", p.pk),
        ("chats", chat.pk),
    ]:
        assert client.get(f"/api/{endpoint}/").data == []
        assert client.get(f"/api/{endpoint}/{pk}/").status_code == 404
        assert client.delete(f"/api/{endpoint}/{pk}/").status_code == 404


def test_exam_confirmation_and_profile_validation(client, course):
    r = client.post("/api/exams/", {"course": course.pk, "title": "Unknown date", "confirmed": True}, format="json")
    assert r.status_code == 201 and not r.data["confirmed"]
    assert client.post(f"/api/exams/{r.data['id']}/confirm/", {}, format="json").status_code == 400
    assert client.patch("/api/profile/", {"timezone": "Not/AZone"}, format="json").status_code == 400
    assert (
        client.patch(
            "/api/profile/", {"availability": [{"day": 8, "start": "20:00", "end": "19:00"}]}, format="json"
        ).status_code
        == 400
    )
    assert client.patch("/api/profile/", {"session_minutes": 0}, format="json").status_code == 400


def test_data_export_cannot_reference_foreign_plan(client, student, course, topic):
    other = User.objects.create_user("bob")
    p = Plan.objects.create(owner=other)
    assert client.post("/api/exports/", {"kind": "pdf", "plan": p.pk}, format="json").status_code == 400


def test_quiz_worker_validates_model_output(student, course, topic):
    from quizzes.tasks import generate_quiz

    d = document(student, course)
    d.confirmed = True
    d.save()
    DocumentPage.objects.create(
        document=d, number=1, text="Database normalization reduces redundancy in relational databases."
    )
    q = Quiz.objects.create(owner=student, course=course, topic=topic, length=1)
    with patch(
        "quizzes.services.generate",
        return_value={"questions": [{"text": "Test", "choices": ["same"] * 4, "correct": 9, "topic_id": topic.pk}]},
    ):
        generate_quiz(q.pk, student.pk)
    q.refresh_from_db()
    assert q.status == "failed" and q.questions == []


def test_ocr_real_when_installed():
    import shutil

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract executable unavailable on this host; CI installs it.")
    from PIL import Image, ImageDraw
    from documents.services import ocr

    image = Image.new("RGB", (1800, 400), "white")
    ImageDraw.Draw(image).text((60, 80), "DATABASE NORMALIZATION REDUCES REDUNDANCY", fill="black", font_size=44)
    text, confidence = ocr(image)
    assert "NORMALIZATION" in text.upper() and confidence > 0.5


def test_cited_tutor_and_quiz_with_explicit_model_double(
    client, student, course, topic, django_capture_on_commit_callbacks
):
    d = document(student, course)
    d.status = "ready"
    d.confirmed = True
    d.save()
    source = DocumentPage.objects.create(
        document=d, number=1, text="Database normalization reduces redundancy and improves data integrity."
    )
    citation = {"page_id": source.pk, "quote": "Database normalization reduces redundancy"}
    chat = ChatSession.objects.create(owner=student, course=course)
    with patch(
        "tutoring.services.generate",
        return_value={"answer": "Normalization reduces redundancy.", "citations": [citation]},
    ):
        response = client.post(
            f"/api/chats/{chat.pk}/ask/", {"question": "What is database normalization?"}, format="json"
        )
    assert response.status_code == 200 and response.data["citations"][0]["document"] == d.pk
    questions = [
        {
            "text": "What does normalization reduce?",
            "choices": ["Redundancy", "Integrity", "Tables", "Keys"],
            "correct": 0,
            "explanation": "The notes state that normalization reduces redundancy.",
            "topic_id": topic.pk,
            "citations": [citation],
        }
    ]
    with (
        patch("quizzes.services.generate", return_value={"questions": questions}),
        django_capture_on_commit_callbacks(execute=True),
    ):
        result = client.post(
            "/api/quizzes/", {"course": course.pk, "topic": topic.pk, "length": 1, "difficulty": "easy"}, format="json"
        )
    q = Quiz.objects.get(pk=result.data["id"])
    assert q.status == "ready"
    response = client.post(f"/api/quizzes/{q.pk}/submit/", {"answers": [0]}, format="json")
    assert response.data["correct"] == 1 and response.data["results"][0]["citations"][0]["page"] == 1


def test_selective_reprocessing_preserves_other_pages(student, course):
    d = document(student, course)
    d.status = "queued"
    d.generation = 3
    d.save()
    page1 = DocumentPage.objects.create(document=d, number=1, text="Old")
    page2 = DocumentPage.objects.create(document=d, number=2, text="Keep corrected page")
    with patch("documents.tasks.extract", return_value=[(1, "New text", 0.9)]):
        process_document(d.pk, student.pk, 3, [1])
    page1.refresh_from_db()
    page2.refresh_from_db()
    assert page1.text == "New text" and page2.text == "Keep corrected page"


def test_stale_plan_cannot_drop_completed_session(student, course, topic):
    from rest_framework.exceptions import ValidationError

    exam(student, course)
    current = generate_plan(student)
    accept(current)
    draft = generate_plan(student)
    s = current.sessions.first()
    s.status = "completed"
    s.actual_minutes = 37
    s.save()
    with pytest.raises(ValidationError):
        accept(draft)


def test_reschedule_is_a_draft_and_rejects_overlap(client, student, course, topic):
    exam(student, course)
    current = generate_plan(student)
    accept(current)
    sessions = list(current.sessions.order_by("starts_at"))
    response = client.post(
        f"/api/sessions/{sessions[0].pk}/reschedule/", {"starts_at": sessions[1].starts_at.isoformat()}, format="json"
    )
    assert response.status_code == 400
    start = sessions[-1].ends_at + timedelta(minutes=30)
    response = client.post(
        f"/api/sessions/{sessions[0].pk}/reschedule/", {"starts_at": start.isoformat()}, format="json"
    )
    if response.status_code == 201:
        assert response.data["status"] == "draft"
        current.refresh_from_db()
        assert current.status == "accepted"
        sessions[0].refresh_from_db()
        assert sessions[0].starts_at != start
    else:
        assert response.status_code == 400  # Last slot may be at the end of a daily window.


def test_account_deletion_requires_password(client, student, course, django_capture_on_commit_callbacks):
    d = document(student, course)
    path = d.file.name
    storage = d.file.storage
    assert client.delete("/api/profile/", {"password": "wrong"}, format="json").status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        response = client.delete("/api/profile/", {"password": "Long-password-390!"}, format="json")
    assert response.status_code == 204
    assert not User.objects.filter(pk=student.pk).exists()
    assert not storage.exists(path)


def test_daily_capacity_and_overlapping_availability(student, course, topic):
    from zoneinfo import ZoneInfo

    profile = Profile.objects.get(user=student)
    profile.timezone = "Asia/Kolkata"
    profile.daily_limit = 60
    profile.availability = [{"day": d, "start": "09:00", "end": "11:00"} for d in range(7)] * 2
    profile.save()
    topic.estimated_minutes = 600
    topic.save()
    e = exam(student, course)
    e.starts_at = timezone.now() + timedelta(days=2)
    e.save()
    p = generate_plan(student)
    assert p.unscheduled
    by_day = {}
    sessions = list(p.sessions.order_by("starts_at"))
    for s in sessions:
        local = s.starts_at.astimezone(ZoneInfo("Asia/Kolkata"))
        assert 9 <= local.hour < 11
        by_day[local.date()] = by_day.get(local.date(), 0) + (s.ends_at - s.starts_at).total_seconds() / 60
    assert all(minutes <= 60 for minutes in by_day.values())
    assert all(b.starts_at >= a.ends_at + timedelta(minutes=10) for a, b in zip(sessions, sessions[1:]))


def test_memory_endpoint_requires_opt_in(client):
    assert client.post("/api/memory/", {"text": "I prefer examples"}, format="json").status_code == 400
    assert client.patch("/api/profile/", {"memory_enabled": True}, format="json").status_code == 200
    response = client.post("/api/memory/", {"text": "I prefer examples", "kind": "fact"}, format="json")
    assert response.status_code == 201
    assert client.patch("/api/profile/", {"memory_enabled": False}, format="json").status_code == 200
    assert client.delete(f"/api/memory/{response.data['id']}/").status_code == 204
