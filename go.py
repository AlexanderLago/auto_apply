#!/usr/bin/env python3
# go.py — Single entry point for the auto_apply pipeline.
# Usage: python go.py
#
# No arguments needed. Pick a number, hit Enter.

import subprocess
import sys
import os

PYTHON = sys.executable
ROOT   = os.path.dirname(os.path.abspath(__file__))

def run(cmd: list, label: str = ""):
    """Run a command, stream output live to the terminal."""
    if label:
        print(f"\n>>> {label}\n{'─' * 50}")
    proc = subprocess.run(cmd, cwd=ROOT)
    return proc.returncode

def menu():
    while True:
        print("""
============================================================
  AUTO APPLY
============================================================
  [1]  Scrape jobs        (fetch from Greenhouse, Lever, etc.)
  [2]  Score jobs         (LLM fit scoring vs your resume)
  [3]  Tailor resumes     (customize resume + cover letter per job)
  [4]  Dry run apply      (fill forms, DON'T submit — watch browser)
  [5]  Submit apps        (actually submit — up to 50 jobs)
  [6]  Full pipeline      (scrape + score + tailor + submit, headless)

  [7]  View dashboard     (Streamlit monitoring UI)
  [8]  Check job counts   (quick DB summary)

  [0]  Quit
------------------------------------------------------------""")
        choice = input("  Pick an option: ").strip()

        if choice == "0":
            print("  Bye.")
            break

        elif choice == "1":
            kw  = input("  Keyword [data analyst]: ").strip() or "data analyst"
            loc = input("  Location [remote]: ").strip() or "remote"
            run([PYTHON, "main.py", "scrape",
                 "--keyword", kw, "--location", loc, "--limit", "100"],
                "Scraping jobs")

        elif choice == "2":
            run([PYTHON, "main.py", "score", "--limit", "200"],
                "Scoring jobs")

        elif choice == "3":
            n = input("  How many jobs to tailor? [20]: ").strip() or "20"
            run([PYTHON, "main.py", "tailor", "--limit", n],
                "Tailoring resumes")

        elif choice == "4":
            n = input("  How many apps to dry-run? [10]: ").strip() or "10"
            run([PYTHON, "main.py", "apply", "--limit", n],
                "Dry run (no submit)")

        elif choice == "5":
            n = input("  How many apps to submit? [50]: ").strip() or "50"
            hw = input("  Headless browser? (y/N): ").strip().lower()
            cmd = [PYTHON, "main.py", "apply", "--submit", "--limit", n]
            if hw == "y":
                cmd.append("--headless")
            run(cmd, f"Submitting up to {n} applications")

        elif choice == "6":
            kw  = input("  Keyword [data analyst]: ").strip() or "data analyst"
            loc = input("  Location [remote]: ").strip() or "remote"
            n   = input("  Max apps to submit [50]: ").strip() or "50"
            run([PYTHON, "main.py", "run",
                 "--keyword", kw, "--location", loc,
                 "--auto-apply", "--submit", "--headless",
                 "--limit", n],
                "Full pipeline (headless)")

        elif choice == "7":
            run([PYTHON, "main.py", "dashboard"],
                "Opening dashboard")

        elif choice == "8":
            _quick_stats()

        else:
            print("  Invalid option.")

        input("\n  Press Enter to return to menu...")


def _quick_stats():
    """Print a quick DB summary without importing the full stack."""
    import sqlite3, os
    db = os.path.join(ROOT, "data", "auto_apply.db")
    if not os.path.exists(db):
        print("  No database found yet. Run Scrape first.")
        return
    con = sqlite3.connect(db)
    cur = con.cursor()
    print("\n  Jobs by status:")
    for row in cur.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]:15s}  {row[1]}")
    cur.execute("SELECT COUNT(*) FROM jobs WHERE status='tailored' AND source IN ('greenhouse','lever','ashby')")
    ready = cur.fetchone()[0]
    print(f"\n  Ready to apply (Greenhouse/Lever/Ashby tailored): {ready}")
    cur.execute("SELECT COUNT(*) FROM applications")
    applied = cur.fetchone()[0]
    print(f"  Total applications submitted: {applied}")
    con.close()


if __name__ == "__main__":
    menu()
