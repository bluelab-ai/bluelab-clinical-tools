#!/usr/bin/env python3
"""
基线分析项目提取工具
====================

从基线分析章节内容中，提取需要进行基线分析的项目。

运行:
    python3 scripts/extract_baseline_items.py 02_内容提取/基线分析.md

输出:
    JSON 文件，包含基线分析项目列表
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
BASELINE_ITEMS_TOOL = {
    "name": "extract_baseline_items",
    "description": "从基线分析章节中提取需要进行基线分析的项目",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "普通基线分析项目列表（不含安全性相关项目）",
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
            },
            "vital_signs": {
                "type": "array",
                "description": "生命体征项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "项目名称"}},
                    "required": ["name"]
                }
            },
            "physical_examination": {
                "type": "array",
                "description": "体格检查项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "项目名称"}},
                    "required": ["name"]
                }
            },
            "ecg": {
                "type": "array",
                "description": "心电图检查项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "项目名称"}},
                    "required": ["name"]
                }
            },
            "laboratory": {
                "type": "array",
                "description": "实验室检查项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "项目名称"}},
                    "required": ["name"]
                }
            },
            "device_defects": {
                "type": "array",
                "description": "器械缺陷项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "项目名称"}},
                    "required": ["name"]
                }
            },
            "concomitant_medication": {
                "type": "array",
                "description": "合并用药或非药物治疗项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "项目名称"}},
                    "required": ["name"]
                }
            },
            "adverse_events": {
                "type": "array",
                "description": "不良事件类项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "项目名称"}},
                    "required": ["name"]
                }
            }
        },
        "required": ["items"]
    }
}

# 聚合类别的 key 集合
BASELINE_SAFETY_KEYS = {
    "vital_signs",
    "physical_examination",
    "ecg",
    "laboratory",
    "device_defects",
    "concomitant_medication",
}


# ===== 提取函数 =====
def extract_baseline_items(content: str, api_logger: APILogger = None) -> dict:
    """
    从基线分析章节中提取需要进行基线分析的项目
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = """你是一个临床试验数据分析专家。

你的任务是从基线分析章节中，提取所有需要进行基线分析的项目。

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
- 只提取文档中明确提到需要进行基线分析的项目
- 不要遗漏任何项目
- 实验室检查如果有多个子项目（如血常规、肝功能、肾功能），每个子项目独立一条"""

    user_message = f"""请分析以下基线分析章节内容，提取所有需要进行基线分析的项目。

# 基线分析内容

{content}

请调用 extract_baseline_items 工具输出结果。"""

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
            tools=[BASELINE_ITEMS_TOOL],
            tool_choice={"type": "tool", "name": "extract_baseline_items"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_baseline_items")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_baseline_items",
            model=MODEL,
            max_tokens=16384,
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
            for cat_key in BASELINE_SAFETY_KEYS:
                val = result.get(cat_key)
                if val is False or val == [] or val is None:
                    result.pop(cat_key, None)
            items = result.get("items", [])
            safety_count = sum(1 for k in BASELINE_SAFETY_KEYS if k in result) + len(result.get("adverse_events", []))
            log(f"提取完成: 普通{len(items)}项, 安全性类{safety_count}项", "DONE")
            return result
        elif block.type == "thinking":
            log(f"思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 主函数 =====
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="基线分析项目提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 extract_baseline_items.py 基线分析.md
  python3 extract_baseline_items.py 基线分析.md --json-output result.json
        """,
    )
    parser.add_argument(
        "input_file",
        help="基线分析文件路径 (如 基线分析.md)",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="JSON 输出文件路径 (默认: 与输入文件同名_基线分析项目.json)",
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
        args.json_output = f"{base}_基线分析项目.json"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"基线分析项目提取工具", file=sys.stderr)
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

        # 提取基线分析项目
        result = extract_baseline_items(content, api_logger=api_logger)

        print(f"{'─'*60}", file=sys.stderr)

        # 保存文件
        if not args.no_save:
            log(f"保存 JSON: {args.json_output}", "SAVE")
            with open(args.json_output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            log(f"保存完成", "SAVE")

        print(f"{'─'*60}", file=sys.stderr)

        # 输出到 stdout
        items = result.get("items", [])
        safety_count = sum(1 for k in BASELINE_SAFETY_KEYS if k in result) + len(result.get("adverse_events", []))
        print(f"\n=== 基线分析项目 (普通{len(items)}项, 安全性类{safety_count}项) ===\n")
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
