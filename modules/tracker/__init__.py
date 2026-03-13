# modules/tracker/__init__.py
"""
Tracker Module — Data Persistence and Application Tracking

This module handles all database operations for tracking jobs and applications.

## Components

### models.py — Pydantic Models + SQL Schema
Defines data structures used throughout the application.

**Models:**
- `Job` — Job posting with fit score and status
- `Application` — Submitted application with outcome
- `ParsedJD` — Structured job description (LLM output)
- `FitResult` — Fit scoring result with breakdown

**Database Schema:**
```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    source TEXT,              -- greenhouse, lever, adzuna, etc.
    external_id TEXT,         -- platform job ID
    title TEXT,
    company TEXT,
    location TEXT,
    work_type TEXT,           -- remote, hybrid, onsite
    url TEXT,
    description_raw TEXT,
    fit_score REAL,           -- 0-100
    fit_breakdown TEXT,       -- JSON {skills, experience, education, location}
    status TEXT               -- new, scored, tailored, applied, ignored
);

CREATE TABLE applications (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id),
    resume_path TEXT,
    cover_letter_path TEXT,
    applied_at TEXT,
    method TEXT,              -- manual, easy_apply
    outcome TEXT              -- pending, interview, rejected, offer
);
```

### database.py — CRUD Operations
All database access goes through this module.

**Functions:**
- `init_db()` — Create tables if not exist
- `upsert_job(job)` — Insert or update job
- `get_jobs(status, min_score, limit)` — Fetch jobs with filters
- `save_fit_result(job_id, result)` — Store fit score
- `update_job_status(job_id, status)` — Update job status
- `log_application(app)` — Record submitted application
- `get_applications(outcome)` — Fetch application history
- `deduplicate_jobs()` — Remove duplicate job entries

**Usage:**
```python
from modules.tracker.database import (
    init_db, upsert_job, get_jobs, save_fit_result,
    update_job_status, log_application
)
from modules.tracker.models import Job, Application

# Initialize
init_db()

# Store job
job = Job(source="greenhouse", external_id="123", title="Engineer", ...)
upsert_job(job)

# Fetch scored jobs
jobs = get_jobs(status="scored", min_score=70, limit=50)

# Save fit score
save_fit_result(job_id, fit_result)

# Log application
app = Application(job_id=job_id, resume_path="...", method="easy_apply")
log_application(app)
```

**Concurrency:**
- WAL mode enabled for better concurrency
- 60 second busy timeout
- Context manager for proper connection handling
"""

from modules.tracker.models import Job, Application, ParsedJD, FitResult, SCHEMA_SQL
from modules.tracker.database import (
    init_db,
    upsert_job,
    get_jobs,
    save_fit_result,
    update_job_status,
    log_application,
    get_applications,
    deduplicate_jobs,
)

__all__ = [
    # Models
    "Job",
    "Application",
    "ParsedJD",
    "FitResult",
    "SCHEMA_SQL",
    # Database
    "init_db",
    "upsert_job",
    "get_jobs",
    "save_fit_result",
    "update_job_status",
    "log_application",
    "get_applications",
    "deduplicate_jobs",
]
