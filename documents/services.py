import io
import re
import fitz
from PIL import Image
from django.db import transaction
from rest_framework.exceptions import ValidationError
from .models import DocumentPage, TopicMapping


def validate_upload(file):
    if not file or file.size > 25 * 1024 * 1024 or file.size == 0:
        raise ValidationError({"file": "Upload a nonempty PDF, PNG, JPEG or WebP up to 25 MB."})
    head = file.read(16)
    file.seek(0)
    try:
        if head.startswith(b"%PDF-"):
            pdf = fitz.open(stream=file.read(), filetype="pdf")
            if pdf.is_encrypted or not 1 <= len(pdf) <= 100:
                raise ValueError("PDF must be unlocked and contain 1–100 pages.")
            pdf.close()
        else:
            image = Image.open(file)
            if image.format not in ("PNG", "JPEG", "WEBP") or image.width * image.height > 25_000_000:
                raise ValueError("Unsupported image or image exceeds 25 megapixels.")
            image.verify()
    except Exception as e:
        raise ValidationError({"file": f"Invalid upload: {e}"})
    finally:
        file.seek(0)
    return file


def ocr(image):
    import pytesseract

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, timeout=60)
    words = [(text, float(conf)) for text, conf in zip(data["text"], data["conf"]) if text.strip() and float(conf) >= 0]
    text = " ".join(w[0] for w in words)
    confidence = sum(w[1] for w in words) / max(len(words), 1) / 100
    return text, confidence


def extract(file, page_numbers=None):
    raw = file.read()
    pages = []
    if raw.startswith(b"%PDF-"):
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            for i, page in enumerate(pdf):
                if page_numbers and i + 1 not in page_numbers:
                    continue
                text = page.get_text().strip()
                confidence = 1.0
                if len(text) < 40:
                    if page.rect.width * page.rect.height * 4 > 25_000_000:
                        raise ValueError("Page dimensions exceed the OCR rasterization limit.")
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    if pix.width * pix.height > 25_000_000:
                        raise ValueError("Rendered page exceeds OCR size limit.")
                    text, confidence = ocr(Image.open(io.BytesIO(pix.tobytes("png"))))
                pages.append((i + 1, text, confidence))
    else:
        text, confidence = ocr(Image.open(io.BytesIO(raw)))
        pages.append((1, text, confidence))
    return pages


def remap(course):
    with transaction.atomic():
        TopicMapping.objects.filter(topic__course=course, confirmed=False).delete()
        pages = DocumentPage.objects.filter(
            document__course=course, document__confirmed=True, document__kind="material"
        )
        for topic in course.topics.all():
            terms = set(re.findall(r"\w{3,}", topic.title.lower()))
            for page in pages:
                found = terms & set(re.findall(r"\w{3,}", page.text.lower()))
                score = len(found) / max(len(terms), 1)
                if score >= 0.3:
                    TopicMapping.objects.get_or_create(
                        owner=course.owner,
                        topic=topic,
                        page=page,
                        defaults={
                            "score": score,
                            "reason": f"Title keyword overlap: {', '.join(sorted(found))}. Review this suggested match.",
                        },
                    )
            from courses.services.workload import estimate

            estimate(topic)


def invalidate(document):
    if document.confirmed:
        from tutoring.models import ChatSession
        from quizzes.models import Quiz
        from mastery.models import TopicMastery

        ChatSession.objects.filter(owner=document.owner, course=document.course).delete()
        Quiz.objects.filter(owner=document.owner, course=document.course).delete()
        TopicMastery.objects.filter(owner=document.owner, topic__course=document.course).delete()
    document.confirmed = False
    document.save(update_fields=["confirmed"])
    TopicMapping.objects.filter(page__document=document).delete()
