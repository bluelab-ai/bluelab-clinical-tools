#!/usr/bin/env python3
"""
试验流程访视项目提取工具
========================

提取规则：提取第一个访视中的所有检查/评估项目。

运行:
    python3 scripts/extract_first_visit.py sap_output/02_内容提取/试验流程.md

输出:
    JSON 文件，包含第一个访视的所有检查项目
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from config import API_KEY, BASE_URL, MODEL, get_thinking_config, APILogger


# ===== 日志 =====
def log(msg: str, level: str = "INFO"):
    """输出日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "📋",
        "GEN": "🤖",
        "SAVE": "💾",
        "ERROR": "❌",
        "DONE": "✅",
    }.get(level, "  ")
    print(f"[{timestamp}] {prefix} {msg}", file=sys.stderr)


# ===== Tool Schema =====
VISIT_DIFF_TOOL = {
    "name": "extract_first_visit_unique_items",
    "description": "提取只在第一个访视中进行，但在其他访视中未进行的检查/评估项目",
    "input_schema": {
        "type": "object",
        "properties": {
            "first_visit_unique_items": {
                "type": "array",
                "description": "只在第一个访视中进行的项目列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_name": {
                            "type": "string",
                            "description": "检查/评估项目名称"
                        },
                        "first_visit_name": {
                            "type": "string",
                            "description": "第一个访视的名称（如：访视1、筛选期等）"
                        },
                        "first_visit_description": {
                            "type": "string",
                            "description": "在第一个访视中的具体描述或要求"
                        },
                        "appears_in_other_visits": {
                            "type": "boolean",
                            "description": "该项目是否在其他访视中出现"
                        },
                        "other_visits_appeared": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "如果在其他访视中出现，列出这些访视的名称"
                        },
                        "reason": {
                            "type": "string",
                            "description": "判断依据"
                        }
                    },
                    "required": ["item_name", "first_visit_name", "appears_in_other_visits", "reason"]
                }
            },
            "first_visit_name": {
                "type": "string",
                "description": "第一个访视的名称"
            },
            "total_visits_analyzed": {
                "type": "integer",
                "description": "分析的访视总数"
            },
            "analysis_summary": {
                "type": "string",
                "description": "分析总结"
            }
        },
        "required": ["first_visit_unique_items", "first_visit_name", "total_visits_analyzed", "analysis_summary"]
    }
}


# ===== 提取规则 =====
EXTRACTION_PROMPT = """## 提取规则

### 目标
从试验流程表中找出**只在第一个访视中进行，但在其他所有访视中都没有进行**的检查/评估项目。

### 判断标准

1. **只在第一个访视出现**：该项目在第一个访视的检查/评估项目列中出现
2. **在其他访视不出现**：该项目在其他所有访视的检查/评估项目列中都没有出现

### 注意事项

- 要区分"完全不出现"和"部分访视出现"
  - 例如：如果某项目在访视1、访视5、访视8出现，则**不是**第一个访视独有的
  - 只有在第一个访视出现，其他**所有**访视都不出现，才算第一个访视独有

- 要区分"检查项目"和"检查项目的具体内容"
  - 例如："实验室检查"在多个访视都出现，但第一个访视的检查项目可能更全面
  - 此时应以"实验室检查"这个大类来判断，而不是细分项目

- 如果有多个流程图，分别分析

### 输出要求

对每个识别出的第一个访视独有项目，提供：
- `item_name`：项目名称
- `first_visit_name`：第一个访视的名称（自动识别）
- `first_visit_description`：在第一个访视中的具体描述
- `appears_in_other_visits`：是否在其他访视出现（应该为 false）
- `other_visits_appeared`：如果在其他访视出现，列出这些访视（应该为空）
- `reason`：判断依据
"""


# ===== 提取函数 =====
def extract_first_visit_diff(content: str, api_logger: APILogger = None) -> dict:
    """
    提取只在第一个访视中进行的项目

    自动识别第一个访视名称，找出只在该访视中出现的项目。
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = """你是一个临床试验流程分析专家。

你的任务是从试验流程表中，找出只在第一个访视中进行，但在其他所有访视中都没有进行的检查/评估项目。

【重要】
- 第一个访视通常是"筛选期"或"访视1"，但具体名称可能因项目而异
- 请自动识别第一个访视的名称
- 仔细对比所有访视的检查项目，准确判断哪些项目只在第一个访视出现"""

    user_message = f"""请分析以下试验流程内容，找出只在第一个访视中进行的项目。

# 试验流程内容

{content}

# 提取规则

{EXTRACTION_PROMPT}

请调用 extract_first_visit_unique_items 工具输出结果。"""

    log("调用 AI 模型进行分析...", "GEN")

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=1500)

    from scripts.ai_retry import call_ai_with_retry, has_tool_use

    def call_ai():
        return client.messages.create(
            model=MODEL,
            max_tokens=4096,
            temperature=0,
            system=system_prompt,
            tools=[VISIT_DIFF_TOOL],
            tool_choice={"type": "tool", "name": "extract_first_visit_unique_items"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_first_visit_unique_items")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_first_visit_diff",
            model=MODEL,
            max_tokens=4096,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[VISIT_DIFF_TOOL],
            tool_choice={"type": "tool", "name": "extract_first_visit_unique_items"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_first_visit_unique_items":
            result = block.input
            items = result.get("first_visit_unique_items", [])
            first_visit = result.get("first_visit_name", "未知")
            log(f"提取完成: 第一个访视为 '{first_visit}'，找到 {len(items)} 个独有项目", "DONE")
            return result
        elif block.type == "thinking":
            log(f"思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 主函数 =====
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="试验流程访视差异提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 extract_visit_diff.py 试验流程.md
  python3 extract_visit_diff.py 试验流程.md --json-output result.json
        """,
    )
    parser.add_argument(
        "input_file",
        help="试验流程文件路径 (如 试验流程.md)",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="JSON 输出文件路径 (默认: 与输入文件同名_访视1独有项目.json)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="不保存文件，只输出到 stdout",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="保存 API 调用日志到指定目录",
    )

    args = parser.parse_args()

    # 设置默认输出路径
    if args.json_output is None:
        base = os.path.splitext(args.input_file)[0]
        args.json_output = f"{base}_访视1独有项目.json"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"试验流程访视差异提取工具", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 初始化 API 日志记录器
    api_logger = APILogger(args.log_dir) if args.log_dir else None

    try:
        # 读取输入文件
        log(f"读取文件: {args.input_file}", "INFO")
        with open(args.input_file, "r", encoding="utf-8") as f:
            content = f.read()
        log(f"文件长度: {len(content)} 字符", "INFO")

        print(f"{'─'*60}", file=sys.stderr)

        # 提取第一个访视独有项目
        result = extract_first_visit_diff(content, api_logger=api_logger)

        print(f"{'─'*60}", file=sys.stderr)

        # 保存文件
        if not args.no_save:
            log(f"保存 JSON: {args.json_output}", "SAVE")
            with open(args.json_output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            log(f"保存完成", "SAVE")

        print(f"{'─'*60}", file=sys.stderr)

        # 输出到 stdout
        first_visit = result.get("first_visit_name", "第一个访视")
        items = result.get("first_visit_unique_items", [])
        print(f"\n=== {first_visit}独有项目 ({len(items)}个) ===\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if not args.no_save:
            log(f"完成！JSON: {args.json_output}", "DONE")
        else:
            log("完成！", "DONE")

    except FileNotFoundError as e:
        log(str(e), "ERROR")
        sys.exit(1)
    except Exception as e:
        log(f"执行失败: {e}", "ERROR")
        raise


if __name__ == "__main__":
    main()
