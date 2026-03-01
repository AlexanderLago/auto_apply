# dashboard/app.py — Streamlit monitoring dashboard
# Run with: python main.py dashboard  (or: streamlit run dashboard/app.py)

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import streamlit as st
import pandas as pd

import config
from modules.tracker.database import (
    init_db, get_jobs, get_applications, deduplicate_jobs, update_job_status,
    save_fit_result,
)

st.set_page_config(page_title="Auto Apply", layout="wide")
init_db()

st.title("Auto Apply — Pipeline Dashboard")

# ── Sidebar controls ────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Run Pipeline")
    keyword  = st.text_input("Keyword",  placeholder="data analyst")
    location = st.text_input("Location", placeholder="remote")
    limit    = st.slider("Max jobs to scrape", 10, 200, 50, step=10)

    # ── Scrape ──────────────────────────────────────────────────────────────────
    if st.button("Scrape", use_container_width=True):
        from modules.scraper.adzuna     import AdzunaScraper
        from modules.scraper.greenhouse import GreenhouseScraper
        from modules.scraper.lever      import LeverScraper
        from modules.scraper.linkedin   import LinkedInScraper
        from modules.scraper.remotive   import RemotiveScraper
        from modules.scraper.usajobs    import USAJobsScraper
        from modules.tracker.database   import upsert_job
        with st.spinner("Scraping..."):
            scrapers = (
                [AdzunaScraper(country="us")]
                + [GreenhouseScraper(t) for t in config.GREENHOUSE_BOARDS]
                + [LeverScraper(s)      for s  in config.LEVER_COMPANIES]
                + [RemotiveScraper()]
                + [USAJobsScraper()]
                + [LinkedInScraper()]
            )
            total = 0
            for sc in scrapers:
                for j in sc.scrape(keyword=keyword, location=location, max_results=limit):
                    upsert_job(j)
                    total += 1
            removed = deduplicate_jobs()
        st.success(f"Scraped {total} jobs ({removed} duplicates removed)")
        st.rerun()

    # ── Score ───────────────────────────────────────────────────────────────────
    if st.button("Score All New", use_container_width=True):
        from modules.parser.jd_parser        import parse_jd
        from modules.scorer.llm_scorer       import score_llm
        from modules.parser.candidate_parser import load_cached_profile, parse_candidate
        from modules.tailor.resume_tailor    import load_master_resume
        with st.spinner("Scoring..."):
            profile = load_cached_profile()
            if not profile:
                profile = parse_candidate(load_master_resume())
            new_jobs = get_jobs(status="new", limit=500)
            skipped = 0
            scored_count = 0
            prog = st.progress(0)
            for i, row in enumerate(new_jobs):
                if len(row["description_raw"]) < 200:
                    update_job_status(row["id"], "ignored")
                    skipped += 1
                else:
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
                    scored_count += 1
                prog.progress((i + 1) / max(len(new_jobs), 1))
        st.success(f"Scored {scored_count} jobs ({skipped} skipped — sparse descriptions)")
        st.rerun()

    # ── Tailor ──────────────────────────────────────────────────────────────────
    if st.button("Tailor Top Jobs", use_container_width=True):
        from modules.parser.jd_parser       import parse_jd
        from modules.tailor.resume_tailor   import tailor, load_master_resume
        from modules.tailor.cover_letter    import generate as gen_cover, save as save_cover
        from modules.parser.candidate_parser import load_cached_profile, parse_candidate
        output_dir = config.ROOT_DIR / "resumes" / "tailored"
        cl_dir     = config.ROOT_DIR / "resumes" / "cover_letters"
        with st.spinner("Tailoring + writing cover letters..."):
            profile = load_cached_profile() or parse_candidate(load_master_resume())
            resume_text = load_master_resume()
            jobs = get_jobs(status="scored", min_score=config.MIN_SCORE_TO_TAILOR, limit=10)
            count, failed = 0, 0
            for row in jobs:
                try:
                    parsed = parse_jd(row["description_raw"])
                    tailor(resume_text, row["description_raw"], parsed, output_dir=output_dir)
                    cl_text = gen_cover(resume_text, row["description_raw"], parsed,
                                        candidate_name=profile.get("name", ""))
                    save_cover(cl_text, cl_dir, parsed)
                    update_job_status(row["id"], "tailored")
                    count += 1
                except Exception as e:
                    st.warning(f"Tailor failed for {row['title']}: {e}")
                    failed += 1
        msg = f"Tailored {count} resumes"
        if failed:
            msg += f" ({failed} failed)"
        st.success(msg)
        st.rerun()

# ── Metrics row ─────────────────────────────────────────────────────────────────
all_jobs = get_jobs(limit=2000)
df       = pd.DataFrame(all_jobs) if all_jobs else pd.DataFrame()

def _count(status):
    return len(df[df["status"] == status]) if not df.empty else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Jobs", len(df))
c2.metric("Scored",     _count("scored"))
c3.metric("Tailored",   _count("tailored"))
c4.metric("Applied",    _count("applied"))
c5.metric("Ignored",    _count("ignored"))

st.divider()

# ── Main tabs ───────────────────────────────────────────────────────────────────
tab_jobs, tab_detail, tab_apps, tab_cl = st.tabs(["Jobs", "Job Detail", "Applications", "Cover Letters"])

with tab_jobs:
    min_score = st.slider("Min fit score", 0, 100, 50)
    if df.empty:
        st.info("No jobs yet — run Scrape + Score from the sidebar.")
    else:
        scored_df = df[df["fit_score"].notna() & (df["fit_score"] >= min_score)].copy()
        scored_df = scored_df.sort_values("fit_score", ascending=False)
        cols = [c for c in ["title", "company", "location", "work_type",
                             "fit_score", "status", "source", "url"] if c in scored_df.columns]
        st.dataframe(
            scored_df[cols],
            column_config={
                "fit_score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%.0f"),
                "url": st.column_config.LinkColumn("Link"),
            },
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"{len(scored_df)} jobs shown")

with tab_detail:
    if df.empty or df["fit_score"].isna().all():
        st.info("Score some jobs first.")
    else:
        scored_df2 = df[df["fit_score"].notna()].sort_values("fit_score", ascending=False)
        labels = scored_df2["title"] + " @ " + scored_df2["company"] + \
                 " — " + scored_df2["fit_score"].astype(int).astype(str)
        choice = st.selectbox("Pick a job", range(len(scored_df2)),
                              format_func=lambda i: labels.iloc[i])
        row = scored_df2.iloc[choice]

        col_l, col_r = st.columns([2, 1])
        with col_l:
            st.markdown(f"### {row['title']}")
            st.markdown(f"**{row['company']}** &nbsp;|&nbsp; {row['location']} &nbsp;|&nbsp; "
                        f"{row['work_type']} &nbsp;|&nbsp; *{row['source']}*")
            if row.get("url"):
                st.markdown(f"[Open posting]({row['url']})")
            st.markdown(f"**Status:** `{row['status']}`")

        with col_r:
            st.markdown("**Fit Breakdown**")
            strengths, gaps = [], []
            if row.get("fit_breakdown"):
                try:
                    bd = json.loads(row["fit_breakdown"]) if isinstance(row["fit_breakdown"], str) \
                         else row["fit_breakdown"]
                    strengths = bd.pop("_strengths", [])
                    gaps      = bd.pop("_gaps", [])
                    for k, v in bd.items():
                        st.metric(k.capitalize(), f"{float(v):.0f} / 100")
                except Exception:
                    pass
            st.metric("Overall Score", f"{row['fit_score']:.0f} / 100")

        if strengths or gaps:
            col_s, col_g = st.columns(2)
            with col_s:
                if strengths:
                    st.markdown("**Strengths**")
                    for s in strengths:
                        st.markdown(f"- {s}")
            with col_g:
                if gaps:
                    st.markdown("**Gaps**")
                    for g in gaps:
                        st.markdown(f"- {g}")

        if row.get("description_raw"):
            with st.expander("Full job description"):
                st.text(row["description_raw"][:4000])

with tab_apps:
    st.subheader("Application Log")
    apps = get_applications()
    if apps:
        st.dataframe(pd.DataFrame(apps), use_container_width=True, hide_index=True)
    else:
        st.info("No applications logged yet.")

with tab_cl:
    st.subheader("Cover Letters")
    cl_dir = config.ROOT_DIR / "resumes" / "cover_letters"
    cl_files = sorted(cl_dir.glob("cover_letter_*.txt")) if cl_dir.exists() else []
    if not cl_files:
        st.info("No cover letters yet — run Tailor from the sidebar.")
    else:
        chosen = st.selectbox("Select cover letter", cl_files,
                              format_func=lambda p: p.stem.replace("cover_letter_", "").capitalize())
        if chosen:
            text = chosen.read_text(encoding="utf-8")
            st.text_area("Cover letter", text, height=350)
            st.download_button("Download .txt", text, file_name=chosen.name)
