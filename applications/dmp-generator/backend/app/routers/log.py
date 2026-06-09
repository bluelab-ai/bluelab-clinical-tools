import json
import os

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel

from app.config import WORKSPACES_DIR
from app.dependencies import get_current_user, get_project

router = APIRouter(dependencies=[Depends(get_current_user)])


class LogEntry(BaseModel):
    data: dict


def _ws_project_dir(workspace: str, project: str) -> str:
    return os.path.join(WORKSPACES_DIR, workspace, project)


def _log_path(workspace: str, project: str) -> str:
    return os.path.join(_ws_project_dir(workspace, project), "dm-log.json")


@router.get("/current")
def get_current_log(request: Request, project: str = Depends(get_project)):
    log_path = _log_path(request.state.workspace, project)
    if not os.path.exists(log_path):
        return {"entries": [], "latest": None}
    with open(log_path, "r", encoding="utf-8") as f:
        entries = json.load(f)
    return {"entries": entries, "latest": entries[-1] if entries else None}


@router.post("/save")
def save_log(entry: LogEntry, request: Request, project: str = Depends(get_project)):
    log_path = _log_path(request.state.workspace, project)
    try:
        entries = []
        if os.path.exists(log_path):
            os.chmod(log_path, 0o644)
            with open(log_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        entries.append(entry.data)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=4)
            os.fchmod(f.fileno(), 0o644)
        return {"status": "saved", "version_count": len(entries), "entries": entries}
    except json.JSONDecodeError:
        raise HTTPException(400, detail="dm-log.json 文件格式错误，请删除后重试")
    except PermissionError as e:
        raise HTTPException(500, detail=f"文件权限不足: {str(e)}")
    except Exception as e:
        raise HTTPException(500, detail=f"保存失败: {str(e)}")
