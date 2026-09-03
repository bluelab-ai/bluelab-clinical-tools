#!/usr/bin/env python3
"""
表格自动填充工具
使用预定义的 fill_template.py 和 gen_docx.py 填充 Word 表格模板
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.phase2.fill_template import fill_template, get_template_code
from scripts.phase2.gen_docx import gen_docx


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def fill_table(template_code, data_path, output_path):
    """
    填充表格

    参数:
        template_code: 模板代码（如 F_G2_RR）
        data_path: JSON 数据文件路径
        output_path: 输出 Word 文件路径
    """
    log(f"填充表格: {template_code}")

    # 1. 填充模板
    fill_result = fill_template(template_code, data_path)
    if not fill_result["ok"]:
        log(f"✗ 填充失败: {fill_result['error']}")
        return None

    filled_json_path = fill_result["output_path"]
    log(f"✓ 填充完成: {filled_json_path}")

    # 2. 生成 Word
    gen_result = gen_docx(template_code, filled_json_path, output_path)
    if not gen_result["ok"]:
        log(f"✗ 生成失败: {gen_result['error']}")
        return None

    log(f"✓ 生成完成: {gen_result['output_path']}")
    return gen_result["output_path"]


def fill_single_table(template_dir, data_dir, output_dir, data_file, template_codes=None):
    """填充单个表格（用于并行执行）

    参数:
        template_dir: 模板文件目录（未使用，保留兼容性）
        data_dir: 数据文件目录
        output_dir: 输出文件目录
        data_file: 数据文件名
        template_codes: 模板代码字典（可选，从模板代码结果.json读取）
    """
    data_path = os.path.join(data_dir, data_file)
    table_name = os.path.splitext(data_file)[0]

    # 从文件名推断模板代码
    template_code = table_name

    # 如果提供了模板代码字典，使用它来获取正确的模板代码
    # 注意：文件名中 / 被替换为 _，需要还原才能匹配模板代码字典
    lookup_name = table_name.replace("_", "/")
    if template_codes and (table_name in template_codes or lookup_name in template_codes):
        code = template_codes.get(table_name) or template_codes.get(lookup_name)
        if isinstance(code, list):
            # 多个模板代码，组合成一个名称
            template_code = "_".join(code)
        else:
            template_code = code

    # 检查模板代码目录是否存在
    code_dir = os.path.join(os.path.dirname(__file__), "模板代码", template_code)
    if not os.path.exists(code_dir):
        log(f"⚠️ 模板代码不存在: {template_code}")
        return False

    # 填充表格
    output_path = os.path.join(output_dir, f"{table_name}.docx")
    result = fill_table(template_code, data_path, output_path)
    return result is not None


def fill_tables_batch(template_dir, data_dir, output_dir, max_workers=8, script_dir=None, template_codes_file=None):
    """
    批量填充表格（支持并行）

    参数:
        template_dir: 模板文件目录（未使用，保留兼容性）
        data_dir: 数据文件目录
        output_dir: 输出文件目录
        max_workers: 并行数（默认8）
        script_dir: 中间脚本保存目录（未使用，保留兼容性）
        template_codes_file: 模板代码结果.json文件路径（可选）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    os.makedirs(output_dir, exist_ok=True)

    # 读取模板代码字典
    template_codes = {}
    if template_codes_file and os.path.exists(template_codes_file):
        with open(template_codes_file, "r", encoding="utf-8") as f:
            codes_data = json.load(f)
            for table in codes_data.get("tables", []):
                name = table.get("name", "")
                code = table.get("template_code")
                if name and code:
                    template_codes[name] = code

    # 获取所有数据文件
    data_files = []
    for f in os.listdir(data_dir):
        if f.endswith('.json'):
            data_files.append(f)

    log(f"找到 {len(data_files)} 个数据文件，并行数: {max_workers}")

    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        futures = {
            executor.submit(fill_single_table, template_dir, data_dir, output_dir, df, template_codes): df
            for df in data_files
        }

        # 等待完成
        for future in as_completed(futures):
            data_file = futures[future]
            try:
                if future.result():
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                log(f"❌ {data_file}: {e}")
                failed += 1

    log(f"\n✅ 完成: {success} 成功, {failed} 失败")
    return success, failed


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="表格自动填充工具")
    parser.add_argument("template_code", nargs="?", help="模板代码（如 F_G2_RR）")
    parser.add_argument("data", nargs="?", help="JSON 数据文件路径")
    parser.add_argument("output", nargs="?", help="输出文件路径")
    parser.add_argument("--batch", action="store_true", help="批量模式")
    parser.add_argument("--template-dir", help="模板文件目录（批量模式，未使用）")
    parser.add_argument("--data-dir", help="数据文件目录（批量模式）")
    parser.add_argument("--output-dir", help="输出目录（批量模式）")
    parser.add_argument("--max-workers", type=int, default=8, help="并行数（默认8）")

    args = parser.parse_args()

    if args.batch:
        if not args.data_dir or not args.output_dir:
            print("批量模式需要 --data-dir 和 --output-dir", file=sys.stderr)
            sys.exit(1)
        fill_tables_batch(args.template_dir or "", args.data_dir, args.output_dir, args.max_workers)
    else:
        if not args.template_code or not args.data or not args.output:
            print("单个模式需要 template_code、data、output 参数", file=sys.stderr)
            sys.exit(1)
        fill_table(args.template_code, args.data, args.output)
