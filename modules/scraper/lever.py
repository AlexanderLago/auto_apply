# modules/scraper/lever.py
# Lever also has a public JSON API — no auth, no browser needed.
# Docs: https://hire.lever.co/developer/postings

from __future__ import annotations
from datetime import datetime
from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

_API = "https://api.lever.co/v0/postings/{company}"


class LeverScraper(BaseScraper):
    source = "lever"

    def __init__(self, company_slug: str):
        self.company_slug = company_slug

    def scrape(self, keyword: str = "", location: str = "", max_results: int = 50) -> list[Job]:
        params = {"mode": "json", "limit": max_results}
        if location:
            params["location"] = location

        resp = self._safe_get(_API.format(company=self.company_slug), params=params)
        if not resp:
            return []

        jobs = []
        for item in resp.json()[:max_results]:
            title = item.get("text", "")
            if keyword and keyword.lower() not in title.lower():
                continue

            cats   = item.get("categories", {})
            loc    = cats.get("location", "")
            commit = cats.get("commitment", "")       # 'Full-time', 'Part-time', etc.

            description = _flatten_lists(item.get("lists", []))

            jobs.append(Job(
                source=self.source,
                external_id=item.get("id", ""),
                title=title,
                company=self.company_slug,
                location=loc,
                work_type=_infer_work_type(loc + " " + commit),
                url=item.get("hostedUrl", ""),
                description_raw=description,
                posted_date=None,
                scraped_at=datetime.utcnow().isoformat(),
            ))

        log.info("Lever [%s]: %d jobs scraped", self.company_slug, len(jobs))
        return jobs


def _flatten_lists(lists: list[dict]) -> str:
    """Convert Lever's content list objects to plain text."""
    parts = []
    for section in lists:
        parts.append(section.get("text", ""))
        for item in section.get("content", "").split("<br>"):
            parts.append(f"- {item.strip()}")
    return "\n".join(parts)


def _infer_work_type(text: str) -> str:
    t = text.lower()
    if "remote" in t:
        return "remote"
    if "hybrid" in t:
        return "hybrid"
    return "onsite"
