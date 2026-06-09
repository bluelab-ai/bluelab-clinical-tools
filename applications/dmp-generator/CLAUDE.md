# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Backend
cd backend
uvicorn app.main:app --port 8000 --reload          # Start dev server
python -m pytest tests/ -v                          # Run all tests
python -m pytest tests/test_auth.py::test_register_success -v  # Run single test

# Frontend
cd frontend
npm run dev                                         # Start Vite dev server (port 5173)
npx tsc --noEmit                                    # Type-check only
npm run build                                       # Production build
```

The frontend Vite config proxies `/api` to `http://localhost:8000`, so run both servers together for full-stack development.

## Two-directory setup

This project lives in two directories:

| Directory | Purpose |
|---|---|
| `Documents/方案/sdk测试/` | Development copy — edit files here |
| `项目/sdk测试/` | Runtime copy — backend runs from here |

After making changes in the dev directory, sync affected files to the runtime directory. The two share identical structure.

## Architecture

- **Monorepo**: `backend/` (FastAPI + SQLite), `frontend/` (React 18 + TypeScript + Vite)
- **Auth**: JWT (HS256, 24h expiry) via `backend/app/utils/security.py`. Passwords hashed with bcrypt. The `get_current_user` dependency (HTTPBearer) injects `user_id` and `workspace` into `request.state`.
- **Multi-tenant isolation**: Each user gets a workspace directory under `backend/data/workspaces/user_<username>/`. Within each workspace, projects are subdirectories (e.g., `default/`, `project-a/`). All file I/O is scoped to the workspace. `safe_path()` in `security.py` prevents path traversal.
- **Database**: Single SQLite file at `backend/data/app.db`, created on startup. Only one table: `users` (id, username, password, workspace, created_at).

### Backend structure

| Module | Purpose |
|---|---|
| `app/main.py` | FastAPI app, CORS, lifespan (creates dirs, inits DB), mounts routers, project list/delete endpoints |
| `app/config.py` | All constants: paths, JWT settings, upload limits (`.docx` only, 50MB), `SESSION_TTL_MINUTES` (30), `CLAUDE_MODEL` |
| `app/models.py` | SQLAlchemy User model |
| `app/database.py` | Engine/session factory, `init_db()` called once at startup |
| `app/dependencies.py` | `get_current_user` — JWT decode + inject into request.state; `get_project` — validates project name from URL path, blocks traversal chars |
| `app/utils/security.py` | bcrypt hash/verify, JWT create/decode, `safe_path()` |
| `app/routers/auth.py` | POST `/register`, POST `/login` |
| `app/routers/log.py` | GET `/current` (read dm-log.json latest entry), POST `/save` (append to JSON array, multi-version) |
| `app/routers/files.py` | POST `/upload`, GET `/list` (grouped by category), GET `/download/{name}`, DELETE `/delete/{name}` |
| `app/routers/chat.py` | POST `/send` (SSE stream), POST `/start-dmp` (SSE stream, always fresh session), POST `/clear` |
| `app/services/dmp_orchestrator.py` | Core: spawns Claude Code CLI as subprocess, converts stream-json to SSE |

### DMP Orchestrator (`dmp_orchestrator.py`) — critical internals

This is the most complex module. Key design decisions:

- **Claude Code CLI, not SDK**: The orchestrator spawns the `claude` binary via `subprocess.Popen` with `--output-format stream-json`. It does NOT use the Anthropic Python SDK. Claude CLI is given `--add-dir` for both the workspace and the skill directory, plus `--permission-mode bypassPermissions` to auto-execute scripts.
- **Sync generators**: `send_message()` and `start_dmp()` are regular `def` returning sync generators. `StreamingResponse` iterates them synchronously. `_run_claude()` yields SSE-formatted strings line-by-line from Claude's stdout.
- **SSE conversion**: `_convert_stream_json_to_sse()` parses each JSON line from Claude's stdout: `content_block_delta` with `text_delta` → SSE `text`; `content_block_start` with `tool_use` → SSE `tool_use`; `result` with error → SSE `error`; successful result → SSE `tool_use`.
- **Session management**: `_acquire_session()` atomically creates/retrieves session UUIDs keyed by workspace-project directory path. `start_dmp()` always calls `clear_session()` first to ensure a fresh generation. Sessions are held in-memory with a 30-minute TTL. Thread-safe via `threading.Lock`.
- **Budget**: `--max-budget-usd 15` limits Claude CLI cost per invocation.
- **Stderr draining**: A daemon thread drains stderr to prevent buffer blocking. On non-zero exit, the last 20 stderr lines are sent as an SSE error event.
- **QUESTION format**: The `start_dmp()` prompt requires Claude to use `[[QUESTION:type:choice]]` / `[[QUESTION:type:input]]` / `[[OPTION:X:...]]` / `[[END_QUESTION]]` markers. The frontend `ChatMessage` parses these via regex and renders `QuestionCard` components.

### Frontend structure

| File | Purpose |
|---|---|
| `src/App.tsx` | Router: `/login`, `/register`, `/log-form`, `/chat`, `/help` (protected). Wraps in `AuthProvider` + `ProjectProvider`. |
| `src/pages/HelpPage.tsx` | Step-by-step usage guide + FAQ, accessible from ChatPage and LogFormPage header help buttons |
| `src/contexts/AuthContext.tsx` | Auth state, login/logout, localStorage persistence, listens for `auth:logout` event |
| `src/contexts/ProjectContext.tsx` | Current project name state, syncs to localStorage and API service |
| `src/services/api.ts` | Axios instance: JWT interceptor, project path prefix (`/{project}/...`), 401 → logout redirect |
| `src/hooks/useSSE.ts` | SSE client: POST with fetch, reads ReadableStream, parses `event:`/`data:` lines, AbortController cancel |
| `src/pages/LoginPage.tsx` | Login form, shows expired-session message from sessionStorage |
| `src/pages/RegisterPage.tsx` | Registration form (username ≥3, password ≥6) |
| `src/pages/LogFormPage.tsx` | 34-field DM log form with conditional visibility (`dependsOn`), project dropdown + create + delete, duplicate-save detection |
| `src/pages/ChatPage.tsx` | Main chat: SSE event dispatch (`text`/`question`/`tool_use`/`error`/`done`/`file_update`), message merging, file sidebar, upload, project selector |
| `src/components/ChatMessage.tsx` | Renders messages with `ReactMarkdown` + `remarkGfm`, parses `[[QUESTION:...]]` blocks from Claude text, renders `QuestionCard` |
| `src/components/QuestionCard.tsx` | Interactive choice buttons (A/B/C) or text input + Submit |
| `src/components/ChatInput.tsx` | "Generate DMP" button only — disabled until `dm-log.json` + protocol file both exist |
| `src/components/FileSidebar.tsx` | File list grouped by category (Logs/Protocols/DMP Outputs), download/delete |
| `src/components/FileUpload.tsx` | Drag-and-drop upload, `.docx` only, max 50MB |

### Message merging in ChatPage

`addMessage()` merges consecutive same-role text messages (no questions, never system role) by appending content. This handles the small text deltas from Claude's streaming output.

### protocol-to-dmp skill

Located at `.claude/skills/protocol-to-dmp/`. Contains:
- `SKILL.md` — master workflow definition (Steps 0-9)
- `scripts/` — key scripts:
  - `build_dmp_trace.py` — parse protocol + DM log → evidence trace with confidence scoring (`compute_confidence()`). Extracts ~49 fields from checklist, with `protocol_literal` (92%), `dm_lookup` (92%), `protocol_regex` (72%), and `filename_fallback` (45%) confidence tiers. `normalize_version()` standardizes version numbers to `Vx.x` format.
  - `review_trace.py` — **combined** semantic review + few-shot format in a single prepare→review→apply cycle. Replaces the separate two-pass workflow.
  - `semantic_review.py` — standalone semantic review (prepare/apply modes), kept for single-pass use cases.
  - `fewshot_format.py` — standalone few-shot formatting (prepare/apply modes).
  - `apply_trace_to_template.py` — fill confirmed values into Word template.
  - `update_dm_log.py` — update latest DM log entry after user confirmation.
- `assets/` — 3 DMP Word templates (随机系统/登记系统/无随机无登记), Excel checklist, `fewshot.md`
- `reference/chinese-dmp-generation.md` — authoritative 14-section DMP generation rulebook

The `start_dmp()` prompt embeds the full workflow inline. The skill directory is mounted via `--add-dir` so Claude CLI can read assets and execute scripts.
