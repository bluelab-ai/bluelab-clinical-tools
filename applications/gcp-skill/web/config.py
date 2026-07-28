"""Centralized paths, constants, and settings."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Auto-load .env from skill root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---- Paths ----
SKILL_ROOT = Path(__file__).resolve().parent.parent  # GCP-2026-skill/
ARTICLES_DIR = SKILL_ROOT / "content" / "articles"
CURRICULUM_DIR = SKILL_ROOT / "curriculum"
EXAMS_DIR = SKILL_ROOT / "exams"
SCRIPTS_DIR = SKILL_ROOT / "scripts"
ASSETS_DIR = SKILL_ROOT / "assets"
RECORDS_DIR = SKILL_ROOT / ".training-records"  # legacy, kept for skill compatibility
USERS_DIR = SKILL_ROOT / "web" / "users"       # per-user isolated accounts
FEEDBACK_DIR = SKILL_ROOT / "web" / "feedback"  # user-submitted feedback / bug reports
DIFF_GUIDE_PATH = SKILL_ROOT / "content" / "diff-guide.md"
BANK_PATH = EXAMS_DIR / "bank.json"
CHAPTER_RULES_PATH = EXAMS_DIR / "chapter-quiz-rules.json"
FINAL_RULES_PATH = EXAMS_DIR / "final-exam-rules.json"

# Ensure directories exist
RECORDS_DIR.mkdir(parents=True, exist_ok=True)
USERS_DIR.mkdir(parents=True, exist_ok=True)
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

# ---- Chapter order ----
CHAPTERS = ["导论", "第一章", "第二章", "第三章", "第四章", "第五章", "第六章"]
CHAPTER_ARTICLES = {
    "导论": [],
    "第一章": list(range(1, 14)),   # 1-13
    "第二章": list(range(14, 18)),  # 14-17
    "第三章": list(range(18, 32)),  # 18-31
    "第四章": list(range(32, 51)),  # 32-50
    "第五章": list(range(51, 54)),  # 51-53
    "第六章": [54],
}

CHAPTER_TITLES = {
    "第一章": "第一章 总则",
    "第二章": "第二章 伦理审查委员会",
    "第三章": "第三章 研究者与机构",
    "第四章": "第四章 申办者",
    "第五章": "第五章 数据治理",
    "第六章": "第六章 附则",
}

# ---- Role definitions ----
ROLES = {
    "PI": {"emoji": "🏥", "label": "主要研究者（PI）/ 医生"},
    "CRA": {"emoji": "📋", "label": "临床监查员（CRA）"},
    "CRC": {"emoji": "📝", "label": "临床研究协调员（CRC）"},
    "student": {"emoji": "🎓", "label": "学生 / 初学者"},
}

ROLE_EMOJI_MAP = {v["emoji"]: k for k, v in ROLES.items()}

# ---- Section emoji to strip from display ----
STRIP_SECTION_EMOJIS = ["📜", "🔑", "🔄", "👤"]
KEEP_SECTION_EMOJIS = ["💡", "⚠️"]

# ---- DeepSeek via Anthropic-compatible endpoint ----
# DeepSeek provides an Anthropic-compatible API at /anthropic endpoint
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "deepseek-v4-pro")

# ---- Session secret ----
SESSION_SECRET = os.getenv("SESSION_SECRET", "gcp-training-dev-secret-change-in-prod")

# ---- Admin ----
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
