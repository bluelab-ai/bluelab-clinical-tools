# DMP Generation Platform Design Spec

## Overview

A web platform for clinical trial Data Management Plan (DMP) generation. Users register, fill in DM log metadata, upload protocol documents, and interact with Claude (via Claude SDK + protocol-to-dmp skill) through a chat interface to generate DMP Word documents.

## Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | Python (FastAPI) |
| Frontend | React |
| Database | SQLite |
| AI | Claude SDK + protocol-to-dmp skill |
| Auth | JWT (bcrypt password hashing) |
| Real-time | SSE (Server-Sent Events) |
| DMP Output | Word .docx |

## User Flow

```
Register/Login → Log Metadata Form → Protocol Upload → Chat Interface (DMP Generation) → Download DMP
```

## Architecture

Three-layer architecture:

```
React Frontend ←→ FastAPI Backend ←→ Claude SDK + protocol-to-dmp scripts
                                       ↓
                                  File System (user workspaces)
```

### Frontend Pages

1. **Register/Login** — username + password, JWT stored in localStorage
2. **Log Metadata Form** — key-value form for DMP metadata fields
3. **Protocol Upload** — drag-and-drop file upload area
4. **Chat Interface** — split layout: file sidebar (left) + chat (right)

### Backend API Modules

- **Auth API** — `/api/auth/register`, `/api/auth/login`
- **Log API** — `/api/log/current`, `/api/log/save`
- **File API** — `/api/files/upload`, `/api/files/list`, `/api/files/download/{name}`, `/api/files/delete/{name}`
- **Chat API** — `/api/chat/send`, `/api/chat/start-dmp`

### Core Services

- **UserManager** — SQLite user CRUD, bcrypt password handling
- **WorkspaceManager** — per-user directory creation and file isolation
- **DMPOrchestrator** — Claude SDK session management, SSE streaming

## Authentication & Workspace Isolation

### User Model (SQLite)

```sql
CREATE TABLE users (
    id         INTEGER PRIMARY KEY,
    username   TEXT UNIQUE NOT NULL,
    password   TEXT NOT NULL,           -- bcrypt hash
    workspace  TEXT UNIQUE NOT NULL,    -- "user_alice"
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Registration Flow

1. Validate username uniqueness
2. bcrypt hash password
3. Insert into users table
4. Create `data/workspaces/{username}/` directory
5. Return JWT token (contains `user_id` + `workspace`)

### Login Flow

1. Query users table by username
2. bcrypt verify password
3. Return JWT token

### Request Authentication

- Every request: `Authorization: Bearer <token>`
- FastAPI middleware decodes JWT → injects `user_id` + `workspace` into `request.state`
- All file operations constrained to `data/workspaces/{workspace}/`
- `safe_path()` function validates all paths against workspace root to prevent path traversal

### Security

- bcrypt for password storage
- Path traversal prevention via `safe_path()` resolution check
- File upload: extension whitelist (`.docx .pdf .txt .md`), max 50MB, magic number validation
- SQL injection prevention: SQLAlchemy ORM parameterized queries
- CORS: restrict to frontend origin in production

## Log Metadata Form & JSON Management

### Form Fields

Derived from protocol-to-dmp skill's `DMP非固定内容清单.xlsx`. Fields are served from backend configuration (not hardcoded in frontend) so checklist updates auto-propagate.

Three field categories:
- **Text inputs**: version number, dates, names, revision notes
- **Select/dropdown**: project type (drug/device), EDC/PDC mode, boolean flags (has randomization, has registration, has external data, etc.)
- **Conditional fields**: shown based on parent selection (e.g., EDC vendor only shown when EDC mode selected)

### New vs Append Logic

- `GET /api/log/current` — returns latest entry from `dm-log.json` (for form pre-fill)
- `POST /api/log/save` — if `dm-log.json` exists, append new entry to array; otherwise create new file with `[{entry}]`
- Multiple versions = multiple array items in one JSON file

### JSON Structure

```json
[
    {
        "DMP版本号": "V1.0",
        "DMP版本日期": "2026-05-18",
        "方案定稿日期": "2026-04-30",
        "临床监查方名称": "泰格医药科技有限公司",
        ...
    }
]
```

## File Upload & Management

### Upload Flow

- Drag-and-drop or click-to-select
- Extension whitelist: `.docx .pdf .txt .md`
- Max file size: 50MB
- Same-name overwrite: old file renamed to `.bak`
- Saved to user workspace directory

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/files/upload` | Upload file to workspace |
| GET | `/api/files/list` | List workspace files (grouped: logs, protocols, DMPs) |
| GET | `/api/files/download/{name}` | Download file |
| DELETE | `/api/files/delete/{name}` | Delete file |

All files are deletable by the user.

## Chat Interface & Claude SDK Integration

### Page Layout

- **Left sidebar**: file browser grouped by category (logs, protocols, DMP outputs)
- **Right panel**: chat message stream + input area
- **Generate DMP button**: in input area, disabled until log + protocol exist

### SSE Event Types

| Event | Purpose | Data |
|-------|---------|------|
| `text` | Claude streaming output | text delta |
| `question` | Claude needs user input | `{questions: [{id, text, type: "choice"|"input", options?}]}` |
| `tool_use` | Claude executing scripts | `{tool, arguments, status: "running"|"done"|"error"}` |
| `file_update` | Workspace file changes | `{filename, action: "created"|"modified"}` |
| `error` | Error occurred | error message |
| `done` | Generation complete | `{output_file, report}` |

### Interaction Model

- Questions appear as interactive cards within the chat stream
- `choice` type: render as clickable option buttons (A/B/C)
- `input` type: render as inline text input
- User clicks option or types answer → auto-sends to backend → Claude continues

### Chat API

- `POST /api/chat/send` — send user message, receive SSE stream
- `POST /api/chat/start-dmp` — trigger DMP generation, receive SSE stream

### Backend Claude SDK Session

- Backend holds one Claude SDK session per user
- System prompt = SKILL.md + DMP非固定内容清单 + chinese-dmp-generation.md + fewshot.md
- Claude SDK has access to user workspace files (read) and protocol-to-dmp scripts (execute)
- Claude SDK autonomously follows skill workflow
- Backend role: inject context, stream output, bridge questions between Claude and user

## DMP Generation Pipeline

Claude SDK autonomously executes the protocol-to-dmp skill workflow:

1. **Context assembly** — backend loads SKILL.md + checklist + reference into system prompt
2. **Template selection** — Claude reads dm-log.json, selects correct DMP template (随机/登记/无)
3. **Evidence trace** — Claude runs `build_dmp_trace.py` via tool_use
4. **Semantic review** — Claude reviews high-risk fields (sample size, endpoints, study design)
5. **Few-shot formatting** — Claude formats values against few-shot examples
6. **User Q&A** — unresolved fields pushed as SSE `question` events, user answers feed back
7. **Template fill** — Claude runs `apply_trace_to_template.py` via tool_use
8. **QA + completion** — Claude checks output, emits `done` event with file download info

## Error Handling

| Scenario | Strategy |
|----------|----------|
| Claude SDK failure/timeout | SSE `error` event, prompt retry; session context preserved |
| User closes page during generation | Session retained for N minutes, reconnection resumes |
| Missing required files | Generate DMP button disabled, chat shows prompt |
| Protocol file parse failure | SSE `error` event, prompt user to check file |
| Disk full | File write failure → SSE `error` event |
| Duplicate generation click | Backend checks for active session, rejects with message |
| JWT expiry | Frontend intercepts 401, shows re-login prompt; 24h token lifetime |
| Concurrent multi-user | Per-user sessions + isolated workspaces, no conflict |

## Dependencies

- **protocol-to-dmp skill** (existing at `.claude/skills/protocol-to-dmp/`):
  - `SKILL.md` — skill definition and workflow
  - `assets/DMP-随机系统.docx`, `assets/DMP-登记系统.docx`, `assets/DMP-无随机无登记.docx` — DMP templates
  - `assets/DMP非固定内容清单.xlsx` — non-fixed content checklist
  - `assets/fewshot.md` — few-shot formatting examples
  - `scripts/build_dmp_trace.py` — evidence trace builder
  - `scripts/semantic_review.py` — semantic review helper
  - `scripts/fewshot_format.py` — few-shot format helper
  - `scripts/apply_trace_to_template.py` — template fill script
  - `reference/chinese-dmp-generation.md` — detailed reference rules
- **Python packages**: `python-docx`, `openpyxl` (required by skill scripts)
- **Claude SDK**: Anthropic Python SDK for Claude API access
