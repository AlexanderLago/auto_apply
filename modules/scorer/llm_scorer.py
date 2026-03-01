# modules/scorer/llm_scorer.py
# LLM-based fit scorer — richer than keyword matching, understands context.
# Falls back to the rubric scorer if the LLM call fails.

from __future__ import annotations
from typing import List

import config
from modules.tracker.models import ParsedJD, FitResult
from modules.llm.client import call_llm, parse_json_response

log = config.get_logger(__name__)

_SYSTEM = """You are a resume-to-job fit evaluator. Score how well this candidate matches this job.

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
  - experience: years of experience vs requirement
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
