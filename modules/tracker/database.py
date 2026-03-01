# modules/tracker/database.py — SQLite CRUD operations
# All DB access goes through this module. No raw SQL elsewhere.

import json
import sqlite3
from contextlib import contextmanager
from typing import Optional

import config
from modules.tracker.models import SCHEMA_SQL, Job, Application, FitResult

log = config.get_logger(__name__)


@contextmanager
def _conn():
    """Context manager yielding a sqlite3 connection with row_factory set."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _conn() as con:
        con.executescript(SCHEMA_SQL)
    log.info("Database initialised at %s", config.DB_PATH)


# ── Jobs ───────────────────────────────────────────────────────────────────────

def upsert_job(job: Job) -> int:
    """
    Insert a new job or update it if (source, external_id) already exists.
    Returns the row id.
    """
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO jobs
                (source, external_id, title, company, location, work_type, url,
                 description_raw, skills_required, skills_nice, salary_min, salary_max,
                 posted_date, scraped_at, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                title           = excluded.title,
                description_raw = excluded.description_raw,
                scraped_at      = excluded.scraped_at
        """, (
            job.source, job.external_id, job.title, job.company,
            job.location, job.work_type, job.url, job.description_raw,
            json.dumps(job.skills_required), json.dumps(job.skills_nice_to_have),
            job.salary_min, job.salary_max, job.posted_date, job.scraped_at, job.status,
        ))
        return cur.lastrowid


def save_fit_result(job_id: int, result: FitResult) -> None:
    with _conn() as con:
        con.execute("""
            UPDATE jobs SET fit_score=?, fit_breakdown=?, status='scored'
            WHERE id=?
        """, (result.score, json.dumps(result.breakdown), job_id))


def update_job_status(job_id: int, status: str) -> None:
    with _conn() as con:
        con.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))


def get_jobs(status: Optional[str] = None, min_score: Optional[float] = None,
             limit: int = 100) -> list[dict]:
    """Fetch jobs, optionally filtered by status and minimum fit score."""
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if min_score is not None:
        clauses.append("fit_score >= ?")
        params.append(min_score)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM jobs {where} ORDER BY fit_score DESC NULLS LAST LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ── Applications ───────────────────────────────────────────────────────────────

def log_application(app: Application) -> int:
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO applications
                (job_id, resume_path, cover_letter_path, applied_at, method, notes, follow_up_date, outcome)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            app.job_id, app.resume_path, app.cover_letter_path,
            app.applied_at, app.method, app.notes, app.follow_up_date, app.outcome,
        ))
        update_job_status(app.job_id, "applied")
        return cur.lastrowid


def get_applications(outcome: Optional[str] = None) -> list[dict]:
    clauses, params = [], []
    if outcome:
        clauses.append("a.outcome = ?")
        params.append(outcome)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn() as con:
        rows = con.execute(f"""
            SELECT a.*, j.title, j.company, j.url, j.fit_score
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            {where}
            ORDER BY a.applied_at DESC
        """, params).fetchall()
    return [dict(r) for r in rows]
