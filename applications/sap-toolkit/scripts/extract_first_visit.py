#!/usr/bin/env python3
"""
试验流程第一个访视项目提取工具
==============================

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
FIRST_VISIT_TOOL = {
    "name": "extract_first_visit_items",
    "description": "提取第一个访视中的所有检查/评估项目",
    "input_schema": {
        "type": "object",
        "properties": {
            "first_visit_name": {
                "type": "string",
                "description": "第一个访视的名称（如：访视1、筛选期等）"
            },
            "visit_time": {
                "type": "string",
                "description": "访视时间（如：-30至0天）"
            },
            "visit_form": {
                "type": "string",
                "description": "访视形式（如：院内访视、门诊访视、电话访视）"
            },
            "items": {
                "type": "array",
                "description": "普通检查/评估项目列表（不含安全性相关项目）",
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
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"},
                        "only_in_first_visit": {"type": "boolean", "description": "是否只在第一个访视中出现（true=只在第一个访视，false=在其他访视也出现）"},
                        "visits": {"type": "array", "description": "该检查项目出现的所有访视名称列表", "items": {"type": "string"}}
                    },
                    "required": ["name", "only_in_first_visit"]
                }
            },
            "physical_examination": {
                "type": "array",
                "description": "体格检查项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"},
                        "only_in_first_visit": {"type": "boolean", "description": "是否只在第一个访视中出现（true=只在第一个访视，false=在其他访视也出现）"},
                        "visits": {"type": "array", "description": "该检查项目出现的所有访视名称列表", "items": {"type": "string"}}
                    },
                    "required": ["name", "only_in_first_visit"]
                }
            },
            "ecg": {
                "type": "array",
                "description": "心电图检查项目列表，无则不填此项",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"},
                        "only_in_first_visit": {"type": "boolean", "description": "是否只在第一个访视中出现（true=只在第一个访视，false=在其他访视也出现）"},
                        "visits": {"type": "array", "description": "该检查项目出现的所有访视名称列表", "items": {"type": "string"}}
                    },
                    "required": ["name", "only_in_first_visit"]
                }
            },
            "laboratory": {
                "type": "array",
                "description": "实验室检查项目列表（如血常规、肝功能、肾功能等），无则不填此项。注意：妊娠检查/孕检不属于此项，应放入 items",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"},
                        "only_in_first_visit": {"type": "boolean", "description": "是否只在第一个访视中出现（true=只在第一个访视，false=在其他访视也出现）"}
                    },
                    "required": ["name", "only_in_first_visit"]
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
                "description": "不良事件类项目列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"}
                    },
                    "required": ["name"]
                }
            },
            "medical_history": {
                "type": "array",
                "description": "病史类项目列表（如病史、眼部手术史、过敏史等）",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"}
                    },
                    "required": ["name"]
                }
            }
        },
        "required": ["first_visit_name", "items"]
    }
}

# 聚合类别的 key 映射
VISIT_SAFETY_KEYS = {
    "vital_signs",
    "physical_examination",
    "ecg",
    "laboratory",
    "device_defects",
    "concomitant_medication",
    "medical_history",
}


# ===== 提取函数 =====
def extract_first_visit(content: str, api_logger: APILogger = None) -> dict:
    """
    提取第一个访视中的所有项目
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = """你是一个临床试验流程分析专家。

你的任务是从试验流程表中，提取第一个访视的所有检查/评估项目。

**先阅读以下规则，再进行思考和提取：**

【必须提取的项目（即使不在第一个访视列中）】
以下项目**必须提取**，即使它们不在筛选期/第一个访视的列中，也要从文档的其他访视中提取：
1. 合并用药 或 非药物治疗 → concomitant_medication（不管文档中叫哪个名字，都用这个 key）
2. 器械缺陷 → device_defects（**只要文档中任何位置提到了"器械缺陷"，就必须提取**，即使它在访视2、访视3或其他访视中。如果文档完全没有提到器械缺陷，则不填此项）
3. 病史类项目（如病史、眼部手术史、过敏史等） → medical_history 数组

【排除规则】
以下项目**不要提取**：
- 知情同意
- 人口学资料/人口学信息
- 入选标准/排除标准/入排标准/入选排除标准
- 随机分组

【分类规则】
以下安全性相关项目必须作为独立 key 提取，不要放入 items 数组：
- 生命体征 → vital_signs
- 体格检查 → physical_examination
- 心电图检查 → ecg
- 实验室检查 → laboratory（注意：妊娠检查/孕检/HCG 检查属于基线项目，应放入 items 数组，不要放入 laboratory）
- 不良事件、严重不良事件 → adverse_events 数组

其他普通项目（如各类检查、评估等）放入 items 数组，只有 item_name，不要 description。

【only_in_first_visit 判断规则】
对于 vital_signs、physical_examination、ecg、laboratory 这4个类别中的**每个子项**，需要单独判断该子项是否**只在第一个访视中出现**：
- 仔细对比试验流程表中所有访视的检查项目列
- 对每个子项（如"感染筛查"、"凝血功能"、"血常规"等）分别判断
- 如果该子项只在第一个访视的列中出现，其他所有访视的列中都没有该子项，则 `only_in_first_visit` 设为 `true`
- 如果该子项在其他任何一个访视的列中也出现了，则 `only_in_first_visit` 设为 `false`
- 注意：同一个类别中的不同子项可能有不同的 `only_in_first_visit` 值
- **重要：仔细阅读备注！** 有些项目虽然在多个访视中都标记为"X"，但不同访视的**检查内容可能不同**。例如：实验室检查在访视1和访视3都有X，但备注说明术前检查包含血常规、凝血功能、血生化，而术后检查只包含血常规、凝血功能。这意味着血生化（肝功能、肾功能）只在访视1做，`only_in_first_visit` 应为 `true`

【visits 提取规则】
对于 vital_signs、physical_examination、ecg 这3个类别中的**每个子项**，需要提取该子项出现的**所有访视名称**：
- 仔细查看试验流程表中所有访视的检查项目列
- 对每个子项（如"生命体征"、"心电图"、"体格检查"等）分别记录它出现在哪些访视中
- **重要：必须使用访视的实际名称**（如"筛选期"、"手术检查"、"随访期"），而不是"访视1"、"访视2"这样的编号
- 例如：如果表格标题是"访视1<br>筛选期"，则使用"筛选期"；如果是"访视2<br>手术检查"，则使用"手术检查"
- 将访视名称放入 `visits` 数组，如 ["筛选期", "手术检查", "随访期"]
- 如果某个子项只在第一个访视出现，visits 数组仍然只包含第一个访视的名称
- 注意：laboratory（实验室检查）不需要提取 visits

【第一个访视识别】
- 第一个访视通常是"筛选期"或"访视1"，但具体名称可能因项目而异
- 请自动识别第一个访视的名称
- 提取该访视中的所有检查项目，不要遗漏"""

    user_message = f"""请分析以下试验流程内容，提取第一个访视的所有检查/评估项目。

# 试验流程内容

{content}

请调用 extract_first_visit_items 工具输出结果。"""

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
            tools=[FIRST_VISIT_TOOL],
            tool_choice={"type": "tool", "name": "extract_first_visit_items"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_first_visit_items")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_first_visit",
            model=MODEL,
            max_tokens=4096,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[FIRST_VISIT_TOOL],
            tool_choice={"type": "tool", "name": "extract_first_visit_items"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_first_visit_items":
            result = block.input
            # 清理：移除值为 false 或空数组的聚合类别 key
            for cat_key in VISIT_SAFETY_KEYS:
                val = result.get(cat_key)
                if val is False or val == [] or val is None:
                    result.pop(cat_key, None)
            items = result.get("items", [])
            first_visit = result.get("first_visit_name", "未知")
            log(f"提取完成: '{first_visit}' 共 {len(items)} 个项目", "DONE")
            return result
        elif block.type == "thinking":
            log(f"思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 主函数 =====
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="试验流程第一个访视项目提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 extract_first_visit.py 试验流程.md
  python3 extract_first_visit.py 试验流程.md --json-output result.json
        """,
    )
    parser.add_argument(
        "input_file",
        help="试验流程文件路径 (如 试验流程.md)",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="JSON 输出文件路径 (默认: 与输入文件同名_第一个访视项目.json)",
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
        args.json_output = f"{base}_第一个访视项目.json"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"试验流程第一个访视项目提取工具", file=sys.stderr)
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

        # 提取第一个访视项目
        result = extract_first_visit(content, api_logger=api_logger)

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
        items = result.get("items", [])
        safety_count = sum(1 for k in VISIT_SAFETY_KEYS if k in result) + len(result.get("adverse_events", []))
        print(f"\n=== {first_visit} 检查项目 (普通{len(items)}个, 安全性类{safety_count}个) ===\n")
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
