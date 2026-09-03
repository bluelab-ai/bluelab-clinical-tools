#!/usr/bin/env python3
"""
SAP 文档处理工作流
==================

完整管线：
  Step 1: 探索目录 → 目录 md 文件
  Step 2: 并行提取内容 → 4 个 md 文件
  Step 3: 生成表格目录 → JSON + 表格名称文件

运行:
    cd sap_toolkit
    python3 scripts/sap_workflow.py examples/sap.pdf

输出结构:
    sap_output/
    ├── 01_目录/
    │   └── sap_目录.md
    ├── 02_内容提取/
    │   ├── 主要评价终点.md
    │   ├── 次要评价终点.md
    │   ├── 安全性评价终点.md
    │   └── 试验流程.md
    └── 03_表格目录/
        ├── 主要评价终点.json
        ├── 主要评价终点_表格名称.txt
        ├── 次要评价终点.json
        └── 次要评价终点_表格名称.txt
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import EXTRACTION_TASKS


# ===== 路径配置 =====
SCRIPT_DIR = Path(__file__).resolve().parent

EXPLORE_TOC_SCRIPT = SCRIPT_DIR / "explore_toc.py"
PDF_QA_SCRIPT = SCRIPT_DIR / "pdf_qa.py"
EXTRACT_GENERATE_SCRIPT = SCRIPT_DIR / "extract_and_generate.py"


# ===== 工具函数 =====
def log(msg: str, level: str = "INFO"):
    """输出日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "📋",
        "STEP": "🔷",
        "RUN": "▶️",
        "DONE": "✅",
        "ERROR": "❌",
        "WARN": "⚠️",
    }.get(level, "  ")
    print(f"[{timestamp}] {prefix} {msg}", file=sys.stderr)


def run_script(script_path: str, args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """运行 Python 脚本"""
    cmd = [sys.executable, script_path] + args
    log(f"运行: {' '.join(cmd)}", "RUN")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result


def create_output_dirs(base_dir: str) -> dict:
    """创建输出目录结构"""
    dirs = {
        "base": base_dir,
        "toc": os.path.join(base_dir, "01_目录"),
        "content": os.path.join(base_dir, "02_内容提取"),
        "tables": os.path.join(base_dir, "03_表格目录"),
        "logs": os.path.join(base_dir, "logs"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


# ===== Step 1: 探索目录 =====
def step_explore_toc(pdf_path: str, toc_dir: str, log_dir: str = None) -> str:
    """探索 PDF 目录，生成目录 md 文件"""
    log("=" * 60, "STEP")
    log("Step 1: 探索目录", "STEP")
    log("=" * 60, "STEP")

    args = [pdf_path, "--save"]
    if log_dir:
        args.extend(["--log-dir", log_dir])

    result = run_script(
        str(EXPLORE_TOC_SCRIPT),
        args,
        timeout=300,
    )

    if result.returncode != 0:
        log(f"目录探索失败: {result.stderr[:500]}", "ERROR")
        return ""

    # 找到生成的目录文件
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    toc_file = f"{pdf_name}_目录.md"

    # explore_toc.py 默认保存在当前目录，移动到目标目录
    if os.path.exists(toc_file):
        import shutil
        dest = os.path.join(toc_dir, toc_file)
        shutil.move(toc_file, dest)
        log(f"目录文件: {dest}", "DONE")
        return dest
    else:
        log("未找到生成的目录文件", "ERROR")
        return ""


# ===== Step 2: 并行提取内容 =====
def extract_single_content(pdf_path: str, task: dict, content_dir: str, log_dir: str = None) -> dict:
    """提取单个内容"""
    name = task["name"]
    prompt = task["prompt"]
    output_file = task["output_filename"]
    output_path = os.path.join(content_dir, output_file)

    log(f"提取: {name}", "RUN")

    args = [pdf_path, prompt, output_path, "--allow-write-dir", content_dir, "--output-filename", output_file]
    if log_dir:
        args.extend(["--log-dir", log_dir])

    result = run_script(
        str(PDF_QA_SCRIPT),
        args,
        timeout=600,
    )

    if result.returncode != 0:
        log(f"提取失败 [{name}]: {result.stderr[:300]}", "ERROR")
        return {"name": name, "success": False, "path": "", "error": result.stderr[:500]}

    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        log(f"完成 [{name}]: {output_path} ({size:,} bytes)", "DONE")
        return {"name": name, "success": True, "path": output_path, "error": ""}
    else:
        log(f"未找到输出文件 [{name}]", "ERROR")
        return {"name": name, "success": False, "path": "", "error": "输出文件未生成"}


def step_extract_content(pdf_path: str, content_dir: str, log_dir: str = None) -> list[dict]:
    """并行提取多个内容"""
    log("=" * 60, "STEP")
    log("Step 2: 并行提取内容", "STEP")
    log("=" * 60, "STEP")

    results = []
    max_workers = min(len(EXTRACTION_TASKS), 4)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for task in EXTRACTION_TASKS:
            future = pool.submit(extract_single_content, pdf_path, task, content_dir, log_dir=log_dir)
            futures[future] = task["name"]

        for future in as_completed(futures):
            name = futures[future]
            try:
                r = future.result()
                results.append(r)
            except Exception as e:
                log(f"异常 [{name}]: {e}", "ERROR")
                results.append({"name": name, "success": False, "path": "", "error": str(e)})

    # 统计
    success = sum(1 for r in results if r["success"])
    log(f"提取完成: {success}/{len(results)} 成功", "DONE")

    return results


# ===== Step 3: 生成表格目录 =====
def step_generate_tables(content_dir: str, tables_dir: str, log_dir: str = None) -> list[dict]:
    """基于提取的内容生成表格目录"""
    log("=" * 60, "STEP")
    log("Step 3: 生成表格目录", "STEP")
    log("=" * 60, "STEP")

    results = []

    # 只处理主要终点和次要终点
    target_files = [
        ("主要评价终点.md", "主要评价终点"),
        ("次要评价终点.md", "次要评价终点"),
    ]

    for filename, name in target_files:
        input_path = os.path.join(content_dir, filename)
        if not os.path.exists(input_path):
            log(f"跳过 [{name}]: 文件不存在", "WARN")
            results.append({"name": name, "success": False, "error": "文件不存在"})
            continue

        log(f"生成表格目录: {name}", "RUN")

        # 输出文件路径
        json_output = os.path.join(tables_dir, f"{name}.json")
        table_output = os.path.join(tables_dir, f"{name}_表格名称.txt")

        args = ["--input", input_path, "--json-output", json_output, "--table-output", table_output]
        if log_dir:
            args.extend(["--log-dir", log_dir])

        result = run_script(
            str(EXTRACT_GENERATE_SCRIPT),
            args,
            timeout=120,
        )

        if result.returncode != 0:
            log(f"生成失败 [{name}]: {result.stderr[:300]}", "ERROR")
            results.append({"name": name, "success": False, "error": result.stderr[:500]})
            continue

        if os.path.exists(json_output) and os.path.exists(table_output):
            log(f"完成 [{name}]: {json_output}", "DONE")
            results.append({"name": name, "success": True, "error": ""})
        else:
            log(f"输出文件不完整 [{name}]", "ERROR")
            results.append({"name": name, "success": False, "error": "输出文件不完整"})

    # 统计
    success = sum(1 for r in results if r["success"])
    log(f"表格目录生成完成: {success}/{len(results)} 成功", "DONE")

    return results


# ===== 主工作流 =====
def run_workflow(pdf_path: str, output_dir: str):
    """运行完整工作流"""
    start_time = time.time()

    print("\n" + "╔" + "═" * 58 + "╗", file=sys.stderr)
    print("║   SAP 文档处理工作流                                    ║", file=sys.stderr)
    print("╠" + "═" * 58 + "╣", file=sys.stderr)
    print(f"║  PDF: {pdf_path:<52}║", file=sys.stderr)
    print(f"║  输出: {output_dir:<51}║", file=sys.stderr)
    print("╚" + "═" * 58 + "╝", file=sys.stderr)

    # 创建输出目录
    dirs = create_output_dirs(output_dir)
    log_dir = dirs["logs"]

    # Step 1: 探索目录
    toc_file = step_explore_toc(pdf_path, dirs["toc"], log_dir=log_dir)

    # Step 2: 并行提取内容
    extract_results = step_extract_content(pdf_path, dirs["content"], log_dir=log_dir)

    # Step 3: 生成表格目录
    table_results = step_generate_tables(dirs["content"], dirs["tables"], log_dir=log_dir)

    # 汇总
    elapsed = time.time() - start_time

    print("\n" + "=" * 60, file=sys.stderr)
    print("🎉 工作流完成!", file=sys.stderr)
    print(f"⏱  总耗时: {elapsed:.1f}s", file=sys.stderr)
    print(f"📁 输出目录: {output_dir}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # 列出生成的文件
    print("\n生成的文件:", file=sys.stderr)
    for root, _, files in os.walk(output_dir):
        for f in sorted(files):
            filepath = os.path.join(root, f)
            size = os.path.getsize(filepath)
            rel_path = os.path.relpath(filepath, output_dir)
            print(f"  {rel_path:<40} ({size:,} bytes)", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="SAP 文档处理工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 sap_workflow.py sap.pdf
  python3 sap_workflow.py sap.pdf --output my_output
        """,
    )
    parser.add_argument("pdf_path", help="SAP PDF 文件路径")
    parser.add_argument("--output", default=None, help="输出目录（默认: <pdf名>_output）")

    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"❌ PDF 文件不存在: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    # 默认输出目录
    if args.output:
        output_dir = args.output
    else:
        pdf_name = os.path.splitext(os.path.basename(args.pdf_path))[0]
        output_dir = f"{pdf_name}_output"

    run_workflow(args.pdf_path, output_dir)


if __name__ == "__main__":
    main()
