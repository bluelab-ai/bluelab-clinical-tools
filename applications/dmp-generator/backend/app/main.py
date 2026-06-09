import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import DATA_DIR, WORKSPACES_DIR, DB_PATH
from app.database import init_db
from app.dependencies import get_current_user
from app.routers import auth, log, files, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(WORKSPACES_DIR, exist_ok=True)
    init_db(DB_PATH)
    yield


app = FastAPI(title="DMP Generation Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(log.router, prefix="/api/{project}/log", tags=["log"])
app.include_router(files.router, prefix="/api/{project}/files", tags=["files"])
app.include_router(chat.router, prefix="/api/{project}/chat", tags=["chat"])


@app.get("/api/projects")
def list_projects(request: Request, _=Depends(get_current_user)):
    ws = request.state.workspace
    base = os.path.join(WORKSPACES_DIR, ws)
    if not os.path.exists(base):
        return {"projects": []}
    dirs = sorted(
        [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))],
        key=lambda d: os.path.getmtime(os.path.join(base, d)),
        reverse=True,
    )
    return {"projects": dirs}


@app.delete("/api/projects/{project_name}")
def delete_project(project_name: str, request: Request, _=Depends(get_current_user)):
    if not project_name or project_name == "default":
        raise HTTPException(400, "Cannot delete the default project")
    ws = request.state.workspace
    base = os.path.join(WORKSPACES_DIR, ws)
    target = os.path.join(base, project_name)
    if not os.path.exists(target):
        raise HTTPException(404, "Project not found")
    if not str(target).startswith(str(base) + os.sep) and str(target) != str(base):
        raise HTTPException(400, "Invalid project name")
    shutil.rmtree(target)
    return {"status": "deleted", "project": project_name}


@app.get("/api/health")
def health():
    return {"status": "ok"}
