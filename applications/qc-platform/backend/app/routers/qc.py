"""
表格清单一致性质控 SSE 路由

运行 tfl_qc_workflow.py 并实时流式推送进度事件给前端。
"""
import asyncio
import json
import os
import re
import shutil
import signal
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.config import WORKFLOW_SCRIPT, INNER_QC_WORKFLOW_SCRIPT, PROTOCOL_TABLE_WORKFLOW_SCRIPT, UPLOAD_DIR
from app.dependencies import get_current_user
from app.utils.docx_validator import validate_upload

router = APIRouter()


class QCRequest(BaseModel):
    table_path: str
    listing_path: str
    manual_qc: bool = False
    project_dir: str = ""  # 继续质控时复用已有项目目录
    api_key: str = ""  # 用户自己的 API key


class CleanupRequest(BaseModel):
    temp_dir: str


# ─── SSE helpers ──────────────────────────────────────────────────────────

def _find_project_dir(session_id: str, workspace: str) -> str | None:
    """查找 session 对应的项目目录。

    优先从内存 _session_projects，若后端重启丢失则根据 session_id 推导路径：
      temp_* / inner_qc_* / qc_session_* → {UPLOAD_DIR}/{workspace}/{session_id}
    """
    # 1. 内存缓存
    proj = _session_projects.get(session_id)
    if proj and os.path.isdir(proj):
        return proj

    # 2. 从 session_id 推导
    ws_dir = os.path.join(UPLOAD_DIR, workspace)
    candidate = os.path.join(ws_dir, session_id)
    if os.path.isdir(candidate):
        _session_projects[session_id] = candidate
        return candidate

    # 3. 扫描 workspace 子目录（session_id 可能是子目录名）
    try:
        for entry in os.listdir(ws_dir):
            entry_path = os.path.join(ws_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry == session_id:
                _session_projects[session_id] = entry_path
                return entry_path
            sub = os.path.join(entry_path, session_id)
            if os.path.isdir(sub):
                _session_projects[session_id] = sub
                return sub
    except FileNotFoundError:
        pass

    return None


def _sse_event(event: str, data: dict | None = None) -> str:
    lines = [f"event: {event}"]
    if data is not None:
        lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    else:
        lines.append(f"data: {json.dumps({})}")
    return "\n".join(lines) + "\n\n"


async def _validate_and_reject(path: str, label: str, output_queue: asyncio.Queue) -> bool:
    """校验上传文件格式。

    - .doc 旧格式 → 推送 error 并返回 True（阻断）
    """
    # .doc 旧格式 → 阻断
    err = validate_upload(path)
    if err:
        await output_queue.put(_sse_event("error", {"content": f"{label}: {err}"}))
        await output_queue.put(_sse_event("done", {}))
        return True
    return False


# ─── 全局活跃任务追踪（用于强制终止）───────────────────────────────────────

_active_processes: dict[str, asyncio.subprocess.Process] = {}
_session_projects: dict[str, str] = {}  # session_id → project_dir 映射
_temp_folders: dict[str, str] = {}  # temp_id → temp_dir 映射（临时文件夹追踪）


def _kill_process(process: asyncio.subprocess.Process):
    """强制终止子进程及其所有子进程"""
    if process.returncode is not None:
        return  # 已经退出
    try:
        pid = process.pid
        print(f"[QC] 正在终止子进程 PID={pid} ...")
        # SIGTERM 先优雅终止
        process.terminate()
        try:
            process.wait(timeout=3)
        except Exception:
            # SIGKILL 强制终止整个进程组
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                process.kill()
        print(f"[QC] 子进程 PID={pid} 已终止")
    except Exception as e:
        print(f"[QC] 终止子进程时出错: {e}")


# ─── QC 执行器 ────────────────────────────────────────────────────────────

async def _run_qc_workflow(
    table_path: str,
    listing_path: str,
    workspace: str,
    manual_qc: bool,
    output_queue: asyncio.Queue,
    project_dir: str = "",
    api_key: str = "",
):
    """在子进程中运行 tfl_qc_workflow.py，解析 stdout 并推送 SSE 事件。

    关键：无论何种原因退出（正常结束/客户端断开/异常），都会在 finally 中
    终止子进程，确保不会留下孤儿进程。
    """
    process: asyncio.subprocess.Process | None = None
    file_monitor_task: asyncio.Task | None = None
    monitor_stop = asyncio.Event()
    session_id = ""

    try:
        if not os.path.exists(table_path):
            await output_queue.put(_sse_event("error", {"content": f"表格文件不存在: {table_path}"}))
            await output_queue.put(_sse_event("done", {}))
            return
        if not os.path.exists(listing_path):
            await output_queue.put(_sse_event("error", {"content": f"清单文件不存在: {listing_path}"}))
            await output_queue.put(_sse_event("done", {}))
            return
        # 格式校验：.doc 旧格式 / 修订标记
        if await _validate_and_reject(table_path, "表格文件", output_queue):
            return
        if await _validate_and_reject(listing_path, "清单文件", output_queue):
            return

        if project_dir and os.path.isdir(project_dir):
            # 继续质控：复用已有项目目录
            session_id = os.path.basename(project_dir)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            session_id = f"qc_session_{ts}"
            project_dir = os.path.join(UPLOAD_DIR, workspace, session_id)
        os.makedirs(project_dir, exist_ok=True)
        _session_projects[session_id] = project_dir
        if session_id.startswith("temp_"):
            _temp_folders[session_id] = project_dir

        cmd = [
            "python3", "-u", WORKFLOW_SCRIPT,
            "--table", table_path,
            "--listing", listing_path,
            "--project", project_dir,
        ]
        if api_key:
            cmd += ["--api-key", api_key]
        if not manual_qc:
            cmd.append("--skip-review")

        print(f"[QC] 启动工作流 (session={session_id}): {' '.join(cmd)}")

        # 启动子进程时创建新的进程组，方便后续整组 kill
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid,  # 创建新进程组
        )
        _active_processes[session_id] = process

        total_pairs: int = 0

        async def monitor_pair_files():
            """后台任务：每秒轮询项目目录，检测新生成的 pair 报告文件"""
            nonlocal total_pairs
            known: set[str] = set()
            while not monitor_stop.is_set():
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().create_future(), timeout=1.0
                    )
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                if monitor_stop.is_set():
                    break
                try:
                    existing = set(
                        str(p) for p in Path(project_dir).glob("QC结果-Pair*.md")
                        if p.stat().st_size > 500
                    )
                    new = existing - known
                    if new:
                        known = existing
                        completed = len(known)
                        ttl = total_pairs if total_pairs > 0 else max(completed, 1)
                        pct = 5 + int((completed / ttl) * 90)
                        print(f"[QC] 📊 pair_progress: {completed}/{ttl} ({pct}%)  ← 新文件: {new}")
                        await output_queue.put(_sse_event("pair_progress", {
                            "completed": completed,
                            "total": ttl,
                            "percent": pct,
                        }))
                except Exception as e:
                    print(f"[QC] ⚠️ 文件监控异常: {e}")
                    pass

        # ── 逐行读取 stdout ──
        async for line_bytes in process.stdout:
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue

            m_total = re.search(r"需要 QC 的 pair 总数:\s*(\d+)", line)
            if m_total:
                total_pairs = int(m_total.group(1))
                await output_queue.put(_sse_event("total_pairs", {"total": total_pairs}))
                # ★ 收到 total_pairs → 立即启动文件监控（不依赖 stdout 文本匹配）
                if file_monitor_task is None:
                    file_monitor_task = asyncio.create_task(monitor_pair_files())
                    print(f"[QC] 文件监控已启动 (total_pairs={total_pairs})")
                continue

            # 检测人工复核 HTML 已生成 → 发送 review_html_ready 让前端自动弹出
            m_html = re.search(r"复核页面已生成:\s*(.+)", line)
            if m_html:
                html_path = m_html.group(1).strip()
                # 构建可通过 API 访问的 URL
                html_url = f"/api/qc/review-html/{session_id}"
                await output_queue.put(_sse_event("review_html_ready", {
                    "html_path": html_path,
                    "html_url": html_url,
                    "session_id": session_id,
                    "project_dir": project_dir,
                }))
                continue

            if re.search(r"Phase 3:", line) and "准备" not in line:
                if file_monitor_task is None:
                    file_monitor_task = asyncio.create_task(monitor_pair_files())
                    print(f"[QC] 文件监控已启动 (Phase 3 触发, total_pairs={total_pairs})")
                continue

            if "Phase 3 完成" in line:
                monitor_stop.set()
                if file_monitor_task:
                    file_monitor_task.cancel()
                    file_monitor_task = None
                if total_pairs > 0:
                    try:
                        final_count = len(list(Path(project_dir).glob("QC结果-Pair*.md")))
                    except Exception:
                        final_count = total_pairs
                    await output_queue.put(_sse_event("pair_progress", {
                        "completed": final_count, "total": total_pairs, "percent": 95,
                    }))
                continue

            if "Phase 4 完成" in line:
                await output_queue.put(_sse_event("progress", {"percent": 100, "text": "质控完成"}))
                continue

            if any(kw in line for kw in ["Traceback", "❌"]) or (
                "Error" in line and any(k in line for k in ["文件不存在", "失败", "Exception", "Error:"])
            ):
                await output_queue.put(_sse_event("error", {"content": line.strip()}))
                continue

        await process.wait()
        return_code = process.returncode

        if return_code != 0:
            await output_queue.put(_sse_event("error", {"content": f"工作流异常退出 (退出码: {return_code})"}))

        # 收集结果
        result_files = []
        try:
            for p in Path(project_dir).glob("QC*"):
                if p.is_file():
                    result_files.append(os.path.basename(str(p)))
        except Exception:
            pass

        await output_queue.put(_sse_event("done", {
            "files": result_files,
            "project_dir": project_dir,
            "session_id": session_id,
        }))

    except asyncio.CancelledError:
        print(f"[QC] 任务被取消 (session={session_id})，正在清理...")
        raise  # 重新抛出，让 finally 执行清理

    finally:
        # ═══════════════════════════════════════════════════════════
        # 保证无论何种退出都终止子进程和后台任务
        # ═══════════════════════════════════════════════════════════
        monitor_stop.set()
        if file_monitor_task and not file_monitor_task.done():
            file_monitor_task.cancel()

        if process is not None:
            _kill_process(process)
            if session_id in _active_processes:
                del _active_processes[session_id]
            # 注意：不删除 _session_projects，人工审核模式下 resumeQC 需要复用

        print(f"[QC] 清理完成 (session={session_id})")


# ─── SSE 端点 ─────────────────────────────────────────────────────────────

@router.post("/table-listing-cross")
async def qc_table_listing_cross(
    request: Request,
    body: QCRequest,
    _=Depends(get_current_user),
):
    """启动表格清单一致性质控，通过 SSE 流式返回进度。

    客户端断开连接（刷新/关闭页面）时自动终止后端子进程。
    """
    workspace = request.state.workspace
    output_queue: asyncio.Queue = asyncio.Queue()

    async def event_generator():
        workflow_task = asyncio.create_task(_run_qc_workflow(
            table_path=body.table_path,
            listing_path=body.listing_path,
            workspace=workspace,
            manual_qc=body.manual_qc,
            output_queue=output_queue,
            project_dir=body.project_dir,
            api_key=body.api_key,
        ))

        try:
            while True:
                # 检查客户端是否还在
                if await request.is_disconnected():
                    print("[QC] 客户端已断开，取消工作流...")
                    break

                try:
                    event_str = await asyncio.wait_for(output_queue.get(), timeout=0.5)
                    yield event_str
                except asyncio.TimeoutError:
                    if workflow_task.done():
                        while not output_queue.empty():
                            try:
                                yield output_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        break
                    yield ": heartbeat\n\n"

        except asyncio.CancelledError:
            print("[QC] 生成器被取消，取消工作流...")
            raise
        finally:
            # 客户端断开或异常 → 取消工作流任务 → 触发其 finally 杀子进程
            if not workflow_task.done():
                workflow_task.cancel()
                try:
                    await asyncio.wait_for(workflow_task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass  # 5 秒内没清理完也算了

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── 表格内部一致性质控 SSE 端点 ───────────────────────────────────────────


class InnerQCRequest(BaseModel):
    table_path: str
    baseline_path: str = ""  # 外部人群划分表（可选）
    randomization_path: str = ""  # 外部随机表（可选）
    project_dir: str = ""  # 复用已有项目目录
    api_key: str = ""  # 用户自己的 API key


class ProtocolTableQCRequest(BaseModel):
    protocol_path: str      # 方案文件路径
    table_path: str         # 表格文件路径
    project_dir: str = ""   # 复用已有项目目录


INNER_QC_PHASES = [
    "解析表格", "表型判断", "外部核查", "确定人群基准", "核查", "生成报告", "清理"
]


async def _run_inner_qc_workflow(
    table_path: str,
    workspace: str,
    output_queue: asyncio.Queue,
    baseline_path: str = "",
    randomization_path: str = "",
    project_dir: str = "",
    api_key: str = "",
):
    """在子进程中运行 inner_qc_workflow.py，解析 stdout 并推送 SSE 事件。"""
    process: asyncio.subprocess.Process | None = None
    file_monitor_task: asyncio.Task | None = None
    monitor_stop = asyncio.Event()
    session_id = ""
    total_tables: int = 0

    try:
        if not os.path.exists(table_path):
            await output_queue.put(_sse_event("error", {"content": f"表格文件不存在: {table_path}"}))
            await output_queue.put(_sse_event("done", {}))
            return
        # 格式校验：.doc 旧格式 / 修订标记
        if await _validate_and_reject(table_path, "表格文件", output_queue):
            return
        if baseline_path and os.path.exists(baseline_path):
            if await _validate_and_reject(baseline_path, "人群划分表", output_queue):
                return
        if randomization_path and os.path.exists(randomization_path):
            if await _validate_and_reject(randomization_path, "随机表", output_queue):
                return

        if project_dir and os.path.isdir(project_dir):
            session_id = os.path.basename(project_dir)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            session_id = f"inner_qc_{ts}"
            project_dir = os.path.join(UPLOAD_DIR, workspace, session_id)
        os.makedirs(project_dir, exist_ok=True)
        _session_projects[session_id] = project_dir
        if session_id.startswith("temp_"):
            _temp_folders[session_id] = project_dir

        cmd = [
            "python3", "-u", INNER_QC_WORKFLOW_SCRIPT,
            "--table", table_path,
            "--project", project_dir,
        ]
        if api_key:
            cmd += ["--api-key", api_key]
        if baseline_path and os.path.exists(baseline_path):
            cmd += ["--baseline-xlsx", baseline_path]
        if randomization_path and os.path.exists(randomization_path):
            cmd += ["--external-randomization", randomization_path]

        print(f"[InnerQC] 启动工作流 (session={session_id}): {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        _active_processes[session_id] = process

        async def monitor_qc_files():
            """后台任务：每秒轮询 qc_output/ 检测新生成的 qc_*.md/qc_*.json 和 qc_ext_*"""
            nonlocal total_tables
            known_nums: set[int] = set()
            qc_dir = Path(project_dir, "qc_output")
            while not monitor_stop.is_set():
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().create_future(), timeout=1.5
                    )
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                if monitor_stop.is_set():
                    break
                try:
                    if not qc_dir.is_dir():
                        continue
                    # 扫描 qc_*.md / qc_*.json 和 qc_ext_*.md / qc_ext_*.json，提取编号去重
                    nums: set[int] = set()
                    for p in qc_dir.glob("qc_*"):
                        # Phase 5: qc_05.md / qc_05.json；Phase 3: qc_ext_03.md / qc_ext_03.json
                        m = re.match(r"qc(?:_ext)?_(\d+)", p.name)
                        if m and p.stat().st_size > 50:
                            nums.add(int(m.group(1)))
                    new_nums = nums - known_nums
                    if new_nums:
                        known_nums.update(new_nums)
                        completed = len(known_nums)
                        ttl = total_tables if total_tables > 0 else max(completed, 1)
                        pct = min(22 + int((completed / ttl) * 73), 95)
                        print(f"[InnerQC] 📊 qc_progress: {completed}/{ttl} ({pct}%)")
                        await output_queue.put(_sse_event("qc_progress", {
                            "completed": completed,
                            "total": ttl,
                            "percent": pct,
                            "text": f"正在核查表 {completed}/{ttl}",
                        }))
                except Exception as e:
                    print(f"[InnerQC] ⚠️ 文件监控异常: {e}")

        # ★ 进程启动即开文件监控，不等 Phase 4 stdout（stdout 有缓冲延迟）
        file_monitor_task = asyncio.create_task(monitor_qc_files())

        # ── 逐行读取 stdout ──
        async for line_bytes in process.stdout:
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue

            # Phase 进展检测（match workflow 内部 print 行）

            # Phase 1: 提取表格
            if "Phase 1: 提取表格" in line or "Phase 1 提取" in line:
                await output_queue.put(_sse_event("progress", {"percent": 3, "text": "正在解析表格..."}))
                continue

            if "提取表格:" in line and "张" in line:
                m = re.search(r"(\d+)\s*张", line)
                if m:
                    total_tables = int(m.group(1))
                    await output_queue.put(_sse_event("total_tables", {"total": total_tables}))
                continue

            if "Phase 1 完成" in line:
                await output_queue.put(_sse_event("progress", {"percent": 10, "text": "表格解析完成"}))
                continue

            # Phase 2: 表型分类
            if "Phase 2: 表型分类" in line or "Phase 2 表型分类" in line:
                await output_queue.put(_sse_event("progress", {"percent": 12, "text": "正在进行表型判断..."}))
                continue

            if "分类表数:" in line:
                m = re.search(r"(\d+)", line)
                if m:
                    total_tables = int(m.group(1))
                    await output_queue.put(_sse_event("total_tables", {"total": total_tables}))
                continue

            if "Phase 2 完成" in line:
                await output_queue.put(_sse_event("progress", {"percent": 18, "text": "表型判断完成"}))
                continue

            # Phase 3: 外部核查（可选）
            if "Phase 3: 外部核查" in line or "Phase 3 外部核查" in line:
                await output_queue.put(_sse_event("progress", {"percent": 19, "text": "正在进行外部核查..."}))
                continue

            # Phase 4: 建立人数基准（原 Phase 3）
            if "Phase 4: 建立人数基准" in line or "Phase 4 建立人数基准" in line:
                await output_queue.put(_sse_event("progress", {"percent": 20, "text": "正在确定人群基准..."}))
                continue

            if "Phase 4 完成" in line:
                await output_queue.put(_sse_event("progress", {"percent": 22, "text": "人群基准确定完成"}))
                continue

            # Phase 5: 逐表 QC（原 Phase 4）
            if "Phase 5: 逐表 QC" in line or "Phase 5 逐表" in line or "Phase 5 准备" in line:
                await output_queue.put(_sse_event("progress", {"percent": 25, "text": "正在启动逐表核查..."}))
                continue

            if "Phase 5 完成" in line:
                await output_queue.put(_sse_event("progress", {"percent": 95, "text": "逐表核查完成"}))
                continue

            # Phase 6: 合并报告 + HTML 可视化（原 Phase 5 + 6）
            if "Phase 6: 合并报告" in line or "Phase 6 合并" in line:
                await output_queue.put(_sse_event("progress", {"percent": 96, "text": "正在生成合并报告..."}))
                continue

            if "Phase 6 合并完成" in line:
                await output_queue.put(_sse_event("progress", {"percent": 98, "text": "报告生成完成"}))
                continue

            if "Phase 6: 生成 HTML" in line or "Phase 6 生成 HTML" in line:
                await output_queue.put(_sse_event("progress", {"percent": 99, "text": "正在生成可视化报告..."}))
                continue

            # Phase 7: 清理
            if "Phase 7: 清理" in line or "Phase 7 清理" in line:
                await output_queue.put(_sse_event("progress", {"percent": 100, "text": "正在清理中间产物..."}))
                continue

            # 完成
            if "内部 QC 管线全部完成" in line:
                await output_queue.put(_sse_event("progress", {"percent": 100, "text": "质控完成"}))
                continue

            if any(kw in line for kw in ["Traceback", "❌"]) or (
                "Error" in line and any(k in line for k in ["文件不存在", "失败", "Exception", "Error:"])
            ):
                await output_queue.put(_sse_event("error", {"content": line.strip()}))
                continue

        await process.wait()
        return_code = process.returncode

        if return_code != 0:
            await output_queue.put(_sse_event("error", {"content": f"工作流异常退出 (退出码: {return_code})"}))

        await output_queue.put(_sse_event("done", {
            "project_dir": project_dir,
            "session_id": session_id,
        }))

    except asyncio.CancelledError:
        print(f"[InnerQC] 任务被取消 (session={session_id})")
        raise

    finally:
        monitor_stop.set()
        if file_monitor_task and not file_monitor_task.done():
            file_monitor_task.cancel()
        if process is not None:
            _kill_process(process)
            if session_id in _active_processes:
                del _active_processes[session_id]
        print(f"[InnerQC] 清理完成 (session={session_id})")


@router.post("/table-internal")
async def qc_table_internal(
    request: Request,
    body: InnerQCRequest,
    _=Depends(get_current_user),
):
    """启动表格内部一致性质控，通过 SSE 流式返回进度。"""
    workspace = request.state.workspace
    output_queue: asyncio.Queue = asyncio.Queue()

    async def event_generator():
        workflow_task = asyncio.create_task(_run_inner_qc_workflow(
            table_path=body.table_path,
            workspace=workspace,
            output_queue=output_queue,
            baseline_path=body.baseline_path,
            randomization_path=body.randomization_path,
            project_dir=body.project_dir,
            api_key=body.api_key,
        ))

        try:
            while True:
                if await request.is_disconnected():
                    print("[InnerQC] 客户端已断开，取消工作流...")
                    break

                try:
                    event_str = await asyncio.wait_for(output_queue.get(), timeout=0.5)
                    yield event_str
                except asyncio.TimeoutError:
                    if workflow_task.done():
                        while not output_queue.empty():
                            try:
                                yield output_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        break
                    yield ": heartbeat\n\n"

        except asyncio.CancelledError:
            print("[InnerQC] 生成器被取消，取消工作流...")
            raise
        finally:
            if not workflow_task.done():
                workflow_task.cancel()
                try:
                    await asyncio.wait_for(workflow_task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/inner-qc-viewer/{session_id}")
async def download_inner_qc_viewer(
    session_id: str,
    request: Request,
    token: str = "",
    _=Depends(get_current_user),
):
    """下载 inner-qc 可视化 HTML 报告。

    支持通过 ?token=xxx 传递 JWT 作为 window.open 回退方案的认证。
    """
    from fastapi.responses import FileResponse

    # 如果 query param 带了 token 但 header 没有，手动验证
    if token and not getattr(request.state, "user_id", 0):
        try:
            from app.utils.security import decode_token
            payload = decode_token(token)
            request.state.user_id = payload["user_id"]
            request.state.workspace = payload["workspace"]
        except Exception:
            pass  # fall through to normal auth

    project_dir = _find_project_dir(session_id, request.state.workspace)
    if not project_dir:
        raise HTTPException(404, "会话不存在或已过期，请重新运行质控")

    # 先在 qc_output/ 找，找不到再在项目根找（兼容 cleanup 后）
    html_path = os.path.join(project_dir, "qc_output", "QC可视化报告.html")
    if not os.path.exists(html_path):
        html_path = os.path.join(project_dir, "QC可视化报告.html")
    if not os.path.exists(html_path):
        raise HTTPException(404, "QC 报告尚未生成，请确认质控流程已完成")

    return FileResponse(
        html_path,
        media_type="text/html",
        filename="QC可视化报告.html",
    )


# ─── 方案表格一致性质控 SSE 端点 ───────────────────────────────────────────


async def _run_protocol_table_qc_workflow(
    protocol_path: str,
    table_path: str,
    workspace: str,
    output_queue: asyncio.Queue,
    project_dir: str = "",
):
    """在子进程中运行 qc_workflow.py（方案 vs 表格一致性质控），解析 stdout 并推送 SSE 事件。"""
    process: asyncio.subprocess.Process | None = None
    session_id = ""

    try:
        if not os.path.exists(protocol_path):
            await output_queue.put(_sse_event("error", {"content": f"方案文件不存在: {protocol_path}"}))
            await output_queue.put(_sse_event("done", {}))
            return
        if not os.path.exists(table_path):
            await output_queue.put(_sse_event("error", {"content": f"表格文件不存在: {table_path}"}))
            await output_queue.put(_sse_event("done", {}))
            return
        # 格式校验：.doc 旧格式 / 修订标记
        if await _validate_and_reject(protocol_path, "方案文件", output_queue):
            return
        if await _validate_and_reject(table_path, "表格文件", output_queue):
            return

        if project_dir and os.path.isdir(project_dir):
            session_id = os.path.basename(project_dir)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            session_id = f"protocol_qc_{ts}"
            project_dir = os.path.join(UPLOAD_DIR, workspace, session_id)
        os.makedirs(project_dir, exist_ok=True)
        _session_projects[session_id] = project_dir
        if session_id.startswith("temp_"):
            _temp_folders[session_id] = project_dir

        cmd = [
            "python3", "-u", PROTOCOL_TABLE_WORKFLOW_SCRIPT,
            "--protocol", protocol_path,
            "--tables", table_path,
            "--project", project_dir,
        ]

        print(f"[ProtocolQC] 启动工作流 (session={session_id}): {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        _active_processes[session_id] = process

        # Progress tracking: 5 nodes mapped to 0-100%
        # Node 1: 0-25%, Node 2: 25-40%, Node 3: 40-55%, Node 4: 55-90%, Node 5: 90-100%
        node_progress = {
            1: (0, "正在提取方案统计分析要素..."),
            2: (25, "正在提取表格目录并匹配..."),
            3: (40, "正在提取表格 DOCX → Excel..."),
            4: (55, "正在并行 Agent QC 核查..."),
            5: (90, "正在汇总生成质控报告..."),
        }

        async for line_bytes in process.stdout:
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue

            # Detect node transitions
            if "Node 1:" in line and "提取方案" in line:
                await output_queue.put(_sse_event("progress", {
                    "percent": node_progress[1][0], "text": node_progress[1][1],
                }))
                continue

            if "Node 2:" in line and "提取表格目录" in line:
                await output_queue.put(_sse_event("progress", {
                    "percent": node_progress[2][0], "text": node_progress[2][1],
                }))
                continue

            if "Node 3:" in line and "提取表格 DOCX" in line:
                await output_queue.put(_sse_event("progress", {
                    "percent": node_progress[3][0], "text": node_progress[3][1],
                }))
                continue

            if "Node 4:" in line and "并行 Agent" in line:
                await output_queue.put(_sse_event("progress", {
                    "percent": node_progress[4][0], "text": node_progress[4][1],
                }))
                continue

            if "Node 5:" in line and "汇总" in line:
                await output_queue.put(_sse_event("progress", {
                    "percent": node_progress[5][0], "text": node_progress[5][1],
                }))
                continue

            if "Node 6:" in line and "HTML" in line:
                await output_queue.put(_sse_event("progress", {
                    "percent": 98, "text": "正在生成可视化报告...",
                }))
                continue

            # Agent QC sub-progress: track individual section completions
            # Format: [板块名] ✅ or [板块名] ⚠️
            m_section = re.search(r"\[(.+?)\]\s*(✅|⚠️|❌)", line)
            if m_section:
                section_name = m_section.group(1)
                status = m_section.group(2)
                await output_queue.put(_sse_event("progress", {
                    "percent": 55 + 15,  # approximate
                    "text": f"Agent QC: [{section_name}] {status}",
                }))
                continue

            # Extract section count
            m_count = re.search(r"启动\s*(\d+)\s*个并行\s*Agent", line)
            if m_count:
                agent_count = int(m_count.group(1))
                await output_queue.put(_sse_event("total_pairs", {"total": agent_count}))
                continue

            # Error detection
            if any(kw in line for kw in ["Traceback", "❌"]) or (
                "Error" in line and any(k in line for k in ["文件不存在", "失败", "Exception", "Error:"])
            ):
                await output_queue.put(_sse_event("error", {"content": line.strip()}))
                continue

        await process.wait()
        return_code = process.returncode

        if return_code != 0:
            await output_queue.put(_sse_event("error", {"content": f"工作流异常退出 (退出码: {return_code})"}))

        # Collect result files
        result_files = []
        try:
            for p in Path(project_dir).glob("QC*"):
                if p.is_file():
                    result_files.append(os.path.basename(str(p)))
            # Also check for report in root
            for p in Path(project_dir).glob("*.md"):
                if p.is_file() and "QC" in p.name:
                    result_files.append(os.path.basename(str(p)))
        except Exception:
            pass

        await output_queue.put(_sse_event("done", {
            "files": result_files,
            "project_dir": project_dir,
            "session_id": session_id,
        }))

    except asyncio.CancelledError:
        print(f"[ProtocolQC] 任务被取消 (session={session_id})，正在清理...")
        raise

    finally:
        if process is not None:
            _kill_process(process)
            if session_id in _active_processes:
                del _active_processes[session_id]
        print(f"[ProtocolQC] 清理完成 (session={session_id})")


@router.post("/protocol-table")
async def qc_protocol_table(
    request: Request,
    body: ProtocolTableQCRequest,
    _=Depends(get_current_user),
):
    """启动方案表格一致性质控，通过 SSE 流式返回进度。"""
    workspace = request.state.workspace
    output_queue: asyncio.Queue = asyncio.Queue()

    async def event_generator():
        workflow_task = asyncio.create_task(_run_protocol_table_qc_workflow(
            protocol_path=body.protocol_path,
            table_path=body.table_path,
            workspace=workspace,
            output_queue=output_queue,
            project_dir=body.project_dir,
        ))

        try:
            while True:
                if await request.is_disconnected():
                    print("[ProtocolQC] 客户端已断开，取消工作流...")
                    break

                try:
                    event_str = await asyncio.wait_for(output_queue.get(), timeout=0.5)
                    yield event_str
                except asyncio.TimeoutError:
                    if workflow_task.done():
                        while not output_queue.empty():
                            try:
                                yield output_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        break
                    yield ": heartbeat\n\n"

        except asyncio.CancelledError:
            print("[ProtocolQC] 生成器被取消，取消工作流...")
            raise
        finally:
            if not workflow_task.done():
                workflow_task.cancel()
                try:
                    await asyncio.wait_for(workflow_task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── 人工审核辅助端点 ─────────────────────────────────────────────────────
# ─── 人工审核辅助端点 ─────────────────────────────────────────────────────

@router.get("/review-html/{session_id}")
async def serve_review_html(
    session_id: str,
    request: Request,
    _=Depends(get_current_user),
):
    """提供人工复核 HTML 页面，供前端自动弹出新标签页"""
    from fastapi.responses import HTMLResponse

    project_dir = _find_project_dir(session_id, request.state.workspace)
    if not project_dir:
        raise HTTPException(404, "会话不存在或已过期，请重新运行质控")

    html_path = os.path.join(project_dir, "映射复核.html")
    if not os.path.exists(html_path):
        raise HTTPException(404, "复核页面尚未生成")

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@router.get("/download-viewer/{session_id}")
async def download_viewer_html(
    session_id: str,
    request: Request,
    _=Depends(get_current_user),
):
    """下载 qc-viewer.html 交互式质控报告（QC 完成后前端自动触发下载）。

    优先从内存 _session_projects 查找，若后端进程重启导致丢失则自动推导路径。
    """
    from fastapi.responses import FileResponse

    project_dir = _find_project_dir(session_id, request.state.workspace)

    if not project_dir:
        raise HTTPException(404, "会话不存在或已过期，请重新运行质控")

    html_path = os.path.join(project_dir, "qc-viewer.html")
    if not os.path.exists(html_path):
        raise HTTPException(404, "QC 报告尚未生成，请确认质控流程已完成")

    return FileResponse(
        html_path,
        media_type="text/html",
        filename="qc-viewer.html",
    )


@router.get("/download-tfl-report/{session_id}")
async def download_tfl_report(
    session_id: str,
    request: Request,
    _=Depends(get_current_user),
):
    """下载表格清单一致性质控 HTML 交互式报告。"""
    from fastapi.responses import FileResponse

    project_dir = _find_project_dir(session_id, request.state.workspace)
    if not project_dir:
        raise HTTPException(404, "会话不存在或已过期，请重新运行质控")

    report_path = os.path.join(project_dir, "qc-viewer.html")
    if not os.path.exists(report_path):
        raise HTTPException(404, "QC 报告尚未生成，请确认质控流程已完成")

    return FileResponse(
        report_path,
        media_type="text/html",
        filename="表格清单一致性质控报告.html",
    )


@router.get("/download-protocol-viewer/{session_id}")
async def download_protocol_viewer(
    session_id: str,
    request: Request,
    _=Depends(get_current_user),
):
    """下载方案表格一致性质控 HTML 交互式报告。"""
    from fastapi.responses import FileResponse

    project_dir = _find_project_dir(session_id, request.state.workspace)
    if not project_dir:
        raise HTTPException(404, "会话不存在或已过期，请重新运行质控")

    html_path = os.path.join(project_dir, "QC可视化报告.html")
    if not os.path.exists(html_path):
        raise HTTPException(404, "QC HTML 报告尚未生成，请确认质控流程已完成")

    return FileResponse(
        html_path,
        media_type="text/html",
        filename="方案表格一致性质控报告.html",
    )


@router.get("/download-protocol-report/{session_id}")
async def download_protocol_report(
    session_id: str,
    request: Request,
    _=Depends(get_current_user),
):
    """下载方案表格一致性质控报告（Markdown 文件）。"""
    from fastapi.responses import FileResponse

    project_dir = _find_project_dir(session_id, request.state.workspace)
    if not project_dir:
        raise HTTPException(404, "会话不存在或已过期，请重新运行质控")

    # qc_workflow.py 产出的报告文件名
    report_path = os.path.join(project_dir, "QC一致性质控报告.md")
    if not os.path.exists(report_path):
        raise HTTPException(404, "QC 报告尚未生成，请确认质控流程已完成")

    return FileResponse(
        report_path,
        media_type="text/markdown; charset=utf-8",
        filename="QC一致性质控报告.md",
    )


@router.post("/upload-reviewed-json")
async def upload_reviewed_json(
    file: UploadFile,
    request: Request,
    session_id: str = Form(""),
    _=Depends(get_current_user),
):
    """上传人工审核后的 表格-清单-映射表-已复核.json，放置到对应项目目录以恢复管线"""
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(400, "仅支持 .json 文件")

    project_dir = _find_project_dir(session_id, request.state.workspace)
    if not project_dir:
        raise HTTPException(400, "会话不存在或已过期，请提供有效的 session_id")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(400, "文件超过 10MB 限制")

    dest = os.path.join(project_dir, "表格-清单-映射表-已复核.json")
    with open(dest, "wb") as f:
        f.write(contents)

    print(f"[QC] 已接收复核 JSON: {dest} ({len(contents)} bytes, session={session_id})")

    return {
        "status": "ok",
        "filename": "表格-清单-映射表-已复核.json",
        "path": dest,
        "size": len(contents),
    }


# ─── 临时文件夹管理 ──────────────────────────────────────────────────────

@router.post("/temp-folder")
async def create_temp_folder(request: Request, _=Depends(get_current_user)):
    """页面挂载时创建临时文件夹，上传和所有中间文件均存放于此"""
    workspace = request.state.workspace
    ws_upload_dir = os.path.join(UPLOAD_DIR, workspace)

    # 清理上一次会话残留的孤儿 temp 目录
    try:
        for entry in os.listdir(ws_upload_dir):
            if entry.startswith("temp_"):
                old_dir = os.path.join(ws_upload_dir, entry)
                if os.path.isdir(old_dir):
                    shutil.rmtree(old_dir, ignore_errors=True)
                    print(f"[QC] 清理孤儿临时文件夹: {old_dir}")
    except FileNotFoundError:
        pass

    temp_id = f"temp_{uuid.uuid4().hex[:8]}"
    temp_dir = os.path.join(ws_upload_dir, temp_id)
    os.makedirs(temp_dir, exist_ok=True)
    _temp_folders[temp_id] = temp_dir
    print(f"[QC] 创建临时文件夹: {temp_dir}")
    return {"temp_id": temp_id, "temp_dir": temp_dir}


class CancelRequest(BaseModel):
    session_id: str


@router.post("/cancel")
async def cancel_qc(body: CancelRequest):
    """主动取消正在运行的 QC 任务（不删除项目文件）。

    前端在以下场景调用:
      - Phase 3 执行中超时/报错，用户点击"取消"
      - 用户主动中止质控
    """
    proc = _active_processes.get(body.session_id)
    if proc is None:
        # 可能已经自然结束
        return {"status": "not_found", "session_id": body.session_id}

    _kill_process(proc)
    _active_processes.pop(body.session_id, None)
    # 保留 _session_projects —— 允许后续恢复
    print(f"[QC] 已强制终止任务 (session={body.session_id})")
    return {"status": "cancelled", "session_id": body.session_id}


@router.post("/cleanup")
async def cleanup_temp_folder(body: CleanupRequest):
    """页面刷新/关闭时清理临时文件夹及其所有内容（sendBeacon 调用，无认证依赖）"""
    temp_dir = os.path.abspath(body.temp_dir)
    basename = os.path.basename(temp_dir)

    # 安全校验（路径推导用户身份，不依赖 JWT）
    # 1. 必须是 temp_ 前缀目录
    if not basename.startswith("temp_"):
        raise HTTPException(400, "仅支持清理临时文件夹")
    # 2. 必须位于 UPLOAD_DIR 下某个现有 workspace 内
    try:
        parent_abs = os.path.abspath(os.path.dirname(temp_dir))
        upload_abs = os.path.abspath(UPLOAD_DIR)
    except Exception:
        raise HTTPException(400, "路径无效")
    if not parent_abs.startswith(upload_abs + os.sep):
        raise HTTPException(403, "无权删除此目录")
    # 3. 父目录（workspace）必须真实存在
    if not os.path.isdir(parent_abs):
        raise HTTPException(404, "工作区不存在")

    # 终止该目录下的活跃子进程
    sessions_to_remove: list[str] = []
    for sid, proj_dir in list(_session_projects.items()):
        abs_proj = os.path.abspath(proj_dir)
        if abs_proj == temp_dir or abs_proj.startswith(temp_dir + os.sep):
            proc = _active_processes.get(sid)
            if proc:
                _kill_process(proc)
            sessions_to_remove.append(sid)

    for sid in sessions_to_remove:
        _active_processes.pop(sid, None)
        _session_projects.pop(sid, None)

    # 清理 _temp_folders
    temps_to_remove = [tid for tid, td in _temp_folders.items()
                       if os.path.abspath(td) == temp_dir]
    for tid in temps_to_remove:
        _temp_folders.pop(tid, None)

    # 删除整个目录树
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"[QC] 已清理临时文件夹: {temp_dir}")

    return {"status": "cleaned", "temp_dir": temp_dir}
