#!/usr/bin/env python3
"""
基线项目过滤 SDK
================

从第一次访视 JSON 中过滤掉人口学、安全性指标、病史类项目，保留基线项目。

用法:
    python3 scripts/filter_baseline.py 试验流程_第一个访视项目.json 安全性评价终点.md
    python3 scripts/filter_baseline.py 试验流程_第一个访视项目.json 安全性评价终点.md --output result.json

输出:
    JSON 文件，包含过滤后的基线项目
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
from config.prompts import FILTER_BASELINE_SYSTEM_PROMPT, FILTER_BASELINE_USER_PROMPT


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
FILTER_TOOL = {
    "name": "filter_baseline_items",
    "description": "过滤访视项目，保留基线项目",
    "input_schema": {
        "type": "object",
        "properties": {
            "baseline_items": {
                "type": "array",
                "description": "过滤后的基线项目列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_name": {
                            "type": "string",
                            "description": "项目名称"
                        },
                        "description": {
                            "type": "string",
                            "description": "项目描述"
                        }
                    },
                    "required": ["item_name"]
                }
            },
            "removed_items": {
                "type": "array",
                "description": "被移除的项目列表（用于调试）",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_name": {
                            "type": "string",
                            "description": "项目名称"
                        },
                        "reason": {
                            "type": "string",
                            "description": "移除原因"
                        }
                    },
                    "required": ["item_name", "reason"]
                }
            }
        },
        "required": ["baseline_items"]
    }
}


# ===== 过滤函数 =====
def filter_baseline_items(first_visit_items: list[dict], safety_content: str, api_logger: APILogger = None) -> dict:
    """
    从第一次访视项目中过滤掉人口学、安全性指标、病史类项目

    Args:
        first_visit_items: 第一次访视项目列表
        safety_content: 安全性评价文件内容
        api_logger: API 日志记录器（可选）

    Returns:
        包含 baseline_items 和 removed_items 的字典
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    # 构建项目文本
    items_text = "\n".join([
        f"- {item.get('item_name', '')}: {item.get('description', '')}"
        for item in first_visit_items
    ])

    system_prompt = FILTER_BASELINE_SYSTEM_PROMPT
    user_message = FILTER_BASELINE_USER_PROMPT.format(
        items_text=items_text,
        safety_content=safety_content
    )

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
            tools=[FILTER_TOOL],
            tool_choice={"type": "tool", "name": "filter_baseline_items"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "filter_baseline_items")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="filter_baseline_items",
            model=MODEL,
            max_tokens=16384,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[FILTER_TOOL],
            tool_choice={"type": "tool", "name": "filter_baseline_items"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "filter_baseline_items":
            result = block.input
            baseline_items = result.get("baseline_items", [])
            removed_items = result.get("removed_items", [])
            log(f"过滤完成: 保留 {len(baseline_items)} 个，移除 {len(removed_items)} 个", "DONE")
            return result
        elif block.type == "thinking":
            log(f"思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 主函数 =====
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="基线项目过滤 SDK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 filter_baseline.py 试验流程_第一个访视项目.json 安全性评价终点.md
  python3 filter_baseline.py 试验流程_第一个访视项目.json 安全性评价终点.md --output result.json
        """,
    )
    parser.add_argument(
        "visit_file",
        help="第一次访视项目 JSON 文件路径",
    )
    parser.add_argument(
        "safety_file",
        help="安全性评价文件路径（.md）",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="输出 JSON 文件路径 (默认: 与访视文件同名_基线项目.json)",
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
    if args.output is None:
        base = os.path.splitext(args.visit_file)[0]
        args.output = f"{base}_基线项目.json"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"基线项目过滤 SDK", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 初始化 API 日志记录器
    api_logger = APILogger(args.log_dir) if args.log_dir else None

    try:
        # 读取访视项目文件
        log(f"读取访视文件: {args.visit_file}", "INFO")
        with open(args.visit_file, "r", encoding="utf-8") as f:
            visit_data = json.load(f)
            first_visit_items = visit_data.get("items", [])
        log(f"访视项目数量: {len(first_visit_items)} 个", "INFO")

        # 读取安全性评价文件
        log(f"读取安全性文件: {args.safety_file}", "INFO")
        with open(args.safety_file, "r", encoding="utf-8") as f:
            safety_content = f.read()
        log(f"安全性文件长度: {len(safety_content)} 字符", "INFO")

        print(f"{'─'*60}", file=sys.stderr)

        # 过滤基线项目
        result = filter_baseline_items(first_visit_items, safety_content, api_logger=api_logger)

        print(f"{'─'*60}", file=sys.stderr)

        # 保存文件
        if not args.no_save:
            log(f"保存 JSON: {args.output}", "SAVE")
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            log(f"保存完成", "SAVE")

        print(f"{'─'*60}", file=sys.stderr)

        # 输出到 stdout
        baseline_items = result.get("baseline_items", [])
        removed_items = result.get("removed_items", [])
        print(f"\n=== 基线项目 ({len(baseline_items)}个) ===\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if not args.no_save:
            log(f"完成！JSON: {args.output}", "DONE")
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
