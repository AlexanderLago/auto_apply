# modules/scraper/remotive.py
# RemoteOK public API — no auth, no rate limit, remote tech jobs only.
# API: https://remoteok.com/api
# Returns all remote jobs; keyword filter is applied client-side.

from __future__ import annotations
from datetime import datetime
from typing import List

from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

_API     = "https://remoteok.com/api"
_HEADERS = {"User-Agent": "auto_apply_bot/1.0 (job search automation)"}


class RemotiveScraper(BaseScraper):
    """Scrapes RemoteOK — all results are remote roles."""
    source = "remoteok"

    def scrape(self, keyword: str = "", location: str = "",
               max_results: int = 50) -> List[Job]:
        resp = self._safe_get(_API, headers=_HEADERS)
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception as e:
            log.warning("RemoteOK JSON parse error: %s", e)
            return []

        # API returns a list; first item is metadata dict (no 'position' key)
        raw_jobs = [j for j in data if isinstance(j, dict) and j.get("position")]

        jobs = []
        kw_lower = keyword.lower()
        for item in raw_jobs:
            title   = item.get("position", "")
            company = item.get("company", "")
            desc    = item.get("description", "") or ""
            tags    = " ".join(item.get("tags", []))

            # Client-side keyword filter across title + tags + description
            if kw_lower and kw_lower not in (title + tags + desc[:200]).lower():
                continue

            import re, html as html_mod
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = html_mod.unescape(desc)
            desc = re.sub(r"\s+", " ", desc).strip()

            url     = item.get("url", "")
            ext_id  = str(item.get("id", ""))
            posted  = item.get("date", "")[:10] if item.get("date") else None

            jobs.append(Job(
                source=self.source,
                external_id=ext_id,
                title=title,
                company=company,
                location="Remote",
                work_type="remote",
                url=f"https://remoteok.com{url}" if url.startswith("/") else url,
                description_raw=desc,
                posted_date=posted,
                scraped_at=datetime.utcnow().isoformat(),
            ))

            if len(jobs) >= max_results:
                break

        log.info("RemoteOK: %d jobs scraped (keyword=%r)", len(jobs), keyword)
        return jobs
