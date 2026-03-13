# modules/scraper/__init__.py
"""
Scraper Module — Job Sourcing from Multiple Platforms

This module handles fetching job postings from various sources.

## Architecture

All scrapers inherit from `BaseScraper` which provides:
- HTTP request handling with retry logic
- Rate limiting
- Error handling
- Response caching

## Supported Platforms

### ATS Platforms (Company Career Sites)

| Platform | File | API Type | Auth Required |
|----------|------|----------|---------------|
| Greenhouse | greenhouse.py | REST API | No |
| Lever | lever.py | Public JSON | No |
| Ashby | ashby.py | GraphQL | No |

### Job Boards

| Platform | File | API Type | Auth Required |
|----------|------|----------|---------------|
| Adzuna | adzuna.py | REST API | Yes (App ID + Key) |
| LinkedIn | linkedin.py | Unofficial API | Yes (Email/Pass) |
| Indeed | indeed.py | HTML Scraping | No |
| Remotive | remotive.py | Public JSON | No |
| Jobicy | jobicy.py | HTML Scraping | No |
| WeWorkRemotely | weworkremotely.py | RSS/HTML | No |
| USAJobs | usajobs.py | Government API | Yes (API Key) |

## Usage

```python
from modules.scraper.greenhouse import GreenhouseScraper
from modules.scraper.lever import LeverScraper
from modules.scraper.adzuna import AdzunaScraper

# Greenhouse (no auth)
gh_scraper = GreenhouseScraper(board_token="stripe")
jobs = gh_scraper.scrape(keyword="data analyst", location="remote", max_results=50)

# Lever (no auth)
lever_scraper = LeverScraper(slug="plaid")
jobs = lever_scraper.scrape(location="remote", max_results=50)

# Adzuna (requires API keys in .env)
adzuna = AdzunaScraper(country="us")
jobs = adzuna.scrape(keyword="engineer", location="remote", max_results=50)
```

## Work Type Inference

Scrapers attempt to infer work type from job description:
- `remote` — "remote", "anywhere", "work from home"
- `hybrid` — "hybrid", "flexible"
- `onsite` — "onsite", "in-office", specific location only

## Rate Limiting

- Greenhouse: 100 requests/minute (no auth needed)
- Lever: No documented limit (public JSON)
- Adzuna: 200 requests/hour (API key required)
- LinkedIn: Use with caution — unofficial API

## Configuration

API keys in `.env`:
```bash
ADZUNA_APP_ID=your_id
ADZUNA_APP_KEY=your_key
LINKEDIN_EMAIL=your@email.com
LINKEDIN_PASS=your_password
USAJOBS_API_KEY=your_key
```

Company targets in `.env`:
```bash
GREENHOUSE_BOARDS=stripe,discord,robinhood,...
LEVER_COMPANIES=plaid,wealthfront,...
ASHBY_COMPANIES=notion,linear,vercel,...
```
"""

from modules.scraper.base import BaseScraper
from modules.scraper.greenhouse import GreenhouseScraper
from modules.scraper.lever import LeverScraper
from modules.scraper.adzuna import AdzunaScraper

__all__ = [
    "BaseScraper",
    "GreenhouseScraper",
    "LeverScraper",
    "AdzunaScraper",
]
