# modules/utils/email_reader.py
# Polls Gmail inbox via IMAP and extracts verification codes from emails.
# Used by the apply bot to handle post-submit email verification steps.

from __future__ import annotations

import email
import imaplib
import re
import time
from email.header import decode_header
from typing import Optional

import config

log = config.get_logger(__name__)

_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993


def _decode_str(s) -> str:
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="ignore")
    return s or ""


def _get_text_body(msg) -> str:
    """Extract readable text from an email.Message (plain text or stripped HTML)."""
    import re as _re

    def _strip_html(html: str) -> str:
        # Remove style/script blocks entirely (CSS color codes live here)
        html = _re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=_re.DOTALL | _re.I)
        html = _re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=_re.DOTALL | _re.I)
        # Remove all remaining tags
        html = _re.sub(r'<[^>]+>', ' ', html)
        # Decode HTML entities
        html = html.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return html

    plain = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            decoded = payload.decode("utf-8", errors="ignore")
            if ct == "text/plain":
                plain += decoded
            elif ct == "text/html" and not plain:
                html += decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            ct = msg.get_content_type()
            decoded = payload.decode("utf-8", errors="ignore")
            if ct == "text/html":
                html = decoded
            else:
                plain = decoded

    return plain if plain.strip() else _strip_html(html)


def get_verification_code(
    keywords: list = None,
    code_pattern: str = r"\b(?=(?:[A-Za-z0-9]*\d){2})[A-Za-z0-9]{6,8}\b",
    timeout: int = 120,
    poll_interval: int = 8,
    since_timestamp: float = None,  # only accept emails received after this Unix time
    recipient_email: str = None,    # filter by recipient email (To: header)
) -> Optional[str]:
    """
    Poll Gmail inbox and return the first verification code found in a
    recent email matching any of the given keywords (checked in From + Subject + body).

    Args:
        keywords:        Strings to match against From/Subject/body (e.g. ["greenhouse", "chime"]).
                         Defaults to ["greenhouse", "verify", "verification", "confirm"].
        code_pattern:    Regex for the code to extract. Default: 6-digit number.
        timeout:         Total seconds to wait before giving up.
        poll_interval:   Seconds between inbox checks.
        since_timestamp: Only accept emails received after this Unix time (submit time).
        recipient_email: Filter by recipient email address (To: header).
                         Defaults to config.APPLICANT_EMAIL if not provided.

    Returns:
        The code string, or None if not found within timeout.
    """
    if not config.SMTP_USER or not config.SMTP_PASS:
        log.warning("Email verification skipped — SMTP credentials not set")
        return None

    if keywords is None:
        keywords = ["greenhouse", "verify", "verification", "confirm", "chime"]

    # Use applicant email as recipient filter if not specified
    if recipient_email is None:
        recipient_email = config.APPLICANT_EMAIL

    log.info("Waiting for verification email (timeout=%ds, recipient=%s)...", 
             timeout, recipient_email)
    deadline = time.time() + timeout
    
    # Track if we found any emails at all (for debugging)
    emails_checked = 0
    emails_skipped_recipient = 0

    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
            mail.login(config.SMTP_USER, config.SMTP_PASS)
            mail.select("inbox")

            # Search all emails received today (not just UNSEEN — code email may have
            # been fetched/read in a previous poll attempt)
            import datetime as _dt
            today = _dt.datetime.now().strftime("%d-%b-%Y")
            _, data = mail.search(None, f'(SINCE "{today}")')
            ids = data[0].split()

            for num in reversed(ids[-30:]):   # newest first, check more
                _, msg_data = mail.fetch(num, "(BODY.PEEK[])")  # PEEK avoids marking as read
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                
                emails_checked += 1

                # Check email Date header against since_timestamp
                if since_timestamp is not None:
                    import email.utils as _eu
                    date_str = msg.get("Date", "")
                    try:
                        msg_time = _eu.parsedate_to_datetime(date_str).timestamp()
                        if msg_time < since_timestamp - 30:  # 30s grace for clock skew
                            continue
                    except Exception:
                        pass  # Can't parse date — include it anyway

                from_addr = _decode_str(msg.get("From", "")).lower()
                
                # Check recipient (To: header) - CRITICAL FIX
                to_addr = _decode_str(msg.get("To", "")).lower()
                
                # Parse subject early for logging
                subject_parts = decode_header(msg.get("Subject", ""))
                subject = " ".join(
                    _decode_str(p[0]) if isinstance(p[0], bytes) else (p[0] or "")
                    for p in subject_parts
                ).lower()
                
                if recipient_email and recipient_email.lower() not in to_addr:
                    # Email was sent to a different address - skip it
                    log.debug("Skipping email to %s (looking for %s)", to_addr, recipient_email)
                    emails_skipped_recipient += 1
                    continue
                
                log.debug("Checking email: From=%s, To=%s, Subject=%s", 
                         from_addr[:50], to_addr[:50], subject[:50] if subject else "N/A")
                body = _get_text_body(msg).lower()
                combined = from_addr + " " + subject + " " + body

                if any(kw.lower() in combined for kw in keywords):
                    codes = re.findall(code_pattern, _get_text_body(msg))
                    if codes:
                        log.info("Verification code found: %s", codes[0])
                        mail.logout()
                        return codes[0]

            mail.logout()

        except Exception as e:
            log.warning("IMAP poll error: %s", e)

        remaining = deadline - time.time()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))
    
    # Log summary for debugging
    log.info("Email check complete: checked=%d, skipped_recipient=%d", 
             emails_checked, emails_skipped_recipient)

    log.warning("Verification code not found within %d seconds", timeout)
    return None
