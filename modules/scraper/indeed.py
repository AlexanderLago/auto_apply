# modules/scraper/indeed.py
# Scrapes Indeed via their public RSS feed (no API key, no auth needed).
# The RSS feed is query-based and returns recent job postings.
# URL: https://www.indeed.com/rss?q=QUERY&l=LOCATION&sort=date&fromage=3

from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

_RSS_URL = "https://www.indeed.com/rss"


class IndeedScraper(BaseScraper):
    source = "indeed"

    def scrape(self, keyword: str = "", location: str = "",
               max_results: int = 50) -> list[Job]:
        params = {
            "q":        keyword  or "data analyst",
            "l":        location or "remote",
            "sort":     "date",
            "fromage":  "7",    # last 7 days
            "limit":    min(max_results, 50),
        }
        # Indeed blocks default requests UA — spoof a browser
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        resp = self._safe_get(_RSS_URL, params=params, headers=headers)
        if not resp:
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            log.warning("Indeed: RSS parse error: %s", e)
            return []

        jobs = []
        for item in root.iter("item"):
            if len(jobs) >= max_results:
                break

            title   = _text(item, "title")
            link    = _text(item, "link")
            desc    = _strip_html(_text(item, "description"))
            pub     = _text(item, "pubDate")[:10] if _text(item, "pubDate") else None

            # Indeed embeds company + location in title: "Title - Company - Location"
            parts   = [p.strip() for p in title.split(" - ")]
            job_title = parts[0] if parts else title
            company   = parts[1] if len(parts) > 1 else ""
            loc       = parts[2] if len(parts) > 2 else location

            work_type = "remote" if "remote" in (loc + desc[:200]).lower() else \
                        "hybrid" if "hybrid" in (loc + desc[:200]).lower() else "onsite"

            if not link:
                continue

            jobs.append(Job(
                source="indeed",
                external_id=link,
                title=job_title,
                company=company,
                location=loc,
                work_type=work_type,
                url=link,
                description_raw=desc,
                posted_date=pub,
                scraped_at=datetime.utcnow().isoformat(),
            ))

        log.info("Indeed RSS: %d jobs scraped", len(jobs))
        return jobs


def _text(el, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()
