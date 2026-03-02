# modules/applicator/easy_apply.py
# Browser automation for Greenhouse and Lever application forms.
# Uses Playwright (headless=False by default so you can monitor / intervene).
#
# SAFETY: actual form submission only happens when submit=True is passed.
#         Default is dry_run mode — fills the form but does NOT click Submit.
#
# Usage:
#   with EasyApplyBot(resume_path=Path("resumes/tailored/resume_jobot.docx"),
#                     submit=False) as bot:
#       app = bot.apply(job, job_id)

from __future__ import annotations
from pathlib import Path
from datetime import datetime

import config
from modules.tracker.models import Job, Application

log = config.get_logger(__name__)


class EasyApplyBot:
    def __init__(self, resume_path: Path = None, headless: bool = False, submit: bool = False):
        self.resume_path = Path(resume_path) if resume_path else None
        self.headless    = headless
        self.submit      = submit   # must be True to actually click Submit
        self._pw         = None
        self._browser    = None
        self._page       = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw_cm   = sync_playwright()
        self._pw      = self._pw_cm.__enter__()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._page    = self._browser.new_page()
        return self

    def __exit__(self, *_):
        if self._browser:
            self._browser.close()
        if self._pw_cm:
            self._pw_cm.__exit__(None, None, None)

    def apply(self, job: Job, job_id: int) -> Application | None:
        log.info("Easy Apply [%s]: %s at %s (submit=%s)",
                 job.source, job.title, job.company, self.submit)
        try:
            ats = self._detect_ats(job)
            if ats == "greenhouse":
                return self._apply_greenhouse(job, job_id)
            if ats == "lever":
                return self._apply_lever(job, job_id)
            if job.source == "linkedin":
                return self._apply_linkedin(job, job_id)
            log.warning("No Easy Apply handler for %s (url=%s)", job.source, job.url[:60])
            return None
        except Exception as e:
            log.error("Easy Apply failed for job %d: %s", job_id, e)
            return None

    @staticmethod
    def _detect_ats(job: Job) -> str:
        """
        Determine which ATS the job uses.
        Checks the job's source first, then falls back to URL pattern matching
        so that Adzuna/RemoteOK jobs pointing to Greenhouse or Lever can also
        be auto-applied.
        """
        if job.source in ("greenhouse", "lever"):
            return job.source
        url = (job.url or "").lower()
        if "greenhouse.io" in url or "boards.greenhouse.io" in url:
            return "greenhouse"
        if "lever.co" in url or "jobs.lever.co" in url:
            return "lever"
        return job.source  # unknown — apply() will log a warning

    # ── Greenhouse ─────────────────────────────────────────────────────────────

    def _apply_greenhouse(self, job: Job, job_id: int) -> Application | None:
        """
        Fill the standard Greenhouse application form.
        Greenhouse forms are hosted at boards.greenhouse.io/<token>/jobs/<id>.
        Selectors are stable across all Greenhouse boards.
        """
        page = self._page
        page.goto(job.url, wait_until="networkidle", timeout=30000)

        # Personal info
        _fill_if_exists(page, "#first_name", config.APPLICANT_FIRST_NAME)
        _fill_if_exists(page, "#last_name",  config.APPLICANT_LAST_NAME)
        _fill_if_exists(page, "#email",      config.APPLICANT_EMAIL)
        _fill_if_exists(page, "#phone",      config.APPLICANT_PHONE)

        # Resume upload — try multiple selectors across different Greenhouse board configs
        for resume_selector in (
            "input[type='file'][id*='resume']",
            "input[type='file'][name*='resume']",
            "input[type='file']",
        ):
            if page.locator(resume_selector).count() > 0:
                break
        else:
            resume_selector = None

        if resume_selector and self.resume_path and self.resume_path.exists():
            page.set_input_files(resume_selector, str(self.resume_path))
            log.info("Resume uploaded: %s", self.resume_path.name)
        elif not resume_selector:
            log.warning("No file input found on page for job %d", job_id)
        else:
            log.warning("Resume file missing: %s", self.resume_path)

        # Demographic / EEO dropdowns — select "Decline to self-identify" where present
        for select in page.locator("select").all():
            try:
                opts = select.locator("option").all_text_contents()
                decline = next((o for o in opts if "decline" in o.lower()), None)
                if decline:
                    select.select_option(label=decline)
            except Exception:
                pass

        if self.submit:
            page.locator("input[type='submit'], button[type='submit']").first.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            log.info("Greenhouse form submitted for job %d", job_id)
        else:
            log.info("Greenhouse form filled (dry run — submit=False) for job %d", job_id)

        return _make_application(job_id, self.resume_path, "easy_apply",
                                 notes="dry_run" if not self.submit else "")

    # ── Lever ──────────────────────────────────────────────────────────────────

    def _apply_lever(self, job: Job, job_id: int) -> Application | None:
        """
        Fill the standard Lever application form.
        Lever apply pages are at jobs.lever.co/<company>/<job-id>/apply.
        """
        apply_url = job.url
        if "/apply" not in apply_url:
            apply_url = apply_url.rstrip("/") + "/apply"

        page = self._page
        page.goto(apply_url, wait_until="networkidle", timeout=30000)

        full_name = f"{config.APPLICANT_FIRST_NAME} {config.APPLICANT_LAST_NAME}".strip()
        _fill_if_exists(page, "input[name='name']",  full_name)
        _fill_if_exists(page, "input[name='email']", config.APPLICANT_EMAIL)
        _fill_if_exists(page, "input[name='phone']", config.APPLICANT_PHONE)

        # Resume upload
        resume_selector = "input[type='file']"
        if page.locator(resume_selector).first.count() > 0 and self.resume_path.exists():
            page.set_input_files(resume_selector, str(self.resume_path))
            log.info("Resume uploaded: %s", self.resume_path.name)
        else:
            log.warning("Resume input not found or file missing: %s", self.resume_path)

        if self.submit:
            page.locator("button[type='submit'], input[type='submit']").first.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            log.info("Lever form submitted for job %d", job_id)
        else:
            log.info("Lever form filled (dry run — submit=False) for job %d", job_id)

        return _make_application(job_id, self.resume_path, "easy_apply",
                                 notes="dry_run" if not self.submit else "")

    # ── LinkedIn ───────────────────────────────────────────────────────────────

    def _apply_linkedin(self, job: Job, job_id: int) -> Application | None:
        """LinkedIn Easy Apply requires an active logged-in session — not automated."""
        log.warning("LinkedIn Easy Apply requires manual login — skipping job %d", job_id)
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fill_if_exists(page, selector: str, value: str) -> None:
    """Fill a field only if it exists on the page and value is non-empty."""
    if not value:
        return
    try:
        loc = page.locator(selector)
        if loc.count() > 0:
            loc.first.fill(value)
    except Exception as e:
        log.debug("Could not fill %s: %s", selector, e)


def _make_application(job_id: int, resume_path: Path,
                      method: str, notes: str = "") -> Application:
    return Application(
        job_id=job_id,
        resume_path=str(resume_path),
        applied_at=datetime.utcnow().isoformat(),
        method=method,
        notes=notes,
    )
