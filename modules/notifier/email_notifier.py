# modules/notifier/email_notifier.py
# Sends a daily HTML email digest of top job matches.
#
# Setup (Gmail):
#   1. Enable 2FA on your Google account
#   2. Generate an App Password: myaccount.google.com → Security → App Passwords
#   3. Add to .env:
#        SMTP_HOST=smtp.gmail.com
#        SMTP_PORT=587
#        SMTP_USER=your@gmail.com
#        SMTP_PASS=your_app_password
#        NOTIFY_EMAIL=recipient@email.com  (can be same as SMTP_USER)

from __future__ import annotations
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict

import config

log = config.get_logger(__name__)


def send_digest(jobs: List[Dict], min_score: float = 65.0) -> bool:
    """
    Send an HTML email digest of top-scoring jobs.
    Returns True on success, False on any error.
    Silently skips if SMTP credentials are not configured.
    """
    if not all([config.SMTP_HOST, config.SMTP_USER, config.SMTP_PASS, config.NOTIFY_EMAIL]):
        log.info("Email digest skipped — SMTP credentials not configured in .env")
        return False

    top = [j for j in jobs if (j.get("fit_score") or 0) >= min_score]
    top.sort(key=lambda j: j.get("fit_score", 0), reverse=True)

    if not top:
        log.info("Email digest skipped — no jobs above score %.0f", min_score)
        return False

    subject = f"Auto Apply — {len(top)} top matches for {date.today()}"
    html    = _build_html(top)

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = config.SMTP_USER
        msg["To"]      = config.NOTIFY_EMAIL
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(config.SMTP_HOST, int(config.SMTP_PORT)) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASS)
            server.sendmail(config.SMTP_USER, config.NOTIFY_EMAIL, msg.as_string())

        log.info("Email digest sent to %s (%d jobs)", config.NOTIFY_EMAIL, len(top))
        return True
    except Exception as e:
        log.error("Email digest failed: %s", e)
        return False


def _build_html(jobs: List[Dict]) -> str:
    import json

    rows = ""
    for j in jobs:
        score = j.get("fit_score", 0)
        color = "#16a34a" if score >= 75 else "#ca8a04"
        bar_w = int(score)

        # Extract strengths/gaps from stored breakdown JSON
        strengths, gaps = [], []
        if j.get("fit_breakdown"):
            try:
                bd = json.loads(j["fit_breakdown"]) if isinstance(j["fit_breakdown"], str) \
                     else j["fit_breakdown"]
                strengths = bd.get("_strengths", [])
                gaps      = bd.get("_gaps", [])
            except Exception:
                pass

        str_html = "".join(f"<li style='color:#16a34a'>&#10003; {s}</li>" for s in strengths[:2])
        gap_html = "".join(f"<li style='color:#dc2626'>&#10007; {g}</li>" for g in gaps[:2])

        rows += f"""
        <tr>
          <td style='padding:16px;border-bottom:1px solid #e5e7eb;vertical-align:top'>
            <strong style='font-size:15px'>{j.get('title','')}</strong><br>
            <span style='color:#6b7280'>{j.get('company','')} &bull; {j.get('location','')} &bull; {j.get('work_type','')}</span><br>
            <div style='margin:6px 0;background:#e5e7eb;border-radius:4px;height:8px;width:200px'>
              <div style='background:{color};height:8px;border-radius:4px;width:{bar_w}%'></div>
            </div>
            <span style='font-weight:bold;color:{color}'>{score:.0f} / 100</span>
            &nbsp;&nbsp;
            <a href='{j.get("url","")}' style='color:#4f46e5;font-size:13px'>Apply &rarr;</a>
            <ul style='margin:6px 0 0 0;padding-left:18px;font-size:13px'>
              {str_html}{gap_html}
            </ul>
          </td>
        </tr>"""

    return f"""
    <html><body style='font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#111'>
      <h2 style='background:#4f46e5;color:white;padding:16px;border-radius:8px 8px 0 0;margin:0'>
        Auto Apply &mdash; Daily Job Digest
      </h2>
      <p style='padding:12px;background:#f9fafb;margin:0;border:1px solid #e5e7eb'>
        Found <strong>{len(jobs)}</strong> top matches today.
        Run <code>python main.py tailor</code> to generate tailored resumes.
      </p>
      <table style='width:100%;border-collapse:collapse'>
        {rows}
      </table>
      <p style='font-size:11px;color:#9ca3af;padding:12px'>
        Sent by auto_apply &bull; Run dashboard: <code>python main.py dashboard</code>
      </p>
    </body></html>"""
