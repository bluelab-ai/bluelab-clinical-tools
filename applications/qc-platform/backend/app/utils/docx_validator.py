"""
上传文件格式校验模块。

校验两类问题：
1. 旧版 .doc 格式 → 提示转为 .docx
2. .docx 包含修订标记（tracked changes） → 提示转为清洁版
"""

import os
import zipfile
from pathlib import Path
from typing import Optional

# ─── XPaths / namespaces for tracked changes in OOXML ───────────────────
_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def _has_tracked_changes(docx_path: str) -> bool:
    """检测 docx 文件的 document.xml 是否包含修订标记（<w:ins> / <w:del>）。"""
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            # 先检查最可能存在修订标记的 document.xml
            for candidate in ("word/document.xml", "word/document2.xml"):
                if candidate not in zf.namelist():
                    continue
                xml_bytes = zf.read(candidate)
                # 简单字符串扫描，避免 XML 解析开销和命名空间问题
                text = xml_bytes.decode("utf-8", errors="replace")
                if "<w:ins " in text or "<w:ins>" in text or "<w:del " in text or "<w:del>" in text:
                    return True
                # 也检查 w:ins 和 w:del（无前缀命名空间的写法）
                if "<w:ins" in text or "<w:del" in text:
                    return True
    except (zipfile.BadZipFile, OSError):
        pass
    return False


def check_tracked_changes(file_path: str) -> Optional[str]:
    """
    检测 .docx 文件是否包含修订标记。

    返回:
        None      — 无修订标记
        str       — 警告信息（中文）
    """
    ext = Path(file_path).suffix.lower()
    if ext != ".docx":
        return None
    if _has_tracked_changes(file_path):
        return "该文件包含修订标记（tracked changes / 标注模式），可能降低质控质量或产生错误，建议转为清洁版后重新上传。"
    return None


def validate_upload(file_path: str) -> Optional[str]:
    """
    校验上传文件是否为可接受的格式（仅检查 .doc 旧格式阻断性错误）。

    参数:
        file_path: 文件在磁盘上的绝对路径

    返回:
        None   — 校验通过
        str    — 错误提示信息（中文，可直接展示给用户）
    """
    if not file_path or not os.path.exists(file_path):
        return "文件不存在，请重新上传"

    ext = Path(file_path).suffix.lower()

    # ── 1. 旧版 .doc 格式 → 阻断 ──
    if ext == ".doc":
        return (
            "不支持旧版 .doc 格式。请用 Word 打开文件，"
            "另存为 → 选择「Word 文档 (.docx)」格式，转换后刷新页面重新上传。"
        )

    # ── 2. .docx 修订标记 → 不在此处检查，由 check_tracked_changes 独立处理 ──
    # （check_tracked_changes 返回 warning 而非 error，允许用户继续质控）

    # ── 3. 非 docx 也非 doc（如 pdf）→ 放行，由下游脚本自行处理 ──
    return None
