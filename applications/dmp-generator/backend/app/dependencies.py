from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.security import decode_token

security_scheme = HTTPBearer()


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
):
    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    request.state.user_id = payload["user_id"]
    request.state.workspace = payload["workspace"]
    return payload


FORBIDDEN_CHARS = {"..", "/", "\\", " ", "\t", "\n", "\r"}


def get_project(project: str):
    if not project or any(c in project for c in FORBIDDEN_CHARS):
        raise HTTPException(400, "Invalid project name")
    return project
