# modules/scraper/weworkremotely.py
# We Work Remotely — scrapes their public RSS feeds (no API key required).
# Category feeds: https://weworkremotely.com/categories/{slug}/jobs.rss

from __future__ import annotations
import xml.etree.ElementTree as ET
from datetime import datetime
from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config
import re

log = config.get_logger(__name__)

# RSS feeds covering data / analytics / backend roles
_FEEDS = [
    "https://weworkremotely.com/categories/remote-data-science-jobs/jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs/jobs.rss",
    "https://weworkremotely.com/categories/remote-management-and-finance-jobs/jobs.rss",
]


class WeWorkRemotelyScraper(BaseScraper):
    source = "weworkremotely"

    def scrape(self, keyword: str = "", location: str = "",
               max_results: int = 50) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()

        for feed_url in _FEEDS:
            if len(jobs) >= max_results:
                break
            resp = self._safe_get(feed_url, headers={"Accept": "application/rss+xml"})
            if not resp:
                continue
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError:
                log.warning("WWR: failed to parse RSS from %s", feed_url)
                continue

            for item in root.iter("item"):
                if len(jobs) >= max_results:
                    break

                title = _text(item, "title")
                link  = _text(item, "link")
                guid  = _text(item, "guid") or link

                if not title or guid in seen:
                    continue
                seen.add(guid)

                if keyword and keyword.lower() not in title.lower():
                    continue

                # WWR embeds company in title as "Company: Job Title"
                parts   = title.split(":", 1)
                company = parts[0].strip() if len(parts) == 2 else ""
                job_title = parts[1].strip() if len(parts) == 2 else title

                desc  = _strip_html(_text(item, "description") or "")
                pub   = (_text(item, "pubDate") or "")[:16]

                jobs.append(Job(
                    source="weworkremotely",
                    external_id=guid,
                    title=job_title,
                    company=company,
                    location="Remote",
                    work_type="remote",
                    url=link,
                    description_raw=desc,
                    posted_date=pub[:10] if pub else None,
                    scraped_at=datetime.utcnow().isoformat(),
                ))

        log.info("WeWorkRemotely: %d jobs scraped", len(jobs))
        return jobs


def _text(el, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()
