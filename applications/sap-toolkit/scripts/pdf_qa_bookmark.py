#!/usr/bin/env python3
"""
PDF 问答工具（书签版）
基于用户问题，利用 PDF 书签定位相关页面并回答
使用 Anthropic Tool Loop 实现
"""

import fitz  # PyMuPDF
import anthropic
import base64
import json
import sys
import os
from typing import Optional
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

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
        "name": "get_pdf_info",
        "description": "获取 PDF 文件的基本信息，包括总页数、文件大小等",
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
        "name": "write_markdown",
        "description": "将 Markdown 内容写入文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Markdown 内容"
                },
                "output_path": {
                    "type": "string",
                    "description": "输出文件路径"
                },
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "写入模式：overwrite 覆盖，append 追加",
                    "default": "overwrite"
                }
            },
            "required": ["content", "output_path"]
        }
    },
    {
        "name": "write_json",
        "description": "将 JSON 数据写入文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "description": "要写入的 JSON 数据对象"
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


def write_markdown(content: str, output_path: str, mode: str = "overwrite") -> dict:
    """写入 Markdown 文件"""
    log(f"写入文件: {output_path} (模式: {mode})", "TOOL")

    try:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        if mode == "append":
            with open(output_path, "a", encoding="utf-8") as f:
                f.write("\n\n" + content)
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)

        file_size = os.path.getsize(output_path)
        log(f"✓ 写入成功: {file_size:,} 字节", "TOOL")
        return {
            "success": True,
            "output_path": output_path,
            "file_size": file_size
        }
    except Exception as e:
        log(f"✗ 写入失败: {e}", "ERROR")
        return {"error": str(e)}


def write_json(data: dict, output_path: str) -> dict:
    """写入 JSON 文件"""
    log(f"写入 JSON: {output_path}", "TOOL")

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
            "file_size": file_size
        }
    except Exception as e:
        log(f"✗ 写入失败: {e}", "ERROR")
        return {"error": str(e)}


# ===== Tool Loop =====
def run_tool_loop(pdf_path: str, user_question: str, output_path: Optional[str] = None, allow_write_dir: Optional[str] = None, output_filename: Optional[str] = None, log_dir: str = None, output_format: str = "markdown"):
    """
    运行 Tool Loop
    基于用户问题，利用书签从 PDF 提取相关内容并回答

    Args:
        pdf_path: PDF 文件路径
        user_question: 用户问题
        output_path: 输出文件路径
        allow_write_dir: 允许写入的目录
        output_filename: 输出文件名
        log_dir: 日志目录
        output_format: 输出格式，"markdown" 或 "json"
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    # 初始化 API 日志记录器
    api_logger = APILogger(log_dir, task_name="PDF书签") if log_dir else None

    # 系统提示
    output_tool_hint = "使用 write_json 工具保存结果为 JSON 格式" if output_format == "json" else "使用 write_markdown 工具保存结果为 Markdown 格式"

    system_prompt = f"""你是一个 PDF 文档分析助手。

当前分析的 PDF 文件: {pdf_path}

【核心原则】
- 每次只能读取一页（read_pdf_page）
- 利用书签（大纲）定位页面，不要盲目逐页读取
- 回答必须基于实际读取的内容，不要编造

【工作流程】你必须严格按照以下步骤执行：

**第一步：获取 PDF 基本信息**
调用 get_pdf_info 获取总页数。

**第二步：获取书签**
调用 get_pdf_bookmarks 获取 PDF 的完整书签（大纲）。
书签是文档的结构化目录，每个书签包含标题和页码。

**第三步：分析书签，定位相关页码**
根据用户问题和书签标题，确定需要读取哪些页面。
- **精准匹配**：只选择书签标题与用户问题完全一致的条目
- 如果书签有层级结构（level 1/2/3），优先匹配更具体的子书签
- 如果找不到精确匹配的书签，返回空结果

**第四步：精准读取相关页面**
只读取第三步定位到的页面，不要多读。
如果书签指向的页面内容不够完整，可以读取相邻页面补充。

**第五步：回答问题**
基于读取的内容，准确回答用户问题。
{output_tool_hint}

【注意事项】
- **精准匹配**：只提取书签标题与用户问题完全一致的内容，禁止同义词匹配和发散匹配
- 如果书签层级很深，先看父级书签判断范围，再看子级精确定位
- 如果没有匹配的书签，返回空结果
- 回答要完整、准确，引用原文内容"""

    # 初始消息
    messages = [
        {
            "role": "user",
            "content": f"请分析以下 PDF 文档，回答我的问题：\n\n{user_question}"
        }
    ]

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"PDF 问答工具（书签版）", file=sys.stderr)
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
        response = client.messages.create(
            model=MODEL_PRO,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            extra_body=extra_body,
            messages=messages
        )

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
                    thinking_content = block.thinking

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
                        tool_input["pdf_path"] = pdf_path  # 强制覆盖
                        result = get_pdf_info(**tool_input)
                    elif tool_name == "get_pdf_bookmarks":
                        tool_input["pdf_path"] = pdf_path  # 强制覆盖
                        result = get_pdf_bookmarks(**tool_input)
                    elif tool_name == "read_pdf_page":
                        tool_input["pdf_path"] = pdf_path  # 强制覆盖
                        result = read_pdf_page(**tool_input, api_logger=api_logger)
                    elif tool_name == "write_markdown":
                        # 如果指定了 allow_write_dir，强制写入到该目录
                        if allow_write_dir:
                            if output_filename:
                                filename = output_filename
                            else:
                                filename = os.path.basename(tool_input.get("output_path", "output.md"))
                            tool_input["output_path"] = os.path.join(allow_write_dir, filename)
                        result = write_markdown(**tool_input)
                    elif tool_name == "write_json":
                        # 如果指定了 allow_write_dir，强制写入到该目录
                        if allow_write_dir:
                            if output_filename:
                                filename = output_filename
                            else:
                                filename = os.path.basename(tool_input.get("output_path", "output.json"))
                            tool_input["output_path"] = os.path.join(allow_write_dir, filename)
                        result = write_json(**tool_input)
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


# ===== 主函数 =====
def main():
    """主函数"""
    if len(sys.argv) < 3:
        print("用法: python3 pdf_qa_bookmark.py <pdf文件> <问题> [输出文件] [--allow-write-dir 目录] [--output-filename 文件名] [--log-dir 目录] [--json]")
        print()
        print("示例:")
        print('  python3 pdf_qa_bookmark.py sap.pdf "主要评价指标是什么？"')
        print('  python3 pdf_qa_bookmark.py sap.pdf "入选标准有哪些？" output.md')
        print('  python3 pdf_qa_bookmark.py sap.pdf "问题" --allow-write-dir ./output/')
        print('  python3 pdf_qa_bookmark.py sap.pdf "问题" --log-dir logs/')
        print('  python3 pdf_qa_bookmark.py sap.pdf "提取裂隙灯检查的分析项目" --json --allow-write-dir ./output/')
        print()
        print("功能:")
        print("  - 书签定位：利用 PDF 书签（大纲）精准定位相关页面")
        print("  - 最小化读取：只读必要的页面，节省时间和成本")
        print("  - 可选将结果保存为 Markdown 或 JSON 文件")
        print("  - --allow-write-dir: 限制 AI 使用 write_markdown/write_json 工具的写入目录")
        print("  - --output-filename: 强制指定输出文件名（配合 --allow-write-dir 使用）")
        print("  - --log-dir: 保存 API 调用日志到指定目录")
        print("  - --json: 使用 JSON 格式输出结果")
        print()
        print("与 pdf_qa.py 的区别:")
        print("  - pdf_qa.py         → 通过读取目录页定位页面（适合有目录页的 PDF）")
        print("  - pdf_qa_bookmark.py → 通过 PDF 书签定位页面（适合有书签但无目录页的 PDF）")
        sys.exit(1)

    pdf_path = sys.argv[1]
    user_question = sys.argv[2]
    output_path = None
    allow_write_dir = None
    output_filename = None
    log_dir = None
    output_format = "markdown"

    # 解析参数
    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == "--allow-write-dir":
            allow_write_dir = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
            i += 2
        elif sys.argv[i] == "--output-filename":
            output_filename = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
            i += 2
        elif sys.argv[i] == "--log-dir":
            log_dir = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
            i += 2
        elif sys.argv[i] == "--json":
            output_format = "json"
            i += 1
        elif output_path is None:
            output_path = sys.argv[i]
            i += 1
        else:
            i += 1

    # 运行 Tool Loop
    result = run_tool_loop(pdf_path, user_question, output_path, allow_write_dir, output_filename, log_dir=log_dir, output_format=output_format)

    # 自动保存（兜底）
    if result and output_path:
        log(f"\n保存结果到: {output_path}", "INFO")
        if output_format == "json":
            try:
                json_data = json.loads(result) if isinstance(result, str) else result
                write_json(json_data, output_path)
            except json.JSONDecodeError:
                log("警告: 无法解析为 JSON，保存为 Markdown", "WARN")
                write_markdown(result, output_path)
        else:
            write_markdown(result, output_path)
        log(f"完成！", "ANSWER")


if __name__ == "__main__":
    main()
