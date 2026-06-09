import json
import os

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.config import WORKSPACES_DIR
from app.dependencies import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


class LogEntry(BaseModel):
    data: dict


@router.get("/current")
def get_current_log(request: Request):
    log_path = os.path.join(WORKSPACES_DIR, request.state.workspace, "dm-log.json")
    if not os.path.exists(log_path):
        return {"entries": [], "latest": None}
    with open(log_path, "r", encoding="utf-8") as f:
        entries = json.load(f)
    return {"entries": entries, "latest": entries[-1] if entries else None}


@router.post("/save")
def save_log(entry: LogEntry, request: Request):
    log_path = os.path.join(WORKSPACES_DIR, request.state.workspace, "dm-log.json")
    entries = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    entries.append(entry.data)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=4)
    return {"status": "saved", "version_count": len(entries), "entries": entries}
