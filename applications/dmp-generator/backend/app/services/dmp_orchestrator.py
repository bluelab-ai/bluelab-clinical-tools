import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone

from anthropic import Anthropic

from app.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    SKILL_DIR,
    WORKSPACES_DIR,
    SESSION_TTL_MINUTES,
)

SKILL_SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
SKILL_ASSETS_DIR = os.path.join(SKILL_DIR, "assets")

TOOLS = [
    {
        "name": "read_file",
        "description": "Read contents of a file from the user workspace or skill directory",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file in the user workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to write the file"},
                "content": {"type": "string", "description": "Content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "run_shell",
        "description": "Run a shell command for executing protocol-to-dmp scripts",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory for the command"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "list_files",
        "description": "List files in a directory within the user workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the directory"}
            },
            "required": ["path"]
        }
    },
]


def _execute_tool(tool_name: str, tool_input: dict, workspace: str) -> dict:
    ws_path = os.path.join(WORKSPACES_DIR, workspace)

    if tool_name == "read_file":
        path = tool_input.get("path", "")
        if not any(path.startswith(p) for p in [ws_path, SKILL_DIR, SKILL_SCRIPTS_DIR, SKILL_ASSETS_DIR]):
            return {"error": f"Access denied: {path}"}
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"content": content[:50000]}
        except Exception as e:
            return {"error": str(e)}

    elif tool_name == "write_file":
        path = tool_input.get("path", "")
        if not path.startswith(ws_path):
            return {"error": f"Write only allowed in workspace: {ws_path}"}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(tool_input.get("content", ""))
            return {"success": True, "path": path}
        except Exception as e:
            return {"error": str(e)}

    elif tool_name == "run_shell":
        command = tool_input.get("command", "")
        cwd = tool_input.get("cwd", ws_path)
        if not any(cwd.startswith(p) for p in [ws_path, SKILL_DIR, SKILL_SCRIPTS_DIR]):
            cwd = ws_path
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "WORKSPACE": ws_path, "SKILL_DIR": SKILL_DIR}
            )
            return {
                "stdout": result.stdout[:10000],
                "stderr": result.stderr[:5000],
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out after 120s"}
        except Exception as e:
            return {"error": str(e)}

    elif tool_name == "list_files":
        path = tool_input.get("path", ws_path)
        if not any(path.startswith(p) for p in [ws_path, SKILL_DIR]):
            return {"error": f"Access denied: {path}"}
        try:
            items = []
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                items.append({
                    "name": name,
                    "type": "directory" if os.path.isdir(full) else "file",
                    "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                })
            return {"items": items}
        except Exception as e:
            return {"error": str(e)}

    return {"error": f"Unknown tool: {tool_name}"}


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

    def _load_system_prompt(self, workspace: str) -> str:
        prompt_parts = []
        ws_path = os.path.join(WORKSPACES_DIR, workspace)

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
## Your Workspace
- Workspace directory: {ws_path}
- Skill scripts: {SKILL_SCRIPTS_DIR}
- Skill assets (templates): {SKILL_ASSETS_DIR}
- Available scripts: build_dmp_trace.py, semantic_review.py, fewshot_format.py, apply_trace_to_template.py
- DMP templates: DMP-随机系统.docx, DMP-登记系统.docx, DMP-无随机无登记.docx
- Checklist: DMP非固定内容清单.xlsx

## Available Tools
You have: read_file, write_file, run_shell, list_files.

## Interaction Rules
When you need user input, you MUST use this format:
[[QUESTION:type:choice|input]]
[[QUESTION_TEXT:question text]]
[[OPTION:A:option]]
[[OPTION:B:option]]
[[END_QUESTION]]

DO NOT ask questions in plain text. Always use the markers above.
DO read workspace files and run scripts. DO NOT guess values.
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
        system_prompt = self._load_system_prompt(session.workspace)
        api_messages = list(session.messages)
        session.messages = []

        try:
            round_count = 0
            while round_count < 15:
                round_count += 1
                response_text = ""
                tool_use_blocks = []

                with session.client.messages.stream(
                    model=CLAUDE_MODEL,
                    max_tokens=8000,
                    system=system_prompt,
                    messages=api_messages,
                    tools=TOOLS,
                ) as stream:
                    for text_delta in stream.text_stream:
                        if text_delta:
                            response_text += text_delta
                            session.push_event("text", {"content": text_delta})

                # Get final message to check for tool use
                final_msg = stream.get_final_message()
                api_messages.append({"role": "assistant", "content": final_msg.content})

                # Collect tool_use blocks
                tool_blocks = []
                for block in final_msg.content:
                    if hasattr(block, 'type') and block.type == "tool_use":
                        tool_blocks.append(block)

                if not tool_blocks:
                    break

                # Execute tools
                tool_results = []
                for block in tool_blocks:
                    session.push_event("tool_use", {
                        "tool": block.name,
                        "arguments": block.input,
                        "status": "running"
                    })
                    result = _execute_tool(block.name, block.input, session.workspace)
                    session.push_event("tool_use", {
                        "tool": block.name,
                        "arguments": block.input,
                        "status": "done" if "error" not in result else "error"
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False)
                    })

                api_messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            session.push_event("error", {"message": str(e)})
        finally:
            session.active = False

    def send_message(self, workspace: str, user_message: str):
        session = self.get_or_create_session(workspace)
        session.last_active = datetime.now(timezone.utc)
        session.messages.append({"role": "user", "content": user_message})
        return self._stream_events(session, trigger_stream=True)

    def start_dmp(self, workspace: str):
        session = self.get_or_create_session(workspace)
        session.last_active = datetime.now(timezone.utc)
        session.messages = []

        workspace_path = os.path.join(WORKSPACES_DIR, workspace)

        files_list = ""
        if os.path.exists(workspace_path):
            for name in sorted(os.listdir(workspace_path)):
                fpath = os.path.join(workspace_path, name)
                if os.path.isfile(fpath):
                    files_list += f"  - {name} ({os.path.getsize(fpath)} bytes)\n"

        dmp_message = f"""请按照 protocol-to-dmp 工作流帮我生成 DMP 数据管理计划。

工作目录: {workspace_path}
工作目录文件:
{files_list}
脚本目录: {SKILL_SCRIPTS_DIR}
模板目录: {SKILL_ASSETS_DIR}

流程:
1. 先用 read_file 读取 dm-log.json 了解项目配置
2. 用 read_file 读取方案文档了解试验内容
3. 根据 是否使用随机系统/是否使用登记系统 选择 DMP 模板
4. 用 run_shell 执行: python {SKILL_SCRIPTS_DIR}/build_dmp_trace.py --protocol <方案文件路径> --dm-log {workspace_path}/dm-log.json --template-dir {SKILL_ASSETS_DIR} --checklist {SKILL_ASSETS_DIR}/DMP非固定内容清单.xlsx --out {workspace_path}/dmp_trace.json --questions {workspace_path}/dmp_questions.md
5. 如果 dmp_questions.md 有未解决的字段，用 [[QUESTION:...]] 格式询问我
6. 确认所有值之后用 run_shell 执行: python {SKILL_SCRIPTS_DIR}/apply_trace_to_template.py --trace {workspace_path}/dmp_trace.json --out {workspace_path}/DMP-初稿.docx --report {workspace_path}/DMP生成报告.md
7. 完成后告知 DMP 已生成在哪个路径

现在开始。"""

        session.messages.append({"role": "user", "content": dmp_message})
        return self._stream_events(session, trigger_stream=True)

    def _stream_events(self, session: DMPSession, trigger_stream: bool = False):
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
                    yield f"event: done\ndata: {json.dumps({'message': 'OK'})}\n\n"
                    break
                time.sleep(0.05)
