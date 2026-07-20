import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import DATA_DIR, WORKSPACES_DIR, DB_PATH, UPLOAD_DIR
from app.database import init_db
from app.routers import auth, files, qc

# 前端静态文件目录（npm run build 产物）
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(WORKSPACES_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db(DB_PATH)
    yield


app = FastAPI(title="TFL QC Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(qc.router, prefix="/api/qc", tags=["qc"])


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ─── LLM 配置读写（用户自定义 API Key / Model / Base URL）───────────────

import re as _re

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")

# 缓存原始默认值（首次读取时记录，用于"未填写则恢复默认"）
_ORIGINAL_DEFAULTS: dict[str, str] = {}


def _read_llm_config() -> dict[str, str]:
    """读取 config.py 中的 LLM 配置值。"""
    result = {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    for key in ("LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL"):
        m = _re.search(rf'^{key}\s*=\s*"(.+?)"', content, _re.MULTILINE)
        if m:
            result[key] = m.group(1)
    return result


def _write_llm_config(updates: dict[str, str]) -> None:
    """将 LLM 配置写入 config.py，仅替换匹配的行。"""
    if not updates:
        return
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    for key, value in updates.items():
        if value:  # 有值才替换
            content = _re.sub(
                rf'^({key}\s*=\s*)"(.+?)"',
                rf'\1"{value}"',
                content,
                flags=_re.MULTILINE,
            )

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)


# 启动时记录原始默认值
_ORIGINAL_DEFAULTS.update(_read_llm_config())


@app.get("/api/config/llm")
def get_llm_config():
    """获取当前 LLM 配置（API Key 脱敏显示）。"""
    config = _read_llm_config()
    key = config.get("LLM_API_KEY", "")
    # 脱敏：只显示前4位和后4位
    if len(key) > 8:
        config["LLM_API_KEY_masked"] = key[:4] + "****" + key[-4:]
    elif key:
        config["LLM_API_KEY_masked"] = key[:2] + "****"
    else:
        config["LLM_API_KEY_masked"] = "（未设置）"
    # 不返回完整 API Key 给前端
    config.pop("LLM_API_KEY", None)
    return config


@app.put("/api/config/llm")
async def update_llm_config(body: dict):
    """更新 LLM 配置。未填写的字段保持原有值不变。"""
    updates: dict[str, str] = {}
    for key in ("LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL"):
        val = (body.get(key) or "").strip()
        if val:
            updates[key] = val
    if updates:
        _write_llm_config(updates)
        # 清除 import 缓存，使后续的 from config import 读到新值
        import importlib as _il
        import app.config as _cfg
        _il.reload(_cfg)
        return {"status": "ok", "updated": list(updates.keys())}
    return {"status": "ok", "updated": []}


# ─── SPA 托管（生产模式）──────────────────────────────────────────────────

_SPA_INDEX = os.path.join(FRONTEND_DIST, "index.html")
_SPA_READY = os.path.exists(_SPA_INDEX)

if _SPA_READY:
    from fastapi.staticfiles import StaticFiles

    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="spa_assets")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """兜底：非 /api 路径返回前端 SPA 入口"""
    if not _SPA_READY:
        if full_path == "logo.png":
            # 返回一个简单的 SVG logo
            from fastapi.responses import Response
            return Response(
                content='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#2563eb"/><text x="32" y="42" text-anchor="middle" fill="white" font-size="28" font-family="sans-serif" font-weight="bold">QC</text></svg>',
                media_type="image/svg+xml",
            )
        raise HTTPException(404, "Frontend not built. Run: cd frontend && npm run build")

    file_path = os.path.join(FRONTEND_DIST, full_path)
    if full_path and os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(_SPA_INDEX)
