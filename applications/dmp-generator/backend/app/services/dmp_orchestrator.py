import json
import logging
import os
import re
import subprocess
import threading
import time as time_module
import uuid as uuid_lib

from app.config import (
    WORKSPACES_DIR, SKILL_DIR, CLAUDE_MODEL,
    CLAUDE_MAX_BUDGET_USD, CLAUDE_PROCESS_TIMEOUT_MINUTES,
    CLAUDE_OUTPUT_IDLE_TIMEOUT_MINUTES,
)

logger = logging.getLogger("dmp_orchestrator")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SESSION_FILE = ".dmp_session"

_sessions: dict[str, str] = {}
_has_active: set[str] = set()
_lock = threading.Lock()


def _ws_project_dir(workspace: str, project: str) -> str:
    return os.path.join(WORKSPACES_DIR, workspace, project)


def _session_path(ws_dir: str) -> str:
    return os.path.join(ws_dir, SESSION_FILE)


def _load_session_from_disk(ws_dir: str) -> str | None:
    sp = _session_path(ws_dir)
    if os.path.exists(sp):
        try:
            with open(sp) as f:
                sid = f.read().strip()
                if sid:
                    return sid
        except Exception:
            pass
    return None


def _save_session_to_disk(ws_dir: str, sid: str):
    os.makedirs(ws_dir, exist_ok=True)
    with open(_session_path(ws_dir), "w") as f:
        f.write(sid)


def _acquire_session(ws_dir: str) -> tuple[str, bool]:
    """Atomically get/create session ID and return (session_id, is_resume).

    Session IDs are persisted to disk so they survive backend restarts.
    is_resume=True means the session already existed (use --resume).
    is_resume=False means this is a brand-new session (use --session-id).
    """
    with _lock:
        # 1. Check disk — survives backend restarts
        existing = _load_session_from_disk(ws_dir)
        if existing:
            _sessions[ws_dir] = existing
            _has_active.add(ws_dir)
            return existing, True

        # 2. Check in-memory cache — from earlier in this process lifetime
        if ws_dir in _sessions:
            _has_active.add(ws_dir)
            return _sessions[ws_dir], True

        # 3. Brand-new session — persist to disk immediately
        sid = str(uuid_lib.uuid4())
        _sessions[ws_dir] = sid
        _save_session_to_disk(ws_dir, sid)
        _has_active.add(ws_dir)
        return sid, False


def _tool_args_summary(tool_name: str, tool_input: dict) -> str:
    """Extract a human-readable summary from tool input."""
    if not tool_input:
        return ""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Show first 60 chars of command
        if len(cmd) > 60:
            return cmd[:57] + "..."
        return cmd
    if tool_name in ("Read", "Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            return os.path.basename(file_path)
        return ""
    if tool_name in ("Grep", "Glob"):
        pattern = tool_input.get("pattern", "")
        return pattern[:40] if pattern else ""
    return ""


def _make_sse_converter():
    """Return a thread-safe SSE converter with its own thinking-block state."""
    _in_thinking = False
    _line_buffer = ""

    # Patterns for internal monologue lines that should be suppressed
    _MONOLOGUE_PATTERNS = [
        r"^(Now|Let me|I'll|I will|I need|First|Next|The|This|Checking|Looks like|Looks|Good[,.]|OK[,.]|Okay[,.]|Confirmed|Also|But|So|We|It|That|There|Here|Actually|Hmm|Wait|Ah|Yes|No|Maybe|Perhaps|Let's|Should|Could|Would|Must)\b",
        r"^(好的|让我|我来|首先|接下来|确认|检查|现在|当前|目前|然后|最后|注意|需要|可以|应该|必须)",
    ]

    def _is_monologue(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        for pat in _MONOLOGUE_PATTERNS:
            if re.match(pat, stripped):
                return True
        return False

    def _flush_line(line: str) -> str | None:
        """Convert a complete line (without trailing newline) to SSE."""
        if line.startswith("[STAGE]"):
            content = line[len("[STAGE]"):].strip()
            if content:
                data = json.dumps({"content": content}, ensure_ascii=False)
                return f"event: stage\ndata: {data}\n\n"
            return None
        elif _is_monologue(line):
            return None
        else:
            data = json.dumps({"content": line + "\n"}, ensure_ascii=False)
            return f"event: text\ndata: {data}\n\n"

    def _flush_remainder() -> str | None:
        """Flush any incomplete final line in the buffer."""
        nonlocal _line_buffer
        if not _line_buffer:
            return None
        remaining = _line_buffer
        _line_buffer = ""
        if remaining.startswith("[STAGE]"):
            content = remaining[len("[STAGE]"):].strip()
            if content:
                data = json.dumps({"content": content}, ensure_ascii=False)
                return f"event: stage\ndata: {data}\n\n"
            return None
        elif _is_monologue(remaining):
            return None
        else:
            data = json.dumps({"content": remaining}, ensure_ascii=False)
            return f"event: text\ndata: {data}\n\n"

    def _process_text_delta(text: str) -> str | None:
        """Buffer text and emit SSE for each complete line."""
        nonlocal _line_buffer
        _line_buffer += text
        events = []
        while "\n" in _line_buffer:
            idx = _line_buffer.index("\n")
            complete_line = _line_buffer[:idx]
            _line_buffer = _line_buffer[idx + 1:]
            sse = _flush_line(complete_line)
            if sse:
                events.append(sse)
        if events:
            return "".join(events)
        return None

    def convert(line: str) -> str | None:
        """Convert one stream-json line from claude CLI into SSE format."""
        nonlocal _in_thinking
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return None

        t = ev.get("type", "")

        if t == "stream_event":
            inner = ev.get("event", {})
            it = inner.get("type", "")

            if it == "content_block_start":
                block = inner.get("content_block", {})
                block_type = block.get("type", "")
                if block_type == "thinking":
                    result = _flush_remainder()
                    _in_thinking = True
                    return result
                elif block_type == "text":
                    _in_thinking = False
                    return None
                elif block_type == "tool_use":
                    result = _flush_remainder()
                    _in_thinking = False
                    name = block.get("name", "unknown")
                    args_summary = _tool_args_summary(name, block.get("input", {}))
                    data_dict = {"tool": name, "status": "running"}
                    if args_summary:
                        data_dict["args_summary"] = args_summary
                    data = json.dumps(data_dict, ensure_ascii=False)
                    tool_sse = f"event: tool_use\ndata: {data}\n\n"
                    if result:
                        return result + tool_sse
                    return tool_sse
                return None

            if it == "content_block_delta":
                delta = inner.get("delta", {})
                delta_type = delta.get("type", "")
                if delta_type in ("thinking_delta", "signature_delta"):
                    return None
                if _in_thinking:
                    return None
                if delta_type == "text_delta":
                    return _process_text_delta(delta.get("text", ""))
                return None

            if it == "content_block_stop":
                _in_thinking = False
                return _flush_remainder()

        elif t == "result":
            _in_thinking = False
            remainder_sse = _flush_remainder()
            if ev.get("is_error"):
                msg = ev.get("result", "Unknown error")
                data = json.dumps({"message": msg}, ensure_ascii=False)
                error_sse = f"event: error\ndata: {data}\n\n"
                if remainder_sse:
                    return remainder_sse + error_sse
                return error_sse
            result_text = ev.get("result", "")
            if result_text and isinstance(result_text, str) and len(result_text) < 200:
                data = json.dumps({"tool": "done", "status": "completed"}, ensure_ascii=False)
                tool_sse = f"event: tool_use\ndata: {data}\n\n"
                if remainder_sse:
                    return remainder_sse + tool_sse
                return tool_sse
            return remainder_sse

        return None

    return convert


def _run_claude(ws_dir: str, message: str):
    """Run Claude Code CLI and stream SSE output."""
    os.makedirs(ws_dir, exist_ok=True)
    session_id, is_resume = _acquire_session(ws_dir)
    flag = "--resume" if is_resume else "--session-id"

    cmd = [
        CLAUDE_BIN,
        "-p", message,
        "--model", CLAUDE_MODEL,
        flag, session_id,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--add-dir", ws_dir,
        "--add-dir", SKILL_DIR,
        "--permission-mode", "bypassPermissions",
        "--max-budget-usd", str(CLAUDE_MAX_BUDGET_USD),
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=PROJECT_ROOT,
    )

    # Drain stderr in a background thread to prevent buffer blocking
    stderr_lines = []
    def _drain_stderr():
        try:
            for line in process.stderr:
                stderr_lines.append(line)
        except Exception:
            pass

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    had_error = False
    error_message = ""
    process_start_time = time_module.time()
    last_output_time = process_start_time
    idle_timeout = CLAUDE_OUTPUT_IDLE_TIMEOUT_MINUTES * 60
    idle_keepalive_interval = 90  # send keepalive SSE every 90s of silence
    idle_kill_after = idle_timeout  # kill after full idle timeout

    # Watchdog: monitor idle time and kill process if it hangs
    _watchdog_stop = threading.Event()
    def _watchdog():
        while not _watchdog_stop.is_set():
            _watchdog_stop.wait(timeout=30)  # check every 30s
            if _watchdog_stop.is_set():
                return
            idle = time_module.time() - last_output_time
            if idle > idle_timeout:
                logger.error(f"Claude CLI idle for {idle:.0f}s, killing process")
                if process.poll() is None:
                    process.kill()
                return

    watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
    watchdog_thread.start()

    convert = _make_sse_converter()  # per-call instance with isolated thinking-block state

    try:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            last_output_time = time_module.time()
            sse = convert(line)
            if sse:
                yield sse

        # Process stdout exhausted, wait for exit with timeout
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            logger.warning("Claude CLI did not exit within 30s after stdout closed, killing")
            had_error = True
            error_message = "DMP 生成进程超时未退出，已终止"
            process.kill()
            process.wait(timeout=5)
            stderr_thread.join(timeout=2)
            err_text = "".join(stderr_lines[-20:]) if stderr_lines else "Process hang after stdout closed"
            logger.error(f"Claude CLI hang: {err_text[:500]}")
            data = json.dumps({"message": error_message}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"
            return

        # Check if process was killed by watchdog
        if process.returncode == -9:
            had_error = True
            idle_min = CLAUDE_OUTPUT_IDLE_TIMEOUT_MINUTES
            error_message = f"DMP 生成中断：连续 {idle_min} 分钟无输出，进程已终止。请检查网络或重试"
            logger.error(f"Claude CLI killed by watchdog after {idle_min}min idle")
            data = json.dumps({"message": error_message}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"
            return

        if process.returncode != 0:
            had_error = True
            stderr_thread.join(timeout=2)
            err_text = "".join(stderr_lines[-20:]) if stderr_lines else "Unknown error"
            logger.error(f"Claude CLI exited with code {process.returncode}: {err_text[:500]}")
            # Check for common failure patterns
            if "budget" in err_text.lower() or "max_budget" in err_text.lower():
                error_message = f"DMP 生成超出预算上限 (${CLAUDE_MAX_BUDGET_USD})，请简化方案或联系管理员提高预算"
            elif "rate" in err_text.lower() or "429" in err_text:
                error_message = "API 速率限制，请稍后重试"
            elif "auth" in err_text.lower() or "401" in err_text or "403" in err_text:
                error_message = "API 认证失败，请检查 API Key 配置"
            else:
                error_message = f"DMP 生成失败 (exit {process.returncode})，请重试"
            data = json.dumps({"message": error_message}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"

    except GeneratorExit:
        # Client disconnected — kill the process and log
        elapsed = time_module.time() - process_start_time
        logger.info(f"Client disconnected after {elapsed:.0f}s, killing Claude CLI process")
        had_error = True  # Prevent done event after disconnect
    except Exception as exc:
        had_error = True
        error_message = f"DMP 生成异常: {str(exc)}"
        logger.exception(f"Unexpected error in Claude CLI streaming: {exc}")
        data = json.dumps({"message": error_message}, ensure_ascii=False)
        yield f"event: error\ndata: {data}\n\n"
    finally:
        _watchdog_stop.set()
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Claude CLI refused to die after kill()")

    if not had_error:
        # Emit file_update to refresh frontend sidebar
        updated_files = []
        if os.path.exists(ws_dir):
            for name in sorted(os.listdir(ws_dir)):
                fpath = os.path.join(ws_dir, name)
                if os.path.isfile(fpath):
                    updated_files.append(name)
        if updated_files:
            data = json.dumps({"files": updated_files}, ensure_ascii=False)
            yield f"event: file_update\ndata: {data}\n\n"
        yield f"event: done\ndata: {json.dumps({'message': 'OK'}, ensure_ascii=False)}\n\n"


def clear_session(ws_dir: str):
    with _lock:
        _has_active.discard(ws_dir)
        _sessions.pop(ws_dir, None)
        sp = _session_path(ws_dir)
        if os.path.exists(sp):
            try:
                os.remove(sp)
            except OSError:
                pass


def send_message(ws_dir: str, user_message: str):
    yield from _run_claude(ws_dir, user_message)


def continue_dmp(ws_dir: str, project: str):
    """Resume an existing DMP session without clearing context."""
    if not _load_session_from_disk(ws_dir) and ws_dir not in _sessions:
        data = json.dumps({"message": "No existing session to continue. Please click Generate DMP first."}, ensure_ascii=False)
        yield f"event: error\ndata: {data}\n\n"
        return
    prompt = "继续执行未完成的工作。请从上一次中断的地方继续，不要从头开始。"
    yield from _run_claude(ws_dir, prompt)


def start_dmp(ws_dir: str, project: str):
    clear_session(ws_dir)  # Always start fresh DMP generation, never resume old context
    skill_scripts = os.path.join(SKILL_DIR, "scripts")
    skill_assets = os.path.join(SKILL_DIR, "assets")

    files_list = ""
    if os.path.exists(ws_dir):
        for name in sorted(os.listdir(ws_dir)):
            fpath = os.path.join(ws_dir, name)
            if os.path.isfile(fpath):
                files_list += f"  - {name} ({os.path.getsize(fpath)} bytes)\n"

    prompt = f"""你是 DMP 数据管理计划生成助手。严格按照 protocol-to-dmp skill (SKILL.md) 的完整工作流生成 DMP。

环境信息：
- 工作目录: {ws_dir}
- 脚本目录: {skill_scripts}
- 模板目录: {skill_assets}
- 方案文件: {files_list.strip()}

================================================================
铁律 — 违反以下任何一条即视为任务失败，每条必须遵守
================================================================

铁律 1：禁止自行修改 DM 日志的任何字段。
你永远不能在不经用户确认的情况下修改 dm-log.json 中的任何值。
发现需要修改的字段（包括但不限于：是否使用随机系统、是否使用登记系统、
EDC/PDC 选择、供应商、版本号、撰写人、审核人等），必须通过 [[QUESTION]]
格式弹窗询问用户，等用户明确回答后才能修改。
即使你认为某个字段"明显填错了"或"根据协议可以推断正确的值"，也不得自行修改。

铁律 2：遇到任何不确定/冲突/缺失的信息，必须通过 [[QUESTION]] 格式弹窗询问用户。
包括但不限于：方案与 DM 日志矛盾、DM 日志内部逻辑冲突（如随机系统=否但有随机供应商）、
必填字段缺失、模板选择歧义（随机和登记两者都是或两者都否且无法判定）。
禁止用纯文本叙述替代弹窗，禁止在文本中说"请确认XXX"而不使用 [[QUESTION]] 格式。

铁律 3：生成初稿（步骤 5）之前，必须先完成最终顺序确认门（步骤 6）。
不可跳过确认门直接生成文档。确认门中每轮只弹一个问题，等用户回答后继续下一个。
确认门必须覆盖所有在步骤 1-4 中积累的未解决项。

铁律 4：耦合字段联动检查。
「是否使用随机系统」和「是否使用登记系统」是关联字段。任一字段被用户修正后：
a) 先运行 update_dm_log.py 更新该字段
b) 立即重读 dm-log.json
c) 重新评估模板选择条件，主动弹窗询问另一个关联字段是否需要同步修正
d) 例：用户将随机改为"否"且登记仍为"是"→ 弹窗「您将随机系统改为"否"，登记系统当前为"是"，是否也需修改？」

================================================================
全局规则：用户交互必须使用以下格式，禁止纯文本提问
================================================================

[[QUESTION:type:choice]]
[[QUESTION_TEXT:问题文本]]
[[OPTION:A:选项A]]
[[OPTION:B:选项B]]
[[END_QUESTION]]

输入型用 [[QUESTION:type:input]]（不带 OPTION）。每次只问一个问题。

================================================================
输出纪律
================================================================

- 所有用户可见输出必须是中文。protocol 译为「方案」，不可译为「协议」。
- 进度更新只能是简短里程碑（如：trace 已构建、初稿已生成、QA 完成）。
- **所有进度更新行必须以 [STAGE] 开头独占一行**，不要用 markdown 格式（不要加 ### 或 **）。
  示例：
  [STAGE] 阶段0: 读取规则文档
  [STAGE] 阶段1: 选择模板 — 仅随机系统=是，使用 DMP-随机系统.docx
  [STAGE] 阶段2: 构建DMP Trace — 完成
  [STAGE] 阶段3a: 语义审查准备
  [STAGE] 阶段3b: 语义审查评审中...
  [STAGE] 阶段4: 交叉检查完成 — 未发现冲突
  [STAGE] 阶段5: 顺序确认门
  [STAGE] 阶段6: 标记清理 — 完成
  [STAGE] 阶段7: 质量检查QA — 完成
  [STAGE] 阶段8: 生成DMP初稿
  [STAGE] 阶段9: AI审查披露 — 完成
- **[STAGE] 严格限制**：
  - 只用于阶段级里程碑（阶段0-9），不用于子步骤、内部操作或调试信息
  - 每条不超过一行，不超过 40 个汉字
  - **禁止**在 [STAGE] 中出现：JSON 错误、修复过程、脚本日志、内部推理、统计数据（如 filled=33）
  - 这些细节如需告知用户，用不带 [STAGE] 的普通文本输出
- 禁止输出思维链、证据比较、原始 trace/review JSON、脚本日志、内部状态标签。
- 最终回复简洁：生成的文件路径、未解决的阻塞项、已执行的 QA、AI 审查披露。

================================================================
工作流步骤 — 必须按序完整执行，不可跳过
================================================================

阶段 0 — 规则准备：
以 Core Rules 为指南，按引用章节查阅 reference/chinese-dmp-generation.md。内部审查，不输出到聊天。

阶段 1 — 模板选择（含耦合字段检查）：
读取 dm-log.json，根据「是否使用随机系统」和「是否使用登记系统」选模板：
- 仅随机系统=是 → {skill_assets}/DMP-随机系统.docx
- 仅登记系统=是 → {skill_assets}/DMP-登记系统.docx
- 两者都否 → {skill_assets}/DMP-无随机无登记.docx
- 两者都是 → 弹窗询问用户选择
- 若用户纠正其中任一字段 → 更新 DM log → 重读 → 主动弹窗确认另一关联字段

阶段 2 — 构建证据溯源：
python3 {skill_scripts}/build_dmp_trace.py --protocol <方案文件> --dm-log {ws_dir}/dm-log.json --template-dir {skill_assets} --checklist {skill_assets}/DMP非固定内容清单.xlsx --out {ws_dir}/dmp_trace.json --questions {ws_dir}/dmp_questions.md --protocol-dump {ws_dir}/protocol_dump.txt

阶段 3 — 联合审查（语义 + few-shot，不可跳过）：
a) python3 {skill_scripts}/review_trace.py --mode prepare --trace {ws_dir}/dmp_trace.json --protocol-text {ws_dir}/protocol_dump.txt --fewshot {skill_assets}/fewshot.md --out {ws_dir}/review_input.json
b) 读取 review_input.json，静默审查。语义字段设 review_decision（accept/correct/flag），格式字段设 format_decision（accept/reformat/flag）。用 Edit 写入 JSON。
c) python3 {skill_scripts}/review_trace.py --mode apply --trace {ws_dir}/dmp_trace.json --review {ws_dir}/review_input.json --out {ws_dir}/dmp_trace.json

阶段 4 — 交叉检查（铁律 2 适用）：
审查 dmp_trace.json，对 Protocol/DM-log 交叉检查和 DM-log 内部一致性检查（见 reference doc §1）。
uncertain/missing/conflict/manual_confirm/not_processed 视为未解决。
**此步骤发现的任何冲突、矛盾、缺失，必须记录但先不弹窗，集中到步骤 5 统一处理。**

阶段 5 — 最终顺序确认门（铁律 3 适用，不可跳过）：
整理步骤 1-4 中所有仍未解决的确认项（包括模板选择歧义、交叉检查发现的冲突、
trace 中的 uncertain/missing/conflict 项）。
逐项弹窗提问，每轮一个，等用户回答后继续下一个。
用户每次回答后：
- 若涉及 DM-log 字段 → 运行 update_dm_log.py 更新
- 若涉及随机/登记字段 → 执行铁律 4 的耦合字段联动检查
- 更新 trace 中的对应项

阶段 6 — 标记清理：
按 checklist 规则完成模板选择/标记替换。受保护区域（section 9/15.2/26.1/27.1/27.2/27.3/29）不自行修改。
确保无残留 /模板/ 标记。

阶段 7 — 质量检查（见 reference doc §14）。

阶段 8 — 生成初稿：
python3 {skill_scripts}/apply_trace_to_template.py --trace {ws_dir}/dmp_trace.json --out {ws_dir}/DMP-初稿.docx --report {ws_dir}/DMP生成报告.md --annotated

阶段 9 — AI 披露（见 reference doc 步骤 9）。

================================================================
输出格式规范
================================================================

阶段标题和步骤结果行必须加 [STAGE] 前缀，例如：
[STAGE] 阶段 0/9：规则准备
[STAGE] **已完成** 读取规则文档
警告：> **警告**：描述
表格：标准 markdown，前后空行
[[QUESTION]] 块：前后空行，每次一个

禁止：逐字回显步骤编号、输出中间状态、合并多个问题到一个块、
输出 JSON/traceback/内部状态标签、跳过任何步骤。

现在开始。"""

    yield from _run_claude(ws_dir, prompt)
