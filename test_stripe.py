# Direct Stripe application test
import config
from pathlib import Path
from modules.applicator.easy_apply import EasyApplyBot
from modules.tracker.models import Job

print("=== Stripe Application Test ===")

# Create Stripe job directly
job = Job(
    source='greenhouse',
    external_id='5956528',
    title='Strategy & Business Operations, Stripe Business Performance',
    company='Stripe',
    location='Remote',
    work_type='Full-time',
    url='https://job-boards.greenhouse.io/stripe/jobs/5956528',  # Removed /apply suffix
    description_raw='Strategy role at Stripe',
    skills_required=[],
    skills_nice_to_have=[],
)

# Find tailored resume
tailored_dir = config.ROOT_DIR / 'resumes' / 'tailored'
resume = tailored_dir / 'resume_stripe.docx'
if not resume.exists():
    resume = next(tailored_dir.glob('*.docx'), None)
    if not resume:
        resume = config.MASTER_RESUME

print(f"Using resume: {resume}")
print(f"Resume exists: {resume.exists()}")
print(f"Job URL: {job.url}")

# Apply
print("\n=== Starting Application ===")
try:
    with EasyApplyBot(resume_path=resume, headless=False, submit=False) as bot:  # Dry run first
        outcome = bot.apply(job, job_id=999)
        print(f"\n=== Outcome ===")
        print(f"Status: {outcome.status}")
        print(f"Error: {outcome.error}")
except Exception as e:
    print(f"Exception: {e}")
    import traceback
    traceback.print_exc()
