"""
CRF PDF 书签提取脚本

用法：
    python scripts/extract_crf_bookmarks.py [pdf路径]

默认路径：../crf.pdf（相对于脚本位置）
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

import fitz  # PyMuPDF


def extract_bookmarks(pdf_path: str, output_path: str = None) -> list[dict]:
    """
    提取 PDF 书签（目录结构）

    Args:
        pdf_path: PDF 文件路径
        output_path: 输出 JSON 路径（可选）

    Returns:
        书签列表，每个书签包含 title, level, page
    """
    doc = fitz.open(pdf_path)

    # 获取目录（书签）
    toc = doc.get_toc(simple=False)

    bookmarks = []
    for item in toc:
        level, title, page = item[0], item[1], item[2]
        # 页码从 1 开始
        bookmarks.append({
            "level": level,
            "title": title,
            "page": page
        })

    doc.close()

    # 输出到文件
    if output_path:
        import json
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(bookmarks, f, ensure_ascii=False, indent=2)
        print(f"提取到 {len(bookmarks)} 个书签")
        print(f"保存到: {output_path}")

    return bookmarks


def main():
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        # 默认路径：项目根目录的上级目录中的 crf.pdf
        pdf_path = str(project_root.parent / "crf.pdf")

    if not Path(pdf_path).exists():
        print(f"错误: 文件不存在 - {pdf_path}")
        sys.exit(1)

    output_path = str(project_root / "sap_output" / "01_目录识别" / "crf_书签.json")

    extract_bookmarks(pdf_path, output_path)


if __name__ == "__main__":
    main()
