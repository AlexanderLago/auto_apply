# modules/parser/__init__.py
"""
Parser Module — Job Description and Candidate Profile Parsing

This module uses LLMs to extract structured information from text.

## Components

### jd_parser.py — Job Description Parser
Extracts structured requirements from job descriptions.

**Input:** Raw job description text  
**Output:** `ParsedJD` model with:
- Title
- Company
- Skills required (list)
- Skills nice to have (list)
- Years of experience
- Education required
- Work type (remote/hybrid/onsite)
- Location
- Summary

**Usage:**
```python
from modules.parser.jd_parser import parse_jd

jd_text = "We are looking for a Senior Data Analyst..."
parsed = parse_jd(jd_text)

print(parsed.skills_required)  # ["Python", "SQL", "Tableau", ...]
print(parsed.years_experience)  # 5
```

### candidate_parser.py — Resume Parser
Extracts candidate profile from master resume.

**Input:** Resume text (PDF/DOCX)  
**Output:** Dict with:
- Name
- Email
- Phone
- Location
- Education (degree, school, graduation year)
- Years of experience
- Skills (technical + soft)
- Titles (previous job titles)
- Summary

**Usage:**
```python
from modules.parser.candidate_parser import parse_candidate, load_cached_profile

# Parse from resume text
profile = parse_candidate(resume_text)

# Load from cache (faster, parsed on first run)
profile = load_cached_profile()
```

## LLM Provider

Uses `modules.llm.client` with auto-fallback:
- Groq (Llama 3.3 70B) — Fast, cheap
- Cerebras (Llama 3.1 70B) — Backup
- Gemini Flash — Fast alternative
- Anthropic Claude — High quality fallback

## Caching

Candidate profile is cached after first parse:
- Cache file: `.profile_cache.json`
- Re-parse with `parse_candidate(resume_text, force=True)`
"""

from modules.parser.jd_parser import parse_jd
from modules.parser.candidate_parser import parse_candidate, load_cached_profile

__all__ = [
    "parse_jd",
    "parse_candidate",
    "load_cached_profile",
]
