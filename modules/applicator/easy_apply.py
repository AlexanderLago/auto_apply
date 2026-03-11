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
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

import config
from modules.tracker.models import Job, Application

log = config.get_logger(__name__)


# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class ApplyOutcome:
    """Outcome of a single job application attempt."""
    job_id:  int
    company: str
    title:   str
    # status values: "submitted" | "dry_run" | "captcha" | "no_handler" | "error"
    status:  str
    error:   str = ""
    app:     Optional[Application] = None
    resume_path: str = ""
    cover_letter_path: str = ""

# ── Timing constants (seconds) ─────────────────────────────────────────────────
_SHORT  = (0.4, 1.2)   # between field fills
_MEDIUM = (1.0, 2.5)   # after page loads / button clicks
_LONG   = (3.0, 6.0)   # between jobs
_TYPE_DELAY_MS = (45, 130)   # ms per character while typing


def _pause(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


# ── Human-like movement helpers ────────────────────────────────────────────────

def _human_mouse_move(page, start_x: float, start_y: float, end_x: float, end_y: float, 
                      duration_ms: float = None) -> None:
    """
    Move mouse in a human-like curved path with variable speed.
    Uses bezier curve with random control points for natural movement.
    """
    import math
    
    if duration_ms is None:
        # Humans move mouse at ~200-800ms for typical distances
        distance = math.sqrt((end_x - start_x)**2 + (end_y - start_y)**2)
        duration_ms = random.uniform(200, 600) * (distance / 500)  # Scale by distance
    
    # Generate bezier curve control points (adds natural curve)
    cp1_x = start_x + (end_x - start_x) * random.uniform(0.3, 0.7) + random.uniform(-50, 50)
    cp1_y = start_y + (end_y - start_y) * random.uniform(0.3, 0.7) + random.uniform(-50, 50)
    cp2_x = start_x + (end_x - start_x) * random.uniform(0.3, 0.7) + random.uniform(-50, 50)
    cp2_y = start_y + (end_y - start_y) * random.uniform(0.3, 0.7) + random.uniform(-50, 50)
    
    # Number of steps (humans have micro-adjustments)
    steps = int(duration_ms / random.uniform(8, 20))  # ~50-125Hz sampling
    steps = max(steps, 5)  # Minimum steps
    
    for i in range(steps + 1):
        t = i / steps
        # Add slight randomness to timing (humans aren't perfectly linear)
        t += random.uniform(-0.02, 0.02)
        t = max(0, min(1, t))
        
        # Cubic bezier interpolation
        x = ((1-t)**3 * start_x + 
             3*(1-t)**2*t * cp1_x + 
             3*(1-t)*t**2 * cp2_x + 
             t**3 * end_x)
        y = ((1-t)**3 * start_y + 
             3*(1-t)**2*t * cp1_y + 
             3*(1-t)*t**2 * cp2_y + 
             t**3 * end_y)
        
        # Add micro-jitter (human hand tremor)
        x += random.uniform(-0.5, 0.5)
        y += random.uniform(-0.5, 0.5)
        
        try:
            page.mouse.move(x, y)
        except Exception:
            pass  # Ignore if element scrolled out of view
        
        # Variable delay between steps (humans accelerate/decelerate)
        if i < steps:
            page.wait_for_timeout(random.uniform(2, 15))


def _human_click(page, x: float, y: float, click_type: str = "left") -> None:
    """
    Perform a human-like click with natural movement and timing.
    """
    # Move to position with human-like trajectory
    _human_mouse_move(page, 0, 0, x, y)
    
    # Random pre-click pause (humans hesitate slightly)
    page.wait_for_timeout(random.uniform(50, 150))
    
    # Click with human timing
    if click_type == "left":
        page.mouse.down()
        page.wait_for_timeout(random.uniform(80, 200))  # Hold time
        page.mouse.up()
    elif click_type == "double":
        page.mouse.dblclick(x, y)
    elif click_type == "right":
        page.mouse.click(x, y, button="right")
    
    # Post-click pause
    page.wait_for_timeout(random.uniform(30, 100))


def _human_scroll(page, direction: str = "down", amount: int = None) -> None:
    """
    Perform human-like scroll with variable speed and micro-pauses.
    """
    if amount is None:
        amount = random.randint(100, 400)  # Typical scroll amount
    
    if direction == "down":
        amount = -abs(amount)
    else:
        amount = abs(amount)
    
    # Humans scroll in chunks with pauses
    chunks = random.randint(2, 5)
    scroll_per_chunk = amount // chunks
    
    for i in range(chunks):
        page.evaluate(f"window.scrollBy(0, {scroll_per_chunk})")
        page.wait_for_timeout(random.uniform(50, 200))  # Pause between scroll chunks
    
    # Occasional scroll correction (humans often overscroll/underscroll)
    if random.random() < 0.3:
        correction = random.randint(-30, 30)
        page.evaluate(f"window.scrollBy(0, {correction})")
        page.wait_for_timeout(random.uniform(30, 100))


def _human_type(page, selector: str, text: str, error_rate: float = 0.02) -> None:
    """
    Type text with human-like variations: variable speed, occasional errors/corrections.
    """
    if not text:
        return
    
    try:
        element = page.locator(selector).first
        element.scroll_into_view_if_needed()
        page.wait_for_timeout(random.uniform(100, 300))  # Pre-type pause
        
        # Click to focus with human-like movement
        box = element.bounding_box()
        if box:
            click_x = box['x'] + box['width'] * random.uniform(0.3, 0.7)
            click_y = box['y'] + box['height'] * random.uniform(0.3, 0.7)
            _human_click(page, click_x, click_y)
        
        # Clear existing text (humans select all)
        if random.random() < 0.5:
            page.keyboard.press("Control+A")
            page.wait_for_timeout(random.uniform(50, 150))
            page.keyboard.press("Delete")
            page.wait_for_timeout(random.uniform(50, 150))
        else:
            element.fill("")
        
        page.wait_for_timeout(random.uniform(100, 300))  # Pause before typing
        
        # Type character by character with variable speed
        for i, char in enumerate(text):
            # Occasional typo (humans make mistakes)
            if error_rate > 0 and random.random() < error_rate:
                # Type wrong char, backspace, retype
                wrong_chars = "qwertyuiopasdfghjklzxcvbnm1234567890"
                wrong_char = random.choice(wrong_chars)
                page.keyboard.type(wrong_char, delay=random.uniform(30, 80))
                page.wait_for_timeout(random.uniform(100, 300))  # Realize mistake
                page.keyboard.press("Backspace")
                page.wait_for_timeout(random.uniform(80, 200))
            
            # Variable typing speed (humans speed up/slow down)
            base_delay = random.uniform(40, 120)
            # Slow down for special chars, capitals
            if char in "!@#$%^&*()_+-={}[]|\\:;\"'<>?,./":
                base_delay *= random.uniform(1.5, 2.5)
            elif char.isupper():
                base_delay *= random.uniform(1.2, 1.8)
            # Speed up for common letter sequences
            if i > 0 and text[i-1:i+1].lower() in ['th', 'he', 'in', 'er', 'an', 'on']:
                base_delay *= random.uniform(0.6, 0.8)
            
            page.keyboard.type(char, delay=base_delay)
            
            # Random micro-pauses between words
            if char == ' ':
                page.wait_for_timeout(random.uniform(100, 400))
            # Occasional longer pause mid-typing (human thinking)
            elif random.random() < 0.05:
                page.wait_for_timeout(random.uniform(200, 600))
        
        # Post-type pause
        page.wait_for_timeout(random.uniform(100, 300))
        
    except Exception as e:
        log.debug("Human type failed for %s: %s", selector, e)
        # Fallback to regular fill
        try:
            page.locator(selector).first.fill(text)
        except Exception:
            pass


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
        # Patchright is a drop-in replacement for playwright-python that patches
        # out the Runtime.Enable CDP detection vector.  Standard Playwright sends
        # Runtime.Enable at startup which creates a detectable side-effect
        # (window.__playwright__binding__); Greenhouse detects this and
        # intentionally skips calling hydrateRoot(), leaving all React Select
        # dropdowns as non-interactive server-rendered HTML.
        # Patchright eliminates this signal so React hydrates normally.
        try:
            from patchright.sync_api import sync_playwright
            log.info("Using Patchright (patched Playwright — bypasses CDP detection)")
        except ImportError:
            from playwright.sync_api import sync_playwright
            log.warning("patchright not installed — falling back to standard playwright")
        self._pw_cm  = sync_playwright()
        self._pw     = self._pw_cm.__enter__()
        launch_args = {
            'headless': self.headless,
            'args': ['--disable-blink-features=AutomationControlled'],
        }
        self._browser = self._pw.chromium.launch(**launch_args)
        return self

    def __exit__(self, *_):
        try:
            if self._browser:
                # Give browser time to finish any pending operations
                import time
                time.sleep(0.5)
                self._browser.close()
        except Exception:
            pass  # Ignore close errors
        try:
            if self._pw_cm:
                self._pw_cm.__exit__(None, None, None)
        except Exception:
            pass  # Ignore cleanup errors

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
        page = context.new_page()
        # Cap individual actions at 8 s; navigations (goto/wait_for_load) at 60 s
        page.set_default_timeout(8000)
        page.set_default_navigation_timeout(60000)
        # Log browser JS errors and interesting network requests for debugging
        page.on('console', lambda msg: log.warning(
            "BROWSER %s: %.200s", msg.type.upper(), msg.text)
            if msg.type == 'error' else None)
        page.on('pageerror', lambda exc: log.error("BROWSER PAGEERROR: %.300s", str(exc)))
        page.on('response', lambda resp: log.info(
            "NET %d  %s", resp.status, resp.url[-80:])
            if resp.url.endswith(('.js', '.mjs')) else None)
        # Patchright handles detection evasion at the CDP level (patches out
        # Runtime.Enable, __playwright__ globals, etc.).  Adding playwright_stealth
        # on top conflicts with Patchright's internal route injection and causes
        # page.goto to hang indefinitely.  Skip stealth when Patchright is active.
        import os as _os
        _using_patchright = 'patchright' in type(page).__module__
        if not _using_patchright and _os.getenv("SKIP_STEALTH", "").lower() != "true":
            try:
                from playwright_stealth import stealth_sync, StealthConfig
                stealth_sync(page, StealthConfig(iframe_content_window=False))
                log.debug("playwright_stealth applied (fallback Playwright mode)")
            except ImportError:
                log.debug("playwright-stealth not installed — skipping stealth patch")
        elif _os.getenv("SKIP_STEALTH", "").lower() == "true":
            log.info("Stealth patch DISABLED (SKIP_STEALTH=true)")
        return context, page

    # ── Public apply ───────────────────────────────────────────────────────────

    def apply(self, job: Job, job_id: int) -> ApplyOutcome:
        log.info("Easy Apply [%s]: %s at %s (submit=%s)",
                 job.source, job.title, job.company, self.submit)
        context, page = self._new_page()
        outcome = ApplyOutcome(job_id=job_id, company=job.company,
                               title=job.title, status="error")
        try:
            ats = self._detect_ats(job)
            if ats == "greenhouse":
                result = self._apply_greenhouse(page, job, job_id)
                # Check if result is an ApplyOutcome (error case) or Application (success)
                if isinstance(result, ApplyOutcome):
                    return result  # Return the error outcome directly
                app = result
            elif ats == "lever":
                result = self._apply_lever(page, job, job_id)
                if isinstance(result, ApplyOutcome):
                    return result
                app = result
            elif ats == "ashby":
                result = self._apply_ashby(page, job, job_id)
                if isinstance(result, ApplyOutcome):
                    return result
                app = result
            else:
                log.warning("No Easy Apply handler for %s (url=%s)",
                            job.source, job.url[:60])
                outcome.status = "no_handler"
                return outcome

            if app is None:
                # _apply_* returns None only for captcha skip
                outcome.status = "captcha"
            else:
                outcome.status = "submitted" if self.submit else "dry_run"
                outcome.app = app

        except Exception as e:
            log.error("Easy Apply failed for job %d — skipping: %s", job_id, e)
            outcome.status = "error"
            outcome.error  = str(e)
        finally:
            context.close()
            _pause(*_LONG)   # human-like gap between jobs
        return outcome

    @staticmethod
    def _captcha_detected(page) -> bool:
        """Return True if a CAPTCHA widget is visible on the page."""
        selectors = (
            "iframe[src*='recaptcha']",
            "iframe[src*='hcaptcha']",
            "iframe[src*='challenges.cloudflare.com']",
            ".g-recaptcha",
            "[class*='captcha']",
            "[id*='captcha']",
            "[data-sitekey]",
        )
        try:
            for sel in selectors:
                if page.locator(sel).count() > 0:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _detect_ats(job: Job) -> str:
        if job.source in ("greenhouse", "lever", "ashby"):
            return job.source
        url = (job.url or "").lower()
        if "greenhouse.io" in url:
            return "greenhouse"
        if "lever.co" in url:
            return "lever"
        if "ashby.com" in url or "ashbyhq.com" in url:
            return "ashby"
        return job.source

    # ── Greenhouse URL resolution ──────────────────────────────────────────────

    @staticmethod
    def _resolve_greenhouse_url(job: Job) -> str:
        """
        Companies like Airbnb, Lyft, Stripe, Asana wrap Greenhouse behind custom
        career sites. The URL contains ?gh_jid=<id> which lets us construct the
        direct job-boards.greenhouse.io APPLY URL, bypassing any redirect.
        Direct Greenhouse URLs are returned unchanged.
        """
        parsed = urlparse(job.url)
        if "greenhouse.io" in parsed.netloc:
            return job.url

        # Custom career site with gh_jid → go directly to the apply form
        qs = parse_qs(parsed.query)
        gh_jid = (qs.get("gh_jid") or [None])[0]
        if gh_jid:
            board_token = job.company.lower().replace(" ", "").replace("-", "")[:30]
            # /apply suffix routes directly to the form, bypassing career site redirects
            url = f"https://job-boards.greenhouse.io/{board_token}/jobs/{gh_jid}/apply"
            log.info("Resolved %s -> %s", job.url[:50], url)
            return url

        return job.url  # fallback — try as-is

    # ── Greenhouse ─────────────────────────────────────────────────────────────

    def _apply_greenhouse(self, page, job: Job, job_id: int) -> Optional[Application]:
        target_url = self._resolve_greenhouse_url(job)
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        _pause(*_MEDIUM)

        if self._captcha_detected(page):
            log.warning("CAPTCHA detected for job %d — skipping", job_id)
            return None

        # Check for expired/404 job pages
        page_text = page.evaluate("document.body.innerText.toLowerCase()") or ""
        if any(s in page_text for s in ["page not found", "job not found", "posting not found",
                                         "no longer available", "position has been filled",
                                         "job board you are looking"]):
            log.warning("Job %d appears expired/removed — skipping", job_id)
            from modules.tracker.database import update_job_status
            update_job_status(job_id, "ignored")
            return None

        # Detect form variant by TARGET URL (before any redirects) and current URL.
        # Use target_url so custom career sites (Airbnb, Lyft, Stripe, etc.) that
        # redirect don't accidentally fall into the classic form path.
        current_url = page.url
        if ("job-boards.greenhouse.io" in target_url
                or "job-boards.greenhouse.io" in current_url):
            self._fill_gh_new_form(page, job, job_id)
        else:
            self._fill_gh_classic_form(page, job, job_id)

        if self.submit:
            _pause(*_MEDIUM)

            # CRITICAL: Pre-submit validation - check for errors before clicking
            # Only check for actual submission-blocking errors, not generic "required" labels
            error_check = page.evaluate("""() => {
                const errors = [];

                // Check for red error styling (actual validation errors, not just "required" labels)
                const redElements = document.querySelectorAll('[style*="red"], [style*="error"], .error-text, .field_error, .error-message');
                
                // Only count as error if element has actual error content (not just "required" label)
                for (const el of redElements) {
                    const text = el.textContent.trim().toLowerCase();
                    // Skip if it's just a label with asterisk
                    if (text.length > 3 && !text.includes('*')) {
                        errors.push('error-styled: ' + text.slice(0, 30));
                    }
                }

                // Check for specific error messages (not generic "required" labels)
                const text = document.body.innerText.toLowerCase();
                const specificErrors = [
                    'please correct', 'must be filled',
                    'invalid email', 'invalid phone',
                    'complete this field', 'choose one',
                    'this field is required',  // More specific than just "required"
                    'select a country'
                ];

                for (const pattern of specificErrors) {
                    if (text.includes(pattern)) {
                        errors.push(pattern);
                    }
                }

                return {
                    hasErrors: errors.length > 0,
                    errors: errors.slice(0, 5),
                    errorCount: errors.length
                };
            }""")

            if error_check['hasErrors']:
                log.error("  [VALIDATION ERROR] Form has %d errors: %s",
                         error_check['errorCount'], error_check['errors'])
                log.warning("  [FAILED] Not submitting form with validation errors")
                return ApplyOutcome(
                    job_id=job_id,
                    company=job.company,
                    title=job.title,
                    status="error",
                    error=f"Form validation errors: {', '.join(error_check['errors'])}",
                    resume_path=str(self.resume_path) if self.resume_path else "",
                    cover_letter_path=""
                )

            # Pre-submit: Check for any unfilled required fields and fill defaults
            try:
                unfilled_check = page.evaluate("""() => {
                    const unfilled = [];
                    // Check all required text inputs
                    document.querySelectorAll('input[required][type="text"], input[required][type="email"], input[required][type="tel"]').forEach(el => {
                        if (!el.value || el.value.trim() === '') {
                            const label = el.closest('[class*="field"], [class*="question"]')?.textContent?.slice(0, 50) || el.name || el.id || 'Field';
                            unfilled.push(label);
                        }
                    });
                    // Check React Select dropdowns — only report unfilled if the
                    // placeholder "Select..." is STILL showing (no single-value selected).
                    // React Select stores selected value in state, NOT in input.value,
                    // so we must check single-value div presence, not input.value.
                    document.querySelectorAll('[class*="select__control"]').forEach(ctrl => {
                        const placeholder = ctrl.querySelector('[class*="placeholder"]');
                        const singleValue = ctrl.querySelector('[class*="single-value"]');
                        const multiValue  = ctrl.querySelector('[class*="multi-value"]');
                        // Only unfilled if placeholder is visible AND no selected value
                        if (placeholder && !singleValue && !multiValue) {
                            const placeholderText = placeholder.textContent.trim();
                            if (placeholderText === 'Select...') {
                                // Find label from parent question container
                                let node = ctrl.parentElement;
                                for (let i = 0; i < 6 && node; i++, node = node.parentElement) {
                                    const t = node.textContent.trim().replace(/\\s+/g,' ');
                                    if (t.length > 5 && t.length < 100) {
                                        unfilled.push(t.slice(0, 50) + ' (dropdown)');
                                        break;
                                    }
                                }
                            }
                        }
                    });
                    return unfilled.slice(0, 10);
                }""")
                if unfilled_check:
                    log.warning("  [AUTO-FILL] %d required fields unfilled: %s", len(unfilled_check), unfilled_check[:5])
                    # Try to fill dropdowns with "Decline" or first option
                    for i in range(len(unfilled_check)):
                        if 'dropdown' in unfilled_check[i].lower():
                            try:
                                page.keyboard.press('Tab')
                                page.wait_for_timeout(200)
                                page.keyboard.press('ArrowDown')
                                page.wait_for_timeout(300)
                                page.keyboard.press('Enter')
                                page.wait_for_timeout(200)
                            except Exception:
                                pass
            except Exception as _uf:
                log.debug("  Unfilled check failed: %s", _uf)
            
            # Scroll to bottom so the submit button is in the viewport
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(600)

            # Try multiple submit button selectors — scroll into view before clicking
            submit_clicked = False
            for sel in (
                "button:has-text('Submit Application')",
                "button:has-text('Submit')",
                "input[value*='Submit' i]",
                "input[type='submit'], button[type='submit']",
                "button[class*='submit'], input[class*='submit']",
                "[data-testid*='submit']",
                "[data-qa='btn-submit']",
            ):
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0:
                        btn.scroll_into_view_if_needed()
                        page.wait_for_timeout(300)
                        if btn.is_visible(timeout=3000):
                            btn.click(timeout=5000)
                            submit_clicked = True
                            log.info("Submit clicked via: %s", sel)
                            break
                except Exception:
                    continue

            if not submit_clicked:
                log.warning("Submit button not found by selector, trying JS click on last visible button")
                try:
                    result = page.evaluate("""() => {
                        const btns = [...document.querySelectorAll('button, input[type="submit"]')];
                        const visible = btns.filter(b => {
                            const r = b.getBoundingClientRect();
                            return r.width > 0 && r.height > 0;
                        });
                        const last = visible[visible.length - 1];
                        if (last) { last.click(); return last.textContent || last.value || 'clicked'; }
                        return 'not found';
                    }""")
                    log.info("JS button click result: %s", result)
                    submit_clicked = result != 'not found'
                except Exception as _js:
                    log.debug("JS click failed: %s", _js)

            if not submit_clicked:
                log.warning("No submit button found at all")

            # Record time of submit click so we only accept emails arriving after it
            import time as _time
            _submit_time = _time.time()

            # ── Email verification code (Greenhouse anti-bot check) ────────────
            # After clicking submit, Greenhouse may show an 8-character security
            # code prompt. Detect it, fetch the code from Gmail, enter it, resubmit.
            try:
                page.wait_for_timeout(2000)
                needs_code = page.evaluate("""() => {
                    const text = document.body.innerText.toLowerCase();
                    return text.includes('verification code') ||
                           text.includes('security code') ||
                           text.includes('confirm you') ||
                           text.includes('enter the') && text.includes('code');
                }""")
                if needs_code:
                    log.info("  Email verification code required — polling Gmail...")
                    from modules.utils.email_reader import get_verification_code
                    code = get_verification_code(
                        keywords=["greenhouse", job.company.lower(), "verify", "security code", "verification code"],
                        code_pattern=r"\b(?=(?:[A-Za-z0-9]*\d){2})[A-Za-z0-9]{6,8}\b",
                        timeout=90,
                        since_timestamp=_submit_time,  # only accept fresh codes
                        recipient_email=config.APPLICANT_EMAIL,  # filter by applicant email
                    )
                    if code:
                        code = code.strip()  # preserve case — Greenhouse codes are case-sensitive
                        log.info("  Got verification code: %s — entering into form", code)
                        # Find the code input boxes and type the code
                        # Greenhouse uses either one input or 8 separate single-char inputs
                        code_inputs = page.locator('input[maxlength="1"], input[data-testid*="code"], input[name*="code"], input[aria-label*="code" i]')
                        if code_inputs.count() >= len(code):
                            # 8 separate single-char boxes
                            for idx, ch in enumerate(code):
                                code_inputs.nth(idx).click()
                                page.keyboard.type(ch)
                                page.wait_for_timeout(100)
                        else:
                            # Single input field
                            single = page.locator('input[type="text"]:visible, input[type="tel"]:visible').last
                            if single.count() > 0:
                                single.click()
                                page.keyboard.type(code)
                        page.wait_for_timeout(500)
                        # Click submit again
                        for sel in ("button:has-text('Submit application')", "button:has-text('Submit')", "input[type='submit']"):
                            try:
                                btn = page.locator(sel).first
                                if btn.count() > 0 and btn.is_visible(timeout=2000):
                                    btn.click(timeout=5000)
                                    log.info("  Re-submitted after entering code")
                                    break
                            except Exception:
                                continue
                    else:
                        log.warning("  Could not get verification code from Gmail within 90s")
            except Exception as _ev:
                log.debug("  Email verification step failed: %s", _ev)

            # Wait for submission to complete
            page.wait_for_load_state("networkidle", timeout=20000)
            
            # CRITICAL: Verify submission actually succeeded
            submission_verified = False
            try:
                page.wait_for_timeout(5000)  # Wait for redirect/settle
                
                # Take screenshot BEFORE checking (preserves state)
                import os
                ss_dir = config.ROOT_DIR / "logs" / "screenshots"
                ss_dir.mkdir(parents=True, exist_ok=True)
                ss_path = ss_dir / f"submission_{job_id}_{datetime.now().strftime('%H%M%S')}.png"
                try:
                    page.screenshot(path=str(ss_path), full_page=False)
                    log.info("  Screenshot saved: %s", ss_path.name)
                except Exception as ss_err:
                    log.debug("  Screenshot failed: %s", ss_err)
                
                # Check for confirmation indicators
                verification = page.evaluate("""() => {
                    const text = document.body.innerText.toLowerCase();
                    const title = document.title.toLowerCase();
                    const url = window.location.href.toLowerCase();
                    const combined = text + ' ' + title + ' ' + url;
                    
                    // Positive indicators
                    const positives = [
                        'thank you', 'thankyou', 'thanks for',
                        'application submitted', 'successfully applied',
                        'confirmation', 'application received',
                        'we have received', 'your application',
                        'next steps', 'what to expect'
                    ];
                    
                    // Negative indicators — specific error/incomplete phrases
                    const negatives = [
                        'please correct the following',
                        'please fix the following',
                        'there was an error',
                        'something went wrong',
                        'unable to submit',
                        'try again later',
                        'submission failed',
                        // Still on verification code screen — not submitted yet
                        'security code',
                        'verification code was sent',
                        "confirm you're a human",
                        'enter the 8',
                        // Validation errors still present
                        'this field is required',
                        'select a country',
                        'please select'
                    ];

                    const hasPositive = positives.some(p => combined.includes(p));
                    const hasNegative = negatives.some(n => combined.includes(n));
                    
                    return {
                        verified: hasPositive && !hasNegative,
                        hasPositive,
                        hasNegative,
                        title: document.title.slice(0, 150),
                        url: window.location.href.slice(0, 300),
                        textPreview: text.slice(0, 500).replace(/\s+/g, ' ')
                    };
                }""")
                
                if verification['verified']:
                    submission_verified = True
                    log.info("  [OK] SUBMISSION VERIFIED: %s", verification['title'])
                elif verification['hasNegative']:
                    log.error("  [FAIL] SUBMISSION FAILED - Error detected: %s", verification['textPreview'][:200])
                else:
                    log.warning("  [UNCERTAIN] SUBMISSION UNCERTAIN - URL: %s", verification['url'][:150])
                    log.debug("  Page text: %s", verification['textPreview'][:300])
                    
            except Exception as e:
                log.error("  [ERROR] Verification check failed: %s", e)
                submission_verified = False
            
            # Only count as submitted if verified
            if submission_verified:
                log.info("  [SUBMITTED] Greenhouse SUBMITTED & VERIFIED for job %d", job_id)
                return _make_application(job_id, self.resume_path, "easy_apply", notes="submitted")
            else:
                log.warning("  [FAILED] Greenhouse submit clicked but NOT VERIFIED for job %d", job_id)
                # Return error outcome instead of counting as submitted
                return ApplyOutcome(
                    job_id=job_id,
                    company=job.company,
                    title=job.title,
                    status="error",
                    error="Form submission not verified - may have validation errors",
                    resume_path=str(self.resume_path) if self.resume_path else "",
                    cover_letter_path=""
                )
        else:
            log.info("Greenhouse filled (dry run) for job %d", job_id)

        return _make_application(job_id, self.resume_path, "easy_apply",
                                 notes="" if self.submit else "dry_run")

    def _fill_gh_new_form(self, page, job: Job, job_id: int) -> None:
        """
        Fill new-style job-boards.greenhouse.io forms.
        Selectors derived directly from playwright codegen recording.
        """

        # ── Click Apply if on description page ────────────────────────────────
        try:
            btn = page.get_by_label("Apply", exact=True)
            if btn.count() == 0:
                btn = page.get_by_role("link", name="Apply").first
            if btn.count() > 0 and btn.first.is_visible():
                _pause(*_SHORT)
                btn.first.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    page.wait_for_timeout(2000)  # SPA fallback
                _pause(*_MEDIUM)
                log.info("Clicked Apply button for job %d", job_id)
        except Exception as e:
            log.warning("Apply button click error: %s", e)

        # ── Personal info ──────────────────────────────────────────────────────
        try:
            page.get_by_label("First Name", exact=True).fill(config.APPLICANT_FIRST_NAME)
        except Exception: pass
        try:
            page.get_by_label("Last Name").click()
            page.get_by_label("Last Name").fill(config.APPLICANT_LAST_NAME)
        except Exception: pass
        for _pref_label in ("Preferred First Name", "Preferred Name", "Nickname", "Goes By"):
            try:
                fld = page.get_by_label(_pref_label)
                if fld.count() > 0 and fld.first.is_visible(timeout=1000):
                    fld.first.click()
                    fld.first.fill(config.APPLICANT_PREFERRED_NAME)
                    break
            except Exception:
                continue
        try:
            page.get_by_label("Email").click()
            page.get_by_label("Email").fill(config.APPLICANT_EMAIL)
        except Exception: pass

        # ── Phone: Select country then fill number ─────────────────────────────
        try:
            # Wait for phone field to be visible
            phone_field = page.get_by_label("Phone")
            phone_field.wait_for(state='visible', timeout=5000)
            page.wait_for_timeout(500)

            country_set = False

            # ── Method 1: Direct ITI widget manipulation (most reliable) ───────
            # The iti widget stores country in data attributes and hidden inputs
            # We directly set the country code and fire all necessary events
            if not country_set:
                try:
                    result = page.evaluate("""() => {
                        // Find all tel inputs with iti widget
                        const telInputs = document.querySelectorAll('input[type="tel"]');
                        
                        for (const input of telInputs) {
                            // Check if this input has iti widget attached
                            const iti = window.intlTelInputGlobals && window.intlTelInputGlobals.getInstance(input);
                            
                            if (iti) {
                                // Method 1a: Use official ITI API
                                iti.setCountry('us');
                                
                                // Fire all events that Greenhouse/React might listen for
                                input.dispatchEvent(new Event('countrychange', { bubbles: true, cancelable: true }));
                                input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                                input.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                                input.dispatchEvent(new CustomEvent('intlTelInput:countrychange', { bubbles: true }));
                                
                                // Also update the hidden input if it exists
                                const hiddenInput = input.parentElement.querySelector('.iti__hidden-input');
                                if (hiddenInput) {
                                    hiddenInput.value = 'us';
                                    hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                                
                                return 'iti_api_success';
                            }
                            
                            // Method 1b: Direct DOM manipulation (no iti instance)
                            // Look for the flag container and country code elements
                            const flagContainer = input.parentElement.querySelector('.iti__flag-container');
                            const selectedFlag = input.parentElement.querySelector('.iti__selected-flag');
                            const selectedCountry = input.parentElement.querySelector('.iti__selected-country');
                            
                            if (selectedFlag || selectedCountry) {
                                // Update the country code directly in the DOM
                                const countryElement = selectedCountry || selectedFlag;
                                if (countryElement) {
                                    // Remove all country classes
                                    countryElement.className = countryElement.className.replace(/iti__[^ ]*/g, '');
                                    // Add US flag class
                                    countryElement.classList.add('iti__flag', 'iti__us');
                                    
                                    // Update data attributes
                                    countryElement.setAttribute('data-country-code', 'us');
                                    
                                    // Update title/aria labels
                                    countryElement.setAttribute('title', 'United States');
                                    countryElement.setAttribute('aria-label', 'United States');
                                    
                                    // Fire events
                                    input.dispatchEvent(new Event('countrychange', { bubbles: true }));
                                    input.dispatchEvent(new Event('change', { bubbles: true }));
                                    
                                    return 'direct_dom_success';
                                }
                            }
                        }
                        
                        return 'no_iti_widget_found';
                    }""")
                    
                    if result in ('iti_api_success', 'direct_dom_success'):
                        log.info("Phone country set via: %s", result)
                        country_set = True
                        page.wait_for_timeout(300)
                    else:
                        log.debug("ITI widget method returned: %s", result)
                        
                except Exception as _iti:
                    log.debug("ITI direct method failed: %s", _iti)

            # ── Method 2: Hidden select input (iti injects this) ───────────────
            if not country_set:
                try:
                    result = page.evaluate("""() => {
                        // Look for iti's hidden select input
                        const hiddenSelects = document.querySelectorAll('.iti__hidden-input, select.iti__country-list');
                        
                        for (const sel of hiddenSelects) {
                            if (sel.tagName === 'SELECT') {
                                sel.value = 'us';
                                sel.dispatchEvent(new Event('change', { bubbles: true }));
                                sel.dispatchEvent(new Event('input', { bubbles: true }));
                                return 'hidden_select_updated';
                            }
                        }
                        
                        // Fallback: any select with US options
                        for (const s of document.querySelectorAll('select')) {
                            const options = [...s.options];
                            const hasUS = options.some(o => o.value === 'us' || o.text.includes('United States'));
                            if (hasUS && !s.disabled) {
                                s.value = 'us';
                                s.dispatchEvent(new Event('change', { bubbles: true }));
                                return 'generic_select_updated';
                            }
                        }
                        
                        return 'no_select_found';
                    }""")
                    
                    if result in ('hidden_select_updated', 'generic_select_updated'):
                        log.info("Phone country set via: %s", result)
                        country_set = True
                        page.wait_for_timeout(300)
                        
                except Exception as _sel:
                    log.debug("Hidden select method failed: %s", _sel)

            # ── Method 3: Click dropdown and select (visual method) ────────────
            if not country_set:
                try:
                    # Find the country selector button (flag button)
                    country_btn = page.locator('.iti__selected-flag, .iti__flag-container button').first
                    
                    if country_btn.count() > 0:
                        # Scroll into view and click
                        country_btn.scroll_into_view_if_needed()
                        country_btn.click()
                        page.wait_for_timeout(600)  # Wait for dropdown to open
                        
                        # Try to find and click "United States" option
                        # ITI uses li elements with data-country-code attribute
                        us_option = page.locator('[data-country-code="us"], .iti__country:has-text("United States")').first
                        
                        if us_option.count() > 0:
                            us_option.scroll_into_view_if_needed()
                            us_option.click()
                            page.wait_for_timeout(400)
                            log.info("Phone country set via dropdown click")
                            country_set = True
                        else:
                            # Try keyboard navigation (US is usually first)
                            page.keyboard.press("ArrowDown")
                            page.wait_for_timeout(100)
                            page.keyboard.press("Enter")
                            page.wait_for_timeout(200)
                            log.info("Phone country set via keyboard")
                            country_set = True
                            
                except Exception as _click:
                    log.debug("Dropdown click method failed: %s", _click)

            # ── Method 4: React Select combobox (newer GH forms) ───────────────
            if not country_set:
                try:
                    # New GH forms use React Select for country
                    combobox = page.locator('input[role="combobox"][aria-label*="country" i]').first
                    
                    if combobox.count() > 0:
                        combobox.click()
                        page.wait_for_timeout(400)
                        
                        # Type "united" to filter
                        combobox.fill("united")
                        page.wait_for_timeout(300)
                        
                        # Press Enter to select first match
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(200)
                        log.info("Phone country set via React Select")
                        country_set = True
                        
                except Exception as _react:
                    log.debug("React Select method failed: %s", _react)

            # Final check and warning
            if not country_set:
                log.warning("Could not set phone country — form may show 'Select a country' error")
                # Take screenshot for debugging
                try:
                    ss_dir = config.ROOT_DIR / "logs" / "screenshots"
                    ss_dir.mkdir(parents=True, exist_ok=True)
                    ss_path = ss_dir / f"phone_country_{int(time.time())}.png"
                    page.screenshot(path=str(ss_path))
                    log.info("Screenshot saved: %s", ss_path.name)
                except Exception:
                    pass

            # Fill the phone number (after country is set)
            page.wait_for_timeout(200)
            phone_field.fill(config.APPLICANT_PHONE)
            log.info("Phone filled with country=%s", "US" if country_set else "UNKNOWN")
            
        except Exception as e:
            log.debug("Phone section failed: %s", e)

        # ── Resume upload ──────────────────────────────────────────────────────
        if self.resume_path and self.resume_path.exists():
            uploaded = False
            # Method 1: direct file input (fastest — GH forms always have one)
            for sel in ("input[type='file'][id*='resume']",
                        "input[type='file'][name*='resume']",
                        "input[type='file']"):
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        loc.set_input_files(str(self.resume_path))
                        _pause(*_SHORT)
                        log.info("Resume uploaded via file input: %s", self.resume_path.name)
                        uploaded = True
                        break
                except Exception:
                    continue
            # Method 2: Attach button / file chooser dialog (fallback)
            if not uploaded:
                for label_text in ("Resume/CV*", "Resume/CV", "Resume", "CV"):
                    try:
                        grp = page.get_by_role("group", name=label_text)
                        if grp.count() == 0:
                            grp = page.get_by_label(label_text)
                        attach = grp.get_by_role("button", name="Attach")
                        if attach.count() > 0:
                            with page.expect_file_chooser(timeout=5000) as fc:
                                attach.first.click()
                            fc.value.set_files(str(self.resume_path))
                            _pause(*_SHORT)
                            log.info("Resume uploaded via Attach button: %s", self.resume_path.name)
                            uploaded = True
                            break
                    except Exception:
                        continue
            if not uploaded:
                log.warning("Resume upload failed for job %d", job_id)

        # ── Cover letter ───────────────────────────────────────────────────────
        if self.resume_path:
            cl_dir = config.ROOT_DIR / "resumes" / "cover_letters"
            slug = job.company.lower().replace(" ", "")[:20]
            cl_file = cl_dir / f"cover_letter_{slug}.txt"
            if not cl_file.exists():
                cl_file = next(cl_dir.glob("cover_letter_*.txt"), None) if cl_dir.exists() else None
            if cl_file:
                for label_text in ("Cover Letter", "Cover letter"):
                    try:
                        cl_btn = page.get_by_label(label_text).get_by_role("button", name="Attach")
                        if cl_btn.count() > 0:
                            with page.expect_file_chooser(timeout=5000) as fc:
                                cl_btn.first.click()
                            fc.value.set_files(str(cl_file))
                            _pause(*_SHORT)
                            log.info("Cover letter uploaded: %s", cl_file.name)
                            break
                    except Exception:
                        continue

        # ── Text questions ─────────────────────────────────────────────────────
        try:
            page.get_by_label("LinkedIn Profile").click()
            page.get_by_label("LinkedIn Profile").fill(config.APPLICANT_LINKEDIN)
        except Exception: pass
        try:
            page.get_by_label("How did you hear about this").click()
            page.get_by_label("How did you hear about this").fill("LinkedIn")
        except Exception: pass

        # ── All Select... dropdowns: work-auth custom questions + EEO ────────────
        # New GH forms use the same "Select... ▼" box for ALL dropdown questions
        # (custom work-auth AND EEO). We do one JS tree-walk to find every unfilled
        # placeholder, match the question text against known patterns, then
        # mouse-click at viewport coordinates to open each one.
        _veteran_ans  = config.APPLICANT_VETERAN_STATUS or "No"
        _disability_ans = config.APPLICANT_DISABILITY or "No"
        _orient_ans   = config.APPLICANT_ORIENTATION or "Straight/Heterosexual"
        _race_ans     = config.APPLICANT_RACE or "Latinx or Hispanic"
        _gender_ans   = config.APPLICANT_GENDER or "Male"
        _gender_id_ans = config.APPLICANT_GENDER_IDENTITY or _gender_ans

        _Q_MAP = [
            # Work auth / custom questions — more specific first
            (r"authoriz.*work|work.*authoriz|eligible.*work",        "Yes"),
            (r"located.{0,10}us\b|based.{0,10}us\b|current.{0,10}us\b", "Yes"),
            # Sponsorship — must come BEFORE generic "sponsor" to avoid matching "Canada" questions
            (r"sponsor.{0,30}canada|canada.{0,30}sponsor",          "Yes"),  # US citizen needs Canada sponsorship
            (r"require.*sponsor|sponsor|visa.*requir",               "No"),   # US work sponsorship: No
            (r"non.?compet",                                          "No"),
            (r"relocat|bay area|willing to move",                    "No"),
            (r"year.{0,20}exp|exp.{0,20}year",                      str(config.APPLICANT_YEARS_EXP)),
            # State/province (type state name — options list will match)
            (r"state.{0,20}reside|province.{0,20}reside|which.{0,10}state|which.{0,10}province",
             "New Jersey"),  # Alex's state
            # "How did you hear about us?" dropdown variant
            (r"how did you.{0,30}learn|how did you.{0,30}hear|how.{0,15}find.{0,15}(job|role|position|opening|us)",
             "LinkedIn"),
            # "Previously employed here?" — always No
            (r"previously.{0,30}employ|previously.{0,30}work.{0,15}(here|company|us|this)",
             "No"),
            # EEO / demographic — MORE SPECIFIC patterns first, generic last
            # Gender identity (includes "I identify as:")
            (r"gender.{0,10}identity|identify.{0,15}as\b(?!.*race|.*orient|.*sex)",  _gender_id_ans),
            (r"\bgender\b",                _gender_ans),
            # Binary "Are you Hispanic/Latino?" question (Yes/No)
            (r"are you hispanic|are you latino",
             "Yes" if any(w in _race_ans.lower() for w in ['hispanic', 'latin']) else "No"),
            # Race/ethnicity
            (r"hispanic|latino",           _race_ans),
            (r"race|ethnicit",             _race_ans),
            # Veteran — "No" for non-veterans; tries exact then substring
            (r"veteran|military",          _veteran_ans),
            # Orientation (includes "I identify my sexual orientation as:")
            (r"sexual.{0,20}orient|lgbtq|\borientation\b", _orient_ans),
            # Disability (includes "I have a disability:")
            (r"disabilit",                 _disability_ans),
        ]
        try:
            # Scroll to bottom so lazily-rendered sections appear, then back up
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(700)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(400)

            # Wait for React to finish hydrating the interactive components.
            # React attaches non-enumerable fiber keys (e.g. __reactFiber$xxx)
            # to DOM nodes; Object.getOwnPropertyNames() reveals them even
            # though Object.keys() does not.  Only after hydration do event
            # handlers exist and dropdowns respond to user interaction.
            try:
                page.wait_for_function("""() => {
                    const inp = document.querySelector('input[role="combobox"]');
                    if (!inp) return false;
                    return Object.getOwnPropertyNames(inp)
                        .some(k => k.includes('react') || k.includes('React'));
                }""", timeout=10000)
                log.info("React hydration confirmed (fiber key present)")
            except Exception as _he:
                log.warning("React hydration wait timed out (%s); continuing", _he)
                page.wait_for_timeout(3000)   # hard wait as fallback

            # JS tree-walk: find every text node whose value is "Select..."
            # and return the surrounding question context for each.
            # KEY: use the FIRST (narrowest) qualifying ancestor so each dropdown
            # gets its own specific question text, not a broad shared parent.
            dd_list = page.evaluate("""() => {
                const results = [];
                function walk(el) {
                    for (const child of el.childNodes) {
                        if (child.nodeType === 3 &&
                                child.textContent.trim() === 'Select...') {
                            const parent = child.parentElement;
                            if (!parent) continue;
                            let q = '', node = parent.parentElement;
                            for (let i = 0; i < 8 && node; i++, node = node.parentElement) {
                                const t = (node.textContent || '').trim()
                                           .replace(/\\s+/g, ' ');
                                // Stop at the FIRST ancestor that has meaningful text
                                // (15-200 chars) — this gives the specific question,
                                // not a broad section containing many questions.
                                if (t.length > 15 && t.length < 200) {
                                    q = t;
                                    break;
                                }
                            }
                            results.push({q: q.slice(0, 200)});
                        } else if (child.nodeType === 1 &&
                                   !['SCRIPT','STYLE','NOSCRIPT'].includes(child.tagName)) {
                            walk(child);
                        }
                    }
                }
                walk(document.body);
                return results;
            }""")
            log.info("Select... dropdowns on page: %d", len(dd_list))
            log.info("  Processing %d dropdowns...", len(dd_list))
            for i, dd in enumerate(dd_list):
                log.info("  [Dropdown %d/%d] Starting: %.50s", i+1, len(dd_list), dd.get("q", "")[:50])
                q = dd.get("q", "")
                answer = None
                for pattern, ans in _Q_MAP:
                    if re.search(pattern, q, re.I):
                        answer = ans
                        break
                if answer is None:
                    log.debug("  No match for dropdown: %.50s", q)
                    continue

                # Strip the "Select..." suffix from the anchor before passing to JS
                anchor = q.replace("Select...", "").strip()[:80]
                log.info("  Dropdown: '%.45s' -> '%s'", anchor, answer)

                # Aggressively close any open dropdown before proceeding
                # This prevents stale menus from polluting option queries
                try:
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(300)
                    # Click on body to ensure any open menu closes
                    page.evaluate("document.body.click()")
                    page.wait_for_timeout(200)
                    # Force React to unmount any open menu by blurring active element
                    page.evaluate("""() => {
                        if (document.activeElement && document.activeElement.blur) {
                            document.activeElement.blur();
                        }
                        // Force close any open select menus
                        document.querySelectorAll('[class*="select__menu"]').forEach(m => {
                            m.style.display = 'none';
                        });
                    }""")
                    page.wait_for_timeout(150)
                except Exception:
                    pass

                # React Select opens when its `input[role="combobox"]` receives a
                # click or focus event.  We locate the exact input by finding its
                # index among all comboboxes on the page, then click it via the
                # Playwright locator API — per the [role="combobox"] approach.
                ss_dir = config.ROOT_DIR / "logs" / "screenshots"
                ss_dir.mkdir(parents=True, exist_ok=True)

                # Find the DOM index of the input[role="combobox"] that belongs
                # to this question's select__control.
                log.info("  [Dropdown %d/%d] Finding combobox index...", i+1, len(dd_list))
                cb_idx: int = page.evaluate("""(anchor) => {
                    const allInputs = [...document.querySelectorAll(
                        'input[role="combobox"]')];
                    const controls = document.querySelectorAll(
                        '[class*="select__control"]');
                    for (const ctrl of controls) {
                        const ph = ctrl.querySelector('[class*="placeholder"]');
                        if (!ph || ph.textContent.trim() !== 'Select...') continue;
                        let node = ctrl.parentElement, found = false;
                        for (let i = 0; i < 8 && node; i++, node = node.parentElement) {
                            if ((node.textContent || '').includes(anchor)) {
                                found = true; break;
                            }
                        }
                        if (!found) continue;
                        const inp = ctrl.querySelector('input[role="combobox"]');
                        if (inp) return allInputs.indexOf(inp);
                    }
                    return -1;
                }""", anchor)

                if cb_idx < 0:
                    log.warning("  Combobox not found for: %.45s", anchor)
                    continue

                cb = page.locator('input[role="combobox"]').nth(cb_idx)
                opened_dropdown = False

                # Get bounding box for human-like click
                cb_box = None
                try:
                    cb_box = cb.bounding_box(timeout=3000)
                except Exception:
                    pass

                # ── Strategy 1: Human-like click + ArrowDown ─────────────────
                # Use human-like mouse movement and click timing
                try:
                    if cb_box:
                        # Scroll element into view with human-like scroll
                        cb.scroll_into_view_if_needed()
                        page.wait_for_timeout(random.uniform(200, 400))
                        
                        # Human-like click on the input
                        click_x = cb_box['x'] + cb_box['width'] * random.uniform(0.3, 0.7)
                        click_y = cb_box['y'] + cb_box['height'] * random.uniform(0.3, 0.7)
                        _human_click(page, click_x, click_y)
                    else:
                        cb.scroll_into_view_if_needed()
                        page.wait_for_timeout(300)
                        cb.click(force=True, timeout=3000)
                    
                    page.wait_for_timeout(random.uniform(300, 600))
                    
                    # Human-like ArrowDown (with slight pause before)
                    page.wait_for_timeout(random.uniform(50, 150))
                    page.keyboard.press('ArrowDown')
                    page.wait_for_timeout(random.uniform(400, 700))
                    
                    # Check if dropdown opened by checking aria-expanded
                    expanded = page.evaluate("""(idx) => {
                        const inp = document.querySelectorAll('input[role="combobox"]')[idx];
                        return inp ? inp.getAttribute('aria-expanded') : 'none';
                    }""", cb_idx)
                    
                    if expanded == 'true':
                        opened_dropdown = True
                        log.info("  Opened via click+ArrowDown (aria-expanded=true): %.35s", anchor)
                        
                        # CRITICAL: Wait for menu content to populate AND be different from stale content
                        # React Select reuses menu DOM, so we need to wait for actual content change
                        page.wait_for_timeout(random.uniform(400, 700))
                        
                        # Wait for options to appear with correct count
                        prev_menu_text = None
                        for retry in range(3):
                            menu_info = page.evaluate("""(idx) => {
                                const inp = document.querySelectorAll('input[role="combobox"]')[idx];
                                if (!inp) return { text: '', count: 0 };
                                const ctrl = inp.closest('[class*="select__control"]');
                                if (!ctrl) return { text: '', count: 0 };
                                let menu = ctrl.querySelector('[class*="select__menu"]') || ctrl.nextElementSibling;
                                if (!menu) return { text: '', count: 0 };
                                const opts = menu.querySelectorAll('[role="option"]');
                                // Get concatenated text of all options (for change detection)
                                const optTexts = [...opts].map(o => o.textContent.trim()).slice(0, 5);
                                return { 
                                    text: optTexts.join('|'),
                                    count: opts.length,
                                    firstOpt: optTexts[0] || ''
                                };
                            }""", cb_idx)
                            
                            # Check if menu content changed from previous dropdown
                            if menu_info['count'] > 0 and menu_info['text'] != prev_menu_text:
                                # Verify content matches expected answer type
                                # (e.g., Yes/No questions should have short options)
                                log.debug("  Menu has %d options, first: %s", menu_info['count'], menu_info['firstOpt'][:40])
                                break
                            
                            prev_menu_text = menu_info['text']
                            page.wait_for_timeout(random.uniform(200, 400))
                        
                    else:
                        # Try waiting for option selector
                        page.wait_for_selector('[role="option"]', timeout=2500)
                        opened_dropdown = True
                        log.info("  Opened via click+ArrowDown (options found): %.35s", anchor)
                        
                except Exception as _e1:
                    log.debug("  Strategy 1 failed: %s", _e1)

                # ── Strategy 2: type-to-filter (keep open for option retrieval) ──
                # Type the answer to filter options, then let the option-finding
                # code below click the correct item.  Do NOT press Enter here —
                # Enter with no match closes the dropdown without selecting.
                if not opened_dropdown:
                    try:
                        cb.click(force=True, timeout=3000)
                        page.wait_for_timeout(400)
                        cb.fill(answer, timeout=2000)
                        page.wait_for_timeout(600)
                        # Only mark as open if aria-expanded is actually true
                        is_open = page.evaluate("""(idx) => {
                            const inp = document.querySelectorAll('input[role="combobox"]')[idx];
                            return inp ? inp.getAttribute('aria-expanded') === 'true' : false;
                        }""", cb_idx)
                        if is_open:
                            opened_dropdown = True
                            log.info("  Opened via type-filter: %.35s", anchor)
                        else:
                            log.debug("  Strategy 2: fill did not open dropdown for %.35s", anchor)
                    except Exception as _e2:
                        log.debug("  Strategy 2 failed: %s", _e2)

                # ── Strategy 3: Focus + Space ─────────────────────────────────
                if not opened_dropdown:
                    try:
                        cb.focus(timeout=3000)
                        page.wait_for_timeout(300)
                        page.keyboard.press('Space')
                        page.wait_for_timeout(500)
                        expanded = page.evaluate("""(idx) => {
                            const inp = document.querySelectorAll('input[role="combobox"]')[idx];
                            return inp ? inp.getAttribute('aria-expanded') : 'none';
                        }""", cb_idx)
                        if expanded == 'true':
                            opened_dropdown = True
                            log.info("  Opened via Space (aria-expanded=true): %.35s", anchor)
                        else:
                            page.wait_for_selector('[role="option"]', timeout=2000)
                            opened_dropdown = True
                            log.info("  Opened via Space (options found): %.35s", anchor)
                    except Exception as _e3:
                        log.debug("  Strategy 3 failed: %s", _e3)

                # ── Strategy 4: Click parent control div ──────────────────────
                # Fallback: find and click the parent select__control div
                if not opened_dropdown:
                    try:
                        ctrl_sel = page.evaluate("""(idx) => {
                            const inp = document.querySelectorAll('input[role="combobox"]')[idx];
                            if (!inp) return null;
                            const ctrl = inp.closest('[class*="select__control"]');
                            if (!ctrl) return null;
                            // Build selector using unique class combo
                            const cls = Array.from(ctrl.classList)
                                .filter(c => c.startsWith('select__') || c.startsWith('remix'))
                                .join('.');
                            const all = [...document.querySelectorAll('.' + cls)];
                            const myIdx = all.indexOf(ctrl);
                            return '.' + cls + ':nth-of-type(' + (myIdx + 1) + ')';
                        }""", cb_idx)
                        if ctrl_sel:
                            ctrl_loc = page.locator(ctrl_sel)
                            ctrl_loc.scroll_into_view_if_needed()
                            page.wait_for_timeout(200)
                            ctrl_loc.click(timeout=3000)
                            page.wait_for_timeout(400)
                            page.keyboard.press('ArrowDown')
                            page.wait_for_timeout(400)
                            page.wait_for_selector('[role="option"]', timeout=2500)
                            opened_dropdown = True
                            log.info("  Opened via control.click: %.35s", anchor)
                    except Exception as _e4:
                        log.debug("  Strategy 4 failed: %s", _e4)

                # Screenshot regardless — shows what succeeded or failed
                safe_lbl = re.sub(r'[^\w]', '_', anchor[:30])
                try:
                    page.screenshot(path=str(ss_dir / f"{safe_lbl}_open.png"))
                except Exception:
                    pass

                if not opened_dropdown:
                    log.warning("  All open strategies failed: %.45s", anchor)
                    page.keyboard.press('Escape')
                    continue

                # Wait for dropdown animation to complete before selecting
                page.wait_for_timeout(300)

                # If the dropdown was opened via type-filter, only clear the typed text
                # for SHORT answers (Yes/No/Male/etc.) where the filter isn't helpful.
                # For SPECIFIC answers like "New Jersey" or "Hispanic or Latino", keep the
                # filter so Strategy A can find the exact match in the filtered list.
                _SHORT_ANSWERS = {'yes', 'no', 'male', 'female', 'straight', 'other',
                                  'none', 'true', 'false', '1', '2', '3', '4', '5'}
                try:
                    current_val = page.locator('input[role="combobox"]').nth(cb_idx).input_value(timeout=500)
                    if current_val and current_val.lower().strip() in _SHORT_ANSWERS:
                        # Short answer — clear so all options show (non-filterable dropdowns)
                        page.locator('input[role="combobox"]').nth(cb_idx).fill("")
                        page.wait_for_timeout(350)
                    # For longer specific answers, keep the filter text so it narrows the list
                except Exception:
                    pass

                # Wait for the select__menu to appear (React Select renders it after click)
                try:
                    page.wait_for_selector('[class*="select__menu"]', timeout=2000)
                    page.wait_for_timeout(200)  # Extra wait for animation
                except Exception:
                    log.debug("  select__menu did not appear, continuing anyway")

                # Debug: log what elements appear when dropdown is open
                # KEY: scope to select__menu to avoid phone country dropdown (iti__country)
                debug_info = page.evaluate("""(idx) => {
                    const inp = document.querySelectorAll('input[role="combobox"]')[idx];
                    const menu = inp?.closest('[class*="select__control"]')
                        ?.querySelector('[class*="select__menu"]');
                    const menus = menu ? [menu.className.slice(0, 80)] : [];
                    const opts = menu
                        ? [...menu.querySelectorAll('[role="option"]')].map(e => ({
                            cls: e.className.slice(0, 60),
                            txt: e.textContent.slice(0, 40),
                            w: e.getBoundingClientRect().width,
                            h: e.getBoundingClientRect().height
                        }))
                        : [];
                    return { menus, opts: opts.slice(0, 10) };
                }""", cb_idx)
                if debug_info['opts']:
                    log.info("  DEBUG menu classes: %s", debug_info['menus'][:3])
                    log.info("  DEBUG option elements: %s", debug_info['opts'][:5])

                # Get all options SCOPED to the select__menu container for THIS dropdown
                # React Select renders the menu as a sibling after the control, or as a portal
                # We find it by: 1) sibling after control, 2) by aria-controls relationship
                options = page.evaluate("""(idx) => {
                    const inp = document.querySelectorAll('input[role="combobox"]')[idx];
                    if (!inp) return [];
                    const ctrl = inp.closest('[class*="select__control"]');
                    
                    // Only look for VISIBLE menus (height > 0) to avoid stale hidden menus
                    // that React keeps in the DOM after closing with display:none.
                    function isVisible(el) {
                        return el && el.getBoundingClientRect().height > 0;
                    }

                    // Method 1: Find visible menu as child of control
                    let menu = null;
                    const childMenu = ctrl?.querySelector('[class*="select__menu"]');
                    if (isVisible(childMenu)) menu = childMenu;

                    if (!menu) {
                        // React Select renders menu as sibling after control
                        const sib = ctrl?.nextElementSibling;
                        if (sib && sib.className.includes('select__menu') && isVisible(sib)) {
                            menu = sib;
                        }
                    }
                    if (!menu) {
                        // Portal-rendered: find via aria-controls
                        const ariaControls = inp.getAttribute('aria-controls');
                        if (ariaControls) {
                            const portal = document.getElementById(ariaControls);
                            if (isVisible(portal)) menu = portal;
                        }
                    }
                    if (!menu) {
                        // Last resort: any visible select__menu on the page
                        const allMenus = [...document.querySelectorAll('[class*="select__menu"]')];
                        menu = allMenus.find(isVisible) || null;
                    }
                    if (!menu) return [];
                    
                    // Get options from this specific menu
                    return [...menu.querySelectorAll('[role="option"]')].map((e, i) => ({
                        idx: i,
                        txt: e.textContent.trim(),
                        visible: e.getBoundingClientRect().height > 0,
                        sel: (() => {
                            if (e.id) return '#' + CSS.escape(e.id);
                            const cls = Array.from(e.classList)
                                .filter(c => c.startsWith('select__option') || c.startsWith('remix'))
                                .join('.');
                            const all = [...menu.querySelectorAll('.' + cls)];
                            const myIdx = all.indexOf(e);
                            return '.' + cls + ':nth-of-type(' + (myIdx + 1) + ')';
                        })()
                    }));
                }""", cb_idx)

                opt_texts = [o['txt'] for o in options]
                log.info("  Options for '%.30s': %s", anchor, opt_texts[:8])

                # Fallback: try broader selectors if [role="option"] is empty
                # But filter to reasonable option text (not full sentences)
                if not options:
                    for alt_sel in ('[class*="select__option"]', '[class*="Option"]'):
                        opts_data = page.evaluate("""(arg) => {
                            const { sel, cbIdx } = arg;
                            const inp = document.querySelectorAll('input[role="combobox"]')[cbIdx];
                            if (!inp) return [];
                            const ctrl = inp.closest('[class*="select__control"]');
                            
                            // Find menu using same logic as above
                            let menu = ctrl?.querySelector('[class*="select__menu"]');
                            if (!menu) {
                                menu = ctrl?.nextElementSibling;
                                if (!menu || !menu.className.includes('select__menu')) {
                                    const ariaControls = inp.getAttribute('aria-controls');
                                    if (ariaControls) menu = document.getElementById(ariaControls);
                                }
                            }
                            if (!menu) return [];
                            
                            return [...menu.querySelectorAll(sel)]
                                .filter(e => {
                                    const txt = e.textContent.trim();
                                    return txt.length > 1 && txt.length < 100 && !txt.includes(',');
                                })
                                .map((e, i) => ({
                                    txt: e.textContent.trim(),
                                    sel: (() => {
                                        if (e.id) return '#' + CSS.escape(e.id);
                                        const cls = Array.from(e.classList).join('.');
                                        return '.' + cls + ':nth-of-type(' + (i + 1) + ')';
                                    })()
                                }));
                        }""", {'sel': alt_sel, 'cbIdx': cb_idx})
                        if opts_data:
                            options = opts_data
                            opt_texts = [o['txt'] for o in options]
                            log.info("  Found options via %s: %s", alt_sel, opt_texts[:8])
                            break

                # Last resort fallback: use Playwright locators (may include wrong elements)
                if not options:
                    for alt_sel in ('li', 'button', 'span[role]'):
                        opts = page.locator(alt_sel).filter(has_text=answer).all()
                        if opts:
                            options = [{'txt': o.inner_text().strip(), 'sel': None, 'el': o} for o in opts]
                            opt_texts = [o['txt'] for o in options]
                            log.info("  Found options via %s: %s", alt_sel, opt_texts[:8])
                            break

                _DECLINE = ('prefer not', 'decline', 'choose not',
                            'do not wish', 'not specified',
                            'prefer to self-describe', 'i do not want')
                matched = False

                # Strategy A: Exact case-insensitive match (no substring — prevents
                # "Male" hitting "Female" or "Yes" hitting "Yesterday" etc.)
                for opt in options:
                    ot = opt['txt']
                    if answer.lower() == ot.lower():
                        try:
                            if opt.get('sel'):
                                page.locator(opt['sel']).first.click(timeout=3000)
                            elif opt.get('el'):
                                opt['el'].click()
                            else:
                                page.get_by_role('option', name=ot).first.click()
                            log.info("  -> Selected (exact): '%s'", ot)
                            matched = True
                            break
                        except Exception as _ce:
                            log.debug("  Click failed for '%s': %s", ot, _ce)

                # Strategy A2: Substring match (answer is contained in option text)
                # e.g. "Straight/Heterosexual" matches "Straight / Heterosexual"
                if not matched:
                    for opt in options:
                        ot = opt['txt']
                        if (answer.lower() in ot.lower() or ot.lower() in answer.lower()):
                            # Skip if another option is a better (exact) match
                            exact_exists = any(o['txt'].lower() == answer.lower() for o in options)
                            if exact_exists:
                                continue
                            try:
                                if opt.get('sel'):
                                    page.locator(opt['sel']).first.click(timeout=3000)
                                elif opt.get('el'):
                                    opt['el'].click()
                                else:
                                    page.get_by_role('option', name=ot).first.click()
                                log.info("  -> Selected (substring): '%s'", ot)
                                matched = True
                                break
                            except Exception as _ce:
                                log.debug("  Click failed for '%s': %s", ot, _ce)

                # Strategy B: Keyword-based fallback for EEO questions
                # Maps common answer values to likely option text patterns
                if not matched:
                    keyword_map = {
                        'man': ['man', 'male'],
                        'woman': ['woman', 'female'],
                        'cisgender': ['man', 'woman', 'cis'],
                        'hispanic': ['hispanic', 'latino', 'latin', 'latinx'],
                        'latino': ['hispanic', 'latino', 'latin', 'latinx'],
                        'latin': ['hispanic', 'latino', 'latin', 'latinx'],
                        'latinx': ['hispanic', 'latino', 'latin', 'latinx'],
                        'asian': ['asian'],
                        'black': ['black', 'african'],
                        'white': ['white', 'caucasian'],
                        'native': ['native', 'indigenous'],
                        'pacific': ['pacific', 'islander'],
                        'no': ['no', 'not', 'none', 'do not'],
                        'yes': ['yes'],
                        'straight': ['straight', 'heterosexual'],
                        'heterosexual': ['straight', 'heterosexual'],
                        'gay': ['gay', 'lesbian', 'homosexual'],
                        'lesbian': ['gay', 'lesbian', 'homosexual'],
                        'bisexual': ['bi', 'bisexual'],
                        'veteran': ['veteran', 'military'],
                        'non-binary': ['non-binary', 'nonbinary', 'genderqueer', 'third gender'],
                        'disability': ['disability', 'disabilities'],
                    }
                    # Get keywords from map, or extract from answer by splitting on common delimiters
                    answer_lower = answer.lower()
                    if answer_lower in keyword_map:
                        keywords = keyword_map[answer_lower]
                    else:
                        # Extract keywords by splitting on commas, 'or', 'and', '/'
                        import re as _re
                        words = _re.split(r'[,/]|\\bor\\b|\\band\\b', answer_lower)
                        keywords = [w.strip() for w in words if len(w.strip()) > 2]
                        # Also check keyword_map for each extracted word
                        for w in keywords[:]:
                            if w in keyword_map:
                                keywords.extend(keyword_map[w])

                    # For gender, prioritize exact matches first
                    if 'gender' in anchor.lower() or answer_lower in ('man', 'woman', 'male', 'female'):
                        # Try exact match first (case-insensitive whole word)
                        for opt in options:
                            ot = opt['txt'].lower().strip()
                            # Exact match or common equivalents
                            if (answer_lower == ot or
                                (answer_lower == 'man' and ot == 'male') or
                                (answer_lower == 'woman' and ot == 'female') or
                                (answer_lower == 'male' and ot == 'man') or
                                (answer_lower == 'female' and ot == 'woman')):
                                try:
                                    if opt.get('sel'):
                                        page.locator(opt['sel']).first.click(timeout=3000)
                                    elif opt.get('el'):
                                        opt['el'].click()
                                    else:
                                        page.get_by_role('option', name=opt['txt']).first.click()
                                    log.info("  -> Selected (exact gender): '%s'", opt['txt'])
                                    matched = True
                                    log.info("  [Dropdown %d/%d] After gender select, matched=%s", i+1, len(dd_list), matched)
                                except Exception as _gf:
                                    log.debug("  Gender exact click failed: %s", _gf)
                                break  # Exit gender matching loop after first match
                        # Skip remaining matching strategies if gender matched
                        if matched:
                            log.info("  [Dropdown %d/%d] Gender matched, skipping other strategies", i+1, len(dd_list))
                            continue  # Continue to next dropdown, not break!
                    
                    # Regular keyword matching
                    for opt in options:
                        ot = opt['txt'].lower()
                        for kw in keywords:
                            if kw in ot:
                                try:
                                    if opt.get('sel'):
                                        page.locator(opt['sel']).first.click(timeout=3000)
                                    elif opt.get('el'):
                                        opt['el'].click()
                                    else:
                                        page.get_by_role('option', name=opt['txt']).first.click()
                                    log.info("  -> Selected (keyword fallback): '%s'", opt['txt'])
                                    matched = True
                                    break
                                except Exception as _kf:
                                    log.debug("  Keyword fallback click failed: %s", _kf)
                        if matched:
                            break

                # Strategy E: Smart inference for unknown questions
                # When we can't match any known pattern, infer from question + options
                if not matched:
                    question_lower = anchor.lower()
                    opt_texts = [o['txt'].lower() for o in options]
                    
                    # Rule 1: Yes/No questions - infer from question type
                    if len(options) == 2 and set(opt_texts) == {'yes', 'no'}:
                        # Work authorization, sponsorship, relocation → typically No for sponsorship, Yes for authorization
                        if any(kw in question_lower for kw in ['authoriz', 'eligible', 'citizen', 'perm']):
                            answer = 'Yes'
                        elif any(kw in question_lower for kw in ['sponsor', 'visa', 'require']):
                            answer = 'No'
                        elif any(kw in question_lower for kw in ['relocat', 'bay area', 'willing']):
                            answer = 'No'  # Default to no relocation
                        elif any(kw in question_lower for kw in ['located', 'based', 'current']):
                            answer = 'Yes'  # Assume located in US
                        else:
                            answer = 'No'  # Default to No for unknown Yes/No
                        try:
                            no_opt = next(o for o in options if o['txt'].lower() == answer.lower())
                            if no_opt.get('sel'):
                                page.locator(no_opt['sel']).first.click(timeout=3000)
                            elif no_opt.get('el'):
                                no_opt['el'].click()
                            else:
                                page.get_by_role('option', name=no_opt['txt']).first.click()
                            log.info("  -> Selected (inferred Yes/No): '%s' for '%.40s'", answer, anchor)
                            matched = True
                        except Exception as _inf:
                            log.debug("  Inferred Yes/No failed: %s", _inf)
                    
                    # Rule 2: Protected class with mismatched options (like Amplitude bug)
                    # If question is about gender/race/veteran but options don't match, pick decline
                    elif any(kw in question_lower for kw in ['gender', 'race', 'ethnic', 'veteran', 'disability', 'sexual', 'orientation']):
                        # Look for decline/self-describe options
                        for decline_kw in ['prefer', 'self-describe', 'decline', "don't", 'not wish']:
                            for opt in options:
                                if decline_kw in opt['txt'].lower():
                                    try:
                                        if opt.get('sel'):
                                            page.locator(opt['sel']).first.click(timeout=3000)
                                        elif opt.get('el'):
                                            opt['el'].click()
                                        else:
                                            page.get_by_role('option', name=opt['txt']).first.click()
                                        log.info("  -> Selected (protected class decline): '%s'", opt['txt'])
                                        matched = True
                                        break
                                    except Exception as _pd:
                                        log.debug("  Protected decline failed: %s", _pd)
                            if matched:
                                break
                    
                    # Rule 3: Experience/tenure questions - pick middle option
                    elif any(kw in question_lower for kw in ['year', 'experience', 'exp', 'seniority']):
                        # Try to find numeric options and pick middle
                        numeric_opts = []
                        for opt in options:
                            import re as _re
                            nums = _re.findall(r'\d+', opt['txt'])
                            if nums:
                                numeric_opts.append((int(nums[0]), opt))
                        if numeric_opts:
                            numeric_opts.sort(key=lambda x: x[0])
                            mid_idx = len(numeric_opts) // 2
                            mid_opt = numeric_opts[mid_idx][1]
                            try:
                                if mid_opt.get('sel'):
                                    page.locator(mid_opt['sel']).first.click(timeout=3000)
                                elif mid_opt.get('el'):
                                    mid_opt['el'].click()
                                else:
                                    page.get_by_role('option', name=mid_opt['txt']).first.click()
                                log.info("  -> Selected (middle experience): '%s'", mid_opt['txt'])
                                matched = True
                            except Exception as _exp:
                                log.debug("  Experience middle failed: %s", _exp)
                    
                    # Rule 4: Last resort - pick first non-decline option
                    if not matched and options:
                        for opt in options:
                            ot = opt['txt'].lower()
                            # Skip decline options, pick first real answer
                            if not any(kw in ot for kw in ['prefer', 'decline', "don't", 'not wish', 'self-describe']):
                                try:
                                    if opt.get('sel'):
                                        page.locator(opt['sel']).first.click(timeout=3000)
                                    elif opt.get('el'):
                                        opt['el'].click()
                                    else:
                                        page.get_by_role('option', name=opt['txt']).first.click()
                                    log.info("  -> Selected (first non-decline): '%s'", opt['txt'])
                                    matched = True
                                    break
                                except Exception as _fn:
                                    log.debug("  First non-decline failed: %s", _fn)

                # Strategy D: Decline fallback for EEO questions
                if not matched:
                    for opt in options:
                        ot = opt['txt']
                        if any(ph in ot.lower() for ph in _DECLINE):
                            try:
                                if opt.get('sel'):
                                    page.locator(opt['sel']).first.click(timeout=3000)
                                elif opt.get('el'):
                                    opt['el'].click()
                                else:
                                    page.get_by_role('option', name=ot).first.click()
                                log.info("  -> Decline fallback: '%s'", ot)
                                matched = True
                                break
                            except Exception as _de:
                                log.debug("  Decline click failed for '%s': %s", ot, _de)

                # Strategy F: Ultimate fallback - just pick something to avoid validation errors
                if not matched and options:
                    # Pick the first option that's not obviously a decline
                    # This ensures we don't leave required fields blank
                    for opt in options:
                        try:
                            if opt.get('sel'):
                                page.locator(opt['sel']).first.click(timeout=3000)
                            elif opt.get('el'):
                                opt['el'].click()
                            else:
                                page.get_by_role('option', name=opt['txt']).first.click()
                            log.info("  -> Selected (fallback): '%s' for '%.40s'", opt['txt'], anchor)
                            matched = True
                            break
                        except Exception as _uf:
                            log.debug("  Ultimate fallback failed: %s", _uf)
                    
                    if not matched:
                        log.warning("  [GAVE UP] Could not fill dropdown: %.50s", anchor)
                        page.keyboard.press('Escape')

                log.info("  [Dropdown %d/%d] Completed: %.40s", i+1, len(dd_list), anchor[:40])
                page.wait_for_timeout(300)
                _pause(*_SHORT)
                log.info("  [Dropdown %d/%d] Iteration complete, continuing to next...", i+1, len(dd_list))

        except Exception as e:
            log.error("Custom/EEO dropdowns error: %s", e)
            import traceback
            log.error("Traceback: %s", traceback.format_exc())

        # ── Consent checkbox ───────────────────────────────────────────────────
        try:
            consent = page.get_by_label("By checking this box, I")
            if consent.count() > 0:
                _pause(*_SHORT)
                consent.check()
                log.info("Consent checked for job %d", job_id)
        except Exception as e:
            log.debug("Consent checkbox: %s", e)

    def _fill_gh_classic_form(self, page, job: Job, job_id: int) -> None:
        """Fill classic boards.greenhouse.io forms using #id selectors."""

        # Click Apply button if still on description page
        if page.locator("#first_name, #last_name, #email").count() == 0:
            apply_btn = page.locator(
                "a:has-text('Apply'), button:has-text('Apply'), "
                "a:has-text('Apply for this job'), button:has-text('Apply for this job'), "
                "a[href*='/apply'], button[data-test='apply-button']"
            ).first
            try:
                if apply_btn.count() > 0:
                    _pause(*_SHORT)
                    apply_btn.click()
                    page.wait_for_load_state("networkidle", timeout=15000)
                    _pause(*_MEDIUM)
                    log.info("Clicked Apply for job %d", job_id)
            except Exception:
                pass

        # Personal info
        _human_type(page, "#first_name",     config.APPLICANT_FIRST_NAME)
        _pause(*_SHORT)
        _human_type(page, "#last_name",      config.APPLICANT_LAST_NAME)
        _pause(*_SHORT)
        _human_type(page, "#preferred_name", config.APPLICANT_PREFERRED_NAME)
        _pause(*_SHORT)
        _human_type(page, "#email",          config.APPLICANT_EMAIL)
        _pause(*_SHORT)

        # Country — Greenhouse classic uses a Select2 combobox over a hidden <select>
        try:
            if page.locator("#country").count() > 0:
                # Try native select_option first (works even when Select2 hides it)
                try:
                    page.locator("#country").first.select_option(label="United States")
                    _pause(*_SHORT)
                    log.info("Country set via select_option")
                except Exception:
                    # Fallback: open combobox, type, click the matching option
                    page.locator("#country").first.click()
                    _pause(0.3, 0.6)
                    page.locator("#country").first.fill("United States")
                    _pause(0.5, 1.0)
                    # Click the autocomplete result
                    for opt_sel in (
                        "[role='option']:has-text('United States')",
                        ".select2-results__option:has-text('United States')",
                        "li:has-text('United States')",
                    ):
                        if page.locator(opt_sel).count() > 0:
                            page.locator(opt_sel).first.click()
                            log.info("Country set via autocomplete click")
                            break
                    else:
                        page.keyboard.press("ArrowDown")
                        page.keyboard.press("Enter")
                    _pause(*_SHORT)
        except Exception as e:
            log.debug("Country field error (non-fatal): %s", e)

        _human_type(page, "#phone", config.APPLICANT_PHONE)
        _pause(*_SHORT)

        # LinkedIn / website fields
        _human_type(page, "#job_application_linkedin_profile_url, [id*='linkedin']",
                    config.APPLICANT_LINKEDIN)
        _pause(*_SHORT)

        # Resume upload
        if self.resume_path and self.resume_path.exists():
            uploaded = False
            # 1) Direct file input (classic GH)
            for sel in ("input[type='file']#resume",
                        "input[type='file'][id*='resume']",
                        "input[type='file'][name*='resume']",
                        "input[type='file']"):
                try:
                    if page.locator(sel).count() > 0:
                        page.set_input_files(sel, str(self.resume_path))
                        _pause(*_SHORT)
                        log.info("Resume uploaded via file input: %s", self.resume_path.name)
                        uploaded = True
                        break
                except Exception:
                    continue
            # 2) Styled Attach/Upload button (some classic GH boards use this)
            if not uploaded:
                for btn_text in ("Attach", "Upload", "Choose File", "Browse"):
                    try:
                        btn = page.get_by_role("button", name=btn_text)
                        if btn.count() == 0:
                            btn = page.locator(f"button:has-text('{btn_text}'), a:has-text('{btn_text}')")
                        if btn.count() > 0:
                            with page.expect_file_chooser() as fc:
                                btn.first.click()
                            fc.value.set_files(str(self.resume_path))
                            _pause(*_SHORT)
                            log.info("Resume uploaded via '%s' button: %s", btn_text, self.resume_path.name)
                            uploaded = True
                            break
                    except Exception:
                        continue
            if not uploaded:
                log.warning("Could not upload resume for job %d", job_id)
        else:
            log.warning("No resume path set for job %d", job_id)

        # Cover letter upload
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

        # EEO / demographic selects — prefer user's own answers, decline as fallback
        _fill_eeo_selects(page)

    # ── Lever ──────────────────────────────────────────────────────────────────

    def _apply_lever(self, page, job: Job, job_id: int) -> Optional[Application]:
        apply_url = job.url
        if "/apply" not in apply_url:
            apply_url = apply_url.rstrip("/") + "/apply"

        page.goto(apply_url, wait_until="domcontentloaded", timeout=60000)
        _pause(*_MEDIUM)

        if self._captcha_detected(page):
            log.warning("CAPTCHA detected for job %d — skipping", job_id)
            return None

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
            # Try multiple submit selectors for Lever
            submit_clicked = False
            for sel in (
                "button[type='submit'], input[type='submit']",
                "button[class*='submit'], input[class*='submit']",
                "button:has-text('Submit'), button:has-text('Apply')",
            ):
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible(timeout=2000):
                        btn.click(timeout=3000)
                        submit_clicked = True
                        break
                except Exception:
                    continue
            
            if not submit_clicked:
                log.warning("Lever submit not found, trying Enter key")
                page.keyboard.press('Enter')
            
            page.wait_for_load_state("networkidle", timeout=15000)
            log.info("Lever submitted for job %d", job_id)
        else:
            log.info("Lever filled (dry run) for job %d", job_id)

        return _make_application(job_id, self.resume_path, "easy_apply",
                                 notes="" if self.submit else "dry_run")

    # ── Ashby ──────────────────────────────────────────────────────────────────

    def _apply_ashby(self, page, job: Job, job_id: int) -> Optional[Application]:
        """
        Fill Ashby application forms (jobs.ashby.com).
        Ashby is a React SPA — the apply URL is the job URL + '/apply'.
        Form fields use accessible labels + name attributes.
        """
        apply_url = job.url
        if not apply_url:
            log.warning("No URL for Ashby job %d", job_id)
            return None

        # Navigate directly to the apply page
        if "/apply" not in apply_url:
            apply_url = apply_url.rstrip("/") + "/apply"

        page.goto(apply_url, wait_until="domcontentloaded", timeout=60000)
        _pause(*_MEDIUM)

        if self._captcha_detected(page):
            log.warning("CAPTCHA on Ashby job %d — skipping", job_id)
            return None

        # ── Name ──────────────────────────────────────────────────────────────
        for sel, val in [
            ("input[name='firstName'], input[placeholder*='First']",  config.APPLICANT_FIRST_NAME),
            ("input[name='lastName'],  input[placeholder*='Last']",   config.APPLICANT_LAST_NAME),
            ("input[name='email'],     input[type='email']",          config.APPLICANT_EMAIL),
            ("input[name='phone'],     input[type='tel']",            config.APPLICANT_PHONE),
        ]:
            _human_type(page, sel, val)
            _pause(*_SHORT)

        # Try get_by_label as well (Ashby sometimes uses aria labels)
        _gh_label_fill(page, "First Name",  config.APPLICANT_FIRST_NAME)
        _gh_label_fill(page, "Last Name",   config.APPLICANT_LAST_NAME)
        _gh_label_fill(page, "Email",       config.APPLICANT_EMAIL)
        _gh_label_fill(page, "Phone",       config.APPLICANT_PHONE)

        # ── Resume upload ──────────────────────────────────────────────────────
        if self.resume_path and self.resume_path.exists():
            # Try labeled attach button first
            for label_text in ("Resume", "CV", "Resume/CV"):
                try:
                    btn = page.get_by_label(label_text).get_by_role("button", name="Attach")
                    if btn.count() > 0:
                        with page.expect_file_chooser() as fc:
                            btn.first.click()
                        fc.value.set_files(str(self.resume_path))
                        _pause(*_SHORT)
                        log.info("Ashby resume uploaded via Attach button")
                        break
                except Exception:
                    continue
            else:
                # Fall back to raw file input
                for sel in ("input[type='file'][name*='resume']",
                            "input[type='file'][accept*='pdf']",
                            "input[type='file']"):
                    if page.locator(sel).count() > 0:
                        page.set_input_files(sel, str(self.resume_path))
                        _pause(*_SHORT)
                        log.info("Ashby resume uploaded via file input")
                        break

        # ── LinkedIn / website ─────────────────────────────────────────────────
        for sel in ("input[name='linkedinUrl']", "input[name='linkedin']",
                    "input[placeholder*='linkedin' i]", "input[placeholder*='LinkedIn']"):
            _human_type(page, sel, config.APPLICANT_LINKEDIN)
        _gh_label_fill(page, "LinkedIn", config.APPLICANT_LINKEDIN)

        # ── Work auth / standard Yes-No questions ─────────────────────────────
        # Ashby uses <select> or radio groups for these
        for sel_text in page.locator("select").all():
            try:
                opts = sel_text.locator("option").all_text_contents()
                combined = " ".join(opts).lower()
                sel_name = (sel_text.get_attribute("name") or "").lower()
                if "authorized" in combined or "authorized" in sel_name or "eligible" in sel_name:
                    match = next((o for o in opts if "yes" in o.lower()), None)
                    if match:
                        sel_text.select_option(label=match)
                elif "sponsor" in combined or "visa" in sel_name:
                    match = next((o for o in opts if "no" in o.lower()), None)
                    if match:
                        sel_text.select_option(label=match)
                _pause(0.2, 0.5)
            except Exception:
                pass

        # ── EEO demographic selects ────────────────────────────────────────────
        _fill_eeo_selects(page)

        # ── Consent checkboxes ─────────────────────────────────────────────────
        for checkbox in page.locator("input[type='checkbox']").all():
            try:
                if not checkbox.is_checked():
                    label = page.locator(f"label[for='{checkbox.get_attribute('id')}']")
                    label_text = (label.first.text_content() or "").lower()
                    # Only check explicit consent / agreement boxes, not opt-in marketing
                    if any(w in label_text for w in ("agree", "consent", "acknowledge", "certify")):
                        checkbox.check()
                        _pause(0.2, 0.5)
            except Exception:
                pass

        if self.submit:
            _pause(*_MEDIUM)
            # Ashby uses various submit button patterns - try multiple selectors
            submit_clicked = False
            for sel in (
                "button[type='submit'], input[type='submit']",
                "button[class*='submit'], input[class*='submit']",
                "button:has-text('Submit'), button:has-text('Apply now')",
                "form button:last-of-type",
                "[data-testid='submit-button']",
            ):
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible(timeout=3000):
                        btn.click(timeout=5000)
                        submit_clicked = True
                        log.debug("Ashby submit clicked via: %s", sel)
                        break
                except Exception:
                    continue
            
            if not submit_clicked:
                # Ashby sometimes uses a multi-step form - try to find next/continue button
                for sel in ("button:has-text('Next'), button:has-text('Continue'), [class*='next']"):
                    try:
                        btn = page.locator(sel).first
                        if btn.count() > 0 and btn.is_visible(timeout=2000):
                            btn.click(timeout=3000)
                            submit_clicked = True
                            log.info("Ashby 'Next' button clicked (multi-step form)")
                            break
                    except Exception:
                        continue
            
            if not submit_clicked:
                log.warning("Ashby submit not found, trying Enter key")
                page.keyboard.press('Enter')
            
            page.wait_for_load_state("networkidle", timeout=15000)
            log.info("Ashby submitted for job %d", job_id)
        else:
            log.info("Ashby filled (dry run) for job %d", job_id)

        return _make_application(job_id, self.resume_path, "easy_apply",
                                 notes="" if self.submit else "dry_run")


# ── Form-filling helpers ────────────────────────────────────────────────────────

def _click_visible_option(page, answer: str, label: str = "",
                           decline_fallback: bool = False) -> bool:
    """
    After a dropdown/flyout has been opened, find and click the option that
    best matches `answer`.

    DEBUG MODE: all strategies are probed and logged before the first
    successful one is clicked.  Saves a screenshot to logs/screenshots/ so
    the actual rendered dropdown can be inspected.

    Strategy order:
      A. Native <select> via select_option()   ← handles hidden/styled selects
      B. Playwright ARIA get_by_role()
      C. CSS locators (li / button / class-based) + is_visible()
      D. JS getBoundingClientRect() viewport scan  ← catches React portals
      E. Decline / prefer-not fallback (EEO only)
    """
    page.wait_for_timeout(900)
    answer_lower = (answer or "").lower().strip()

    # ── Screenshot for debugging ──────────────────────────────────────────────
    try:
        scr_dir = config.ROOT_DIR / "logs" / "screenshots"
        scr_dir.mkdir(parents=True, exist_ok=True)
        safe = label.replace("'", "").replace(" ", "_").replace("[","").replace("]","")
        page.screenshot(path=str(scr_dir / f"{safe}_open.png"), full_page=False)
        log.info("  %s screenshot saved", label)
    except Exception as _se:
        log.debug("  %s screenshot failed: %s", label, _se)

    # ── Full DOM dump (always runs — shows what's actually there) ─────────────
    dom_dump: list = page.evaluate("""() => {
        // Cast the widest possible net: every conceivable option element type
        const tags = [
            'option', 'li', 'button',
            '[role="option"]', '[role="menuitem"]', '[role="listitem"]',
            '[role="listbox"] *', '[role="menu"] *',
            '[class*="option"]', '[class*="item"]', '[class*="choice"]',
            '[class*="list-item"]', '[class*="flyout"]',
            '[data-value]', '[data-option]', '[tabindex]',
        ].join(', ');
        return [...document.querySelectorAll(tags)]
            .map(e => {
                const r = e.getBoundingClientRect();
                return {
                    tag:     e.tagName,
                    role:    e.getAttribute('role') || '',
                    cls:     e.className.slice(0, 60),
                    text:    e.textContent.trim().slice(0, 60),
                    visible: r.width > 0 && r.height > 0
                               && r.top < window.innerHeight && r.top >= -20,
                    val:     e.value || e.getAttribute('data-value') || '',
                };
            })
            .filter(e => e.text);          // drop empties
    }""")
    vis_dump  = [d for d in dom_dump if d["visible"]]
    all_texts = [d["text"] for d in vis_dump]
    log.info("  %s DOM dump — %d visible option-like elements: %s",
             label, len(vis_dump), all_texts[:20])

    # ── Helper: try clicking an element found by locator ─────────────────────
    def _try_click(loc, strategy_name: str) -> bool:
        try:
            vis = [el for el in loc.all() if el.is_visible()]
            if vis:
                vis[0].click()
                log.info("  %s CLICKED via %s: '%s'", label, strategy_name, answer)
                return True
        except Exception as exc:
            log.debug("  %s %s exception: %s", label, strategy_name, exc)
        return False

    clicked = False

    # ── A. Native <select> ────────────────────────────────────────────────────
    if answer_lower and not clicked:
        for sel_el in page.locator("select").all():
            try:
                opts = sel_el.locator("option").all_text_contents()
                match = next((o for o in opts
                              if answer_lower in o.lower() or o.lower() in answer_lower),
                             None)
                if match:
                    sel_el.select_option(label=match)
                    log.info("  %s CLICKED via native <select>: '%s'", label, match)
                    clicked = True
                    break
            except Exception:
                continue

    # ── B. ARIA get_by_role() ─────────────────────────────────────────────────
    if answer_lower and not clicked:
        for role, kw in (("option", answer), ("menuitem", answer),
                         ("listitem", answer), ("option", "")):
            loc = (page.get_by_role(role, name=kw, exact=True) if kw
                   else page.get_by_role(role).filter(has_text=answer))
            if _try_click(loc, f"ARIA[{role}]"):
                clicked = True
                break

    # ── C. CSS locators + is_visible() ────────────────────────────────────────
    _CSS = (
        "li", "button",
        "[role='option']", "[role='menuitem']", "[role='listitem']",
        "ul > *", "[class*='option']", "[class*='item']",
        "[class*='choice']", "[class*='list-item']", "[class*='flyout']",
        "span[tabindex]", "div[tabindex]",
    )
    if answer_lower and not clicked:
        for sel in _CSS:
            loc = page.locator(sel).filter(has_text=answer)
            if _try_click(loc, f"CSS[{sel}]"):
                clicked = True
                break

    # ── D. JS viewport scan — fuzzy text match ────────────────────────────────
    if answer_lower and not clicked:
        # exact match first, then substring
        matched_text = None
        for d in vis_dump:
            if d["text"].lower() == answer_lower:
                matched_text = d["text"]
                break
        if not matched_text:
            for d in vis_dump:
                t = d["text"].lower()
                if answer_lower in t or t in answer_lower:
                    matched_text = d["text"]
                    break
        if matched_text:
            for sel in _CSS:
                loc = page.locator(sel).filter(has_text=matched_text)
                if _try_click(loc, f"JS-fuzzy[{sel}]"):
                    clicked = True
                    break

    # ── E. Decline / prefer-not fallback ─────────────────────────────────────
    if not clicked and decline_fallback:
        _DECLINE = ("decline", "prefer not", "do not wish", "i don't want",
                    "choose not", "not specified", "prefer to self-describe",
                    "i do not want to answer")
        for d in vis_dump:
            t = d["text"].lower()
            if any(ph in t for ph in _DECLINE):
                for sel in _CSS:
                    loc = page.locator(sel).filter(has_text=d["text"][:30])
                    if _try_click(loc, f"decline-fallback[{sel}]"):
                        clicked = True
                        break
            if clicked:
                break

    if not clicked:
        log.warning("  %s ALL strategies failed for '%s' — pressing Escape",
                    label, answer)
        page.keyboard.press("Escape")

    return clicked


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


def _gh_label_fill(page, label: str, value: str, exact: bool = False) -> None:
    """Fill a labeled text/email input on a new-style Greenhouse form."""
    if not value:
        return
    try:
        loc = page.get_by_label(label, exact=exact)
        if loc.count() == 0:
            return
        loc.first.click()
        _pause(0.1, 0.3)
        loc.first.fill(value)
        _pause(*_SHORT)
    except Exception as e:
        log.debug("Could not fill label '%s': %s", label, e)


def _gh_flyout_select(page, label_fragment: str, option_text: str) -> None:
    """
    Handle Greenhouse custom flyout dropdowns (used for years-exp, demographics, etc.).
    Finds any group/section whose label contains label_fragment, clicks the
    Toggle flyout, then selects the matching option.
    """
    if not option_text:
        return
    try:
        # Walk all <select> elements first (EEO section sometimes uses native selects)
        for sel in page.locator("select").all():
            try:
                # Check if a nearby label matches
                sel_id = sel.get_attribute("id") or ""
                sel_name = sel.get_attribute("name") or ""
                label_els = page.locator(f"label[for='{sel_id}']")
                label_text = label_els.first.text_content() if label_els.count() > 0 else ""
                if label_fragment.lower() in (label_text + sel_id + sel_name).lower():
                    opts = sel.locator("option").all_text_contents()
                    match = next(
                        (o for o in opts if option_text.lower() in o.lower()), None
                    )
                    if match:
                        _pause(*_SHORT)
                        sel.select_option(label=match)
                        return
            except Exception:
                continue

        # Try flyout toggle widget
        # Strategy: find Toggle flyout buttons inside groups/divs that contain label_fragment
        toggles = page.get_by_label("Toggle flyout").all()
        for toggle in toggles:
            try:
                parent = toggle.locator("xpath=ancestor::div[contains(@class,'field') "
                                        "or contains(@class,'question') "
                                        "or contains(@class,'form-field')][1]")
                if parent.count() == 0:
                    parent = toggle.locator("xpath=ancestor::div[3]")
                parent_text = parent.first.text_content() or ""
                if label_fragment.lower() in parent_text.lower():
                    _pause(*_SHORT)
                    toggle.click()
                    _pause(0.3, 0.6)
                    opt = page.get_by_role("option", name=option_text, exact=True)
                    if opt.count() == 0:
                        # Partial match
                        opt = page.get_by_role("option").filter(
                            has_text=option_text)
                    if opt.count() > 0:
                        opt.first.click()
                        _pause(*_SHORT)
                        return
                    # If option not found, press Escape to close flyout
                    page.keyboard.press("Escape")
            except Exception:
                continue
    except Exception as e:
        log.debug("Flyout select error for '%s': %s", label_fragment, e)


def _fill_eeo_selects(page) -> None:
    """
    For classic Greenhouse forms: fill EEO demographic <select> elements
    with the applicant's personal answers where possible, otherwise decline.
    """
    answer_map = {
        "gender":      config.APPLICANT_GENDER,
        "race":        config.APPLICANT_RACE,
        "ethnicity":   config.APPLICANT_RACE,
        "veteran":     config.APPLICANT_VETERAN_STATUS,
        "disability":  config.APPLICANT_DISABILITY,
        "orientation": config.APPLICANT_ORIENTATION,
    }
    for sel in page.locator("select").all():
        try:
            sel_id   = (sel.get_attribute("id")   or "").lower()
            sel_name = (sel.get_attribute("name") or "").lower()
            opts = sel.locator("option").all_text_contents()

            # Try to match a known answer
            chosen = None
            for keyword, answer in answer_map.items():
                if keyword in sel_id or keyword in sel_name:
                    match = next(
                        (o for o in opts if answer.lower() in o.lower()), None
                    )
                    if match:
                        chosen = match
                        break

            # Fallback: decline / prefer not to say
            if not chosen:
                chosen = next(
                    (o for o in opts
                     if any(w in o.lower() for w in
                            ("decline", "prefer not", "do not wish"))),
                    None,
                )

            if chosen:
                _pause(*_SHORT)
                sel.select_option(label=chosen)
        except Exception:
            pass


def _make_application(job_id: int, resume_path: Optional[Path],
                      method: str, notes: str = "") -> Application:
    return Application(
        job_id=job_id,
        resume_path=str(resume_path) if resume_path else "",
        applied_at=datetime.utcnow().isoformat(),
        method=method,
        notes=notes,
    )
