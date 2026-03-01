# modules/scraper/greenhouse.py
# Greenhouse has a public JSON API — no auth, no browser needed.
# Docs: https://developers.greenhouse.io/job-board.html

from __future__ import annotations
from datetime import datetime
from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
_JOB = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"


class GreenhouseScraper(BaseScraper):
    source = "greenhouse"

    def __init__(self, board_token: str):
        self.board_token = board_token

    def scrape(self, keyword: str = "", location: str = "", max_results: int = 50) -> list[Job]:
        url = _API.format(token=self.board_token)
        resp = self._safe_get(url, params={"content": "true"})
        if not resp:
            return []

        jobs = []
        for item in resp.json().get("jobs", [])[:max_results]:
            title = item.get("title", "")
            # Basic keyword filter (API doesn't support server-side filtering)
            if keyword and keyword.lower() not in title.lower():
                continue

            loc = item.get("location", {}).get("name", "")
            if location and location.lower() not in loc.lower():
                continue

            posted = item.get("updated_at", "")[:10] if item.get("updated_at") else None

            jobs.append(Job(
                source=self.source,
                external_id=str(item["id"]),
                title=title,
                company=self.board_token,          # refined later if needed
                location=loc,
                work_type=_infer_work_type(title + " " + loc),
                url=item.get("absolute_url", ""),
                description_raw=item.get("content", ""),
                posted_date=posted,
                scraped_at=datetime.utcnow().isoformat(),
            ))

        log.info("Greenhouse [%s]: %d jobs scraped", self.board_token, len(jobs))
        return jobs


def _infer_work_type(text: str) -> str:
    t = text.lower()
    if "remote" in t:
        return "remote"
    if "hybrid" in t:
        return "hybrid"
    return "onsite"
