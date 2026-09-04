#!/usr/bin/env python3
"""
PDF 目录探索工具
从 PDF 中自动识别目录页并输出内容
"""

import fitz  # PyMuPDF
import anthropic
import base64
import json
import sys
import os
from datetime import datetime

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import API_KEY, BASE_URL, MODEL, MODEL_PRO, IS_TOC_PAGE_PROMPT, get_thinking_config, APILogger


def log(msg: str, level: str = "INFO"):
    """输出日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "📋",
        "TOOL": "🔧",
        "READ": "📖",
        "DONE": "✅",
        "ERROR": "❌"
    }.get(level, "  ")
    print(f"[{timestamp}] {prefix} {msg}", file=sys.stderr)


def read_pdf_page(client, pdf_path: str, page_num: int, api_logger: APILogger = None) -> str:
    """读取 PDF 单页内容，转换为 Markdown"""
    log(f"读取 PDF: 第 {page_num} 页", "READ")

    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    pix = page.get_pixmap(dpi=300)
    image_bytes = pix.tobytes("png")
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    doc.close()

    messages = [{
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64,
                },
            },
            {
                "type": "text",
                "text": f"""请提取这个 PDF 页面（第 {page_num} 页）的全部文字内容。"""
            },
        ],
    }]

    response = client.messages.create(
        model=MODEL,
        max_tokens=16384,
        temperature=0,
        messages=messages,
    )

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="read_pdf_page",
            model=MODEL,
            max_tokens=16384,
            messages=messages,
            response=response,
        )

    markdown_content = next(
        (block.text for block in response.content if block.type == "text"),
        ""
    )

    if response.stop_reason == "max_tokens" and not markdown_content:
        # max_tokens 且没有 text block，尝试从 thinking 中提取
        thinking = next(
            (block.thinking for block in response.content if block.type == "thinking"),
            ""
        )
        if thinking:
            markdown_content = thinking
            log(f"  ⚠ 第 {page_num} 页达到 max_tokens，使用 thinking 内容 ({len(markdown_content)} 字符)", "READ")
        else:
            log(f"  ⚠ 第 {page_num} 页达到 max_tokens，无内容返回", "READ")
    elif response.stop_reason == "max_tokens":
        log(f"  ⚠ 第 {page_num} 页达到 max_tokens，部分内容 ({len(markdown_content)} 字符)", "READ")
    else:
        log(f"  ✓ 第 {page_num} 页完成 ({len(markdown_content)} 字符)", "READ")

    return markdown_content


def is_toc_page(client, page_content: str, page_num: int, api_logger: APILogger = None) -> bool:
    """让 AI 判断是否是目录页"""
    try:
        messages = [{
            "role": "user",
            "content": f"{IS_TOC_PAGE_PROMPT}\n\n{page_content[:2000]}"
        }]
        extra_body = get_thinking_config(budget_tokens=500)

        response = client.messages.create(
            model=MODEL_PRO,
            max_tokens=16384,
            extra_body=extra_body,
            messages=messages,
        )

        # 记录 API 调用日志
        if api_logger:
            api_logger.log_call(
                func_name="is_toc_page",
                model=MODEL_PRO,
                max_tokens=16384,
                messages=messages,
                extra_body=extra_body,
                response=response,
            )

        result = ""
        for block in response.content:
            if block.type == "text":
                result = block.text.strip().lower()
                break

        log(f"  AI 判断: '{result}'", "READ")
        return "true" in result

    except Exception as e:
        log(f"  AI 判断失败: {e}", "ERROR")
        return False


def explore_toc(pdf_path: str, max_pages: int = 15, log_dir: str = None) -> dict:
    """
    自动探索 PDF 目录

    从第1页开始逐页读取，用 AI 识别目录页并收集内容，遇到非目录页时停止。

    返回:
        {
            "found": True/False,
            "pages": [2, 3, 4],  # 目录页码
            "page_count": 3,
            "content": "..."     # 合并的目录内容
        }
    """
    log(f"探索目录: {pdf_path}", "TOOL")

    if not os.path.exists(pdf_path):
        log(f"文件不存在: {pdf_path}", "ERROR")
        return {"error": f"文件不存在: {pdf_path}"}

    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    # 初始化 API 日志记录器
    api_logger = APILogger(log_dir, task_name="目录探索") if log_dir else None
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    toc_pages = []
    toc_content = []
    found_toc = False
    max_check = min(max_pages, total_pages)

    for page_num in range(1, max_check + 1):
        log(f"\n检查第 {page_num} 页...", "READ")

        # 读取页面内容
        page_content = read_pdf_page(client, pdf_path, page_num, api_logger=api_logger)

        # 内容为空时跳过判断
        if not page_content or not page_content.strip():
            log(f"  ⚠ 第 {page_num} 页内容为空，跳过", "READ")
            if found_toc:
                break
            continue

        # AI 判断是否是目录页
        is_toc = is_toc_page(client, page_content, page_num, api_logger=api_logger)

        if is_toc:
            if not found_toc:
                found_toc = True
                log(f"  ✓ 第 {page_num} 页是目录页（首次发现）", "READ")
            else:
                log(f"  ✓ 第 {page_num} 页是目录页（继续）", "READ")
            toc_pages.append(page_num)
            toc_content.append(page_content)
        else:
            if found_toc:
                log(f"  ✗ 第 {page_num} 页不是目录页，停止探索", "READ")
                break
            else:
                log(f"  - 第 {page_num} 页不是目录页，跳过", "READ")

    # 构建结果
    if found_toc:
        combined_content = "\n\n---\n\n".join(toc_content)
        log(f"\n找到目录：第 {toc_pages[0]}-{toc_pages[-1]} 页，共 {len(toc_pages)} 页", "DONE")
        return {
            "found": True,
            "pages": toc_pages,
            "page_count": len(toc_pages),
            "content": combined_content
        }
    else:
        log("\n未找到目录", "DONE")
        return {
            "found": False,
            "pages": [],
            "page_count": 0,
            "content": None,
            "message": f"未在前 {max_pages} 页中找到目录"
        }


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python3 explore_toc.py <pdf文件> [最大检查页数] [--save] [--log-dir 目录]")
        print()
        print("示例:")
        print("  python3 explore_toc.py sap.pdf")
        print("  python3 explore_toc.py sap.pdf 10")
        print("  python3 explore_toc.py sap.pdf --save")
        print("  python3 explore_toc.py sap.pdf 10 --save --log-dir logs/")
        print()
        print("功能:")
        print("  - 自动从第1页开始探索 PDF 目录")
        print("  - 用 AI 识别目录页")
        print("  - 返回目录页码和内容")
        print()
        print("选项:")
        print("  --save          保存目录内容到 md 文件")
        print("  --log-dir 目录   保存 API 调用日志到指定目录")
        sys.exit(1)

    # 解析参数
    pdf_path = sys.argv[1]
    max_pages = 15
    save_to_file = False
    log_dir = None

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--save":
            save_to_file = True
            i += 1
        elif sys.argv[i] == "--log-dir" and i + 1 < len(sys.argv):
            log_dir = sys.argv[i + 1]
            i += 2
        elif sys.argv[i].isdigit():
            max_pages = int(sys.argv[i])
            i += 1
        else:
            i += 1

    # 探索目录
    result = explore_toc(pdf_path, max_pages, log_dir=log_dir)

    # 输出结果到 stdout
    print("\n" + "=" * 60)
    print("目录探索结果")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 如果找到目录，输出内容
    if result.get("found"):
        print("\n" + "=" * 60)
        print("目录内容")
        print("=" * 60)
        print(result["content"])

        # 保存到文件
        if save_to_file:
            # 生成输出文件名
            pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
            output_path = f"{pdf_name}_目录.md"

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# {pdf_name} 目录\n\n")
                f.write(f"**来源文件**: {pdf_path}\n")
                f.write(f"**目录页码**: 第 {result['pages'][0]}-{result['pages'][-1]} 页\n")
                f.write(f"**目录页数**: {result['page_count']} 页\n\n")
                f.write("---\n\n")
                f.write(result["content"])

            log(f"\n目录已保存到: {output_path}", "DONE")


if __name__ == "__main__":
    main()
