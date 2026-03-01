# utils/pdf_builder.py — Build an ATS-friendly PDF resume using ReportLab

import io
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem,
    Table, TableStyle,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

BRAND_COLOR = colors.HexColor("#4F46E5")
DARK_GRAY = colors.HexColor("#444444")
BLACK = colors.black


def _styles():
    base = getSampleStyleSheet()
    custom = {}

    custom["name"] = ParagraphStyle(
        "name", parent=base["Normal"],
        fontSize=18, fontName="Helvetica-Bold",
        leading=24,
        textColor=BLACK, alignment=TA_CENTER,
        spaceAfter=2,
    )
    custom["contact"] = ParagraphStyle(
        "contact", parent=base["Normal"],
        fontSize=9, fontName="Helvetica",
        textColor=DARK_GRAY, alignment=TA_CENTER,
        spaceAfter=6,
    )
    custom["section"] = ParagraphStyle(
        "section", parent=base["Normal"],
        fontSize=11, fontName="Helvetica-Bold",
        textColor=BRAND_COLOR, alignment=TA_LEFT,
        spaceBefore=5, spaceAfter=1,
    )
    custom["job_title"] = ParagraphStyle(
        "job_title", parent=base["Normal"],
        fontSize=11, fontName="Helvetica-Bold",
        textColor=BLACK, spaceBefore=3, spaceAfter=0,
    )
    custom["meta"] = ParagraphStyle(
        "meta", parent=base["Normal"],
        fontSize=10, fontName="Helvetica-Oblique",
        textColor=DARK_GRAY, spaceAfter=0,
    )
    custom["meta_right"] = ParagraphStyle(
        "meta_right", parent=base["Normal"],
        fontSize=10, fontName="Helvetica-Oblique",
        textColor=DARK_GRAY, spaceAfter=0,
        alignment=TA_CENTER,
    )
    custom["body"] = ParagraphStyle(
        "body", parent=base["Normal"],
        fontSize=10, fontName="Helvetica",
        textColor=BLACK, spaceAfter=2, leading=12,
    )
    custom["bullet"] = ParagraphStyle(
        "bullet", parent=base["Normal"],
        fontSize=10, fontName="Helvetica",
        textColor=BLACK, spaceAfter=0, leading=12,
        leftIndent=12, bulletIndent=0,
    )
    return custom


_LEFT_MARGIN = 0.75 * inch
_RIGHT_MARGIN = 0.75 * inch
_TOP_MARGIN = 0.5 * inch
_BOTTOM_MARGIN = 0.5 * inch
_USABLE_WIDTH = letter[0] - _LEFT_MARGIN - _RIGHT_MARGIN


def _meta_row(left_text: str, dates: str, styles: dict):
    """One-row table that pins company/location left and dates right, no wrapping."""
    if not dates:
        return Paragraph(left_text, styles["meta"])
    left_col = _USABLE_WIDTH * 0.65
    right_col = _USABLE_WIDTH * 0.35
    tbl = Table(
        [[Paragraph(left_text, styles["meta"]), Paragraph(dates, styles["meta_right"])]],
        colWidths=[left_col, right_col],
    )
    tbl.setStyle(TableStyle([
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",    (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 0),
        ("TOPPADDING",     (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 2),
    ]))
    return tbl


def build_pdf(data: dict) -> bytes:
    """Build an ATS-friendly PDF from structured resume data. Returns bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=_LEFT_MARGIN,
        rightMargin=_RIGHT_MARGIN,
        topMargin=_TOP_MARGIN,
        bottomMargin=_BOTTOM_MARGIN,
    )

    S = _styles()
    story = []

    # ── Name ──────────────────────────────────────────────────────────────────
    story.append(Paragraph(data.get("name", ""), S["name"]))

    # ── Contact ───────────────────────────────────────────────────────────────
    contact_parts = [
        data.get("phone", ""),
        data.get("email", ""),
        data.get("location", ""),
        data.get("linkedin", ""),
        data.get("website", ""),
    ]
    contact_line = "  |  ".join(p for p in contact_parts if p)
    if contact_line:
        story.append(Paragraph(contact_line, S["contact"]))

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = data.get("summary", "")
    if summary:
        story.append(Paragraph("PROFESSIONAL SUMMARY", S["section"]))
        story.append(HRFlowable(width="100%", thickness=1, color=BRAND_COLOR, spaceAfter=2))
        story.append(Paragraph(summary, S["body"]))

    # ── Experience ────────────────────────────────────────────────────────────
    experience = data.get("experience", [])
    if experience:
        story.append(Paragraph("EXPERIENCE", S["section"]))
        story.append(HRFlowable(width="100%", thickness=1, color=BRAND_COLOR, spaceAfter=2))
        for job in experience:
            story.append(Paragraph(job.get("title", ""), S["job_title"]))
            company = job.get("company", "")
            location = job.get("location", "")
            dates = job.get("dates", "")
            left = company + (f"  —  {location}" if location else "")
            story.append(_meta_row(left, dates, S))
            for bullet in job.get("bullets", []):
                story.append(Paragraph(f"• {bullet}", S["bullet"]))

    # ── Education ─────────────────────────────────────────────────────────────
    education = data.get("education", [])
    if education:
        story.append(Paragraph("EDUCATION", S["section"]))
        story.append(HRFlowable(width="100%", thickness=1, color=BRAND_COLOR, spaceAfter=2))
        for edu in education:
            story.append(Paragraph(edu.get("degree", ""), S["job_title"]))
            school = edu.get("school", "")
            loc = edu.get("location", "")
            dates = edu.get("dates", "")
            left = school + (f"  —  {loc}" if loc else "")
            story.append(_meta_row(left, dates, S))
            if edu.get("details"):
                story.append(Paragraph(edu["details"], S["body"]))

    # ── Skills ────────────────────────────────────────────────────────────────
    skills = data.get("skills", [])
    if skills:
        story.append(Paragraph("SKILLS", S["section"]))
        story.append(HRFlowable(width="100%", thickness=1, color=BRAND_COLOR, spaceAfter=2))
        story.append(Paragraph(", ".join(skills), S["body"]))

    # ── Certifications ────────────────────────────────────────────────────────
    certs = data.get("certifications", [])
    if certs:
        story.append(Paragraph("CERTIFICATIONS", S["section"]))
        story.append(HRFlowable(width="100%", thickness=1, color=BRAND_COLOR, spaceAfter=2))
        for cert in certs:
            story.append(Paragraph(f"• {cert}", S["bullet"]))

    doc.build(story)
    buf.seek(0)
    return buf.read()
