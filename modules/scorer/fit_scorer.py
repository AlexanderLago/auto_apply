# modules/scorer/fit_scorer.py
# Weighted rubric scoring — compares candidate profile vs ParsedJD.
# No LLM call needed; pure logic. Fast and deterministic.

from __future__ import annotations
import config
from modules.tracker.models import ParsedJD, FitResult

log = config.get_logger(__name__)


def score(
    candidate_skills: list[str],
    candidate_experience_years: int,
    candidate_education: str,
    candidate_location: str,
    parsed_jd: ParsedJD,
    weights: dict[str, float] | None = None,
) -> FitResult:
    """
    Score a candidate against a parsed job description.

    Returns a FitResult with a 0-100 score, per-category breakdown,
    strengths, gaps, and an auto recommendation.

    Extend this function to add new rubric dimensions — just add a key
    to `weights` and a corresponding _score_* function below.
    """
    w = weights or config.WEIGHTS

    # Per-category scores (each 0–100)
    s_skills     = _score_skills(candidate_skills, parsed_jd)
    s_experience = _score_experience(candidate_experience_years, parsed_jd.years_experience)
    s_education  = _score_education(candidate_education, parsed_jd.education_required)
    s_location   = _score_location(candidate_location, parsed_jd)

    breakdown = {
        "skills":     round(s_skills, 1),
        "experience": round(s_experience, 1),
        "education":  round(s_education, 1),
        "location":   round(s_location, 1),
    }

    total = sum(breakdown[k] * w.get(k, 0) for k in breakdown)
    total = round(min(100.0, max(0.0, total)), 1)

    strengths, gaps = _narrative(candidate_skills, parsed_jd, breakdown)

    recommendation = (
        "apply"             if total >= config.AUTO_APPLY_MIN_SCORE else
        "tailor_and_apply"  if total >= config.MIN_SCORE_TO_TAILOR  else
        "skip"
    )

    log.debug("Fit score: %.1f | %s", total, breakdown)
    return FitResult(
        score=total,
        breakdown=breakdown,
        strengths=strengths,
        gaps=gaps,
        recommendation=recommendation,
    )


# ── Category scorers ───────────────────────────────────────────────────────────

def _score_skills(candidate: list[str], jd: ParsedJD) -> float:
    if not jd.skills_required:
        return 80.0  # no requirements = not penalised
    cand_lower = {s.lower() for s in candidate}
    matched    = sum(1 for s in jd.skills_required if s.lower() in cand_lower)
    required   = len(jd.skills_required)
    base       = (matched / required) * 100

    # Bonus points for nice-to-have matches (up to +10)
    if jd.skills_nice_to_have:
        bonus_matched = sum(1 for s in jd.skills_nice_to_have if s.lower() in cand_lower)
        base += (bonus_matched / len(jd.skills_nice_to_have)) * 10

    return min(100.0, base)


def _score_experience(candidate_years: int, required_years: int | None) -> float:
    if required_years is None:
        return 80.0
    if candidate_years >= required_years:
        return 100.0
    if candidate_years >= required_years - 1:
        return 75.0
    if candidate_years >= required_years - 2:
        return 50.0
    return 25.0


def _score_education(candidate_edu: str, required_edu: str) -> float:
    if not required_edu:
        return 100.0
    c, r = candidate_edu.lower(), required_edu.lower()
    edu_rank = {"phd": 4, "doctorate": 4, "master": 3, "bachelor": 2, "associate": 1}
    c_rank = next((v for k, v in edu_rank.items() if k in c), 0)
    r_rank = next((v for k, v in edu_rank.items() if k in r), 0)
    if c_rank >= r_rank:
        return 100.0
    if c_rank == r_rank - 1:
        return 60.0
    return 30.0


def _score_location(candidate_loc: str, jd: ParsedJD) -> float:
    if jd.work_type == "remote":
        return 100.0
    if not jd.location or not candidate_loc:
        return 80.0
    if candidate_loc.lower() in jd.location.lower() or jd.location.lower() in candidate_loc.lower():
        return 100.0
    return 40.0


def _narrative(candidate_skills: list[str], jd: ParsedJD, breakdown: dict) -> tuple[list, list]:
    cand_lower = {s.lower() for s in candidate_skills}
    matched    = [s for s in jd.skills_required if s.lower() in cand_lower]
    missing    = [s for s in jd.skills_required if s.lower() not in cand_lower]

    strengths = [f"Matches required skill: {s}" for s in matched[:5]]
    if breakdown.get("experience", 0) >= 80:
        strengths.append("Meets experience requirement")

    gaps = [f"Missing required skill: {s}" for s in missing[:5]]
    if breakdown.get("experience", 0) < 60:
        gaps.append("Below required years of experience")

    return strengths, gaps
