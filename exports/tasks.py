import io
import json
import zipfile
from datetime import timezone as dt_timezone
from celery import shared_task
from django.apps import apps
from django.core.files.base import ContentFile
from django.core.serializers import serialize
from django.db import transaction
from django.contrib.auth.models import User
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from .models import ExportJob
from notifications.services import notify


def ics_escape(text):
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def render_plan(job):
    sessions = job.plan.sessions.select_related("topic").order_by("starts_at")
    if job.kind == "ics":
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//StudyLens//Study plan//EN", "CALSCALE:GREGORIAN"]
        for s in sessions:
            stamp = lambda d: d.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            lines += [
                "BEGIN:VEVENT",
                f"UID:studylens-{s.pk}@local",
                f"DTSTAMP:{stamp(job.created_at)}",
                f"DTSTART:{stamp(s.starts_at)}",
                f"DTEND:{stamp(s.ends_at)}",
                f"SUMMARY:{ics_escape(s.topic.title)}",
                f"DESCRIPTION:{ics_escape(s.kind)}",
                "END:VEVENT",
            ]
        lines += ["END:VCALENDAR"]
        # RFC5545 folding at octet boundaries (UTF-8 codepoints stay intact).
        folded = []
        for line in lines:
            part = ""
            for char in line:
                if len((part + char).encode()) > 73:
                    folded.append(part)
                    part = " " + char
                else:
                    part += char
            folded.append(part)
        return ("\r\n".join(folded) + "\r\n").encode()
    out = io.BytesIO()
    pdf = canvas.Canvas(out)
    pdf.setTitle("StudyLens study plan")
    pdf.setFont("Helvetica", 16)
    pdf.drawString(45, 800, "StudyLens | Study plan (UTC)")
    y = 770
    for s in sessions:
        for line in simpleSplit(
            f"{s.starts_at:%Y-%m-%d %H:%M} - {s.ends_at:%H:%M} | {s.kind} | {s.topic.title}", "Helvetica", 10, 500
        ):
            if y < 45:
                pdf.showPage()
                y = 800
            pdf.setFont("Helvetica", 10)
            pdf.drawString(45, y, line)
            y -= 16
    pdf.save()
    return out.getvalue()


def data_bundle(owner):
    from documents.models import Document, DocumentPage
    from tutoring.models import ChatMessage
    from accounts.models import Profile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("account.json", json.dumps({"username": owner.username, "email": owner.email}))
        for model in apps.get_models():
            if model._meta.app_label in ("auth", "admin", "contenttypes", "sessions", "exports"):
                continue
            fields = {f.name for f in model._meta.fields}
            if "owner" in fields:
                qs = model.objects.filter(owner=owner)
            elif model == Profile:
                qs = model.objects.filter(user=owner)
            elif model == DocumentPage:
                qs = model.objects.filter(document__owner=owner)
            elif model == ChatMessage:
                qs = model.objects.filter(session__owner=owner)
            else:
                continue
            bundle.writestr(f"{model._meta.label_lower}.json", serialize("json", qs))
        for document in Document.objects.filter(owner=owner):
            with document.file.open("rb") as file:
                bundle.writestr(f"uploads/{document.pk}.bin", file.read())
    return out.getvalue()


@shared_task
def build_export(pk, owner_id):
    if not ExportJob.objects.filter(pk=pk, owner_id=owner_id, status="queued").update(status="processing"):
        return
    try:
        with transaction.atomic():
            owner = User.objects.select_for_update().get(pk=owner_id)
            job = ExportJob.objects.select_for_update().get(pk=pk, owner=owner)
            content = data_bundle(owner) if job.kind == "data" else render_plan(job)
            job.file.save("export", ContentFile(content), save=False)
            job.status = "ready"
            job.save()
        notify(owner_id, f"export:{pk}", "Your protected export is ready (expires in 24 hours).")
    except Exception as e:
        ExportJob.objects.filter(pk=pk, owner_id=owner_id).update(status="failed", error=str(e)[:500])
