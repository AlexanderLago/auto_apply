# modules/parser/candidate_parser.py
# Extracts a structured candidate profile from master resume text.
# Result is cached to disk so we don't re-parse on every run.

import json
import hashlib
from pathlib import Path
from typing import Optional

import config
from modules.llm.client import call_llm, parse_json_response

log = config.get_logger(__name__)

_CACHE_FILE = config.ROOT_DIR / "data" / "candidate_profile.json"

_SYSTEM = """You are a resume analyst. Extract structured information from this resume.
Return ONLY valid JSON — no markdown, no explanation:
{
  "name": "Full Name",
  "email": "email@example.com",
  "location": "City, State",
  "skills": ["Python", "SQL", "Tableau"],
  "years_experience": 4,
  "education": "Bachelor's in Computer Science",
  "education_level": "bachelor",
  "titles": ["Data Analyst", "Business Intelligence Analyst"],
  "summary": "1-2 sentence description of this candidate's background"
}

Rules:
- skills: all technical and soft skills, normalised (e.g. "MS Excel" -> "Excel")
- years_experience: integer, estimate from date spans if not stated explicitly
- education_level: "high_school" | "associate" | "bachelor" | "master" | "phd"
- titles: job titles held, most recent first — used to infer target roles
- Include ALL skills you can identify — be thorough"""


def parse_candidate(resume_text: str, force: bool = False) -> dict:
    """
    Parse master resume into a structured candidate profile.
    Caches result to data/candidate_profile.json keyed by resume hash.
    Pass force=True to re-parse even if cached.
    """
    resume_hash = hashlib.md5(resume_text.encode()).hexdigest()

    if not force and _CACHE_FILE.exists():
        try:
            cached = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if cached.get("_resume_hash") == resume_hash:
                log.info("Candidate profile loaded from cache")
                return cached
        except Exception:
            pass

    log.info("Parsing candidate profile from resume (%d chars)...", len(resume_text))
    raw = call_llm(_SYSTEM, resume_text[:6000], max_tokens=1024)
    profile = parse_json_response(raw)
    profile["_resume_hash"] = resume_hash

    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    log.info("Candidate profile parsed and cached: %s, %d skills, %d years exp",
             profile.get("name"), len(profile.get("skills", [])), profile.get("years_experience", 0))

    return profile


def load_cached_profile() -> Optional[dict]:
    """Return the cached profile without re-parsing, or None if not cached yet."""
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None
