import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
WORKSPACES_DIR = os.path.join(DATA_DIR, "workspaces")
DB_PATH = os.path.join(DATA_DIR, "app.db")
SKILL_DIR = os.path.join(BASE_DIR, "..", ".claude", "skills", "protocol-to-dmp")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
UPLOAD_MAX_SIZE_MB = 50
UPLOAD_ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
SESSION_TTL_MINUTES = 30
