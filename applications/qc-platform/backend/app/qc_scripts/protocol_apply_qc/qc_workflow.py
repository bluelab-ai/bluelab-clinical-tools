"""
比对基准 vs 表格文件 一致性质控 — LangGraph 工作流
====================================================

完整管线：
  Node 1: 提取方案要素 → 结构化 JSON（带重试验证）
  Node 2: 提取表格 DOCX → Excel 文件 + 标题索引 JSON
  Node 3: 匹配表格索引到方案 JSON 的「表格」字段
  Node 4: 并行 Agent QC → 条目覆盖 + 统计方法 + 脚注
  Node 5: 汇总报告

运行:
    python qc_workflow.py \\
        --api-key sk-xxx \\
        --protocol 方案.docx \\
        --tables 表格.docx \\
        --project /path/to/project

依赖:
    pip install langgraph openpyxl anthropic python-docx
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict, cast

_sys_path_add = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
if _sys_path_add not in sys.path:
    sys.path.insert(0, _sys_path_add)
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL

import anthropic
import operator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver


# ═══════════════════════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent  # 本包目录，所有脚本在同一文件夹

EXTRACT_PROTOCOL_SCRIPT = SCRIPT_DIR / "统计分析提取_一体化.py"
MATCH_TABLES_SCRIPT   = SCRIPT_DIR / "表格匹配.py"
EXTRACT_TABLES_SCRIPT = SCRIPT_DIR / "extract_tables.py"

# ═══════════════════════════════════════════════════════════════════════════
# 参数配置
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class WorkflowConfig:
    """运行时配置"""
    protocol_path: str = ""          # 方案 docx 路径
    tables_path: str = ""            # 表格 docx 路径
    project_dir: str = ""           # 项目工作目录
    model: str = LLM_MODEL
    api_key: str = ""
    api_base: str = LLM_API_BASE
    max_retries: int = 2            # 提取失败重试次数
    max_qc_iterations: int = 25     # QC Agent 单板块最大迭代


# ═══════════════════════════════════════════════════════════════════════════
# 全局 State
# ═══════════════════════════════════════════════════════════════════════════

class QCWorkflowState(TypedDict, total=False):
    """贯穿全部节点的全局状态"""

    # ── 输入 ──
    config: WorkflowConfig

    # ── Node 1: 方案提取 ──
    protocol_json_path: str         # 方案提取产出的 JSON 路径
    protocol_extraction_attempts: int  # 提取尝试次数

    # ── Node 2: 表格提取 ──
    tables_index_path: str          # 表格-标题索引.json 路径（供匹配消费）
    tables_output_dir: str          # Excel 提取目录

    # ── Node 3: 表格匹配 ──
    matched_json_path: str          # 匹配后 JSON（含表格字段）路径

    # ── Node 4: 并行 Agent QC ──
    qc_section_results: list[dict]  # 各板块 Agent 的结构化发现
    qc_report_path: str             # 最终 QC 报告
    viewer_html_path: str           # 交互式 HTML 报告

    # ── 控制 ──
    current_node: str
    error_message: str
    retry_count: int                # 通用重试计数


# ═══════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════

def _run_script(script_path: str, args: list[str], cwd: str | None = None,
                timeout: int = 600) -> subprocess.CompletedProcess:
    """运行 Python 脚本"""
    cmd = [sys.executable, script_path] + args
    print(f"  → {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        out = result.stdout.strip()
        print(f"  stdout: {out[:1500]}{'...(截断)' if len(out) > 1500 else ''}")
    if result.stderr:
        err = result.stderr.strip()
        print(f"  stderr: {err[:800]}{'...(截断)' if len(err) > 800 else ''}")
    return result


def _find_latest_json(directory: str, pattern: str = "*.json") -> str:
    """在目录中找最新的 JSON 文件"""
    files = sorted(Path(directory).glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    return str(files[0]) if files else ""


def _create_anthropic_client(api_key: str, api_base: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, base_url=api_base, timeout=180, max_retries=3)


# ═══════════════════════════════════════════════════════════════════════════
# Node 1: 提取方案要素
# ═══════════════════════════════════════════════════════════════════════════

def node_extract_protocol(state: QCWorkflowState) -> dict:
    """运行 统计分析提取_一体化.py 从方案 docx 提取结构化 JSON"""
    print("\n" + "=" * 60)
    print("📋 Node 1: 提取方案统计分析要素")
    print("=" * 60)

    cfg = state["config"]
    protocol_path = cfg.protocol_path
    project_dir = cfg.project_dir
    out_dir = os.path.join(project_dir, "方案输出")
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(protocol_path):
        return {"error_message": f"方案文件不存在: {protocol_path}"}

    attempts = state.get("protocol_extraction_attempts", 0) + 1

    result = _run_script(
        str(EXTRACT_PROTOCOL_SCRIPT),
        ["--file", protocol_path, "--out-dir", out_dir],
        timeout=900,
    )

    if result.returncode != 0:
        print(f"  ❌ 提取失败 (第 {attempts} 次)")
        err_detail = (result.stderr or result.stdout or "").strip()
        return {
            "protocol_extraction_attempts": attempts,
            "error_message": f"方案提取返回非零: {err_detail[:500]}",
        }

    json_path = _find_latest_json(out_dir, "*统计分析*.json")
    if not json_path:
        json_path = _find_latest_json(out_dir, "*.json")

    if not json_path:
        print(f"  ❌ 未找到产出 JSON (第 {attempts} 次)")
        # 把脚本输出的最后部分当作错误参考
        err_hint = (result.stderr or result.stdout or "").strip()
        if err_hint:
            # 提取关键错误信息（取最后 300 字符）
            err_hint = err_hint[-500:]
        hint = f"\n脚本输出参考: ...{err_hint}" if err_hint else ""
        return {
            "protocol_extraction_attempts": attempts,
            "error_message": f"方案提取后未生成 JSON 文件{hint}",
        }

    size = os.path.getsize(json_path)
    print(f"  ✅ 方案 JSON: {json_path} ({size:,} bytes)")
    return {
        "protocol_json_path": json_path,
        "protocol_extraction_attempts": attempts,
        "error_message": "",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Node 1b: 验证方案提取结果
# ═══════════════════════════════════════════════════════════════════════════

def node_validate_protocol(state: QCWorkflowState) -> dict:
    """验证方案 JSON 是否完整——包含必要的分析板块"""
    print("\n" + "=" * 60)
    print("🔍 Node 1b: 验证方案提取结果")
    print("=" * 60)

    json_path = state.get("protocol_json_path", "")
    if not json_path or not os.path.exists(json_path):
        return {"error_message": "方案 JSON 不存在，无法验证"}

    with open(json_path) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            return {"error_message": f"方案 JSON 解析失败: {e}"}

    sap = data.get("统计分析计划", data)
    required_sections = ["主要终点分析", "次要终点分析", "安全性分析"]
    found = [s for s in required_sections if s in sap]
    missing = [s for s in required_sections if s not in sap]

    # 检查板块是否有 "表格" 字段
    has_tables = any(
        isinstance(sap.get(s), dict) and sap[s].get("表格")
        for s in found
    )

    print(f"  找到分析板块: {found}")
    if missing:
        print(f"  ⚠️ 缺少板块: {missing}")
    print(f"  含表格字段: {'是' if has_tables else '否'}")

    # 当前阶段只要求有核心板块存在即可（表格字段在 Node 2 填充）
    if len(found) < 2:
        print(f"  ❌ 核心板块不足，需重试")
        return {"error_message": "方案 JSON 缺少核心分析板块"}

    print("  ✅ 验证通过")
    return {"error_message": ""}


# ═══════════════════════════════════════════════════════════════════════════
# 条件边: 提取成功后继续 / 失败后重试或终止
# ═══════════════════════════════════════════════════════════════════════════

def should_retry_extraction(state: QCWorkflowState) -> str:
    """判断提取是否有错误、是否需要重试"""
    error = state.get("error_message", "")
    max_retries = state["config"].max_retries
    attempts = state.get("protocol_extraction_attempts", 0)

    if not error:
        return "continue"

    if attempts < max_retries:
        print(f"\n  🔄 重试提取 ({attempts}/{max_retries})...")
        return "retry"
    else:
        print(f"\n  ❌ 已达最大重试次数 ({max_retries})")
        return "error_end"


def should_retry_validation(state: QCWorkflowState) -> str:
    """验证失败后的重试判断"""
    error = state.get("error_message", "")
    max_retries = state["config"].max_retries
    attempts = state.get("protocol_extraction_attempts", 0)

    if not error:
        return "continue"

    if attempts < max_retries:
        print(f"\n  🔄 验证失败，返回重试提取 ({attempts}/{max_retries})...")
        return "retry_extract"
    else:
        print(f"\n  ❌ 已达最大重试，终止")
        return "error_end"


# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# Node 3: 匹配表格到方案 JSON
# ═══════════════════════════════════════════════════════════════════════════

def node_extract_and_match_tables(state: QCWorkflowState) -> dict:
    """使用 extract_tables 产出的 表格-标题索引.json 匹配到方案 JSON 的「表格」字段"""
    print("\n" + "=" * 60)
    print("📊 Node 3: 匹配表格 → 方案 JSON")
    print("=" * 60)

    cfg = state["config"]
    project_dir = cfg.project_dir
    protocol_json = state.get("protocol_json_path", "")
    index_path = state.get("tables_index_path", "")

    out_dir = os.path.join(project_dir, "表格输出")
    os.makedirs(out_dir, exist_ok=True)

    if not index_path or not os.path.exists(index_path):
        return {"error_message": f"表格索引 JSON 不存在: {index_path}"}

    print(f"  📑 表格索引: {index_path}")

    # Step 3: 匹配表格到 JSON
    print("  匹配表格到方案 JSON...")
    matched_path = os.path.join(out_dir, "比对基准.json")

    _run_script(
        str(MATCH_TABLES_SCRIPT),
        ["-s", protocol_json, "-t", index_path],
        timeout=600,
    )

    # 表格匹配.py 可能直接修改了 JSON 或生成了新文件
    if os.path.exists(matched_path):
        print(f"  ✅ 匹配后 JSON: {matched_path}")
    else:
        # 去找匹配脚本的默认输出
        found = _find_latest_json(out_dir, "*匹配*.json") or _find_latest_json(out_dir, "*.json")
        if found and found != protocol_json:
            shutil.copy(found, matched_path)
            print(f"  ✅ 匹配后 JSON（复制）: {matched_path}")
        else:
            # 没有专用匹配输出，直接用原 JSON（可能已经被匹配脚本原位更新了）
            matched_path = protocol_json
            print(f"  ⚠️ 未找到匹配专用输出，使用原 JSON: {matched_path}")

    return {
        "matched_json_path": matched_path,
        "error_message": "",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Node 2: 提取表格 DOCX → Excel
# ═══════════════════════════════════════════════════════════════════════════

def node_extract_tables(state: QCWorkflowState) -> dict:
    """运行 extract_tables.py 从表格 DOCX 提取所有表格为 Excel"""
    print("\n" + "=" * 60)
    print("📑 Node 3: 提取表格 DOCX → Excel")
    print("=" * 60)

    cfg = state["config"]
    project_dir = cfg.project_dir
    tables_docx = cfg.tables_path
    out_dir = os.path.join(project_dir, "tables_output")

    if os.path.isdir(out_dir):
        for f in os.listdir(out_dir):
            if f.endswith(".xlsx"):
                os.unlink(os.path.join(out_dir, f))
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(tables_docx):
        return {"error_message": f"表格 DOCX 不存在: {tables_docx}"}

    result = _run_script(
        str(EXTRACT_TABLES_SCRIPT),
        [tables_docx, "--out", out_dir],
        timeout=300,
    )

    if result.returncode != 0:
        return {"error_message": f"表格提取失败: {result.stderr[:500]}"}

    xlsx_count = len(list(Path(out_dir).glob("*.xlsx")))
    if xlsx_count == 0:
        return {"error_message": "未提取到任何表格"}

    # 确定索引 JSON 路径
    index_path = os.path.join(out_dir, "表格-标题索引.json")
    if not os.path.exists(index_path):
        index_path = os.path.join(out_dir, "清单-标题索引.json")

    print(f"  ✅ 提取 {xlsx_count} 张表格 → {out_dir}")
    return {
        "tables_index_path": index_path,
        "tables_output_dir": out_dir,
        "error_message": "",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Node 4: 并行 Agent QC（复用 qc_baseline_vs_tables.py 的核心逻辑）
# ═══════════════════════════════════════════════════════════════════════════

# Agent 工具定义
AGENT_TOOLS: list[dict] = [
    {
        "name": "bash",
        "description": (
            "执行 Shell 命令，返回 stdout 和 stderr。"
            "工作目录已设为表格目录，可用的基础环境: openpyxl, python3。"
            "适用场景: 列出文件(ls)、查看文件行数(wc -l)、"
            "快速检查文件是否存在、用 openpyxl 读取 Excel 等。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 Shell 命令"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "python",
        "description": (
            "执行一段 Python 脚本，返回 stdout 和 stderr。"
            "已预装 openpyxl，表格目录路径可通过环境变量 TABLES_DIR 获取。"
            "适用场景: 逐表读取数据、对比分析、统计计算等复杂质控逻辑。"
            "建议先 ls 了解文件名，再写 Python 逐表核查。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python 代码（可多行）"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "report_section_findings",
        "description": "提交本板块的核查发现（结构化 JSON），必须在本板块全部核查完成后调用一次。",
        "input_schema": {
            "type": "object",
            "properties": {
                "findings_json": {
                    "type": "string",
                    "description": (
                        "JSON 字符串。格式: "
                        '{"section":"板块名","coverage":[...],"method_issues":[...],'
                        '"label_issues":[...],"footnote_issues":[...],'
                        '"n_values":{},"numeric_issues":[...],'
                        '"narrative":"总体描述"}'
                    ),
                },
            },
            "required": ["findings_json"],
        },
    },
]


@dataclass
class SectionConfig:
    """一个分析板块的配置"""
    name: str
    population: str
    items: list[str] = field(default_factory=list)
    table_ids: list[str] = field(default_factory=list)
    table_files: dict[str, str] = field(default_factory=dict)


def _parse_sections_from_json(json_path: str, tables_dir: str) -> list[SectionConfig]:
    """从 JSON 中解析分析板块配置，同时预匹配表格文件名。

    映射策略:
      表格-标题索引.json 与 xlsx 文件由 extract_tables.py 在同一循环中生成，
      序号天然对齐 —— index[0] ↔ 01-*.xlsx, index[1] ↔ 02-*.xlsx, ...
      直接用序号建立 num → filename 映射，无需正则或标题模糊匹配。
    """
    with open(json_path) as f:
        data = json.load(f)

    sap = data.get("统计分析计划", data)
    tp = Path(tables_dir)

    # ── 步骤1: 读 表格-标题索引.json，按序号建立 num → seq ──
    #          extract_tables.py 保证 index_data[i] ↔ {i+1:02d}-*.xlsx
    num_to_seq: dict[str, int] = {}
    index_path = tp / "表格-标题索引.json"
    if index_path.exists():
        with open(index_path) as f:
            index_data = json.load(f)
        for i, entry in enumerate(index_data):
            n = entry.get("num", "")
            if n:
                num_to_seq[n] = i + 1  # seq 从 1 开始

    # ── 步骤2: 建立 seq → filename（按序号排序 xlsx 文件）──
    xlsx_files = sorted(tp.glob("*.xlsx")) if tp.is_dir() else []
    seq_to_file: dict[int, str] = {}
    for xf in xlsx_files:
        m = re.match(r'^(\d{2,3})-', xf.name)
        if m:
            seq_to_file[int(m.group(1))] = xf.name

    # ── 步骤3: num → seq → filename ──
    table_files: dict[str, str] = {}
    for num, seq in num_to_seq.items():
        if seq in seq_to_file:
            table_files[num] = seq_to_file[seq]

    section_keys = [
        "受试者分布分析", "人口学与基线特征分析",
        "主要终点分析", "次要终点分析", "安全性分析",
    ]

    # ── 提取缺失数据处理（数组结构，不生成板块Agent，而是注入到其他板块prompt）──
    missing_data_info: str = ""
    md_items = sap.get("缺失数据处理")
    if isinstance(md_items, list) and md_items:
        lines = []
        for d in md_items:
            if isinstance(d, dict) and d.get("处理方法"):
                scope = d.get("适用范围", "未指定")
                method = d.get("处理方法", "")
                lines.append(f"  - 适用范围：{scope}；处理方法：{method}")
        if lines:
            missing_data_info = "\n".join(lines)

    configs = []
    for key in section_keys:
        if key not in sap:
            continue
        section = sap[key]

        if not isinstance(section, dict):
            continue

        # 匹配多种编号格式：\d+.\d+... 或 \d+-\d+...
        table_ids = re.findall(r'(\d+(?:[\.\-]\d+)+)', section.get("表格", ""))

        matched_files = {}
        seen: set[str] = set()
        for tid in table_ids:
            if tid in table_files and tid not in seen:
                matched_files[tid] = table_files[tid]
                seen.add(tid)

        items = section.get("条目", [])
        if isinstance(items, str):
            items = [items]

        configs.append(SectionConfig(
            name=key,
            population=section.get("分析人群", ""),
            items=items,
            table_ids=table_ids,
            table_files=matched_files,
        ))

    return configs, missing_data_info


def _build_agent_prompt(cfg: SectionConfig, global_info: dict, tables_dir: str,
                        missing_data_info: str = "") -> str:
    """为一个板块构建精简的 system prompt"""
    pops = global_info.get("分析人群", {})
    pop_text = "\n".join([f"  - {k}: {v}" for k, v in pops.items()])

    principles = global_info.get("统计通用原则", [])
    principles_text = "\n".join([f"  {i}. {p}" for i, p in enumerate(principles, 1)])

    table_list = "\n".join([
        f"  表{tid} → 文件 {fname}" for tid, fname in cfg.table_files.items()
    ]) if cfg.table_files else "  （无预匹配文件）"

    items_text = "\n".join([f"  {i}. {item}" for i, item in enumerate(cfg.items, 1)])

    special = ""
    if "主要终点" in cfg.name:
        special = "重点: 协方差模型(ANCOVA)、LSmeans/95%CI、缺失值处理方法、α水平"
    elif "次要终点" in cfg.name:
        special = "重点: FAS/PPS配对一致性、各终点全覆盖、分析方法层级一致"
    elif "安全性" in cfg.name:
        special = "重点: 描述性统计层级、SOC-PT层级、SS分析集用法"

    # ── 缺失数据处理（贯穿性，注入到各板块prompt供对照）──
    md_block = ""
    if missing_data_info:
        md_block = f"""## 缺失值处理方法（方案声明，供对照用）
{missing_data_info}
"""

    return f"""你是临床试验统计质控专家。请核查本分析板块。

## 板块: {cfg.name}  |  声明人群: {cfg.population}

## 分析人群定义
{pop_text}

## 统计通用原则
{principles_text}

## 本板块条目（方案预设的分析）
{items_text if items_text else '（无条目）'}

## 表格编号→文件名 映射
{table_list}
{md_block}
{special}

## 核查维度
1. 条目→表格覆盖: ✅/⚠/❌（区分主要/亚组/敏感性/探索性）。
   **⚠️ 判定覆盖前，先识别方案措辞的义务等级**：
   - 🔴 **必须（应有对应表格）**：措辞含「应」「须」「将」「进行」「采用」「计算」等强制性动词
   - 🟡 **可选（有表更好，无表不视为缺失）**：措辞含「可视情况」「可考虑」「必要时」「酌情」「如适用」「可以」
   - 🟢 **探索（不要求表格）**：方案明确标记为「探索性」「事后」
   只有 🔴 级别的条目缺失时才标 ❌；🟡 级别的条目缺失标 ⚠ 即可，**不算问题**。
   **注意**：条目中提到的"清单""明细列表""受试者ID级别"等不属于TFL表格，是附录中的数据列表(listing)，即使在条目中出现也标注为「不适用(清单)」而非❌缺失
2. 分析方式一致性: 方案规定的分析方式（如协方差模型/生存分析/CMH检验/描述性统计等）是否与表格实际采用的分析方式一致？注：**只检查分析方式层面**，不检查具体检验方法的选取（如卡方vsFisher），因为后者依赖数据特征判断
3. 人群标签: 表标题标注是否与声明一致？注：入组数与FAS/PPS人数不一致是正常现象（筛选失败不入分析集），**不要因此报错**
4. 表题/脚注: 分析集、时间点、分析单位是否标注完整？
   注：a) 首个表写了完整脚注后后续表写"下同"或"同前"是行业标准写法，后续表不算缺失
   b) 脚注不需注明统计方法选用依据
   c) 脚注不是必须项。**只要表题或表头已经清晰写出了分析集 + 时间点，即使完全没有脚注也视作合格，不产 Finding**
   d) **只有在表题+表头都看不出分析集或时间点的情况下，脚注缺失才可标为 🟢轻微（不可更高级别）**
5. 数值自洽: 同一分析集内各表合计N是否一致？注：**只检查同一分析集内部**，不跨分析集比较（入组>FAS是正常的）
6. 缺失值处理一致性: 如方案声明了缺失数据处理方法（见上表），检查其适用的终点分析在表格中是否确实采用了声明的处理方法。注：a) 表格脚注或方法说明中提及的缺失值处理方式是否与方案一致 b) 如表格未注明缺失值处理方式，标注为「表格未注明缺失值处理方法」而非直接判定不一致

## 工具
- `bash` — 执行 Shell 命令。工作目录={tables_dir}。先用 `ls *.xlsx` 了解有哪些表格文件
- `python` — 执行 Python 脚本（预装 openpyxl）。环境变量 `TABLES_DIR` 指向表格目录。建议写一个综合脚本来批量读取和分析本板块的所有表格
- `report_section_findings` — 核查完毕后提交结构化发现（仅调用一次）

## 工作流程建议
1. `bash`: `ls *.xlsx` 了解表格文件命名
2. `python`: 写一个脚本，用 openpyxl 逐一读取上表「表格编号→文件名 映射」中列出的每个表格，打印关键内容（包括表题、脚注、方法说明行）
3. 根据打印结果，逐一与方案条目和核查维度比对（共七项）
4. 如需进一步检查某张表的具体数值，再写针对性的 python 脚本
5. 完成本板块全部核查后，调用 `report_section_findings` 提交

现在开始逐表核查。

## ⚠️ 表号格式（极其重要）
报告发现时，**表号必须使用上方「表格编号→文件名 映射」中的原始编号**（如 `表7.4.1.1`），**严禁使用文件名前缀序号**（如 `表21`）。文件名前缀 `21-xxx.xlsx` 中的 `21` 只是文件排序号，不是正式表号。**每次引用表格都从映射表查对。**

## ⚠️ 证据要求
- 每个 method_issues / label_issues / footnote_issues 条目必须附带从表格中实际读取到的具体证据（如行号、列值）
- 报告某表"缺少XX"前，必须先写 python 脚本完整打印该表的所有行，确认确实没有
- 宁可少报（漏报一个真实问题）不可误报（无中生有）"""


class AgentExecutor:
    """Agent 工具执行器 — 支持 bash 和 python 两个通用工具。"""

    def __init__(self, tables_dir: str, matched_files: dict[str, str]):
        self.tables_dir = Path(tables_dir).resolve()
        self.matched_files = matched_files
        self._bash_session: list[subprocess.CompletedProcess] = []

    def execute(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "bash":
            return self._run_bash(tool_input.get("command", ""))
        elif tool_name == "python":
            return self._run_python(tool_input.get("code", ""))
        elif tool_name == "report_section_findings":
            return "收到。发现已记录。"
        return f"ERROR: 未知工具 '{tool_name}'"

    def _run_bash(self, command: str) -> str:
        if not command.strip():
            return "ERROR: 命令为空"
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=30, cwd=str(self.tables_dir),
                env={**os.environ, "TABLES_DIR": str(self.tables_dir)},
            )
        except subprocess.TimeoutExpired:
            return "ERROR: 命令超时 (30s)"
        out = result.stdout.strip()
        err = result.stderr.strip()
        parts = []
        if out:
            parts.append(out[:8000])
        if err:
            parts.append(f"[stderr]\n{err[:2000]}")
        if not parts:
            parts.append(f"(exit={result.returncode})")
        return "\n".join(parts)

    def _run_python(self, code: str) -> str:
        if not code.strip():
            return "ERROR: 代码为空"
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=60,
                cwd=str(self.tables_dir),
                env={**os.environ, "TABLES_DIR": str(self.tables_dir)},
            )
        except subprocess.TimeoutExpired:
            return "ERROR: Python 脚本超时 (60s)"
        out = result.stdout.strip()
        err = result.stderr.strip()
        parts = []
        if out:
            parts.append(out[:10000])
        if err:
            parts.append(f"[stderr]\n{err[:3000]}")
        if not parts:
            parts.append(f"(exit={result.returncode})")
        return "\n".join(parts)


def _run_one_section_agent(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    executor: AgentExecutor,
    section_name: str,
    max_iterations: int = 25,
) -> dict | None:
    """单个板块 Agent 的 tool-use loop"""
    messages = [
        {"role": "user", "content": f"请核查【{section_name}】板块，逐表打开关键表格后调用 report_section_findings。"}
    ]

    for iteration in range(1, max_iterations + 1):
        try:
            response = client.messages.create(
                model=model, max_tokens=16000,
                system=system_prompt, messages=messages, tools=AGENT_TOOLS,
            )
        except Exception as e:
            print(f"  [{section_name}] API 异常(iter {iteration}): {e}")
            if iteration < 3:
                time.sleep(5)
                continue
            return {"section": section_name, "findings": None, "error": str(e)}

        tool_uses = []
        for block in response.content:
            if block.type == "tool_use":
                tool_uses.append(block)

        if not tool_uses:
            text = "".join(block.text for block in response.content if block.type == "text")
            if text.strip():
                print(f"  [{section_name}] ✅ {iteration}轮 ({len(text)} 字符)")
            return {"section": section_name, "findings": None, "raw_text": text}

        tool_results = []
        for block in tool_uses:
            result_text = executor.execute(block.name, cast(dict, block.input))
            if len(result_text) > 15000:
                result_text = result_text[:15000] + "\n...(已截断)"

            if block.name == "report_section_findings":
                try:
                    findings = json.loads(block.input.get("findings_json", "{}"))
                    print(f"  [{section_name}] ✅ 提交 ({iteration}轮)")
                    return {"section": section_name, "findings": findings}
                except json.JSONDecodeError:
                    result_text = f"JSON解析失败: {str(block.input)[:300]}"

            tool_results.append({
                "type": "tool_result", "tool_use_id": block.id, "content": result_text,
            })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    print(f"  [{section_name}] ⚠️ 达到最大迭代")
    return {"section": section_name, "findings": None, "error": "max_iterations"}


def node_run_qc_agents(state: QCWorkflowState) -> dict:
    """并行运行 5 个板块 Agent，收集结构化发现"""
    print("\n" + "=" * 60)
    print("🔬 Node 4: 并行 Agent QC（5 板块）")
    print("=" * 60)

    cfg = state["config"]
    json_path = state.get("matched_json_path", state.get("protocol_json_path", ""))
    tables_dir = state.get("tables_output_dir", "")

    if not json_path or not tables_dir:
        return {"error_message": "缺少方案 JSON 或表格目录"}

    with open(json_path) as f:
        baseline = json.load(f)

    global_info = baseline.get("统计分析计划", baseline)
    sections, missing_data_info = _parse_sections_from_json(json_path, tables_dir)

    if not sections:
        return {"error_message": "未解析到任何分析板块"}

    print(f"  启动 {len(sections)} 个并行 Agent...")
    t0 = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=min(len(sections), 5)) as pool:
        futures = {}
        for sec in sections:
            prompt = _build_agent_prompt(sec, global_info, tables_dir, missing_data_info)
            executor = AgentExecutor(tables_dir, sec.table_files)
            client = _create_anthropic_client(cfg.api_key, cfg.api_base)
            future = pool.submit(
                _run_one_section_agent,
                client, cfg.model, prompt, executor, sec.name, cfg.max_qc_iterations,
            )
            futures[future] = sec.name

        for future in as_completed(futures):
            name = futures[future]
            try:
                r = future.result()
                results.append(r)
                status = "✅" if r and r.get("findings") else "⚠️"
                print(f"  [{name}] {status}")
            except Exception as e:
                print(f"  [{name}] ❌ {e}")
                results.append({"section": name, "findings": None, "error": str(e)})

    elapsed = time.time() - t0
    ok = sum(1 for r in results if r and r.get("findings"))
    print(f"  ⏱ {elapsed:.0f}s | {ok}/{len(results)} 成功")
    return {"qc_section_results": results, "error_message": ""}


# ═══════════════════════════════════════════════════════════════════════════
# Node 5: 汇总生成报告
# ═══════════════════════════════════════════════════════════════════════════

MASTER_TOOLS: list[dict] = [
    {
        "name": "write_report",
        "description": "将最终质控报告写入文件。",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "完整的 Markdown 报告"}},
            "required": ["content"],
        },
    },
]


def node_generate_report(state: QCWorkflowState) -> dict:
    """主控汇总：合并 5 个板块的发现，去重分级，生成报告"""
    print("\n" + "=" * 60)
    print("📝 Node 5: 汇总生成质控报告")
    print("=" * 60)

    cfg = state["config"]
    results = state.get("qc_section_results", [])
    project_dir = cfg.project_dir
    report_path = os.path.join(project_dir, "QC一致性质控报告.md")

    with open(state["matched_json_path"] or state["protocol_json_path"]) as f:
        baseline = json.load(f)

    protocol_info = baseline.get("统计分析计划", baseline)

    # 构建各板块摘要
    summaries = []
    all_findings_json = []
    for r in results:
        name = r.get("section", "未知")
        f = r.get("findings") or {}
        if f:
            cov = f.get("coverage", [])
            n_ok = sum(1 for c in cov if c.get("verdict") == "✅")
            n_partial = sum(1 for c in cov if c.get("verdict") == "⚠")
            n_miss = sum(1 for c in cov if c.get("verdict") == "❌")
            summaries.append(
                f"### {name}\n"
                f"- 覆盖: ✅{n_ok} ⚠{n_partial} ❌{n_miss}\n"
                f"- 方法: {len(f.get('method_issues',[]))} 标签: {len(f.get('label_issues',[]))} "
                f"脚注: {len(f.get('footnote_issues',[]))}\n"
                f"- 叙述: {f.get('narrative','无')}"
            )
        else:
            summaries.append(f"### {name}\n- 无结构化发现")
        all_findings_json.append(json.dumps(f if f else {"section": name}, ensure_ascii=False, indent=2))

    pop_text = json.dumps(protocol_info.get("分析人群", {}), ensure_ascii=False, indent=2)
    sample_text = json.dumps(protocol_info.get("样本量与检验参数", []), ensure_ascii=False, indent=2)

    # ── 从源数据计算事实基线，防止主控 Agent 猜测 ──
    tables_dir = state.get("tables_output_dir", "")
    table_count = len(list(Path(tables_dir).glob("*.xlsx"))) if tables_dir else 0

    item_counts_lines = []
    for key in ["受试者分布分析", "人口学与基线特征分析", "主要终点分析", "次要终点分析", "安全性分析"]:
        section = protocol_info.get(key)
        if isinstance(section, dict):
            items = section.get("条目", [])
            if isinstance(items, list):
                item_counts_lines.append(f"  - {key}: {len(items)} 条条目, 分析人群={section.get('分析人群','?')}")

    missing_data = protocol_info.get("缺失数据处理")
    if isinstance(missing_data, list) and missing_data:
        md_lines = []
        for d in missing_data:
            md_lines.append(f"  - 适用范围={d.get('适用范围','?')}; 处理方法={d.get('处理方法','?')}")
        item_counts_lines.append(f"  - 缺失数据处理: {chr(10).join(md_lines)}")

    # ── 计算实际表数 + 建立序号→原始编号映射（从 表格-标题索引.json）──
    table_section_breakdown = ""
    seq_to_num_map: list[str] = []
    if tables_dir:
        tp = Path(tables_dir)
        index_path = tp / "表格-标题索引.json"
        if index_path.exists():
            with open(index_path) as f:
                idx_data = json.load(f)
            table_section_breakdown = f"\n实际表格文件数: {len(idx_data)} 个（tables_output 目录共 {table_count} 个 xlsx 文件）\n"
            sec_tables: dict[str, list[str]] = {}
            for i, entry in enumerate(idx_data):
                num = entry.get("num", "?")
                seq_to_num_map.append(f"  序号{i+1:02d} → 表{num}  {entry.get('title','')}")
                sec = entry.get("section", "") or "其他"
                sec_tables.setdefault(sec, []).append(num)
            for sec, nums in sec_tables.items():
                if sec:
                    table_section_breakdown += f"  - {sec}: 表{', '.join(nums[:8])}{'...' if len(nums)>8 else ''} ({len(nums)}张)\n"

    seq_mapping_text = "\n".join(seq_to_num_map)

    master_prompt = f"""你是临床试验质控报告编写专家。基于各Agent发现，汇总生成最终报告。

## ⚠️ 事实基线（硬数据，直接引用，不可猜测或修改）
- 报告日期: {datetime.now().strftime('%Y年%m月%d日')}
- 表格总数: {table_count} 个 xlsx 文件
{table_section_breakdown}

## ⚠️ 序号→原始编号映射（写报告时查此表，严禁用序号代替原始编号）
{seq_mapping_text}

- 方案各板块条目数（来源于方案提取JSON，直接使用）:
{chr(10).join(item_counts_lines)}

## 分析人群
{pop_text}

## 样本量计划
{sample_text}

## 分级标准
- 🔴 严重: 方案预设分析完全缺失 / 分析方式根本错误 / 人群标签错配
- 🟡 中等: 有表但不完整 / 方法不一致
- 🟢 轻微: 脚注缺失 / 标题不完整 / 分析单位未说明

## ⚠️ 汇总时的铁律（必须遵守，否则报告质量不合格）
- **脚注缺失的严重度上限是 🟢 轻微**。脚注缺失永远不能升到 🟡 或 🔴。
- **以下情况直接不计入问题**：表题或表头已经写明了分析集 + 时间点 + 分析内容的，就算完全没有脚注也是合格的，不产生任何 Finding。
- **首个表脚注 + 后续表"下同"或"同前"的模式是行业标准写法**，后续表不算脚注缺失。
- 汇总时必须执行「全表脚注最小值原则」——同一板块内第一个表有完整脚注即为通过，后续表不再重复统计。

## 各板块发现（Agent 核查结果，可能有误，交叉验证）
{chr(10).join(summaries)}

## 各板块原始JSON
{chr(10).join(all_findings_json)}

## 要求
1. **元数据块（必须放在报告最开头，一字不改）**：
```
<!-- META
报告日期: {datetime.now().strftime('%Y年%m月%d日')}
表格总数: {table_count} 张
严重: X
中等: X
轻微: X
END_META -->
```
其中严重/中等/轻微的数量 X 必须根据实际发现数填写，无则填0。

2. 报告中所有数字（表数、条目数、分析集名称）必须使用「事实基线」中的值，禁止自行估算
3. 跨板块去重 + 共性问题识别
4. 按🔴🟡🟢严格分级，分级必须符合上述定义
5. 用 write_report 写入完整 Markdown 报告
6. ⚠️ Agent 发现可能有误报，汇总时须逐条二次判定：
   a) **方案措辞义务等级**：条目中用词含「可视情况」「可考虑」「必要时」「酌情」「如适用」「可以」等可选性措辞的 → 即使缺表也**不标为问题**，最多在正文提及"可补充"。只有含「应」「须」「将」「采用」等强制性措辞的条目缺失才标🔴。
   b) 对声称"缺"但无具体证据的发现，优先相信事实基线，降级或移除

报告章节: 一、总体概要 二、预设指标覆盖 三、统计方法一致性 四、表题/脚注审查 五、人群标签与组别检查 六、数值验证 七、问题汇总(🔴🟡🟢) 八、总结与建议"""

    client = _create_anthropic_client(cfg.api_key, cfg.api_base)
    messages = [{"role": "user", "content": "请汇总生成完整质控报告并调用 write_report 写入。"}]

    for iteration in range(1, 6):
        try:
            response = client.messages.create(
                model=cfg.model, max_tokens=24000,
                system=master_prompt, messages=messages, tools=MASTER_TOOLS,
            )
        except Exception as e:
            print(f"  ❌ 主控 API 异常: {e}")
            break

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            text = "".join(b.text for b in response.content if b.type == "text")
            break

        tool_results = []
        for block in tool_uses:
            if block.name == "write_report":
                content = block.input.get("content", "")
                Path(report_path).write_text(content, encoding="utf-8")
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": f"报告已写入: {report_path} ({len(content)} 字符)",
                })
            else:
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": f"未知工具: {block.name}",
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        if response.stop_reason == "end_turn":
            break

    print(f"  ✅ 报告: {report_path}" if os.path.exists(report_path) else "  ⚠️ 报告未生成")
    return {"qc_report_path": report_path, "error_message": ""}


# ═══════════════════════════════════════════════════════════════════════════
# Node 6: 生成 HTML 可视化报告
# ═══════════════════════════════════════════════════════════════════════════

def node_build_html_report(state: QCWorkflowState) -> dict:
    """将 .md 报告转换为交互式 HTML 查看器。"""
    cfg = state["config"]
    report_path = state.get("qc_report_path", "")
    project_dir = cfg.project_dir

    print("🌐 Node 6: 生成 HTML 可视化报告")

    if not report_path or not os.path.exists(report_path):
        print("  ⚠️ 报告未生成，跳过 HTML 构建")
        return {"viewer_html_path": "", "error_message": ""}

    build_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "build_report_viewer.py",
    )

    if not os.path.exists(build_script):
        print(f"  ⚠️ build_report_viewer.py 不存在，跳过 HTML 构建")
        return {"viewer_html_path": "", "error_message": ""}

    output_html = os.path.join(project_dir, "QC可视化报告.html")
    result = _run_script(
        build_script,
        ["--md", report_path, "--output", output_html,
         "--project-name", os.path.basename(project_dir)],
        timeout=120,
    )
    if result.returncode == 0 and os.path.exists(output_html):
        size_kb = os.path.getsize(output_html) / 1024
        print(f"  ✅ HTML 报告: {output_html} ({size_kb:.0f} KB)")
        return {"viewer_html_path": output_html, "error_message": ""}

    print(f"  ⚠️ HTML 报告生成失败")
    return {"viewer_html_path": "", "error_message": ""}


# ═══════════════════════════════════════════════════════════════════════════
# 条件边函数
# ═══════════════════════════════════════════════════════════════════════════

def _check_error(state: QCWorkflowState) -> str:
    return "error_end" if state.get("error_message") else "continue"


def _check_extraction_error(state: QCWorkflowState) -> str:
    error = state.get("error_message", "")
    max_retries = state["config"].max_retries
    attempts = state.get("protocol_extraction_attempts", 0)
    if not error:
        return "continue"
    if attempts < max_retries:
        return "retry"
    return "error_end"


# ═══════════════════════════════════════════════════════════════════════════
# 构建 LangGraph
# ═══════════════════════════════════════════════════════════════════════════

def build_workflow() -> StateGraph:
    builder = StateGraph(QCWorkflowState)

    # 注册节点
    builder.add_node("extract_protocol", node_extract_protocol)
    builder.add_node("validate_protocol", node_validate_protocol)
    builder.add_node("extract_and_match_tables", node_extract_and_match_tables)
    builder.add_node("extract_tables_docx", node_extract_tables)
    builder.add_node("run_qc_agents", node_run_qc_agents)
    builder.add_node("generate_report", node_generate_report)

    # 入口
    builder.set_entry_point("extract_protocol")

    # 提取方案 → 条件边（带重试）
    builder.add_conditional_edges(
        "extract_protocol", _check_extraction_error,
        {"continue": "validate_protocol", "retry": "extract_protocol", "error_end": END},
    )

    # 验证方案 → 提取表格
    builder.add_conditional_edges(
        "validate_protocol", _check_extraction_error,
        {"continue": "extract_tables_docx", "retry": "extract_protocol", "error_end": END},
    )

    # 提取表格 → 匹配表格
    builder.add_conditional_edges(
        "extract_tables_docx", _check_error,
        {"continue": "extract_and_match_tables", "error_end": END},
    )

    # 匹配表格 → Agent QC
    builder.add_conditional_edges(
        "extract_and_match_tables", _check_error,
        {"continue": "run_qc_agents", "error_end": END},
    )

    # Agent QC → 报告
    builder.add_conditional_edges(
        "run_qc_agents", _check_error,
        {"continue": "generate_report", "error_end": END},
    )

    # 报告 → HTML → END
    builder.add_node("build_html_report", node_build_html_report)
    builder.add_edge("generate_report", "build_html_report")
    builder.add_edge("build_html_report", END)

    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="比对基准 vs 表格一致性质控 — LangGraph 工作流")
    parser.add_argument("--api-key", default=LLM_API_KEY,
                        help="API key")
    parser.add_argument("--api-base", default=LLM_API_BASE,
                        help="API base URL")
    parser.add_argument("--model", default=LLM_MODEL, help="模型名")
    parser.add_argument("--protocol", default="", help="方案 DOCX 路径")
    parser.add_argument("--tables", default="", help="表格 DOCX 路径")
    parser.add_argument("--project", default="", help="项目工作目录")
    parser.add_argument("--max-retries", type=int, default=2, help="提取失败最大重试次数（默认2）")
    parser.add_argument("--skip-extract", action="store_true", help="跳过方案/表格提取，直接QC")
    parser.add_argument("--skip-qc", action="store_true", help="仅提取+匹配，跳过QC")
    args = parser.parse_args()

    if not args.api_key:
        print("❌ 缺少 API key")
        sys.exit(1)

    # 默认路径 — 用户须显式提供方案和表格路径
    project_dir = args.project or str(SCRIPT_DIR)
    protocol_path = args.protocol
    tables_path = args.tables

    if not protocol_path or not tables_path:
        print("❌ 必须提供 --protocol 和 --tables 参数")
        sys.exit(1)

    os.makedirs(project_dir, exist_ok=True)

    cfg = WorkflowConfig(
        protocol_path=protocol_path,
        tables_path=tables_path,
        project_dir=project_dir,
        model=args.model,
        api_key=args.api_key,
        api_base=args.api_base,
        max_retries=args.max_retries,
    )

    initial_state: QCWorkflowState = {
        "config": cfg,
        "qc_section_results": [],
        "current_node": "init",
        "error_message": "",
        "protocol_extraction_attempts": 0,
    }

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   比对基准 vs 表格 一致性质控 — LangGraph 工作流            ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  方案: {protocol_path}")
    print(f"║  表格: {tables_path}")
    print(f"║  项目: {project_dir}")
    print(f"║  模型: {args.model}")
    print("╚══════════════════════════════════════════════════════════════╝")

    # 根据模式选择不同的子图
    if args.skip_extract:
        # 跳过提取，直接进入 QC
        initial_state["protocol_json_path"] = os.path.join(project_dir, "方案输出",
            _find_latest_json(os.path.join(project_dir, "方案输出")) or "none.json")
        initial_state["matched_json_path"] = os.path.join(project_dir, "表格输出", "比对基准.json")
        initial_state["tables_output_dir"] = os.path.join(project_dir, "tables_output")
        initial_state["current_node"] = "run_qc_agents"
    elif args.skip_qc:
        initial_state["current_node"] = "extract_and_match_tables"

    workflow = build_workflow()
    config = {"configurable": {"thread_id": os.path.basename(project_dir)}}

    try:
        result = workflow.invoke(initial_state, config)
    except Exception as e:
        print(f"\n❌ 管线执行失败: {e}")
        traceback.print_exc()
        sys.exit(1)

    if result.get("error_message"):
        print(f"\n⚠️ 管线终止: {result['error_message']}")

    print("\n" + "=" * 60)
    print("🎉 工作流完成!")
    for key in ["protocol_json_path", "matched_json_path", "tables_output_dir", "qc_report_path"]:
        val = result.get(key, "")
        if val:
            print(f"   {key}: {val}")
    print("=" * 60)


if __name__ == "__main__":
    main()
