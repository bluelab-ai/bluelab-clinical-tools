import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, Form
from fastapi.responses import FileResponse

from app.config import UPLOAD_MAX_SIZE_MB, UPLOAD_ALLOWED_EXTENSIONS, UPLOAD_DIR, FILES_ARCHIVE_DIR
from app.dependencies import get_current_user
from app.utils.docx_validator import check_tracked_changes

router = APIRouter()

MAX_BYTES = UPLOAD_MAX_SIZE_MB * 1024 * 1024


def _get_upload_dir(workspace: str) -> str:
    d = os.path.join(UPLOAD_DIR, workspace)
    os.makedirs(d, exist_ok=True)
    return d


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    request: Request,
    category: str = Form("default"),
    temp_dir: str = Form(""),
    _=Depends(get_current_user),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型 {ext}，仅支持 {', '.join(UPLOAD_ALLOWED_EXTENSIONS)}")

    contents = await file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(400, f"文件超过 {UPLOAD_MAX_SIZE_MB}MB 限制")

    ws_dir = _get_upload_dir(request.state.workspace)

    # 若指定了临时文件夹，文件存入临时文件夹
    if temp_dir:
        abs_temp = os.path.abspath(temp_dir)
        abs_ws = os.path.abspath(ws_dir)
        if not (abs_temp.startswith(abs_ws + os.sep) or abs_temp == abs_ws):
            raise HTTPException(400, "临时目录不在用户工作区")
        os.makedirs(temp_dir, exist_ok=True)
        dest = os.path.join(temp_dir, file.filename)
    else:
        dest = os.path.join(ws_dir, file.filename)

    # 备份已存在的同名文件
    if os.path.exists(dest):
        bak = dest + ".bak"
        shutil.move(dest, bak)

    with open(dest, "wb") as f:
        f.write(contents)

    # 永久归档：副本到 backend/files/{timestamp}_{filename}/
    try:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        archive_dir = os.path.join(FILES_ARCHIVE_DIR, f"{ts}_{file.filename}")
        os.makedirs(archive_dir, exist_ok=True)
        archive_path = os.path.join(archive_dir, file.filename)
        with open(archive_path, "wb") as af:
            af.write(contents)
        print(f"[Files] 已归档: {archive_path}")
    except Exception as e:
        print(f"[Files] 归档失败（不影响上传）: {e}")

    return {
        "filename": file.filename,
        "path": dest,
        "size": len(contents),
        "category": category,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/check-tracked-changes")
async def check_tracked_changes_endpoint(
    path: str = Form(""),
    request: Request = None,
    _=Depends(get_current_user),
):
    """检测上传的 .docx 文件是否包含修订标记（上传后、质控前调用）。"""
    warn = check_tracked_changes(path)
    return {
        "has_tracked_changes": warn is not None,
        "warning": warn or "",
    }


@router.get("/download/{filename:path}")
def download_file(filename: str, request: Request, _=Depends(get_current_user)):
    ws_dir = _get_upload_dir(request.state.workspace)
    path = os.path.join(ws_dir, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=os.path.basename(filename))


# ─── 文件归档管理 ──────────────────────────────────────────────────────────

@router.get("/archive/stats")
def archive_stats(_=Depends(get_current_user)):
    """返回 files 文件夹下的文件统计信息"""
    if not os.path.exists(FILES_ARCHIVE_DIR):
        return {"file_count": 0, "dirs": 0}
    entries = []
    for root, _dirs, filenames in os.walk(FILES_ARCHIVE_DIR):
        for fn in filenames:
            full = os.path.join(root, fn)
            try:
                st = os.stat(full)
                entries.append({
                    "name": fn,
                    "path": os.path.relpath(full, FILES_ARCHIVE_DIR),
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                })
            except OSError:
                pass
    subdirs = [d for d in os.listdir(FILES_ARCHIVE_DIR)
               if os.path.isdir(os.path.join(FILES_ARCHIVE_DIR, d))]
    return {"file_count": len(entries), "dirs": len(subdirs), "files": entries}


@router.post("/archive/clear")
def archive_clear(_=Depends(get_current_user)):
    """清空 files 文件夹下的所有文件"""
    if os.path.exists(FILES_ARCHIVE_DIR):
        shutil.rmtree(FILES_ARCHIVE_DIR, ignore_errors=True)
        os.makedirs(FILES_ARCHIVE_DIR, exist_ok=True)
    return {"status": "cleared"}


@router.get("/archive/download-zip")
def archive_download_zip(_=Depends(get_current_user)):
    """打包下载 files 文件夹下的所有文件为 zip"""
    if not os.path.exists(FILES_ARCHIVE_DIR):
        raise HTTPException(404, "归档文件夹不存在，没有可下载的文件")

    zip_path = os.path.join(tempfile.gettempdir(), "tfl_qc_files_archive.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, filenames in os.walk(FILES_ARCHIVE_DIR):
            for fn in filenames:
                full = os.path.join(root, fn)
                arcname = os.path.relpath(full, FILES_ARCHIVE_DIR)
                zf.write(full, arcname)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return FileResponse(zip_path, filename=f"files_archive_{ts}.zip",
                        media_type="application/zip")
