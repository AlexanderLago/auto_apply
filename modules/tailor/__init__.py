# modules/tailor/__init__.py
"""
Tailor Module — Resume and Cover Letter Customization

This module generates customized application documents per job.

## Components

### resume_tailor.py — Resume Tailoring
Customizes master resume for specific job requirements.

**Input:**
- Master resume text
- Job description raw text
- Parsed job description (ParsedJD model)

**Output:**
- Tailored resume JSON with:
  - Customized summary
  - Reordered skills (job-relevant first)
  - Highlighted experience matching job requirements
- DOCX file saved to `resumes/tailored/`

**Usage:**
```python
from modules.tailor.resume_tailor import tailor, load_master_resume

resume_text = load_master_resume()
output_dir = Path("resumes/tailored")

tailor(
    resume_text=resume_text,
    job_description=jd_text,
    parsed_jd=parsed_job,
    output_dir=output_dir,
)
# Output: resumes/tailored/resume_<company>.docx
```

### cover_letter.py — Cover Letter Generation
Generates customized cover letters per job.

**Input:**
- Master resume text
- Job description
- Parsed job description
- Candidate name

**Output:**
- Cover letter text file
- Saved to `resumes/cover_letters/`

**Usage:**
```python
from modules.tailor.cover_letter import generate, save

cl_text = generate(
    resume_text=resume_text,
    job_description=jd_text,
    parsed_jd=parsed_job,
    candidate_name="Alexander Lago",
)

save(cl_text, output_dir=Path("resumes/cover_letters"), parsed=parsed_job)
# Output: resumes/cover_letters/cover_letter_<company>.txt
```

### docx_builder.py — DOCX Generation
Creates formatted Word documents from structured data.

**Features:**
- Professional formatting
- Section headers
- Bullet points
- Contact info header

### pdf_builder.py — PDF Generation (Optional)
Converts DOCX to PDF for submission.

**Note:** Some ATS platforms prefer DOCX (parseable), use PDF only when required.

## LLM Provider

Uses Anthropic Claude (Sonnet/Haiku) for high-quality tailoring:
- Haiku: Fast, cheap for initial draft
- Sonnet: Higher quality for final polish

## File Naming

- Resumes: `resumes/tailored/resume_<company_slug>.docx`
- Cover Letters: `resumes/cover_letters/cover_letter_<company_slug>.txt`

Company slug: lowercase, no spaces, first 20 chars
Example: "Goldman Sachs" → "goldmansachs"
"""

from modules.tailor.resume_tailor import tailor, load_master_resume
from modules.tailor.cover_letter import generate, save
from modules.tailor.docx_builder import create_resume_docx
from modules.tailor.pdf_builder import create_resume_pdf

__all__ = [
    "tailor",
    "load_master_resume",
    "generate",
    "save",
    "create_resume_docx",
    "create_resume_pdf",
]
