# modules/__init__.py
"""
Auto Apply Modules — Job Application Automation Pipeline

This package contains all modules for the auto_apply job application system.

## Architecture

```
auto_apply/
├── main.py              # CLI entry point
├── config.py            # Central configuration
├── go.py                # Interactive menu
│
├── modules/
│   ├── scraper/         # Job sourcing (Greenhouse, Lever, Adzuna, etc.)
│   ├── parser/          # JD parsing + candidate profile extraction
│   ├── scorer/          # Fit scoring (LLM + rule-based)
│   ├── tailor/          # Resume + cover letter customization
│   ├── tracker/         # Database models + CRUD operations
│   ├── applicator/      # Browser automation (Easy Apply)
│   ├── notifier/        # Email digests + notifications
│   ├── llm/             # LLM client abstraction
│   └── utils/           # Helpers (email reader, location filter)
│
├── dashboard/           # Streamlit monitoring UI
├── data/                # SQLite database
├── logs/                # Application logs + screenshots
└── resumes/             # Master + tailored resumes
```

## Pipeline Flow

1. **Scrape** → Fetch jobs from Greenhouse, Lever, Adzuna, etc.
2. **Parse** → Extract skills/requirements from JDs (LLM)
3. **Score** → Calculate fit score vs candidate profile
4. **Tailor** → Customize resume + cover letter per job
5. **Apply** → Auto-submit forms via browser automation
6. **Track** → Log applications + outcomes in SQLite

## Module Overview

| Module | Purpose | Key Files |
|--------|---------|-----------|
| scraper | Job sourcing | greenhouse.py, lever.py, adzuna.py |
| parser | JD + candidate parsing | jd_parser.py, candidate_parser.py |
| scorer | Fit scoring | llm_scorer.py, fit_scorer.py |
| tailor | Resume customization | resume_tailor.py, cover_letter.py |
| tracker | Data persistence | models.py, database.py |
| applicator | Form automation | easy_apply.py |
| notifier | Email alerts | email_notifier.py |
| utils | Helpers | email_reader.py, location_filter.py |

## Configuration

All settings in `config.py` loaded from `.env`:
- API keys (Anthropic, Adzuna, LinkedIn, etc.)
- Scraping targets (Greenhouse boards, Lever companies)
- Scoring weights and thresholds
- Applicant personal info

## Database Schema

See `tracker/models.py` for Pydantic models and SQL schema.

Main tables:
- `jobs` — Scraped job postings with fit scores
- `applications` — Submitted applications with outcomes
"""

# Import all modules for easy access
from modules import (
    scraper,
    parser,
    scorer,
    tailor,
    tracker,
    applicator,
    notifier,
    llm,
    utils,
)

__all__ = [
    "scraper",
    "parser",
    "scorer",
    "tailor",
    "tracker",
    "applicator",
    "notifier",
    "llm",
    "utils",
]
