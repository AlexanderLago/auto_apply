# modules/scraper/adzuna.py
# Adzuna REST API — same integration as job_bot, reused here.
# Free tier: 25,000 requests/month.

from datetime import datetime
from modules.scraper.base import BaseScraper
from modules.tracker.models import Job
import config

log = config.get_logger(__name__)

_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


class AdzunaScraper(BaseScraper):
    source = "adzuna"

    def __init__(self, country: str = "us"):
        self.country = country
        self.app_id  = config.ADZUNA_APP_ID
        self.app_key = config.ADZUNA_APP_KEY

    def scrape(self, keyword: str = "", location: str = "", max_results: int = 50) -> list[Job]:
        if not self.app_id or not self.app_key:
            log.warning("Adzuna credentials not set — skipping")
            return []

        results_per_page = min(max_results, 50)
        params = {
            "app_id":           self.app_id,
            "app_key":          self.app_key,
            "results_per_page": results_per_page,
            "content-type":     "application/json",
        }
        if keyword:
            params["what"] = keyword
        if location:
            params["where"] = location

        resp = self._safe_get(_API.format(country=self.country, page=1), params=params)
        if not resp:
            return []

        jobs = []
        for item in resp.json().get("results", []):
            salary_min = item.get("salary_min")
            salary_max = item.get("salary_max")
            loc_obj    = item.get("location", {})
            loc_str    = loc_obj.get("display_name", "") if isinstance(loc_obj, dict) else ""
            company    = item.get("company", {})
            co_str     = company.get("display_name", "") if isinstance(company, dict) else ""

            posted = ""
            try:
                posted = item.get("created", "")[:10]
            except Exception:
                pass

            jobs.append(Job(
                source=self.source,
                external_id=item.get("id", ""),
                title=item.get("title", ""),
                company=co_str,
                location=loc_str,
                work_type="remote" if "remote" in item.get("title", "").lower() else "unknown",
                url=item.get("redirect_url", ""),
                description_raw=item.get("description", ""),
                salary_min=float(salary_min) if salary_min else None,
                salary_max=float(salary_max) if salary_max else None,
                posted_date=posted,
                scraped_at=datetime.utcnow().isoformat(),
            ))

        log.info("Adzuna: %d jobs scraped", len(jobs))
        return jobs
