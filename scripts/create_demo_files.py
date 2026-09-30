"""Generate development fixtures only; never insert demo data into student accounts."""

from pathlib import Path
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
root.mkdir(parents=True, exist_ok=True)


def pdf(name, title, lines):
    doc = canvas.Canvas(str(root / name))
    doc.setFont("Helvetica-Bold", 18)
    doc.drawString(50, 790, title)
    doc.setFont("Helvetica", 12)
    for i, line in enumerate(lines):
        doc.drawString(50, 745 - i * 25, line)
    doc.save()


pdf(
    "sample_text.pdf",
    "Database Systems — Development Fixture",
    [
        "Database normalization reduces redundancy and improves data integrity.",
        "A primary key uniquely identifies each row in a relation.",
        "First normal form requires atomic attribute values and no repeating groups.",
        "Second normal form removes partial dependencies on a composite candidate key.",
        "Third normal form removes transitive dependencies of non-key attributes.",
        "A transaction groups operations into a logical unit of work.",
        "ACID means atomicity, consistency, isolation and durability.",
        "Atomicity ensures either all transaction operations succeed or none do.",
        "A database index can speed up retrieval at the cost of storage and writes.",
        "Practice: explain how normalization prevents update anomalies.",
    ],
)
pdf(
    "sample_syllabus.pdf",
    "Database Systems — Sample Syllabus",
    [
        "Unit 1: Relational foundations",
        "Topics: Relations, primary keys and relational constraints",
        "Unit 2: Database normalization",
        "Topics: First normal form, second normal form, third normal form",
        "Unit 3: Transactions",
        "Topics: ACID properties, atomicity and isolation",
        "Unit 4: Indexing and query optimization",
    ],
)
pdf(
    "sample_timetable.pdf",
    "Exam Timetable — Development Fixture",
    [
        "Course: Database Systems (CS402)",
        "Date: 15 December 2030",
        "Start: 09:00 UTC",
        "Duration: 120 minutes",
        "This future date is illustrative. Review and confirm before scheduling.",
    ],
)
image = Image.new("RGB", (1800, 900), "white")
draw = ImageDraw.Draw(image)
try:
    font = ImageFont.truetype("arial.ttf", 38)
except OSError:
    font = ImageFont.load_default(size=38)
for i, line in enumerate(
    [
        "DATABASE SYSTEMS - SCANNED SAMPLE",
        "Database normalization reduces redundancy.",
        "A primary key uniquely identifies each row.",
        "Atomicity means all operations succeed or none do.",
    ]
):
    draw.text((70, 90 + i * 130), line, font=font, fill="black")
image.save(root / "sample_scanned.png")
image.save(root / "sample_scanned.pdf", "PDF", resolution=150)
print(f"Created development fixtures in {root}")
