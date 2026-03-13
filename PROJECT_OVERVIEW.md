# Auto Apply — Project Overview & Context

**Last Updated:** 2026-03-10  
**Repository:** https://github.com/AlexanderLago/auto_apply  
**Deployed Dashboard:** https://share.streamlit.io (deploy from `dashboard/app.py`)

---

## 🎯 Project Goal

Automate job application pipeline: **scrape → parse → score → tailor → apply**

Target: 50-100 applications/day with 70%+ success rate on compatible forms.

---

## 📁 Project Structure

```
auto_apply/
├── main.py                        # CLI: python main.py <command>
├── go.py                          # Interactive menu
├── config.py                      # Central config (loads .env)
├── requirements.txt               # Python dependencies
├── README.md                      # User documentation
├── STATUS_REPORT.md               # Current development status
├── LESSONS_LEARNED.md             # Development learnings
│
├── modules/                       # Core automation modules
│   ├── scraper/                   # Job sourcing
│   │   ├── base.py                # Abstract BaseScraper
│   │   ├── greenhouse.py          # Greenhouse API
│   │   ├── lever.py               # Lever API
│   │   ├── adzuna.py              # Adzuna API
│   │   ├── ashby.py               # Ashby API
│   │   ├── linkedin.py            # LinkedIn (unofficial API)
│   │   ├── indeed.py              # Indeed scraper
│   │   └── ...
│   │
│   ├── parser/                    # JD + candidate parsing
│   │   ├── jd_parser.py           # Parse job descriptions (LLM)
│   │   └── candidate_parser.py    # Parse master resume
│   │
│   ├── scorer/                    # Fit scoring
│   │   ├── llm_scorer.py          # LLM-based scoring
│   │   └── fit_scorer.py          # Rule-based scoring
│   │
│   ├── tailor/                    # Resume customization
│   │   ├── resume_tailor.py       # Tailor resume per job
│   │   ├── cover_letter.py        # Generate cover letters
│   │   ├── docx_builder.py        # DOCX generation
│   │   └── pdf_builder.py         # PDF generation
│   │
│   ├── tracker/                   # Data persistence
│   │   ├── models.py              # Pydantic models + SQL schema
│   │   └── database.py            # SQLite CRUD operations
│   │
│   ├── applicator/                # Browser automation
│   │   └── easy_apply.py          # Playwright form filler
│   │
│   ├── notifier/                  # Notifications
│   │   └── email_notifier.py      # Email digests
│   │
│   ├── llm/                       # LLM abstraction
│   │   └── client.py              # Multi-provider LLM client
│   │
│   └── utils/                     # Helpers
│       ├── email_reader.py        # IMAP verification code reader
│       └── location_filter.py     # Remote/NYC/NJ filtering
│
├── dashboard/                     # Streamlit UI
│   ├── app.py                     # Main dashboard
│   └── terminal_app.py            # Terminal UI (fallback)
│
├── data/                          # SQLite database
│   └── auto_apply.db
│
├── logs/                          # Logs + screenshots
│   ├── auto_apply.log
│   └── screenshots/
│
└── resumes/
    ├── master_resume.pdf          # Base resume
    ├── tailored/                  # Customized resumes
    └── cover_letters/             # Generated cover letters
```

---

## 🚀 Quick Start

```bash
# Setup
cp .env.example .env          # Fill in API keys
pip install -r requirements.txt
playwright install chromium   # For Easy Apply

# Place your resume
cp ~/your_resume.pdf resumes/master_resume.pdf

# Run pipeline
python go.py                  # Interactive menu
# OR
python main.py scrape --keyword "data analyst" --location "remote"
python main.py score
python main.py tailor --min-score 60
python main.py apply --limit 20 --submit
```

---

## 📊 Pipeline Details

### 1. Scrape
**Sources:**
- **Job Boards:** Adzuna, Indeed, Remotive, Jobicy, WeWorkRemotely, USAJobs, LinkedIn
- **ATS Platforms:** Greenhouse (70+ companies), Lever (20+ companies), Ashby (30+ companies)

**Output:** Jobs stored in `data/auto_apply.db` with status="new"

### 2. Parse Candidate
**Input:** `resumes/master_resume.pdf`  
**Output:** Structured profile cached in `.profile_cache.json`
- Skills list
- Years of experience
- Education level
- Target titles
- Location

### 3. Score Jobs
**Process:** LLM compares candidate profile vs job requirements  
**Output:** Fit score 0-100 with breakdown:
- Skills match (40%)
- Experience match (30%)
- Education match (15%)
- Location match (15%)

**Status:** new → scored

### 4. Tailor Resumes
**Input:** Master resume + job description + parsed JD  
**Output:** 
- `resumes/tailored/resume_<company>.docx`
- `resumes/cover_letters/cover_letter_<company>.txt`

**Status:** scored → tailored

### 5. Apply (Easy Apply)
**Platforms:** Greenhouse, Lever, Ashby  
**Process:**
1. Open browser (Playwright)
2. Navigate to job URL
3. Fill personal info
4. Upload tailored resume + cover letter
5. Fill EEO dropdowns
6. Handle phone country (ITI widget)
7. Click Submit
8. Handle email verification code (if required)
9. Verify submission success

**Status:** tailored → applied

---

## 🔧 Configuration

### .env Variables

```bash
# LLM Providers (chain: Groq → Cerebras → Gemini → Anthropic)
ANTHROPIC_API_KEY=
GROQ_API_KEY=
CEREBRAS_API_KEY=
GEMINI_API_KEY=

# Job Sources
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
USAJOBS_API_KEY=
USAJOBS_EMAIL=
LINKEDIN_EMAIL=
LINKEDIN_PASS=

# Scraping Targets
GREENHOUSE_BOARDS=stripe,discord,robinhood,amplitude,...
LEVER_COMPANIES=plaid,wealthfront,nerdwallet,...
ASHBY_COMPANIES=notion,linear,vercel,retool,...

# Email (for verification codes + digests)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=app-password
NOTIFY_EMAIL=your@gmail.com

# Applicant Info
APPLICANT_FIRST_NAME=
APPLICANT_LAST_NAME=
APPLICANT_EMAIL=
APPLICANT_PHONE=
APPLICANT_LINKEDIN=
APPLICANT_YEARS_EXP=
APPLICANT_GENDER=
APPLICANT_VETERAN_STATUS=
APPLICANT_DISABILITY=
APPLICANT_RACE=

# Thresholds
AUTO_APPLY_MIN_SCORE=68
MIN_SCORE_TO_TAILOR=65
```

---

## 🎯 Current Status (2026-03-10)

### ✅ Working
- [x] All EEO dropdowns (9-11 per form)
- [x] Gender matching (no opposite selection)
- [x] Resume + cover letter upload
- [x] Personal info auto-fill
- [x] Submit button clicking
- [x] Validation error detection
- [x] Email verification code reading
- [x] Location filtering (Remote anywhere, Hybrid/Onsite NYC/NJ only)
- [x] Phone country selection (ITI widget — 4 methods)
- [x] Scrambled form detection (auto-skip broken companies)

### ❌ Known Issues
- [ ] Amplitude, Chime: Broken EEO forms (auto-skipped)
- [ ] CAPTCHA: Requires manual intervention
- [ ] Custom career sites: Some need manual URL resolution

### 📈 Expected Coverage
- Standard Greenhouse: 60-70% ✅
- Ashby forms: 10-15% ✅
- Broken configs: 5-10% ⏭️ (skipped)
- Custom forms: 10-15% 🔧 (needs work)
- Enterprise ATS: 10% 🔧 (needs work)

**Target: 70-80% coverage**

---

## 🧪 Testing

```bash
# Test apply (dry run)
python main.py apply --limit 5

# Test apply (submit)
python main.py apply --limit 20 --submit

# Test specific company
python main.py apply --limit 1 --submit
# (Select job from DB manually if needed)
```

### Priority Test Companies
- GitLab, Stripe, Discord, Gusto (known working)
- Airbnb, Lyft, Robinhood, Brex, Asana

### Skip Companies
- Amplitude, Chime (broken EEO configs)

---

## 📊 Dashboard

**Deploy on Streamlit Cloud:**
1. Go to https://share.streamlit.io
2. Connect GitHub repo: `AlexanderLago/auto_apply`
3. Main file: `dashboard/app.py`
4. Add secrets in Settings → Secrets

**Features:**
- Pipeline metrics (total, scored, tailored, applied)
- Interactive charts (Plotly)
- Apply queue table
- Job detail view with fit breakdown
- Application log + timeline
- Cover letter preview/download
- Sidebar controls for all pipeline steps

---

## 🐛 Debugging

### Logs
```bash
tail -f logs/auto_apply.log
```

### Screenshots
```bash
ls -lt logs/screenshots/
# View: submission_*.png, phone_country_*.png
```

### Common Issues

**Phone country fails:**
```
Could not set phone country — form may show 'Select a country' error
```
→ Check `logs/screenshots/phone_country_*.png` for widget state

**EEO dropdown scrambled:**
```
SCRAMBLED FORM DETECTED: Veteran Status — options=['Gay', 'Lesbian', ...]
```
→ Company has broken Greenhouse config (auto-skipped if in skip list)

**CAPTCHA detected:**
```
CAPTCHA detected for job 123 — skipping
```
→ Manual apply required (status="captcha")

---

## 📝 Development Notes

See `LESSONS_LEARNED.md` and `STATUS_REPORT.md` for detailed development history.

### Key Fixes (2026-03-10)
1. Email verification recipient filtering
2. Location filter (NYC/NJ only for hybrid/onsite)
3. Phone country ITI widget (4 methods)
4. EEO scrambled form detection
5. Gender matching (exclusive pairs)
6. Streamlit dashboard deployment

---

## 🔐 Security

**Never commit:**
- `.env` — API keys
- `.streamlit/secrets.toml` — Streamlit secrets
- `resumes/*.pdf` — Personal documents
- `data/auto_apply.db` — Application history

**Gitignore already excludes these.**

---

## 📞 Contact

**Developer:** Alexander Lago  
**Email:** alexanderlago11@gmail.com  
**LinkedIn:** https://linkedin.com/in/alexander-lago-89073b160/
