#!/usr/bin/env python3
"""
二阶段工作流（LangGraph）
========================

在 graph 一阶段完成后运行：
1. 从 tables.json 提取表名列表
2. 从 CRF PDF 抓取每个表的指标详情 → 05_表格信息/
3. 复制依赖文件（其他json/）
4. 从生命体征/实验室检查生成表格 JSON → 05_表格信息/
5. 生成每个表的模板代码 → 模板代码结果.json
6. 提取模板
7. 填充表格
8. 合并表格
9. 格式化合并表格

运行:
    python -m scripts.phase2.phase2_graph --output-dir <一阶段输出目录> --crf <CRF PDF路径>
"""

import os
import sys
import json
import time
import shutil
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END

from scripts.phase2.batch_extract_tables import load_tables
from scripts.phase2.extract_table_info import extract_tables_parallel
from scripts.phase2.判断指标类型 import generate_template_codes
from scripts.phase2.extract_template import extract_tables_to_folder
from scripts.phase2.fill_table import fill_tables_batch
from scripts.phase2.merge_tables import merge_tables
from scripts.phase2.gen_table_json import main as gen_table_json
from scripts.phase2.format_word_tables import process_document


# ===== State 定义 =====
class Phase2State(TypedDict):
    output_dir: str
    crf_pdf: str
    max_workers: int
    table_names: list[str]
    extract_result: dict
    template_codes: dict
    category_map: dict[str, str]  # 表格分类映射，用于判断是否需要AI兜底
    instructions_map: dict[str, str]  # 自定义指令映射，来自 prompts.json


# ===== 日志 =====
NODE_NAMES = {
    "extract_table_names": "提取表名",
    "batch_extract": "批量抓取指标",
    "copy_dependencies": "复制依赖文件",
    "gen_table_json": "生成表格JSON",
    "gen_template_codes": "生成模板代码",
    "extract_templates": "提取模板",
    "fill_tables": "填充表格",
    "merge_tables": "合并表格",
    "format_tables": "格式化表格",
}

def log(msg: str, level: str = "INFO"):
    prefix = {"INFO": "📋", "STEP": "🔷", "DONE": "✅", "ERROR": "❌", "WARN": "⚠️"}.get(level, "  ")
    line = f"  {prefix} {msg}"
    print(line, file=sys.stderr, flush=True)
    print(f"[LOG:{level}] {msg}", file=sys.stdout, flush=True)


# ===== Node: 提取表名 =====
def extract_table_names(state: Phase2State) -> dict:
    """从 tables.json 提取需要抓取的表格信息列表，同时读取 prompts.json 获取自定义指令"""
    output_dir = state["output_dir"]
    tables_file = os.path.join(output_dir, "tables.json")

    if not os.path.exists(tables_file):
        log(f"❌ tables.json 不存在: {tables_file}")
        return {"table_names": [], "category_map": {}, "instructions_map": {}}

    table_infos = load_tables(tables_file)
    table_names = [t["name"] for t in table_infos]
    category_map = {t["name"]: t["category"] for t in table_infos}

    # 读取 prompts.json（如果存在）
    instructions_map = {}
    prompts_file = os.path.join(output_dir, "prompts.json")
    if os.path.exists(prompts_file):
        with open(prompts_file, "r", encoding="utf-8") as f:
            prompts_data = json.load(f)
        disabled_names = set()
        for item in prompts_data.get("items", []):
            if not item.get("enabled", True):
                disabled_names.add(item["name"])
            else:
                instructions_map[item["name"]] = item["instruction"]
        # 过滤掉禁用的表
        if disabled_names:
            original_count = len(table_names)
            table_names = [n for n in table_names if n not in disabled_names]
            # 同步更新 category_map
            category_map = {k: v for k, v in category_map.items() if k not in disabled_names}
            log(f"📋 prompts.json 中禁用了 {len(disabled_names)} 张表（{original_count} → {len(table_names)}）")
        log(f"📋 使用 prompts.json 中的自定义指令（{len(instructions_map)} 条）")

    log(f"📋 需要抓取 {len(table_names)} 张表的指标信息")
    return {"table_names": table_names, "category_map": category_map, "instructions_map": instructions_map}


# ===== Node: 批量抓取指标 =====
def batch_extract(state: Phase2State) -> dict:
    """从 CRF PDF 批量提取表格指标信息"""
    table_names = state["table_names"]
    if not table_names:
        log("⏭️  无需抓取的表，跳过")
        return {"extract_result": {"total": 0, "success": 0, "failed": 0}}

    crf_pdf = state["crf_pdf"]
    output_dir = state["output_dir"]
    max_workers = state.get("max_workers", 8)

    if not crf_pdf or not os.path.exists(crf_pdf):
        log(f"❌ CRF PDF 不存在: {crf_pdf}")
        return {"extract_result": {"total": 0, "success": 0, "failed": 0, "error": "CRF PDF 不存在"}}

    # 输出到 05_表格信息/
    info_dir = os.path.join(output_dir, "05_表格信息")
    log_dir = os.path.join(output_dir, "logs")

    # 1. 创建人口学信息固定JSON
    demo_table = "人口学信息（FAS）"
    if demo_table in table_names:
        demo_json = {
            "table_name": demo_table,
            "projects": [
                {"name": "性别", "categories": ["男", "女"]},
                {"name": "年龄", "unit": "岁"},
                {"name": "身高", "unit": "cm"},
                {"name": "体重", "unit": "kg"},
                {"name": "BMI", "unit": "kg/m2"}
            ]
        }
        demo_path = os.path.join(info_dir, f"{demo_table}.json")
        with open(demo_path, "w", encoding="utf-8") as f:
            json.dump(demo_json, f, ensure_ascii=False, indent=2)
        log(f"📋 人口学信息: 使用固定JSON")

    # 2. 过滤掉已处理的表格
    tables_to_extract = [t for t in table_names if t != demo_table]

    # 3. 优化：检测 FAS/PPS 配对，只提取一次
    fas_pps_pairs = {}  # base_name -> (fas_name, pps_name)
    tables_to_extract_deduped = []
    skip_tables = set()

    for table_name in tables_to_extract:
        if table_name in skip_tables:
            continue

        # 检查是否是 FAS 或 PPS 版本
        if "（FAS）" in table_name:
            base_name = table_name.replace("（FAS）", "")
            pps_name = base_name + "（PPS）"
            if pps_name in tables_to_extract:
                # 配对成功，只提取 FAS 版本
                fas_pps_pairs[base_name] = (table_name, pps_name)
                tables_to_extract_deduped.append(table_name)
                skip_tables.add(pps_name)
                log(f"📋 配对优化: {base_name} (FAS/PPS 合并提取)")
            else:
                tables_to_extract_deduped.append(table_name)
        elif "（PPS）" in table_name:
            base_name = table_name.replace("（PPS）", "")
            fas_name = base_name + "（FAS）"
            if fas_name not in tables_to_extract:
                # 没有对应的 FAS 版本，正常提取
                tables_to_extract_deduped.append(table_name)
            # 如果有对应的 FAS 版本，跳过（由 FAS 版本处理）
        else:
            tables_to_extract_deduped.append(table_name)

    if not tables_to_extract_deduped:
        log("⏭️  无需抓取的表，跳过")
        return {"extract_result": {"total": 1, "success": 1, "failed": 0}}

    log(f"📋 优化后需提取 {len(tables_to_extract_deduped)} 个表格（原 {len(tables_to_extract)} 个）")

    # 4. 从CRF提取其他表格
    category_map = state.get("category_map", {})
    instructions_map = state.get("instructions_map", {})
    result = extract_tables_parallel(
        pdf_path=crf_pdf,
        table_names=tables_to_extract_deduped,
        output_dir=info_dir,
        max_workers=max_workers,
        log_dir=log_dir,
        category_map=category_map,
        instructions_map=instructions_map
    )

    # 5. 复制 FAS 结果到 PPS 版本
    copied_count = 0
    for base_name, (fas_name, pps_name) in fas_pps_pairs.items():
        fas_safe = fas_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        pps_safe = pps_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        fas_file = os.path.join(info_dir, f"{fas_safe}.json")
        pps_file = os.path.join(info_dir, f"{pps_safe}.json")

        if os.path.exists(fas_file):
            # 读取 FAS 结果，修改 table_name 后保存为 PPS 版本
            with open(fas_file, "r", encoding="utf-8") as f:
                fas_data = json.load(f)
            fas_data["table_name"] = pps_name
            with open(pps_file, "w", encoding="utf-8") as f:
                json.dump(fas_data, f, ensure_ascii=False, indent=2)
            copied_count += 1
            log(f"📋 复制: {fas_name} → {pps_name}")
            # 增加成功计数
            result["total"] += 1
            result["success"] += 1
        else:
            log(f"⚠️ 无法复制: {fas_name} 文件不存在")
            result["total"] += 1
            result["failed"] += 1

    if copied_count > 0:
        log(f"📋 复制了 {copied_count} 个 PPS 版本")

    # 加上人口学信息的成功数
    result["total"] += 1
    result["success"] += 1

    log(f"📊 抓取完成: {result['success']}/{result['total']} 成功")
    return {"extract_result": result}


# ===== Node: 复制依赖文件 =====
def copy_dependencies(state: Phase2State) -> dict:
    """从一阶段输出复制依赖文件到指定位置

    - 基本信息来源/：从 02_内容提取/ 复制（试验样本.json、统计方法.json）
    - 其他json/：从 04_项目详情/ 复制（生命体征.json、心电图.json → 重命名）
    """
    output_dir = state["output_dir"]

    # 1. 从 02_内容提取/ 复制 基本信息来源/
    src_sample = os.path.join(output_dir, "02_内容提取", "试验样本.json")
    src_stats = os.path.join(output_dir, "02_内容提取", "统计方法.json")
    dst_base = os.path.join(output_dir, "基本信息来源")

    os.makedirs(dst_base, exist_ok=True)
    for src, name in [(src_sample, "试验样本.json"), (src_stats, "统计方法.json")]:
        dst = os.path.join(dst_base, name)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            log(f"📁 02_内容提取/{name} → 基本信息来源/{name}")
        else:
            log(f"⚠️  一阶段未生成 {name}")

    # 2. 从 04_项目详情/ 复制 其他json/（生命体征、心电图等汇总数据）
    #    注意文件名映射：心电图.json → 心电图检查（SS）.json
    details_dir = os.path.join(output_dir, "04_项目详情")
    dst_other = os.path.join(output_dir, "其他json")
    os.makedirs(dst_other, exist_ok=True)

    # 文件名映射：graph输出名 → 模板代码需要的名
    rename_map = {
        "生命体征.json": "生命体征.json",
        "心电图.json": "心电图检查（SS）.json",
    }
    for src_name, dst_name in rename_map.items():
        src = os.path.join(details_dir, src_name)
        dst = os.path.join(dst_other, dst_name)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            log(f"📁 04_项目详情/{src_name} → 其他json/{dst_name}")
        else:
            log(f"⚠️  一阶段未生成 {src_name}")

    return {}


# ===== Node: 生成表格 JSON =====
def gen_table_json_node(state: Phase2State) -> dict:
    """从生命体征和实验室检查 JSON 生成表格 JSON"""
    output_dir = state["output_dir"]
    details_dir = os.path.join(output_dir, "04_项目详情")
    info_dir = os.path.join(output_dir, "05_表格信息")
    content_dir = os.path.join(output_dir, "02_内容提取")

    if not os.path.exists(details_dir):
        log("⚠️  04_项目详情不存在，跳过生成表格 JSON")
        return {}

    try:
        created = gen_table_json(details_dir, info_dir, content_dir)
        log(f"📋 生成表格 JSON: {len(created)} 个")
        return {}
    except Exception as e:
        log(f"❌ 生成表格 JSON 失败: {e}")
        return {}


# ===== Node: 生成模板代码 =====
def gen_template_codes(state: Phase2State) -> dict:
    """根据所有依赖文件生成每个表的模板代码"""
    output_dir = state["output_dir"]

    try:
        result = generate_template_codes(output_dir)
        log(f"🏷️  模板代码: {result['total']} 张表有代码")
        return {"template_codes": result}
    except Exception as e:
        log(f"❌ 模板代码生成失败: {e}")
        return {"template_codes": {"total": 0, "tables": [], "error": str(e)}}


# ===== Node: 提取模板 =====
def extract_templates(state: Phase2State) -> dict:
    """根据模板代码从模版库中提取表格模板"""
    output_dir = state["output_dir"]
    json_path = os.path.join(output_dir, "模板代码结果.json")

    if not os.path.exists(json_path):
        log("⚠️  模板代码结果不存在，跳过提取")
        return {}

    try:
        template_dir = os.path.join(output_dir, "模版")
        extract_tables_to_folder(json_path, template_dir)
        log(f"📄 模板提取完成 → {template_dir}")
        return {}
    except Exception as e:
        log(f"❌ 模板提取失败: {e}")
        return {}


# ===== Node: 填充表格 =====
def fill_tables(state: Phase2State) -> dict:
    """根据 JSON 数据填充表格模板"""
    output_dir = state["output_dir"]
    max_workers = state.get("max_workers", 8)

    template_dir = os.path.join(output_dir, "模版")  # 保留，兼容性
    data_dir = os.path.join(output_dir, "05_表格信息")
    output_table_dir = os.path.join(output_dir, "填充的表格")
    template_codes_file = os.path.join(output_dir, "模板代码结果.json")

    if not os.path.exists(data_dir):
        log("⚠️  数据目录不存在，跳过填充")
        return {}

    try:
        success, failed = fill_tables_batch(template_dir, data_dir, output_table_dir, max_workers, template_codes_file=template_codes_file)
        log(f"📝 表格填充: {success} 成功, {failed} 失败 → {output_table_dir}")
        return {}
    except Exception as e:
        log(f"❌ 表格填充失败: {e}")
        return {}


# ===== Node: 合并表格 =====
def merge_all_tables(state: Phase2State) -> dict:
    """合并所有表格到一个 Word 文档"""
    output_dir = state["output_dir"]

    try:
        result = merge_tables(output_dir)
        if result:
            log(f"📑 表格合并完成 → {result}")
        return {}
    except Exception as e:
        log(f"❌ 表格合并失败: {e}")
        return {}


# ===== Node: 格式化合并表格 =====
def format_merged_table(state: Phase2State) -> dict:
    """格式化合并后的表格文档"""
    from pathlib import Path

    output_dir = state["output_dir"]
    merged_file = os.path.join(output_dir, "合并的表格.docx")

    if not os.path.exists(merged_file):
        log("⚠️  合并的表格不存在，跳过格式化")
        return {}

    try:
        result_path = process_document(Path(merged_file))
        log(f"🎨 表格格式化完成 → {result_path}")
        return {}
    except Exception as e:
        log(f"❌ 表格格式化失败: {e}")
        return {}


# ===== Graph 构建 =====
def build_phase2_graph():
    """构建二阶段 LangGraph（完整流程）"""
    graph = StateGraph(Phase2State)

    # 添加节点
    graph.add_node("extract_table_names", extract_table_names)
    graph.add_node("batch_extract", batch_extract)
    graph.add_node("copy_dependencies", copy_dependencies)
    graph.add_node("gen_table_json", gen_table_json_node)
    graph.add_node("gen_template_codes", gen_template_codes)
    graph.add_node("extract_templates", extract_templates)
    graph.add_node("fill_tables", fill_tables)
    graph.add_node("merge_tables", merge_all_tables)
    graph.add_node("format_tables", format_merged_table)

    # 定义流程
    graph.add_edge(START, "extract_table_names")
    graph.add_edge("extract_table_names", "batch_extract")
    graph.add_edge("batch_extract", "copy_dependencies")
    graph.add_edge("copy_dependencies", "gen_table_json")
    graph.add_edge("gen_table_json", "gen_template_codes")
    graph.add_edge("gen_template_codes", "extract_templates")
    graph.add_edge("extract_templates", "fill_tables")
    graph.add_edge("fill_tables", "merge_tables")
    graph.add_edge("merge_tables", "format_tables")
    graph.add_edge("format_tables", END)

    return graph.compile()


def build_phase2a_graph():
    """构建二阶段a：仅提取指标（前4个节点）"""
    graph = StateGraph(Phase2State)

    graph.add_node("extract_table_names", extract_table_names)
    graph.add_node("batch_extract", batch_extract)
    graph.add_node("copy_dependencies", copy_dependencies)
    graph.add_node("gen_table_json", gen_table_json_node)

    graph.add_edge(START, "extract_table_names")
    graph.add_edge("extract_table_names", "batch_extract")
    graph.add_edge("batch_extract", "copy_dependencies")
    graph.add_edge("copy_dependencies", "gen_table_json")
    graph.add_edge("gen_table_json", END)

    return graph.compile()


PHASE2B_NODE_NAMES = {
    "gen_template_codes": "生成模板代码",
    "extract_templates": "提取模板",
    "fill_tables": "填充表格",
    "merge_tables": "合并表格",
    "format_tables": "格式化表格",
}


def build_phase2b_graph():
    """构建二阶段b：生成表格（后5个节点）"""
    graph = StateGraph(Phase2State)

    graph.add_node("gen_template_codes", gen_template_codes)
    graph.add_node("extract_templates", extract_templates)
    graph.add_node("fill_tables", fill_tables)
    graph.add_node("merge_tables", merge_all_tables)
    graph.add_node("format_tables", format_merged_table)

    graph.add_edge(START, "gen_template_codes")
    graph.add_edge("gen_template_codes", "extract_templates")
    graph.add_edge("extract_templates", "fill_tables")
    graph.add_edge("fill_tables", "merge_tables")
    graph.add_edge("merge_tables", "format_tables")
    graph.add_edge("format_tables", END)

    return graph.compile()


# ===== 主函数 =====
def run_phase2(output_dir: str, crf_pdf: str, max_workers: int = 8, steps: str | None = None):
    """运行二阶段工作流

    Args:
        output_dir: 一阶段输出目录（包含 tables.json）
        crf_pdf: CRF PDF 文件路径
        max_workers: 并行抓取数
        steps: "a" 仅提取指标，"b" 仅生成表格，None 运行全部
    """
    start_time = time.time()

    step_label = {"a": "提取指标", "b": "生成表格", None: "抓项目 + 生成模板代码"}[steps]
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"二阶段{f'({step_label})' if steps else ''}：{step_label}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  输出目录: {output_dir}", file=sys.stderr)
    print(f"  CRF PDF: {crf_pdf}", file=sys.stderr)
    print(f"  并行数: {max_workers}", file=sys.stderr)
    print(f"  步骤: {steps or '全部'}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    # 根据步骤选择 graph
    if steps == "a":
        graph = build_phase2a_graph()
        total = 4
    elif steps == "b":
        graph = build_phase2b_graph()
        total = 5
    else:
        graph = build_phase2_graph()
        total = 9

    initial_state = {
        "output_dir": output_dir,
        "crf_pdf": crf_pdf,
        "max_workers": max_workers,
        "table_names": [],
        "extract_result": {},
        "template_codes": {},
        "category_map": {},
        "instructions_map": {}
    }

    completed = 0
    node_names = PHASE2B_NODE_NAMES if steps == "b" else NODE_NAMES

    for event in graph.stream(initial_state, stream_mode="updates"):
        for node_name, node_output in event.items():
            completed += 1
            node_cn = node_names.get(node_name, node_name)
            log(f"[{completed}/{total}] {node_cn} 完成", "DONE")
            print(f"[PROGRESS] {completed}/{total} {node_cn}", file=sys.stdout, flush=True)

    elapsed = time.time() - start_time
    log(f"二阶段{step_label}完成! 耗时 {elapsed:.1f}s", "DONE")
    print(f"  输出目录: {output_dir}\n", file=sys.stderr)

    return {"output_dir": output_dir, "elapsed": elapsed}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="二阶段工作流：抓项目 + 生成模板代码")
    parser.add_argument("--output-dir", required=True, help="一阶段输出目录（包含 tables.json）")
    parser.add_argument("--crf", required=True, help="CRF PDF 文件路径")
    parser.add_argument("--max-workers", type=int, default=8, help="并行抓取数（默认8）")
    parser.add_argument("--steps", choices=["a", "b"], default=None,
                        help="a=仅提取指标(前4节点)，b=仅生成表格(后5节点)，不传=全部运行")

    args = parser.parse_args()

    if not os.path.exists(args.output_dir):
        print(f"错误: 输出目录不存在 - {args.output_dir}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.crf):
        print(f"错误: CRF 文件不存在 - {args.crf}", file=sys.stderr)
        sys.exit(1)

    run_phase2(args.output_dir, args.crf, args.max_workers, steps=args.steps)
