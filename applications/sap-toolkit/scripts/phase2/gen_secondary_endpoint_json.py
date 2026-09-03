#!/usr/bin/env python3
"""
次要终点指标 JSON 生成工具
==========================

根据表名和次要评价终点.md，通过 AI 直接生成对应的指标 JSON 文件。

用法:
    python -m scripts.phase2.gen_secondary_endpoint_json <md_file> <表名1> <表名2> ... [--output-dir <输出目录>]
"""

import os
import sys
import json
import re

from config import API_KEY, BASE_URL, MODEL
import anthropic


def generate_secondary_endpoint_json(md_file: str, table_names: list[str], output_dir: str) -> list[str]:
    """为次要终点表格生成指标JSON"""
    with open(md_file, "r", encoding="utf-8") as f:
        md_content = f.read()

    os.makedirs(output_dir, exist_ok=True)
    client = anthropic.Anthropic(api_key=API_KEY)
    created_files = []

    for table_name in table_names:
        # 去掉人群标识
        clean_name = re.sub(r'[（(](FAS|PPS|SS)[）)]', '', table_name).strip()

        prompt = f"""根据以下次要评价终点信息，为"{clean_name}"生成指标。

【次要评价终点信息】
{md_content}

【要求】
- table_name 必须是 "{table_name}"
- project name 固定为 "{clean_name}"
- 如果是定量指标（数值型，有单位），使用 unit 字段
- 如果是定性指标（分类型），使用 categories 字段列出分类选项
- 每个 project 只能有 categories 或 unit 之一，不能同时有"""

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                tools=[{
                    "name": "write_table_json",
                    "description": "保存表格信息JSON",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string"},
                            "projects": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "categories": {"type": "array", "items": {"type": "string"}},
                                        "unit": {"type": "string"}
                                    },
                                    "required": ["name"]
                                }
                            }
                        },
                        "required": ["table_name", "projects"]
                    }
                }],
                tool_choice={"type": "any"}
            )

            for content in response.content:
                if content.type == "tool_use" and content.name == "write_table_json":
                    result = content.input
                    # 确保 table_name 正确
                    result["table_name"] = table_name
                    safe_name = table_name.replace("/", "_")
                    output_file = os.path.join(output_dir, f"{safe_name}.json")
                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    created_files.append(output_file)
                    print(f"✅ {table_name}", file=sys.stderr)
                    break

        except Exception as e:
            print(f"❌ {table_name}: {e}", file=sys.stderr)

    return created_files


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("md_file")
    parser.add_argument("table_names", nargs="+")
    parser.add_argument("--output-dir", default="05_表格信息")
    args = parser.parse_args()

    created = generate_secondary_endpoint_json(args.md_file, args.table_names, args.output_dir)
    print(f"\n共生成 {len(created)} 个文件", file=sys.stderr)


if __name__ == "__main__":
    main()
