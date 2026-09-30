from celery import shared_task
from django.db import transaction
from .models import Document, DocumentPage
from .services import extract
from notifications.services import notify


@shared_task(bind=True, max_retries=2)
def process_document(self, document_id, owner_id, generation, page_numbers=None):
    document = Document.objects.filter(
        pk=document_id, owner_id=owner_id, generation=generation, status="queued"
    ).first()
    if not document:
        return
    if not Document.objects.filter(pk=document_id, generation=generation, status="queued").update(status="processing"):
        return
    try:
        with document.file.open("rb") as file:
            pages = extract(file, page_numbers)
        with transaction.atomic():
            document = (
                Document.objects.select_for_update()
                .filter(pk=document_id, owner_id=owner_id, generation=generation)
                .first()
            )
            if not document:
                return
            if not page_numbers:
                document.pages.all().delete()
            for n, text, c in pages:
                DocumentPage.objects.update_or_create(
                    document=document,
                    number=n,
                    defaults={
                        "text": text,
                        "confidence": c,
                        "warning": "Review OCR or unreadable text." if c < 0.8 or len(text) < 40 else "",
                    },
                )
            document.status = "review"
            document.error = ""
            document.save(update_fields=["status", "error"])
        notify(owner_id, f"document:{document_id}:{generation}", f"Extraction ready for review: {document.title}")
    except Exception as exc:
        # Retry temporary storage/IO failures only, with a bounded exponential delay.
        # Missing OCR/model executables and malformed files remain visible failures.
        if isinstance(exc, (TimeoutError, ConnectionError)) and self.request.retries < self.max_retries:
            Document.objects.filter(pk=document_id, generation=generation).update(status="queued")
            raise self.retry(exc=exc, countdown=10 * (2**self.request.retries))
        Document.objects.filter(pk=document_id, generation=generation).update(
            status="failed", error=f"{type(exc).__name__}: {str(exc)[:400]}"
        )


def enqueue(document, page_numbers=None):
    with transaction.atomic():
        document = Document.objects.select_for_update().get(pk=document.pk)
        if document.status in ("queued", "processing"):
            return
        from .services import invalidate

        invalidate(document)
        document.generation += 1
        document.status = "queued"
        document.error = ""
        document.save()
        args = (document.pk, document.owner_id, document.generation, page_numbers)

        def dispatch():
            try:
                process_document.delay(*args)
            except Exception:
                Document.objects.filter(pk=args[0], generation=args[2]).update(
                    status="failed", error="Worker queue unavailable. Start Redis and the worker, then retry."
                )

        transaction.on_commit(dispatch)
