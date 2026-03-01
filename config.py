# config.py — central config loaded once at startup
# All modules import from here; never import os.environ directly elsewhere.

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT_DIR          = Path(__file__).parent
DB_PATH           = ROOT_DIR / os.getenv("DB_PATH", "data/auto_apply.db")
LOG_PATH          = ROOT_DIR / os.getenv("LOG_PATH", "logs/auto_apply.log")
MASTER_RESUME     = ROOT_DIR / os.getenv("MASTER_RESUME_PATH", "resumes/master_resume.pdf")

# ── API keys ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ADZUNA_APP_ID     = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY    = os.getenv("ADZUNA_APP_KEY", "")

# ── Scraping targets ───────────────────────────────────────────────────────────
GREENHOUSE_BOARDS = [b.strip() for b in os.getenv("GREENHOUSE_BOARDS", "").split(",") if b.strip()]
LEVER_COMPANIES   = [c.strip() for c in os.getenv("LEVER_COMPANIES", "").split(",") if c.strip()]

# ── Scoring weights ────────────────────────────────────────────────────────────
WEIGHTS = {
    "skills":     float(os.getenv("WEIGHT_SKILLS",     0.40)),
    "experience": float(os.getenv("WEIGHT_EXPERIENCE", 0.30)),
    "education":  float(os.getenv("WEIGHT_EDUCATION",  0.15)),
    "location":   float(os.getenv("WEIGHT_LOCATION",   0.15)),
}

# ── Thresholds ─────────────────────────────────────────────────────────────────
AUTO_APPLY_MIN_SCORE  = int(os.getenv("AUTO_APPLY_MIN_SCORE", 75))
MIN_SCORE_TO_TAILOR   = int(os.getenv("MIN_SCORE_TO_TAILOR",  50))

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
