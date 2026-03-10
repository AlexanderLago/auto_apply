# modules/scraper/ashby.py
# Ashby has a public posting API — no auth required.
# API docs: https://developers.ashbyhq.com/reference/job-posting-api
#
# Common Ashby companies: notion, figma, linear, vercel, retool, ramp,
#   deel, mercury, posthog, dbtlabs, metabase, hex, scale, wandb, modal

from __future__ import annotations
from datetime import datetime
from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

_API = "https://api.ashbyhq.com/posting-api/job-board/{company}"


class AshbyScraper(BaseScraper):
    source = "ashby"

    def __init__(self, company: str):
        self.company = company

    def scrape(self, keyword: str = "", location: str = "",
               max_results: int = 50) -> list[Job]:
        url  = _API.format(company=self.company)
        resp = self._safe_get(url)
        if not resp:
            return []

        data = resp.json()
        jobs = []
        for item in data.get("jobs", [])[:max_results]:
            title = item.get("title", "")
            if keyword and keyword.lower() not in title.lower():
                continue

            loc       = item.get("locationName", "") or ""
            is_remote = item.get("isRemote", False)
            work_type = "remote" if is_remote else _infer_work_type(loc)

            if location and location.lower() not in loc.lower() and not is_remote:
                continue

            # Ashby returns HTML description; strip tags for plain text storage
            desc_html  = item.get("descriptionHtml", "") or ""
            desc_plain = item.get("descriptionPlainText", "") or _strip_html(desc_html)

            posted = (item.get("publishedDate") or "")[:10] or None

            jobs.append(Job(
                source="ashby",
                external_id=item["id"],
                title=title,
                company=self.company,
                location=loc,
                work_type=work_type,
                url=item.get("jobUrl", ""),
                description_raw=desc_plain,
                posted_date=posted,
                scraped_at=datetime.utcnow().isoformat(),
            ))

        log.info("Ashby [%s]: %d jobs scraped", self.company, len(jobs))
        return jobs


def _infer_work_type(text: str) -> str:
    t = text.lower()
    if "remote" in t:
        return "remote"
    if "hybrid" in t:
        return "hybrid"
    return "onsite"


def _strip_html(html: str) -> str:
    """Minimal HTML tag stripper — avoids importing bs4 for a simple task."""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
