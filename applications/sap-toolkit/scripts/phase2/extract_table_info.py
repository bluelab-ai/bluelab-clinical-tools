#!/usr/bin/env python3
"""
CRF 表格信息提取工具
====================

根据表名构造 prompt，从 CRF 中提取表格所需的信息。

运行:
    python -m scripts.phase2.extract_table_info <crf.pdf> <表名1> <表名2> ... [--output-dir <输出目录>] [--max-workers 10]
"""

import os
import sys
import json
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import API_KEY, BASE_URL, MODEL, MODEL_PRO, get_thinking_config
from scripts.phase2.pdf_qa_table import run_tool_loop
import anthropic
import fitz


def find_secondary_endpoint_md(output_dir: str) -> str:
    """查找次要评价终点.md文件

    Args:
        output_dir: 输出目录（05_表格信息）

    Returns:
        md文件路径，如果不存在返回None
    """
    parent_dir = os.path.dirname(output_dir)
    md_file = os.path.join(parent_dir, "02_内容提取", "次要评价终点.md")
    if os.path.exists(md_file):
        return md_file
    return None


def generate_from_md_by_ai(table_name: str, md_file: str) -> dict:
    """用 AI 根据 md 内容生成默认指标

    Args:
        table_name: 表名
        md_file: 次要评价终点.md 文件路径

    Returns:
        生成的 JSON 结构，失败返回 None
    """
    import re

    with open(md_file, "r", encoding="utf-8") as f:
        md_content = f.read()

    # 去掉人群标识
    clean_name = re.sub(r'[（(](FAS|PPS|SS)[）)]', '', table_name).strip()

    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

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
            model=MODEL_PRO,
            max_tokens=16384,
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
                result["table_name"] = table_name
                return result

    except Exception as e:
        print(f"⚠️ AI生成失败: {e}", file=sys.stderr)

    return None


# 公共提取规则（排除文本/日期/时间等非分析字段）
EXTRACT_RULES = """1. 提取该表格所需的测量项目或记录项目
2. 每个项目要**一个一个列出**，不要合并
3. 区分定性项目和定量项目：
   - **定性项目**（分类型）：需要列出所有可能的分类选项，使用 categories 字段
   - **定量项目**（数值型）：只需要名称和单位，使用 unit 字段
4. **不要提取以下类型的项目**：
   - 文本输入框（如 Char(100)、Char(200) 等自由填写的文本字段）
   - 日期输入框（如"日期型"、"部分日期型"等日期字段）
   - 时间输入框
   - 这些字段在CRF中通常显示为"XXX Char(N)"或"XXX 日期型"
5. 只提取**有固定分类选项**的定性项目和**有明确单位**的定量项目
6. **项目名称规范化**：去掉CRF中的编码和缩写（如CS、TIA、MHYN等），只保留中文描述名称。例如："不明原因脑卒中CS" → "不明原因脑卒中"，"短暂性脑缺血发作TIA" → "短暂性脑缺血发作\""""

OUTPUT_FORMAT = """必须使用 write_table_json 工具保存结果（不要使用 write_json），数据结构如下：
{{
    "table_name": "<表名>",
    "projects": [
        {{
            "name": "定性项目名称",
            "categories": ["分类1", "分类2", "分类3"]
        }},
        {{
            "name": "定量项目名称",
            "unit": "单位"
        }}
    ]
}}"""

NOTES = """注意：
- 每个 project 必须有 name 字段，以及 categories 或 unit 之一
- 如果没有可分析的项目，projects 设为 []"""


def build_prompt(table_name: str) -> str:
    """根据表名构造提取 prompt"""
    # 过滤"基线信息"，避免 AI 误解为需要提取所有基线信息
    prompt_table_name = table_name.replace("基线信息-", "").replace("基线信息", "")
    if not prompt_table_name.strip():
        prompt_table_name = table_name

    output_fmt = OUTPUT_FORMAT.replace("<表名>", table_name)
    return f"""请从 CRF 中提取"{prompt_table_name}"所需的分析项目。

【提取要求】
{EXTRACT_RULES}

【输出格式】
{output_fmt}

{NOTES}
"""


def build_prompt_for_enrollment(table_name: str) -> str:
    """为入组病例表格构造特殊的提取 prompt（抓取退出试验原因）"""

    return f"""请从 CRF 中提取"试验完成情况"中的"退出试验原因"相关信息。

【提取要求】
1. 找到 CRF 中"试验完成情况"或"研究完成情况"相关的页面
2. 提取所有"退出试验原因"或"退出研究原因"的选项
3. 每个退出原因作为一项，不要合并

【输出格式】
必须使用 write_table_json 工具保存结果（不要使用 write_json），数据结构如下：
{{
    "table_name": "{table_name}",
    "projects": [
        {{
            "name": "退出试验原因",
            "categories": ["原因1", "原因2", "原因3", "..."]
        }}
    ]
}}

注意：
- 只提取退出原因的分类选项，不需要提取具体数据
- 如果有"其他"选项，也要包含在内
"""


def build_prompt_for_deviation(table_name: str) -> str:
    """为方案偏离表格构造特殊的提取 prompt（抓取方案偏离类型）"""

    return f"""请从 CRF 中提取"试验方案偏离情况记录"中的"方案偏离类型"相关信息。

【提取要求】
1. 找到 CRF 中"试验方案偏离情况记录"或"方案偏离"相关的页面
2. 提取所有"方案偏离类型"的选项
3. 每个偏离类型作为一项，不要合并

【输出格式】
必须使用 write_table_json 工具保存结果（不要使用 write_json），数据结构如下：
{{
    "table_name": "{table_name}",
    "projects": [
        {{
            "name": "方案偏离类型",
            "categories": ["类型1", "类型2", "类型3", "..."]
        }}
    ]
}}

注意：
- 只提取方案偏离类型的分类选项，不需要提取具体数据
- 如果有"其他"选项，也要包含在内
"""


def extract_table_info(
    pdf_path: str,
    table_name: str,
    output_dir: str,
    log_dir: str = None,
    category: str = "",
    instruction: str = None
) -> Dict[str, Any]:
    """从 CRF 中提取表格信息

    Args:
        pdf_path: CRF PDF路径
        table_name: 表格名称
        output_dir: 输出目录
        log_dir: 日志目录
        category: 表格分类（如"次要疗效终点分析"），用于判断是否需要AI兜底
        instruction: 自定义提取指令（来自 prompts.json），如果提供则直接使用
    """

    print(f"📋 {table_name} 正在提取...", file=sys.stderr)

    # 构建输出文件名（/ 替换为 _）
    safe_filename = table_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    output_file = os.path.join(output_dir, f"{safe_filename}.json")

    # 构建 prompt：优先使用自定义 instruction，否则走原有逻辑
    if instruction:
        user_question = f"""{instruction}

【提取要求】
{EXTRACT_RULES}

【输出格式】
{OUTPUT_FORMAT}

{NOTES}"""
    elif "入组病例" in table_name:
        user_question = build_prompt_for_enrollment(table_name)
    elif "方案偏离" in table_name:
        user_question = build_prompt_for_deviation(table_name)
    else:
        user_question = build_prompt(table_name)

    try:
        # 运行 tool loop
        result = run_tool_loop(
            pdf_path=pdf_path,
            user_question=user_question,
            allow_write_dir=output_dir,
            output_filename=f"{safe_filename}.json",
            log_dir=log_dir
        )

        # 读取生成的 JSON 文件
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                json_result = json.load(f)

            # 如果 projects 为空，只有次要疗效表格才尝试用 AI 生成默认指标
            if not json_result.get("projects"):
                if "次要疗效" in category:
                    md_file = find_secondary_endpoint_md(output_dir)
                    if md_file:
                        print(f"⚠️ {table_name} projects 为空，尝试用 AI 生成默认指标...", file=sys.stderr)
                        fallback_result = generate_from_md_by_ai(table_name, md_file)
                        if fallback_result and fallback_result.get("projects"):
                            json_result = fallback_result
                            with open(output_file, "w", encoding="utf-8") as f:
                                json.dump(json_result, f, ensure_ascii=False, indent=2)
                            print(f"✅ {table_name} 已用 AI 生成默认指标", file=sys.stderr)
                else:
                    print(f"⚠️ {table_name} projects 为空（非次要疗效表格，跳过AI兜底）", file=sys.stderr)

            # 如果是方案偏离表格，兜底处理
            if "方案偏离" in table_name:
                modified = False

                # 情况1：projects 为空，创建默认的方案偏离 project
                if not json_result.get("projects"):
                    json_result["projects"] = [{
                        "name": "方案偏离类型",
                        "categories": ["方案偏离"]
                    }]
                    modified = True
                else:
                    # 情况2：projects 存在但 categories 为空
                    for proj in json_result["projects"]:
                        if not proj.get("categories"):
                            proj["categories"] = ["方案偏离"]
                            modified = True

                # 如果修改了，保存回文件
                if modified:
                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(json_result, f, ensure_ascii=False, indent=2)

            json_result["success"] = True
            print(f"✅ {table_name} 已提取", file=sys.stderr)
            return json_result
        else:
            # 文件不存在，只有次要疗效表格才尝试用 AI 生成默认指标
            if "次要疗效" in category:
                md_file = find_secondary_endpoint_md(output_dir)
                if md_file:
                    print(f"⚠️ {table_name} 未生成输出文件，尝试用 AI 生成默认指标...", file=sys.stderr)
                    fallback_result = generate_from_md_by_ai(table_name, md_file)
                    if fallback_result and fallback_result.get("projects"):
                        with open(output_file, "w", encoding="utf-8") as f:
                            json.dump(fallback_result, f, ensure_ascii=False, indent=2)
                        fallback_result["success"] = True
                        print(f"✅ {table_name} 已用 AI 生成默认指标", file=sys.stderr)
                        return fallback_result

            print(f"❌ {table_name} 提取失败", file=sys.stderr)
            return {
                "table_name": table_name,
                "success": False,
                "error": "未生成输出文件",
                "projects": []
            }

    except Exception as e:
        print(f"❌ {table_name} 提取失败: {e}", file=sys.stderr)
        return {
            "table_name": table_name,
            "success": False,
            "error": str(e),
            "projects": []
        }


def extract_tables_parallel(
    pdf_path: str,
    table_names: List[str],
    output_dir: str,
    max_workers: int = 10,
    log_dir: str = None,
    category_map: Dict[str, str] = None,
    instructions_map: Dict[str, str] = None
) -> Dict[str, Any]:
    """并行提取多个表格信息

    Args:
        pdf_path: CRF PDF路径
        table_names: 表格名称列表
        output_dir: 输出目录
        max_workers: 最大并行数
        log_dir: 日志目录
        category_map: 表格分类映射 {表名: category}，用于判断是否需要AI兜底
        instructions_map: 自定义指令映射 {表名: instruction}，来自 prompts.json
    """

    print(f"📋 开始并行提取 {len(table_names)} 个表格（最大并行数：{max_workers}）...", file=sys.stderr)

    os.makedirs(output_dir, exist_ok=True)

    results = {}
    failed_items = []

    # 使用线程池并行提取
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_table = {}
        for table_name in table_names:
            category = category_map.get(table_name, "") if category_map else ""
            instruction = instructions_map.get(table_name) if instructions_map else None
            future = executor.submit(
                extract_table_info,
                pdf_path,
                table_name,
                output_dir,
                log_dir,
                category,
                instruction
            )
            future_to_table[future] = table_name

        # 收集结果
        for future in as_completed(future_to_table):
            table_name = future_to_table[future]
            try:
                result = future.result()
                results[table_name] = result

                if not result.get("success"):
                    failed_items.append(table_name)

            except Exception as e:
                failed_items.append(table_name)
                results[table_name] = {
                    "table_name": table_name,
                    "success": False,
                    "error": str(e),
                    "projects": []
                }

    success_count = len([r for r in results.values() if r.get("success")])
    print(f"✅ 提取完成 ({success_count}/{len(table_names)})", file=sys.stderr)

    return {
        "total": len(table_names),
        "success": success_count,
        "failed": len(failed_items),
        "failed_items": failed_items,
        "results": results
    }
