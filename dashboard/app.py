# dashboard/app.py — Streamlit monitoring dashboard
# Run with: streamlit run dashboard/app.py (from the auto_apply root)
#
# Shows pipeline status, scored jobs, application log, and manual trigger buttons.

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))  # auto_apply root on path

import streamlit as st
import pandas as pd

import config
from modules.tracker.database import init_db, get_jobs, get_applications

st.set_page_config(page_title="Auto Apply", page_icon="🤖", layout="wide")

init_db()

st.title("🤖 Auto Apply — Pipeline Dashboard")

# ── Sidebar controls ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Run Pipeline")
    keyword  = st.text_input("Keyword",  placeholder="data analyst")
    location = st.text_input("Location", placeholder="remote")
    limit    = st.slider("Max jobs to scrape", 10, 200, 50, step=10)

    if st.button("▶ Scrape", use_container_width=True):
        from modules.scraper.adzuna     import AdzunaScraper
        from modules.scraper.greenhouse import GreenhouseScraper
        from modules.scraper.lever      import LeverScraper
        from modules.tracker.database   import upsert_job
        with st.spinner("Scraping..."):
            scrapers = (
                [AdzunaScraper()] +
                [GreenhouseScraper(t) for t in config.GREENHOUSE_BOARDS] +
                [LeverScraper(s)      for s  in config.LEVER_COMPANIES]
            )
            total = sum(
                (upsert_job(j) and 1 or 1)
                for sc in scrapers
                for j in sc.scrape(keyword=keyword, location=location, max_results=limit)
            )
        st.success(f"Scraped {total} jobs")
        st.rerun()

    if st.button("🎯 Score All New", use_container_width=True):
        from modules.parser.jd_parser    import parse_jd
        from modules.scorer.fit_scorer   import score
        from modules.tailor.resume_tailor import load_master_resume
        from modules.tracker.database    import save_fit_result
        from modules.tracker.models      import Job
        with st.spinner("Scoring..."):
            resume_text = load_master_resume()
            new_jobs = get_jobs(status="new", limit=200)
            for row in new_jobs:
                parsed = parse_jd(row["description_raw"])
                result = score([], 0, "", "", parsed)      # TODO: parse candidate profile
                save_fit_result(row["id"], result)
        st.success(f"Scored {len(new_jobs)} jobs")
        st.rerun()

# ── Metrics ────────────────────────────────────────────────────────────────────
all_jobs = get_jobs(limit=1000)
df_jobs  = pd.DataFrame(all_jobs) if all_jobs else pd.DataFrame()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Jobs",    len(df_jobs))
col2.metric("Scored",        len(df_jobs[df_jobs["status"] == "scored"])        if not df_jobs.empty else 0)
col3.metric("Tailored",      len(df_jobs[df_jobs["status"] == "tailored"])      if not df_jobs.empty else 0)
col4.metric("Applied",       len(df_jobs[df_jobs["status"] == "applied"])       if not df_jobs.empty else 0)

st.divider()

# ── Job table ──────────────────────────────────────────────────────────────────
tab_jobs, tab_apps = st.tabs(["🔍 Jobs", "📋 Applications"])

with tab_jobs:
    st.subheader("Scored Jobs")
    min_score = st.slider("Min fit score", 0, 100, 50)

    if not df_jobs.empty:
        display_cols = [c for c in ["title", "company", "location", "fit_score",
                                     "work_type", "status", "url"] if c in df_jobs.columns]
        filtered = df_jobs[df_jobs["fit_score"].notna() & (df_jobs["fit_score"] >= min_score)]
        filtered = filtered.sort_values("fit_score", ascending=False)
        st.dataframe(
            filtered[display_cols],
            column_config={
                "fit_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
                "url":       st.column_config.LinkColumn("Link"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No jobs yet — run Scrape + Score from the sidebar.")

with tab_apps:
    st.subheader("Application Log")
    apps = get_applications()
    if apps:
        st.dataframe(pd.DataFrame(apps), use_container_width=True, hide_index=True)
    else:
        st.info("No applications logged yet.")
