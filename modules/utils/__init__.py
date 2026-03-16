# modules/utils/__init__.py
"""
Utility Modules — Helper functions for auto_apply

## Components

### email_reader.py — Verification Code Reader
Reads Gmail inbox via IMAP to extract verification codes from application confirmation emails.

**Usage:**
```python
from modules.utils.email_reader import get_verification_code

code = get_verification_code(
    keywords=["greenhouse", "verify", "security code"],
    timeout=90,
    since_timestamp=submit_time,
    recipient_email="applicant@email.com"
)
```

**Features:**
- Filters by recipient email (To: header)
- Time-based filtering (only emails after submit)
- Pattern matching for 6-8 character codes
- Debug logging for troubleshooting

### location_filter.py — Job Location Filtering
Filters jobs based on location preferences.

**Logic:**
- Remote jobs: Always accepted (anywhere)
- Hybrid/Onsite: Only NYC or NJ metro area

**Usage:**
```python
from modules.utils.location_filter import filter_jobs, is_target_location

target_jobs = filter_jobs(all_jobs)
if is_target_location(job_row):
    print("Job matches location preferences")
```

**NYC/NJ Terms:**
- NYC: Manhattan, Brooklyn, Queens, Bronx, Staten Island, etc.
- NJ: Jersey City, Hoboken, Newark, Princeton, etc.
"""

from modules.utils.email_reader import get_verification_code
from modules.utils.location_filter import filter_jobs, is_target_location, location_label
from modules.utils.target_tracker import (
    TARGET_COMPANIES,
    TARGET_JOB_TITLES,
    add_tracked_job,
    remove_tracked_job,
    update_job_status,
    get_tracked_jobs,
    get_tracker_stats,
    get_enabled_companies,
    get_enabled_titles,
    toggle_company,
    toggle_title,
    match_job_title,
    is_target_company,
    get_company_info,
    get_quick_add_options,
)

__all__ = [
    "get_verification_code",
    "filter_jobs",
    "is_target_location",
    "location_label",
    # Target tracker
    "TARGET_COMPANIES",
    "TARGET_JOB_TITLES",
    "add_tracked_job",
    "remove_tracked_job",
    "update_job_status",
    "get_tracked_jobs",
    "get_tracker_stats",
    "get_enabled_companies",
    "get_enabled_titles",
    "toggle_company",
    "toggle_title",
    "match_job_title",
    "is_target_company",
    "get_company_info",
    "get_quick_add_options",
]
