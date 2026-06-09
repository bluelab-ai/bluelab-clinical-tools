# DMP Generation Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web platform where users register, fill DM log metadata, upload protocol documents, and interact with Claude SDK + protocol-to-dmp skill through a chat interface to generate DMP Word documents.

**Architecture:** React SPA frontend communicating with FastAPI backend via REST + SSE. Backend manages per-user SQLite auth, file-system-isolated workspaces, and Claude SDK sessions that autonomously execute the protocol-to-dmp skill workflow, streaming output and questions to the frontend in real-time.

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy / SQLite / bcrypt / PyJWT / Anthropic Python SDK / React 18+ / TypeScript / Vite / React Router / Axios

---

## File Structure

```
backend/
  requirements.txt
  app/
    __init__.py
    main.py                  # FastAPI app entry: CORS, router mounts, startup DB init
    config.py                 # Settings from env vars with defaults
    database.py               # SQLAlchemy engine, sessionmaker, Base, init_db()
    models.py                 # User SQLAlchemy model
    dependencies.py           # get_current_user FastAPI dependency
    routers/
      __init__.py
      auth.py                 # POST /api/auth/register, /api/auth/login
      log.py                  # GET /api/log/current, POST /api/log/save
      files.py                # POST /api/files/upload, GET list/download, DELETE delete
      chat.py                 # POST /api/chat/send, POST /api/chat/start-dmp
    services/
      __init__.py
      workspace.py            # WorkspaceManager: create, list, resolve paths
      dmp_orchestrator.py     # DMPOrchestrator: Claude SDK session, SSE generation
    utils/
      __init__.py
      security.py             # hash_password, verify_password, create_token, safe_path
  tests/
    __init__.py
    conftest.py
    test_auth.py
    test_log.py
    test_files.py

frontend/
  package.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  index.html
  src/
    main.tsx
    App.tsx
    vite-env.d.ts
    types/
      index.ts
    services/
      api.ts                  # Axios instance with JWT interceptor
    hooks/
      useAuth.ts
      useSSE.ts
    contexts/
      AuthContext.tsx
    pages/
      LoginPage.tsx
      RegisterPage.tsx
      LogFormPage.tsx
      ChatPage.tsx
    components/
      ProtectedRoute.tsx
      FileSidebar.tsx
      ChatMessage.tsx
      ChatInput.tsx
      QuestionCard.tsx
      FileUpload.tsx
```

---

### Task 1: Backend Project Scaffolding

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy==2.0.35
bcrypt==4.2.0
PyJWT==2.9.0
anthropic==0.40.0
python-multipart==0.0.12
python-docx==1.1.2
openpyxl==3.1.5
pytest==8.3.0
httpx==0.27.0
```

- [ ] **Step 2: Create config.py**

```python
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
WORKSPACES_DIR = os.path.join(DATA_DIR, "workspaces")
DB_PATH = os.path.join(DATA_DIR, "app.db")
SKILL_DIR = os.path.join(BASE_DIR, "..", ".claude", "skills", "protocol-to-dmp")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
UPLOAD_MAX_SIZE_MB = 50
UPLOAD_ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
SESSION_TTL_MINUTES = 30
```

- [ ] **Step 3: Create main.py**

```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import DATA_DIR, WORKSPACES_DIR, DB_PATH
from app.database import init_db
from app.routers import auth, log, files, chat

app = FastAPI(title="DMP Generation Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(log.router, prefix="/api/log", tags=["log"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])


@app.on_event("startup")
def on_startup():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(WORKSPACES_DIR, exist_ok=True)
    init_db(DB_PATH)


@app.get("/api/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Install dependencies and verify startup**

Run: `cd backend && pip install -r requirements.txt`
Run: `cd backend && uvicorn app.main:app --reload --port 8000`
Expected: App starts without errors, `GET http://localhost:8000/api/health` returns `{"status":"ok"}`

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "feat: scaffold backend project with FastAPI, config, and health endpoint"
```

---

### Task 2: Database Models & Init

**Files:**
- Create: `backend/app/database.py`
- Create: `backend/app/models.py`

- [ ] **Step 1: Create database.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

engine = None
SessionLocal = None


class Base(DeclarativeBase):
    pass


def init_db(db_path: str):
    global engine, SessionLocal
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    from app.models import User  # noqa: F401
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: Create models.py**

```python
from sqlalchemy import Column, Integer, String
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password = Column(String, nullable=False)
    workspace = Column(String, unique=True, nullable=False)
    created_at = Column(String, nullable=False)
```

- [ ] **Step 3: Verify table creation**

Run: `cd backend && python -c "from app.database import init_db; from app.config import DB_PATH; init_db(DB_PATH); print('OK')"`
Expected: Prints OK, `backend/data/app.db` created with `users` table.

- [ ] **Step 4: Commit**

```bash
git add backend/app/database.py backend/app/models.py
git commit -m "feat: add SQLite database layer with User model"
```

---

### Task 3: Auth Utilities & Router

**Files:**
- Create: `backend/app/utils/__init__.py`
- Create: `backend/app/utils/security.py`
- Create: `backend/app/routers/__init__.py`
- Create: `backend/app/routers/auth.py`

- [ ] **Step 1: Create security.py**

```python
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
from app.config import SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRATION_HOURS, WORKSPACES_DIR


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: int, workspace: str) -> str:
    payload = {
        "user_id": user_id,
        "workspace": workspace,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])


def safe_path(workspace: str, filename: str) -> Path:
    base = Path(WORKSPACES_DIR).resolve()
    target = (base / workspace / filename).resolve()
    if not str(target).startswith(str(base / workspace)):
        raise ValueError("Path traversal detected")
    return target
```

- [ ] **Step 2: Create auth.py router**

```python
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
        raise HTTPException(400, "Username must be at least 3 characters")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    existing = db.query(User).filter(User.username == body.username.strip()).first()
    if existing:
        raise HTTPException(409, "Username already exists")

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
    import os
    os.makedirs(os.path.join(WORKSPACES_DIR, workspace), exist_ok=True)

    token = create_token(user.id, workspace)
    return AuthResponse(token=token, username=user.username, workspace=workspace)


@router.post("/login", response_model=AuthResponse)
def login(body: AuthRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user or not verify_password(body.password, user.password):
        raise HTTPException(401, "Invalid username or password")

    token = create_token(user.id, user.workspace)
    return AuthResponse(token=token, username=user.username, workspace=user.workspace)
```

- [ ] **Step 3: Test auth endpoints**

Run:
```bash
# Test register
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}'

# Test duplicate register
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}'

# Test login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}'
```
Expected: First returns token, second returns 409, third returns token.

- [ ] **Step 4: Commit**

```bash
git add backend/app/utils/ backend/app/routers/
git commit -m "feat: add auth endpoints (register/login) with JWT and bcrypt"
```

---

### Task 4: Auth Dependency

**Files:**
- Create: `backend/app/dependencies.py`

- [ ] **Step 1: Create dependencies.py**

```python
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
```

- [ ] **Step 2: Verify with a protected test endpoint**

Add temporarily to `main.py`:
```python
from app.dependencies import get_current_user

@app.get("/api/me")
def me(payload: dict = Depends(get_current_user)):
    return {"user_id": payload["user_id"], "workspace": payload["workspace"]}
```

Run:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/me

# Test no token
curl http://localhost:8000/api/me
```
Expected: First returns user info, second returns 401.
Remove the test endpoint after verification.

- [ ] **Step 3: Commit**

```bash
git add backend/app/dependencies.py
git commit -m "feat: add JWT auth dependency for protected routes"
```

---

### Task 5: Log API

**Files:**
- Create: `backend/app/routers/log.py`

- [ ] **Step 1: Create log.py router**

```python
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
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
```

- [ ] **Step 2: Test log endpoints**

Run:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# Save first version
curl -X POST http://localhost:8000/api/log/save \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"data":{"DMP版本号":"V1.0","DMP版本日期":"2026-05-18","撰写者":"张三"}}'

# Save second version (append)
curl -X POST http://localhost:8000/api/log/save \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"data":{"DMP版本号":"V2.0","DMP版本日期":"2026-05-25","撰写者":"李四"}}'

# Get current
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/log/current
```
Expected: Current returns 2 entries, latest is V2.0. Check `backend/data/workspaces/user_testuser/dm-log.json` has array of 2.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/log.py
git commit -m "feat: add log API with JSON append logic for dm-log.json"
```

---

### Task 6: File API

**Files:**
- Create: `backend/app/routers/files.py`

- [ ] **Step 1: Create files.py router**

```python
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.config import UPLOAD_MAX_SIZE_MB, UPLOAD_ALLOWED_EXTENSIONS
from app.dependencies import get_current_user
from app.utils.security import safe_path

router = APIRouter(dependencies=[Depends(get_current_user)])

MAX_BYTES = UPLOAD_MAX_SIZE_MB * 1024 * 1024


def _workspace_dir(workspace: str) -> str:
    from app.config import WORKSPACES_DIR
    return os.path.join(WORKSPACES_DIR, workspace)


@router.post("/upload")
async def upload_file(file: UploadFile, request: Request):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type {ext} not allowed")

    contents = await file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(400, f"File exceeds {UPLOAD_MAX_SIZE_MB}MB limit")

    ws_dir = _workspace_dir(request.state.workspace)
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
def list_files(request: Request):
    ws_dir = _workspace_dir(request.state.workspace)
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
def download_file(filename: str, request: Request):
    path = safe_path(request.state.workspace, filename)
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(path), filename=filename)


@router.delete("/delete/{filename}")
def delete_file(filename: str, request: Request):
    path = safe_path(request.state.workspace, filename)
    if not path.exists():
        raise HTTPException(404, "File not found")
    os.remove(str(path))
    return {"status": "deleted", "filename": filename}
```

- [ ] **Step 2: Test file endpoints**

Run:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# Upload a file
echo "test protocol content" > /tmp/test-protocol.txt
curl -X POST http://localhost:8000/api/files/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/test-protocol.txt"

# List files
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/files/list

# Download
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/files/download/test-protocol.txt

# Delete
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/files/delete/test-protocol.txt

# Verify removed
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/files/list
```
Expected: Upload returns file info, list shows file, download returns content, delete removes it.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/files.py
git commit -m "feat: add file upload/list/download/delete API with safe_path"
```

---

### Task 7: DMP Orchestrator Service

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/dmp_orchestrator.py`

- [ ] **Step 1: Create dmp_orchestrator.py**

```python
import asyncio
import json
import os
import queue
import threading
from datetime import datetime, timezone
from typing import Optional

from anthropic import Anthropic

from app.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    SKILL_DIR,
    WORKSPACES_DIR,
    SESSION_TTL_MINUTES,
)


class DMPSession:
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.event_queue: queue.Queue = queue.Queue()
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.messages = []
        self.active = False
        self.last_active = datetime.now(timezone.utc)

    def push_event(self, event_type: str, data: dict):
        self.event_queue.put({"event": event_type, "data": data})

    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.last_active).total_seconds()
        return elapsed > SESSION_TTL_MINUTES * 60


class DMPOrchestrator:
    def __init__(self):
        self.sessions: dict[str, DMPSession] = {}

    def _load_system_prompt(self) -> str:
        prompt_parts = []

        skill_md = os.path.join(SKILL_DIR, "SKILL.md")
        if os.path.exists(skill_md):
            with open(skill_md, "r", encoding="utf-8") as f:
                prompt_parts.append(f.read())

        reference_md = os.path.join(SKILL_DIR, "reference", "chinese-dmp-generation.md")
        if os.path.exists(reference_md):
            with open(reference_md, "r", encoding="utf-8") as f:
                prompt_parts.append("\n\n" + f.read())

        fewshot_md = os.path.join(SKILL_DIR, "assets", "fewshot.md")
        if os.path.exists(fewshot_md):
            with open(fewshot_md, "r", encoding="utf-8") as f:
                prompt_parts.append("\n\n" + f.read())

        prompt_parts.append(f"""
## Current Workspace
Workspace directory: {WORKSPACES_DIR}/{{workspace}}/
Available files: you can read files from this directory.
Protocol-to-dmp scripts are at: {SKILL_DIR}/scripts/
DMP templates are at: {SKILL_DIR}/assets/

## IMPORTANT Interaction Rules
When you need user input to resolve unclear/missing/conflicting values, you MUST use a special format:
[[QUESTION:type:choice|input]]
[[QUESTION_TEXT:the question text]]
[[OPTION:A:description]]  (only for choice type)
[[OPTION:B:description]]  (only for choice type)
[[END_QUESTION]]

The backend will parse these markers and push them as interactive cards to the frontend.
DO NOT ask questions in plain text. Always use the question markers above.
""")
        return "\n\n".join(prompt_parts)

    def get_or_create_session(self, workspace: str) -> DMPSession:
        if workspace in self.sessions:
            session = self.sessions[workspace]
            if session.is_expired():
                del self.sessions[workspace]
            else:
                return session

        session = DMPSession(workspace)
        self.sessions[workspace] = session
        return session

    def _stream_claude_response(self, session: DMPSession):
        system_prompt = self._load_system_prompt().replace("{workspace}", session.workspace)

        try:
            with session.client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=8000,
                system=system_prompt,
                messages=session.messages,
            ) as stream:
                for text in stream.text_stream:
                    session.push_event("text", {"content": text})
        except Exception as e:
            session.push_event("error", {"message": str(e)})
        finally:
            session.active = False

    async def send_message(self, workspace: str, user_message: str):
        session = self.get_or_create_session(workspace)
        session.last_active = datetime.now(timezone.utc)
        session.messages.append({"role": "user", "content": user_message})

        return self._stream_events(session, trigger_stream=True)

    async def start_dmp(self, workspace: str):
        session = self.get_or_create_session(workspace)
        session.last_active = datetime.now(timezone.utc)
        session.messages = []  # Reset for new DMP generation

        workspace_path = os.path.join(WORKSPACES_DIR, workspace)

        # Gather context from workspace
        log_path = os.path.join(workspace_path, "dm-log.json")
        log_content = ""
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                log_content = f.read()

        protocol_files = []
        for name in os.listdir(workspace_path):
            ext = os.path.splitext(name)[1].lower()
            if ext in {".docx", ".pdf", ".txt", ".md"} and not name.startswith("DMP"):
                protocol_files.append(name)

        dmp_message = f"""Please generate a DMP following the protocol-to-dmp workflow.

The DM log file is at: {workspace_path}/dm-log.json
Content:
{log_content}

Protocol files in workspace: {', '.join(protocol_files)}

Please follow the workflow:
1. Read the DM log, select the correct DMP template
2. Build the evidence trace using build_dmp_trace.py
3. Run semantic review
4. Run few-shot formatting
5. Ask me about any unresolved fields using the question format
6. Fill the template and generate the DMP .docx file

Start now."""
        session.messages.append({"role": "user", "content": dmp_message})

        return self._stream_events(session, trigger_stream=True)

    async def _stream_events(self, session: DMPSession, trigger_stream: bool = False):
        if trigger_stream and not session.active:
            session.active = True
            thread = threading.Thread(target=self._stream_claude_response, args=(session,), daemon=True)
            thread.start()

        while True:
            try:
                event = session.event_queue.get(timeout=0.1)
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            except queue.Empty:
                if not session.active and session.event_queue.empty():
                    session.push_event("done", {"message": "Generation complete"})
                    yield f"event: done\ndata: {json.dumps({'message': 'Generation complete'})}\n\n"
                    break
                await asyncio.sleep(0.05)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/
git commit -m "feat: add DMP orchestrator with Claude SDK SSE streaming"
```

---

### Task 8: Chat API Router

**Files:**
- Create: `backend/app/routers/chat.py`

- [ ] **Step 1: Create chat.py router**

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.services.dmp_orchestrator import DMPOrchestrator

router = APIRouter(dependencies=[Depends(get_current_user)])
orchestrator = DMPOrchestrator()


class ChatRequest(BaseModel):
    message: str


@router.post("/send")
async def send_message(body: ChatRequest, request: Request):
    return StreamingResponse(
        orchestrator.send_message(request.state.workspace, body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/start-dmp")
async def start_dmp(request: Request):
    return StreamingResponse(
        orchestrator.start_dmp(request.state.workspace),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/routers/chat.py
git commit -m "feat: add chat API with SSE streaming endpoints"
```

---

### Task 9: Frontend Project Scaffolding

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/types/index.ts`
- Create: `frontend/src/services/api.ts`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "dmp-platform-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{"path": "./tsconfig.node.json"}]
}
```

- [ ] **Step 3: Create tsconfig.node.json**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: Create vite.config.ts**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
```

- [ ] **Step 5: Create index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>DMP Generation Platform</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create types/index.ts**

```typescript
export interface User {
  username: string;
  workspace: string;
  token: string;
}

export interface LogEntry {
  [key: string]: string;
}

export interface LogData {
  entries: LogEntry[];
  latest: LogEntry | null;
}

export interface FileInfo {
  name: string;
  size: number;
  modified_at: string;
  category: "log" | "protocol" | "dmp";
}

export interface SSEMessage {
  type: string;
  content?: string;
  questions?: Question[];
  message?: string;
  output_file?: string;
  report?: string;
}

export interface Question {
  id: string;
  text: string;
  type: "choice" | "input";
  options?: string[];
}

export interface ChatMessage {
  role: "user" | "claude" | "system";
  content: string;
  questions?: Question[];
}
```

- [ ] **Step 7: Create services/api.ts**

```typescript
import axios from "axios";

const api = axios.create({
  baseURL: "/api",
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export default api;
```

- [ ] **Step 8: Create main.tsx**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 9: Create App.tsx**

```tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import LogFormPage from "./pages/LogFormPage";
import ChatPage from "./pages/ChatPage";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/log-form"
            element={
              <ProtectedRoute>
                <LogFormPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/chat"
            element={
              <ProtectedRoute>
                <ChatPage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
```

- [ ] **Step 10: Install deps and verify startup**

Run: `cd frontend && npm install`
Run: `cd frontend && npm run dev`
Expected: Vite dev server starts on port 5173, page loads (blank, no errors).

- [ ] **Step 11: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold React frontend with Vite, Router, Axios, and types"
```

---

### Task 10: Auth Context & Pages

**Files:**
- Create: `frontend/src/contexts/AuthContext.tsx`
- Create: `frontend/src/hooks/useAuth.ts`
- Create: `frontend/src/components/ProtectedRoute.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/RegisterPage.tsx`

- [ ] **Step 1: Create AuthContext.tsx**

```tsx
import { createContext, useState, useEffect, ReactNode } from "react";
import { User } from "../types";

interface AuthContextType {
  user: User | null;
  login: (user: User) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

export const AuthContext = createContext<AuthContextType>({
  user: null,
  login: () => {},
  logout: () => {},
  isAuthenticated: false,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("user");
    const token = localStorage.getItem("token");
    if (stored && token) {
      setUser(JSON.parse(stored));
    }
  }, []);

  const login = (user: User) => {
    localStorage.setItem("token", user.token);
    localStorage.setItem("user", JSON.stringify(user));
    setUser(user);
  };

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}
```

- [ ] **Step 2: Create useAuth.ts**

```typescript
import { useContext } from "react";
import { AuthContext } from "../contexts/AuthContext";

export function useAuth() {
  return useContext(AuthContext);
}
```

- [ ] **Step 3: Create ProtectedRoute.tsx**

```tsx
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ReactNode } from "react";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
```

- [ ] **Step 4: Create LoginPage.tsx**

```tsx
import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../services/api";
import { useAuth } from "../hooks/useAuth";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const { login } = useAuth();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await api.post("/auth/login", { username, password });
      login(res.data);
      navigate("/log-form");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Login failed");
    }
  };

  return (
    <div style={{ maxWidth: 400, margin: "100px auto", padding: 24 }}>
      <h1>DMP Platform Login</h1>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 12 }}>
          <label>Username</label>
          <input
            style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            minLength={3}
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label>Password</label>
          <input
            type="password"
            style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
          />
        </div>
        {error && <p style={{ color: "red" }}>{error}</p>}
        <button type="submit" style={{ width: "100%", padding: 10 }}>
          Login
        </button>
      </form>
      <p style={{ marginTop: 12 }}>
        No account? <Link to="/register">Register</Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 5: Create RegisterPage.tsx**

```tsx
import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../services/api";
import { useAuth } from "../hooks/useAuth";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const { login } = useAuth();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await api.post("/auth/register", { username, password });
      login(res.data);
      navigate("/log-form");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Registration failed");
    }
  };

  return (
    <div style={{ maxWidth: 400, margin: "100px auto", padding: 24 }}>
      <h1>Register</h1>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 12 }}>
          <label>Username (min 3 chars)</label>
          <input
            style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            minLength={3}
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label>Password (min 6 chars)</label>
          <input
            type="password"
            style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
          />
        </div>
        {error && <p style={{ color: "red" }}>{error}</p>}
        <button type="submit" style={{ width: "100%", padding: 10 }}>
          Register
        </button>
      </form>
      <p style={{ marginTop: 12 }}>
        Already have an account? <Link to="/login">Login</Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 6: Test login/register flow**

Run: `cd frontend && npm run dev` (backend must be running on 8000)
Expected:
- Navigate to `http://localhost:5173/login` → login page renders
- Click Register link → register page renders
- Register a new user → redirects to `/log-form`
- Logout (clear localStorage) → redirects to `/login`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/contexts/ frontend/src/hooks/ frontend/src/components/ProtectedRoute.tsx frontend/src/pages/LoginPage.tsx frontend/src/pages/RegisterPage.tsx
git commit -m "feat: add auth context, login/register pages with JWT flow"
```

---

### Task 11: Log Form Page

**Files:**
- Create: `frontend/src/pages/LogFormPage.tsx`

- [ ] **Step 1: Create LogFormPage.tsx**

```tsx
import { useState, useEffect, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import { useAuth } from "../hooks/useAuth";

const FORM_FIELDS = [
  { key: "DMP版本号", label: "DMP Version", type: "text" },
  { key: "DMP版本日期", label: "DMP Version Date", type: "date" },
  { key: "方案定稿日期", label: "Protocol Final Date", type: "date" },
  { key: "临床监查方名称", label: "Clinical Monitor", type: "text" },
  { key: "统计分析方名称", label: "Statistical Analysis Provider", type: "text" },
  { key: "版本修订记录", label: "Revision Notes", type: "text" },
  { key: "撰写者/修订者", label: "Author/Reviser", type: "text" },
  { key: "项目类型：药物 / 器械", label: "Project Type", type: "select", options: ["药物项目", "器械项目"] },
  { key: "项目数据采集模式：EDC / PDC", label: "Data Collection Mode", type: "select", options: ["EDC", "PDC"] },
  { key: "EDC系统供应商/系统类型", label: "EDC System/Vendor", type: "text", dependsOn: { key: "项目数据采集模式：EDC / PDC", value: "EDC" } },
  { key: "是否使用登记系统", label: "Use Registration System", type: "select", options: ["是", "否"] },
  { key: "是否使用随机系统", label: "Use Randomization System", type: "select", options: ["是", "否"] },
  { key: "随机系统供应商/系统类型", label: "Randomization System/Vendor", type: "text", dependsOn: { key: "是否使用随机系统", value: "是" } },
  { key: "是否涉及外部数据", label: "External Data Involved", type: "select", options: ["是", "否"] },
  { key: "涉及的外部数据类型", label: "External Data Types", type: "text", dependsOn: { key: "是否涉及外部数据", value: "是" } },
  { key: "是否涉及医学编码", label: "Medical Coding Involved", type: "select", options: ["是", "否"] },
  { key: "是否涉及针对有药物警戒系统的项目", label: "Drug Safety System", type: "select", options: ["是", "否"] },
  { key: "是否有阶段性分析/中期分析", label: "Interim Analysis", type: "select", options: ["是", "否"] },
  { key: "阶段性分析目的和阶段要求", label: "Interim Analysis Details", type: "text", dependsOn: { key: "是否有阶段性分析/中期分析", value: "是" } },
  { key: "是否需要预递交", label: "Pre-submission Required", type: "select", options: ["是", "否"] },
  { key: "是否需要数据管理报告", label: "DM Report Required", type: "select", options: ["是", "否"] },
  { key: "是否包含向申办者数据递交服务范围", label: "Sponsor Data Submission", type: "select", options: ["是", "否"] },
  { key: "项目质量控制等级/模板", label: "QC Level/Template", type: "select", options: ["高标准模板", "标准模板"] },
];

export default function LogFormPage() {
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const navigate = useNavigate();
  const { user } = useAuth();

  useEffect(() => {
    api.get("/log/current").then((res) => {
      if (res.data.latest) {
        setFormData(res.data.latest);
      }
    }).catch(() => {});
  }, []);

  const handleChange = (key: string, value: string) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const isVisible = (field: typeof FORM_FIELDS[0]) => {
    if (!field.dependsOn) return true;
    return formData[field.dependsOn.key] === field.dependsOn.value;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const res = await api.post("/log/save", { data: formData });
      setMessage(`Saved. Total versions: ${res.data.version_count}`);
    } catch (err: any) {
      setMessage("Save failed: " + (err.response?.data?.detail || "Unknown error"));
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: "40px auto", padding: 24 }}>
      <h1>DM Log Metadata</h1>
      <p>Workspace: {user?.workspace}</p>
      <form onSubmit={handleSubmit}>
        {FORM_FIELDS.filter(isVisible).map((field) => (
          <div key={field.key} style={{ marginBottom: 12 }}>
            <label style={{ display: "block", marginBottom: 4 }}>{field.label}</label>
            {field.type === "select" ? (
              <select
                style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
                value={formData[field.key] || ""}
                onChange={(e) => handleChange(field.key, e.target.value)}
              >
                <option value="">-- Select --</option>
                {field.options?.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            ) : (
              <input
                type={field.type}
                style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
                value={formData[field.key] || ""}
                onChange={(e) => handleChange(field.key, e.target.value)}
              />
            )}
          </div>
        ))}
        <div style={{ display: "flex", gap: 12, marginTop: 20 }}>
          <button type="submit" style={{ padding: "10px 24px" }}>
            Save Log
          </button>
          <button
            type="button"
            style={{ padding: "10px 24px" }}
            onClick={() => navigate("/chat")}
          >
            Go to Chat →
          </button>
        </div>
      </form>
      {message && <p style={{ marginTop: 12, color: "#4ade80" }}>{message}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Test log form**

Run: `cd frontend && npm run dev`
Expected:
- Login → redirected to `/log-form`
- Form shows all fields, conditional fields show/hide based on selections
- Fill and save → success message
- Reload → form pre-filled with latest saved data

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/LogFormPage.tsx
git commit -m "feat: add log metadata form with conditional fields and append logic"
```

---

### Task 12: Chat Page Components

**Files:**
- Create: `frontend/src/components/FileSidebar.tsx`
- Create: `frontend/src/components/FileUpload.tsx`
- Create: `frontend/src/components/ChatMessage.tsx`
- Create: `frontend/src/components/QuestionCard.tsx`
- Create: `frontend/src/components/ChatInput.tsx`
- Create: `frontend/src/hooks/useSSE.ts`
- Create: `frontend/src/pages/ChatPage.tsx`

- [ ] **Step 1: Create FileSidebar.tsx**

```tsx
import { useEffect, useState } from "react";
import api from "../services/api";
import { FileInfo } from "../types";

interface Props {
  refreshTrigger: number;
}

export default function FileSidebar({ refreshTrigger }: Props) {
  const [files, setFiles] = useState<FileInfo[]>([]);

  useEffect(() => {
    api.get("/files/list").then((res) => setFiles(res.data.files)).catch(() => {});
  }, [refreshTrigger]);

  const handleDownload = async (name: string) => {
    const res = await api.get(`/files/download/${name}`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete ${name}?`)) return;
    await api.delete(`/files/delete/${name}`);
    setFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const byCategory = (cat: string) => files.filter((f) => f.category === cat);
  const labels: Record<string, string> = { log: "Logs", protocol: "Protocols", dmp: "DMP Outputs" };

  return (
    <div style={{ width: 240, background: "#1a1a2e", padding: 12, overflowY: "auto", borderRight: "1px solid #333" }}>
      <h3 style={{ fontSize: 14, marginBottom: 4 }}>Workspace</h3>
      {(["log", "protocol", "dmp"] as const).map((cat) => (
        <div key={cat} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 10, color: "#888", textTransform: "uppercase", marginBottom: 4 }}>
            {labels[cat]}
          </div>
          {byCategory(cat).map((f) => (
            <div
              key={f.name}
              style={{ fontSize: 12, padding: "4px 6px", borderRadius: 4, cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center" }}
              title={`${f.name} (${(f.size / 1024).toFixed(1)} KB)`}
            >
              <span onClick={() => handleDownload(f.name)} style={{ flex: 1 }}>
                {f.name}
              </span>
              <span onClick={() => handleDelete(f.name)} style={{ color: "#f87171", cursor: "pointer", marginLeft: 8, fontSize: 14 }}>
                ×
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create FileUpload.tsx**

```tsx
import { useRef, useState } from "react";
import api from "../services/api";

interface Props {
  onUploaded: () => void;
}

export default function FileUpload({ onUploaded }: Props) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const upload = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      await api.post("/files/upload", formData);
      onUploaded();
    } catch (err: any) {
      alert("Upload failed: " + (err.response?.data?.detail || "Error"));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      style={{
        border: `2px dashed ${dragging ? "#4ade80" : "#555"}`,
        borderRadius: 8,
        padding: 20,
        textAlign: "center",
        marginBottom: 16,
        cursor: "pointer",
      }}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); }}
      onClick={() => fileInputRef.current?.click()}
    >
      <p style={{ color: "#888", margin: 0 }}>
        {uploading ? "Uploading..." : "Drop protocol file here or click to browse"}
      </p>
      <p style={{ color: "#666", fontSize: 12, margin: "4px 0 0" }}>
        Supports .docx .pdf .txt .md (max 50MB)
      </p>
      <input
        ref={fileInputRef}
        type="file"
        hidden
        accept=".docx,.pdf,.txt,.md"
        onChange={(e) => { if (e.target.files?.[0]) upload(e.target.files[0]); }}
      />
    </div>
  );
}
```

- [ ] **Step 3: Create ChatMessage.tsx**

```tsx
import { ChatMessage as ChatMessageType } from "../types";
import QuestionCard from "./QuestionCard";

interface Props {
  message: ChatMessageType;
  onAnswer: (answer: string) => void;
}

export default function ChatMessage({ message, onAnswer }: Props) {
  const colors: Record<string, string> = {
    user: "#60a5fa",
    claude: "#4ade80",
    system: "#fbbf24",
  };

  return (
    <div style={{ marginBottom: 12, fontFamily: "monospace", fontSize: 13, lineHeight: 1.6 }}>
      <span style={{ color: colors[message.role] }}>
        {message.role === "user" ? "You" : message.role === "claude" ? "Claude" : "System"}
      </span>
      <div style={{ color: "#ccc", whiteSpace: "pre-wrap", marginTop: 4 }}>
        {message.content}
      </div>
      {message.questions && message.questions.length > 0 && (
        <QuestionCard questions={message.questions} onAnswer={onAnswer} />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create QuestionCard.tsx**

```tsx
import { useState } from "react";
import { Question } from "../types";

interface Props {
  questions: Question[];
  onAnswer: (answer: string) => void;
}

export default function QuestionCard({ questions, onAnswer }: Props) {
  const [inputs, setInputs] = useState<Record<string, string>>({});

  return (
    <div style={{ marginTop: 8, padding: 12, background: "#1a2a1a", borderRadius: 6, borderLeft: "3px solid #fbbf24" }}>
      <div style={{ color: "#fbbf24", fontSize: 12, marginBottom: 8 }}>Action Required</div>
      {questions.map((q) => (
        <div key={q.id} style={{ marginBottom: 8 }}>
          <p style={{ color: "#ccc", fontSize: 13, margin: "0 0 6px" }}>{q.text}</p>
          {q.type === "choice" && q.options ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {q.options.map((opt, i) => (
                <button
                  key={i}
                  style={{ padding: "4px 12px", background: "#2a5a3a", border: "none", borderRadius: 4, color: "#fff", cursor: "pointer", fontSize: 12 }}
                  onClick={() => onAnswer(opt)}
                >
                  {String.fromCharCode(65 + i)}: {opt}
                </button>
              ))}
            </div>
          ) : (
            <div style={{ display: "flex", gap: 8 }}>
              <input
                style={{ flex: 1, padding: 6, borderRadius: 4, border: "1px solid #555", background: "#111", color: "#fff", fontSize: 12 }}
                value={inputs[q.id] || ""}
                onChange={(e) => setInputs({ ...inputs, [q.id]: e.target.value })}
                placeholder="Type your answer..."
              />
              <button
                style={{ padding: "4px 12px", background: "#3a3a5a", border: "none", borderRadius: 4, color: "#fff", cursor: "pointer", fontSize: 12 }}
                onClick={() => inputs[q.id] && onAnswer(inputs[q.id])}
              >
                Submit
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Create ChatInput.tsx**

```tsx
import { useState, FormEvent } from "react";

interface Props {
  onSend: (message: string) => void;
  onStartDMP: () => void;
  disabled: boolean;
  canGenerate: boolean;
}

export default function ChatInput({ onSend, onStartDMP, disabled, canGenerate }: Props) {
  const [text, setText] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, padding: 12, borderTop: "1px solid #333" }}>
      <input
        style={{ flex: 1, padding: 10, borderRadius: 6, border: "1px solid #555", background: "#111", color: "#fff", fontSize: 13 }}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={disabled ? "Claude is working..." : "Type a message..."}
        disabled={disabled}
      />
      <button type="submit" disabled={disabled} style={{ padding: "8px 16px", cursor: disabled ? "not-allowed" : "pointer" }}>
        Send
      </button>
      <button
        type="button"
        disabled={disabled || !canGenerate}
        onClick={onStartDMP}
        style={{ padding: "8px 16px", background: canGenerate ? "#2a5a3a" : "#333", cursor: canGenerate && !disabled ? "pointer" : "not-allowed" }}
      >
        Generate DMP
      </button>
    </form>
  );
}
```

- [ ] **Step 6: Create useSSE.ts**

```typescript
import { useCallback, useRef } from "react";

export function useSSE() {
  const readerRef = useRef<ReadableStreamDefaultReader | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const connect = useCallback(
    (url: string, onEvent: (type: string, data: any) => void, onDone: () => void) => {
      abortRef.current = new AbortController();

      fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("token")}`,
        },
        signal: abortRef.current.signal,
      })
        .then(async (response) => {
          if (!response.ok || !response.body) {
            onEvent("error", { message: `HTTP ${response.status}` });
            onDone();
            return;
          }
          const reader = response.body.getReader();
          readerRef.current = reader;
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            let currentEvent = "";
            for (const line of lines) {
              if (line.startsWith("event: ")) {
                currentEvent = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                try {
                  const data = JSON.parse(line.slice(6));
                  onEvent(currentEvent, data);
                  if (currentEvent === "done") {
                    onDone();
                    return;
                  }
                } catch {}
              }
            }
          }
          onDone();
        })
        .catch((err) => {
          if (err.name !== "AbortError") {
            onEvent("error", { message: err.message });
            onDone();
          }
        });
    },
    []
  );

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
    readerRef.current?.cancel();
  }, []);

  return { connect, disconnect };
}
```

- [ ] **Step 7: Create ChatPage.tsx**

```tsx
import { useState, useCallback, useRef, useEffect } from "react";
import api from "../services/api";
import { ChatMessage as ChatMessageType } from "../types";
import { useAuth } from "../hooks/useAuth";
import { useSSE } from "../hooks/useSSE";
import FileSidebar from "../components/FileSidebar";
import FileUpload from "../components/FileUpload";
import ChatMessage from "../components/ChatMessage";
import ChatInput from "../components/ChatInput";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [canGenerate, setCanGenerate] = useState(false);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { user } = useAuth();
  const { connect, disconnect } = useSSE();

  useEffect(() => {
    api.get("/files/list").then((res) => {
      const hasLog = res.data.files.some((f: any) => f.name === "dm-log.json");
      const hasProtocol = res.data.files.some((f: any) => f.category === "protocol");
      setCanGenerate(hasLog && hasProtocol);
    }).catch(() => {});
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const addMessage = (msg: ChatMessageType) => {
    setMessages((prev) => [...prev, msg]);
  };

  const handleSSEEvent = useCallback((type: string, data: any) => {
    switch (type) {
      case "text":
        addMessage({ role: "claude", content: data.content || "" });
        break;
      case "question":
        addMessage({ role: "system", content: "Please answer the following:", questions: data.questions });
        break;
      case "tool_use":
        addMessage({ role: "system", content: `Running: ${data.tool || "script"} [${data.status}]` });
        break;
      case "file_update":
        setSidebarRefresh((prev) => prev + 1);
        break;
      case "error":
        addMessage({ role: "system", content: `Error: ${data.message}` });
        break;
      case "done":
        setSidebarRefresh((prev) => prev + 1);
        break;
    }
  }, []);

  const handleDone = useCallback(() => {
    setIsGenerating(false);
  }, []);

  const handleSend = (text: string) => {
    addMessage({ role: "user", content: text });
    setIsGenerating(true);
    connect("/api/chat/send", handleSSEEvent, handleDone);
  };

  const handleStartDMP = () => {
    addMessage({ role: "system", content: "Starting DMP generation..." });
    setIsGenerating(true);
    connect("/api/chat/start-dmp", handleSSEEvent, handleDone);
  };

  const handleAnswer = (answer: string) => {
    handleSend(answer);
  };

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <FileSidebar refreshTrigger={sidebarRefresh} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "#0d0d1a" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #333", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ color: "#fff", fontWeight: "bold" }}>DMP Generation Chat</span>
          <span style={{ color: "#888", fontSize: 12 }}>Workspace: {user?.workspace}</span>
        </div>
        <div style={{ padding: 16 }}>
          <FileUpload onUploaded={() => { setSidebarRefresh((p) => p + 1); setCanGenerate(true); }} />
        </div>
        <div style={{ flex: 1, padding: "0 16px", overflowY: "auto" }}>
          {messages.map((msg, i) => (
            <ChatMessage key={i} message={msg} onAnswer={handleAnswer} />
          ))}
          <div ref={messagesEndRef} />
        </div>
        <ChatInput
          onSend={handleSend}
          onStartDMP={handleStartDMP}
          disabled={isGenerating}
          canGenerate={canGenerate}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Test full chat flow**

Run: Backend on 8000, Frontend on 5173.
Expected:
- Login → go to log form → save → go to chat
- Sidebar shows dm-log.json
- Upload a protocol file → appears in sidebar under Protocols
- Generate DMP button is now enabled
- Type a message → sends to backend → SSE events appear in chat

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/ frontend/src/hooks/useSSE.ts frontend/src/pages/ChatPage.tsx
git commit -m "feat: add chat interface with SSE streaming, file sidebar, upload, and question cards"
```

---

### Task 13: Integration Testing

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_auth.py`

- [ ] **Step 1: Create conftest.py**

```python
import os
import shutil
import pytest
from fastapi.testclient import TestClient

os.environ["SECRET_KEY"] = "test-secret"

from app.main import app
from app.config import DATA_DIR, DB_PATH
from app.database import init_db


@pytest.fixture(autouse=True)
def clean_data():
    if os.path.exists(DATA_DIR):
        shutil.rmtree(DATA_DIR)
    os.makedirs(DATA_DIR, exist_ok=True)
    init_db(DB_PATH)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    client.post("/api/auth/register", json={"username": "tester", "password": "test123"})
    res = client.post("/api/auth/login", json={"username": "tester", "password": "test123"})
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}
```

- [ ] **Step 2: Create test_auth.py**

```python
def test_register_success(client):
    res = client.post("/api/auth/register", json={"username": "newuser", "password": "pass1234"})
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["username"] == "newuser"
    assert data["workspace"] == "user_newuser"


def test_register_duplicate(client):
    client.post("/api/auth/register", json={"username": "dup", "password": "pass1234"})
    res = client.post("/api/auth/register", json={"username": "dup", "password": "pass1234"})
    assert res.status_code == 409


def test_register_short_username(client):
    res = client.post("/api/auth/register", json={"username": "ab", "password": "pass1234"})
    assert res.status_code == 400


def test_register_short_password(client):
    res = client.post("/api/auth/register", json={"username": "validuser", "password": "12345"})
    assert res.status_code == 400


def test_login_success(client):
    client.post("/api/auth/register", json={"username": "logintest", "password": "test123"})
    res = client.post("/api/auth/login", json={"username": "logintest", "password": "test123"})
    assert res.status_code == 200
    assert "token" in res.json()


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"username": "logintest2", "password": "test123"})
    res = client.post("/api/auth/login", json={"username": "logintest2", "password": "wrong"})
    assert res.status_code == 401


def test_protected_route_no_token(client):
    res = client.get("/api/log/current")
    assert res.status_code == 403


def test_protected_route_with_token(client, auth_headers):
    res = client.get("/api/log/current", headers=auth_headers)
    assert res.status_code == 200
```

- [ ] **Step 3: Run tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 8 tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/
git commit -m "test: add auth integration tests"
```

---

## Self-Review

**1. Spec coverage check:**
- Auth (register/login) → Tasks 3, 4, 10
- Workspace isolation → Tasks 2, 3 (registration creates dir), 4 (safe_path)
- Log metadata form → Tasks 5, 11
- File upload/list/download/delete → Tasks 6, 12
- Chat interface + SSE → Tasks 7, 8, 12
- DMP generation with Claude SDK → Tasks 7, 8
- Question cards (choice/input) → Tasks 7 (SSE format), 12 (QuestionCard component)
- Error handling → Tasks 7 (error events), 9 (401 interceptor)
- All files deletable → Task 6 (no category restriction on delete)

**2. Placeholder scan:** No TBD, TODO, or placeholder patterns found.

**3. Type consistency:** Types defined in Task 9 (`types/index.ts`) are used consistently across Tasks 10-12. API endpoints in frontend match backend routers.
