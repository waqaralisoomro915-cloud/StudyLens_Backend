from io import BytesIO
import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from documents.models import Document, DocumentPage
from tests.test_workflow import pdf_upload


@pytest.mark.parametrize(
    "kind,extension,mime",
    [
        ("PNG", ".png", "image/png"),
        ("JPEG", ".jpg", "image/jpeg"),
        ("WEBP", ".webp", "image/webp"),
        ("PDF", ".pdf", "application/pdf"),
    ],
)
def test_original_download_uses_actual_type(client, student, course, kind, extension, mime):
    if kind == "PDF":
        upload = pdf_upload()
    else:
        stream = BytesIO()
        Image.new("RGB", (10, 10), "white").save(stream, format=kind)
        upload = SimpleUploadedFile("upload", stream.getvalue())
    expected = upload.read()
    upload.seek(0)
    document = Document.objects.create(owner=student, course=course, title="Lecture notes.txt", file=upload)
    response = client.get(f"/api/documents/{document.pk}/download/")
    assert response.status_code == 200
    assert response["Content-Type"] == mime
    assert f'filename="Lecture notes{extension}"' in response["Content-Disposition"]
    assert b"".join(response.streaming_content) == expected
    response.close()


def test_extracted_download_current_text_order_and_ownership(client, student, course):
    document = Document.objects.create(
        owner=student, course=course, title="Notes.pdf", file=pdf_upload(), status="review"
    )
    DocumentPage.objects.create(document=document, number=2, text="Second page")
    page = DocumentPage.objects.create(document=document, number=1, text="Old OCR")
    assert (
        client.post(
            f"/api/documents/{document.pk}/review/", {"page": page.pk, "text": "Corrected café — notes"}, format="json"
        ).status_code
        == 200
    )
    response = client.get(f"/api/documents/{document.pk}/extracted-text/")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    assert 'filename="Notes-extracted.txt"' in response["Content-Disposition"]
    text = b"".join(response.streaming_content).decode("utf-8-sig")
    assert text == "--- Page 1 ---\r\nCorrected café — notes\r\n\r\n--- Page 2 ---\r\nSecond page"
    response.close()
    client.force_authenticate(User.objects.create_user("outsider"))
    for action in ("download", "extracted-text"):
        assert client.get(f"/api/documents/{document.pk}/{action}/").status_code == 404


def test_unprocessed_and_empty_text_download_rejected(client, student, course):
    document = Document.objects.create(owner=student, course=course, title="Notes", file=pdf_upload())
    assert client.get(f"/api/documents/{document.pk}/extracted-text/").status_code == 400
    document.status = "review"
    document.save()
    DocumentPage.objects.create(document=document, number=1, text="  ")
    assert client.get(f"/api/documents/{document.pk}/extracted-text/").status_code == 400
