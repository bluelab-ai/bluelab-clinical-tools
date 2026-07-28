"""Route modules for GCP 2026 Training Web App."""
import json
import shutil
import zipfile
import io
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from web.config import USERS_DIR, RECORDS_DIR, FEEDBACK_DIR, ADMIN_PASSWORD

admin_router = APIRouter()


@admin_router.post("/admin/verify")
async def verify_admin(request: Request):
    if not ADMIN_PASSWORD:
        return JSONResponse({"detail": "管理员功能未配置"}, status_code=501)
    body = await request.json()
    if body.get("password") == ADMIN_PASSWORD:
        return {"status": "ok"}
    return JSONResponse({"detail": "密码错误"}, status_code=401)


@admin_router.get("/admin/users/count")
def user_count():
    if USERS_DIR.exists():
        count = len([d for d in USERS_DIR.iterdir() if d.is_dir()])
    else:
        count = 0
    return {"count": count}


@admin_router.post("/admin/archive/clear")
def clear_archive():
    if RECORDS_DIR.exists():
        shutil.rmtree(RECORDS_DIR)
        RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    return {"status": "ok"}


@admin_router.get("/admin/archive/download")
def download_archive():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for base_dir in (RECORDS_DIR, USERS_DIR, FEEDBACK_DIR):
            if base_dir.exists():
                for f in base_dir.rglob("*"):
                    if f.is_file():
                        zf.write(f, str(f.relative_to(base_dir.parent)))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=gcp_training_data.zip"},
    )


# ── Feedback submission ──────────────────────────────────────────────

@admin_router.post("/feedback/submit")
async def submit_feedback(request: Request):
    """Accept user feedback and save to a timestamped JSON file."""
    body = await request.json()
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    contact = (body.get("contact") or "").strip()
    page = (body.get("page") or "").strip()

    if not title or not content:
        return JSONResponse({"detail": "标题和内容不能为空"}, status_code=400)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{ts}.json"
    filepath = FEEDBACK_DIR / filename

    data = {
        "title": title,
        "content": content,
        "contact": contact,
        "page": page,
        "submitted_at": datetime.now().isoformat(),
        "user_agent": request.headers.get("user-agent", ""),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {"status": "ok"}
