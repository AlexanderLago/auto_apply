# modules/applicator/easy_apply.py
# Browser automation layer for Easy Apply forms (LinkedIn, Greenhouse, Lever).
# Uses Playwright. Install with: playwright install chromium
#
# IMPORTANT: Use responsibly. Respect robots.txt and ToS.
# Recommended: run headful (headless=False) so you can intervene if needed.

from __future__ import annotations
from pathlib import Path

import config
from modules.tracker.models import Job, Application
from modules.tracker import database

log = config.get_logger(__name__)


class EasyApplyBot:
    """
    Orchestrates automated form filling for supported job boards.

    Usage:
        bot = EasyApplyBot(resume_path=Path("resumes/tailored_stripe.pdf"))
        result = bot.apply(job)
    """

    def __init__(self, resume_path: Path, headless: bool = False):
        self.resume_path = resume_path
        self.headless    = headless
        self._browser    = None
        self._page       = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw      = sync_playwright().__enter__()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._page    = self._browser.new_page()
        return self

    def __exit__(self, *_):
        self._browser.close()
        self._pw.__exit__(None, None, None)

    # ── Public API ─────────────────────────────────────────────────────────────

    def apply(self, job: Job, job_id: int) -> Application | None:
        """
        Route to the correct apply strategy based on job.source.
        Returns an Application record on success, None on failure.
        """
        log.info("Attempting Easy Apply: %s at %s", job.title, job.company)
        try:
            if job.source == "linkedin":
                return self._apply_linkedin(job, job_id)
            if job.source == "greenhouse":
                return self._apply_greenhouse(job, job_id)
            if job.source == "lever":
                return self._apply_lever(job, job_id)
            log.warning("No Easy Apply handler for source: %s", job.source)
            return None
        except Exception as e:
            log.error("Easy Apply failed for job %d: %s", job_id, e)
            return None

    # ── Source-specific strategies ─────────────────────────────────────────────

    def _apply_linkedin(self, job: Job, job_id: int) -> Application | None:
        """
        LinkedIn Easy Apply flow.
        Requires user to be logged in (session cookies).

        Steps:
        1. Navigate to job URL
        2. Click "Easy Apply" button
        3. Fill name/email (usually pre-filled from LinkedIn profile)
        4. Upload resume PDF
        5. Handle multi-step form (work experience, screening questions)
        6. Submit — STOP before submitting if any question requires manual review
        """
        # TODO: Implement LinkedIn session management (cookie injection)
        # TODO: Handle multi-step form wizard
        # TODO: Detect and skip jobs with "complex" forms requiring manual review
        log.warning("LinkedIn Easy Apply: not yet implemented — manual action required")
        return None

    def _apply_greenhouse(self, job: Job, job_id: int) -> Application | None:
        """
        Greenhouse standard application form.

        Steps:
        1. Navigate to job URL (redirect_url from API)
        2. Fill: First Name, Last Name, Email, Phone, Resume upload
        3. Answer standard demographic questions (skip / prefer not to say)
        4. Submit
        """
        page = self._page
        page.goto(job.url, wait_until="networkidle")

        # Standard Greenhouse form selectors (stable across boards)
        try:
            page.fill("#first_name",  _get_env_or_raise("APPLICANT_FIRST_NAME"))
            page.fill("#last_name",   _get_env_or_raise("APPLICANT_LAST_NAME"))
            page.fill("#email",       _get_env_or_raise("APPLICANT_EMAIL"))
            page.fill("#phone",       _get_env_or_raise("APPLICANT_PHONE"))
            page.set_input_files("#resume_text_resume", str(self.resume_path))

            # Optional: cover letter
            # page.set_input_files("#cover_letter_text_cover_letter", str(cover_letter_path))

            # Submit — comment this out during testing
            # page.click("input[type='submit']")

            log.info("Greenhouse form filled for job %d (submit commented out)", job_id)
            return _make_application(job_id, self.resume_path, "easy_apply")
        except Exception as e:
            log.error("Greenhouse form error: %s", e)
            return None

    def _apply_lever(self, job: Job, job_id: int) -> Application | None:
        """
        Lever standard application form.
        Similar to Greenhouse but different selectors.
        """
        # TODO: Implement Lever form filling
        log.warning("Lever Easy Apply: not yet implemented")
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_env_or_raise(key: str) -> str:
    import os
    val = os.getenv(key, "")
    if not val:
        raise EnvironmentError(f"{key} not set in .env — required for Easy Apply")
    return val


def _make_application(job_id: int, resume_path: Path, method: str) -> Application:
    from datetime import datetime
    return Application(
        job_id=job_id,
        resume_path=str(resume_path),
        applied_at=datetime.utcnow().isoformat(),
        method=method,
    )
