#!/usr/bin/env python3
"""
SAP 文档处理工作流 - LangGraph 版本
====================================

工作流结构:
  Step 1: 探索目录
      ↓
  Step 2: 并行提取7个任务
      ├─ 2a: 主要终点 → 生成表格目录
      ├─ 2b: 次要终点 → 生成表格目录
      ├─ 2c: 统计分析计划 → 提取书签 → 访视项目和基线项目并行 → 提取详情 → 生成表格目录
      ├─ 2d: 安全性评价 → 生成表格目录
      ├─ 2e: 基线分析（只提取，不生成表格）
      ├─ 2f: 试验样本（只提取，不生成表格）
      └─ 2g: 统计方法（只提取，不生成表格）

  统计分析计划分支详情:
    extract_statistical_plan
        ↓
    extract_crf_bookmarks
        ↓
    ┌───┴───┐
    ↓       ↓
  访视项目  基线项目
    └───┬───┘
        ↓
    extract_crf_details (从 CRF 提取每个项目的详细信息)
        ↓
    generate_statistical_tables

运行:
    cd sap_toolkit
    python3 scripts/sap_workflow_graph.py examples/sap.pdf --crf crf.pdf
"""

import os
import sys
import json
from pathlib import Path
from typing import TypedDict, Annotated
from operator import add
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import StateGraph, START, END
import anthropic

from config import API_KEY, BASE_URL, MODEL, MODEL_PRO, EXTRACTION_TASKS, APILogger, get_thinking_config


# ===== 日志 =====
def log(msg: str, level: str = "INFO"):
    """输出日志 — 同时写 stderr（人类可读）和 stdout（供后端 SSE 解析）"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "📋",
        "STEP": "🔷",
        "RUN": "▶️",
        "DONE": "✅",
        "ERROR": "❌",
        "WARN": "⚠️",
    }.get(level, "  ")
    line = f"[{timestamp}] {prefix} {msg}"
    print(line, file=sys.stderr, flush=True)
    # 同时写 stdout 供后端解析进度
    print(f"[LOG:{level}] {msg}", file=sys.stdout, flush=True)


# ===== 状态定义 =====
class WorkflowState(TypedDict):
    """工作流状态"""
    # 输入
    pdf_path: str
    crf_path: str  # CRF PDF 路径
    output_dir: str

    # Step 1 输出
    toc_content: str
    toc_file: str

    # Step 2 输出（并行提取）
    primary_endpoint_file: str
    secondary_endpoint_file: str
    statistical_plan_file: str
    safety_evaluation_file: str
    baseline_analysis_file: str

    # 统计分析计划分支额外输出
    crf_bookmarks_file: str
    first_visit_items_file: str
    second_visit_items_file: str  # 第二个访视项目
    baseline_items_from_crf_file: str  # 从 CRF 书签提取的基线项目
    crf_details_dir: str  # CRF 项目详情目录

    # 最终输出
    table_results: Annotated[list[dict], add]


# ===== 节点函数 =====

def explore_toc(state: WorkflowState) -> dict:
    """Step 1: 探索目录"""
    log("=" * 60, "STEP")
    log("Step 1: 探索目录", "STEP")
    log("=" * 60, "STEP")

    pdf_path = state["pdf_path"]
    output_dir = state["output_dir"]
    toc_dir = os.path.join(output_dir, "01_目录")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(toc_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    from scripts.explore_toc import explore_toc as do_explore_toc

    result = do_explore_toc(pdf_path, log_dir=log_dir)

    if "error" in result:
        log(f"目录探索失败: {result['error']}", "ERROR")
        return {"toc_content": "", "toc_file": ""}

    toc_content = result.get("content", "")
    if not toc_content:
        log("未找到目录内容", "WARN")
        return {"toc_content": "", "toc_file": ""}

    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    toc_file = os.path.join(toc_dir, f"{pdf_name}_目录.md")
    with open(toc_file, "w", encoding="utf-8") as f:
        f.write(toc_content)

    log(f"目录文件: {toc_file}", "DONE")
    log(f"目录长度: {len(toc_content)} 字符", "INFO")

    return {"toc_content": toc_content, "toc_file": toc_file}


# ===== Step 2: 并行提取任务 =====

def extract_primary_endpoint(state: WorkflowState) -> dict:
    """Step 2a: 提取主要终点"""
    log("=" * 60, "STEP")
    log("Step 2a: 提取主要终点", "STEP")
    log("=" * 60, "STEP")

    pdf_path = state["pdf_path"]
    toc_content = state["toc_content"]
    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    task = next((t for t in EXTRACTION_TASKS if t["name"] == "主要评价终点"), None)
    if not task:
        log("未找到主要终点任务配置", "ERROR")
        return {"primary_endpoint_file": ""}

    output_file = task["output_filename"]
    output_path = os.path.join(content_dir, output_file)

    log(f"提取: {task['name']}", "RUN")

    from scripts.pdf_qa import run_tool_loop_with_toc

    result = run_tool_loop_with_toc(
        pdf_path=pdf_path,
        user_question=task["prompt"],
        toc_content=toc_content,
        output_path=output_path,
        allow_write_dir=content_dir,
        output_filename=output_file,
        log_dir=log_dir,
    )

    if result and os.path.exists(output_path):
        size = os.path.getsize(output_path)
        log(f"完成: {output_path} ({size:,} bytes)", "DONE")
        return {"primary_endpoint_file": output_path}
    else:
        log("主要终点提取失败", "ERROR")
        return {"primary_endpoint_file": ""}


def extract_secondary_endpoint(state: WorkflowState) -> dict:
    """Step 2b: 提取次要终点"""
    log("=" * 60, "STEP")
    log("Step 2b: 提取次要终点", "STEP")
    log("=" * 60, "STEP")

    pdf_path = state["pdf_path"]
    toc_content = state["toc_content"]
    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    task = next((t for t in EXTRACTION_TASKS if t["name"] == "次要评价终点"), None)
    if not task:
        log("未找到次要终点任务配置", "ERROR")
        return {"secondary_endpoint_file": ""}

    output_file = task["output_filename"]
    output_path = os.path.join(content_dir, output_file)

    log(f"提取: {task['name']}", "RUN")

    from scripts.pdf_qa import run_tool_loop_with_toc

    result = run_tool_loop_with_toc(
        pdf_path=pdf_path,
        user_question=task["prompt"],
        toc_content=toc_content,
        output_path=output_path,
        allow_write_dir=content_dir,
        output_filename=output_file,
        log_dir=log_dir,
    )

    if result and os.path.exists(output_path):
        size = os.path.getsize(output_path)
        log(f"完成: {output_path} ({size:,} bytes)", "DONE")
        return {"secondary_endpoint_file": output_path}
    else:
        log("次要终点提取失败", "ERROR")
        return {"secondary_endpoint_file": ""}


def extract_statistical_plan(state: WorkflowState) -> dict:
    """Step 2c: 提取统计分析计划"""
    log("=" * 60, "STEP")
    log("Step 2c: 提取统计分析计划", "STEP")
    log("=" * 60, "STEP")

    pdf_path = state["pdf_path"]
    toc_content = state["toc_content"]
    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    task = next((t for t in EXTRACTION_TASKS if t["name"] == "统计分析计划"), None)
    if not task:
        log("未找到统计分析计划任务配置", "ERROR")
        return {"statistical_plan_file": ""}

    output_file = task["output_filename"]
    output_path = os.path.join(content_dir, output_file)

    log(f"提取: {task['name']}", "RUN")

    from scripts.pdf_qa import run_tool_loop_with_toc

    result = run_tool_loop_with_toc(
        pdf_path=pdf_path,
        user_question=task["prompt"],
        toc_content=toc_content,
        output_path=output_path,
        allow_write_dir=content_dir,
        output_filename=output_file,
        log_dir=log_dir,
    )

    if result and os.path.exists(output_path):
        size = os.path.getsize(output_path)
        log(f"完成: {output_path} ({size:,} bytes)", "DONE")
        return {"statistical_plan_file": output_path}
    else:
        log("统计分析计划提取失败", "ERROR")
        return {"statistical_plan_file": ""}


def extract_safety_evaluation(state: WorkflowState) -> dict:
    """Step 2d: 提取安全性评价"""
    log("=" * 60, "STEP")
    log("Step 2d: 提取安全性评价", "STEP")
    log("=" * 60, "STEP")

    pdf_path = state["pdf_path"]
    toc_content = state["toc_content"]
    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    task = next((t for t in EXTRACTION_TASKS if t["name"] == "安全性评价"), None)
    if not task:
        log("未找到安全性评价任务配置", "ERROR")
        return {"safety_evaluation_file": ""}

    output_file = task["output_filename"]
    output_path = os.path.join(content_dir, output_file)

    log(f"提取: {task['name']}", "RUN")

    from scripts.pdf_qa import run_tool_loop_with_toc

    result = run_tool_loop_with_toc(
        pdf_path=pdf_path,
        user_question=task["prompt"],
        toc_content=toc_content,
        output_path=output_path,
        allow_write_dir=content_dir,
        output_filename=output_file,
        log_dir=log_dir,
    )

    if result and os.path.exists(output_path):
        size = os.path.getsize(output_path)
        log(f"完成: {output_path} ({size:,} bytes)", "DONE")

        # 同时生成安全性评价 JSON（供 generate_safety_tables 使用）
        try:
            from scripts.extract_and_generate import extract_safety_endpoints, read_file
            tables_dir = os.path.join(output_dir, "03_表格目录")
            os.makedirs(tables_dir, exist_ok=True)
            api_logger = APILogger(log_dir, task_name="安全性评价") if log_dir else None
            sap_content = read_file(output_path)
            json_result = extract_safety_endpoints(sap_content, api_logger=api_logger)
            json_output = os.path.join(tables_dir, "安全性评价分析.json")
            with open(json_output, "w", encoding="utf-8") as f:
                json.dump(json_result, f, ensure_ascii=False, indent=2)
            log(f"安全性评价 JSON: {json_output}", "DONE")
        except Exception as e:
            log(f"安全性评价 JSON 生成失败: {e}", "WARN")

        return {"safety_evaluation_file": output_path}
    else:
        log("安全性评价提取失败", "ERROR")
        return {"safety_evaluation_file": ""}


def extract_baseline_analysis(state: WorkflowState) -> dict:
    """Step 2e: 提取基线分析"""
    log("=" * 60, "STEP")
    log("Step 2e: 提取基线分析", "STEP")
    log("=" * 60, "STEP")

    pdf_path = state["pdf_path"]
    toc_content = state["toc_content"]
    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    task = next((t for t in EXTRACTION_TASKS if t["name"] == "基线分析"), None)
    if not task:
        log("未找到基线分析任务配置", "ERROR")
        return {"baseline_analysis_file": ""}

    output_file = task["output_filename"]
    output_path = os.path.join(content_dir, output_file)

    log(f"提取: {task['name']}", "RUN")

    from scripts.pdf_qa import run_tool_loop_with_toc

    result = run_tool_loop_with_toc(
        pdf_path=pdf_path,
        user_question=task["prompt"],
        toc_content=toc_content,
        output_path=output_path,
        allow_write_dir=content_dir,
        output_filename=output_file,
        log_dir=log_dir,
    )

    if result and os.path.exists(output_path):
        size = os.path.getsize(output_path)
        log(f"完成: {output_path} ({size:,} bytes)", "DONE")
        return {"baseline_analysis_file": output_path}
    else:
        log("基线分析提取失败", "ERROR")
        return {"baseline_analysis_file": ""}


def extract_sample_info_node(state: WorkflowState) -> dict:
    """Step 2f: 提取试验样本信息（只提取，不生成表格）"""
    log("=" * 60, "STEP")
    log("Step 2f: 提取试验样本信息", "STEP")
    log("=" * 60, "STEP")

    pdf_path = state["pdf_path"]
    toc_content = state["toc_content"]
    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    task = next((t for t in EXTRACTION_TASKS if t["name"] == "试验样本"), None)
    if not task:
        log("未找到试验样本任务配置", "ERROR")
        return {}

    output_file = task["output_filename"]
    output_path = os.path.join(content_dir, output_file)

    log(f"提取: {task['name']}", "RUN")

    from scripts.pdf_qa import run_tool_loop_with_toc

    result = run_tool_loop_with_toc(
        pdf_path=pdf_path,
        user_question=task["prompt"],
        toc_content=toc_content,
        output_path=output_path,
        allow_write_dir=content_dir,
        output_filename=output_file,
        log_dir=log_dir,
    )

    if result and os.path.exists(output_path):
        # 读取提取的 MD 内容，调用结构化提取函数生成 JSON
        from scripts.extract_and_generate import extract_sample_info, read_file, save_json

        api_logger = APILogger(log_dir, task_name="试验样本") if log_dir else None
        sap_content = read_file(output_path)
        json_data = extract_sample_info(sap_content, api_logger=api_logger)

        json_output = os.path.join(content_dir, "试验样本.json")
        save_json(json_data, json_output)

        log(f"完成: {output_path}", "DONE")
        return {}
    else:
        log("试验样本提取失败", "ERROR")
        return {}


def extract_stat_methods_node(state: WorkflowState) -> dict:
    """Step 2g: 提取统计方法（只提取，不生成表格）"""
    log("=" * 60, "STEP")
    log("Step 2g: 提取统计方法", "STEP")
    log("=" * 60, "STEP")

    pdf_path = state["pdf_path"]
    toc_content = state["toc_content"]
    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    task = next((t for t in EXTRACTION_TASKS if t["name"] == "统计方法"), None)
    if not task:
        log("未找到统计方法任务配置", "ERROR")
        return {}

    output_file = task["output_filename"]
    output_path = os.path.join(content_dir, output_file)

    log(f"提取: {task['name']}", "RUN")

    from scripts.pdf_qa import run_tool_loop_with_toc

    result = run_tool_loop_with_toc(
        pdf_path=pdf_path,
        user_question=task["prompt"],
        toc_content=toc_content,
        output_path=output_path,
        allow_write_dir=content_dir,
        output_filename=output_file,
        log_dir=log_dir,
    )

    if result and os.path.exists(output_path):
        # 读取提取的 MD 内容，调用结构化提取函数生成 JSON
        from scripts.extract_and_generate import extract_stat_methods, read_file, save_json

        api_logger = APILogger(log_dir, task_name="统计方法") if log_dir else None
        sap_content = read_file(output_path)
        json_data = extract_stat_methods(sap_content, api_logger=api_logger)

        json_output = os.path.join(content_dir, "统计方法.json")
        save_json(json_data, json_output)

        log(f"完成: {output_path}", "DONE")
        return {}
    else:
        log("统计方法提取失败", "ERROR")
        return {}


# ===== 统计分析计划分支：书签和访视提取 =====

def extract_crf_bookmarks(state: WorkflowState) -> dict:
    """Step 2c-1: 提取 CRF 书签"""
    log("=" * 60, "STEP")
    log("Step 2c-1: 提取 CRF 书签", "STEP")
    log("=" * 60, "STEP")

    crf_path = state.get("crf_path", "")
    if not crf_path or not os.path.exists(crf_path):
        log("CRF 文件不存在，跳过书签提取", "WARN")
        return {"crf_bookmarks_file": ""}

    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    os.makedirs(content_dir, exist_ok=True)

    output_path = os.path.join(content_dir, "crf_书签.json")

    log("提取 CRF 书签...", "RUN")

    from scripts.extract_crf_bookmarks import extract_bookmarks

    bookmarks = extract_bookmarks(crf_path, output_path)

    if bookmarks:
        log(f"完成: 提取到 {len(bookmarks)} 个书签", "DONE")
        return {"crf_bookmarks_file": output_path}
    else:
        log("CRF 书签提取失败", "ERROR")
        return {"crf_bookmarks_file": ""}


def extract_first_visit_items(state: WorkflowState) -> dict:
    """Step 2c-2: 从统计分析计划中提取访视项目"""
    log("=" * 60, "STEP")
    log("Step 2c-2: 提取访视项目", "STEP")
    log("=" * 60, "STEP")

    statistical_plan_file = state.get("statistical_plan_file", "")
    if not statistical_plan_file or not os.path.exists(statistical_plan_file):
        log("统计分析计划文件不存在，跳过访视提取", "WARN")
        return {"first_visit_items_file": ""}

    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    output_path = os.path.join(content_dir, "试验流程_第一个访视项目.json")

    log("提取访视项目...", "RUN")

    from scripts.extract_first_visit import extract_first_visit as do_extract

    # 初始化 API 日志记录器
    api_logger = APILogger(log_dir, task_name="访视项目") if log_dir else None

    # 读取统计分析计划内容
    with open(statistical_plan_file, "r", encoding="utf-8") as f:
        content = f.read()

    result = do_extract(content, api_logger=api_logger)

    if result and result.get("items"):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log(f"完成: 提取到 {len(result['items'])} 个访视项目", "DONE")
        return {"first_visit_items_file": output_path}
    else:
        log("访视项目提取失败", "ERROR")
        return {"first_visit_items_file": ""}


def extract_second_visit_items(state: WorkflowState) -> dict:
    """Step 2c-2b: 从统计分析计划中提取第二个访视项目"""
    log("=" * 60, "STEP")
    log("Step 2c-2b: 提取第二个访视项目", "STEP")
    log("=" * 60, "STEP")

    statistical_plan_file = state.get("statistical_plan_file", "")
    if not statistical_plan_file or not os.path.exists(statistical_plan_file):
        log("统计分析计划文件不存在，跳过第二个访视提取", "WARN")
        return {"second_visit_items_file": ""}

    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    output_path = os.path.join(content_dir, "试验流程_第二个访视项目.json")

    log("提取第二个访视项目...", "RUN")

    from scripts.extract_second_visit import extract_second_visit as do_extract

    # 初始化 API 日志记录器
    api_logger = APILogger(log_dir, task_name="第二个访视项目") if log_dir else None

    # 读取统计分析计划内容
    with open(statistical_plan_file, "r", encoding="utf-8") as f:
        content = f.read()

    result = do_extract(content, api_logger=api_logger)

    if result and result.get("items"):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log(f"完成: 提取到 {len(result['items'])} 个第二个访视项目", "DONE")
        return {"second_visit_items_file": output_path}
    else:
        log("第二个访视项目提取失败", "ERROR")
        return {"second_visit_items_file": ""}


def extract_baseline_items_from_crf(state: WorkflowState) -> dict:
    """Step 2c-3: 从 CRF 书签中提取基线项目（与访视项目并行）"""
    log("=" * 60, "STEP")
    log("Step 2c-3: 从 CRF 书签提取基线项目", "STEP")
    log("=" * 60, "STEP")

    crf_bookmarks_file = state.get("crf_bookmarks_file", "")
    if not crf_bookmarks_file or not os.path.exists(crf_bookmarks_file):
        log("CRF 书签文件不存在，跳过基线项目提取", "WARN")
        return {"baseline_items_from_crf_file": ""}

    output_dir = state["output_dir"]
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(content_dir, exist_ok=True)

    output_path = os.path.join(content_dir, "crf_基线项目.json")

    log("从 CRF 书签提取基线项目...", "RUN")

    # 读取 CRF 书签
    with open(crf_bookmarks_file, "r", encoding="utf-8") as f:
        crf_bookmarks = json.load(f)

    if not crf_bookmarks:
        log("CRF 书签为空", "WARN")
        return {"baseline_items_from_crf_file": ""}

    from scripts.extract_baseline_items import extract_baseline_items, BASELINE_ITEMS_TOOL

    # 初始化 API 日志记录器
    api_logger = APILogger(log_dir, task_name="基线项目") if log_dir else None

    # 构建 CRF 书签内容文本
    bookmarks_text = "\n".join([
        f"- {item.get('title', '')}: {item.get('description', '')}"
        for item in crf_bookmarks
    ])

    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = """你是一个临床试验数据分析专家。

你的任务是从 CRF 书签中，提取所有需要进行基线分析的项目。

【分类规则】
以下安全性相关项目必须作为独立 key 提取，不要放入 items 数组：
- 生命体征 → vital_signs
- 体格检查 → physical_examination
- 心电图检查 → ecg
- 实验室检查 → laboratory（如血常规、血生化、凝血功能等，每个检查项目独立一条）
- 器械缺陷 → device_defects
- 合并用药 或 非药物治疗 → concomitant_medication
- 不良事件 → adverse_events

其他普通项目（如影像学检查、量表评分等）放入 items 数组，只有 item_name。

【注意】
- 只提取 CRF 书签中明确与基线分析相关的项目
- 不要遗漏任何项目
- 实验室检查如果有多个子项目（如血常规、肝功能、肾功能），每个子项目独立一条"""

    user_message = f"""请分析以下 CRF 书签内容，提取所有需要进行基线分析的项目。

# CRF 书签内容

{bookmarks_text}

请调用 extract_baseline_items 工具输出结果。"""

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=1500)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        system=system_prompt,
        tools=[BASELINE_ITEMS_TOOL],
        tool_choice={"type": "tool", "name": "extract_baseline_items"},
        extra_body=extra_body,
        messages=messages,
    )

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_baseline_items_from_crf",
            model=MODEL,
            max_tokens=4096,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[BASELINE_ITEMS_TOOL],
            tool_choice={"type": "tool", "name": "extract_baseline_items"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_baseline_items":
            result = block.input
            # 清理：移除值为 false 或空数组的聚合类别 key
            for cat_key in ["vital_signs", "physical_examination", "ecg", "laboratory", "device_defects", "concomitant_medication"]:
                val = result.get(cat_key)
                if val is False or val == [] or val is None:
                    result.pop(cat_key, None)
            items = result.get("items", [])
            safety_count = sum(1 for k in ["vital_signs", "physical_examination", "ecg", "laboratory", "device_defects", "concomitant_medication"] if k in result) + len(result.get("adverse_events", []))
            log(f"提取完成: 普通{len(items)}项, 安全性类{safety_count}项", "DONE")

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            return {"baseline_items_from_crf_file": output_path}
        elif block.type == "thinking":
            log(f"思考过程: {block.thinking[:200]}...", "INFO")

    log("基线项目提取失败", "ERROR")
    return {"baseline_items_from_crf_file": ""}


def extract_crf_details(state: WorkflowState) -> dict:
    """Step 2c-4: 从 CRF 中提取4个安全性项目"""
    log("=" * 60, "STEP")
    log("Step 2c-4: 提取 CRF 项目详情", "STEP")
    log("=" * 60, "STEP")

    crf_path = state.get("crf_path", "")
    if not crf_path or not os.path.exists(crf_path):
        log("CRF 文件不存在，跳过详情提取", "WARN")
        return {"crf_details_dir": ""}

    first_visit_file = state.get("first_visit_items_file", "")

    if not first_visit_file:
        log("访视项目文件不存在，跳过详情提取", "WARN")
        return {"crf_details_dir": ""}

    output_dir = state["output_dir"]
    details_dir = os.path.join(output_dir, "04_项目详情")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(details_dir, exist_ok=True)

    log("从 CRF 提取项目详情...", "RUN")

    # 读取访视项目
    with open(first_visit_file, "r", encoding="utf-8") as f:
        visit_data = json.load(f)

    # 提取4个安全性项目（只要key不为空就添加，使用固定的中文名称）
    safety_keys = ["vital_signs", "physical_examination", "ecg", "laboratory"]
    safety_items = []
    lab_item_names = set()
    for key in safety_keys:
        items = visit_data.get(key, [])
        if items:  # 只要有项目就添加大类
            # 使用固定的中文名称
            category_names = {
                "vital_signs": "生命体征",
                "physical_examination": "体格检查",
                "ecg": "心电图",
                "laboratory": "实验室检查",
            }
            category_name = category_names.get(key, key)
            # 从访视项目数据中读取 only_in_first_visit 值
            only_in_first_visit = items[0].get("only_in_first_visit", False) if items else False
            safety_items.append({"name": category_name, "only_in_first_visit": only_in_first_visit})
            if key == "laboratory":
                lab_item_names.add(category_name)

    log(f"安全性项目（需提取详情）: {len(safety_items)} 个", "INFO")
    for item in safety_items:
        log(f"  - {item.get('name', '')}", "INFO")

    from scripts.extract_crf_details import extract_safety_items_parallel

    # 并行提取安全性项目
    safety_result = extract_safety_items_parallel(
        pdf_path=crf_path,
        safety_items=safety_items,
        output_dir=details_dir,
        max_workers=8,
        log_dir=log_dir,
        lab_item_names=lab_item_names
    )

    # 保存汇总结果
    summary_file = os.path.join(details_dir, "_summary.json")
    summary = {
        "safety_items": {
            "total": len(safety_items),
            "success": len([r for r in safety_result["results"].values() if r.get("success")]),
            "failed": len(safety_result["failed_items"]),
            "failed_items": safety_result["failed_items"],
            "results": safety_result["results"]
        }
    }
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    log(f"详情提取完成", "DONE")
    log(f"安全性项目: {summary['safety_items']['success']}/{summary['safety_items']['total']} 成功", "INFO")

    return {"crf_details_dir": details_dir}


# ===== Step 3: 各分支生成表格目录 =====

def generate_primary_tables(state: WorkflowState) -> dict:
    """Step 3a: 主要终点表格目录"""
    log("=" * 60, "STEP")
    log("Step 3a: 生成主要终点表格目录", "STEP")
    log("=" * 60, "STEP")

    primary_file = state.get("primary_endpoint_file", "")
    if not primary_file or not os.path.exists(primary_file):
        log("主要终点文件不存在，跳过", "WARN")
        return {"table_results": [{"name": "主要评价终点", "success": False}]}

    output_dir = state["output_dir"]
    tables_dir = os.path.join(output_dir, "03_表格目录")
    os.makedirs(tables_dir, exist_ok=True)

    from scripts.extract_and_generate import (
        extract_endpoints,
        generate_table_names,
        format_table_output,
        save_json,
        save_text,
        read_file,
    )

    log("生成主要终点表格...", "RUN")

    # 初始化 API 日志记录器
    log_dir = os.path.join(output_dir, "logs")
    api_logger = APILogger(log_dir, task_name="主要终点") if log_dir else None

    try:
        sap_content = read_file(primary_file)
        json_data = extract_endpoints(sap_content, api_logger=api_logger)
        table_data = generate_table_names(json_data)

        json_output = os.path.join(tables_dir, "主要评价终点.json")
        table_output = os.path.join(tables_dir, "主要评价终点_表格名称.txt")

        save_json(json_data, json_output)
        table_text = format_table_output(table_data)
        save_text(table_text, table_output)

        log(f"完成: {json_output}", "DONE")

        # 生成表格信息 JSON
        info_dir = os.path.join(output_dir, "05_表格信息")
        os.makedirs(info_dir, exist_ok=True)
        from scripts.generate_endpoint_tables import parse_table_names, generate_table_json
        table_names = parse_table_names(table_output)
        for table_name in table_names:
            table_json = generate_table_json(table_name, json_data.get("endpoints", []), json_data.get("statistical_methods", {}).get("primary_analysis", {}).get("methods", []))
            safe_name = table_name.replace("/", "_").replace("\\", "_")
            with open(os.path.join(info_dir, f"{safe_name}.json"), "w", encoding="utf-8") as f:
                json.dump(table_json, f, ensure_ascii=False, indent=2)
        log(f"生成表格信息: {info_dir} ({len(table_names)} 个文件)", "DONE")

        return {"table_results": [{"name": "主要评价终点", "success": True}]}
    except Exception as e:
        log(f"失败: {e}", "ERROR")
        return {"table_results": [{"name": "主要评价终点", "success": False}]}


def generate_secondary_tables(state: WorkflowState) -> dict:
    """Step 3b: 次要终点表格目录"""
    log("=" * 60, "STEP")
    log("Step 3b: 生成次要终点表格目录", "STEP")
    log("=" * 60, "STEP")

    secondary_file = state.get("secondary_endpoint_file", "")
    if not secondary_file or not os.path.exists(secondary_file):
        log("次要终点文件不存在，跳过", "WARN")
        return {"table_results": [{"name": "次要评价终点", "success": False}]}

    output_dir = state["output_dir"]
    tables_dir = os.path.join(output_dir, "03_表格目录")
    os.makedirs(tables_dir, exist_ok=True)

    from scripts.extract_and_generate import (
        extract_secondary_endpoints,
        generate_secondary_table_names,
        format_table_output,
        save_json,
        save_text,
        read_file,
    )

    log("生成次要终点表格...", "RUN")

    # 初始化 API 日志记录器
    log_dir = os.path.join(output_dir, "logs")
    api_logger = APILogger(log_dir, task_name="次要终点") if log_dir else None

    try:
        sap_content = read_file(secondary_file)
        json_data = extract_secondary_endpoints(sap_content, api_logger=api_logger)
        table_data = generate_secondary_table_names(json_data)

        json_output = os.path.join(tables_dir, "次要评价终点.json")
        table_output = os.path.join(tables_dir, "次要评价终点_表格名称.txt")

        save_json(json_data, json_output)
        table_text = format_table_output(table_data)
        save_text(table_text, table_output)

        log(f"完成: {json_output}", "DONE")

        # 生成表格信息 JSON
        info_dir = os.path.join(output_dir, "05_表格信息")
        os.makedirs(info_dir, exist_ok=True)
        from scripts.generate_endpoint_tables import parse_table_names, generate_table_json
        table_names = parse_table_names(table_output)
        for table_name in table_names:
            table_json = generate_table_json(table_name, json_data.get("endpoints", []), json_data.get("statistical_methods", {}).get("primary_analysis", {}).get("methods", []))
            safe_name = table_name.replace("/", "_").replace("\\", "_")
            with open(os.path.join(info_dir, f"{safe_name}.json"), "w", encoding="utf-8") as f:
                json.dump(table_json, f, ensure_ascii=False, indent=2)
        log(f"生成表格信息: {info_dir} ({len(table_names)} 个文件)", "DONE")

        return {"table_results": [{"name": "次要评价终点", "success": True}]}
    except Exception as e:
        log(f"失败: {e}", "ERROR")
        return {"table_results": [{"name": "次要评价终点", "success": False}]}


def generate_statistical_tables(state: WorkflowState) -> dict:
    """Step 3c: 统计分析计划表格目录（基于书签和访视项目）"""
    log("=" * 60, "STEP")
    log("Step 3c: 生成统计分析计划表格目录", "STEP")
    log("=" * 60, "STEP")

    crf_bookmarks_file = state.get("crf_bookmarks_file", "")
    first_visit_file = state.get("first_visit_items_file", "")

    output_dir = state["output_dir"]
    tables_dir = os.path.join(output_dir, "03_表格目录")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(tables_dir, exist_ok=True)

    log("汇总统计分析计划数据...", "RUN")

    results = {}

    # 读取 CRF 书签
    crf_bookmarks = []
    if crf_bookmarks_file and os.path.exists(crf_bookmarks_file):
        with open(crf_bookmarks_file, "r", encoding="utf-8") as f:
            crf_bookmarks = json.load(f)
        results["crf_bookmarks"] = crf_bookmarks
        log(f"CRF 书签: {len(crf_bookmarks)} 个", "INFO")
    else:
        results["crf_bookmarks"] = []
        log("CRF 书签: 无", "WARN")

    # 读取访视项目
    first_visit_items = []
    if first_visit_file and os.path.exists(first_visit_file):
        with open(first_visit_file, "r", encoding="utf-8") as f:
            visit_data = json.load(f)
            first_visit_items = visit_data.get("items", [])
        results["first_visit_items"] = visit_data
        log(f"访视项目: {len(first_visit_items)} 个", "INFO")
    else:
        results["first_visit_items"] = {}
        log("访视项目: 无", "WARN")

    # 保存汇总结果
    json_output = os.path.join(tables_dir, "统计分析计划.json")
    with open(json_output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 使用 LLM 提取病史类表格
    history_items = []
    if crf_bookmarks:
        log("使用 LLM 提取病史类表格...", "RUN")
        try:
            from scripts.extract_history import extract_history_tables
            api_logger = APILogger(log_dir, task_name="病史表格") if log_dir else None
            history_result = extract_history_tables(crf_bookmarks, api_logger=api_logger)
            history_items = history_result.get("history_tables", [])
            log(f"病史类表格: {len(history_items)} 个", "INFO")

            # 保存病史提取结果
            history_json = os.path.join(tables_dir, "病史表格.json")
            with open(history_json, "w", encoding="utf-8") as f:
                json.dump(history_result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log(f"病史提取失败，使用备用规则: {e}", "WARN")
            # 备用规则：以"史"结尾
            history_items = [
                {"title": b["title"], "category": "其他病史"}
                for b in crf_bookmarks
                if b.get("title", "").endswith("史")
            ]

    # 生成表格名称 txt
    table_names = []
    idx = 1

    # 1. 人口学信息
    table_names.append(f"\n## 人口学信息")
    table_names.append("-" * 60)
    table_names.append(f"{idx}. 人口学信息（FAS）")
    idx += 1

    # 2. 病史
    if history_items:
        table_names.append(f"\n## 病史")
        table_names.append("-" * 60)
        for item in history_items:
            title = item.get("title", "")
            table_names.append(f"{idx}. {title}（FAS）")
            idx += 1

    # 3. 基线信息（从访视项目中排除人口学和病史相关项目）
    history_titles = {item.get("title", "") for item in history_items}
    baseline_items = [
        item for item in first_visit_items
        if "人口学" not in item.get("item_name", "")
        and item.get("item_name", "") not in history_titles
        and not item.get("item_name", "").endswith("史")
    ]

    # 3.1 从4个安全性类别中提取 only_in_first_visit=true 的项目作为基线项目
    visit_data = results.get("first_visit_items", {})
    safety_keys_for_baseline = ["vital_signs", "physical_examination", "ecg", "laboratory"]
    baseline_safety_items = []
    for key in safety_keys_for_baseline:
        items = visit_data.get(key, [])
        for item in items:
            if item.get("only_in_first_visit", False):
                baseline_safety_items.append({
                    "item_name": item.get("name", ""),
                    "category": key
                })

    if baseline_items or baseline_safety_items:
        table_names.append(f"\n## 基线信息")
        table_names.append("-" * 60)
        # 普通基线项目
        for item in baseline_items:
            name = item.get("item_name", "")
            table_names.append(f"{idx}. 基线信息-{name}（FAS）")
            idx += 1
        # 安全性类别中只在访视1出现的项目（标记原始类别）
        for item in baseline_safety_items:
            name = item.get("item_name", "")
            category = item.get("category", "")
            table_names.append(f"{idx}. 基线信息-{name}（FAS）[from:{category}]")
            idx += 1

    # 保存 txt
    txt_output = os.path.join(tables_dir, "统计分析计划_表格名称.txt")
    with open(txt_output, "w", encoding="utf-8") as f:
        f.write("\n".join(table_names))

    log(f"完成: {json_output}", "DONE")
    log(f"完成: {txt_output}", "DONE")
    return {"table_results": [{"name": "统计分析计划", "success": True}]}


def generate_safety_tables(state: WorkflowState) -> dict:
    """Step 3d: 安全性评价表格目录"""
    log("=" * 60, "STEP")
    log("Step 3d: 生成安全性评价表格目录", "STEP")
    log("=" * 60, "STEP")

    output_dir = state["output_dir"]
    tables_dir = os.path.join(output_dir, "03_表格目录")
    details_dir = os.path.join(output_dir, "04_项目详情")
    content_dir = os.path.join(output_dir, "02_内容提取")
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(tables_dir, exist_ok=True)

    log("生成安全性评价表格目录...", "RUN")

    # ===== Part 1: 从安全性评价 MD 中提取 JSON =====
    safety_md_file = state.get("safety_evaluation_file", "")
    if not safety_md_file or not os.path.exists(safety_md_file):
        # 尝试从 content_dir 查找
        if os.path.exists(content_dir):
            for fname in os.listdir(content_dir):
                if "安全性" in fname and fname.endswith(".md"):
                    safety_md_file = os.path.join(content_dir, fname)
                    break

    # 读取 extract_safety_evaluation 已生成的 JSON
    json_result = {}
    safety_json_file = os.path.join(tables_dir, "安全性评价分析.json")
    if os.path.exists(safety_json_file):
        with open(safety_json_file, "r", encoding="utf-8") as f:
            json_result = json.load(f)
        log(f"读取安全性评价 JSON: {safety_json_file}", "DONE")
    else:
        log("安全性评价分析.json 不存在，跳过安全性终点表格生成", "WARN")

    # ===== Part 2: 生成表格名称 txt =====
    # 直接从输出目录读取第一个访视项目文件
    visit_data = {}
    if os.path.exists(content_dir):
        for fname in os.listdir(content_dir):
            if "第一个访视项目" in fname and fname.endswith(".json"):
                with open(os.path.join(content_dir, fname), "r", encoding="utf-8") as f:
                    visit_data = json.load(f)
                break

    # 辅助函数：读取 04_项目详情 下的 JSON 文件
    def load_detail_json(item_name):
        file_path = os.path.join(details_dir, f"{item_name}.json")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    # 辅助函数：判断 visit_data 中是否有某个 key
    def has_visit_item(key):
        return bool(visit_data.get(key))

    table_names = []
    idx = 1

    # 第1类：不良事件（SS）— 必出
    ae_tables = [
        "不良事件（SS）",
        "不良事件编码（SOC/PT）（SS）",
        "严重不良事件编码（SOC/PT）（SS）",
    ]
    table_names.append(f"\n## 不良事件（SS）")
    table_names.append("-" * 60)
    for t in ae_tables:
        table_names.append(f"{idx}. {t}")
        idx += 1

    # 生成不良事件 JSON（构造数据，不从CRF提取）
    info_dir = os.path.join(output_dir, "05_表格信息")
    os.makedirs(info_dir, exist_ok=True)
    ae_json = {
        "table_name": "不良事件（SS）",
        "projects": [
            {
                "name": "不良事件分类",
                "categories": [
                    "不良事件",
                    "与试验相关的不良事件",
                    "重度不良事件",
                    "导致死亡不良事件",
                    "严重不良事件",
                    "与试验相关的严重不良事件",
                    "导致脱落的不良事件"
                ]
            }
        ]
    }
    ae_file = os.path.join(info_dir, "不良事件（SS）.json")
    with open(ae_file, "w", encoding="utf-8") as f:
        json.dump(ae_json, f, ensure_ascii=False, indent=2)

    # 第1.5类：安全性终点（SS）— 基于 LLM 提取的 safety_endpoints
    safety_endpoints = json_result.get("safety_endpoints", [])
    if safety_endpoints:
        table_names.append(f"\n## 安全性终点（SS）")
        table_names.append("-" * 60)
        for ep in safety_endpoints:
            name = ep.get("name", "")
            if name:
                table_names.append(f"{idx}. {name}（SS）")
                idx += 1

    # 第2类：实验室检查（SS）— 条件出（排除 only_in_first_visit=true 和"其他"分类的项目）
    if has_visit_item("laboratory"):
        # 收集基线中已有的实验室子页面名称（用于排除其子项）
        baseline_lab_parents = set()
        for lab_item in visit_data.get("laboratory", []):
            if lab_item.get("only_in_first_visit", False):
                baseline_lab_parents.add(lab_item.get("name", ""))

        # 直接使用大类名称查找
        detail = load_detail_json("实验室检查")
        if detail and detail.get("analysis_items"):
            # 按category分组
            lab_groups = {}
            for item in detail["analysis_items"]:
                # 排除只在第一次访视出现的项目（属于基线）
                if item.get("only_in_first_visit", False):
                    continue
                # 排除父分组已在基线中的项目（如血生化下的肝功能、肾功能）
                parent = item.get("parent", "")
                if parent and parent in baseline_lab_parents:
                    continue
                category = item.get("category", "")
                # 排除"其他"分类
                if category == "其他":
                    continue
                if category not in lab_groups:
                    lab_groups[category] = []
                lab_groups[category].append(item)

            if lab_groups:
                table_names.append(f"\n## 实验室检查（SS）")
                table_names.append("-" * 60)
                for category, items in lab_groups.items():
                    for item in items:
                        name = item.get("name", "")
                        table_names.append(f"{idx}. {category}-{name}前后交叉表（SS）")
                        idx += 1

    # 第3类：生命体征（SS）— 条件出（排除 only_in_first_visit=true 的项目）
    if has_visit_item("vital_signs"):
        # 直接使用大类名称查找
        detail = load_detail_json("生命体征")
        if detail and detail.get("analysis_items"):
            table_names.append(f"\n## 生命体征（SS）")
            table_names.append("-" * 60)
            for item in detail["analysis_items"]:
                # 排除只在第一次访视出现的项目（属于基线）
                if item.get("only_in_first_visit", False):
                    continue
                name = item.get("name", "")
                table_names.append(f"{idx}. 生命体征-{name}（SS）")
                idx += 1

    # 第4类：体格检查（SS）— 条件出（排除 only_in_first_visit=true 的项目）
    if has_visit_item("physical_examination"):
        # 直接使用大类名称查找
        detail = load_detail_json("体格检查")
        if detail and detail.get("analysis_items"):
            table_names.append(f"\n## 体格检查（SS）")
            table_names.append("-" * 60)
            for item in detail["analysis_items"]:
                # 排除只在第一次访视出现的项目（属于基线）
                if item.get("only_in_first_visit", False):
                    continue
                name = item.get("name", "")
                table_names.append(f"{idx}. 体格检查{name}（SS）")
                idx += 1

    # 第5类：心电图检查（SS）— 条件出，固定1张（排除 only_in_first_visit=true 的项目）
    if has_visit_item("ecg"):
        # 直接使用大类名称查找（心电图不需要从文件读取，直接生成固定表格）
        table_names.append(f"\n## 心电图检查（SS）")
        table_names.append("-" * 60)
        table_names.append(f"{idx}. 心电图检查（SS）")
        idx += 1

    # 第6类：合并用药（SS）— 条件出，固定1张
    if has_visit_item("concomitant_medication"):
        table_names.append(f"\n## 合并用药（SS）")
        table_names.append("-" * 60)
        table_names.append(f"{idx}. 合并用药（SS）")
        idx += 1

        # 生成合并用药 JSON（构造数据，不从CRF提取）
        info_dir = os.path.join(output_dir, "05_表格信息")
        os.makedirs(info_dir, exist_ok=True)
        cm_json = {
            "table_name": "合并用药（SS）",
            "projects": [
                {
                    "name": "是否有合并用药",
                    "categories": ["是", "否"]
                }
            ]
        }
        cm_file = os.path.join(info_dir, "合并用药（SS）.json")
        with open(cm_file, "w", encoding="utf-8") as f:
            json.dump(cm_json, f, ensure_ascii=False, indent=2)

    # 第7类：器械缺陷（SS）— 条件出，固定1张
    if has_visit_item("device_defects"):
        table_names.append(f"\n## 器械缺陷（SS）")
        table_names.append("-" * 60)
        table_names.append(f"{idx}. 器械缺陷（SS）")
        idx += 1

        # 生成器械缺陷 JSON（构造数据，不从CRF提取）
        info_dir = os.path.join(output_dir, "05_表格信息")
        os.makedirs(info_dir, exist_ok=True)
        dd_json = {
            "table_name": "器械缺陷（SS）",
            "projects": [
                {
                    "name": "是否有器械缺陷",
                    "categories": ["是", "否"]
                }
            ]
        }
        dd_file = os.path.join(info_dir, "器械缺陷（SS）.json")
        with open(dd_file, "w", encoding="utf-8") as f:
            json.dump(dd_json, f, ensure_ascii=False, indent=2)

    # 保存 txt
    txt_output = os.path.join(tables_dir, "安全性评价分析_表格名称.txt")
    with open(txt_output, "w", encoding="utf-8") as f:
        f.write("\n".join(table_names))

    total_tables = idx - 1
    log(f"安全性评价分析: {total_tables} 张表", "INFO")
    log(f"完成: {txt_output}", "DONE")

    # 生成安全性终点表格信息 JSON
    if safety_endpoints:
        info_dir = os.path.join(output_dir, "05_表格信息")
        os.makedirs(info_dir, exist_ok=True)
        from scripts.generate_endpoint_tables import parse_table_names, generate_table_json
        table_names_list = parse_table_names(txt_output)
        count = 0
        for table_name in table_names_list:
            table_json = generate_table_json(table_name, safety_endpoints, [])
            if "endpoint" in table_json:  # 只保存匹配到终点的表
                safe_name = table_name.replace("/", "_").replace("\\", "_")
                with open(os.path.join(info_dir, f"{safe_name}.json"), "w", encoding="utf-8") as f:
                    json.dump(table_json, f, ensure_ascii=False, indent=2)
                count += 1
        log(f"生成表格信息: {info_dir} ({count} 个文件)", "DONE")

    return {"table_results": [{"name": "安全性评价", "success": True}]}


def generate_surgery_tables(state: WorkflowState) -> dict:
    """Step 3e: 手术检查信息表格目录"""
    log("=" * 60, "STEP")
    log("Step 3e: 生成手术检查信息表格目录", "STEP")
    log("=" * 60, "STEP")

    output_dir = state["output_dir"]
    tables_dir = os.path.join(output_dir, "03_表格目录")
    content_dir = os.path.join(output_dir, "02_内容提取")
    os.makedirs(tables_dir, exist_ok=True)

    log("生成手术检查信息表格目录...", "RUN")

    # 读取第二个访视项目文件
    second_visit_file = os.path.join(content_dir, "试验流程_第二个访视项目.json")
    if not os.path.exists(second_visit_file):
        log("第二个访视项目文件不存在，跳过", "WARN")
        return {"table_results": [{"name": "手术检查信息", "success": False}]}

    with open(second_visit_file, "r", encoding="utf-8") as f:
        second_visit_data = json.load(f)

    visit_name = second_visit_data.get("visit_name", "手术检查")
    items = second_visit_data.get("items", [])

    if not items:
        log("第二个访视项目为空，跳过", "WARN")
        return {"table_results": [{"name": "手术检查信息", "success": False}]}

    # 过滤关键词
    exclude_keywords = ["器械缺陷", "合并用药"]

    # 生成表格名称 txt
    table_names = []
    table_names.append(f"\n## {visit_name}信息")
    table_names.append("-" * 60)

    idx = 1
    for item in items:
        item_name = item.get("item_name", "")
        # 过滤包含关键词的项目
        if item_name and not any(kw in item_name for kw in exclude_keywords):
            table_names.append(f"{idx}. {item_name}（FAS）")
            idx += 1

    # 保存 txt
    txt_output = os.path.join(tables_dir, "手术检查信息_表格名称.txt")
    with open(txt_output, "w", encoding="utf-8") as f:
        f.write("\n".join(table_names))

    total_tables = idx - 1
    log(f"手术检查信息: {total_tables} 张表", "INFO")
    log(f"完成: {txt_output}", "DONE")

    return {"table_results": [{"name": "手术检查信息", "success": True}]}


# ===== 构建图 =====
def build_graph():
    """构建 LangGraph 工作流图"""
    graph = StateGraph(WorkflowState)

    # 添加节点
    graph.add_node("explore_toc", explore_toc)

    # Step 2: 并行提取
    graph.add_node("extract_primary_endpoint", extract_primary_endpoint)
    graph.add_node("extract_secondary_endpoint", extract_secondary_endpoint)
    graph.add_node("extract_statistical_plan", extract_statistical_plan)
    graph.add_node("extract_safety_evaluation", extract_safety_evaluation)
    graph.add_node("extract_baseline_analysis", extract_baseline_analysis)
    graph.add_node("extract_sample_info", extract_sample_info_node)
    graph.add_node("extract_stat_methods", extract_stat_methods_node)

    # 统计分析计划分支：书签、访视提取和基线项目提取
    graph.add_node("extract_crf_bookmarks", extract_crf_bookmarks)
    graph.add_node("extract_first_visit_items", extract_first_visit_items)
    graph.add_node("extract_second_visit_items", extract_second_visit_items)
    graph.add_node("extract_baseline_items_from_crf", extract_baseline_items_from_crf)
    graph.add_node("extract_crf_details", extract_crf_details)

    # Step 3: 各分支生成表格
    graph.add_node("generate_primary_tables", generate_primary_tables)
    graph.add_node("generate_secondary_tables", generate_secondary_tables)
    graph.add_node("generate_statistical_tables", generate_statistical_tables)
    graph.add_node("generate_safety_tables", generate_safety_tables)
    graph.add_node("generate_surgery_tables", generate_surgery_tables)

    # 添加边
    # Step 1 → Step 2（并行）
    graph.add_edge(START, "explore_toc")
    graph.add_edge("explore_toc", "extract_primary_endpoint")
    graph.add_edge("explore_toc", "extract_secondary_endpoint")
    graph.add_edge("explore_toc", "extract_statistical_plan")
    graph.add_edge("explore_toc", "extract_safety_evaluation")
    graph.add_edge("explore_toc", "extract_baseline_analysis")
    graph.add_edge("explore_toc", "extract_sample_info")
    graph.add_edge("explore_toc", "extract_stat_methods")

    # 主要终点分支
    graph.add_edge("extract_primary_endpoint", "generate_primary_tables")

    # 次要终点分支
    graph.add_edge("extract_secondary_endpoint", "generate_secondary_tables")

    # 统计分析计划分支：提取 → 书签 → 访视和基线项目并行 → 详情提取 → 表格
    graph.add_edge("extract_statistical_plan", "extract_crf_bookmarks")
    graph.add_edge("extract_crf_bookmarks", "extract_first_visit_items")
    graph.add_edge("extract_crf_bookmarks", "extract_second_visit_items")
    graph.add_edge("extract_crf_bookmarks", "extract_baseline_items_from_crf")
    graph.add_edge("extract_first_visit_items", "extract_crf_details")
    graph.add_edge("extract_second_visit_items", "extract_crf_details")
    graph.add_edge("extract_baseline_items_from_crf", "extract_crf_details")
    graph.add_edge("extract_crf_details", "generate_statistical_tables")

    # 安全性评价分支：安全性提取 → 表格（依赖 extract_crf_details 产出的详情文件）
    graph.add_edge("extract_safety_evaluation", "generate_safety_tables")
    graph.add_edge("extract_crf_details", "generate_safety_tables")

    # 手术检查信息分支：第二个访视项目提取 → 表格
    graph.add_edge("extract_second_visit_items", "generate_surgery_tables")

    # 基线分析分支（直接结束，暂无表格生成）
    graph.add_edge("extract_baseline_analysis", END)

    # 试验样本和统计方法分支（只提取，不生成表格）
    graph.add_edge("extract_sample_info", END)
    graph.add_edge("extract_stat_methods", END)

    # 汇总到 END
    graph.add_edge("generate_primary_tables", END)
    graph.add_edge("generate_secondary_tables", END)
    graph.add_edge("generate_statistical_tables", END)
    graph.add_edge("generate_safety_tables", END)
    graph.add_edge("generate_surgery_tables", END)

    return graph.compile()


# ===== 节点中文名映射 =====
NODE_NAMES = {
    "explore_toc": "探索目录",
    "extract_primary_endpoint": "提取主要终点",
    "extract_secondary_endpoint": "提取次要终点",
    "extract_statistical_plan": "提取统计分析计划",
    "extract_safety_evaluation": "提取安全性评价",
    "extract_baseline_analysis": "提取基线分析",
    "extract_sample_info": "提取试验样本",
    "extract_stat_methods": "提取统计方法",
    "extract_crf_bookmarks": "提取CRF书签",
    "extract_first_visit_items": "提取第一个访视项目",
    "extract_second_visit_items": "提取第二个访视项目",
    "extract_baseline_items_from_crf": "提取基线项目",
    "extract_crf_details": "提取CRF项目详情",
    "generate_primary_tables": "生成主要终点表格",
    "generate_secondary_tables": "生成次要终点表格",
    "generate_statistical_tables": "生成统计分析计划表格",
    "generate_safety_tables": "生成安全性评价表格",
    "generate_surgery_tables": "生成手术检查信息表格",
}

ALL_NODES = list(NODE_NAMES.keys())


def _print_progress(current_idx: int, total: int, node_name: str, done: bool = False):
    """打印进度条"""
    bar_len = 30
    filled = int(bar_len * current_idx / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = current_idx * 100 // total
    status = "✅" if done else "🔄"
    name = NODE_NAMES.get(node_name, node_name)
    # 用 \r 覆盖同一行
    line = f"\r  {status} [{bar}] {pct}% ({current_idx}/{total}) {name}"
    sys.stderr.write(line)
    if done:
        sys.stderr.write("\n")
    sys.stderr.flush()


# ===== 目录整合 =====
def consolidate_tables(output_dir: str):
    """整合所有表格目录 txt 文件，统一编号"""
    tables_dir = os.path.join(output_dir, "03_表格目录")

    # 病例分布固定表
    case_distribution = [
        "各中心病例分布情况（随机化人群）",
        "各中心人群划分情况（随机化人群）",
        "入组病例（随机化人群）",
        "方案偏离（随机化人群）",
    ]

    # 需要拼接的 txt 文件（按顺序）
    txt_files = [
        "统计分析计划_表格名称.txt",
        "手术检查信息_表格名称.txt",
        "主要评价终点_表格名称.txt",
        "次要评价终点_表格名称.txt",
        "安全性评价分析_表格名称.txt",
    ]

    # 收集所有表格名称（保留分类结构）
    all_sections = []

    # 1. 病例分布（固定）
    section_lines = []
    section_lines.append(f"\n## 病例分布（随机化人群）")
    section_lines.append("-" * 60)
    for t in case_distribution:
        section_lines.append(t)  # 序号后面统一重编
    all_sections.append(section_lines)

    # 2. 拼接各 txt 文件
    for fname in txt_files:
        fpath = os.path.join(tables_dir, fname)
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                lines = content.split("\n")
                all_sections.append(lines)

    # 重新编号
    output_lines = []
    output_lines.append("# 表格目录汇总")
    output_lines.append("")
    idx = 1
    for i, section in enumerate(all_sections):
        for line in section:
            stripped = line.strip()
            # 匹配 "数字. 表名" 格式，替换序号
            if stripped and stripped[0].isdigit() and ". " in stripped:
                dot_pos = stripped.index(". ")
                table_name = stripped[dot_pos + 2:]
                output_lines.append(f"| {idx} | {table_name} |")
                idx += 1
            elif stripped.startswith("## "):
                # 分类标题
                title = stripped[3:]
                output_lines.append("")
                output_lines.append(f"## {title}")
                output_lines.append("")
                output_lines.append("| 序号 | 表格名称 |")
                output_lines.append("|:---:|:---|")
            elif stripped.startswith("-" * 10):
                continue
            elif stripped == "":
                continue
            else:
                output_lines.append(f"| {idx} | {stripped} |")
                idx += 1

    # 写入整合文件（放到输出目录根目录）
    output_path = os.path.join(output_dir, "表格目录_汇总.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    total = idx - 1
    print(f"\n  📋 目录整合完成: {total} 张表 → {output_path}", file=sys.stderr)
    return output_path


# ===== 运行工作流 =====
def run_workflow(pdf_path: str, crf_path: str = None, output_dir: str = "sap_output"):
    """运行完整工作流"""
    print(f"\n  SAP 文档处理工作流", file=sys.stderr)
    print(f"  PDF: {pdf_path}", file=sys.stderr)
    print(f"  CRF: {crf_path or '未指定'}", file=sys.stderr)
    print(f"  输出: {output_dir}\n", file=sys.stderr)

    os.makedirs(output_dir, exist_ok=True)

    workflow = build_graph()

    initial_state = {
        "pdf_path": pdf_path,
        "crf_path": crf_path or "",
        "output_dir": output_dir,
        "toc_content": "",
        "toc_file": "",
        "primary_endpoint_file": "",
        "secondary_endpoint_file": "",
        "statistical_plan_file": "",
        "safety_evaluation_file": "",
        "crf_bookmarks_file": "",
        "first_visit_items_file": "",
        "second_visit_items_file": "",
        "baseline_items_from_crf_file": "",
        "crf_details_dir": "",
        "table_results": [],
    }

    import time
    start_time = time.time()

    completed = 0
    total = len(ALL_NODES)
    merged_state = dict(initial_state)
    seen_nodes = set()

    for event in workflow.stream(initial_state, stream_mode="updates"):
        for node_name, node_output in event.items():
            if node_name in seen_nodes:
                continue  # 跳过已执行的节点
            seen_nodes.add(node_name)
            completed += 1
            # 合并节点输出到 state
            if isinstance(node_output, dict):
                merged_state.update(node_output)
            # 打印进度到 stderr
            _print_progress(completed, total, node_name, done=True)
            # 同时输出结构化进度到 stdout 供后端解析
            node_cn = NODE_NAMES.get(node_name, node_name)
            print(f"[PROGRESS] {completed}/{total} {node_cn}", file=sys.stdout, flush=True)

    elapsed = time.time() - start_time

    table_results = merged_state.get("table_results", [])
    success_count = sum(1 for t in table_results if t.get("success"))

    print(f"\n  完成! 耗时 {elapsed:.1f}s | 表格 {success_count}/{len(table_results)} 成功", file=sys.stderr)

    # 目录整合
    try:
        md_path = consolidate_tables(output_dir)
        # 生成 JSON 目录
        from scripts.extract_tables_from_md import extract_tables_from_md
        tables = extract_tables_from_md(md_path)
        json_output = os.path.join(output_dir, "tables.json")
        with open(json_output, "w", encoding="utf-8") as f:
            json.dump({"total": len(tables), "tables": tables}, f, ensure_ascii=False, indent=2)
        print(f"  📋 JSON 目录: {len(tables)} 张表 → {json_output}", file=sys.stderr)
    except Exception as e:
        print(f"\n  ⚠️ 目录整合失败: {e}", file=sys.stderr)

    print(f"  输出目录: {output_dir}\n", file=sys.stderr)

    return merged_state


# ===== 主函数 =====
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SAP 文档处理工作流 (LangGraph)")
    parser.add_argument("pdf_path", help="SAP PDF 文件路径")
    parser.add_argument("--crf", help="CRF PDF 文件路径（用于提取书签）")
    parser.add_argument("--output-dir", default="sap_output", help="输出目录")

    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"错误: 文件不存在 - {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    if args.crf and not os.path.exists(args.crf):
        print(f"错误: CRF 文件不存在 - {args.crf}", file=sys.stderr)
        sys.exit(1)

    run_workflow(args.pdf_path, args.crf, args.output_dir)
