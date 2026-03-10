# modules/scraper/jobspy_scraper.py
# python-jobspy covers Indeed, ZipRecruiter, and Glassdoor in one call.
# Install: pip install python-jobspy
# Docs:    https://github.com/Bunsly/JobSpy

from __future__ import annotations
from datetime import datetime
from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)


class JobSpyScraper(BaseScraper):
    """
    Scrapes Indeed and ZipRecruiter via the jobspy library.
    site_name choices: "indeed", "zip_recruiter", "glassdoor", "google"
    """
    source = "jobspy"

    def __init__(self, sites: list[str] | None = None):
        self.sites = sites or ["indeed", "zip_recruiter"]

    def scrape(self, keyword: str = "", location: str = "",
               max_results: int = 50) -> list[Job]:
        try:
            from jobspy import scrape_jobs
        except ImportError:
            log.warning("jobspy not installed — run: pip install python-jobspy")
            return []

        kw  = keyword  or "data analyst"
        loc = location or "remote"

        try:
            df = scrape_jobs(
                site_name=self.sites,
                search_term=kw,
                location=loc,
                results_wanted=max_results,
                hours_old=72,             # only jobs from last 3 days
                country_indeed="USA",
                is_remote=("remote" in loc.lower()),
                verbose=0,
            )
        except Exception as e:
            log.warning("jobspy scrape error: %s", e)
            return []

        if df is None or df.empty:
            return []

        jobs = []
        for _, row in df.iterrows():
            title   = str(row.get("title", ""))
            company = str(row.get("company", ""))
            loc_val = str(row.get("location", ""))
            url     = str(row.get("job_url", ""))
            desc    = str(row.get("description", "") or "")
            source  = str(row.get("site", "jobspy")).lower()
            ext_id  = str(row.get("id", url))

            is_remote = str(row.get("is_remote", "")).lower() in ("true", "1", "yes")
            work_type = "remote" if is_remote else _infer_work_type(loc_val + " " + desc[:200])

            posted = None
            date_posted = row.get("date_posted")
            if date_posted and str(date_posted) != "nan":
                posted = str(date_posted)[:10]

            if not title or not url:
                continue

            jobs.append(Job(
                source=source,            # "indeed", "zip_recruiter", etc.
                external_id=ext_id,
                title=title,
                company=company,
                location=loc_val,
                work_type=work_type,
                url=url,
                description_raw=desc,
                posted_date=posted,
                scraped_at=datetime.utcnow().isoformat(),
            ))

        log.info("jobspy [%s]: %d jobs scraped for '%s'",
                 "+".join(self.sites), len(jobs), kw)
        return jobs


def _infer_work_type(text: str) -> str:
    t = text.lower()
    if "remote" in t:
        return "remote"
    if "hybrid" in t:
        return "hybrid"
    return "onsite"
