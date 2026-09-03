import os
import secrets

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

DATA_DIR = os.path.join(BASE_DIR, "data")
FILES_DIR = os.path.join(BASE_DIR, "files")
DB_PATH = os.path.join(DATA_DIR, "app.db")

SAP_WORKFLOW_SCRIPT = os.path.join(BASE_DIR, "..", "scripts", "sap_workflow_graph.py")
PROJECTS_DIR = os.path.join(BASE_DIR, "..", "projects")
SAP_OUTPUT_BASE = PROJECTS_DIR

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(PROJECTS_DIR, exist_ok=True)
