# modules/utils/location_filter.py
# Determines whether a job row matches the user's location preferences:
#   - Remote (anywhere)
#   - Hybrid/Onsite only if in NYC or NJ metro area
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

# Terms that indicate NJ metro area (NYC-adjacent)
_NJ_TERMS = {
    "jersey city", "hoboken", "newark", "princeton",
    "jersey", "nj", "new jersey",
}


def _is_nyc_nj_area(combined_text: str) -> bool:
    """Check if text contains NYC or NJ location indicators."""
    # Check NYC terms first
    if any(term in combined_text for term in _NYC_TERMS):
        return True
    # Check NJ terms
    if any(term in combined_text for term in _NJ_TERMS):
        return True
    return False


def is_target_location(row: dict) -> bool:
    """
    Return True if the job is:
      - fully remote (any location), OR
      - hybrid/onsite ONLY if in NYC or NJ metro area

    Logic:
      - Remote jobs: Always accept (regardless of location)
      - Hybrid jobs: Accept only if location is NYC or NJ
      - Onsite jobs: Accept only if location is NYC or NJ

    Checks work_type, location, title, and the first 400 chars of description.
    """
    work_type = (row.get("work_type") or "").lower().strip()
    location  = (row.get("location")  or "").lower()
    title     = (row.get("title")     or "").lower()
    desc      = (row.get("description_raw") or "").lower()[:400]

    # ── Remote ────────────────────────────────────────────────────────────────
    # Remote jobs are always accepted, regardless of location
    if work_type == "remote":
        return True
    if "remote" in location or "remote" in title:
        return True
    # Some jobs list "Anywhere" or "US Remote" in location
    if "anywhere" in location:
        return True

    # ── Hybrid / Onsite ──────────────────────────────────────────────────────
    # Only accept if in NYC or NJ metro area
    combined = location + " " + title + " " + desc
    
    if work_type in ("hybrid", "onsite"):
        return _is_nyc_nj_area(combined)
    
    # ── Unknown work_type ────────────────────────────────────────────────────
    # If work_type is unknown, check if it mentions remote first
    # If not remote, then check if it's in NYC/NJ area
    if "hybrid" in combined or "onsite" in combined or "in-office" in combined:
        return _is_nyc_nj_area(combined)
    
    # Default: if we can't determine, accept if it's in NYC/NJ
    return _is_nyc_nj_area(combined)


def filter_jobs(jobs: list[dict]) -> list[dict]:
    """Filter a list of job dicts to only target-location jobs."""
    return [j for j in jobs if is_target_location(j)]


def location_label(row: dict) -> str:
    """Return a short human-readable location tag for display."""
    work_type = (row.get("work_type") or "").lower()
    location  = (row.get("location")  or "")
    
    if work_type == "remote" or "remote" in location.lower():
        return "Remote"
    
    if _is_nyc_nj_area(location.lower()):
        return f"NYC/NJ — {location}"
    
    return location
