import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.config import UPLOAD_MAX_SIZE_MB, UPLOAD_ALLOWED_EXTENSIONS
from app.dependencies import get_current_user, get_project
from app.utils.security import safe_path

router = APIRouter(dependencies=[Depends(get_current_user)])

MAX_BYTES = UPLOAD_MAX_SIZE_MB * 1024 * 1024


def _ws_project_dir(workspace: str, project: str) -> str:
    from app.config import WORKSPACES_DIR
    return os.path.join(WORKSPACES_DIR, workspace, project)


@router.post("/upload")
async def upload_file(file: UploadFile, request: Request, project: str = Depends(get_project)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type {ext} not allowed")

    contents = await file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(400, f"File exceeds {UPLOAD_MAX_SIZE_MB}MB limit")

    ws_dir = _ws_project_dir(request.state.workspace, project)
    os.makedirs(ws_dir, exist_ok=True)
    dest = os.path.join(ws_dir, file.filename)
    if os.path.exists(dest):
        bak = dest + ".bak"
        shutil.move(dest, bak)

    with open(dest, "wb") as f:
        f.write(contents)

    return {
        "filename": file.filename,
        "size": len(contents),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/list")
def list_files(request: Request, project: str = Depends(get_project)):
    ws_dir = _ws_project_dir(request.state.workspace, project)
    if not os.path.exists(ws_dir):
        return {"files": []}

    logs, protocols, dmp_outputs = [], [], []
    for name in os.listdir(ws_dir):
        fpath = os.path.join(ws_dir, name)
        if not os.path.isfile(fpath):
            continue
        stat = os.stat(fpath)
        info = {
            "name": name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
        ext = Path(name).suffix.lower()
        if name.startswith("dm-log") or name.endswith(".json"):
            info["category"] = "log"
            logs.append(info)
        elif name.startswith("DMP") or name.startswith("DMP-"):
            info["category"] = "dmp"
            dmp_outputs.append(info)
        elif ext in UPLOAD_ALLOWED_EXTENSIONS:
            info["category"] = "protocol"
            protocols.append(info)

    return {"files": logs + protocols + dmp_outputs}


@router.get("/download/{filename}")
def download_file(filename: str, request: Request, project: str = Depends(get_project)):
    path = safe_path(request.state.workspace, project, filename)
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(path), filename=filename)


@router.get("/read/{filename}")
def read_file(filename: str, request: Request, project: str = Depends(get_project)):
    try:
        path = safe_path(request.state.workspace, project, filename)
    except ValueError:
        raise HTTPException(400, "Invalid filename")
    if not path.exists():
        raise HTTPException(404, "File not found")
    if not path.is_file():
        raise HTTPException(400, "Not a file")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not a readable text file")
    return {"name": filename, "content": content}


@router.delete("/delete/{filename}")
def delete_file(filename: str, request: Request, project: str = Depends(get_project)):
    path = safe_path(request.state.workspace, project, filename)
    if not path.exists():
        raise HTTPException(404, "File not found")
    os.remove(str(path))
    return {"status": "deleted", "filename": filename}
