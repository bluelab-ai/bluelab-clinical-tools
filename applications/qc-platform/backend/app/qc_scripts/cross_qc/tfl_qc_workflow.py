"""
TFL Cross-Validation QC Workflow
================================
LangGraph + Anthropic SDK 混合架构 — 临床试验表格-清单反向质控管线。

架构:
  LangGraph:     Phase 1 → 1b → 2 → 3 → 4  确定性管线 + 阶段门控
  Anthropic SDK: Phase 3 内部并行 LLM 调用 (ThreadPoolExecutor + tool-use loop)

运行:
    python tfl_qc_workflow.py \
        --api-key sk-xxx \
        --table 表格附件.docx \
        --listing 清单附件.docx \
        --project /path/to/project

    默认使用 DeepSeek Anthropic 兼容端点（与 Claude Code 全局配置对齐）:
      --api-base https://api.deepseek.com/anthropic
      --model deepseek-v4-pro

依赖:
    pip install langgraph langchain openpyxl anthropic
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict, cast
from collections.abc import Sequence

import operator

import anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed

_sys_path_add = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
if _sys_path_add not in sys.path:
    sys.path.insert(0, _sys_path_add)
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver


# ═══════════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════════

class ListingRef(TypedDict):
    """参考清单描述"""
    listing_number: int          # 清单编号
    listing_name: str            # 清单名称
    listing_population: str      # 清单人群 (FAS/PPS/SS)


class QCPair(TypedDict):
    """单个 QC 对（一个表格 + 一到多个参考清单）"""
    pair_id: int                 # 1-based 序号
    table_number: int            # Table 编号
    table_name: str              # 表格名称
    table_population: str        # 表格人群
    listings: list[ListingRef]   # 参考清单列表
    match_method: str            # "关键字匹配" | "人工指定"
    should_qc: bool              # 是否应进入 QC


class QCState(TypedDict, total=False):
    """贯穿全部 Phase 的全局状态"""

    # ── CLI 输入 ──
    table_input: str             # 表格附件路径 (docx/pdf)
    listing_input: str            # 清单附件路径 (docx/pdf)
    project_dir: str              # 项目工作目录
    skill_dir: str                # skill 资源目录
    model: str                    # LLM 模型名
    api_key: str                  # API key（直接传参，不读环境变量）
    api_base: str                 # API base URL
    skip_review: bool             # 是否跳过 Phase 1b 人工复核
    max_pairs: int                # 最多 QC pair 数（None=全部）
    max_retries: int              # 缺失 pair 最大重试次数（默认2）

    # ── Phase 1 产出 ──
    mapping_json_path: str        # 表格-清单-映射表.json 路径
    mapping_data: list[dict]      # 映射表完整数据（内存中）
    needs_review: bool            # 是否需要人工复核

    # ── Phase 1b 产出（可选）──
    reviewed_mapping_path: str    # 表格-清单-映射表-已复核.json
    review_html_path: str         # 映射复核.html

    # ── Phase 2 产出 ──
    table_excel_dir: str          # 表格/ 目录
    listing_excel_dir: str        # 清单/ 目录

    # ── Phase 3 调度 ──
    qc_pairs: list[QCPair]        # 需要 QC 的 pair 列表
    total_pairs: int              # pair 总数
    # 收集各 pair 报告路径；operator.add 自动 append
    pair_report_paths: Annotated[list[str], operator.add]

    # ── Phase 4 产出 ──
    merged_detail_path: str       # QC结果-全部合并.md
    merged_summary_path: str      # QC报告-汇总.md

    # ── Phase 4b 产出 ──
    viewer_html_path: str          # qc-viewer.html (交互式浏览报告)

    # ── 控制 ──
    current_phase: str            # init | phase1_done | phase1b_done | ...
    error_message: str            # 错误信息


# ═══════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_skill_dir() -> str:
    """自动解析 qc_scripts/cross_qc 资源目录（与本脚本同目录）"""
    env = os.environ.get("TFL_QC_SKILL_DIR")
    if env:
        return env
    candidate = Path(__file__).parent
    if candidate.exists():
        return str(candidate.resolve())
    raise FileNotFoundError(
        "无法自动定位 cross_qc 目录，请设置环境变量 TFL_QC_SKILL_DIR"
    )


def _run_script(script_path: str, args: list[str], cwd: str | None = None,
                ) -> subprocess.CompletedProcess:
    """运行 Python 脚本，输出实时打印，返回结果"""
    cmd = ["python3", script_path] + args
    print(f"  → {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        # 截断过长输出
        out = result.stdout.strip()
        if len(out) > 2000:
            out = out[:2000] + "\n  ... (输出已截断)"
        print(f"  stdout:\n{out}")
    if result.stderr:
        err = result.stderr.strip()
        if len(err) > 1000:
            err = err[:1000] + "\n  ... (stderr 已截断)"
        print(f"  stderr:\n{err}")
    return result


def _load_mapping_into_state(state: QCState, mapping_path: str) -> dict:
    """加载映射表 JSON 并存入 state"""
    with open(mapping_path) as f:
        data = json.load(f)
    # 判断是否需要复核：存在 多源候选 或 直接匹配 但相似度低的对
    needs_review = any(
        entry.get("匹配方法") == "多源候选"
        or (
            entry.get("匹配方法") == "直接匹配"
            and entry.get("最佳匹配", {}).get("余弦相似度", 1.0) < 0.70
        )
        for entry in data
    )
    return {
        "mapping_json_path": mapping_path,
        "mapping_data": data,
        "needs_review": needs_review,
    }


def _create_anthropic_client(state: QCState) -> anthropic.Anthropic:
    """
    根据 state 中的配置构建 Anthropic SDK 客户端。

    使用 DeepSeek Anthropic 兼容端点。
    所有参数直接传入，不读环境变量。

    默认值与 ~/.claude/settings.json 中 ANTHROPIC_BASE_URL / ANTHROPIC_MODEL 对齐。
    """
    api_key = state.get("api_key", "")
    api_base = state.get("api_base", LLM_API_BASE)

    if not api_key:
        raise ValueError(
            "缺少 API key。请通过 --api-key 参数传入。\n"
            "示例: --api-key sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        )

    return anthropic.Anthropic(
        api_key=api_key,
        base_url=api_base,
        timeout=300,
        max_retries=3,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1: 提取（提取表格/清单到 Excel + 输出标题索引 JSON）
# ═══════════════════════════════════════════════════════════════════════════

def phase1_extract(state: QCState) -> dict:
    """
    从 docx/PDF 中提取表格和清单为独立 Excel 文件，
    同时产出标题索引 JSON 供 Phase 2 匹配消费。

    输出结构:
      表格/  01-标题.xlsx  ...  + 表格-标题索引.json
      清单/  01-标题.xlsx  ...  + 清单-标题索引.json
    """
    print("\n" + "=" * 60)
    print("📊 Phase 1: 提取表格到 Excel")
    print("=" * 60)

    project = state["project_dir"]
    skill = state["skill_dir"]
    table_input = state["table_input"]
    listing_input = state["listing_input"]

    is_pdf = table_input.lower().endswith(".pdf")
    script_name = "extract_tables_pdf.py" if is_pdf else "extract_tables.py"
    script_path = os.path.join(skill, script_name)

    # 传递 API key 给提取脚本（LLM 分类需要）
    api_key = state.get("api_key", "")
    extra_args = []
    if api_key:
        extra_args = ["--api-key", api_key, "--api-base", state.get("api_base", LLM_API_BASE),
                       "--model", state.get("model", LLM_MODEL)]

    result = _run_script(script_path, [table_input, listing_input] + extra_args, cwd=project)

    if result.returncode != 0:
        return {"error_message": f"Phase 1 提取失败: {result.stderr}", "current_phase": "error"}

    table_dir = os.path.join(project, "表格")
    listing_dir = os.path.join(project, "清单")

    if not os.path.isdir(table_dir) or not os.path.isdir(listing_dir):
        return {"error_message": "Phase 1 未生成 表格/ 或 清单/ 目录", "current_phase": "error"}

    table_count = len([f for f in os.listdir(table_dir) if f.endswith(".xlsx")])
    listing_count = len([f for f in os.listdir(listing_dir) if f.endswith(".xlsx")])
    print(f"  表格: {table_count} 个 xlsx  清单: {listing_count} 个 xlsx")
    print("✅ Phase 1 完成")

    # ── 格式校验 ──
    result = {
        "table_excel_dir": table_dir,
        "listing_excel_dir": listing_dir,
        "current_phase": "phase1_done",
    }
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1b: 人工复核 (Human-in-the-Loop)
# ═══════════════════════════════════════════════════════════════════════════

def _generate_review_html(state: QCState) -> str:
    """生成交互式复核 HTML 页面"""
    skill = state["skill_dir"]
    project = state["project_dir"]

    with open(os.path.join(skill, "assets", "映射复核.html")) as f:
        template = f.read()

    mapping = state.get("mapping_data")
    if not mapping:
        with open(state["mapping_json_path"]) as f:
            mapping = json.load(f)

    # 从清单标题索引 JSON 读取全部清单（不受映射表覆盖范围限制）
    listing_records: list[dict] = []
    listing_index_path = os.path.join(project, "清单", "清单-标题索引.json")
    if os.path.exists(listing_index_path):
        with open(listing_index_path) as f:
            listing_index = json.load(f)
        for lst in listing_index:
            listing_records.append({
                "key": f"{lst.get('num','')}|{lst.get('title','')}",
                "name": lst.get('title', ''),
                "num": lst.get('num', ''),
                "pop": lst.get('population', '-'),
            })
    listing_records.sort(key=lambda r: r["key"])

    html = template.replace(
        "__MAPPING_DATA__",
        json.dumps(mapping, ensure_ascii=False, separators=(",", ":"))
    )
    html = html.replace(
        "__LISTINGS_DATA__",
        json.dumps(listing_records, ensure_ascii=False, separators=(",", ":"))
    )

    html_path = os.path.join(project, "映射复核.html")
    with open(html_path, "w") as f:
        f.write(html)
    return html_path


def _check_reviewed_json(project_dir: str) -> str | None:
    """检查是否有已复核的 JSON"""
    path = os.path.join(project_dir, "表格-清单-映射表-已复核.json")
    return path if os.path.exists(path) else None


def phase1b_review(state: QCState) -> dict:
    """
    生成交互式复核 HTML，暂停等待人工审查。

    用户流程:
      1. 浏览器打开 映射复核.html
      2. 审查匹配关系，修正错误
      3. 点击「导出修改」下载 表格-清单-映射表-已复核.json
      4. 将下载的 JSON 放回项目目录
      5. 恢复执行
    """
    print("\n" + "=" * 60)
    print("🔍 Phase 1b: 人工复核")
    print("=" * 60)

    if state.get("skip_review"):
        print("  --skip-review 已设置，跳过人工复核")
        return {"current_phase": "phase1b_done"}

    project = state["project_dir"]

    # 先检查是否已有已复核 JSON（可能是之前暂停后恢复）
    reviewed = _check_reviewed_json(project)
    if reviewed:
        print(f"  已找到复核结果: {reviewed}")
        print("✅ Phase 1b 完成（使用已有复核结果）")
        return {
            "reviewed_mapping_path": reviewed,
            "current_phase": "phase1b_done",
        }

    # 生成复核 HTML
    html_path = _generate_review_html(state)
    print(f"  复核页面已生成: {html_path}")
    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║  请在浏览器中打开 映射复核.html                          ║")
    print("  ║  审查匹配关系 → 修正 → 点击「导出修改」下载 JSON         ║")
    print("  ║  将下载的 表格-清单-映射表-已复核.json 放回项目目录       ║")
    print("  ║  然后恢复执行                                           ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print()

    # ★ LangGraph interrupt — 暂停执行，等待人工完成恢复
    from langgraph.types import interrupt
    interrupt(
        "请在浏览器中审查 映射复核.html 页面，"
        "将导出的 表格-清单-映射表-已复核.json 放回项目目录后继续。"
    )

    # 恢复后重新检查
    reviewed = _check_reviewed_json(project)
    if reviewed:
        print(f"  已找到复核结果: {reviewed}")
        print("✅ Phase 1b 完成")
        return {
            "reviewed_mapping_path": reviewed,
            "current_phase": "phase1b_done",
        }
    else:
        # 用户跳过，回退到原始映射
        print("  ⚠️ 未找到复核 JSON，回退使用原始映射表")
        return {"current_phase": "phase1b_done"}


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: 匹配（读取 Phase 1 产出的标题索引 JSON，执行关键字+余弦匹配）
# ═══════════════════════════════════════════════════════════════════════════

def phase2_match(state: QCState) -> dict:
    """
    读取提取脚本产出的标题索引 JSON，执行表格-清单匹配。
    策略: 关键字匹配 → 余弦相似度 → (可选) DeepSeek LLM 兜底
    """
    print("\n" + "=" * 60)
    print("📎 Phase 2: 表格-清单匹配")
    print("=" * 60)

    project = state["project_dir"]
    skill = state["skill_dir"]
    mapping_path = os.path.join(project, "表格-清单-映射表.json")

    # Phase 1 已将 DOCX/PDF 统一提取为表格-标题索引.json + 清单-标题索引.json
    # 匹配脚本消费相同的 JSON 中间格式，与原始格式无关
    table_index = os.path.join(project, "表格", "表格-标题索引.json")
    listing_index = os.path.join(project, "清单", "清单-标题索引.json")

    if not os.path.exists(table_index) or not os.path.exists(listing_index):
        return {"error_message": "Phase 2 找不到标题索引 JSON（请先运行 Phase 1 提取）", "current_phase": "error"}

    script_path = os.path.join(skill, "match_tables_listings.py")

    result = _run_script(script_path, [table_index, listing_index, mapping_path])

    if result.returncode != 0:
        return {"error_message": f"Phase 2 匹配失败: {result.stderr}", "current_phase": "error"}

    if not os.path.exists(mapping_path):
        return {"error_message": "Phase 2 未生成映射表 JSON", "current_phase": "error"}

    updates = _load_mapping_into_state(state, mapping_path)

    # 统计
    data = updates["mapping_data"]
    keyword_count = sum(1 for e in data if e.get("匹配方法") == "关键字匹配")
    cosine_count = sum(1 for e in data if e.get("匹配方法") == "直接匹配")
    multi_count = sum(1 for e in data if e.get("匹配方法") == "多源候选")
    print(f"  表格: {len(data)}  关键字匹配: {keyword_count}  直接匹配: {cosine_count}  多源候选: {multi_count}")
    print(f"  需人工复核: {'是' if updates['needs_review'] else '否'}")
    print("✅ Phase 2 完成")

    updates["current_phase"] = "phase2_done"
    return updates


# ═══════════════════════════════════════════════════════════════════════════
# Anthropic SDK 工具定义（替换 deep_agent 的 LocalShellBackend）
# ═══════════════════════════════════════════════════════════════════════════

QC_TOOLS: list[dict] = [
    {
        "name": "bash",
        "description": (
            "Execute a shell command in the project directory. "
            "Use for: exploring files with ls, reading Excel structure with python3 -c openpyxl, "
            "running QC comparison scripts. Commands run in the project working directory. "
            "Timeout: 120 seconds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute. Example: ls 表格/ | grep '05-'",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file. Use for reading existing QC reports, "
            "checking reference files, or inspecting output. Returns up to 50KB of content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read. Relative paths resolved against project dir.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write content to a file. Use ONLY for writing the final QC report. "
            "The report MUST be written to QC结果-Pair{{NN}}.md in the project directory "
            "(NN=two-digit pair number, e.g. QC结果-Pair01.md). "
            "Do NOT create subdirectories, .txt, .py, .json, or .xlsx files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to write to. Must be QC结果-Pair{{NN}}.md in the project dir.",
                },
                "content": {
                    "type": "string",
                    "description": "The full markdown content of the QC report.",
                },
            },
            "required": ["path", "content"],
        },
    },
]


def _execute_tool(tool_name: str, tool_input: dict, project_dir: str) -> str:
    """Execute a tool call from the model and return the result string."""
    if tool_name == "bash":
        command = tool_input.get("command", "")
        try:
            result = subprocess.run(
                command, shell=True, cwd=project_dir,
                capture_output=True, text=True, timeout=180,
            )
            output = result.stdout.strip()
            if result.stderr:
                err = result.stderr.strip()
                if len(err) > 2000:
                    err = err[:2000] + "\n... (stderr truncated)"
                output = (output + "\n" + err).strip() if output else err
            return output[:10000] if len(output) > 10000 else output
        except subprocess.TimeoutExpired:
            return "ERROR: Command timed out (120s limit)"
        except Exception as e:
            return f"ERROR: {e}"

    elif tool_name == "read_file":
        path = tool_input.get("path", "")
        file_path = Path(project_dir) / path
        try:
            content = file_path.read_text(encoding="utf-8")
            if len(content) > 50000:
                return content[:50000] + "\n\n... (content truncated at 50KB)"
            return content
        except Exception as e:
            return f"ERROR reading file: {e}"

    elif tool_name == "write_file":
        path = tool_input.get("path", "")
        content = tool_input.get("content", "")
        file_path = Path(project_dir) / path
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"File written successfully: {file_path} ({len(content)} chars)"
        except Exception as e:
            return f"ERROR writing file: {e}"

    else:
        return f"ERROR: Unknown tool '{tool_name}'"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3: prepare → Anthropic SDK 并行 QC
# ═══════════════════════════════════════════════════════════════════════════

def _build_qc_pairs(state: QCState) -> list[QCPair]:
    """从映射表中筛选需要 QC 的 pair 列表"""
    # 优先使用已复核版本
    mapping_path = state.get("reviewed_mapping_path") or state["mapping_json_path"]
    with open(mapping_path) as f:
        mapping = json.load(f)

    pairs: list[QCPair] = []
    seq = 0

    for entry in mapping:
        qc_flag = entry.get("是否QC", "是")
        match_method = entry.get("匹配方法", "")

        if not (qc_flag == "是" and match_method in ("关键字匹配", "人工指定")):
            continue

        seq += 1

        # v2.0 格式: 匹配清单列表; v1.0 兼容: 最佳匹配
        match_list_raw = entry.get("匹配清单列表")
        if match_list_raw is None:
            best = entry.get("最佳匹配")
            match_list_raw = [best] if best and best.get("清单名称") else []

        listings: list[ListingRef] = []
        for lst in match_list_raw:
            listings.append(ListingRef(
                listing_number=lst.get("清单编号", 0),
                listing_name=lst.get("清单名称", ""),
                listing_population=lst.get("清单人群", entry.get("表格人群", "FAS")),
            ))

        pairs.append(QCPair(
            pair_id=seq,
            table_number=entry.get("表格编号", seq),
            table_name=entry["表格名称"],
            table_population=entry.get("表格人群", "FAS"),
            listings=listings,
            match_method=match_method,
            should_qc=True,
        ))

    return pairs


def _build_pair_system_prompts(pairs: list[QCPair], state: QCState) -> list[dict]:
    """为每个 QC pair 构建包含 skill 内容的完整 system prompt（替换 deep_agent SkillsMiddleware）"""
    project = state["project_dir"]
    table_dir = state.get("table_excel_dir", os.path.join(project, "表格"))
    listing_dir = state.get("listing_excel_dir", os.path.join(project, "清单"))

    # 读取 pair_qc 的三个文件（对应 deep_agent SkillsMiddleware 行为）
    pair_qc_dir = os.path.abspath(os.path.join(state["skill_dir"], "pair_qc"))
    skill_md_path = os.path.join(pair_qc_dir, "SKILL.md")
    qc_rules_path = os.path.join(pair_qc_dir, "reference", "qc_rules.md")
    template_path = os.path.join(pair_qc_dir, "reference", "subagent_output_template.md")

    def _read_skill_file(path: str, label: str) -> str:
        try:
            with open(path) as f:
                content = f.read()
            # 去掉 YAML front matter（--- ... ---）
            if content.startswith("---"):
                end = content.find("---", 3)
                if end != -1:
                    content = content[end + 3:].strip()
            return content
        except Exception:
            return f"（{label} 文件不可用: {path}）"

    skill_content = _read_skill_file(skill_md_path, "SKILL.md")
    qc_rules_content = _read_skill_file(qc_rules_path, "qc_rules.md")
    template_content = _read_skill_file(template_path, "subagent_output_template.md")

    prompt_specs: list[dict] = []

    for pair in pairs:
        pid = pair["pair_id"]
        table_num = pair["table_number"]

        listing_lines = []
        for lst in pair["listings"]:
            listing_lines.append(
                f"  - 清单编号: {lst['listing_number']}, "
                f"清单名称: {lst['listing_name']}, "
                f"清单人群: {lst['listing_population']}"
            )
        listing_desc = "\n".join(listing_lines) if listing_lines else "（无）"

        # 构建完整 system prompt = Skill 指令 + QC 规则 + 输出模板 + 当前 pair 上下文
        # 注意：报告格式、问题分级、禁止行为、核查步骤等内容由 skill 文件承载，
        # 此处仅补充 pair 特定信息和 Anthropic SDK 工具使用提示
        full_system_prompt = f"""你是临床试验 TFL 反向质控专家。请严格按照以下 Skill 指令完成当前 pair 的核查。

# Skill 指令

{skill_content}

# QC 规则参考

{qc_rules_content}

# 输出模板参考

{template_content}

---

# 当前核查对象

**表格:**
- 名称: {pair['table_name']}
- 人群: {pair['table_population']}
- 表格编号: {table_num}

**参考清单（共 {len(pair['listings'])} 个）:**
{listing_desc}

**Pair 序号:** {pid}
**项目目录:** {project}
**表格目录:** {table_dir}
**清单目录:** {listing_dir}

**报告输出路径:** `{project}/QC结果-Pair{pid:02d}.md`

## 可用工具

你可以使用以下 Anthropic SDK 工具完成任务：
- `bash` — 执行 shell 命令（ls 探索目录、python3 openpyxl 读取 Excel、运行 QC 比对脚本等）
- `read_file` — 读取文件内容（注意：.xlsx 是二进制格式，请用 bash + python3 openpyxl 读取）
- `write_file` — 将最终的完整 QC 报告写入报告输出路径

按照 Skill 指令的 Step 0→1→2→3→4 流程执行。工具执行出错时修正后重试，不要跳过步骤。
"""

        prompt_specs.append({
            "pair": pair,
            "system_prompt": full_system_prompt,
        })

    return prompt_specs


def _run_single_pair_qc(pair_spec: dict, state: QCState) -> tuple[int, str | None]:
    """
    使用 Anthropic SDK 对单个 QC pair 运行完整的 tool-use 循环。

    Args:
        pair_spec: 来自 _build_pair_system_prompts 的规格 {pair, system_prompt}
        state: 全局 QC 状态

    Returns:
        (pair_id, report_path) — report_path 为 None 表示该 pair 未生成报告
    """
    pair: QCPair = pair_spec["pair"]
    system_prompt: str = pair_spec["system_prompt"]
    pid = pair["pair_id"]
    project = state["project_dir"]

    client = _create_anthropic_client(state)
    model = state.get("model", LLM_MODEL)

    # 初始用户消息 — 所有上下文已在 system_prompt 中，此处仅触发执行
    user_prompt = f"请开始对 Pair {pid:02d} 进行反向质控核查，按 Skill 指令逐步执行。"

    messages = [{"role": "user", "content": user_prompt}]
    max_iterations = 30

    for iteration in range(max_iterations):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=system_prompt,
                messages=messages,
                tools=QC_TOOLS,
            )
        except Exception as e:
            print(f"  [Pair {pid:02d}] API 调用失败 (iteration {iteration}): {e}")
            break

        # 检查 stop_reason
        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "max_tokens":
            # 可能还有内容未完成，但强制结束
            break

        # 收集 tool_use blocks 并执行
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = cast(dict, block.input)
                result_text = _execute_tool(tool_name, tool_input, project)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

        if not tool_results:
            # 没有工具调用，但 stop_reason 不是 end_turn — 可能是空响应
            break

        # 追加 assistant 消息（含 tool_use blocks）和 user 消息（含 tool_results）
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # 检查是否生成了报告文件
    report_path = os.path.join(project, f"QC结果-Pair{pid:02d}.md")
    if os.path.exists(report_path):
        return (pid, report_path)
    else:
        print(f"  [Pair {pid:02d}] 未生成报告文件（已迭代 {max_iterations} 轮）")
        return (pid, None)


def phase3_prepare(state: QCState) -> dict:
    """Phase 3 准备：从映射表提取 QC pair 列表，验证前置条件"""
    print("\n" + "=" * 60)
    print("🚀 Phase 3: 准备批量 QC")
    print("=" * 60)

    # Phase 2 Done check
    table_dir = state.get("table_excel_dir", "")
    listing_dir = state.get("listing_excel_dir", "")
    if not table_dir or not listing_dir:
        return {"error_message": "Phase 2 未完成，缺少 表格/ 或 清单/ 目录", "current_phase": "error"}
    if not os.path.isdir(table_dir) or not os.path.isdir(listing_dir):
        return {"error_message": f"Phase 2 目录不存在: {table_dir} / {listing_dir}", "current_phase": "error"}

    pairs = _build_qc_pairs(state)
    if not pairs:
        return {"error_message": "没有找到需要 QC 的 pair（是否QC=是 + 关键字匹配/人工指定）", "current_phase": "error"}

    # 限制 pair 数量（测试用）
    max_pairs = state.get("max_pairs") or 0
    if max_pairs > 0 and len(pairs) > max_pairs:
        print(f"  限制 QC 数量: {max_pairs}/{len(pairs)}（--max-pairs 设定）")
        pairs = pairs[:max_pairs]

    total = len(pairs)
    print(f"  需要 QC 的 pair 总数: {total}")
    print("  各 pair 清单:")
    for p in pairs:
        lst_names = ", ".join(l["listing_name"][:40] for l in p["listings"])
        print(f"    Pair {p['pair_id']:02d}: [{p['match_method']}] {p['table_name'][:60]} → {lst_names}")

    # ── 格式校验 ──
    return {
        "qc_pairs": pairs,
        "total_pairs": total,
        "current_phase": "phase3_ready",
    }


def phase3_run_qc(state: QCState) -> dict:
    """
    Phase 3 核心：使用 Anthropic SDK + ThreadPoolExecutor 并行运行 N 个独立 QC 会话。

    每个 QC pair 通过 _run_single_pair_qc() 独立运行 Anthropic tool-use 循环，
    各 pair 之间通过线程池并行执行，无需中心调度 Agent。

    全部完成后收集 QC结果-Pair*.md 路径。
    """
    print("\n" + "=" * 60)
    print("🤖 Phase 3: Anthropic SDK 并行 QC")
    print("=" * 60)

    pairs = state["qc_pairs"]
    total = state["total_pairs"]
    project = state["project_dir"]
    model = state.get("model", LLM_MODEL)
    api_base = state.get("api_base", LLM_API_BASE)

    # 0. 增量恢复：检查已落盘的 QC结果-Pair*.md，跳过已完成 pair
    project_path = Path(project)
    already_done = {}
    for p in pairs:
        pid = p["pair_id"]
        rp = project_path / f"QC结果-Pair{pid:02d}.md"
        if rp.exists() and rp.stat().st_size > 0:
            already_done[pid] = str(rp)
    if already_done:
        print(f"  ♻️  复用已完成的 {len(already_done)} 个 pair 报告: "
              + ", ".join(f"Pair {pid:02d}" for pid in sorted(already_done)))
        pairs = [p for p in pairs if p["pair_id"] not in already_done]
        if not pairs:
            print("  ✅ 全部 pair 已完成，跳过大模型调用")
            report_files = sorted(
                project_path.glob("QC结果-Pair*.md"),
                key=lambda p: int(p.stem.split("Pair")[-1]) if p.stem.split("Pair")[-1].isdigit() else 0,
            )
            return {
                "pair_report_paths": [str(p) for p in report_files],
                "current_phase": "phase3_done",
            }

    # 1. 构建 system prompt 规格列表
    pair_specs = _build_pair_system_prompts(pairs, state)
    print(f"  构建了 {len(pair_specs)} 个 QC 会话规格（跳过 {len(already_done)} 个已完成）")
    print(f"  使用模型: {model} @ {api_base}")

    # 2. 并行执行
    results: dict[int, str | None] = dict(already_done)
    total_to_run = len(pair_specs)
    if total_to_run > 0:
        max_workers = min(8, total_to_run)
        print(f"  ⏳ 并行启动 {total_to_run} 个 QC 会话 (max_workers={max_workers})...\n")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run_single_pair_qc, spec, state): spec["pair"]["pair_id"]
                for spec in pair_specs
            }
            for future in as_completed(futures):
                pid = futures[future]
                try:
                    pair_id, report_path = future.result()
                    results[pair_id] = report_path
                    status = "✅" if report_path else "❌"
                    print(f"  {status} Pair {pair_id:02d} 完成"
                          + (f" → {os.path.basename(report_path)}" if report_path else " (未生成报告)"))
                except Exception as e:
                    print(f"  ❌ Pair {pid:02d} 异常: {e}")
                    results[pid] = None

    # 3. 收集结果 + 重试机制
    all_pair_ids = set(range(1, total + 1))
    max_retries = state.get("max_retries", 2)
    retry_count = 0

    # 收集第一轮已完成的报告
    report_paths = [rp for rp in results.values() if rp is not None]
    found_ids = {pid for pid, rp in results.items() if rp is not None}
    missing_ids = all_pair_ids - found_ids

    print(f"\n  第一轮收集: {len(report_paths)}/{total} 个报告文件")
    if missing_ids:
        print(f"  ⚠️ 缺失: Pair {sorted(missing_ids)}")

    # 重试循环
    while missing_ids and retry_count < max_retries:
        retry_count += 1
        print(f"\n  🔄 第 {retry_count}/{max_retries} 次重试: {len(missing_ids)} 对缺失")

        retry_pairs = [p for p in pairs if p["pair_id"] in missing_ids]
        retry_specs = _build_pair_system_prompts(retry_pairs, state)

        retry_workers = min(4, len(missing_ids))
        with ThreadPoolExecutor(max_workers=retry_workers) as executor:
            retry_futures = {
                executor.submit(_run_single_pair_qc, spec, state): spec["pair"]["pair_id"]
                for spec in retry_specs
            }
            for future in as_completed(retry_futures):
                pid = retry_futures[future]
                try:
                    pair_id, report_path = future.result()
                    if report_path:
                        results[pair_id] = report_path
                        report_paths.append(report_path)
                        print(f"  ✅ Pair {pair_id:02d} 重试成功")
                    else:
                        print(f"  ❌ Pair {pair_id:02d} 重试仍失败")
                except Exception as e:
                    print(f"  ❌ Pair {pid:02d} 重试异常: {e}")

        found_ids = {pid for pid, rp in results.items() if rp is not None}
        missing_ids = all_pair_ids - found_ids

    if missing_ids:
        print(f"\n  ⚠️ 最终缺失: Pair {sorted(missing_ids)}（已达最大重试次数 {max_retries}）")

    # 最终收集
    report_files = sorted(
        project_path.glob("QC结果-Pair*.md"),
        key=lambda p: int(p.stem.split("Pair")[-1]) if p.stem.split("Pair")[-1].isdigit() else 0,
    )

    found = len(report_files)
    print(f"\n  最终收集: {found}/{total} 个报告文件")

    # 快速统计各 pair 结论
    conclusions: dict[str, int] = {}
    for rf in report_files:
        try:
            with open(rf) as f:
                for line in f:
                    if line.startswith("##META_CONCLUSION:"):
                        grade = line.split(":", 1)[1].strip()
                        conclusions[grade] = conclusions.get(grade, 0) + 1
                        break
        except Exception:
            pass
    if conclusions:
        print(f"  结论统计: {conclusions}")

    print("✅ Phase 3 完成")

    return {
        "pair_report_paths": [str(p) for p in report_files],
        "current_phase": "phase3_done",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4: 合并报告
# ═══════════════════════════════════════════════════════════════════════════

def phase4_merge(state: QCState) -> dict:
    """
    合并所有 QC结果-Pair{N}.md 为两份汇总报告:
      - QC结果-全部合并.md (完整详情)
      - QC报告-汇总.md (带封面汇总)
    """
    print("\n" + "=" * 60)
    print("📝 Phase 4: 合并报告")
    print("=" * 60)

    project = state["project_dir"]
    skill = state["skill_dir"]
    merge_script = os.path.join(skill, "merge_qc.py")

    if not os.path.exists(merge_script):
        print("  ⚠️ merge_qc.py 不存在，生成简单合并")
        # 简易合并逻辑
        return _simple_merge(state)

    # 生成完整详情报告
    result = _run_script(merge_script, [project], cwd=project)
    detail_path = os.path.join(project, "QC结果-全部合并.md")

    # 生成带封面汇总
    summary_path = os.path.join(project, "QC报告-汇总.md")
    _run_script(merge_script, [project, summary_path], cwd=project)

    print("✅ Phase 4 完成")
    return {
        "merged_detail_path": detail_path,
        "merged_summary_path": summary_path,
        "current_phase": "phase4_done",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4b: 生成交互式 HTML 报告
# ═══════════════════════════════════════════════════════════════════════════

def phase4b_build_viewer(state: QCState) -> dict:
    """
    调用 build_qc_viewer.py 生成 qc-viewer.html 交互式浏览报告。

    输入: QC报告-汇总.md + 表格附件.docx + 表格-清单-映射表.json
    输出: qc-viewer.html (带封面、左右分栏、悬停预览)
    """
    print("\n" + "=" * 60)
    print("🌐 Phase 4b: 生成交互式 HTML 报告")
    print("=" * 60)

    project = state["project_dir"]
    skill = state["skill_dir"]
    table_input = state["table_input"]
    summary_path = state.get("merged_summary_path") or os.path.join(project, "QC报告-汇总.md")
    mapping_path = state.get("reviewed_mapping_path") or state["mapping_json_path"]

    # 定位 build_qc_viewer.py（与本脚本同目录）
    build_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_qc_viewer.py")
    if not os.path.exists(build_script):
        print("  ⚠️ build_qc_viewer.py 不存在，跳过 HTML 报告生成")
        return {"current_phase": "phase4b_done"}

    output_html = os.path.join(project, "qc-viewer.html")

    cmd_args = [
        "--docx", table_input,
        "--md", summary_path,
        "--mapping", mapping_path,
        "--output", output_html,
    ]

    result = _run_script(build_script, cmd_args, cwd=project)

    if result.returncode != 0 or not os.path.exists(output_html):
        print("  ⚠️ HTML 报告生成失败，继续后续步骤")
        return {"current_phase": "phase4b_done"}

    size_kb = os.path.getsize(output_html) / 1024
    print(f"  📄 qc-viewer.html ({size_kb:.0f} KB)")
    print("✅ Phase 4b 完成")

    return {
        "viewer_html_path": output_html,
        "current_phase": "phase4b_done",
    }


def _simple_merge(state: QCState) -> dict:
    """简易合并（merge_qc.py 不可用时的 fallback）"""
    project = state["project_dir"]
    detail_path = os.path.join(project, "QC结果-全部合并.md")

    report_files = sorted(
        Path(project).glob("QC结果-Pair*.md"),
        key=lambda p: int(p.stem.split("Pair")[-1]) if p.stem.split("Pair")[-1].isdigit() else 0,
    )

    lines = [
        "# TFL 反向质控核查报告",
        "",
        f"**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Pair 总数:** {len(report_files)}",
        "",
    ]

    # 提取各 pair 结论做统计
    stats: dict[str, int] = {}
    for rf in report_files:
        grade = "UNKNOWN"
        try:
            with open(rf) as f:
                for line in f:
                    if line.startswith("##META_CONCLUSION:"):
                        grade = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass
        stats[grade] = stats.get(grade, 0) + 1

    lines.extend([
        "## 核查概览",
        "",
        "| 级别 | 数量 |",
        "|------|------|",
    ])
    for grade in ["PASS", "MAJOR", "MINOR", "SUGGESTION", "PENDING"]:
        count = stats.get(grade, 0)
        lines.append(f"| {grade} | {count} |")
    lines.append("")

    # 拼接各 pair 报告
    for rf in report_files:
        pair_name = rf.stem
        lines.extend([
            "---",
            f"## {pair_name}",
            "",
        ])
        try:
            with open(rf) as f:
                content = f.read()
            # 元数据行保留，正文标题降一级
            for line in content.split("\n"):
                if line.startswith("##META_"):
                    lines.append(line)
                elif line.startswith("### "):
                    lines.append(f"#{line}")
                else:
                    lines.append(line)
        except Exception as e:
            lines.append(f"*读取失败: {e}*")
        lines.append("")

    with open(detail_path, "w") as f:
        f.write("\n".join(lines))

    summary_path = os.path.join(project, "QC报告-汇总.md")
    # 简易版的汇总报告和详情报告内容相同
    with open(summary_path, "w") as f:
        f.write("\n".join(lines))

    return {
        "merged_detail_path": detail_path,
        "merged_summary_path": summary_path,
        "current_phase": "done",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5: 清理（可选）
# ═══════════════════════════════════════════════════════════════════════════

def phase5_cleanup(state: QCState) -> dict:
    """删除中间文件，只保留原始输入和最终报告"""
    print("\n" + "=" * 60)
    print("🧹 Phase 5: 清理中间文件")
    print("=" * 60)

    project = state["project_dir"]
    skill = state["skill_dir"]
    cleanup_script = os.path.join(skill, "cleanup_qc.py")

    if os.path.exists(cleanup_script):
        _run_script(cleanup_script, [project, "--yes"], cwd=project)
    else:
        print("  cleanup_qc.py 不存在，跳过清理")
        print("  手动清理建议: 删除 表格/ 清单/ 映射复核.html QC结果-Pair*.md 表格-清单-映射表.json")

    print("✅ Phase 5 完成")
    print("\n" + "=" * 60)
    print("🎉 QC 管线全部完成!")
    print(f"📂 最终产出: {project}")
    if state.get("merged_summary_path"):
        print(f"   📝 {state['merged_summary_path']}")
    if state.get("merged_detail_path"):
        print(f"   📝 {state['merged_detail_path']}")
    if state.get("viewer_html_path"):
        print(f"   🌐 {state['viewer_html_path']} (交互式浏览)")
    print("=" * 60)

    return {"current_phase": "finished"}


# ═══════════════════════════════════════════════════════════════════════════
# 组装 LangGraph 管线
# ═══════════════════════════════════════════════════════════════════════════

def _after_phase1(state: QCState) -> str:
    """Phase 1 (提取) 之后的路由"""
    if state.get("error_message"):
        return "error_end"
    return "phase2"


def _after_phase2(state: QCState) -> str:
    """Phase 2 (匹配) 之后的路由"""
    if state.get("error_message"):
        return "error_end"
    if state.get("skip_review"):
        return "phase3_prepare"
    # 未跳过复核 → 进入人工复核
    return "phase2b"


def _after_phase2b(state: QCState) -> str:
    """Phase 2b (复核) 之后的路由"""
    if state.get("error_message"):
        return "error_end"
    return "phase3_prepare"


def _after_phase3_prepare(state: QCState) -> str:
    """Phase 3 准备之后的路由"""
    if state.get("error_message"):
        return "error_end"
    return "phase3"


def _after_phase3(state: QCState) -> str:
    """Phase 3 (run_qc) 之后的路由 — 检查是否有报告生成"""
    reports = state.get("pair_report_paths", [])
    if not reports:
        return "error_end"
    total = state.get("total_pairs", 0)
    if len(reports) < total:
        print(f"  ⚠️ Phase 3 部分完成: {len(reports)}/{total} 个报告")
    return "phase4"


def _after_phase4(state: QCState) -> str:
    """Phase 4 之后的路由"""
    if state.get("error_message"):
        return "error_end"
    return "phase4b"


def _after_phase4b(state: QCState) -> str:
    """Phase 4b 之后的路由"""
    # 不管 HTML 生成是否成功，都继续（失败时有 warning 可忽略）
    return "phase5"


def build_qc_workflow(
    enable_cleanup: bool = True,
    enable_checkpoint: bool = True,
) -> StateGraph:
    """
    构建完整 QC 工作流。

    Args:
        enable_cleanup: 是否包含 Phase 5 清理节点
        enable_checkpoint: 是否启用 MemorySaver (支持 interrupt + 恢复)
    """
    builder = StateGraph(QCState)

    # 注册节点
    builder.add_node("phase1_extract", phase1_extract)
    builder.add_node("phase2_match", phase2_match)
    builder.add_node("phase2b_review", phase1b_review)
    builder.add_node("phase3_prepare", phase3_prepare)
    builder.add_node("phase3_run_qc", phase3_run_qc)
    builder.add_node("phase4_merge", phase4_merge)
    builder.add_node("phase4b_build_viewer", phase4b_build_viewer)
    if enable_cleanup:
        builder.add_node("phase5_cleanup", phase5_cleanup)

    # 条件边: Phase 1 → Phase 2
    builder.add_conditional_edges(
        "phase1_extract",
        _after_phase1,
        {
            "phase2": "phase2_match",
            "error_end": END,
        },
    )

    # Phase 2 → 2b 或 3
    builder.add_conditional_edges(
        "phase2_match",
        _after_phase2,
        {
            "phase2b": "phase2b_review",
            "phase3_prepare": "phase3_prepare",
            "error_end": END,
        },
    )

    # Phase 2b → Phase 3
    builder.add_conditional_edges(
        "phase2b_review",
        _after_phase2b,
        {
            "phase3_prepare": "phase3_prepare",
            "error_end": END,
        },
    )

    # Phase 3 prepare → Phase 3 run_qc
    builder.add_conditional_edges(
        "phase3_prepare",
        _after_phase3_prepare,
        {
            "phase3": "phase3_run_qc",
            "error_end": END,
        },
    )

    # Phase 3 → Phase 4（条件路由 — 检查是否有报告生成）
    builder.add_conditional_edges(
        "phase3_run_qc",
        _after_phase3,
        {
            "phase4": "phase4_merge",
            "error_end": END,
        },
    )

    # Phase 4 → Phase 4b → Phase 5 (or END)
    builder.add_conditional_edges(
        "phase4_merge",
        _after_phase4,
        {"phase4b": "phase4b_build_viewer", "error_end": END},
    )
    if enable_cleanup:
        builder.add_conditional_edges(
            "phase4b_build_viewer",
            _after_phase4b,
            {"phase5": "phase5_cleanup", "error_end": END},
        )
        builder.add_edge("phase5_cleanup", END)
    else:
        builder.add_edge("phase4b_build_viewer", END)

    # 入口
    builder.set_entry_point("phase1_extract")

    # Checkpointer（支持 interrupt + 恢复）
    checkpointer = MemorySaver() if enable_checkpoint else None
    return builder.compile(checkpointer=checkpointer)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="TFL Cross-Validation QC — 临床试验表格-清单反向质控管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --api-key sk-xxx --table 表格.docx --listing 清单.docx --project ./project_001
  %(prog)s --api-key sk-xxx --table 表格.pdf --listing 清单.pdf --project ./project_001 --skip-review
  %(prog)s --api-key sk-xxx --table 表格.docx --listing 清单.docx --project ./project_001 --no-cleanup

默认 API 配置（与 ~/.claude/settings.json 对齐）:
  --api-base https://api.deepseek.com/anthropic
  --model   deepseek-v4-pro
        """,
    )
    parser.add_argument("--table", required=True,
                        help="表格附件路径 (.docx 或 .pdf)")
    parser.add_argument("--listing", required=True,
                        help="清单附件路径 (.docx 或 .pdf)")
    parser.add_argument("--project", default=".",
                        help="项目工作目录（所有中间和最终产出存放于此，默认当前目录）")
    parser.add_argument("--api-key", default=LLM_API_KEY,
                        help="API key。DeepSeek: sk-xxx。也可设置环境变量 ANTHROPIC_AUTH_TOKEN")
    parser.add_argument("--api-base", default=LLM_API_BASE,
                        help="API base URL（默认 DeepSeek Anthropic 兼容端点，与 Claude Code 全局配置对齐）")
    parser.add_argument("--model", default=LLM_MODEL,
                        help="模型名（默认 deepseek-v4-pro）")
    parser.add_argument("--skill-dir", default=None,
                        help="skill 资源目录（默认自动检测）")
    parser.add_argument("--skip-review", action="store_true",
                        help="跳过 Phase 1b 人工复核")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="不执行 Phase 5 清理，保留所有中间文件")
    parser.add_argument("--max-pairs", type=int, default=None,
                        help="最多 QC 的 pair 数量（默认全部，测试时建议设 5-10）")
    parser.add_argument("--max-retries", type=int, default=2,
                        help="缺失 pair 的最大重试次数（默认2）")
    parser.add_argument("--no-checkpoint", action="store_true",
                        help="禁用 checkpoint（也禁用 interrupt 暂停恢复能力）")
    args = parser.parse_args()

    # 验证输入
    if not os.path.exists(args.table):
        print(f"❌ 表格文件不存在: {args.table}")
        sys.exit(1)
    if not os.path.exists(args.listing):
        print(f"❌ 清单文件不存在: {args.listing}")
        sys.exit(1)

    # 创建项目目录
    project_dir = os.path.abspath(args.project)
    os.makedirs(project_dir, exist_ok=True)

    # 解析 skill 目录
    skill_dir = args.skill_dir or _resolve_skill_dir()
    if not os.path.isdir(skill_dir):
        print(f"❌ Skill 目录不存在: {skill_dir}")
        sys.exit(1)

    # 初始状态
    initial_state: QCState = {
        "table_input": os.path.abspath(args.table),
        "listing_input": os.path.abspath(args.listing),
        "project_dir": project_dir,
        "skill_dir": skill_dir,
        "model": args.model,
        "api_key": args.api_key or "",
        "api_base": args.api_base,
        "skip_review": args.skip_review,
        "max_pairs": args.max_pairs or 0,
        "max_retries": args.max_retries,
        "pair_report_paths": [],
        "current_phase": "init",
        "error_message": "",
    }

    # 构建并运行
    workflow = build_qc_workflow(
        enable_cleanup=not args.no_cleanup,
        enable_checkpoint=not args.no_checkpoint,
    )

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  TFL Cross-Validation QC — 临床试验表格-清单反向质控       ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  表格: {args.table}")
    print(f"║  清单: {args.listing}")
    print(f"║  项目: {project_dir}")
    print(f"║  端点: {args.api_base}")
    print(f"║  模型: {args.model}")
    print(f"║  复核: {'跳过' if args.skip_review else '按需暂停'}")
    print(f"║  清理: {'保留中间文件' if args.no_cleanup else '自动清理'}")
    print("╚══════════════════════════════════════════════════════════════╝")

    # 流式执行，同时收集最终状态
    config = {"configurable": {"thread_id": os.path.basename(project_dir)}}
    try:
        for event in workflow.stream(initial_state, config):
            node_name = list(event.keys())[0]
            # 合并节点返回的状态差量到 initial_state（否则结束后无法判断完成/出错）
            if isinstance(event[node_name], dict):
                initial_state.update(event[node_name])
            if node_name in ("__interrupt__",):
                interrupt_data = event["__interrupt__"]
                print(f"\n⏸️  管线已暂停，等待人工操作:")
                for item in interrupt_data:
                    print(f"    {item.value}")
                print("\n操作完成后，重新运行相同命令即可从断点恢复。")
                break
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断。可通过相同命令恢复（checkpointer 已保存状态）。")
        sys.exit(130)

    # 检查是否全部完成
    final_phase = initial_state.get("current_phase", "")
    if final_phase == "finished":
        print("\n✅ 全部完成!")
    elif final_phase == "error":
        print(f"\n❌ 管线出错: {initial_state.get('error_message', '未知错误')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
