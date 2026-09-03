#!/usr/bin/env python3
"""
PDF 问答工具
基于用户问题，从 PDF 中提取相关页面并回答
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

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import API_KEY, BASE_URL, MODEL, MODEL_PRO, QA_SYSTEM_PROMPT, get_thinking_config, APILogger

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
        "description": "将内容写入文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要写入的内容"
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


def read_pdf_page(pdf_path: str, page_number, api_logger: APILogger = None) -> str:
    """读取 PDF 页面内容，支持单页或多页"""
    # 统一处理为列表，兼容字符串、整数、列表输入
    if isinstance(page_number, int):
        page_numbers = [page_number]
    elif isinstance(page_number, list):
        page_numbers = [int(p) for p in page_number]
    elif isinstance(page_number, str):
        # 去除方括号和空格，按逗号拆分
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
            # 手动追加输出文本（streaming 模式无法从 response 获取）
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


# ===== Tool Loop =====
def run_tool_loop(pdf_path: str, user_question: str, output_path: Optional[str] = None, allow_write_dir: Optional[str] = None, output_filename: Optional[str] = None, log_dir: str = None):
    """
    运行 Tool Loop
    基于用户问题，从 PDF 提取相关内容并回答
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    # 初始化 API 日志记录器
    api_logger = APILogger(log_dir, task_name="PDF问答") if log_dir else None

    # 系统提示
    system_prompt = QA_SYSTEM_PROMPT.format(pdf_path=pdf_path)

    # 初始消息
    messages = [
        {
            "role": "user",
            "content": f"请分析以下 PDF 文档，回答我的问题：\n\n{user_question}"
        }
    ]

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"PDF 问答工具", file=sys.stderr)
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

                    # 执行工具
                    if tool_name == "get_pdf_info":
                        # 强制使用实际的 PDF 路径，防止 AI 传错
                        tool_input["pdf_path"] = pdf_path
                        result = get_pdf_info(**tool_input)
                    elif tool_name == "read_pdf_page":
                        # 强制使用实际的 PDF 路径，防止 AI 传错
                        tool_input["pdf_path"] = pdf_path
                        result = read_pdf_page(**tool_input, api_logger=api_logger)
                    elif tool_name == "write_markdown":
                        # 如果指定了 allow_write_dir，强制写入到该目录
                        if allow_write_dir:
                            # 优先使用 output_filename，否则使用 AI 提供的文件名
                            if output_filename:
                                filename = output_filename
                            else:
                                filename = os.path.basename(tool_input.get("output_path", "output.md"))
                            tool_input["output_path"] = os.path.join(allow_write_dir, filename)
                        result = write_markdown(**tool_input)
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


# ===== Tool Loop（带目录内容） =====
def run_tool_loop_with_toc(
    pdf_path: str,
    user_question: str,
    toc_content: str,
    output_path: Optional[str] = None,
    allow_write_dir: Optional[str] = None,
    output_filename: Optional[str] = None,
    log_dir: str = None
):
    """
    运行 Tool Loop（使用提供的目录内容）

    与 run_tool_loop 的区别：
    - 直接使用传入的 toc_content，跳过"读取目录页"步骤
    - 从"定位相关页面"开始执行
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    # 初始化 API 日志记录器
    api_logger = APILogger(log_dir, task_name="PDF问答") if log_dir else None

    # 系统提示（注入目录内容）
    system_prompt = f"""你是一个 PDF 文档分析助手。

当前分析的 PDF 文件: {pdf_path}

【核心原则】
- 用户提问明确，必须严格匹配目录项，不要猜测或过度探索
- 只读取与用户问题直接相关的目录项对应的页面
- 回答必须基于实际读取的内容，不要编造

【工作流程】你必须严格按照以下步骤执行：

**第一步：获取 PDF 基本信息**
调用 get_pdf_info 获取总页数。

**第二步：使用已提供的目录内容**
以下是已经提取好的目录内容，不需要再次读取：

{toc_content}

**第三步：定位相关页面**
基于上述目录内容，找出与用户问题相关的章节。

【定位规则】
- **严格匹配**：只选择目录标题与用户问题直接相关的条目
- **确定读取范围**：从匹配目录项的起始页码到下一个同级目录项的起始页码
- **不要过度探索**：只读取明确相关的目录项

**第四步：批量读取相关页面**
使用多页读取一次获取所有相关页面：read_pdf_page(pdf_path, page_number=[7, 8])

**第五步：回答问题**
基于读取的内容，准确回答用户问题。

【注意事项】
- 严格遵循"只读相关目录项"的原则，不要过度探索
- 回答要完整、准确，引用原文内容"""

    # 初始消息
    messages = [
        {
            "role": "user",
            "content": f"请分析以下 PDF 文档，回答我的问题：\n\n{user_question}"
        }
    ]

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"PDF 问答工具 (使用预加载目录)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"PDF 文件: {pdf_path}", file=sys.stderr)
    print(f"问题: {user_question}", file=sys.stderr)
    print(f"目录长度: {len(toc_content)} 字符", file=sys.stderr)
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
                func_name=f"run_tool_loop_with_toc (第{iteration}轮)",
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

                    # 执行工具
                    if tool_name == "get_pdf_info":
                        # 强制使用实际的 PDF 路径，防止 AI 传错
                        tool_input["pdf_path"] = pdf_path
                        result = get_pdf_info(**tool_input)
                    elif tool_name == "read_pdf_page":
                        # 强制使用实际的 PDF 路径，防止 AI 传错
                        tool_input["pdf_path"] = pdf_path
                        result = read_pdf_page(**tool_input, api_logger=api_logger)
                    elif tool_name == "write_markdown":
                        # 如果指定了 allow_write_dir，强制写入到该目录
                        if allow_write_dir:
                            # 优先使用 output_filename，否则使用 AI 提供的文件名
                            if output_filename:
                                filename = output_filename
                            else:
                                filename = os.path.basename(tool_input.get("output_path", "output.md"))
                            tool_input["output_path"] = os.path.join(allow_write_dir, filename)
                        result = write_markdown(**tool_input)
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
        print("用法: python3 pdf_qa.py <pdf文件> <问题> [输出文件] [--allow-write-dir 目录] [--output-filename 文件名] [--log-dir 目录]")
        print()
        print("示例:")
        print('  python3 pdf_qa.py sap.pdf "主要评价指标及其统计学方法是什么？"')
        print('  python3 pdf_qa.py sap.pdf "入选标准和排除标准有哪些？" output.md')
        print('  python3 pdf_qa.py sap.pdf "问题" --allow-write-dir ./output/')
        print('  python3 pdf_qa.py sap.pdf "问题" --allow-write-dir ./output/ --output-filename result.md')
        print('  python3 pdf_qa.py sap.pdf "问题" --log-dir logs/')
        print()
        print("功能:")
        print("  - 智能读取：先读目录，再精准定位相关页面")
        print("  - 最小化读取：只读必要的页面，节省时间和成本")
        print("  - 可选将结果保存为 Markdown 文件")
        print("  - --allow-write-dir: 限制 AI 使用 write_markdown 工具的写入目录")
        print("  - --output-filename: 强制指定输出文件名（配合 --allow-write-dir 使用）")
        print("  - --log-dir: 保存 API 调用日志到指定目录")
        sys.exit(1)

    pdf_path = sys.argv[1]
    user_question = sys.argv[2]
    output_path = None
    allow_write_dir = None
    output_filename = None
    log_dir = None

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
        elif output_path is None:
            output_path = sys.argv[i]
            i += 1
        else:
            i += 1

    # 运行 Tool Loop（AI 会使用 write_markdown 工具写入文件）
    result = run_tool_loop(pdf_path, user_question, output_path, allow_write_dir, output_filename, log_dir=log_dir)

    if result:
        log(f"完成！", "ANSWER")


if __name__ == "__main__":
    main()
