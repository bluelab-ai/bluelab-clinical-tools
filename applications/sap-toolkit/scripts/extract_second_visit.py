#!/usr/bin/env python3
"""
试验流程第二个访视项目提取工具
==============================

提取规则：提取第二个访视中的所有检查/评估项目。

运行:
    python3 scripts/extract_second_visit.py sap_output/02_内容提取/试验流程.md

输出:
    JSON 文件，包含第二个访视的所有检查项目
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
SECOND_VISIT_TOOL = {
    "name": "extract_second_visit_items",
    "description": "提取第二个访视中的所有检查/评估项目",
    "input_schema": {
        "type": "object",
        "properties": {
            "visit_name": {
                "type": "string",
                "description": "第二个访视的名称（如：手术检查、治疗期等）"
            },
            "visit_time": {
                "type": "string",
                "description": "访视时间（如：0天、术后等）"
            },
            "items": {
                "type": "array",
                "description": "该访视中的所有检查/评估项目列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_name": {
                            "type": "string",
                            "description": "项目名称"
                        }
                    },
                    "required": ["item_name"]
                }
            }
        },
        "required": ["visit_name", "items"]
    }
}


# ===== 提取函数 =====
def extract_second_visit(content: str, api_logger: APILogger = None) -> dict:
    """
    提取第二个访视中的所有项目
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = """你是一个临床试验流程分析专家。

你的任务是从试验流程表中，提取第二个访视的所有检查/评估项目。

【重要】
- 第二个访视通常是"治疗期"、"手术检查"或"访视2"，但具体名称可能因项目而异
- 请自动识别第二个访视的名称
- 提取该访视中的所有检查项目，不要遗漏
- **必须使用访视的实际名称**（如"手术检查"、"治疗期"），而不是"访视2"这样的编号

【提取要求】
- 仔细查看试验流程表中第二列的所有检查项目
- **只提取"只在第二个访视中出现"的项目**，即：
  - 该项目在第二个访视中标记为"X"或有内容
  - 该项目在其他所有访视（第一个、第三个、第四个等）中**都没有**标记为"X"
- 如果某个项目在第二个访视和其他任何一个访视都出现了，**不要提取**
- 项目名称要简洁明了"""

    user_message = f"""请分析以下试验流程内容，提取第二个访视的所有检查/评估项目。

# 试验流程内容

{content}

请调用 extract_second_visit_items 工具输出结果。"""

    log("调用 AI 模型进行分析...", "GEN")

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=1500)

    from scripts.ai_retry import call_ai_with_retry, has_tool_use

    def call_ai():
        return client.messages.create(
            model=MODEL,
            max_tokens=16384,
            temperature=0,
            system=system_prompt,
            tools=[SECOND_VISIT_TOOL],
            tool_choice={"type": "tool", "name": "extract_second_visit_items"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_second_visit_items")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_second_visit",
            model=MODEL,
            max_tokens=16384,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[SECOND_VISIT_TOOL],
            tool_choice={"type": "tool", "name": "extract_second_visit_items"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_second_visit_items":
            result = block.input
            visit_name = result.get("visit_name", "第二个访视")
            items = result.get("items", [])
            log(f"提取完成: '{visit_name}' 共 {len(items)} 个项目", "DONE")
            return result
        elif block.type == "thinking":
            log(f"思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 主函数 =====
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="试验流程第二个访视项目提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 extract_second_visit.py 试验流程.md
  python3 extract_second_visit.py 试验流程.md --json-output result.json
        """,
    )
    parser.add_argument(
        "input_file",
        help="试验流程文件路径 (如 试验流程.md)",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="JSON 输出文件路径 (默认: 与输入文件同名_第二个访视项目.json)",
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
        args.json_output = f"{base}_第二个访视项目.json"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"试验流程第二个访视项目提取工具", file=sys.stderr)
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

        # 提取第二个访视项目
        result = extract_second_visit(content, api_logger=api_logger)

        print(f"{'─'*60}", file=sys.stderr)

        # 保存文件
        if not args.no_save:
            log(f"保存 JSON: {args.json_output}", "SAVE")
            with open(args.json_output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            log(f"保存完成", "SAVE")

        print(f"{'─'*60}", file=sys.stderr)

        # 输出到 stdout
        visit_name = result.get("visit_name", "第二个访视")
        items = result.get("items", [])
        print(f"\n=== {visit_name} 检查项目 ({len(items)}个) ===\n")
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
