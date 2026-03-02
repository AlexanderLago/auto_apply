# modules/applicator/easy_apply.py
# Browser automation for Greenhouse and Lever application forms.
# Uses Playwright (headless=False by default so you can monitor / intervene).
#
# SAFETY: actual form submission only happens when submit=True is passed.
#         Default is dry_run mode — fills the form but does NOT click Submit.
#
# Anti-detection:
#   - Random delays between every action (human-like pacing)
#   - Character-by-character typing with random inter-key delay
#   - Proxy rotation: new browser context per job, cycles through PROXY_LIST
#
# Usage:
#   with EasyApplyBot(submit=False) as bot:
#       app = bot.apply(job, job_id)
#
# Proxy setup (optional):
#   Add to .env:  PROXY_LIST=http://host:port,http://user:pass@host2:port
#   Free proxies are unreliable — residential rotating proxies work best.

from __future__ import annotations

import random
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

import config
from modules.tracker.models import Job, Application

log = config.get_logger(__name__)

# ── Timing constants (seconds) ─────────────────────────────────────────────────
_SHORT  = (0.4, 1.2)   # between field fills
_MEDIUM = (1.0, 2.5)   # after page loads / button clicks
_LONG   = (3.0, 6.0)   # between jobs
_TYPE_DELAY_MS = (45, 130)   # ms per character while typing


def _pause(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


# ── Proxy helpers ──────────────────────────────────────────────────────────────

def _parse_proxy(url: str) -> dict:
    """
    Convert a proxy URL string to the dict Playwright expects.
      http://host:port              -> {"server": "http://host:port"}
      http://user:pass@host:port   -> {"server": "...", "username": ..., "password": ...}
      socks5://host:port           -> {"server": "socks5://host:port"}
    """
    p = urlparse(url)
    server = f"{p.scheme}://{p.hostname}:{p.port}"
    result: dict = {"server": server}
    if p.username:
        result["username"] = p.username
    if p.password:
        result["password"] = p.password
    return result


class EasyApplyBot:
    def __init__(self, resume_path: Path = None, headless: bool = False,
                 submit: bool = False):
        self.resume_path  = Path(resume_path) if resume_path else None
        self.headless     = headless
        self.submit       = submit
        self._proxies     = config.PROXY_LIST   # list[str]
        self._proxy_idx   = random.randint(0, max(len(self._proxies) - 1, 0))
        self._pw_cm       = None
        self._pw          = None
        self._browser     = None

    # ── Context management ─────────────────────────────────────────────────────

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw_cm  = sync_playwright()
        self._pw     = self._pw_cm.__enter__()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        return self

    def __exit__(self, *_):
        if self._browser:
            self._browser.close()
        if self._pw_cm:
            self._pw_cm.__exit__(None, None, None)

    # ── Proxy rotation ─────────────────────────────────────────────────────────

    def _next_proxy(self) -> Optional[dict]:
        if not self._proxies:
            return None
        proxy_url = self._proxies[self._proxy_idx % len(self._proxies)]
        self._proxy_idx += 1
        log.info("Using proxy: %s", proxy_url.split("@")[-1])  # hide creds in log
        return _parse_proxy(proxy_url)

    def _new_page(self):
        """Open a fresh browser context (with rotated proxy) and return its page."""
        proxy = self._next_proxy()
        ctx_args = {"proxy": proxy} if proxy else {}
        # Spoof a realistic user-agent
        ctx_args["user_agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
        ctx_args["viewport"] = {"width": 1366, "height": 768}
        context = self._browser.new_context(**ctx_args)
        return context, context.new_page()

    # ── Public apply ───────────────────────────────────────────────────────────

    def apply(self, job: Job, job_id: int) -> Optional[Application]:
        log.info("Easy Apply [%s]: %s at %s (submit=%s)",
                 job.source, job.title, job.company, self.submit)
        context, page = self._new_page()
        try:
            ats = self._detect_ats(job)
            if ats == "greenhouse":
                result = self._apply_greenhouse(page, job, job_id)
            elif ats == "lever":
                result = self._apply_lever(page, job, job_id)
            else:
                log.warning("No Easy Apply handler for %s (url=%s)",
                            job.source, job.url[:60])
                result = None
        except Exception as e:
            log.error("Easy Apply failed for job %d: %s", job_id, e)
            result = None
        finally:
            context.close()
            _pause(*_LONG)   # human-like gap between jobs
        return result

    @staticmethod
    def _detect_ats(job: Job) -> str:
        if job.source in ("greenhouse", "lever"):
            return job.source
        url = (job.url or "").lower()
        if "greenhouse.io" in url:
            return "greenhouse"
        if "lever.co" in url:
            return "lever"
        return job.source

    # ── Greenhouse URL resolution ──────────────────────────────────────────────

    @staticmethod
    def _resolve_greenhouse_url(job: Job) -> str:
        """
        Some companies (Airbnb, Lyft) wrap Greenhouse behind custom career sites.
        The URL contains ?gh_jid=<id> which lets us construct the direct
        boards.greenhouse.io job URL, bypassing the custom wrapper.
        Direct Greenhouse URLs are returned unchanged (Apply button handles navigation).
        """
        parsed = urlparse(job.url)
        if "greenhouse.io" in parsed.netloc:
            # Already a direct Greenhouse URL — return as-is, Apply btn will navigate
            return job.url

        # Custom career site with gh_jid param → redirect to direct Greenhouse job page
        qs = parse_qs(parsed.query)
        gh_jid = (qs.get("gh_jid") or [None])[0]
        if gh_jid:
            board_token = job.company.lower().replace(" ", "").replace("-", "")[:30]
            url = f"https://boards.greenhouse.io/{board_token}/jobs/{gh_jid}"
            log.info("Resolved custom career URL to: %s", url)
            return url

        return job.url  # fallback — try as-is

    @staticmethod
    def _on_gh_form(page) -> bool:
        """Return True if the page already has Greenhouse form fields visible."""
        return page.locator("#first_name, #last_name, #email").count() > 0

    # ── Greenhouse ─────────────────────────────────────────────────────────────

    def _apply_greenhouse(self, page, job: Job, job_id: int) -> Optional[Application]:
        target_url = self._resolve_greenhouse_url(job)
        page.goto(target_url, wait_until="networkidle", timeout=30000)
        _pause(*_MEDIUM)

        # Click Apply button if still on description page (not the form yet)
        if not self._on_gh_form(page):
            apply_btn = page.locator(
                "a:has-text('Apply'), button:has-text('Apply'), "
                "a:has-text('Apply for this job'), button:has-text('Apply for this job'), "
                "a[href*='/apply'], button[data-test='apply-button']"
            ).first
            if apply_btn.count() > 0:
                _pause(*_SHORT)
                apply_btn.click()
                page.wait_for_load_state("networkidle", timeout=15000)
                _pause(*_MEDIUM)
                log.info("Clicked Apply for job %d", job_id)

        # Personal info — type character-by-character
        _human_type(page, "#first_name",    config.APPLICANT_FIRST_NAME)
        _pause(*_SHORT)
        _human_type(page, "#last_name",     config.APPLICANT_LAST_NAME)
        _pause(*_SHORT)
        _human_type(page, "#preferred_name", config.APPLICANT_FIRST_NAME)
        _pause(*_SHORT)
        _human_type(page, "#email",         config.APPLICANT_EMAIL)
        _pause(*_SHORT)

        # Country — plain text input; type value then Tab out to commit
        if page.locator("#country").count() > 0:
            page.locator("#country").first.click()
            _pause(0.3, 0.6)
            page.locator("#country").first.type("United States", delay=random.randint(*_TYPE_DELAY_MS))
            _pause(0.4, 0.8)
            page.keyboard.press("Tab")
            _pause(*_SHORT)

        _human_type(page, "#phone", config.APPLICANT_PHONE)
        _pause(*_SHORT)

        # Resume upload
        for sel in ("input[type='file']#resume",
                    "input[type='file'][id*='resume']",
                    "input[type='file'][name*='resume']",
                    "input[type='file']"):
            if page.locator(sel).count() > 0:
                if self.resume_path and self.resume_path.exists():
                    page.set_input_files(sel, str(self.resume_path))
                    _pause(*_SHORT)
                    log.info("Resume uploaded: %s", self.resume_path.name)
                break
        else:
            log.warning("No file input found for job %d", job_id)

        # Cover letter upload (txt file if available)
        if self.resume_path:
            cl_dir = config.ROOT_DIR / "resumes" / "cover_letters"
            slug = job.company.lower().replace(" ", "")[:20]
            cl_file = cl_dir / f"cover_letter_{slug}.txt"
            if not cl_file.exists():
                cl_file = next(cl_dir.glob("cover_letter_*.txt"), None) if cl_dir.exists() else None
            cl_sel = "input[type='file']#cover_letter, input[type='file'][id*='cover']"
            if cl_file and page.locator(cl_sel).count() > 0:
                page.set_input_files(cl_sel, str(cl_file))
                _pause(*_SHORT)
                log.info("Cover letter uploaded: %s", cl_file.name)

        # EEO / demographic dropdowns — select "Decline to self-identify"
        for select in page.locator("select").all():
            try:
                opts = select.locator("option").all_text_contents()
                decline = next((o for o in opts if "decline" in o.lower()), None)
                if decline:
                    _pause(*_SHORT)
                    select.select_option(label=decline)
            except Exception:
                pass

        if self.submit:
            _pause(*_MEDIUM)
            page.locator("input[type='submit'], button[type='submit']").first.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            log.info("Greenhouse submitted for job %d", job_id)
        else:
            log.info("Greenhouse filled (dry run) for job %d", job_id)

        return _make_application(job_id, self.resume_path, "easy_apply",
                                 notes="" if self.submit else "dry_run")

    # ── Lever ──────────────────────────────────────────────────────────────────

    def _apply_lever(self, page, job: Job, job_id: int) -> Optional[Application]:
        apply_url = job.url
        if "/apply" not in apply_url:
            apply_url = apply_url.rstrip("/") + "/apply"

        page.goto(apply_url, wait_until="networkidle", timeout=30000)
        _pause(*_MEDIUM)

        full_name = f"{config.APPLICANT_FIRST_NAME} {config.APPLICANT_LAST_NAME}".strip()
        _human_type(page, "input[name='name']",  full_name)
        _pause(*_SHORT)
        _human_type(page, "input[name='email']", config.APPLICANT_EMAIL)
        _pause(*_SHORT)
        _human_type(page, "input[name='phone']", config.APPLICANT_PHONE)
        _pause(*_SHORT)

        if page.locator("input[type='file']").count() > 0:
            if self.resume_path and self.resume_path.exists():
                page.set_input_files("input[type='file']", str(self.resume_path))
                _pause(*_SHORT)
                log.info("Resume uploaded: %s", self.resume_path.name)

        if self.submit:
            _pause(*_MEDIUM)
            page.locator("button[type='submit'], input[type='submit']").first.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            log.info("Lever submitted for job %d", job_id)
        else:
            log.info("Lever filled (dry run) for job %d", job_id)

        return _make_application(job_id, self.resume_path, "easy_apply",
                                 notes="" if self.submit else "dry_run")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _human_type(page, selector: str, value: str) -> None:
    """Type into a field character-by-character with random inter-key delay."""
    if not value:
        return
    try:
        loc = page.locator(selector)
        if loc.count() == 0:
            return
        loc.first.click()
        _pause(0.1, 0.4)
        delay_ms = random.randint(*_TYPE_DELAY_MS)
        loc.first.type(value, delay=delay_ms)
    except Exception as e:
        log.debug("Could not type into %s: %s", selector, e)


def _make_application(job_id: int, resume_path: Optional[Path],
                      method: str, notes: str = "") -> Application:
    return Application(
        job_id=job_id,
        resume_path=str(resume_path) if resume_path else "",
        applied_at=datetime.utcnow().isoformat(),
        method=method,
        notes=notes,
    )
