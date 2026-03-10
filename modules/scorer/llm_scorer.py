# modules/scorer/llm_scorer.py
# LLM-based fit scorer — richer than keyword matching, understands context.
# Falls back to the rubric scorer if the LLM call fails.

from __future__ import annotations
from typing import List
import re

import config
from modules.tracker.models import ParsedJD, FitResult
from modules.llm.client import call_llm, parse_json_response

log = config.get_logger(__name__)

# Hard reject — these title patterns are never appropriate for a data/quant analyst
_REJECT_PATTERNS = [
    r'\baccount executive\b', r'\baccount manager\b', r'\bsales\b',
    r'\bbusiness development\b', r'\benablement\b', r'\bpartner development\b',
    r'\bfield marketing\b', r'\bgrowth marketing\b', r'\bmarketing manager\b',
    r'\bmarketing specialist\b', r'\bcontent.{0,10}brand\b', r'\bbrand\b',
    r'\bcustomer success\b', r'\bcustomer support\b', r'\btechnical account manager\b',
    r'\bsolutions architect\b', r'\bsolutions engineer\b', r'\bsolutions consultant\b',
    r'\bplatform architect\b', r'\bdelivery architect\b', r'\bstaff architect\b',
    r'\bengineering manager\b', r'\bstaff engineer\b', r'\bprincipal engineer\b',
    r'\bsoftware engineer\b', r'\bbackend engineer\b', r'\bfrontend engineer\b',
    r'\bmobile engineer\b', r'\bios engineer\b', r'\bandroid engineer\b',
    r'\bsre\b', r'\bdevops\b', r'\bsite reliability\b', r'\binfrastructure engineer\b',
    r'\bdeveloper relations\b', r'\bdeveloper advocate\b', r'\bdevrel\b',
    r'\bproduct manager\b', r'\bproduct designer\b', r'\bux designer\b',
    r'\bux researcher\b', r'\bdesigner\b',
    r'\bhr\b', r'\brecruiter\b', r'\btalent\b', r'\bpeople ops\b', r'\bpeople partner\b',
    r'\blegal counsel\b', r'\bcounsel\b', r'\bparalegal\b', r'\bcompliance.*payroll\b',
    r'\bpayroll\b', r'\baccounting\b', r'\baudit\b',
    r'\bdirector\b', r'\bvice president\b', r'\bvp \b', r'\bhead of\b',
    r'\bmanager,\b', r'\bmanager$', r'^manager\b',
    r'\bprincipal product\b', r'\bstaff product\b',
    r'\bex.founder\b', r'\bfounder\b',
    r'\bcybersecurity\b', r'\binfosec\b', r'\bsecurity engineer\b',
    r'\bnetwork engineer\b', r'\bsysadmin\b', r'\bit specialist\b',
    r'\bprevention specialist\b', r'\bintelligence specialist\b',
    r'\bcomputer assistant\b', r'\bparalegal\b',
    r'\bintern\b',  # interns are not 4-year-experience roles
]

# Must match at least one of these to be considered (if title has no data/quant signal,
# it might still be OK if the JD description mentions analyst work — let LLM decide)
_REQUIRE_ONE_OF = [
    r'\banalyst\b', r'\banalysis\b', r'\banalytics\b',
    r'\bquant\b', r'\bquantitative\b',
    r'\bdata\b', r'\bdataset\b',
    r'\bfinancial\b', r'\bfinance\b',
    r'\brisk\b', r'\bfraud\b', r'\bcredit\b',
    r'\bstatistic\b', r'\bmodeling\b', r'\bforecasting\b',
    r'\boperations\b',  # ops analyst roles
    r'\bscientist\b',  # data scientist
    r'\breporting\b', r'\binsights\b', r'\bintelligence\b(?!.*specialist)',
    r'\bstrategy\b', r'\bplanning\b',
]


def _title_prefilter(title: str) -> bool:
    """Return True if the title should be scored, False if it should be immediately rejected."""
    t = title.lower()

    # Strong analytical signals — if present, it's likely a data/quant role
    _STRONG_SIGNALS = [
        r'\banalyst\b', r'\banalysis\b', r'\banalytics\b',
        r'\bquant\b', r'\bquantitative\b',
        r'\bdata scientist\b', r'\bdata engineer\b',
        r'\bstatistician\b', r'\bactuary\b',
        r'\bfraud.{0,10}analyst\b', r'\bcredit.{0,10}analyst\b',
        r'\brisk.{0,10}analyst\b', r'\bfinancial analyst\b',
    ]
    has_strong_signal = any(re.search(p, t) for p in _STRONG_SIGNALS)

    # Hard-reject patterns — always disqualify regardless of other signals
    _HARD_REJECT = [
        r'\bdirector\b', r'\bvice president\b', r'\bvp \b', r'\bhead of\b',
        r'\bsenior manager\b', r'\bsenior director\b',
        r'\bprincipal (?!analyst|data|quant|scientist)\b',
        r'\bstaff (?!analyst|data|quant|scientist)\b',
        r'\bpayroll\b', r'\baudit\b', r'\bintern\b',
        r'\bsales\b(?!.{0,10}analyst)', r'\baccount executive\b',
        r'\baccount manager\b', r'\bbusiness development\b',
        r'\benablement\b', r'\bcustomer success\b',
        r'\bsolutions architect\b', r'\bsolutions engineer\b',
        r'\bsolutions consultant\b', r'\bdelivery architect\b',
        r'\bengineering manager\b', r'\bsoftware engineer\b',
        r'\bbackend engineer\b', r'\bfrontend engineer\b',
        r'\bmobile engineer\b', r'\bsre\b', r'\bdevops\b',
        r'\bdeveloper relations\b', r'\bdeveloper advocate\b',
        r'\bproduct manager\b', r'\bproduct designer\b',
        r'\brecruiter\b', r'\btalent\b(?!.{0,10}analyst)',
        r'\blegal counsel\b', r'\bparalegal\b',
        r'\bmarketing manager\b', r'\bfield marketing\b',
        r'\brevenue operations\b', r'\bpartner development\b',
        r'\bcybersecurity\b', r'\binfosec\b', r'\bsecurity engineer\b',
        r'\bsysadmin\b', r'\bit specialist\b', r'\bnetwork engineer\b',
    ]

    if any(re.search(p, t) for p in _HARD_REJECT):
        return False

    if has_strong_signal:
        return True

    # Weaker signals: financial, data, operations, strategy — keep only if
    # not caught by reject patterns above and seems analytically-oriented
    _WEAK_SIGNALS = [
        r'\bdata\b(?!.{0,5}entry)', r'\bfinancial\b', r'\brisk\b',
        r'\bfraud\b', r'\bcredit\b', r'\bforecasting\b', r'\bmodeling\b',
        r'\binsights\b', r'\breporting\b', r'\bscientist\b',
        r'\boperations analyst\b', r'\bstrategy analyst\b',
        r'\bplanning analyst\b', r'\bbusiness intelligence\b',
    ]
    return any(re.search(p, t) for p in _WEAK_SIGNALS)

_SYSTEM = """You are a resume-to-job fit evaluator for a quantitative/data analyst with 4 years of experience.

TARGET ROLES (score generously if title matches these):
- Data Analyst, Quantitative Analyst, Business Analyst with data focus
- Financial Analyst, Credit/Risk/Fraud Analyst
- Data Governance Analyst, Analytics Engineer
- Associate/Junior Data Scientist (NOT senior or staff level)
- Operations/Strategy Analyst with heavy data component

AUTOMATICALLY SCORE 0 AND SET recommendation="skip" for these — do not evaluate further:
- Management roles: Director, VP, Head of, Engineering Manager, Senior Manager, Principal (not analyst)
- Sales/GTM roles: Account Executive, Sales Manager, Business Development, Enablement, Revenue Operations
- Marketing roles: Marketing Manager, Growth Marketing, Field Marketing
- Engineering roles: Software Engineer, Backend Engineer, SRE, DevOps, Solutions Architect, Solutions Engineer
- Customer-facing non-analytical: Customer Success Manager, Customer Support, Technical Account Manager
- HR/People roles: Recruiter, HR Business Partner, People Operations
- Product Management: Product Manager, Product Designer
- Other: Developer Relations, Payroll Specialist, Legal, Paralegal, IT Specialist, Cybersecurity
- Senior-only roles requiring 7+ years experience when the candidate has 4

Return ONLY valid JSON — no markdown, no explanation:
{
  "score": 72,
  "breakdown": {
    "skills": 80,
    "experience": 65,
    "education": 75,
    "location": 100
  },
  "strengths": ["Has 4 years data governance experience directly relevant to the role",
                "SQL and Python match required technical skills"],
  "gaps": ["Missing required Snowflake experience",
           "Role requires 6 years, candidate has 4"],
  "recommendation": "tailor_and_apply"
}

Scoring rules:
- score: integer 0-100 (weighted average of breakdown)
- breakdown: each dimension 0-100
  - skills: how many required + nice-to-have skills the candidate has
  - experience: years of experience vs requirement (4 years is mid-level)
  - education: candidate education level vs requirement
  - location: remote-friendly or location match (100 if remote or matching city)
- strengths: 2-4 specific, concrete reasons this candidate is a good fit
- gaps: 2-4 specific missing requirements (empty list [] if there are none)
- recommendation: exactly one of:
  - "apply"            if score >= 75
  - "tailor_and_apply" if score 50-74
  - "skip"             if score < 50
- Be realistic — don't inflate scores for weak matches
- Give credit for transferable skills and adjacent experience"""


def score_llm(
    candidate_skills: List[str],
    candidate_experience_years: int,
    candidate_education: str,
    candidate_location: str,
    candidate_titles: List[str],
    candidate_summary: str,
    parsed_jd: ParsedJD,
) -> FitResult:
    """
    Score candidate vs job using LLM. Falls back to rubric scorer on any error.
    """
    # Pre-filter: reject clearly wrong role types before calling LLM
    if not _title_prefilter(parsed_jd.title):
        log.debug("Title pre-filter rejected: %s", parsed_jd.title)
        return FitResult(score=0.0, breakdown={}, strengths=[],
                         gaps=["Role type not relevant for data/quant analyst"],
                         recommendation="skip")

    candidate_block = (
        f"CANDIDATE:\n"
        f"- Summary: {candidate_summary}\n"
        f"- Titles held: {', '.join(candidate_titles[:5])}\n"
        f"- Skills: {', '.join(candidate_skills[:35])}\n"
        f"- Years experience: {candidate_experience_years}\n"
        f"- Education: {candidate_education}\n"
        f"- Location: {candidate_location}"
    )

    jd_block = (
        f"JOB:\n"
        f"- Title: {parsed_jd.title} at {parsed_jd.company}\n"
        f"- Required skills: {', '.join(parsed_jd.skills_required)}\n"
        f"- Nice-to-have: {', '.join(parsed_jd.skills_nice_to_have)}\n"
        f"- Years required: {parsed_jd.years_experience}\n"
        f"- Education required: {parsed_jd.education_required}\n"
        f"- Work type: {parsed_jd.work_type}\n"
        f"- Location: {parsed_jd.location}\n"
        f"- Summary: {parsed_jd.summary}"
    )

    try:
        raw  = call_llm(_SYSTEM, f"{candidate_block}\n\n{jd_block}", max_tokens=512)
        data = parse_json_response(raw)
        data = {k: v for k, v in data.items() if v is not None}

        score_val = float(data.get("score", 0))
        # Normalize recommendation to match score, in case LLM drifts
        if score_val >= 75:
            rec = "apply"
        elif score_val >= 50:
            rec = "tailor_and_apply"
        else:
            rec = "skip"

        return FitResult(
            score=round(score_val, 1),
            breakdown=data.get("breakdown", {}),
            strengths=data.get("strengths", []),
            gaps=data.get("gaps", []),
            recommendation=rec,
        )

    except Exception as e:
        log.warning("LLM scorer failed (%s) — falling back to rubric scorer", e)
        from modules.scorer.fit_scorer import score as rubric_score
        return rubric_score(
            candidate_skills=candidate_skills,
            candidate_experience_years=candidate_experience_years,
            candidate_education=candidate_education,
            candidate_location=candidate_location,
            parsed_jd=parsed_jd,
        )
