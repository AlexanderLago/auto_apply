#!/usr/bin/env python3
# scripts/daily_run.py — Full daily pipeline run
#
# Runs: scrape -> score -> tailor -> email digest
# Schedule with Windows Task Scheduler (see setup_scheduler.bat) or cron.
#
# Usage: python scripts/daily_run.py --keyword "data analyst" --location "remote"

import sys
import argparse
from pathlib import Path

# Ensure auto_apply root is on path
sys.path.insert(0, str(Path(__file__).parents[1]))

import config
from modules.tracker.database import init_db, get_jobs, upsert_job, deduplicate_jobs, update_job_status, save_fit_result
from modules.parser.candidate_parser import load_cached_profile, parse_candidate
from modules.tailor.resume_tailor import load_master_resume

log = config.get_logger("daily_run")


def main():
    parser = argparse.ArgumentParser(description="Daily auto_apply pipeline run")
    parser.add_argument("--keyword",   default="data analyst")
    parser.add_argument("--location",  default="")
    parser.add_argument("--limit",     type=int, default=50)
    parser.add_argument("--min-score", type=float, default=config.MIN_SCORE_TO_TAILOR)
    parser.add_argument("--no-tailor", action="store_true", help="Skip tailoring step")
    parser.add_argument("--no-email",  action="store_true", help="Skip email digest")
    args = parser.parse_args()

    log.info("=== Daily run started: keyword=%r location=%r ===", args.keyword, args.location)
    init_db()

    # ── 1. Scrape ──────────────────────────────────────────────────────────────
    log.info("Step 1/4: Scraping jobs...")
    from modules.scraper.adzuna     import AdzunaScraper
    from modules.scraper.greenhouse import GreenhouseScraper
    from modules.scraper.lever      import LeverScraper
    from modules.scraper.linkedin   import LinkedInScraper
    from modules.scraper.remotive   import RemotiveScraper
    from modules.scraper.usajobs    import USAJobsScraper

    scrapers = (
        [AdzunaScraper(country="us"), RemotiveScraper(), USAJobsScraper(), LinkedInScraper()]
        + [GreenhouseScraper(t) for t in config.GREENHOUSE_BOARDS]
        + [LeverScraper(s)      for s  in config.LEVER_COMPANIES]
    )
    total = 0
    for sc in scrapers:
        for job in sc.scrape(keyword=args.keyword, location=args.location, max_results=args.limit):
            upsert_job(job)
            total += 1
    removed = deduplicate_jobs()
    log.info("Scraped %d jobs (%d duplicates removed)", total, removed)

    # ── 2. Score ───────────────────────────────────────────────────────────────
    log.info("Step 2/4: Scoring new jobs...")
    from modules.parser.jd_parser   import parse_jd
    from modules.scorer.llm_scorer  import score_llm

    profile = load_cached_profile()
    if not profile:
        profile = parse_candidate(load_master_resume())

    new_jobs = get_jobs(status="new", limit=500)
    scored, skipped = 0, 0
    for row in new_jobs:
        if len(row["description_raw"]) < 200:
            update_job_status(row["id"], "ignored")
            skipped += 1
            continue
        try:
            parsed = parse_jd(row["description_raw"])
            result = score_llm(
                candidate_skills=profile.get("skills", []),
                candidate_experience_years=profile.get("years_experience", 0),
                candidate_education=profile.get("education", ""),
                candidate_location=profile.get("location", ""),
                candidate_titles=profile.get("titles", []),
                candidate_summary=profile.get("summary", ""),
                parsed_jd=parsed,
            )
            save_fit_result(row["id"], result)
            scored += 1
        except Exception as e:
            log.warning("Score failed for job %d: %s", row["id"], e)
    log.info("Scored %d jobs (%d skipped sparse)", scored, skipped)

    # ── 3. Tailor ──────────────────────────────────────────────────────────────
    if not args.no_tailor:
        log.info("Step 3/4: Tailoring top %d+ jobs...", int(args.min_score))
        from modules.tailor.resume_tailor import tailor
        from modules.tailor.cover_letter  import generate as gen_cover, save as save_cover

        resume_text = load_master_resume()
        output_dir  = config.ROOT_DIR / "resumes" / "tailored"
        cl_dir      = config.ROOT_DIR / "resumes" / "cover_letters"
        top_jobs    = get_jobs(status="scored", min_score=args.min_score, limit=10)
        tailored    = 0
        for row in top_jobs:
            try:
                parsed = parse_jd(row["description_raw"])
                tailor(resume_text, row["description_raw"], parsed, output_dir=output_dir)
                cl_text = gen_cover(resume_text, row["description_raw"], parsed,
                                    candidate_name=profile.get("name", ""))
                save_cover(cl_text, cl_dir, parsed)
                update_job_status(row["id"], "tailored")
                tailored += 1
            except Exception as e:
                log.warning("Tailor failed for job %d: %s", row["id"], e)
        log.info("Tailored %d resumes + cover letters", tailored)
    else:
        log.info("Step 3/4: Tailoring skipped (--no-tailor)")

    # ── 4. Email digest ────────────────────────────────────────────────────────
    if not args.no_email:
        log.info("Step 4/4: Sending email digest...")
        from modules.notifier.email_notifier import send_digest
        all_scored = get_jobs(limit=500)
        send_digest(all_scored, min_score=args.min_score)
    else:
        log.info("Step 4/4: Email digest skipped (--no-email)")

    log.info("=== Daily run complete ===")
    print(f"\nDone. {total} scraped, {scored} scored, check logs for details.")
    print(f"Run 'python main.py dashboard' to browse results.")


if __name__ == "__main__":
    main()
