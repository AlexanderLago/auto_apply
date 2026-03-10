# modules/utils/location_filter.py
# Determines whether a job row matches the user's location preferences:
#   - Remote (anywhere)
#   - NYC-area hybrid / onsite
#
# Applied as a post-query filter so the DB stays broad and the filter
# is easy to tweak without re-scraping.

from __future__ import annotations

# Terms that indicate NYC METRO area — specific enough to exclude upstate NY
_NYC_TERMS = {
    "new york, ny", "new york,ny", "new york city",
    "nyc", "manhattan", "brooklyn", "queens", "bronx", "staten island",
    "jersey city", "hoboken", "newark, nj",
    "long island city", "astoria", "flushing",
    # Common shorthand in job postings
    "ny, ny", "ny,ny", "(new york)",
}


def is_target_location(row: dict) -> bool:
    """
    Return True if the job is:
      - fully remote (work_type == 'remote' or location/title says 'remote'), OR
      - NYC-area hybrid or onsite

    Checks work_type, location, title, and the first 400 chars of description.
    """
    work_type = (row.get("work_type") or "").lower().strip()
    location  = (row.get("location")  or "").lower()
    title     = (row.get("title")     or "").lower()
    desc      = (row.get("description_raw") or "").lower()[:400]

    # ── Remote ────────────────────────────────────────────────────────────────
    if work_type == "remote":
        return True
    if "remote" in location or "remote" in title:
        return True
    # Some jobs list "Anywhere" or "US Remote" in location
    if "anywhere" in location:
        return True

    # ── NYC area ──────────────────────────────────────────────────────────────
    combined = location + " " + title + " " + desc
    if any(term in combined for term in _NYC_TERMS):
        return True

    return False


def filter_jobs(jobs: list[dict]) -> list[dict]:
    """Filter a list of job dicts to only target-location jobs."""
    return [j for j in jobs if is_target_location(j)]


def location_label(row: dict) -> str:
    """Return a short human-readable location tag for display."""
    work_type = (row.get("work_type") or "").lower()
    location  = (row.get("location")  or "")
    if work_type == "remote" or "remote" in location.lower():
        return "Remote"
    if is_target_location(row):
        return f"NYC — {location}"
    return location
