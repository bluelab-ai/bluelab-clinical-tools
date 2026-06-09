import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
from app.config import SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRATION_HOURS, WORKSPACES_DIR


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: int, workspace: str) -> str:
    payload = {
        "user_id": user_id,
        "workspace": workspace,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])


def safe_path(workspace: str, project: str, filename: str) -> Path:
    base = Path(WORKSPACES_DIR).resolve()
    root = (base / workspace / project).resolve()
    target = (base / workspace / project / filename).resolve()
    if not str(target).startswith(str(root) + os.sep) and str(target) != str(root):
        raise ValueError("Path traversal detected")
    return target
