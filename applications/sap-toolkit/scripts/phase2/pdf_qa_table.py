#!/usr/bin/env python3
"""
PDF 问答工具（表格提取版）
基于用户问题，利用 PDF 书签定位相关页面并回答
使用 Anthropic Tool Loop 实现
专用于从 CRF 中提取表格项目信息，输出 write_table_json 格式
"""

import fitz  # PyMuPDF
import anthropic
import base64
import json
import sys
import os
from typing import Optional
from datetime import datetime

from config import API_KEY, BASE_URL, MODEL, MODEL_PRO, get_thinking_config, APILogger

# 全局日志
LOG_ENABLED = True


def log(msg: str, level: str = "INFO"):
    """输出日志"""
    if not LOG_ENABLED:
        return
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "📋",
        "TOOL": "🔧",
        "READ": "📖",
        "ANSWER": "✅",
        "ERROR": "❌"
    }.get(level, "  ")
    print(f"[{timestamp}] {prefix} {msg}", file=sys.stderr)


# ===== 工具定义 =====
tools = [
    {
        "name": "get_pdf_bookmarks",
        "description": "获取 PDF 的完整书签（大纲/目录结构）。返回树形结构的书签列表，每个书签包含层级、标题和页码。用于定位需要读取的页面。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "PDF 文件路径"
                }
            },
            "required": ["pdf_path"]
        }
    },
    {
        "name": "read_pdf_page",
        "description": "读取 PDF 页面内容。支持单页或多页。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "PDF 文件路径"
                },
                "page_number": {
                    "description": "页码（从 1 开始）。可以是单个整数或整数列表。",
                    "oneOf": [
                        {"type": "integer"},
                        {"type": "array", "items": {"type": "integer"}, "minItems": 1}
                    ]
                }
            },
            "required": ["pdf_path", "page_number"]
        }
    },
    {
        "name": "write_table_json",
        "description": "保存表格项目提取结果为JSON文件（严格格式）",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "required": ["table_name", "projects"],
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "表格名称"
                        },
                        "projects": {
                            "type": "array",
                            "description": "项目列表（可为空数组，表示该表格无可分析项目）",
                            "items": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "项目名称"
                                    },
                                    "categories": {
                                        "type": "array",
                                        "description": "分类选项（定性项目）",
                                        "items": {"type": "string"},
                                        "minItems": 1
                                    },
                                    "unit": {
                                        "type": "string",
                                        "description": "单位（定量项目）"
                                    }
                                },
                                "additionalProperties": False
                            }
                        }
                    },
                    "additionalProperties": False
                },
                "output_path": {
                    "type": "string",
                    "description": "输出文件路径"
                }
            },
            "required": ["data", "output_path"]
        }
    }
]


# ===== 工具实现 =====
def get_pdf_info(pdf_path: str) -> dict:
    """获取 PDF 信息"""
    log(f"获取 PDF 信息: {pdf_path}", "TOOL")

    if not os.path.exists(pdf_path):
        log(f"文件不存在: {pdf_path}", "ERROR")
        return {"error": f"文件不存在: {pdf_path}"}

    doc = fitz.open(pdf_path)
    info = {
        "total_pages": len(doc),
        "file_size": os.path.getsize(pdf_path),
        "file_name": os.path.basename(pdf_path)
    }
    doc.close()

    log(f"总页数: {info['total_pages']}, 大小: {info['file_size']:,} 字节", "INFO")
    return info


def get_pdf_bookmarks(pdf_path: str) -> dict:
    """获取 PDF 书签（大纲）"""
    log(f"获取 PDF 书签: {pdf_path}", "TOOL")

    if not os.path.exists(pdf_path):
        log(f"文件不存在: {pdf_path}", "ERROR")
        return {"error": f"文件不存在: {pdf_path}"}

    doc = fitz.open(pdf_path)
    toc = doc.get_toc(simple=True)  # 返回 [(level, title, page), ...]
    doc.close()

    if not toc:
        log("PDF 没有书签", "INFO")
        return {"bookmarks": [], "message": "该 PDF 没有书签"}

    # 构建书签树
    bookmarks = []
    for level, title, page in toc:
        indent = "  " * (level - 1)
        bookmarks.append({
            "level": level,
            "title": title,
            "page": page,
            "display": f"{indent}{title} → 第 {page} 页"
        })

    log(f"找到 {len(bookmarks)} 个书签", "INFO")
    return {"bookmarks": bookmarks, "total": len(bookmarks)}


def read_pdf_page(pdf_path: str, page_number, api_logger: APILogger = None) -> str:
    """读取 PDF 页面内容，支持单页或多页"""
    # 统一处理为列表，兼容字符串、整数、列表输入
    if isinstance(page_number, int):
        page_numbers = [page_number]
    elif isinstance(page_number, list):
        page_numbers = [int(p) for p in page_number]
    elif isinstance(page_number, str):
        cleaned = page_number.strip().strip('[]')
        parts = [p.strip() for p in cleaned.split(',') if p.strip()]
        page_numbers = [int(p) for p in parts]
    else:
        page_numbers = [int(page_number)]

    log(f"读取 PDF: 第 {page_numbers} 页", "READ")

    if not os.path.exists(pdf_path):
        log(f"文件不存在: {pdf_path}", "ERROR")
        return f"错误: 文件不存在 - {pdf_path}"

    # 初始化 API 客户端
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    # 打开 PDF
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # 验证所有页码
    for pn in page_numbers:
        page_idx = pn - 1
        if page_idx < 0 or page_idx >= total_pages:
            doc.close()
            return f"错误: 页码 {pn} 超出范围（总页数: {total_pages}）"

    # 转换所有页面为图像
    content = []
    for pn in page_numbers:
        page_idx = pn - 1
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=300)
        image_bytes = pix.tobytes("png")
        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_b64,
            },
        })

    doc.close()

    # 构建提示词
    if len(page_numbers) == 1:
        prompt_text = f"""请提取这个 PDF 页面（第 {page_numbers[0]} 页）的全部文字内容。"""
    else:
        pages_str = ", ".join(str(p) for p in page_numbers)
        prompt_text = f"""请提取以下 PDF 页面（第 {pages_str} 页）的全部文字内容。"""

    content.append({"type": "text", "text": prompt_text})

    # 调用 API 转换（使用 streaming 避免超时）
    try:
        result_text = ""
        thinking_text = ""
        messages = [{"role": "user", "content": content}]
        extra_body = get_thinking_config(budget_tokens=1000)

        with client.messages.stream(
            model=MODEL,
            max_tokens=4096 * len(page_numbers),
            temperature=0,
            extra_body=extra_body,
            messages=messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        result_text += event.delta.text
                    elif hasattr(event.delta, "thinking"):
                        thinking_text += event.delta.thinking

        # 记录 API 调用日志
        if api_logger:
            api_logger.log_call(
                func_name="read_pdf_page (streaming)",
                model=MODEL,
                max_tokens=4096 * len(page_numbers),
                messages=messages,
                extra_body=extra_body,
                response=None,
                thinking_text=thinking_text if thinking_text else None,
            )
            if result_text:
                with open(api_logger.log_file, "a", encoding="utf-8") as f:
                    f.write(f"**Text** ({len(result_text)} 字符, streaming):\n\n")
                    if len(result_text) > 5000:
                        f.write(f"```\n{result_text[:5000]}\n...(已截断)\n```\n\n")
                    else:
                        f.write(f"```\n{result_text}\n```\n\n")

        log(f"  ✓ 第 {page_numbers} 页完成 ({len(result_text)} 字符)", "READ")
        if thinking_text:
            log(f"  ✓ 思考过程: {len(thinking_text)} 字符", "INFO")
        return result_text
    except Exception as e:
        log(f"  ✗ 第 {page_numbers} 页失败: {e}", "ERROR")
        return f"<!-- 第 {page_numbers} 页: 读取失败 - {e} -->"


def write_table_json(data: dict = None, output_path: str = None, **kwargs) -> dict:
    """写入表格项目提取结果的 JSON 文件（带验证）

    兼容两种调用格式：
    - 正确格式: write_table_json(data={...}, output_path="...")
    - AI 直接传字段: write_table_json(table_name="...", projects=[...], output_path="...")
    """
    # 兼容 AI 直接传字段的格式
    if data is None and ("table_name" in kwargs or "projects" in kwargs):
        data = {k: kwargs.pop(k) for k in ["table_name", "projects"] if k in kwargs}
    if output_path is None and "output_path" in kwargs:
        output_path = kwargs.pop("output_path")

    if data is None:
        return {"error": "缺少 data 参数"}
    if output_path is None:
        return {"error": "缺少 output_path 参数"}

    # projects 可能是 JSON 字符串
    if isinstance(data.get("projects"), str):
        try:
            data["projects"] = json.loads(data["projects"])
        except json.JSONDecodeError:
            return {"error": "projects 不是有效的 JSON 字符串"}

    log(f"写入表格 JSON: {output_path}", "TOOL")

    # 验证数据结构
    if "table_name" not in data:
        return {"error": "缺少 table_name 字段"}
    if "projects" not in data:
        return {"error": "缺少 projects 字段"}
    if not isinstance(data["projects"], list):
        return {"error": "projects 必须是数组"}

    # 验证每个 project
    for i, project in enumerate(data["projects"]):
        if "name" not in project:
            return {"error": f"projects[{i}] 缺少 name 字段"}
        has_categories = "categories" in project
        has_unit = "unit" in project
        if not has_categories and not has_unit:
            return {"error": f"projects[{i}] '{project['name']}' 必须有 categories 或 unit"}

    try:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        file_size = os.path.getsize(output_path)
        log(f"✓ 写入成功: {file_size:,} 字节", "TOOL")
        return {
            "success": True,
            "output_path": output_path,
            "file_size": file_size,
            "projects_count": len(data["projects"])
        }
    except Exception as e:
        log(f"✗ 写入失败: {e}", "ERROR")
        return {"error": str(e)}


# ===== Tool Loop =====
def run_tool_loop(pdf_path: str, user_question: str, allow_write_dir: Optional[str] = None, output_filename: Optional[str] = None, log_dir: str = None):
    """
    运行 Tool Loop
    基于用户问题，利用书签从 PDF 提取相关内容并回答

    Args:
        pdf_path: PDF 文件路径
        user_question: 用户问题
        allow_write_dir: 允许写入的目录
        output_filename: 输出文件名
        log_dir: 日志目录
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    # 初始化 API 日志记录器
    api_logger = APILogger(log_dir, task_name="table_extract") if log_dir else None

    # 系统提示
    system_prompt = f"""你是一个 PDF 文档分析助手。

当前分析的 PDF 文件: {pdf_path}

【工作流程】
1. 使用 get_pdf_bookmarks 工具获取书签（目录结构）
2. 根据用户问题，在书签中找到精确匹配的标题和对应页码
3. 使用 read_pdf_page 工具读取该页面内容
4. 基于页面内容，使用 write_table_json 工具保存结果

【注意事项】
- **优先精确匹配**：先尝试找书签标题与用户问题完全一致的内容
- **允许关键词匹配**：如果精确匹配失败，提取问题中的核心关键词（如"器械操作性能"、"图像质量"等），在书签标题中搜索包含这些关键词的页面
- **匹配原则**：关键词匹配时，要求核心含义一致，不要发散匹配无关内容
- 只有当关键词匹配也失败时，才返回空结果
- 基于原文回答问题，不要编造"""

    # 初始消息
    messages = [
        {
            "role": "user",
            "content": f"请分析以下 PDF 文档，回答我的问题：\n\n{user_question}"
        }
    ]

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"PDF 问答工具（表格提取版）", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"PDF 文件: {pdf_path}", file=sys.stderr)
    print(f"问题: {user_question}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    # Tool Loop
    max_iterations = 20
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        log(f"\n{'─'*50}", "INFO")
        log(f"第 {iteration} 轮对话", "INFO")
        log(f"{'─'*50}", "INFO")

        # 调用 API
        log("调用 AI 模型...", "INFO")
        extra_body = get_thinking_config(budget_tokens=2000)

        try:
            response = client.messages.create(
                model=MODEL_PRO,
                max_tokens=4096,
                system=system_prompt,
                tools=tools,
                extra_body=extra_body,
                messages=messages
            )
        except Exception as e:
            log(f"API 调用出错: {e}")
            if iteration < max_iterations:
                log("2秒后重试...")
                import time
                time.sleep(2)
            continue

        # 记录 API 调用日志
        if api_logger:
            api_logger.log_call(
                func_name=f"run_tool_loop (第{iteration}轮)",
                model=MODEL_PRO,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=tools,
                extra_body=extra_body,
                response=response,
            )

        # 检查是否结束
        if response.stop_reason == "end_turn":
            # 提取最终回答和思考过程
            final_answer = ""
            thinking_content = ""
            for block in response.content:
                if block.type == "text":
                    final_answer += block.text
                elif block.type == "thinking":
                    thinking_content += block.thinking

            if thinking_content:
                log(f"思考过程: {thinking_content[:200]}...", "INFO")

            log(f"\n{'═'*50}", "ANSWER")
            log("最终回答:", "ANSWER")
            log(f"{'═'*50}", "ANSWER")

            # 输出到 stdout
            print(final_answer)
            return final_answer

        # 处理工具调用
        if response.stop_reason == "tool_use":
            # 添加 assistant 消息
            messages.append({"role": "assistant", "content": response.content})

            # 处理每个工具调用
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    # 显示工具调用详情
                    log(f"\n调用工具: {tool_name}", "TOOL")
                    log(f"参数: {json.dumps(tool_input, ensure_ascii=False)}", "TOOL")

                    # 执行工具（防护：强制使用传入的 pdf_path）
                    if tool_name == "get_pdf_info":
                        result = get_pdf_info(pdf_path)  # 强制使用传入的路径
                    elif tool_name == "get_pdf_bookmarks":
                        tool_input["pdf_path"] = pdf_path  # 强制覆盖
                        result = get_pdf_bookmarks(**tool_input)
                    elif tool_name == "read_pdf_page":
                        tool_input["pdf_path"] = pdf_path  # 强制覆盖
                        result = read_pdf_page(**tool_input, api_logger=api_logger)
                    elif tool_name == "write_table_json":
                        # 如果指定了 allow_write_dir，强制写入到该目录
                        if allow_write_dir:
                            if output_filename:
                                filename = output_filename
                            else:
                                filename = os.path.basename(tool_input.get("output_path", "output.json"))
                            tool_input["output_path"] = os.path.join(allow_write_dir, filename)
                        result = write_table_json(**tool_input)
                    else:
                        result = {"error": f"未知工具: {tool_name}"}

                    # 显示工具结果摘要
                    if isinstance(result, dict):
                        log(f"结果: {json.dumps(result, ensure_ascii=False)[:300]}", "TOOL")
                    else:
                        log(f"结果: {str(result)[:300]}...", "TOOL")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else result
                    })

            # 添加工具结果消息
            messages.append({"role": "user", "content": tool_results})

    log("错误: 达到最大迭代次数", "ERROR")
    return None
