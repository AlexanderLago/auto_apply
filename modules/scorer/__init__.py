# modules/scorer/__init__.py
"""
Scorer Module — Job Fit Scoring

This module calculates how well a candidate matches a job.

## Components

### llm_scorer.py — LLM-Based Scoring
Uses LLM to analyze fit between candidate and job.

**Input:**
- Candidate profile (skills, experience, education, location)
- Parsed job description (requirements, responsibilities)

**Output:** `FitResult` model with:
- Overall score (0-100)
- Breakdown by category:
  - Skills match (40%)
  - Experience match (30%)
  - Education match (15%)
  - Location match (15%)
- Strengths (list of positive factors)
- Gaps (list of missing requirements)
- Recommendation: "apply", "tailor_and_apply", or "skip"

**Usage:**
```python
from modules.scorer.llm_scorer import score_llm

result = score_llm(
    candidate_skills=["Python", "SQL", "Tableau"],
    candidate_experience_years=4,
    candidate_education="BS Computer Science",
    candidate_location="New Jersey",
    candidate_titles=["Data Analyst", "Business Analyst"],
    candidate_summary="Experienced data analyst...",
    parsed_jd=parsed_job_description,
)

print(result.score)          # 75.5
print(result.recommendation) # "tailor_and_apply"
print(result.strengths)      # ["Strong Python skills", ...]
print(result.gaps)           # ["Missing Spark experience", ...]
```

### fit_scorer.py — Rule-Based Scoring (Future)
Planned: Pure logic-based scoring without LLM for faster iteration.

## Scoring Weights

Configured in `.env` (must sum to 1.0):
```bash
WEIGHT_SKILLS=0.40
WEIGHT_EXPERIENCE=0.30
WEIGHT_EDUCATION=0.15
WEIGHT_LOCATION=0.15
```

## Thresholds

Configured in `.env`:
```bash
AUTO_APPLY_MIN_SCORE=68    # Only auto-apply if score >= 68
MIN_SCORE_TO_TAILOR=65     # Only tailor resume if score >= 65
```

## Performance

- LLM scoring: ~2-5 seconds per job (Groq/Cerebras)
- Batch scoring: 100 jobs in ~3-5 minutes
"""

from modules.scorer.llm_scorer import score_llm

__all__ = ["score_llm"]
