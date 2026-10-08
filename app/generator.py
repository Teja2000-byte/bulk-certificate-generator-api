from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from app.schemas import CertificateDetails, Recipient


def safe_filename(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return (normalized[:80] or "recipient") + ".pdf"


def _fit_font_size(text: str, font_name: str, preferred: int, max_width: float) -> int:
    size = preferred
    while size > 18 and stringWidth(text, font_name, size) > max_width:
        size -= 1
    return size


def generate_certificate(
    recipient: Recipient, details: CertificateDetails, destination: Path
) -> None:
    """Render one certificate to an atomic PDF file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    width, height = landscape(A4)

    canvas = Canvas(str(temporary), pagesize=(width, height))
    canvas.setTitle(f"{details.title} - {recipient.name}")

    canvas.setFillColor(colors.HexColor("#F8F5EC"))
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#17324D"))
    canvas.setLineWidth(8)
    canvas.rect(24, 24, width - 48, height - 48, fill=0, stroke=1)
    canvas.setStrokeColor(colors.HexColor("#C49A45"))
    canvas.setLineWidth(2)
    canvas.rect(38, 38, width - 76, height - 76, fill=0, stroke=1)

    canvas.setFillColor(colors.HexColor("#17324D"))
    canvas.setFont("Helvetica-Bold", 31)
    canvas.drawCentredString(width / 2, height - 115, details.title.upper())
    canvas.setFont("Helvetica", 15)
    canvas.drawCentredString(width / 2, height - 162, "This certificate is proudly presented to")

    name_size = _fit_font_size(recipient.name, "Helvetica-BoldOblique", 36, width - 180)
    canvas.setFillColor(colors.HexColor("#9A6C1E"))
    canvas.setFont("Helvetica-BoldOblique", name_size)
    canvas.drawCentredString(width / 2, height - 225, recipient.name)
    canvas.setStrokeColor(colors.HexColor("#C49A45"))
    canvas.setLineWidth(1)
    canvas.line(140, height - 240, width - 140, height - 240)

    canvas.setFillColor(colors.HexColor("#263849"))
    canvas.setFont("Helvetica", 15)
    canvas.drawCentredString(width / 2, height - 284, "for successfully completing")
    course_size = _fit_font_size(details.course, "Helvetica-Bold", 22, width - 160)
    canvas.setFont("Helvetica-Bold", course_size)
    canvas.drawCentredString(width / 2, height - 326, details.course)

    canvas.setFont("Helvetica", 12)
    canvas.drawString(80, 90, f"Issued: {details.issued_on.isoformat()}")
    canvas.drawRightString(width - 80, 90, details.organization)
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#607080"))
    canvas.drawCentredString(width / 2, 63, f"Recipient: {recipient.email}")
    canvas.showPage()
    canvas.save()
    temporary.replace(destination)

