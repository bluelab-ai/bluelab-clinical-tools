import asyncio
import json
import os
import sys
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Project, User
from app.dependencies import get_current_user
from app.config import SAP_WORKFLOW_SCRIPT

router = APIRouter(prefix="/api/projects", tags=["workflow"])

PHASE2_SCRIPT = os.path.join(os.path.dirname(SAP_WORKFLOW_SCRIPT), "phase2", "phase2_graph.py")

# Map workflow node names to the 7 frontend task names
NODE_TO_TASK = {
    "主要终点": "主要评价终点",
    "次要终点": "次要评价终点",
    "安全性评价": "安全性评价",
    "统计分析计划": "统计分析计划",
    "基线分析": "基线分析",
    "试验样本": "试验样本",
    "统计方法": "统计方法",
}

TASK_NAMES = ["主要评价终点", "次要评价终点", "安全性评价", "统计分析计划", "基线分析", "试验样本", "统计方法"]

TOTAL_NODES = 18  # Total nodes in the LangGraph workflow


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{project_id}/reset")
async def reset_workflow(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reset a stuck project back to pending."""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    p.status = "pending"
    p.phase = "pending"
    db.commit()
    return {"message": "已重置", "status": p.status, "phase": p.phase}


@router.post("/{project_id}/run")
async def run_workflow(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phase 1: Run SAP workflow to extract table catalog."""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if p.status == "running":
        # Auto-reset stuck projects (no active SSE connection means it's stuck)
        p.status = "pending"
        p.phase = "pending"
        db.commit()

    p.status = "running"
    p.phase = "phase1"
    db.commit()

    sap_path = p.sap_path
    crf_path = p.crf_path
    output_dir = p.output_dir

    async def event_stream():
        try:
            cmd = [sys.executable, SAP_WORKFLOW_SCRIPT, sap_path, "--output-dir", output_dir]
            if crf_path:
                cmd.extend(["--crf", crf_path])

            yield _sse("phase", {"phase": "start", "message": "正在启动阶段一工作流..."})

            project_root = os.path.dirname(os.path.dirname(SAP_WORKFLOW_SCRIPT))
            env = {**os.environ, "PYTHONPATH": project_root}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=project_root,
                env=env,
            )

            task_completed = {}
            nodes_done = 0
            line_buffer = ""

            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                line_buffer = line_str

                # Parse [PROGRESS] lines: e.g. "[PROGRESS] 3/18 提取主要终点"
                if line_str.startswith("[PROGRESS]"):
                    try:
                        parts = line_str[len("[PROGRESS]"):].strip().split(" ", 1)
                        done_total = parts[0]  # "3/18"
                        node_name = parts[1] if len(parts) > 1 else ""
                        done_count = int(done_total.split("/")[0])

                        # Map node name to task
                        matched_task = None
                        for key, task in NODE_TO_TASK.items():
                            if key in node_name:
                                matched_task = task
                                break

                        if matched_task and matched_task not in task_completed:
                            task_completed[matched_task] = True
                            completed = len(task_completed)
                            yield _sse("task", {
                                "task": matched_task,
                                "status": "completed",
                                "current": completed,
                                "total": 7,
                                "percent": round(completed / 7 * 100),
                            })

                        # Overall progress
                        overall_pct = round(done_count / TOTAL_NODES * 100)
                        yield _sse("progress", {
                            "current": done_count,
                            "total": TOTAL_NODES,
                            "percent": overall_pct,
                            "message": node_name,
                        })
                    except (ValueError, IndexError):
                        pass

                # Parse [LOG:DONE] lines for task completion
                elif line_str.startswith("[LOG:DONE]"):
                    msg = line_str[len("[LOG:DONE]"):].strip()
                    for key, task in NODE_TO_TASK.items():
                        if key in msg and task not in task_completed:
                            task_completed[task] = True
                            completed = len(task_completed)
                            yield _sse("task", {
                                "task": task,
                                "status": "completed",
                                "current": completed,
                                "total": 7,
                                "percent": round(completed / 7 * 100),
                            })

                # Parse [LOG:STEP] lines for current phase
                elif line_str.startswith("[LOG:STEP]"):
                    msg = line_str[len("[LOG:STEP]"):].strip()
                    # Detect which task is starting
                    for key, task in NODE_TO_TASK.items():
                        if key in msg and task not in task_completed:
                            yield _sse("task", {"task": task, "status": "running"})
                    yield _sse("phase", {"phase": "step", "message": msg})

            await process.wait()

            if process.returncode == 0:
                tables_count = 0
                tables_json = os.path.join(output_dir, "tables.json")
                if os.path.exists(tables_json):
                    with open(tables_json, "r", encoding="utf-8") as f:
                        tables_count = json.load(f).get("total", 0)

                p.status = "completed"
                p.phase = "catalog"
                p.tables_count = tables_count
                db.commit()

                # Mark all tasks as completed
                for task in TASK_NAMES:
                    yield _sse("task", {"task": task, "status": "completed"})
                yield _sse("progress", {"current": TOTAL_NODES, "total": TOTAL_NODES, "percent": 100})
                yield _sse("complete", {"tables_count": tables_count, "message": "阶段一完成"})
            else:
                p.status = "failed"
                p.phase = "pending"
                db.commit()
                yield _sse("error", {"message": line_buffer or f"工作流退出码: {process.returncode}"})

        except Exception as e:
            p.status = "failed"
            p.phase = "pending"
            db.commit()
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/{project_id}/run-phase2")
async def run_phase2(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phase 2: Generate tables from edited tables.json."""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if p.status == "running":
        # Auto-reset stuck projects
        p.status = "completed"
        p.phase = "catalog"
        db.commit()
    if not p.crf_path or not os.path.exists(p.crf_path):
        raise HTTPException(400, "Phase 2 需要 CRF 文件，请先上传")

    tables_json = os.path.join(p.output_dir, "tables.json")
    if not os.path.exists(tables_json):
        raise HTTPException(400, "表格目录不存在，请先完成阶段一")

    p.status = "running"
    p.phase = "phase2"
    db.commit()

    output_dir = p.output_dir
    crf_path = p.crf_path

    async def event_stream():
        try:
            cmd = [sys.executable, PHASE2_SCRIPT, "--output-dir", output_dir, "--crf", crf_path]

            yield _sse("phase", {"phase": "start", "message": "正在启动阶段二工作流..."})

            # Phase 2 uses absolute imports (from scripts.phase2.xxx),
            # so we need the project root on PYTHONPATH
            project_root = os.path.dirname(os.path.dirname(SAP_WORKFLOW_SCRIPT))
            env = {**os.environ, "PYTHONPATH": project_root}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=project_root,
                env=env,
            )

            line_buffer = ""
            PHASE2_TOTAL = 9

            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                line_buffer = line_str

                # Parse [PROGRESS] lines
                if line_str.startswith("[PROGRESS]"):
                    try:
                        parts = line_str[len("[PROGRESS]"):].strip().split(" ", 1)
                        if "/" in parts[0]:
                            cur, tot = parts[0].split("/", 1)
                            cur_i, tot_i = int(cur), int(tot)
                            pct = round(cur_i / tot_i * 100)
                            node_cn = parts[1] if len(parts) > 1 else ""
                            yield _sse("progress", {"current": cur_i, "total": tot_i, "percent": pct, "node": node_cn})
                    except (ValueError, IndexError):
                        pass
                # Forward log lines as phase events
                elif line_str.startswith("[LOG:"):
                    try:
                        bracket_end = line_str.index("]")
                        level = line_str[5:bracket_end]
                        msg = line_str[bracket_end + 1:].strip()
                        yield _sse("phase", {"phase": level.lower(), "message": msg})
                    except (ValueError, IndexError):
                        yield _sse("phase", {"phase": "processing", "message": line_str})
                elif "完成" in line_str or "✅" in line_str:
                    yield _sse("phase", {"phase": "done_step", "message": line_str})

            await process.wait()

            if process.returncode == 0:
                p.status = "completed"
                p.phase = "completed"
                db.commit()
                yield _sse("complete", {"message": "阶段二完成，表格已生成"})
            else:
                p.status = "failed"
                p.phase = "catalog"
                db.commit()
                yield _sse("error", {"message": line_buffer or f"工作流退出码: {process.returncode}"})

        except Exception as e:
            p.status = "failed"
            p.phase = "catalog"
            db.commit()
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/{project_id}/run-phase2a")
async def run_phase2a(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phase 2a: 仅提取指标（前4个节点），完成后进入审核页面"""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if p.status == "running":
        p.status = "completed"
        p.phase = "catalog"
        db.commit()
    if not p.crf_path or not os.path.exists(p.crf_path):
        raise HTTPException(400, "Phase 2 需要 CRF 文件，请先上传")

    tables_json = os.path.join(p.output_dir, "tables.json")
    if not os.path.exists(tables_json):
        raise HTTPException(400, "表格目录不存在，请先完成阶段一")

    p.status = "running"
    p.phase = "phase2"
    db.commit()

    output_dir = p.output_dir
    crf_path = p.crf_path

    async def event_stream():
        try:
            cmd = [sys.executable, PHASE2_SCRIPT, "--output-dir", output_dir, "--crf", crf_path, "--steps", "a"]

            yield _sse("phase", {"phase": "start", "message": "正在提取表格指标..."})

            project_root = os.path.dirname(os.path.dirname(SAP_WORKFLOW_SCRIPT))
            env = {**os.environ, "PYTHONPATH": project_root}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=project_root,
                env=env,
            )

            line_buffer = ""
            PHASE2A_TOTAL = 4

            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                line_buffer = line_str

                if line_str.startswith("[PROGRESS]"):
                    try:
                        parts = line_str[len("[PROGRESS]"):].strip().split(" ", 1)
                        if "/" in parts[0]:
                            cur, tot = parts[0].split("/", 1)
                            cur_i, tot_i = int(cur), int(tot)
                            pct = round(cur_i / tot_i * 100)
                            node_cn = parts[1] if len(parts) > 1 else ""
                            yield _sse("progress", {"current": cur_i, "total": tot_i, "percent": pct, "node": node_cn})
                    except (ValueError, IndexError):
                        pass
                elif line_str.startswith("[LOG:"):
                    try:
                        bracket_end = line_str.index("]")
                        level = line_str[5:bracket_end]
                        msg = line_str[bracket_end + 1:].strip()
                        yield _sse("phase", {"phase": level.lower(), "message": msg})
                    except (ValueError, IndexError):
                        yield _sse("phase", {"phase": "processing", "message": line_str})
                elif "完成" in line_str or "✅" in line_str:
                    yield _sse("phase", {"phase": "done_step", "message": line_str})

            await process.wait()

            if process.returncode == 0:
                p.status = "completed"
                p.phase = "review"
                db.commit()
                yield _sse("complete", {"message": "指标提取完成，请审核", "next": "review"})
            else:
                p.status = "failed"
                p.phase = "catalog"
                db.commit()
                yield _sse("error", {"message": line_buffer or f"工作流退出码: {process.returncode}"})

        except Exception as e:
            p.status = "failed"
            p.phase = "catalog"
            db.commit()
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/{project_id}/run-phase2b")
async def run_phase2b(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phase 2b: 仅生成表格（后5个节点），从审核页面触发"""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if p.status == "running":
        p.status = "completed"
        p.phase = "review"
        db.commit()

    p.status = "running"
    p.phase = "phase2"
    db.commit()

    output_dir = p.output_dir
    crf_path = p.crf_path

    async def event_stream():
        try:
            cmd = [sys.executable, PHASE2_SCRIPT, "--output-dir", output_dir, "--crf", crf_path, "--steps", "b"]

            yield _sse("phase", {"phase": "start", "message": "正在生成表格..."})

            project_root = os.path.dirname(os.path.dirname(SAP_WORKFLOW_SCRIPT))
            env = {**os.environ, "PYTHONPATH": project_root}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=project_root,
                env=env,
            )

            line_buffer = ""
            PHASE2B_TOTAL = 5

            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                line_buffer = line_str

                if line_str.startswith("[PROGRESS]"):
                    try:
                        parts = line_str[len("[PROGRESS]"):].strip().split(" ", 1)
                        if "/" in parts[0]:
                            cur, tot = parts[0].split("/", 1)
                            cur_i, tot_i = int(cur), int(tot)
                            pct = round(cur_i / tot_i * 100)
                            node_cn = parts[1] if len(parts) > 1 else ""
                            yield _sse("progress", {"current": cur_i, "total": tot_i, "percent": pct, "node": node_cn})
                    except (ValueError, IndexError):
                        pass
                elif line_str.startswith("[LOG:"):
                    try:
                        bracket_end = line_str.index("]")
                        level = line_str[5:bracket_end]
                        msg = line_str[bracket_end + 1:].strip()
                        yield _sse("phase", {"phase": level.lower(), "message": msg})
                    except (ValueError, IndexError):
                        yield _sse("phase", {"phase": "processing", "message": line_str})
                elif "完成" in line_str or "✅" in line_str:
                    yield _sse("phase", {"phase": "done_step", "message": line_str})

            await process.wait()

            if process.returncode == 0:
                p.status = "completed"
                p.phase = "completed"
                db.commit()
                yield _sse("complete", {"message": "表格生成完成"})
            else:
                p.status = "failed"
                p.phase = "review"
                db.commit()
                yield _sse("error", {"message": line_buffer or f"工作流退出码: {process.returncode}"})

        except Exception as e:
            p.status = "failed"
            p.phase = "review"
            db.commit()
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/{project_id}/cancel")
async def cancel_workflow(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")

    p.status = "pending"
    db.commit()
    return {"message": "已取消"}
