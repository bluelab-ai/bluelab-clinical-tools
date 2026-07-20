from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.security import decode_token

security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
):
    """JWT 认证依赖；开发模式下可跳过"""
    if credentials:
        try:
            payload = decode_token(credentials.credentials)
            request.state.user_id = payload["user_id"]
            request.state.workspace = payload["workspace"]
            return payload
        except Exception:
            raise HTTPException(401, "Invalid or expired token")

    # 开发模式：无 token 时使用默认用户
    request.state.user_id = 0
    request.state.workspace = "user_dev"
    return {"user_id": 0, "workspace": "user_dev"}
