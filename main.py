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
    from modules.tracker.database   import upsert_job

    scrapers = []
    scrapers.append(AdzunaScraper(country="us"))
    scrapers += [GreenhouseScraper(token) for token in config.GREENHOUSE_BOARDS]
    scrapers += [LeverScraper(slug)       for slug  in config.LEVER_COMPANIES]

    total = 0
    for scraper in scrapers:
        jobs = scraper.scrape(keyword=args.keyword, location=args.location,
                              max_results=args.limit)
        for job in jobs:
            upsert_job(job)
            total += 1

    log.info("Scraped %d jobs total", total)
    print(f"✓ Scraped {total} jobs.")


def cmd_score(args):
    """Parse JDs and score all 'new' jobs against the master resume."""
    from modules.tracker.database import get_jobs, save_fit_result, update_job_status
    from modules.parser.jd_parser import parse_jd
    from modules.scorer.fit_scorer import score
    from modules.tailor.resume_tailor import load_master_resume

    resume_text = load_master_resume()

    # Derive candidate profile from resume (simple extraction — improve as needed)
    candidate_skills = _extract_skills_from_text(resume_text)
    candidate_years  = _extract_years_from_text(resume_text)

    jobs = get_jobs(status="new", limit=args.limit)
    log.info("Scoring %d new jobs", len(jobs))

    for job_row in jobs:
        parsed = parse_jd(job_row["description_raw"])
        result = score(
            candidate_skills=candidate_skills,
            candidate_experience_years=candidate_years,
            candidate_education="Bachelor's",   # TODO: extract from resume
            candidate_location="",
            parsed_jd=parsed,
        )
        save_fit_result(job_row["id"], result)
        print(f"  [{result.score:5.1f}] {job_row['title']} @ {job_row['company']} — {result.recommendation}")


def cmd_tailor(args):
    """Tailor master resume for all scored jobs above the threshold."""
    from modules.tracker.database   import get_jobs, update_job_status
    from modules.parser.jd_parser   import parse_jd
    from modules.tailor.resume_tailor import tailor, load_master_resume

    resume_text = load_master_resume()
    output_dir  = config.ROOT_DIR / "resumes" / "tailored"
    jobs = get_jobs(status="scored", min_score=args.min_score, limit=args.limit)
    log.info("Tailoring for %d jobs", len(jobs))

    for job_row in jobs:
        parsed = parse_jd(job_row["description_raw"])
        try:
            tailor(resume_text, job_row["description_raw"], parsed, output_dir=output_dir)
            update_job_status(job_row["id"], "tailored")
            print(f"  ✓ Tailored: {job_row['title']} @ {job_row['company']}")
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
    from modules.tracker.database  import get_jobs, log_application
    from modules.applicator.easy_apply import EasyApplyBot
    from modules.tracker.models    import Job

    jobs = get_jobs(status="tailored", min_score=config.AUTO_APPLY_MIN_SCORE, limit=10)
    if not jobs:
        print("No jobs ready for auto-apply.")
        return

    with EasyApplyBot(resume_path=config.ROOT_DIR / "resumes" / "tailored" / "resume.pdf",
                      headless=False) as bot:
        for job_row in jobs:
            job = Job(**{k: job_row[k] for k in Job.model_fields if k in job_row})
            app = bot.apply(job, job_row["id"])
            if app:
                log_application(app)
                print(f"  ✓ Applied: {job_row['title']} @ {job_row['company']}")


def cmd_dashboard(_args):
    """Launch the Streamlit dashboard."""
    import subprocess
    subprocess.run([sys.executable, "-m", "streamlit", "run",
                    str(config.ROOT_DIR / "dashboard" / "app.py")])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_skills_from_text(text: str) -> list[str]:
    """
    Naive keyword extraction from resume text.
    Replace with LLM-based extraction for better accuracy.
    """
    _KNOWN = [
        "Python", "SQL", "Excel", "Tableau", "Power BI", "R", "Java", "JavaScript",
        "TypeScript", "React", "Node.js", "AWS", "GCP", "Azure", "Docker", "Kubernetes",
        "Spark", "Pandas", "NumPy", "scikit-learn", "TensorFlow", "PyTorch",
        "Machine Learning", "Data Analysis", "Statistics", "A/B Testing",
        "Product Management", "Agile", "Scrum", "Figma", "Photoshop",
    ]
    text_lower = text.lower()
    return [s for s in _KNOWN if s.lower() in text_lower]


def _extract_years_from_text(text: str) -> int:
    """Very rough heuristic — count distinct year mentions in experience section."""
    import re
    years = re.findall(r'\b(19|20)\d{2}\b', text)
    if len(years) >= 2:
        span = int(max(years)) - int(min(years))
        return max(0, span)
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="auto_apply", description="Job application automation")
    sub = parser.add_subparsers(dest="cmd", required=True)

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

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Launch Streamlit dashboard")
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args()
    init_db()
    args.func(args)


if __name__ == "__main__":
    main()
