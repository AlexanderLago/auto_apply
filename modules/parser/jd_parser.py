# modules/parser/jd_parser.py
# Uses Claude to extract structured data from a raw job description.
# Returns a ParsedJD model — used by the scorer and tailor.

import json
import re
import anthropic

import config
from modules.tracker.models import ParsedJD

log = config.get_logger(__name__)

_SYSTEM = """You are a job description analyst. Extract structured information from the job posting.
Return ONLY valid JSON matching this exact schema — no markdown, no explanation:
{
  "title": "exact job title from the posting",
  "company": "company name",
  "skills_required": ["skill1", "skill2"],
  "skills_nice_to_have": ["skill1", "skill2"],
  "years_experience": 3,
  "education_required": "Bachelor's in Computer Science or equivalent",
  "work_type": "remote | hybrid | onsite | unknown",
  "location": "city, state or 'Remote'",
  "summary": "1-2 sentence description of the role and what the company does"
}
Rules:
- skills_required: only hard requirements (must-have)
- skills_nice_to_have: preferred/bonus qualifications
- years_experience: integer, null if not specified
- Normalise skill names (e.g. 'MS Excel' → 'Excel', 'node.js' → 'Node.js')"""


def parse_jd(description: str, api_key: str = "") -> ParsedJD:
    """
    Parse a raw job description into structured fields using Claude.
    Falls back to a blank ParsedJD on any error.
    """
    key = api_key or config.ANTHROPIC_API_KEY
    if not key:
        log.error("No Anthropic API key — cannot parse JD")
        return ParsedJD(title="", company="", skills_required=[], skills_nice_to_have=[])

    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",   # fast + cheap for parsing
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": description[:6000]}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return ParsedJD(**data)
    except Exception as e:
        log.warning("JD parse failed: %s", e)
        return ParsedJD(title="", company="", skills_required=[], skills_nice_to_have=[])
