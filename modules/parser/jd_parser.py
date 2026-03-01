# modules/parser/jd_parser.py
# Uses the multi-provider LLM client to extract structured data from a raw JD.
# Returns a ParsedJD model — used by the scorer and tailor.

import config
from modules.tracker.models import ParsedJD
from modules.llm.client import call_llm, parse_json_response

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
- Normalise skill names (e.g. 'MS Excel' -> 'Excel', 'node.js' -> 'Node.js')"""


def parse_jd(description: str) -> ParsedJD:
    """
    Parse a raw job description into structured fields.
    Uses the multi-provider LLM chain. Falls back to a blank ParsedJD on error.
    """
    try:
        raw = call_llm(_SYSTEM, description[:6000], max_tokens=1024)
        data = parse_json_response(raw)
        # Drop null values so Pydantic model defaults kick in for optional string fields
        data = {k: v for k, v in data.items() if v is not None}
        return ParsedJD(**data)
    except Exception as e:
        log.warning("JD parse failed: %s", e)
        return ParsedJD(title="", company="", skills_required=[], skills_nice_to_have=[])
