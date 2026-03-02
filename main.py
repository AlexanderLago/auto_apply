#!/usr/bin/env python3
# main.py — CLI entry point for auto_apply
#
# Usage examples:
#   python main.py scrape --keyword "data analyst" --location "remote"
#   python main.py score
#   python main.py tailor --min-score 60
#   python main.py run --keyword "data analyst" --auto-apply
#   python main.py dashboard

import argparse
import sys
from pathlib import Path

import config
from modules.tracker.database import init_db

log = config.get_logger("main")


def cmd_scrape(args):
    """Scrape jobs from all configured sources and store in DB."""
    from modules.scraper.adzuna     import AdzunaScraper
    from modules.scraper.greenhouse import GreenhouseScraper
    from modules.scraper.lever      import LeverScraper
    from modules.scraper.linkedin   import LinkedInScraper
    from modules.scraper.remotive   import RemotiveScraper
    from modules.scraper.usajobs    import USAJobsScraper
    from modules.tracker.database   import upsert_job, deduplicate_jobs

    scrapers = []
    scrapers.append(AdzunaScraper(country="us"))
    scrapers.append(RemotiveScraper())
    scrapers.append(USAJobsScraper())
    scrapers.append(LinkedInScraper())
    scrapers += [GreenhouseScraper(token) for token in config.GREENHOUSE_BOARDS]
    scrapers += [LeverScraper(slug)       for slug  in config.LEVER_COMPANIES]

    total = 0
    for scraper in scrapers:
        jobs = scraper.scrape(keyword=args.keyword, location=args.location,
                              max_results=args.limit)
        for job in jobs:
            upsert_job(job)
            total += 1

    removed = deduplicate_jobs()
    log.info("Scraped %d jobs total (%d duplicates removed)", total, removed)
    print(f"[OK] Scraped {total} jobs ({removed} duplicates removed).")


def _load_candidate_profile() -> dict:
    """Parse master resume into a structured profile (cached after first run)."""
    from modules.tailor.resume_tailor  import load_master_resume
    from modules.parser.candidate_parser import parse_candidate, load_cached_profile

    cached = load_cached_profile()
    if cached:
        return cached
    resume_text = load_master_resume()
    return parse_candidate(resume_text)


def cmd_profile(args):
    """Parse master resume and display the extracted candidate profile."""
    from modules.tailor.resume_tailor    import load_master_resume
    from modules.parser.candidate_parser import parse_candidate

    resume_text = load_master_resume()
    profile = parse_candidate(resume_text, force=getattr(args, "force", False))

    print(f"\n{profile.get('name')}  |  {profile.get('location')}")
    print(f"Email   : {profile.get('email')}")
    print(f"Edu     : {profile.get('education')}  ({profile.get('education_level')})")
    print(f"Exp     : {profile.get('years_experience')} years experience")
    print(f"Titles  : {', '.join(profile.get('titles', []))}")
    print(f"Skills ({len(profile.get('skills', []))}): {', '.join(profile.get('skills', []))}")
    print(f"\n{profile.get('summary')}\n")


def cmd_score(args):
    """Parse JDs and score all 'new' jobs against the master resume."""
    from modules.tracker.database import get_jobs, save_fit_result, update_job_status
    from modules.parser.jd_parser import parse_jd
    from modules.scorer.llm_scorer import score_llm

    profile = _load_candidate_profile()
    candidate_skills  = profile.get("skills", [])
    candidate_years   = profile.get("years_experience", 0)
    candidate_edu     = profile.get("education", "")
    candidate_loc     = profile.get("location", "")
    candidate_titles  = profile.get("titles", [])
    candidate_summary = profile.get("summary", "")

    jobs = get_jobs(status="new", limit=args.limit)
    if not jobs:
        print("No new jobs to score. Run 'scrape' first.")
        return

    log.info("Scoring %d new jobs for %s", len(jobs), profile.get("name", "candidate"))
    print(f"\nScoring {len(jobs)} jobs for {profile.get('name')} "
          f"({len(candidate_skills)} skills, {candidate_years} yrs exp)\n")

    skipped = 0
    for job_row in jobs:
        if len(job_row["description_raw"]) < 200:
            update_job_status(job_row["id"], "ignored")
            skipped += 1
            continue
        parsed = parse_jd(job_row["description_raw"])
        result = score_llm(
            candidate_skills=candidate_skills,
            candidate_experience_years=candidate_years,
            candidate_education=candidate_edu,
            candidate_location=candidate_loc,
            candidate_titles=candidate_titles,
            candidate_summary=candidate_summary,
            parsed_jd=parsed,
        )
        save_fit_result(job_row["id"], result)
        filled = int(result.score / 10)
        bar = "#" * filled + "-" * (10 - filled)
        print(f"  [{bar}] {result.score:5.1f}  {job_row['title'][:40]:<40} @ {job_row['company'][:25]:<25}  -> {result.recommendation}")
        if result.strengths:
            print(f"          + {result.strengths[0]}")
        if result.gaps:
            print(f"          - {result.gaps[0]}")
    if skipped:
        print(f"  (skipped {skipped} jobs with sparse descriptions)")


def cmd_tailor(args):
    """Tailor master resume + generate cover letter for top scored jobs."""
    from modules.tracker.database    import get_jobs, update_job_status
    from modules.parser.jd_parser    import parse_jd
    from modules.tailor.resume_tailor import tailor, load_master_resume
    from modules.tailor.cover_letter  import generate as gen_cover, save as save_cover

    profile     = _load_candidate_profile()
    resume_text = load_master_resume()
    output_dir  = config.ROOT_DIR / "resumes" / "tailored"
    cl_dir      = config.ROOT_DIR / "resumes" / "cover_letters"
    jobs        = get_jobs(status="scored", min_score=args.min_score, limit=args.limit)
    log.info("Tailoring for %d jobs", len(jobs))

    for job_row in jobs:
        parsed = parse_jd(job_row["description_raw"])
        try:
            tailor(resume_text, job_row["description_raw"], parsed, output_dir=output_dir)
            cl_text = gen_cover(resume_text, job_row["description_raw"], parsed,
                                candidate_name=profile.get("name", ""))
            save_cover(cl_text, cl_dir, parsed)
            update_job_status(job_row["id"], "tailored")
            print(f"  [OK] Tailored: {job_row['title']} @ {job_row['company']}")
        except Exception as e:
            log.error("Tailor failed for job %d: %s", job_row["id"], e)


def cmd_run(args):
    """Full pipeline: scrape → score → tailor → (optional) apply."""
    cmd_scrape(args)
    cmd_score(args)
    cmd_tailor(args)
    if args.auto_apply:
        cmd_apply(args)


def cmd_apply(args):
    """Easy Apply to all 'tailored' jobs above AUTO_APPLY_MIN_SCORE."""
    from modules.tracker.database      import get_jobs, log_application
    from modules.applicator.easy_apply import EasyApplyBot
    from modules.tracker.models        import Job

    submit = getattr(args, "submit", False)
    if not submit:
        print("[DRY RUN] Forms will be filled but NOT submitted. Pass --submit to actually apply.")

    # Pull a wide pool, then exclude sources we can't auto-apply
    _SKIP_SOURCES = {"usajobs", "adzuna", "remoteok", "linkedin"}
    jobs = [j for j in get_jobs(status="tailored", min_score=config.AUTO_APPLY_MIN_SCORE, limit=500)
            if j["source"] not in _SKIP_SOURCES][:10]
    if not jobs:
        print("No jobs ready for auto-apply. Run tailor first.")
        return

    tailored_dir = config.ROOT_DIR / "resumes" / "tailored"

    with EasyApplyBot(headless=False, submit=submit) as bot:
        for job_row in jobs:
            job = Job(
                source=job_row["source"],
                external_id=job_row["external_id"],
                title=job_row["title"],
                company=job_row["company"],
                location=job_row.get("location", ""),
                work_type=job_row.get("work_type", "unknown"),
                url=job_row.get("url", ""),
            )
            # Use company-specific tailored resume if it exists, else generic
            slug = job.company.lower().replace(" ", "")[:20]
            resume = tailored_dir / f"resume_{slug}.docx"
            if not resume.exists():
                resume = next(tailored_dir.glob("*.docx"), None)
            if not resume:
                log.warning("No tailored resume found — skipping job %d", job_row["id"])
                continue
            bot.resume_path = resume
            app = bot.apply(job, job_row["id"])
            if app:
                if submit:
                    log_application(app)
                status = "[OK]" if submit else "[DRY RUN]"
                print(f"  {status} {job_row['title']} @ {job_row['company']}")


def cmd_dashboard(_args):
    """Launch the Streamlit dashboard."""
    import subprocess
    subprocess.run([sys.executable, "-m", "streamlit", "run",
                    str(config.ROOT_DIR / "dashboard" / "app.py")])


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="auto_apply", description="Job application automation")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # profile
    p_profile = sub.add_parser("profile", help="Parse master resume and show candidate profile")
    p_profile.add_argument("--force", action="store_true", help="Re-parse even if cached")
    p_profile.set_defaults(func=cmd_profile)

    # scrape
    p_scrape = sub.add_parser("scrape", help="Scrape jobs from all sources")
    p_scrape.add_argument("--keyword",  default="", help="Job title keyword")
    p_scrape.add_argument("--location", default="", help="Location filter")
    p_scrape.add_argument("--limit",    type=int, default=50)
    p_scrape.set_defaults(func=cmd_scrape)

    # score
    p_score = sub.add_parser("score", help="Score all new jobs")
    p_score.add_argument("--limit", type=int, default=100)
    p_score.set_defaults(func=cmd_score)

    # tailor
    p_tailor = sub.add_parser("tailor", help="Tailor resume for scored jobs")
    p_tailor.add_argument("--min-score", type=float, default=config.MIN_SCORE_TO_TAILOR)
    p_tailor.add_argument("--limit",     type=int,   default=20)
    p_tailor.set_defaults(func=cmd_tailor)

    # run (full pipeline)
    p_run = sub.add_parser("run", help="Full pipeline: scrape → score → tailor")
    p_run.add_argument("--keyword",    default="")
    p_run.add_argument("--location",   default="")
    p_run.add_argument("--limit",      type=int,   default=50)
    p_run.add_argument("--min-score",  type=float, default=config.MIN_SCORE_TO_TAILOR)
    p_run.add_argument("--auto-apply", action="store_true", help="Also run Easy Apply")
    p_run.set_defaults(func=cmd_run)

    # apply
    p_apply = sub.add_parser("apply", help="Easy Apply to tailored jobs")
    p_apply.add_argument("--submit", action="store_true",
                         help="Actually submit forms (default: dry run only)")
    p_apply.set_defaults(func=cmd_apply)

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Launch Streamlit dashboard")
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args()
    init_db()
    args.func(args)


if __name__ == "__main__":
    main()
