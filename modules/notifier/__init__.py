# modules/notifier/__init__.py
"""
Notifier Module — Email Notifications and Digests

This module sends email notifications for application updates.

## Components

### email_notifier.py — Email Digest Sender
Sends daily/weekly digest emails with top job matches.

**Features:**
- HTML formatted emails
- Top scored jobs of the day
- Application statistics
- Direct links to job postings

**Usage:**
```python
from modules.notifier.email_notifier import send_digest

send_digest(
    min_score=70,
    limit=10,
)
```

**Email Content:**
- Subject: "Auto Apply Digest — X jobs above score Y"
- Top jobs table (company, title, score, location)
- Application stats (total, pending, interviews)
- Quick action links

## Configuration

SMTP settings in `.env`:
```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=app-password
NOTIFY_EMAIL=recipient@gmail.com
```

**Note:** For Gmail, use an App Password (not your regular password):
1. Enable 2FA on Google account
2. Go to: myaccount.google.com/apppasswords
3. Generate app password for "Mail"
4. Use this password in SMTP_PASS

## Scheduled Digests

Run daily digest via cron/scheduled task:
```bash
# Daily at 8 AM
0 8 * * * cd /path/to/auto_apply && python -c "from modules.notifier import send_digest; send_digest()"
```

Or use Windows Task Scheduler with `monitor.bat`.
"""

from modules.notifier.email_notifier import send_digest

__all__ = ["send_digest"]
