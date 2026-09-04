#!/usr/bin/env python3
"""
病史类表格提取 SDK
==================

从 CRF 书签 JSON 中提取病史相关的表格名称。

用法:
    python3 scripts/extract_history.py crf_书签.json
    python3 scripts/extract_history.py crf_书签.json --output result.json

输出:
    JSON 文件，包含病史类表格列表
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
from config.prompts import HISTORY_SYSTEM_PROMPT, HISTORY_USER_PROMPT


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
HISTORY_TOOL = {
    "name": "extract_history_tables",
    "description": "从 CRF 书签中提取病史相关的表格",
    "input_schema": {
        "type": "object",
        "properties": {
            "history_tables": {
                "type": "array",
                "description": "病史类表格列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "归一化后的标题，格式为xx史（如：既往史、过敏史、手术史、家族史）"
                        },
                        "page": {
                            "type": "integer",
                            "description": "页码"
                        }
                    },
                    "required": ["title"]
                }
            }
        },
        "required": ["history_tables"]
    }
}


# ===== 提取函数 =====
def extract_history_tables(bookmarks: list[dict], api_logger: APILogger = None) -> dict:
    """
    从 CRF 书签中提取病史相关的表格

    Args:
        bookmarks: CRF 书签列表，每个包含 title, level, page
        api_logger: API 日志记录器（可选）

    Returns:
        包含 history_tables 的字典
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    # 检查 level 2 书签是否都是通用标题（如"注释"）
    level2_bookmarks = [b for b in bookmarks if b.get("level") == 2]
    generic_titles = {"注释", "说明", "备注", "问题页"}
    is_generic = all(b.get("title", "") in generic_titles for b in level2_bookmarks)

    # 如果 level 2 都是通用标题，则使用 level 1；否则使用 level 2
    if is_generic or not level2_bookmarks:
        filtered_bookmarks = [b for b in bookmarks if b.get("level") == 1]
    else:
        filtered_bookmarks = level2_bookmarks

    # 构建书签文本
    bookmarks_text = "\n".join([
        f"- {b.get('title', '')} (页码: {b.get('page', '?')})"
        for b in filtered_bookmarks
    ])

    system_prompt = HISTORY_SYSTEM_PROMPT
    user_message = HISTORY_USER_PROMPT.format(bookmarks_text=bookmarks_text)

    log("调用 AI 模型进行分析...", "GEN")

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=1000)

    from scripts.ai_retry import call_ai_with_retry, has_tool_use

    def call_ai():
        return client.messages.create(
            model=MODEL,
            max_tokens=16384,
            temperature=0,
            system=system_prompt,
            tools=[HISTORY_TOOL],
            tool_choice={"type": "tool", "name": "extract_history_tables"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_history_tables")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_history_tables",
            model=MODEL,
            max_tokens=16384,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[HISTORY_TOOL],
            tool_choice={"type": "tool", "name": "extract_history_tables"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_history_tables":
            result = block.input
            tables = result.get("history_tables", [])
            log(f"提取完成: 共 {len(tables)} 个病史类表格", "DONE")
            return result
        elif block.type == "thinking":
            log(f"思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 主函数 =====
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="病史类表格提取 SDK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 extract_history.py crf_书签.json
  python3 extract_history.py crf_书签.json --output result.json
        """,
    )
    parser.add_argument(
        "input_file",
        help="CRF 书签 JSON 文件路径",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="输出 JSON 文件路径 (默认: 与输入文件同名_病史表格.json)",
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
        base = os.path.splitext(args.input_file)[0]
        args.output = f"{base}_病史表格.json"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"病史类表格提取 SDK", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 初始化 API 日志记录器
    api_logger = APILogger(args.log_dir) if args.log_dir else None

    try:
        # 读取输入文件
        log(f"读取文件: {args.input_file}", "INFO")
        with open(args.input_file, "r", encoding="utf-8") as f:
            bookmarks = json.load(f)
        log(f"书签数量: {len(bookmarks)} 个", "INFO")

        print(f"{'─'*60}", file=sys.stderr)

        # 提取病史类表格
        result = extract_history_tables(bookmarks, api_logger=api_logger)

        print(f"{'─'*60}", file=sys.stderr)

        # 保存文件
        if not args.no_save:
            log(f"保存 JSON: {args.output}", "SAVE")
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            log(f"保存完成", "SAVE")

        print(f"{'─'*60}", file=sys.stderr)

        # 输出到 stdout
        tables = result.get("history_tables", [])
        print(f"\n=== 病史类表格 ({len(tables)}个) ===\n")
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
