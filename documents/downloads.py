import re
from io import BytesIO
from django.http import FileResponse
from rest_framework.exceptions import ValidationError


def download_name(title, extension):
    # Titles are editable and need not contain the original file extension.
    stem = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", title).strip(" .") or "material"
    stem = re.sub(r"\.(pdf|png|jpe?g|webp|txt)$", "", stem, flags=re.I)
    return stem[:150] + extension


def original_download(document):
    stream = document.file.open("rb")
    try:
        header = stream.read(12)
        stream.seek(0)
        if header.startswith(b"%PDF-"):
            extension, mime = ".pdf", "application/pdf"
        elif header.startswith(b"\x89PNG\r\n\x1a\n"):
            extension, mime = ".png", "image/png"
        elif header.startswith(b"\xff\xd8\xff"):
            extension, mime = ".jpg", "image/jpeg"
        elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            extension, mime = ".webp", "image/webp"
        else:
            extension, mime = ".bin", "application/octet-stream"
        return FileResponse(
            stream, as_attachment=True, filename=download_name(document.title, extension), content_type=mime
        )
    except Exception:
        stream.close()
        raise


def text_download(document):
    if document.status not in ("review", "ready"):
        raise ValidationError("Finish processing the material before downloading extracted text.")
    pages = list(document.pages.order_by("number"))
    if not any(page.text.strip() for page in pages):
        raise ValidationError("No readable text has been extracted. Review or reprocess the material first.")
    content = "\r\n\r\n".join(f"--- Page {page.number} ---\r\n{page.text}" for page in pages)
    # A BOM makes Unicode text recognizable to Windows text editors.
    return FileResponse(
        BytesIO(content.encode("utf-8-sig")),
        as_attachment=True,
        filename=download_name(document.title, "-extracted.txt"),
        content_type="text/plain; charset=utf-8",
    )
