# modules/scraper/base.py — Abstract base class all scrapers must implement.
# Adding a new job source = subclass BaseScraper, implement scrape().

from abc import ABC, abstractmethod
from modules.tracker.models import Job


class BaseScraper(ABC):
    """
    Contract every scraper must fulfil.

    Usage:
        scraper = GreenhouseScraper(board_token="stripe")
        jobs: list[Job] = scraper.scrape(keyword="data analyst", location="remote")
    """

    source: str = ""  # override in subclass: 'greenhouse' | 'lever' | 'adzuna' | 'linkedin'

    @abstractmethod
    def scrape(
        self,
        keyword: str = "",
        location: str = "",
        max_results: int = 50,
    ) -> list[Job]:
        """
        Fetch job listings and return them as Job model instances.
        Should never raise — log errors and return partial results.
        """
        ...

    def _safe_get(self, url: str, **kwargs):
        """requests.get wrapper with timeout and error logging."""
        import requests
        import config
        log = config.get_logger(self.__class__.__name__)
        try:
            resp = requests.get(url, timeout=15, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            log.warning("GET %s failed: %s", url, e)
            return None
