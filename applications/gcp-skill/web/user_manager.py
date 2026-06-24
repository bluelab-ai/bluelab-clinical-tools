from __future__ import annotations
"""User account management with password hashing and per-user isolation."""
import hashlib
import secrets
import json
from pathlib import Path
from web.config import USERS_DIR


def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Hash a password with PBKDF2-SHA256. Returns (salt, hash_hex)."""
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    )
    return salt, key.hex()


def user_exists(username: str) -> bool:
    """Check if a username already exists."""
    return (USERS_DIR / username).exists()


def create_user(username: str, password: str, real_name: str = "",
                org_type: str = "", job_role: str = "") -> dict:
    """Create a new user account. Raises ValueError if username exists.
    org_type: work nature (高校/药企/CRO/医院/其他)
    job_role: job role (医生/CRC/CRA/学生/教师/其他)"""
    if user_exists(username):
        raise ValueError(f"用户名 '{username}' 已存在，请选择其他用户名。")

    salt, pw_hash = _hash_password(password)
    user_dir = USERS_DIR / username
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "records").mkdir(exist_ok=True)

    account = {
        "username": username,
        "password_hash": pw_hash,
        "password_salt": salt,
        "real_name": real_name,
        "roles": [],
        "created_at": "",
        "org_type": org_type,
        "job_role": job_role,
    }
    _save_account(username, account)
    return account


def verify_login(username: str, password: str) -> dict | None:
    """Verify username and password. Returns account dict or None."""
    account = load_account(username)
    if not account:
        return None
    salt = account.get("password_salt", "")
    _, pw_hash = _hash_password(password, salt)
    if pw_hash == account.get("password_hash", ""):
        return account
    return None


def load_account(username: str) -> dict | None:
    """Load a user account."""
    filepath = USERS_DIR / username / "account.json"
    if not filepath.exists():
        return None
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def _save_account(username: str, account: dict):
    """Save a user account to disk."""
    filepath = USERS_DIR / username / "account.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(account, f, ensure_ascii=False, indent=2)


def set_real_name(username: str, real_name: str):
    """Update the user's real name."""
    account = load_account(username)
    if account:
        account["real_name"] = real_name
        _save_account(username, account)


def add_role(username: str, role: str, role_label: str, has_old_basis: bool):
    """Add a role to the user's account."""
    account = load_account(username)
    if account:
        account["roles"].append({
            "role": role,
            "role_label": role_label,
            "has_old_basis": has_old_basis,
        })
        _save_account(username, account)


def get_user_records_dir(username: str) -> Path:
    """Get the per-user records directory."""
    user_dir = USERS_DIR / username / "records"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir
