import os

# ============================================================
# 用户可修改的配置项
# ============================================================

# JWT 密钥（生产环境必须修改）
SECRET_KEY = "dev-secret-change-in-production"

# LLM API 配置（所有 QC 脚本统一从此读取）
LLM_API_KEY = "sk-97e4571a55f04b5aa19b68cfb01a3378"
LLM_API_BASE = "https://api.deepseek.com/anthropic"
LLM_MODEL = "deepseek-v4-pro"

# ============================================================
# 以下为系统路径配置，通常无需修改
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
WORKSPACES_DIR = os.path.join(DATA_DIR, "workspaces")
DB_PATH = os.path.join(DATA_DIR, "app.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

# 文件永久归档目录（保留用户上传的原始文件，方便定位问题）
FILES_ARCHIVE_DIR = os.path.join(BASE_DIR, "files")

# tfl_qc_workflow.py 脚本路径
WORKFLOW_SCRIPT = os.path.join(BASE_DIR, "app", "qc_scripts", "cross_qc", "tfl_qc_workflow.py")

# inner_qc_workflow.py 脚本路径
INNER_QC_WORKFLOW_SCRIPT = os.path.join(BASE_DIR, "app", "qc_scripts", "inner_qc", "inner_qc_workflow.py")

# protocol_table_qc_workflow.py 脚本路径（功能1：方案表格一致性质控）
PROTOCOL_TABLE_WORKFLOW_SCRIPT = os.path.join(BASE_DIR, "app", "qc_scripts", "protocol_apply_qc", "qc_workflow.py")

# QC 脚本根目录（含 inner_qc / protocol_apply_qc / cross_qc 子目录）
QC_SCRIPTS_DIR = os.path.join(BASE_DIR, "app", "qc_scripts")

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
UPLOAD_MAX_SIZE_MB = 50
UPLOAD_ALLOWED_EXTENSIONS = {".docx", ".json", ".xlsx", ".xls"}
