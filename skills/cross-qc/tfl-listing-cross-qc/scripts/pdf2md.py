#!/usr/bin/env python3
"""PDF → Markdown 转换工具

用法:
    python3 pdf2md.py input.pdf                    # 生成 input.md（文本型 PDF）
    python3 pdf2md.py input.pdf --ocr              # 强制 OCR 模式（扫描件 PDF）
    python3 pdf2md.py input.pdf --output out.md    # 指定输出文件名
    python3 pdf2md.py input.pdf --raw              # 仅提取文本，不生成 Markdown 文件

依赖:
    pip install pdfplumber
    OCR 模式额外需要: pip install pdf2image pytesseract
    系统需安装: poppler (brew install poppler) 用于 OCR 模式
"""

import argparse
import os
import sys


def check_libraries(ocr_mode=False):
    """检查必要的 Python 库是否可用"""
    missing = []
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        missing.append("pdfplumber")

    if ocr_mode:
        try:
            import pdf2image  # noqa: F401
        except ImportError:
            missing.append("pdf2image")
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            missing.append("pytesseract")

    if missing:
        print(f"缺少依赖库: {', '.join(missing)}")
        print(f"请运行: pip install {' '.join(missing)}")
        if "pdf2image" in missing or "pytesseract" in missing:
            print("OCR 模式还需要系统安装 poppler: brew install poppler")
        sys.exit(1)


def extract_text_pdfplumber(pdf_path):
    """使用 pdfplumber 提取 PDF 文本，返回 (总页数, 逐页文本列表)"""
    import pdfplumber

    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"PDF 共 {total} 页，正在提取文本...")
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            pages_text.append(text if text else "")
            print(f"  [{i+1}/{total}] 第 {i+1} 页完成")

    return total, pages_text


def extract_text_ocr(pdf_path):
    """OCR 模式：将 PDF 页面转为图片，再用 Tesseract 识别"""
    from pdf2image import convert_from_path
    import pytesseract

    print("正在将 PDF 转为图片...")
    images = convert_from_path(pdf_path)
    total = len(images)

    pages_text = []
    for i, img in enumerate(images):
        print(f"  [{i+1}/{total}] 正在 OCR 识别第 {i+1} 页...")
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        pages_text.append(text)

    return total, pages_text


def is_likely_scanned(pages_text, threshold=0.3):
    """判断是否为扫描件 PDF（提取文本过少的页数占比超过阈值）"""
    empty_pages = sum(1 for t in pages_text if len(t.strip()) < 50)
    ratio = empty_pages / len(pages_text) if pages_text else 1.0
    return ratio > threshold


def generate_markdown(pages_text):
    """将提取的文本整合为原始 Markdown 草稿（保留换行和页标记）"""
    lines = []
    total = len(pages_text)
    for i, text in enumerate(pages_text):
        lines.append(f"<!-- PAGE {i+1} -->")
        lines.append("")
        if text:
            lines.append(text.strip())
        else:
            lines.append("*(本页无可提取文本)*")
        lines.append("")
        if i < total - 1:
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="PDF → Markdown 转换工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python3 pdf2md.py 方案.pdf                     # 提取文本并生成 .md 文件
    python3 pdf2md.py 方案.pdf --ocr               # 强制 OCR 模式
    python3 pdf2md.py 方案.pdf --output result.md  # 指定输出文件
    python3 pdf2md.py 方案.pdf --raw               # 仅输出原始文本到 stdout
        """,
    )
    parser.add_argument("input", help="PDF 文件路径")
    parser.add_argument("--output", "-o", default=None, help="输出 Markdown 文件路径（默认与输入同名的 .md）")
    parser.add_argument("--ocr", action="store_true", help="强制使用 OCR 模式")
    parser.add_argument("--raw", action="store_true", help="仅提取文本并输出到 stdout，不生成文件")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"文件不存在: {args.input}")
        sys.exit(1)

    check_libraries(ocr_mode=args.ocr)

    # 提取文本
    if args.ocr:
        total, pages_text = extract_text_ocr(args.input)
    else:
        total, pages_text = extract_text_pdfplumber(args.input)
        if is_likely_scanned(pages_text):
            print("\n⚠️  检测到 PDF 可能是扫描件（可提取文本过少）")
            print("   建议使用 --ocr 参数重试：python3 pdf2md.py " + args.input + " --ocr")
            print("   OCR 模式需要: pip install pdf2image pytesseract")
            print("   系统还需要: brew install poppler\n")

    raw_text = generate_markdown(pages_text)

    if args.raw:
        print(raw_text)
    else:
        output_path = args.output or os.path.splitext(args.input)[0] + ".md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(raw_text)
        print(f"\n✅ 已生成 Markdown 文件: {output_path}")
        print(f"   总页数: {total}")
        print(f"   文件大小: {os.path.getsize(output_path):,} bytes")
        print(f"\n💡 提示: 生成的 .md 保留了原始文本结构和页标记。如需精细排版（表格、标题层级等），")
        print(f"   可让 AI 助手进一步处理，例如: \"将 {output_path} 的表格转为 Markdown table 格式\"")


if __name__ == "__main__":
    main()
