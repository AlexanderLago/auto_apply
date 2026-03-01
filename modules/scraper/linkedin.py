# modules/scraper/linkedin.py
# LinkedIn job scraper using the unofficial Voyager API (linkedin-api library).
#
# Setup:
#   pip install linkedin-api
#   Add to .env:  LINKEDIN_EMAIL=you@email.com  LINKEDIN_PASS=yourpassword
#
# Note: LinkedIn does not authorize scraping. Use a dedicated/throwaway account
# and keep limits low to avoid bans.  listed_at=86400 = jobs posted last 24 h.

from __future__ import annotations

import time
from datetime import datetime
from typing import List, Optional

from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

# Seconds to sleep between get_job() calls — keeps request rate human-like
_DETAIL_DELAY = 0.8


class LinkedInScraper(BaseScraper):
    source = "linkedin"

    def __init__(self):
        self._api = None

    # ── Auth (lazy, cached) ────────────────────────────────────────────────────

    def _get_api(self):
        if self._api is not None:
            return self._api
        if not config.LINKEDIN_EMAIL or not config.LINKEDIN_PASS:
            log.info("LinkedIn skipped — set LINKEDIN_EMAIL and LINKEDIN_PASS in .env")
            return None
        try:
            from linkedin_api import Linkedin
            self._api = Linkedin(config.LINKEDIN_EMAIL, config.LINKEDIN_PASS)
            return self._api
        except Exception as e:
            log.warning("LinkedIn auth failed: %s", e)
            return None

    # ── Public interface ───────────────────────────────────────────────────────

    def scrape(self, keyword: str = "", location: str = "",
               max_results: int = 50) -> List[Job]:
        api = self._get_api()
        if api is None:
            return []

        try:
            # listed_at=604800 → jobs posted in the last 7 days
            raw = api.search_jobs(
                keywords=keyword or None,
                location_name=location or None,
                limit=max_results,
                listed_at=604800,
            )
        except Exception as e:
            log.warning("LinkedIn search_jobs failed: %s", e)
            return []

        jobs = []
        for item in raw[:max_results]:
            try:
                job = self._parse(api, item)
                if job:
                    jobs.append(job)
                time.sleep(_DETAIL_DELAY)
            except Exception as e:
                log.warning("LinkedIn parse error: %s", e)

        log.info("LinkedIn: %d jobs scraped (keyword=%r)", len(jobs), keyword)
        return jobs

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _parse(self, api, item: dict) -> Optional[Job]:
        entity_urn = item.get("entityUrn", "")
        job_id = entity_urn.split(":")[-1] if entity_urn else ""
        if not job_id:
            return None

        # Fetch full detail for description + company name
        detail: dict = {}
        try:
            detail = api.get_job(job_id) or {}
        except Exception:
            pass

        title = detail.get("title") or item.get("title", "")

        # Company name lives in a deeply nested key
        company = self._extract_company(detail) or item.get("companyName", "")

        location = (detail.get("formattedLocation")
                    or item.get("formattedLocation", ""))

        # work_type
        work_remote = detail.get("workRemoteAllowed") or item.get("workRemoteAllowed", False)
        work_type = "remote" if work_remote else "onsite"

        # Description text
        desc = ""
        desc_obj = detail.get("description", {})
        if isinstance(desc_obj, dict):
            desc = desc_obj.get("text", "")
        elif isinstance(desc_obj, str):
            desc = desc_obj

        # Posted date from epoch ms
        listed_at = detail.get("listedAt") or item.get("listedAt")
        posted = None
        if listed_at:
            try:
                posted = datetime.utcfromtimestamp(int(listed_at) / 1000).strftime("%Y-%m-%d")
            except Exception:
                pass

        url = f"https://www.linkedin.com/jobs/view/{job_id}/"

        if not title or not company:
            return None

        return Job(
            source=self.source,
            external_id=job_id,
            title=title,
            company=company,
            location=location,
            work_type=work_type,
            url=url,
            description_raw=desc,
            posted_date=posted,
            scraped_at=datetime.utcnow().isoformat(),
        )

    @staticmethod
    def _extract_company(detail: dict) -> str:
        """LinkedIn nests company name inside companyDetails under a long key."""
        cd = detail.get("companyDetails", {})
        # Try both known key variants
        for key in (
            "com.linkedin.voyager.deco.jobs.web.shared.WebJobPostingCompany",
            "com.linkedin.voyager.jobs.JobPostingCompany",
        ):
            inner = cd.get(key, {})
            if inner:
                co = inner.get("company", {})
                if isinstance(co, dict):
                    name = co.get("name", "")
                    if name:
                        return name
                # sometimes it's a string under companyName
                name = inner.get("companyName", "") or inner.get("name", "")
                if name:
                    return name
        return ""
