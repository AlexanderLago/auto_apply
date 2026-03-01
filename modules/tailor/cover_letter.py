# modules/tailor/cover_letter.py
# Generates a targeted cover letter for each tailored resume.
# Output: plain text saved alongside the DOCX in resumes/cover_letters/

from __future__ import annotations
import re
from pathlib import Path

import config
from modules.tracker.models import ParsedJD
from modules.llm.client import call_llm

log = config.get_logger(__name__)

_SYSTEM = """You are an expert cover letter writer for professional job applications.

RULES:
1. 3 paragraphs, under 280 words total.
2. Paragraph 1 — Hook: one specific thing about this company/role that genuinely excites the candidate. Reference the company by name.
3. Paragraph 2 — Evidence: 2-3 concrete achievements from the resume that directly match the job requirements. Use numbers and impact where available.
4. Paragraph 3 — Close: confident, brief call to action. One sentence.
5. NEVER fabricate experience, metrics, or credentials not in the resume.
6. Mirror key phrases from the job description naturally.
7. Sound human and direct — no filler phrases like "I am writing to express my interest."
8. Do NOT include a header, address block, salutation, or sign-off. Body paragraphs only."""


def generate(
    resume_text: str,
    jd_text: str,
    parsed_jd: ParsedJD,
    candidate_name: str = "",
) -> str:
    """
    Generate a targeted cover letter body.
    Returns plain text (no salutation, no header — ready to paste or wrap).
    """
    user_msg = (
        f"<resume>\n{resume_text[:4000]}\n</resume>\n\n"
        f"<job_description>\n{jd_text[:3000]}\n</job_description>\n\n"
        f"Role: {parsed_jd.title} at {parsed_jd.company}\n"
        f"Candidate: {candidate_name}\n\n"
        "Write the cover letter body (3 paragraphs, no header/salutation/sign-off)."
    )

    text = call_llm(_SYSTEM, user_msg, max_tokens=512, temperature=0.4)
    log.info("Cover letter generated for %s at %s", parsed_jd.title, parsed_jd.company)
    return text.strip()


def save(text: str, output_dir: Path, parsed_jd: ParsedJD) -> Path:
    """Write cover letter to output_dir/cover_letter_{company}.txt"""
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]", "", parsed_jd.company.lower()) or "company"
    path = output_dir / f"cover_letter_{slug}.txt"

    # Wrap with salutation + sign-off so the file is ready to use
    name = config.APPLICANT_FIRST_NAME + " " + config.APPLICANT_LAST_NAME
    full = (
        f"Dear Hiring Manager,\n\n"
        f"{text}\n\n"
        f"Sincerely,\n{name.strip() or 'Alexander Lago'}\n"
        f"{config.APPLICANT_EMAIL}\n"
    )
    path.write_text(full, encoding="utf-8")
    log.info("Cover letter saved: %s", path.name)
    return path
