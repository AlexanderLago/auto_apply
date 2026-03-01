# modules/tracker/models.py — Pydantic models + SQLite schema strings
# These are the canonical data shapes shared across all modules.

from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# ── Pydantic models (used in-memory, returned by scrapers/parser) ──────────────

class Job(BaseModel):
    source: str                                 # 'adzuna' | 'greenhouse' | 'lever' | 'linkedin'
    external_id: str                            # platform job ID
    title: str
    company: str
    location: str = ""
    work_type: str = "unknown"                  # 'remote' | 'hybrid' | 'onsite' | 'unknown'
    url: str = ""
    description_raw: str = ""
    skills_required: List[str] = Field(default_factory=list)
    skills_nice_to_have: List[str] = Field(default_factory=list)
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    posted_date: Optional[str] = None
    scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    # Set after scoring
    fit_score: Optional[float] = None
    fit_breakdown: Optional[Dict] = None
    status: str = "new"                         # 'new'|'scored'|'tailored'|'applied'|'rejected'|'offer'|'ignored'


class Application(BaseModel):
    job_id: int
    resume_path: str = ""
    cover_letter_path: str = ""
    applied_at: Optional[str] = None
    method: str = "manual"                      # 'manual' | 'easy_apply'
    notes: str = ""
    follow_up_date: Optional[str] = None
    outcome: str = "pending"                    # 'pending'|'interview'|'rejected'|'offer'|'ghosted'


class ParsedJD(BaseModel):
    """Structured output from the JD parser LLM call."""
    title: str
    company: str
    skills_required: List[str]
    skills_nice_to_have: List[str]
    years_experience: Optional[int] = None
    education_required: str = ""
    work_type: str = "unknown"
    location: str = ""
    summary: str = ""                           # 1-2 sentence description of the role


class FitResult(BaseModel):
    """Output of the fit scorer."""
    score: float                                # 0–100
    breakdown: Dict[str, float]
    strengths: List[str]
    gaps: List[str]
    recommendation: str                         # 'apply' | 'tailor_and_apply' | 'skip'


# ── SQLite schema ──────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,
    external_id     TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    company         TEXT    NOT NULL,
    location        TEXT    DEFAULT '',
    work_type       TEXT    DEFAULT 'unknown',
    url             TEXT    DEFAULT '',
    description_raw TEXT    DEFAULT '',
    skills_required TEXT    DEFAULT '[]',       -- JSON array
    skills_nice     TEXT    DEFAULT '[]',       -- JSON array
    salary_min      REAL,
    salary_max      REAL,
    posted_date     TEXT,
    scraped_at      TEXT    NOT NULL,
    fit_score       REAL,
    fit_breakdown   TEXT,                       -- JSON object
    status          TEXT    DEFAULT 'new',
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id              INTEGER NOT NULL REFERENCES jobs(id),
    resume_path         TEXT    DEFAULT '',
    cover_letter_path   TEXT    DEFAULT '',
    applied_at          TEXT,
    method              TEXT    DEFAULT 'manual',
    notes               TEXT    DEFAULT '',
    follow_up_date      TEXT,
    outcome             TEXT    DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_jobs_status   ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source   ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_score    ON jobs(fit_score);
"""
