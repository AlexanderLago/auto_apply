# modules/tailor/resume_tailor.py
# Adapts job_bot's tailoring logic for the auto_apply pipeline.
# Input: master resume text + ParsedJD -> Output: tailored resume dict + file paths.

from __future__ import annotations
import re
from pathlib import Path

import config
from modules.tracker.models import ParsedJD
from modules.llm.client import call_llm, parse_json_response

log = config.get_logger(__name__)

_SYSTEM = """You are an expert ATS resume writer. Tailor the candidate's resume to the job description.

RULES:
1. NEVER fabricate experience, skills, credentials, or metrics.
2. Only rephrase and reorder existing content using the job description's language.
3. Preserve all dates, company names, and titles exactly.
4. Mirror keywords from the job description wherever truthfully applicable.

Return ONLY valid JSON:
{
  "name": "...", "email": "...", "phone": "...", "location": "...",
  "linkedin": "...", "website": "...",
  "summary": "3-4 sentence summary tailored to this specific role",
  "experience": [
    {"title": "...", "company": "...", "location": "...", "dates": "...",
     "bullets": ["action verb + impact", "..."]}
  ],
  "education": [
    {"degree": "...", "school": "...", "location": "...", "dates": "...", "details": "..."}
  ],
  "skills": ["Skill1", "Skill2"],
  "certifications": ["..."],
  "target_role": "Exact job title from the posting"
}"""


def tailor(
    resume_text: str,
    jd_text: str,
    parsed_jd: ParsedJD,
    output_dir: Path = None,
) -> dict:
    """
    Tailor resume_text to the given job description.
    Returns the structured resume dict.
    Optionally writes DOCX + PDF to output_dir if provided.
    """
    user_msg = (
        f"<resume>\n{resume_text}\n</resume>\n\n"
        f"<job_description>\n{jd_text[:4000]}\n</job_description>\n\n"
        f"Target role: {parsed_jd.title} at {parsed_jd.company}\n"
        "Tailor this resume. Return only JSON."
    )

    raw = call_llm(_SYSTEM, user_msg, max_tokens=4096, temperature=0.3)
    data = parse_json_response(raw)

    if output_dir:
        _write_files(data, output_dir, parsed_jd)

    log.info("Resume tailored for %s at %s", parsed_jd.title, parsed_jd.company)
    return data


def _write_files(data: dict, output_dir: Path, parsed_jd: ParsedJD):
    """Write DOCX (and PDF if possible) to output_dir. Returns (docx_path, pdf_path)."""
    from modules.tailor.docx_builder import build_docx

    output_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]", "", parsed_jd.company.lower()) or "company"
    docx_path = output_dir / f"resume_{slug}.docx"
    pdf_path  = output_dir / f"resume_{slug}.pdf"

    docx_path.write_bytes(build_docx(data))
    log.info("Wrote %s", docx_path.name)

    try:
        from modules.tailor.pdf_builder import build_pdf
        pdf_path.write_bytes(build_pdf(data))
        log.info("Wrote %s", pdf_path.name)
    except Exception as e:
        log.warning("PDF generation skipped (%s) — DOCX only", e)
        pdf_path = None

    return docx_path, pdf_path


def load_master_resume() -> str:
    """Load master resume text from the configured path."""
    path = config.MASTER_RESUME
    if not path.exists():
        raise FileNotFoundError(f"Master resume not found at {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    if suffix == ".docx":
        from docx import Document
        return "\n".join(p.text for p in Document(path).paragraphs)
    return path.read_text(encoding="utf-8")
