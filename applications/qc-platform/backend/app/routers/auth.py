import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.utils.security import hash_password, verify_password, create_token

router = APIRouter()


class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    username: str
    workspace: str


@router.post("/register", response_model=AuthResponse)
def register(body: AuthRequest, db: Session = Depends(get_db)):
    if len(body.username.strip()) < 3:
        raise HTTPException(400, "用户名至少需要3个字符")
    if len(body.password) < 6:
        raise HTTPException(400, "密码至少需要6个字符")

    existing = db.query(User).filter(User.username == body.username.strip()).first()
    if existing:
        raise HTTPException(409, "用户名已存在")

    workspace = f"user_{body.username.strip()}"
    user = User(
        username=body.username.strip(),
        password=hash_password(body.password),
        workspace=workspace,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    from app.config import WORKSPACES_DIR
    os.makedirs(os.path.join(WORKSPACES_DIR, workspace), exist_ok=True)

    token = create_token(user.id, workspace)
    return AuthResponse(token=token, username=user.username, workspace=workspace)


@router.post("/login", response_model=AuthResponse)
def login(body: AuthRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user or not verify_password(body.password, user.password):
        raise HTTPException(401, "用户名或密码错误")

    token = create_token(user.id, user.workspace)
    return AuthResponse(token=token, username=user.username, workspace=user.workspace)


@router.get("/users/count")
def user_count(db: Session = Depends(get_db)):
    """返回已注册用户总数"""
    count = db.query(User).count()
    return {"count": count}


# ─── 管理员密码校验 ────────────────────────────────────────────────────

ADMIN_PASSWORD = "jkl2077"


class AdminRequest(BaseModel):
    password: str


@router.post("/admin/verify")
def verify_admin(body: AdminRequest):
    """校验管理员密码，通过后返回 token 供后续归档管理操作使用"""
    if body.password == ADMIN_PASSWORD:
        return {"status": "ok"}
    raise HTTPException(401, "密码错误")
