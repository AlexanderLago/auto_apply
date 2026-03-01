# auto_apply — Modular Job Application Automation

Personal-use pipeline: scrape → parse → score → tailor → (auto) apply.

---

## Folder Structure

```
auto_apply/
├── main.py                        # CLI entry point
├── config.py                      # Centralised config + logging (loads .env)
├── requirements.txt
├── .env.example                   # Copy to .env and fill in keys
│
├── data/
│   └── auto_apply.db              # SQLite — created automatically on first run
├── logs/
│   └── auto_apply.log
├── resumes/
│   ├── master_resume.pdf          # Your base resume — place here
│   └── tailored/                  # Tailored outputs written here
│
├── modules/
│   ├── scraper/
│   │   ├── base.py                # Abstract BaseScraper (add new sources here)
│   │   ├── adzuna.py              # Adzuna REST API (no browser needed)
│   │   ├── greenhouse.py          # Greenhouse public JSON API
│   │   └── lever.py               # Lever public JSON API
│   │
│   ├── parser/
│   │   └── jd_parser.py           # Claude → ParsedJD (skills, years, work type)
│   │
│   ├── scorer/
│   │   └── fit_scorer.py          # Weighted rubric — no LLM, pure logic, fast
│   │
│   ├── tailor/
│   │   └── resume_tailor.py       # Claude → tailored resume JSON + DOCX/PDF
│   │
│   ├── tracker/
│   │   ├── models.py              # Pydantic models + SQLite schema SQL
│   │   └── database.py            # All DB reads/writes (upsert, score, log)
│   │
│   └── applicator/
│       └── easy_apply.py          # Playwright browser automation (optional)
│
└── dashboard/
    └── app.py                     # Streamlit monitoring UI (optional)
```

---

## Implementation Order

Build in this sequence — each step is independently useful:

| Step | Module | What you get |
|------|--------|-------------|
| 1 | `config.py` + `tracker/models.py` + `tracker/database.py` | DB schema, logging, config |
| 2 | `scraper/greenhouse.py` + `scraper/lever.py` | Real jobs in DB, no API keys needed |
| 3 | `scraper/adzuna.py` | More jobs via Adzuna (keys from job_bot) |
| 4 | `parser/jd_parser.py` | Structured skill/requirement extraction |
| 5 | `scorer/fit_scorer.py` | Automated fit scoring, ranked job list |
| 6 | `tailor/resume_tailor.py` | Tailored resumes per job |
| 7 | `main.py` CLI | Full pipeline runnable from terminal |
| 8 | `dashboard/app.py` | Visual monitoring, manual triggers |
| 9 | `applicator/easy_apply.py` | Automated form submission (Greenhouse first) |

---

## Recommended Libraries

| Purpose | Library |
|---------|---------|
| LLM (parsing, tailoring) | `anthropic` |
| HTTP (Greenhouse, Lever, Adzuna) | `requests` |
| Data models + validation | `pydantic` |
| PDF parsing | `pdfplumber` |
| DOCX output | `python-docx` |
| Browser automation | `playwright` |
| Dashboard | `streamlit` + `pandas` |
| Config / secrets | `python-dotenv` |

---

## Data Schema

### `jobs` table
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| source | TEXT | `adzuna` \| `greenhouse` \| `lever` \| `linkedin` |
| external_id | TEXT | Platform job ID (unique with source) |
| title | TEXT | |
| company | TEXT | |
| location | TEXT | |
| work_type | TEXT | `remote` \| `hybrid` \| `onsite` \| `unknown` |
| url | TEXT | Direct link to posting |
| description_raw | TEXT | Full JD text |
| skills_required | TEXT | JSON array |
| skills_nice | TEXT | JSON array |
| salary_min / max | REAL | Nullable |
| scraped_at | TEXT | ISO datetime |
| fit_score | REAL | 0–100, set after scoring |
| fit_breakdown | TEXT | JSON `{skills, experience, education, location}` |
| status | TEXT | `new` → `scored` → `tailored` → `applied` |

### `applications` table
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| job_id | INTEGER FK | → jobs.id |
| resume_path | TEXT | Path to tailored resume file |
| applied_at | TEXT | ISO datetime |
| method | TEXT | `manual` \| `easy_apply` |
| outcome | TEXT | `pending` \| `interview` \| `rejected` \| `offer` \| `ghosted` |
| follow_up_date | TEXT | |
| notes | TEXT | |

---

## CLI Usage

```bash
# Setup
cp .env.example .env          # fill in API keys
pip install -r requirements.txt
playwright install chromium   # only needed for Easy Apply

# Place your resume
cp ~/your_resume.pdf resumes/master_resume.pdf

# Run individual steps
python main.py scrape --keyword "data analyst" --location "remote" --limit 50
python main.py score
python main.py tailor --min-score 60

# Or full pipeline
python main.py run --keyword "data analyst" --location "remote"

# Dashboard
python main.py dashboard
# OR
streamlit run dashboard/app.py
```

---

## Design Decisions

- **No ORM** — raw sqlite3 is simpler for personal use, easy to inspect with DB Browser for SQLite
- **Scraper deduplication** — `UNIQUE(source, external_id)` prevents duplicates on re-runs
- **Fit scorer is LLM-free** — deterministic, instant, no API cost for ranking
- **Parser uses Haiku** — fast and cheap for structured extraction vs Sonnet for tailoring
- **Easy Apply is opt-in** — never auto-submits unless `--auto-apply` flag is explicitly passed
- **job_bot reuse** — tailor module attempts to import job_bot's DOCX/PDF builders if co-located
