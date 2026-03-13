# modules/applicator/__init__.py
"""
Applicator Module — Automated Job Application Submission

This module handles automated form filling and submission for job applications.

## Components

### easy_apply.py — EasyApplyBot
Browser automation using Playwright to fill and submit application forms.

**Supported ATS Platforms:**
- Greenhouse (job-boards.greenhouse.io and company career sites)
- Lever (lever.co)
- Ashby (ashby.com, ashbyhq.com)

**Key Features:**
- Human-like typing with variable speed and occasional typos
- Mouse movement with bezier curves and micro-jitter
- Proxy rotation per application
- CAPTCHA detection and skip
- Email verification code reading (for Greenhouse security codes)
- Resume and cover letter upload
- EEO dropdown auto-filling with scrambled form detection
- Phone country selection (ITI widget support)

**Usage:**
```python
from modules.applicator.easy_apply import EasyApplyBot
from modules.tracker.models import Job

job = Job(source="greenhouse", external_id="123", title="Engineer", ...)

with EasyApplyBot(submit=True, headless=False) as bot:
    bot.resume_path = Path("resumes/tailored/resume_company.docx")
    outcome = bot.apply(job, job_id=456)
    
    if outcome.status == "submitted":
        print("Application submitted!")
    elif outcome.status == "captcha":
        print("CAPTCHA detected — manual intervention required")
    elif outcome.status == "error":
        print(f"Error: {outcome.error}")
```

**Known Issues:**
- Amplitude, Chime: Broken EEO form configurations (auto-skipped)
- Some companies require phone verification code (handled automatically)
- CAPTCHA: Skipped with status="captcha" (requires manual apply)

**Configuration:**
All applicant data loaded from config.py (APPLICANT_* constants)
"""

from modules.applicator.easy_apply import EasyApplyBot, ApplyOutcome

__all__ = ["EasyApplyBot", "ApplyOutcome"]
