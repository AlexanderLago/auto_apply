# dashboard/app.py — Auto Apply control panel + monitoring dashboard
# Run with: python main.py dashboard   (or: streamlit run dashboard/app.py)
# Deploy on Streamlit Cloud: https://share.streamlit.io

import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parents[1]))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import config
from modules.tracker.database import (
    init_db, get_jobs, get_applications, deduplicate_jobs, 
    update_job_status, save_fit_result, log_application,
)
from modules.tracker.models import Application
from modules.utils.location_filter import filter_jobs, is_target_location

# ── Page config ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Auto Apply Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "Auto Apply — Job Application Automation Pipeline\n\nBuilt with Streamlit"
    }
)

# ── Initialize DB ───────────────────────────────────────────────────────────────
init_db()

# ── Custom CSS ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        font-weight: 600;
    }
    div[data-testid="stMetricValue"] {
        font-size: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Load all jobs once ───────────────────────────────────────────────────────────
all_jobs = get_jobs(limit=5000)
df_all = pd.DataFrame(all_jobs) if all_jobs else pd.DataFrame()

# ── Helper functions ────────────────────────────────────────────────────────────
def _count(status, df=None):
    d = df if df is not None else df_all
    return len(d[d["status"] == status]) if not d.empty and "status" in d.columns else 0

def _format_score(score):
    return f"{score:.0f}" if score else "N/A"

def _get_score_color(score):
    if not score:
        return "gray"
    if score >= 80:
        return "green"
    elif score >= 60:
        return "orange"
    else:
        return "red"

# ── Sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/color/96/robot-2.png", width=80)
    st.title("Auto Apply")
    st.caption("AI-Powered Job Application Automation")
    
    st.markdown("---")
    
    # User profile info
    st.subheader("👤 Candidate Profile")
    profile_cached = None
    try:
        from modules.parser.candidate_parser import load_cached_profile
        profile_cached = load_cached_profile()
    except:
        pass
    
    if profile_cached:
        st.info(f"**{profile_cached.get('name', 'Unknown')}**\n\n{profile_cached.get('titles', [''])[0] if profile_cached.get('titles') else ''}")
        st.caption(f"📍 {profile_cached.get('location', 'Unknown')}")
        st.caption(f"💼 {profile_cached.get('years_experience', 0)} years experience")
        skills = profile_cached.get('skills', [])
        if skills:
            st.markdown(f"**Top Skills:** {', '.join(skills[:5])}")
    else:
        st.warning("Profile not parsed yet. Run Score first.")
    
    st.markdown("---")
    
    # Pipeline Controls
    st.header("🚀 Pipeline Controls")
    
    keyword = st.text_input("Job Keyword", value="data analyst", help="Keywords to search for")
    location = st.text_input("Location", value="remote", help="Location preference")
    limit = st.slider("Max jobs to scrape", 10, 500, 50, step=10)
    
    st.markdown("---")
    
    # Scrape button
    if st.button("1️⃣ Scrape Jobs", use_container_width=True, help="Fetch jobs from all sources"):
        from modules.scraper.adzuna import AdzunaScraper
        from modules.scraper.ashby import AshbyScraper
        from modules.scraper.greenhouse import GreenhouseScraper
        from modules.scraper.indeed import IndeedScraper
        from modules.scraper.jobicy import JobicyScraper
        from modules.scraper.lever import LeverScraper
        from modules.scraper.linkedin import LinkedInScraper
        from modules.scraper.remotive import RemotiveScraper
        from modules.scraper.usajobs import USAJobsScraper
        from modules.scraper.weworkremotely import WeWorkRemotelyScraper
        from modules.tracker.database import upsert_job
        
        with st.spinner("🔍 Scraping jobs from all sources..."):
            scrapers = (
                [AdzunaScraper(country="us")]
                + [IndeedScraper()]
                + [RemotiveScraper()]
                + [JobicyScraper()]
                + [WeWorkRemotelyScraper()]
                + [USAJobsScraper()]
                + [LinkedInScraper()]
                + [GreenhouseScraper(t) for t in config.GREENHOUSE_BOARDS]
                + [LeverScraper(s) for s in config.LEVER_COMPANIES]
                + [AshbyScraper(c) for c in config.ASHBY_COMPANIES]
            )
            total = 0
            errors = []
            for sc in scrapers:
                try:
                    for j in sc.scrape(keyword=keyword, location=location, max_results=limit):
                        upsert_job(j)
                        total += 1
                except Exception as e:
                    errors.append(f"{type(sc).__name__}: {str(e)[:50]}")
            removed = deduplicate_jobs()
        
        if errors:
            st.warning(f"⚠️ {len(errors)} scraper(s) failed")
            with st.expander("View errors"):
                for err in errors:
                    st.text(err)
        
        st.success(f"✅ Scraped {total} jobs ({removed} duplicates removed)")
        st.rerun()
    
    # Score button
    if st.button("2️⃣ Score Jobs", use_container_width=True, help="Score jobs against your resume"):
        from modules.parser.jd_parser import parse_jd
        from modules.scorer.llm_scorer import score_llm
        from modules.parser.candidate_parser import load_cached_profile, parse_candidate
        from modules.tailor.resume_tailor import load_master_resume
        
        with st.spinner("📊 Scoring jobs against your resume..."):
            profile = load_cached_profile() or parse_candidate(load_master_resume())
            new_jobs = get_jobs(status="new", limit=500)
            prog = st.progress(0)
            scored, skipped = 0, 0
            
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
                    scored += 1
                prog.progress((i + 1) / max(len(new_jobs), 1))
        
        st.success(f"✅ Scored {scored} jobs ({skipped} skipped)")
        st.rerun()
    
    # Tailor section
    st.markdown("---")
    st.subheader("3️⃣ Tailor Resumes")
    tailor_limit = st.number_input("Max jobs", 1, 50, 10, step=5, key="tailor_limit")
    
    if st.button("Tailor Resumes", use_container_width=True, help="Generate custom resumes"):
        from modules.parser.jd_parser import parse_jd
        from modules.tailor.resume_tailor import tailor, load_master_resume
        from modules.tailor.cover_letter import generate as gen_cover, save as save_cover
        from modules.parser.candidate_parser import load_cached_profile, parse_candidate
        
        out_dir = config.ROOT_DIR / "resumes" / "tailored"
        cl_dir = config.ROOT_DIR / "resumes" / "cover_letters"
        
        with st.spinner("✂️ Tailoring resumes and cover letters..."):
            profile = load_cached_profile() or parse_candidate(load_master_resume())
            resume_text = load_master_resume()
            jobs = get_jobs(status="scored", min_score=config.MIN_SCORE_TO_TAILOR, limit=int(tailor_limit))
            target = filter_jobs(jobs) or jobs
            
            ok, failed = 0, 0
            progress_bar = st.progress(0)
            for idx, row in enumerate(target):
                try:
                    parsed = parse_jd(row["description_raw"])
                    tailor(resume_text, row["description_raw"], parsed, output_dir=out_dir)
                    cl_text = gen_cover(resume_text, row["description_raw"], parsed, candidate_name=profile.get("name", ""))
                    save_cover(cl_text, cl_dir, parsed)
                    update_job_status(row["id"], "tailored")
                    ok += 1
                except Exception as e:
                    failed += 1
                    st.warning(f"Failed: {row['title'][:30]}...")
                progress_bar.progress((idx + 1) / max(len(target), 1))
        
        st.success(f"✅ Tailored {ok} resumes" + (f" ({failed} failed)" if failed else ""))
        st.rerun()
    
    st.markdown("---")
    
    # Apply section
    st.subheader("4️⃣ Easy Apply")
    apply_limit = st.slider("Max applications", 1, 100, 20, step=5, key="apply_limit")
    do_submit = st.toggle("🚀 Actually submit", value=False, help="Turn ON to actually submit applications")
    do_headless = st.toggle("👻 Headless mode", value=False, help="Run browser without UI")
    
    if not do_submit:
        st.info("💡 Dry run mode: forms will be filled but NOT submitted")
    
    if st.button("Run Apply", use_container_width=True, type="primary" if do_submit else "secondary"):
        cmd = [sys.executable, "main.py", "apply", "--limit", str(apply_limit)]
        if do_submit:
            cmd.append("--submit")
        if do_headless:
            cmd.append("--headless")
        
        label = "🚀 Submitting" if do_submit else "🔍 Dry-running"
        with st.spinner(f"{label} {apply_limit} applications..."):
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(config.ROOT_DIR))
        
        output = result.stdout + ("\n" + result.stderr if result.stderr else "")
        st.session_state["last_apply_output"] = output
        st.rerun()
    
    st.markdown("---")
    
    # Full pipeline
    if st.button("⚡ Run Full Pipeline", use_container_width=True, type="primary"):
        cmd = [
            sys.executable, "main.py", "run",
            "--keyword", keyword, "--location", location,
            "--limit", str(limit), "--auto-apply", "--headless",
        ]
        if do_submit:
            cmd.append("--submit")
        
        with st.spinner("Running full pipeline (scrape → score → tailor → apply)..."):
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(config.ROOT_DIR))
        
        output = result.stdout + ("\n" + result.stderr if result.stderr else "")
        st.session_state["last_apply_output"] = output
        st.rerun()
    
    # Quick stats button
    st.markdown("---")
    if st.button("📊 Refresh Data", use_container_width=True):
        st.rerun()

# ── Main content ────────────────────────────────────────────────────────────────
st.title("🤖 Auto Apply Dashboard")
st.caption("Remote & NYC hybrid job application automation pipeline")

# ── Top metrics row ─────────────────────────────────────────────────────────────
target_df = pd.DataFrame(filter_jobs(all_jobs)) if all_jobs else pd.DataFrame()

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.metric("📦 Total Jobs", len(df_all), help="Total jobs in database")

with col2:
    st.metric("🎯 Target Jobs", len(target_df), help="Remote/NYC jobs matching criteria")

with col3:
    scored_count = _count("scored")
    st.metric("⭐ Scored", scored_count, help="Jobs scored against your profile")

with col4:
    tailored_count = _count("tailored")
    st.metric("✂️ Tailored", tailored_count, help="Jobs with custom resumes")

with col5:
    applied_count = _count("applied")
    st.metric("✅ Applied", applied_count, help="Applications submitted")

with col6:
    ignored_count = _count("ignored")
    st.metric("⚠️ Ignored", ignored_count, help="Jobs skipped (low quality/location)")

st.divider()

# ── Charts row ──────────────────────────────────────────────────────────────────
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("📊 Jobs by Status")
    if not df_all.empty and "status" in df_all.columns:
        status_counts = df_all["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Count"]
        
        fig = px.pie(
            status_counts, 
            values="Count", 
            names="Status",
            color_discrete_sequence=px.colors.qualitative.Set3,
            hole=0.4
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(height=300, margin=dict(t=0, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data yet — run Scrape first")

with chart_col2:
    st.subheader("📈 Fit Score Distribution")
    if not df_all.empty and "fit_score" in df_all.columns:
        scored_df = df_all[df_all["fit_score"].notna()]
        if not scored_df.empty:
            fig = px.histogram(
                scored_df, 
                x="fit_score", 
                nbins=20,
                color_discrete_sequence=["#636EFA"],
                opacity=0.7
            )
            fig.update_layout(
                xaxis_title="Fit Score",
                yaxis_title="Number of Jobs",
                height=300,
                margin=dict(t=0, b=0, l=0, r=0),
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No scored jobs yet")
    else:
        st.info("No data yet — run Score first")

# ── Tabs ────────────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "🎯 Apply Queue",
    "📋 All Jobs", 
    "🔍 Job Detail",
    "📬 Applications",
    "📄 Cover Letters",
    "📝 Run Log"
])

# ── Apply Queue tab ──────────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("🎯 Jobs Ready to Apply")
    st.caption("Remote & NYC hybrid positions with tailored resumes")
    
    tailored_all = get_jobs(status="tailored", min_score=config.AUTO_APPLY_MIN_SCORE, limit=500)
    _SKIP = {"usajobs", "adzuna", "remoteok", "linkedin"}
    applyable = filter_jobs([j for j in tailored_all if j["source"] not in _SKIP])
    
    if not applyable:
        st.info("👋 No jobs in the apply queue yet. Run **Scrape → Score → Tailor** first.")
    else:
        st.metric("Jobs Queued", len(applyable))
        q_df = pd.DataFrame(applyable)
        
        # Format for display
        display_cols = [c for c in ["title", "company", "location", "work_type", "fit_score", "source"] if c in q_df.columns]
        
        # Add clickable URLs
        for idx, row in q_df.iterrows():
            if row.get("url"):
                q_df.at[idx, "link"] = f"[🔗]({row['url']})"
        
        st.dataframe(
            q_df[display_cols + ["link"]].sort_values("fit_score", ascending=False),
            column_config={
                "fit_score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%.0f"),
                "link": st.column_config.TextColumn("Link"),
            },
            use_container_width=True,
            hide_index=True,
        )

# ── All Jobs tab ────────────────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("📋 All Jobs")
    
    # Filters
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    
    with filter_col1:
        min_score_filter = st.slider("Min score", 0, 100, 50, key="jobs_minscore")
    
    with filter_col2:
        loc_filter = st.selectbox("Location", ["All", "Remote/NYC only"], key="jobs_locfilter")
    
    with filter_col3:
        status_filter = st.selectbox(
            "Status", 
            ["all", "new", "scored", "tailored", "applied", "ignored"],
            key="jobs_status"
        )
    
    with filter_col4:
        source_filter = st.selectbox(
            "Source",
            ["all"] + list(df_all["source"].unique()) if not df_all.empty and "source" in df_all.columns else ["all"],
            key="jobs_source"
        )
    
    if df_all.empty:
        st.info("👋 No jobs yet — run **Scrape** from the sidebar.")
    else:
        disp = df_all.copy()
        
        # Apply filters
        if status_filter != "all":
            disp = disp[disp["status"] == status_filter]
        
        if "fit_score" in disp.columns:
            disp = disp[disp["fit_score"].fillna(0) >= min_score_filter]
        
        if loc_filter == "Remote/NYC only":
            disp = pd.DataFrame(filter_jobs(disp.to_dict("records"))) if not disp.empty else disp
        
        if source_filter != "all" and "source" in disp.columns:
            disp = disp[disp["source"] == source_filter]
        
        # Display columns
        display_cols = [c for c in ["title", "company", "location", "work_type", "fit_score", "status", "source"] if c in disp.columns]
        
        st.dataframe(
            disp[display_cols].sort_values("fit_score", ascending=False, na_position="last"),
            column_config={
                "fit_score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%.0f"),
            },
            use_container_width=True,
            hide_index=True,
        )
        
        st.caption(f"Showing {len(disp)} jobs")

# ── Job Detail tab ───────────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("🔍 Job Detail")
    
    if df_all.empty or df_all.get("fit_score", pd.Series(dtype=float)).isna().all():
        st.info("📊 Score some jobs first to see details.")
    else:
        scored_df = df_all[df_all["fit_score"].notna()].sort_values("fit_score", ascending=False)
        
        # Job selector
        job_options = scored_df.apply(
            lambda row: f"{row['fit_score']:.0f} | {row['title'][:40]} @ {row['company'][:25]}", 
            axis=1
        )
        choice = st.selectbox("Select a job", range(len(scored_df)), format_func=lambda i: job_options.iloc[i])
        row = scored_df.iloc[choice]
        
        # Two column layout
        detail_left, detail_right = st.columns([2, 1])
        
        with detail_left:
            st.markdown(f"### {row['title']}")
            
            # Company and metadata
            loc_tag = "🌐 Remote" if row.get("work_type") == "remote" else f"📍 {row.get('location', 'Unknown')}"
            st.markdown(f"**{row['company']}** | {loc_tag} | {row['work_type']} | *{row['source']}*")
            
            if row.get("url"):
                st.markdown(f"[🔗 View Posting]({row['url']})")
            
            st.markdown(f"**Status:** `{row['status']}`")
            
            # Full description
            with st.expander("📄 Full Job Description", expanded=False):
                st.text(row.get("description_raw", "")[:5000])
        
        with detail_right:
            # Score card
            score_val = row.get("fit_score", 0)
            score_color = _get_score_color(score_val)
            
            st.metric("Overall Score", f"{score_val:.0f}/100")
            
            # Fit breakdown
            if row.get("fit_breakdown"):
                try:
                    bd = json.loads(row["fit_breakdown"]) if isinstance(row["fit_breakdown"], str) else row["fit_breakdown"]
                    
                    st.markdown("**📊 Fit Breakdown**")
                    for k, v in bd.items():
                        if not k.startswith("_"):
                            st.metric(k.capitalize(), f"{float(v):.0f}/100")
                except:
                    pass
            
            # Salary info
            if row.get("salary_min") or row.get("salary_max"):
                salary_str = ""
                if row.get("salary_min"):
                    salary_str += f"${row['salary_min']:,.0f}"
                if row.get("salary_max"):
                    salary_str += f" - ${row['salary_max']:,.0f}"
                st.caption(f"💰 {salary_str}")
        
        # Strengths and Gaps
        strengths, gaps = [], []
        if row.get("fit_breakdown"):
            try:
                bd = json.loads(row["fit_breakdown"]) if isinstance(row["fit_breakdown"], str) else row["fit_breakdown"]
                strengths = bd.get("_strengths", [])
                gaps = bd.get("_gaps", [])
            except:
                pass
        
        if strengths or gaps:
            st.markdown("---")
            s_col, g_col = st.columns(2)
            
            with s_col:
                if strengths:
                    st.markdown("### ✅ Strengths")
                    for s in strengths:
                        st.markdown(f"- {s}")
            
            with g_col:
                if gaps:
                    st.markdown("### ⚠️ Gaps")
                    for g in gaps:
                        st.markdown(f"- {g}")

# ── Applications tab ─────────────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("📬 Application Log")
    
    apps = get_applications()
    
    if apps:
        apps_df = pd.DataFrame(apps)
        
        # Summary metrics
        app_col1, app_col2, app_col3 = st.columns(3)
        
        with app_col1:
            total_apps = len(apps_df)
            st.metric("Total Applications", total_apps)
        
        with app_col2:
            # Count by outcome
            if "outcome" in apps_df.columns:
                pending = len(apps_df[apps_df["outcome"] == "pending"])
                st.metric("Pending", pending)
        
        with app_col3:
            if "outcome" in apps_df.columns:
                interviews = len(apps_df[apps_df["outcome"] == "interview"])
                offers = len(apps_df[apps_df["outcome"] == "offer"])
                st.metric("Interviews/Offers", interviews + offers)
        
        st.markdown("---")
        
        # Applications table
        display_app_cols = [c for c in ["company", "title", "outcome", "applied_at", "method", "notes"] if c in apps_df.columns]
        
        st.dataframe(
            apps_df[display_app_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "applied_at": st.column_config.DatetimeColumn("Applied At"),
            }
        )
        
        # Application timeline
        if not apps_df.empty and "applied_at" in apps_df.columns:
            st.markdown("---")
            st.subheader("📅 Application Timeline")
            
            apps_df["applied_date"] = pd.to_datetime(apps_df["applied_at"]).dt.date
            timeline_data = apps_df.groupby("applied_date").size().reset_index(name="count")
            
            fig = px.line(
                timeline_data,
                x="applied_date",
                y="count",
                markers=True,
                labels={"applied_date": "Date", "count": "Applications"}
            )
            fig.update_layout(height=250, margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("📭 No applications logged yet. Run **Tailor** and **Apply** to start applying.")

# ── Cover Letters tab ────────────────────────────────────────────────────────────
with tabs[4]:
    st.subheader("📄 Cover Letters")
    
    cl_dir = config.ROOT_DIR / "resumes" / "cover_letters"
    cl_files = sorted(cl_dir.glob("cover_letter_*.txt")) if cl_dir.exists() else []
    
    if not cl_files:
        st.info("✂️ No cover letters yet — run **Tailor** from the sidebar.")
    else:
        # Cover letter selector
        chosen = st.selectbox(
            "Select cover letter", 
            cl_files,
            format_func=lambda p: p.stem.replace("cover_letter_", "").replace("_", " ").title()
        )
        
        if chosen:
            text = chosen.read_text(encoding="utf-8")
            
            # Preview
            st.text_area("Preview", text, height=400)
            
            # Download button
            st.download_button(
                label="📥 Download .txt",
                data=text,
                file_name=chosen.name,
                mime="text/plain"
            )

# ── Run Log tab ──────────────────────────────────────────────────────────────────
with tabs[5]:
    st.subheader("📝 Last Apply Run Output")
    
    output = st.session_state.get("last_apply_output", "")
    
    if output:
        st.code(output, language="text")
        
        if st.button("🗑️ Clear log"):
            st.session_state["last_apply_output"] = ""
            st.rerun()
    else:
        st.info("📝 No apply run yet this session. Use the sidebar to run Apply.")

# ── Footer ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Built with ❤️ using Streamlit | "
    f"Database: `{config.DB_PATH}` | "
    f"Log: `{config.LOG_PATH}`"
)
