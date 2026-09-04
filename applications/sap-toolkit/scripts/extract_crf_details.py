#!/usr/bin/env python3
"""
CRF 项目详情提取工具
====================

从 CRF 中提取4个安全性项目和病史的分析项目。

运行:
    python3 scripts/extract_crf_details.py <crf.pdf> <访视项目.json> --output-dir <输出目录>

输出:
    每个项目的提取结果以 JSON 形式输出到单独文件
"""

import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import API_KEY, BASE_URL, MODEL, MODEL_PRO, get_thinking_config, APILogger
import anthropic
import fitz


# ===== 日志 =====
def log(msg: str, level: str = "INFO"):
    """输出日志（简化版）"""
    if level == "ERROR":
        print(f"❌ {msg}", file=sys.stderr)
    elif level == "WARN":
        print(f"⚠️ {msg}", file=sys.stderr)
    # 其他日志不输出


# 大类名称映射
CATEGORY_NAMES = {
    "vital_signs": "生命体征",
    "physical_examination": "体格检查",
    "ecg": "心电图",
    "laboratory": "实验室检查",
}


# ===== 工具 Schema 定义 =====

# 实验室检查工具 schema
LAB_ITEMS_TOOL = {
    "name": "extract_lab_items",
    "description": "提取实验室检查的测量项目",
    "input_schema": {
        "type": "object",
        "required": ["item_name", "analysis_items"],
        "properties": {
            "item_name": {"type": "string", "description": "项目名称"},
            "analysis_items": {
                "type": "array",
                "description": "测量项目列表",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["name", "category"],
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"},
                        "category": {
                            "type": "string",
                            "description": "检查类别",
                            "enum": ["血常规", "肝功能", "肾功能", "凝血功能", "传染病筛查", "尿液检查", "其他"]
                        },
                        "unit": {"type": "string", "description": "测量单位（如 g/L, μmol/L, U/L 等）"}
                    },
                    "additionalProperties": False
                }
            }
        },
        "additionalProperties": False
    }
}

# 非实验室检查工具 schema（生命体征/体格检查/心电图）
SAFETY_ITEMS_TOOL = {
    "name": "extract_safety_items",
    "description": "提取生命体征/体格检查/心电图的测量项目",
    "input_schema": {
        "type": "object",
        "required": ["item_name", "analysis_items"],
        "properties": {
            "item_name": {"type": "string", "description": "项目名称"},
            "analysis_items": {
                "type": "array",
                "description": "测量项目列表",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"},
                        "categories": {
                            "type": "array",
                            "description": "分类型项目的可选值列表",
                            "items": {"type": "string"},
                            "minItems": 1
                        },
                        "unit": {"type": "string", "description": "定量型项目的测量单位"}
                    },
                    "additionalProperties": False
                }
            }
        },
        "additionalProperties": False
    }
}


# ===== 提取安全性项目 =====
def extract_safety_item(
    pdf_path: str,
    item_name: str,
    output_dir: str,
    log_dir: str = None,
    is_lab_item: bool = False,
    only_in_first_visit: bool = False
) -> Dict[str, Any]:
    """使用专用工具 schema 从 CRF 中提取安全性项目的分析项目"""

    print(f"📋 {item_name}正在提取...", file=sys.stderr)

    # 构建输出文件名
    output_file = os.path.join(output_dir, f"{item_name}.json")

    # 选择工具和 prompt
    if is_lab_item:
        tool_def = LAB_ITEMS_TOOL
        tool_name = "extract_lab_items"
        category_hint = """3. 每个项目必须标注所属的**检查类别**（category），类别名称必须使用以下固定值：
   - 血常规、肝功能、肾功能、凝血功能、传染病筛查、尿液检查、其他"""
    else:
        tool_def = SAFETY_ITEMS_TOOL
        tool_name = "extract_safety_items"
        category_hint = """3. 根据项目类型填写字段：
   - **分类型项目**（如下拉框、单选框）：填写 `categories` 数组，列出所有可选值
   - **定量型项目**（需要填写数值）：填写 `unit` 字段，标注测量单位"""

    user_question = f"""请从 CRF 中提取"{item_name}"的测量项目。

【提取要求】
1. 只提取**测量项目**（需要实际检测或评估才能获得结果的项目），不要提取说明性内容（如是否检查、检查日期等）
2. 每个项目要**一个一个列出**，不要合并
{category_hint}

请调用 {tool_name} 工具输出结果。"""

    # 为实验室检查添加特殊提示
    if is_lab_item:
        user_question = f"""请从 CRF 中提取"{item_name}"的测量项目。

【提取要求】
1. 只提取**测量项目**（需要实际检测或评估才能获得结果的项目），不要提取说明性内容（如是否检查、检查日期等）
2. 每个项目要**一个一个列出**，不要合并
{category_hint}
4. 每个项目必须填写 **unit**（测量单位），如 g/L、μmol/L、U/L、10^9/L、% 等。如果CRF中没有明确标注单位，根据医学常识填写该项目的标准单位。

【重要提示】
"{item_name}"在CRF中包含以下4类子页面：
- 血常规
- 血生化（包含肝功能、肾功能等）
- 凝血常规
- 尿常规

你必须**找到并读取所有4类子页面**，然后将所有子页面的测量项目**合并到一个结果中**输出。不要只读一个页面就输出！

请调用 {tool_name} 工具输出结果。"""

    try:
        client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

        # 读取 PDF 书签
        doc = fitz.open(pdf_path)
        toc = doc.get_toc(simple=True)
        doc.close()

        bookmarks = [{"level": l, "title": t, "page": p} for l, t, p in toc]
        bookmarks_text = "\n".join([f"- 第{bm['page']}页: {bm['title']}" for bm in bookmarks])

        system_prompt = f"""你是一个临床试验数据分析专家。

当前分析的 PDF 文件: {pdf_path}

【工作流程】
1. 获取 PDF 书签（使用 get_pdf_bookmarks）
2. 根据书签定位与"{item_name}"相关的页面
3. 读取相关页面内容
4. 提取测量项目并调用 {tool_name} 工具输出结果

【PDF 书签】
{bookmarks_text}"""

        messages = [{"role": "user", "content": user_question}]
        extra_body = get_thinking_config(budget_tokens=2000)

        # 导入 PDF 工具函数
        from scripts.pdf_qa_bookmark import get_pdf_info, get_pdf_bookmarks, read_pdf_page, tools as pdf_tools

        # 合并 PDF 工具和输出工具
        all_tools = pdf_tools + [tool_def]

        # Tool Loop：先读 PDF，再输出结果
        max_iterations = 15
        messages = [{"role": "user", "content": user_question}]

        for iteration in range(max_iterations):
            response = client.messages.create(
                model=MODEL_PRO,
                max_tokens=16384,
                system=system_prompt,
                tools=all_tools,
                extra_body=extra_body,
                messages=messages,
            )

            # 记录 API 调用日志
            if log_dir:
                api_logger = APILogger(log_dir, task_name="CRF详情")
                api_logger.log_call(
                    func_name=f"extract_safety_item ({item_name}) 第{iteration+1}轮",
                    model=MODEL_PRO,
                    max_tokens=16384,
                    system=system_prompt,
                    messages=messages,
                    tools=all_tools,
                    extra_body=extra_body,
                    response=response,
                )

            # 检查是否有输出工具调用
            for block in response.content:
                if block.type == "tool_use" and block.name == tool_name:
                    result = block.input

                    # 将 only_in_first_visit 字段添加到 analysis_items 中，并补充 parent 字段
                    CATEGORY_TO_PARENT = {
                        "血常规": "血常规",
                        "肝功能": "血生化",
                        "肾功能": "血生化",
                        "凝血功能": "凝血常规",
                        "传染病筛查": "其他",
                        "尿液检查": "尿常规",
                        "其他": "其他",
                    }
                    if "analysis_items" in result:
                        for item in result["analysis_items"]:
                            item["only_in_first_visit"] = only_in_first_visit
                            cat = item.get("category", "")
                            item["parent"] = CATEGORY_TO_PARENT.get(cat, "其他")

                    # 保存到文件
                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)

                    items_count = len(result.get("analysis_items", []))
                    print(f"✅ {item_name}已提取 ({items_count}个项目)", file=sys.stderr)
                    return result

            # 处理其他工具调用（PDF 读取）
            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "get_pdf_info":
                            result = get_pdf_info(**block.input)
                        elif block.name == "get_pdf_bookmarks":
                            result = get_pdf_bookmarks(**block.input)
                        elif block.name == "read_pdf_page":
                            result = read_pdf_page(**block.input)
                        else:
                            result = {"error": f"未知工具: {block.name}"}

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False)
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                # AI 没有调用任何工具，强制要求调用输出工具
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": f"请调用 {tool_name} 工具输出提取结果。"})

        print(f"❌ {item_name}提取失败: 超过最大迭代次数", file=sys.stderr)
        return {
            "item_name": item_name,
            "error": "超过最大迭代次数",
            "analysis_items": []
        }

    except Exception as e:
        print(f"❌ {item_name}提取失败: {e}", file=sys.stderr)
        return {
            "item_name": item_name,
            "error": str(e),
            "analysis_items": []
        }


# ===== 提取病史（一轮 SDK） =====
def extract_medical_history(
    pdf_path: str,
    output_dir: str,
    log_dir: str = None
) -> Dict[str, Any]:
    """使用一轮 SDK 从 CRF 书签中提取病史相关的表格"""

    print(f"📋 病史相关表格正在提取...", file=sys.stderr)

    output_file = os.path.join(output_dir, "病史相关表格.json")

    # 获取 CRF 书签
    doc = fitz.open(pdf_path)
    toc = doc.get_toc(simple=True)
    doc.close()

    bookmarks = []
    for level, title, page in toc:
        bookmarks.append({
            "level": level,
            "title": title,
            "page": page,
        })

    # 构建书签文本
    bookmarks_text = "\n".join([
        f"- 第{bm['page']}页: {bm['title']}"
        for bm in bookmarks
    ])

    # 构建 prompt
    system_prompt = """你是一个临床试验数据分析专家。

你的任务是从 CRF 书签中，找出与病史相关的**总表**。

【输出要求】
请使用 write_json 工具保存结果，JSON 格式如下：
{
    "medical_history_tables": [
        {"name": "表格名称", "page": 页码},
        ...
    ]
}

【重要】
- 只提取**总表**，不要提取细节表
- 例如：提取"病史"，不要提取"病史细节"
- 例如：提取"眼部手术史"，不要提取"眼部手术史细节"
- 例如：提取"过敏史"，不要提取"过敏史细节"

【注意】
- 只列出与病史相关的总表（如病史、眼部手术史、过敏史等）"""

    user_message = f"""请分析以下 CRF 书签，找出与病史相关的表格。

# CRF 书签列表

{bookmarks_text}

请调用 write_json 工具输出结果。"""

    try:
        client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

        # Tool schema
        history_tool = {
            "name": "extract_history_tables",
            "description": "提取病史相关的表格",
            "input_schema": {
                "type": "object",
                "properties": {
                    "medical_history_tables": {
                        "type": "array",
                        "description": "病史相关表格列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "表格名称"},
                                "page": {"type": "integer", "description": "页码"}
                            },
                            "required": ["name", "page"]
                        }
                    }
                },
                "required": ["medical_history_tables"]
            }
        }

        messages = [{"role": "user", "content": user_message}]
        extra_body = get_thinking_config(budget_tokens=1000)

        response = client.messages.create(
            model=MODEL,
            max_tokens=16384,
            temperature=0,
            system=system_prompt,
            tools=[history_tool],
            tool_choice={"type": "tool", "name": "extract_history_tables"},
            extra_body=extra_body,
            messages=messages,
        )

        # 记录 API 调用日志
        if log_dir:
            api_logger = APILogger(log_dir, task_name="CRF详情")
            api_logger.log_call(
                func_name="extract_medical_history",
                model=MODEL,
                max_tokens=16384,
                temperature=0,
                system=system_prompt,
                messages=messages,
                tools=[history_tool],
                tool_choice={"type": "tool", "name": "extract_history_tables"},
                extra_body=extra_body,
                response=response,
            )

        # 从 tool_use 响应中提取结果
        for block in response.content:
            if block.type == "tool_use" and block.name == "extract_history_tables":
                result = block.input
                result["success"] = True

                # 保存到文件
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)

                tables = result.get("medical_history_tables", [])
                print(f"✅ 病史相关表格已提取 ({len(tables)}个)", file=sys.stderr)
                return result
            elif block.type == "thinking":
                pass  # 忽略思考过程

        print(f"❌ 病史相关表格提取失败", file=sys.stderr)
        return {
            "success": False,
            "error": "未找到 tool_use 响应",
            "medical_history_tables": []
        }

    except Exception as e:
        print(f"❌ 病史相关表格提取失败: {e}", file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "medical_history_tables": []
        }


# ===== 并行提取安全性项目 =====
def extract_safety_items_parallel(
    pdf_path: str,
    safety_items: List[Dict[str, str]],
    output_dir: str,
    max_workers: int = 4,
    log_dir: str = None,
    lab_item_names: set = None
) -> Dict[str, Any]:
    """并行提取多个安全性项目的详细信息"""

    print(f"📋 安全性项目正在提取 ({len(safety_items)}个)...", file=sys.stderr)

    os.makedirs(output_dir, exist_ok=True)
    if lab_item_names is None:
        lab_item_names = set()

    results = {}
    failed_items = []

    # 使用线程池并行提取
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_item = {}
        item_info_map = {}  # 保存 item_info 以便后续使用
        for item_info in safety_items:
            item_name = item_info.get("name", "")
            if not item_name:
                continue

            # 使用固定的中文名称
            category_name = CATEGORY_NAMES.get(item_name, item_name)
            item_info_map[category_name] = item_info

            is_lab = item_name in lab_item_names
            future = executor.submit(
                extract_safety_item,
                pdf_path,
                category_name,
                output_dir,
                log_dir,
                is_lab,
                item_info.get("only_in_first_visit", False)
            )
            future_to_item[future] = category_name

        # 收集结果
        for future in as_completed(future_to_item):
            item_name = future_to_item[future]
            try:
                result = future.result()
                results[item_name] = result

                # 通过 analysis_items 判断是否成功
                if "analysis_items" not in result:
                    failed_items.append(item_name)

            except Exception as e:
                failed_items.append(item_name)
                results[item_name] = {
                    "item_name": item_name,
                    "error": str(e),
                    "analysis_items": []
                }

    success_count = len([r for r in results.values() if "analysis_items" in r])
    print(f"✅ 安全性项目已提取 ({success_count}/{len(safety_items)})", file=sys.stderr)

    return {
        "results": results,
        "failed_items": failed_items
    }


# ===== 主函数 =====
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="CRF 项目详情提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 extract_crf_details.py crf.pdf 访视项目.json --output-dir 04_项目详情

提取内容:
  - 4个安全性项目（生命体征、体格检查、心电图、实验室检查）
  - 病史相关表格
        """,
    )
    parser.add_argument("crf_pdf", help="CRF PDF 文件路径")
    parser.add_argument("visit_items_file", help="访视项目 JSON 文件路径")
    parser.add_argument("--output-dir", default="04_项目详情", help="输出目录")
    parser.add_argument("--max-workers", type=int, default=4, help="最大并行数")
    parser.add_argument("--log-dir", default=None, help="日志目录")

    args = parser.parse_args()

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"CRF 项目详情提取", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 读取访视项目
    with open(args.visit_items_file, "r", encoding="utf-8") as f:
        visit_data = json.load(f)

    # 提取4个安全性项目
    safety_keys = ["vital_signs", "physical_examination", "ecg", "laboratory"]
    safety_items = []
    lab_item_names = set()
    category_names = {
        "vital_signs": "生命体征",
        "physical_examination": "体格检查",
        "ecg": "心电图",
        "laboratory": "实验室检查",
    }
    for key in safety_keys:
        items = visit_data.get(key, [])
        if items:
            # 使用固定的中文名称
            category_name = category_names.get(key, key)
            # 从访视项目数据中读取 only_in_first_visit 值
            # 如果有多个项目，取第一个项目的值
            only_in_first_visit = items[0].get("only_in_first_visit", False) if items else False
            safety_items.append({"name": category_name, "only_in_first_visit": only_in_first_visit})
            if key == "laboratory":
                lab_item_names.add(category_name)

    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)

    # 并行提取安全性项目
    safety_result = extract_safety_items_parallel(
        pdf_path=args.crf_pdf,
        safety_items=safety_items,
        output_dir=args.output_dir,
        max_workers=args.max_workers,
        log_dir=args.log_dir,
        lab_item_names=lab_item_names
    )

    # 提取病史
    history_result = extract_medical_history(
        pdf_path=args.crf_pdf,
        output_dir=args.output_dir,
        log_dir=args.log_dir
    )

    # 保存汇总结果
    summary_file = os.path.join(args.output_dir, "_summary.json")
    summary = {
        "safety_items": {
            "total": len(safety_items),
            "success": len([r for r in safety_result["results"].values() if "analysis_items" in r]),
            "failed": len(safety_result["failed_items"]),
            "failed_items": safety_result["failed_items"],
            "results": safety_result["results"]
        },
        "medical_history": history_result
    }
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"{'='*60}\n", file=sys.stderr)


if __name__ == "__main__":
    main()
