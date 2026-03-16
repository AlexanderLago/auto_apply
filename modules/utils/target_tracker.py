# modules/utils/target_tracker.py
# Tracks job openings at target remote-first companies
# Monitors specific job titles at curated companies

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import config

log = config.get_logger(__name__)

# ── Target Companies Configuration ──────────────────────────────────────────────

TARGET_COMPANIES = {
    # Fully Remote / Remote-First
    "GitLab": {"type": "remote-first", "careers_url": "https://about.gitlab.com/jobs/"},
    "Automattic": {"type": "remote-first", "careers_url": "https://automattic.com/work-with-us/"},
    "Zapier": {"type": "remote-first", "careers_url": "https://zapier.com/jobs/"},
    "Doist": {"type": "remote-first", "careers_url": "https://doist.com/careers/"},
    "DuckDuckGo": {"type": "remote-first", "careers_url": "https://duckduckgo.com/hiring/"},
    
    # Remote-Friendly Tech
    "Atlassian": {"type": "remote-friendly", "careers_url": "https://www.atlassian.com/company/careers"},
    "Shopify": {"type": "remote-friendly", "careers_url": "https://www.shopify.com/careers"},
    "Airbnb": {"type": "remote-friendly", "careers_url": "https://careers.airbnb.com/"},
    "Dropbox": {"type": "remote-friendly", "careers_url": "https://www.dropbox.com/jobs"},
    
    # Fintech
    "Stripe": {"type": "fintech", "careers_url": "https://stripe.com/jobs"},
    "Plaid": {"type": "fintech", "careers_url": "https://plaid.com/careers/"},
    "Ramp": {"type": "fintech", "careers_url": "https://ramp.com/careers"},
    "Brex": {"type": "fintech", "careers_url": "https://www.brex.com/careers"},
    "Mercury": {"type": "fintech", "careers_url": "https://mercury.com/careers"},
}

TARGET_JOB_TITLES = [
    "Analytics Engineer",
    "Product Data Analyst",
    "Decision Scientist",
    "Data Platform Analyst",
    "Data Engineer",
    "Quantitative Analyst",
    "Risk Data Analyst",
    "Applied Data Scientist",
]

# Keywords for each job title (for matching)
TITLE_KEYWORDS = {
    "Analytics Engineer": ["analytics engineer", "analytics engineer", "bi engineer", "data analytics engineer"],
    "Product Data Analyst": ["product data analyst", "product analyst", "product analytics"],
    "Decision Scientist": ["decision scientist", "decision science", "business decision"],
    "Data Platform Analyst": ["data platform", "platform data", "data infrastructure"],
    "Data Engineer": ["data engineer", "data engineering", "etl engineer", "data pipeline"],
    "Quantitative Analyst": ["quantitative analyst", "quant analyst", "quant", "quantitative researcher"],
    "Risk Data Analyst": ["risk analyst", "risk data", "financial risk", "credit risk"],
    "Applied Data Scientist": ["applied scientist", "applied data scientist", "data scientist"],
}

# ── Tracker State File ──────────────────────────────────────────────────────────

TRACKER_STATE_FILE = config.ROOT_DIR / "data" / "target_tracker_state.json"


def _load_state() -> dict:
    """Load tracker state from file."""
    if TRACKER_STATE_FILE.exists():
        with open(TRACKER_STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "last_check": None,
        "tracked_jobs": [],
        "applied_jobs": [],
        "companies_enabled": list(TARGET_COMPANIES.keys()),
        "titles_enabled": TARGET_JOB_TITLES,
    }


def _save_state(state: dict) -> None:
    """Save tracker state to file."""
    TRACKER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACKER_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ── Tracker Functions ───────────────────────────────────────────────────────────

def add_tracked_job(
    company: str,
    title: str,
    url: str,
    location: str = "Remote",
    source: str = "manual",
    notes: str = ""
) -> dict:
    """Add a job to the tracked list."""
    state = _load_state()
    
    job = {
        "id": f"{company.lower().replace(' ', '')}-{title.lower().replace(' ', '-')}-{datetime.now().strftime('%Y%m%d')}",
        "company": company,
        "title": title,
        "url": url,
        "location": location,
        "source": source,
        "notes": notes,
        "date_added": datetime.now().isoformat(),
        "date_applied": None,
        "status": "tracking",  # tracking, applied, interviewed, rejected, offer
        "company_type": TARGET_COMPANIES.get(company, {}).get("type", "unknown"),
    }
    
    # Check for duplicates
    for existing in state["tracked_jobs"]:
        if existing["company"] == company and existing["title"] == title and existing["status"] == "tracking":
            log.warning(f"Job already tracked: {title} at {company}")
            return existing
    
    state["tracked_jobs"].append(job)
    state["last_check"] = datetime.now().isoformat()
    _save_state(state)
    
    log.info(f"Added tracked job: {title} at {company}")
    return job


def remove_tracked_job(job_id: str) -> bool:
    """Remove a job from tracking."""
    state = _load_state()
    
    initial_count = len(state["tracked_jobs"])
    state["tracked_jobs"] = [j for j in state["tracked_jobs"] if j["id"] != job_id]
    
    if len(state["tracked_jobs"]) < initial_count:
        _save_state(state)
        log.info(f"Removed tracked job: {job_id}")
        return True
    
    return False


def update_job_status(job_id: str, status: str, notes: str = "") -> bool:
    """Update the status of a tracked job."""
    state = _load_state()
    
    for job in state["tracked_jobs"]:
        if job["id"] == job_id:
            job["status"] = status
            if notes:
                job["notes"] = notes
            if status == "applied":
                job["date_applied"] = datetime.now().isoformat()
            _save_state(state)
            log.info(f"Updated job {job_id} status to {status}")
            return True
    
    return False


def get_tracked_jobs(status: Optional[str] = None, company: Optional[str] = None) -> List[dict]:
    """Get all tracked jobs, optionally filtered."""
    state = _load_state()
    jobs = state["tracked_jobs"]
    
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    
    if company:
        jobs = [j for j in jobs if j["company"] == company]
    
    return sorted(jobs, key=lambda x: x["date_added"], reverse=True)


def get_tracker_stats() -> dict:
    """Get statistics about tracked jobs."""
    state = _load_state()
    jobs = state["tracked_jobs"]
    
    stats = {
        "total_tracking": len([j for j in jobs if j["status"] == "tracking"]),
        "total_applied": len([j for j in jobs if j["status"] == "applied"]),
        "total_interviews": len([j for j in jobs if j["status"] == "interview"]),
        "total_offers": len([j for j in jobs if j["status"] == "offer"]),
        "total_rejected": len([j for j in jobs if j["status"] == "rejected"]),
        "by_company": {},
        "by_title": {},
        "by_type": {},
    }
    
    # Count by company
    for job in jobs:
        company = job["company"]
        if company not in stats["by_company"]:
            stats["by_company"][company] = 0
        stats["by_company"][company] += 1
        
        # Count by title
        title = job["title"]
        if title not in stats["by_title"]:
            stats["by_title"][title] = 0
        stats["by_title"][title] += 1
        
        # Count by company type
        company_type = job.get("company_type", "unknown")
        if company_type not in stats["by_type"]:
            stats["by_type"][company_type] = 0
        stats["by_type"][company_type] += 1
    
    return stats


def get_enabled_companies() -> List[str]:
    """Get list of enabled companies for tracking."""
    state = _load_state()
    return state.get("companies_enabled", list(TARGET_COMPANIES.keys()))


def get_enabled_titles() -> List[str]:
    """Get list of enabled job titles for tracking."""
    state = _load_state()
    return state.get("titles_enabled", TARGET_JOB_TITLES)


def toggle_company(company: str, enabled: bool) -> None:
    """Enable or disable tracking for a company."""
    state = _load_state()
    
    if enabled:
        if company not in state["companies_enabled"]:
            state["companies_enabled"].append(company)
    else:
        if company in state["companies_enabled"]:
            state["companies_enabled"].remove(company)
    
    _save_state(state)


def toggle_title(title: str, enabled: bool) -> None:
    """Enable or disable tracking for a job title."""
    state = _load_state()
    
    if enabled:
        if title not in state["titles_enabled"]:
            state["titles_enabled"].append(title)
    else:
        if title in state["titles_enabled"]:
            state["titles_enabled"].remove(title)
    
    _save_state(state)


def match_job_title(title: str) -> Optional[str]:
    """
    Check if a job title matches one of our target titles.
    Returns the matched target title or None.
    """
    title_lower = title.lower()
    
    for target_title, keywords in TITLE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in title_lower:
                return target_title
    
    # Also check exact match
    for target_title in TARGET_JOB_TITLES:
        if target_title.lower() in title_lower or title_lower in target_title.lower():
            return target_title
    
    return None


def is_target_company(company: str) -> bool:
    """Check if a company is in our target list."""
    company_normalized = company.lower().replace(' ', '').replace('-', '').replace('.', '')
    
    for target in TARGET_COMPANIES.keys():
        target_normalized = target.lower().replace(' ', '').replace('-', '').replace('.', '')
        if company_normalized == target_normalized or target_normalized in company_normalized:
            return True
    
    return False


def get_company_info(company: str) -> Optional[dict]:
    """Get information about a target company."""
    company_normalized = company.lower().replace(' ', '').replace('-', '').replace('.', '')
    
    for target, info in TARGET_COMPANIES.items():
        target_normalized = target.lower().replace(' ', '').replace('-', '').replace('.', '')
        if company_normalized == target_normalized or target_normalized in company_normalized:
            return {
                "name": target,
                "type": info["type"],
                "careers_url": info["careers_url"],
            }
    
    return None


# ── Quick Add Form Data ─────────────────────────────────────────────────────────

def get_quick_add_options() -> dict:
    """Get options for quick add job form."""
    return {
        "companies": list(TARGET_COMPANIES.keys()),
        "titles": TARGET_JOB_TITLES,
        "company_types": list(set(info["type"] for info in TARGET_COMPANIES.values())),
    }
