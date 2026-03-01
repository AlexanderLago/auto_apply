# modules/scraper/usajobs.py
# USAJobs public API — free, requires a free API key from developer.usajobs.gov
# Highly relevant for data governance / federal financial institution backgrounds.
#
# To get a free API key: https://developer.usajobs.gov/apirequest/
# Add to .env: USAJOBS_API_KEY=your_key   USAJOBS_EMAIL=your@email.com

from __future__ import annotations
from datetime import datetime
from typing import List

from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

_API = "https://data.usajobs.gov/api/search"


class USAJobsScraper(BaseScraper):
    source = "usajobs"

    def scrape(self, keyword: str = "", location: str = "",
               max_results: int = 50) -> List[Job]:
        if not config.USAJOBS_API_KEY or not config.USAJOBS_EMAIL:
            log.info("USAJobs skipped — set USAJOBS_API_KEY and USAJOBS_EMAIL in .env")
            return []

        headers = {
            "Host":              "data.usajobs.gov",
            "User-Agent":        config.USAJOBS_EMAIL,
            "Authorization-Key": config.USAJOBS_API_KEY,
        }
        params = {"ResultsPerPage": min(max_results, 50)}
        if keyword:
            params["Keyword"] = keyword
        if location:
            params["LocationName"] = location

        resp = self._safe_get(_API, headers=headers, params=params)
        if not resp:
            return []

        try:
            items = resp.json()["SearchResult"]["SearchResultItems"]
        except (KeyError, TypeError) as e:
            log.warning("USAJobs response parse error: %s", e)
            return []

        jobs = []
        for item in items[:max_results]:
            mv = item.get("MatchedObjectDescriptor", {})
            title       = mv.get("PositionTitle", "")
            company     = mv.get("OrganizationName", "")
            loc_list    = mv.get("PositionLocation", [{}])
            loc         = loc_list[0].get("LocationName", "") if loc_list else ""
            url         = mv.get("PositionURI", "")
            description = mv.get("QualificationSummary", "") or mv.get("UserArea", {}).get("Details", {}).get("JobSummary", "")
            posted      = mv.get("PublicationStartDate", "")[:10] if mv.get("PublicationStartDate") else None

            # Salary
            salary_ranges = mv.get("PositionRemuneration", [{}])
            sal = salary_ranges[0] if salary_ranges else {}
            sal_min = _to_float(sal.get("MinimumRange"))
            sal_max = _to_float(sal.get("MaximumRange"))

            # Work type
            schedule = mv.get("PositionSchedule", [{}])
            sched_str = schedule[0].get("Name", "").lower() if schedule else ""
            work_type = "remote" if "telework" in description.lower() else "onsite"

            ext_id = mv.get("PositionID", url)

            jobs.append(Job(
                source=self.source,
                external_id=ext_id,
                title=title,
                company=company,
                location=loc,
                work_type=work_type,
                url=url,
                description_raw=description,
                salary_min=sal_min,
                salary_max=sal_max,
                posted_date=posted,
                scraped_at=datetime.utcnow().isoformat(),
            ))

        log.info("USAJobs: %d jobs scraped", len(jobs))
        return jobs


def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
