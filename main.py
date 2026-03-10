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
    from modules.scraper.adzuna         import AdzunaScraper
    from modules.scraper.ashby          import AshbyScraper
    from modules.scraper.greenhouse     import GreenhouseScraper
    from modules.scraper.indeed         import IndeedScraper
    from modules.scraper.jobicy         import JobicyScraper
    from modules.scraper.lever          import LeverScraper
    from modules.scraper.linkedin       import LinkedInScraper
    from modules.scraper.remotive       import RemotiveScraper
    from modules.scraper.usajobs        import USAJobsScraper
    from modules.scraper.weworkremotely import WeWorkRemotelyScraper
    from modules.tracker.database       import upsert_job, deduplicate_jobs

    kw  = args.keyword
    loc = args.location
    lim = args.limit

    # Broad job boards — use keyword + location to stay relevant
    broad = [
        AdzunaScraper(country="us"),
        IndeedScraper(),
        RemotiveScraper(),
        JobicyScraper(),
        WeWorkRemotelyScraper(),
        USAJobsScraper(),
        LinkedInScraper(),
    ]
    # ATS company boards — get ALL jobs from each company (no keyword filter).
    # The LLM scorer decides relevance, keeping our pipeline flexible.
    ats = (
        [GreenhouseScraper(token) for token in config.GREENHOUSE_BOARDS]
        + [LeverScraper(slug)     for slug  in config.LEVER_COMPANIES]
        + [AshbyScraper(company)  for company in config.ASHBY_COMPANIES]
    )

    total = 0
    for scraper in broad:
        try:
            jobs = scraper.scrape(keyword=kw, location=loc, max_results=lim)
            for job in jobs:
                upsert_job(job)
                total += 1
        except Exception as e:
            log.warning("Scraper %s failed: %s", type(scraper).__name__, e)

    for scraper in ats:
        try:
            # Empty keyword → get all jobs; location filter still applied
            jobs = scraper.scrape(keyword="", location=loc, max_results=lim)
            for job in jobs:
                upsert_job(job)
                total += 1
        except Exception as e:
            log.warning("Scraper %s failed: %s", type(scraper).__name__, e)

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

    from modules.utils.location_filter import filter_jobs, is_target_location
    all_new = get_jobs(status="new", limit=args.limit)
    if not all_new:
        print("No new jobs to score. Run 'scrape' first.")
        return

    # Score only remote / NYC-area jobs; ignore others to save LLM calls
    jobs    = filter_jobs(all_new)
    ignored = [j for j in all_new if not is_target_location(j)]
    for j in ignored:
        update_job_status(j["id"], "ignored")

    log.info("Scoring %d/%d new jobs (remote/NYC filter, %d ignored)",
             len(jobs), len(all_new), len(ignored))
    print(f"\nScoring {len(jobs)}/{len(all_new)} jobs for {profile.get('name')} "
          f"({len(candidate_skills)} skills, {candidate_years} yrs exp)"
          f"  [{len(ignored)} non-remote/NYC ignored]\n")

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
    import collections, time as _time
    import sqlite3
    
    # Clean up any database locks before starting
    try:
        con = sqlite3.connect(config.DB_PATH, timeout=5.0)
        con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        con.close()
    except Exception:
        pass
    
    submit   = getattr(args, "submit",   False)
    headless = getattr(args, "headless", False)
    limit    = getattr(args, "limit",    50)

    mode_tag = "[SUBMIT]" if submit else "[DRY RUN]"
    if not submit:
        print(f"{mode_tag} Forms will be filled but NOT submitted. Pass --submit to actually apply.")
    if headless:
        print("[HEADLESS] Running unattended — CAPTCHAs will be skipped automatically.")

    # Pull a wide pool; exclude sources the bot can't auto-fill
    # (location filter applies at scoring/scrape time, not here — keep apply pool broad)
    _SKIP_SOURCES = {"usajobs", "adzuna", "remoteok", "linkedin"}
    jobs = [j for j in get_jobs(status="tailored", min_score=config.AUTO_APPLY_MIN_SCORE, limit=500)
            if j["source"] not in _SKIP_SOURCES][:limit]
    if not jobs:
        print("No jobs ready for auto-apply. Run 'tailor' first.")
        return

    print(f"\n{'-'*60}")
    print(f"  Starting apply run -- {len(jobs)} jobs queued")
    print(f"  min_score={config.AUTO_APPLY_MIN_SCORE}  limit={limit}  submit={submit}  headless={headless}")
    print(f"{'-'*60}\n")

    tailored_dir = config.ROOT_DIR / "resumes" / "tailored"
    outcomes = []
    t_start  = _time.time()

    with EasyApplyBot(headless=headless, submit=submit) as bot:
        for i, job_row in enumerate(jobs, 1):
            job = Job(
                source=job_row["source"],
                external_id=job_row["external_id"],
                title=job_row["title"],
                company=job_row["company"],
                location=job_row.get("location", ""),
                work_type=job_row.get("work_type", "unknown"),
                url=job_row.get("url", ""),
            )
            # Use company-specific tailored resume if it exists, else any generic one
            slug = job.company.lower().replace(" ", "")[:20]
            resume = tailored_dir / f"resume_{slug}.docx"
            if not resume.exists():
                resume = next(tailored_dir.glob("*.docx"), None)
            if not resume:
                log.warning("No tailored resume found — skipping job %d", job_row["id"])
                from modules.applicator.easy_apply import ApplyOutcome
                outcomes.append(ApplyOutcome(
                    job_id=job_row["id"], company=job_row["company"],
                    title=job_row["title"], status="error",
                    error="no tailored resume found"))
                print(f"  [{i:02d}] [NO RESUME] {job_row['title'][:35]} @ {job_row['company']}")
                continue

            bot.resume_path = resume
            outcome = bot.apply(job, job_row["id"])
            outcomes.append(outcome)

            if outcome.status in ("submitted", "dry_run") and outcome.app:
                if submit:
                    try:
                        log_application(outcome.app)
                        # Checkpoint after each application to clear WAL
                        import sqlite3
                        try:
                            ckpt_con = sqlite3.connect(config.DB_PATH, timeout=5.0)
                            ckpt_con.execute("PRAGMA wal_checkpoint(PASSIVE)")
                            ckpt_con.close()
                        except Exception:
                            pass
                    except Exception as log_err:
                        log.warning("Failed to log application: %s", log_err)
                tag = "SUBMITTED" if submit else "DRY RUN OK"
            elif outcome.status == "captcha":
                tag = "CAPTCHA"
            elif outcome.status == "no_handler":
                tag = "NO HANDLER"
            else:
                tag = "ERROR"

            label = f"[{i:02d}] [{tag}]"
            print(f"  {label} {job_row['title'][:35]:<35} @ {job_row['company']}")
            if outcome.error:
                # Truncate long errors for readability
                print(f"           {outcome.error[:90]}")

    elapsed = _time.time() - t_start
    _print_apply_report(outcomes, elapsed, submit)


def _print_apply_report(outcomes, elapsed_secs, submitted: bool) -> None:
    """Print a formatted metrics report after an apply run."""
    import collections

    total = len(outcomes)
    if total == 0:
        return

    counts = collections.Counter(o.status for o in outcomes)
    success_statuses = {"submitted", "dry_run"}
    n_success  = sum(counts[s] for s in success_statuses)
    n_captcha  = counts["captcha"]
    n_error    = counts["error"]
    n_handler  = counts["no_handler"]
    pct        = (n_success / total * 100) if total else 0

    # Group errors by first ~60 chars of message
    error_groups = collections.Counter(
        o.error[:60] for o in outcomes if o.status == "error" and o.error
    )

    w = 60
    print(f"\n{'='*w}")
    print(f"  APPLY RUN REPORT")
    print(f"{'-'*w}")
    print(f"  Attempted        : {total}")
    success_label = "Submitted" if submitted else "Filled OK (dry run)"
    print(f"  {success_label:<22}: {n_success}  ({pct:.0f}%)")
    if n_captcha:
        print(f"  CAPTCHA skipped  : {n_captcha}")
    if n_handler:
        print(f"  No handler       : {n_handler}")
    if n_error:
        print(f"  Errors           : {n_error}")
    print(f"  Elapsed          : {elapsed_secs/60:.1f} min  "
          f"({elapsed_secs/total:.0f}s/app avg)")
    print(f"{'-'*w}")

    if error_groups:
        print(f"  Top error reasons:")
        for msg, cnt in error_groups.most_common(5):
            print(f"    x{cnt}  {msg}")
        print(f"{'-'*w}")

    print(f"  Per-company breakdown:")
    by_company = collections.defaultdict(list)
    for o in outcomes:
        by_company[o.company].append(o.status)
    for company, statuses in sorted(by_company.items()):
        ok  = sum(1 for s in statuses if s in success_statuses)
        ttl = len(statuses)
        bar = "[OK]" * ok + "[--]" * (ttl - ok)
        print(f"    {company:<20} {bar}  ({ok}/{ttl})")

    print(f"{'='*w}\n")


def cmd_stats(_args):
    """Show quick application statistics."""
    import sqlite3
    from datetime import datetime
    
    con = sqlite3.connect(config.DB_PATH, timeout=30.0)
    con.row_factory = sqlite3.Row
    
    # Total applications
    total = con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    
    # Applications today
    today = datetime.now().date().isoformat()
    today_count = con.execute("""
        SELECT COUNT(*) FROM applications 
        WHERE date(applied_at) = ?
    """, (today,)).fetchone()[0]
    
    # Outcome breakdown
    outcome_counts = con.execute("""
        SELECT outcome, COUNT(*) as count 
        FROM applications 
        GROUP BY outcome
    """).fetchall()
    
    # Recent applications
    recent = con.execute("""
        SELECT j.company, j.title, a.outcome, a.applied_at, a.method
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
        ORDER BY a.applied_at DESC
        LIMIT 10
    """).fetchall()
    
    con.close()
    
    outcome_dict = {r['outcome']: r['count'] for r in outcome_counts}
    pending = outcome_dict.get('pending', 0)
    interviews = outcome_dict.get('interview', 0)
    rejected = outcome_dict.get('rejected', 0)
    offers = outcome_dict.get('offer', 0)
    
    # Calculate success rate (interviews + offers / total)
    success_rate = ((interviews + offers) / total * 100) if total > 0 else 0
    
    print("\n" + "=" * 70)
    print("  AUTO-APPLY STATISTICS")
    print("=" * 70)
    print(f"  Total Applications:  {total}")
    print(f"  Applied Today:       {today_count}")
    print(f"  Interview/Offer Rate: {success_rate:.1f}%")
    print("-" * 70)
    print(f"  Pending: {pending}  |  Interviews: {interviews}  |  Offers: {offers}  |  Rejected: {rejected}")
    print("=" * 70)
    
    if recent:
        print("\n  RECENT APPLICATIONS")
        print("-" * 70)
        for app in recent:
            if app['outcome'] == 'pending':
                status_icon = "[~]"
            elif app['outcome'] == 'interview':
                status_icon = "[!]"
            elif app['outcome'] == 'offer':
                status_icon = "[OK]"
            else:
                status_icon = "[X]"
            time_str = datetime.fromisoformat(app['applied_at']).strftime('%m-%d %H:%M')
            method_str = "[BOT]" if app['method'] == 'easy_apply' else "[MAN]"
            print(f"  {status_icon} {method_str} {time_str}  {app['company'][:25]:<25}  {app['title'][:35]}")
        print("=" * 70 + "\n")


def cmd_dashboard(_args):
    """Launch the terminal dashboard."""
    from dashboard.terminal_app import dashboard
    dashboard()


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
    p_run.add_argument("--headless",   action="store_true", help="Run browser headless")
    p_run.add_argument("--submit",     action="store_true", help="Actually submit forms")
    p_run.set_defaults(func=cmd_run)

    # apply
    p_apply = sub.add_parser("apply", help="Easy Apply to tailored jobs")
    p_apply.add_argument("--submit",   action="store_true",
                         help="Actually submit forms (default: dry run only)")
    p_apply.add_argument("--headless", action="store_true",
                         help="Run browser headless for unattended/overnight runs")
    p_apply.add_argument("--limit",    type=int, default=50,
                         help="Max number of jobs to apply to (default: 50)")
    p_apply.set_defaults(func=cmd_apply)

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Launch terminal dashboard")
    p_dash.set_defaults(func=cmd_dashboard)

    # stats
    p_stats = sub.add_parser("stats", help="Show application statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    init_db()
    args.func(args)


if __name__ == "__main__":
    main()
