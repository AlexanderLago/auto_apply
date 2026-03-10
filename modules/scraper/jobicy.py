# modules/scraper/jobicy.py
# Jobicy free remote jobs API — no auth required.
# Docs: https://jobicy.com/jobs-rss-feed
# API:  https://jobicy.com/api/v0/jobs?count=N&geo=usa&industry=data&tag=analyst

from __future__ import annotations
from datetime import datetime
from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

_API = "https://jobicy.com/api/v0/jobs"


class JobicyScraper(BaseScraper):
    source = "jobicy"

    def scrape(self, keyword: str = "", location: str = "",
               max_results: int = 50) -> list[Job]:
        params = {
            "count":    min(max_results, 50),   # API max is 50
            "geo":      "usa",
            "industry": "data",
            "tag":      keyword or "data analyst",
        }
        resp = self._safe_get(_API, params=params)
        if not resp:
            return []

        jobs = []
        for item in resp.json().get("jobs", []):
            title = item.get("jobTitle", "")
            if keyword and keyword.lower() not in title.lower():
                continue

            geo       = item.get("jobGeo", "Worldwide")
            work_type = "remote" if geo.lower() in ("worldwide", "remote") else "onsite"

            posted = (item.get("pubDate") or "")[:10] or None

            jobs.append(Job(
                source="jobicy",
                external_id=str(item.get("id", "")),
                title=title,
                company=item.get("companyName", ""),
                location=geo,
                work_type=work_type,
                url=item.get("url", ""),
                description_raw=item.get("jobDescription", ""),
                posted_date=posted,
                scraped_at=datetime.utcnow().isoformat(),
            ))

        log.info("Jobicy: %d jobs scraped", len(jobs))
        return jobs
