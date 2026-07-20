#!/usr/bin/env python3
"""从 Word 文档中提取所有表格为 Excel 文件，按文档标题命名。

用法:
    # 同时处理表格和清单
    python3 extract_tables.py <表格.docx> <清单.docx> [输出目录]

    # 单独处理一个文件
    python3 extract_tables.py <文件.docx> [--out 输出目录] [--type 表格|清单]

提取策略:
  1. 优先从 Word 自动目录（TOC）读取标题索引（语言无关，支持中/英文）
  2. TOC 不可用时回退到正文遍历（双语正则 Table/表、Listing/清单）
  3. TOC 条目数与正文表格数不一致时：多余的 TOC 标题创建空 Excel，
     缺少标题的表格标记为"未命名"
"""

import os
import re
import sys

from docx import Document
from lxml import etree
from openpyxl import Workbook

# ═══════════════════════════════════════════════════════════════════════════
# TOC 提取（语言无关，与 match_tables_listings.py 共享实现）
# ═══════════════════════════════════════════════════════════════════════════

nsmap = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def _is_toc_paragraph(elem):
    """语言无关的 TOC 条目检测：域字符 + 点状前导符。
    对 Word 自动生成的目录，不分语言版本，100% 可靠。
    """
    fld_types = [fc.get(f'{{{nsmap["w"]}}}fldCharType')
                 for fc in elem.findall(f'.//{{{nsmap["w"]}}}fldChar')]
    has_fld = 'begin' in fld_types and 'separate' in fld_types
    has_dot_leader = any(
        t.get(f'{{{nsmap["w"]}}}leader') == 'dot'
        for t in elem.findall(f'.//{{{nsmap["w"]}}}tab')
    )
    return has_fld and has_dot_leader


def _get_toc_text(elem):
    """提取 TOC 条目文本（跳过域指令 <w:instrText>）"""
    texts = []
    for t in elem.iter(f'{{{nsmap["w"]}}}t'):
        if etree.QName(t.getparent()).localname == 'instrText':
            continue
        if t.text:
            texts.append(t.text)
    return ''.join(texts).strip()


def _get_paragraph_style(p_elem):
    """获取段落样式 ID"""
    pPr = p_elem.find(f'{{{nsmap["w"]}}}pPr')
    if pPr is None:
        return 'NONE'
    pStyle = pPr.find(f'{{{nsmap["w"]}}}pStyle')
    if pStyle is None:
        return 'NONE'
    return pStyle.get(f'{{{nsmap["w"]}}}val', 'NONE')


def _parse_toc_style_level(style_name):
    """从 TOC 样式名提取层级数字。支持多语言：
    TOC1 / TOC 1 / 目录 1 / 目次 1 / TM 1 / TDC 1 等
    """
    m = re.match(r'^TOC\s*(\d+)$', style_name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r'^(目录|目次)\s*(\d+)$', style_name)
    if m:
        return int(m.group(2))
    m = re.match(r'^TM\s*(\d+)$', style_name, re.IGNORECASE)    # 法文
    if m:
        return int(m.group(1))
    m = re.match(r'^TDC\s*(\d+)$', style_name, re.IGNORECASE)   # 西班牙文
    if m:
        return int(m.group(1))
    m = re.match(r'^TOC\s*Heading$', style_name, re.IGNORECASE)  # TOC Heading
    if m:
        return 1
    return None


def _extract_toc(doc):
    """从 docx Document 对象提取 TOC 条目及层级。
    返回 [(level: int, text: str), ...]
    若文档无自动目录则返回 []。
    """
    toc_paragraphs = []
    for p in doc.element.body.iter(f'{{{nsmap["w"]}}}p'):
        if _is_toc_paragraph(p):
            style = _get_paragraph_style(p)
            text = _get_toc_text(p)
            if text:
                toc_paragraphs.append((style, text))

    if not toc_paragraphs:
        return []

    # 层级推断：样式名 → 首次出现顺序
    style_to_level = {}
    for style, _ in toc_paragraphs:
        if style not in style_to_level:
            lv = _parse_toc_style_level(style)
            if lv is not None:
                style_to_level[style] = lv

    unmapped = []
    _seen = set()
    for style, _ in toc_paragraphs:
        if style not in style_to_level and style not in _seen:
            unmapped.append(style)
            _seen.add(style)

    base = max(style_to_level.values()) + 1 if style_to_level else 1
    for i, s in enumerate(unmapped):
        style_to_level[s] = base + i

    return [(style_to_level[s], text) for s, text in toc_paragraphs]


# ═══════════════════════════════════════════════════════════════════════════
# 双语标题正则和解析（与 match_tables_listings.py 共享实现）
# ═══════════════════════════════════════════════════════════════════════════

_TABLE_TITLE_RE = re.compile(r'^(?:表|Table)\s*[\d.]+\s+(.+)', re.IGNORECASE)
_TABLE_NUM_RE  = re.compile(r'^(?:表|Table)\s*([\d.]+)', re.IGNORECASE)
_LISTING_TITLE_RE = re.compile(r'^(?:清单|Listing)\s+([\d.]+)\s+(.+)', re.IGNORECASE)

# 已知分析集枚举（用于标题标准化时剥离人群后缀）
_POP_ACRONYMS = {'FAS', 'PPS', 'SS', 'ITT', 'mITT'}


def _parse_table_title(toc_text):
    """从 TOC 条目文本提取表格标题。
    '表 11.1.1.1 各中心病例分布情况（随机化人群）4' → '各中心病例分布情况（随机化人群）'
    """
    m = _TABLE_TITLE_RE.match(toc_text)
    if not m:
        return toc_text
    title = m.group(1).strip()
    title = re.sub(r'\s*\d+$', '', title)  # 去掉末尾页码
    return title


def _parse_listing_title(toc_text):
    """从 TOC 条目文本提取清单编号和名称。
    '清单 1 剔除脱落情况清单（随机化人群）2' → ('1', '剔除脱落情况清单（随机化人群）')
    """
    m = _LISTING_TITLE_RE.match(toc_text)
    if not m:
        return '', toc_text
    section_id = m.group(1)
    name = m.group(2).strip()
    name = re.sub(r'\s*\d+$', '', name)  # 去掉末尾页码
    return section_id, name


def _strip_title(title):
    """剥离标题中的干扰前缀/后缀，返回核心主题词。"""
    core = title
    # 去前缀：分层/时间/终点标签
    core = re.sub(r'^(?:各\S+(?:分层|因素)?\s*|By\s+\S+\s+|Per\s+\S+\s+)', '', core)
    core = re.sub(r'^(?:次要疗效指标|主要疗效指标|安全性指标|基线信息)[—-]?', '', core)
    core = re.sub(r'^(?:Secondary|Primary|Safety|Exploratory)\s+Endpoint[:\s—-]*', '', core, flags=re.IGNORECASE)
    # 去后缀：分析集括号
    core = re.sub(r'\s*[（(【\[]\s*(?:' + '|'.join(_POP_ACRONYMS) + r')\s*[）)】\]]\s*$', '', core, flags=re.IGNORECASE)
    core = re.sub(r'\s*[（(【\[]\s*(?:FAS&PPS)\s*[）)】\]]\s*$', '', core, flags=re.IGNORECASE)
    # 去后缀：统计方法和通用后缀
    core = re.sub(r'\s*(?:发生率|发生情况|变化情况|情况|清单|描述|汇总)$', '', core)
    core = re.sub(r'\s*(?:Incidence|Rate|Summary|Description|Overview|Listing)$', '', core, flags=re.IGNORECASE)
    core = re.sub(r'\s*协方差分析\s*[（(][^）)]*[）)]?\s*$', '', core)
    core = re.sub(r'\s*(?:ANCOVA|Analysis\s+of\s+Covariance)\s*[（(][^）)]*[）)]?\s*$', '', core, flags=re.IGNORECASE)
    core = core.strip()
    return core if core else title


# ═══════════════════════════════════════════════════════════════════════════
# 标题索引构建（TOC 驱动 + 正文 fallback）
# ═══════════════════════════════════════════════════════════════════════════

def _build_index_fallback(doc, doc_type):
    """回退：遍历 body XML，用双语正则匹配标题。
    返回 (titles, extra_toc_titles, warnings)。
    extra_toc_titles 在 fallback 模式下始终为空。
    """
    titles = []
    last_title = ""
    seen_numbers: set[str] = set()

    for child in doc.element.body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            # 提取段落文本
            texts = []
            for t in child.findall(".//" + f'{{{nsmap["w"]}}}t'):
                if t.text:
                    texts.append(t.text)
            text = "".join(texts).strip()
            if not text:
                continue

            if doc_type == "表格":
                m = _TABLE_TITLE_RE.match(text)
                if m:
                    last_title = text
            else:  # 清单
                # 跳过目录段落（样式含 toc）
                pPr = child.find(f'{{{nsmap["w"]}}}pPr')
                if pPr is not None:
                    pStyle = pPr.find(f'{{{nsmap["w"]}}}pStyle')
                    if pStyle is not None and "toc" in (pStyle.get(f'{{{nsmap["w"]}}}val', '') or '').lower():
                        continue
                m = _LISTING_TITLE_RE.match(text)
                if m:
                    section_id = m.group(1)
                    if section_id in seen_numbers:
                        continue
                    seen_numbers.add(section_id)
                    last_title = text

        elif tag == "tbl":
            titles.append(last_title if last_title else "未命名")
            last_title = ""

    warnings = []
    unnamed_positions = [i + 1 for i, t in enumerate(titles) if t == "未命名"]
    if unnamed_positions:
        warnings.append(
            f"⚠ {len(unnamed_positions)} 个表格无标题，已标记为未命名（位置: {unnamed_positions}）"
        )

    return titles, [], warnings, [None] * len(titles)


def build_table_index(doc, doc_type):
    """从 TOC 建立表格标题索引（语言无关）。

    策略:
      1. 从 Word 自动目录提取标题队列
      2. 遍历 body，每遇到 <w:tbl> 消费队列头部标题
      3. 队列耗尽 → "未命名" 占位
      4. 队列剩余 → 报告为 extra_toc_titles（正文无对应表格）

    返回 (titles, extra_toc_titles_slot, warnings, match_toc_indices)
      - titles:              与正文 <w:tbl> 一一对应的标题列表
      - extra_toc_titles_slot: [(toc_index, title), ...] TOC有但正文无的表（调用方插空文件）
      - warnings:            诊断信息列表
      - match_toc_indices:   [toc_index or None, ...] 每body表匹配的TOC序号
    """
    toc = _extract_toc(doc)

    if not toc:
        print("  ⚠ 未检测到自动目录，回退到正文遍历模式")
        return _build_index_fallback(doc, doc_type)

    # ── 从 TOC 构建标题队列（编号, 标题）──
    title_queue = []   # [(number, title), ...]
    seen_sections: set[str] = set()

    for _level, text in toc:
        if doc_type == "表格":
            m = _TABLE_TITLE_RE.match(text)
            if m:
                title = _parse_table_title(text)
                title = _strip_title(title)
                # 提取表号（如 11.1.1.1）
                num_m = _TABLE_NUM_RE.match(text)
                num = num_m.group(1) if num_m else title
                title_queue.append((num, title))
        else:  # 清单
            m = _LISTING_TITLE_RE.match(text)
            if m:
                section_id, name = _parse_listing_title(text)
                if section_id in seen_sections:
                    continue
                seen_sections.add(section_id)
                name = _strip_title(name)
                title_queue.append((section_id, name))

    if not title_queue:
        print("  ⚠ TOC 中未提取到标题，回退到正文遍历模式")
        return _build_index_fallback(doc, doc_type)

    print(f"  📑 TOC 提取到 {len(title_queue)} 个标题")

    # ── 遍历 body，按编号精准匹配 ──
    titles = []
    match_toc_indices = []   # 每个 body 表匹配的 TOC 序号（1-based），body-only为None
    queue = list(title_queue)  # [(number, title), ...]
    last_num = None
    last_body_title = ""       # body 段落标题全文（兜底用）

    for child in doc.element.body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            texts = []
            for t in child.findall(".//" + f'{{{nsmap["w"]}}}t'):
                if t.text:
                    texts.append(t.text)
            text = "".join(texts).strip()
            if not text:
                continue

            if doc_type == "表格":
                m = _TABLE_NUM_RE.match(text)
                if m:
                    last_num = m.group(1)
                    last_body_title = _strip_title(_parse_table_title(text))
            else:
                m = _LISTING_TITLE_RE.match(text)
                if m:
                    last_num = m.group(1)
                    _, name = _parse_listing_title(text)
                    last_body_title = _strip_title(name)

        elif tag == "tbl":
            matched = False
            if last_num is not None:
                for i, (num, title) in enumerate(queue):
                    if num == last_num:
                        titles.append(title)
                        # toc_index = 原始TOC序号（重建自 TOC 条目排位）
                        toc_index = title_queue.index((num, title)) + 1
                        match_toc_indices.append(toc_index)
                        queue.pop(i)
                        matched = True
                        break
            if not matched:
                # TOC 无匹配 → 用 body 自身标题兜底，无标题才标"未命名"
                titles.append(last_body_title if last_body_title else "未命名")
                match_toc_indices.append(None)

    # 重建 extra：queue 剩余条目需知道原始 TOC 序号
    extra_slot = []
    for num, title in queue:
        for idx, (qn, qt) in enumerate(title_queue):
            if qn == num and qt == title:
                extra_slot.append((idx + 1, title))
                break

    # ── 差异诊断 ──
    warnings = []

    unnamed_positions = [i + 1 for i, t in enumerate(titles) if t == "未命名"]
    if unnamed_positions:
        n = len(unnamed_positions)
        preview = unnamed_positions[:10]
        suffix = "..." if len(unnamed_positions) > 10 else ""
        warnings.append(
            f"⚠ {n} 个表格无 TOC 标题，已标记为未命名"
            f"（位置: {preview}{suffix}）"
        )

    if extra_slot:
        n = len(extra_slot)
        preview = ", ".join(f'"{t[:40]}"' for _, t in extra_slot[:3])
        suffix = " ..." if n > 3 else ""
        warnings.append(
            f"📭 TOC 中 {n} 个标题无对应表格，将创建空文件: {preview}{suffix}"
        )

    return titles, extra_slot, warnings, match_toc_indices


# ═══════════════════════════════════════════════════════════════════════════
# 表格数据提取
# ═══════════════════════════════════════════════════════════════════════════

def extract_tables_from_docx(doc):
    """从已打开的 docx Document 提取所有表格为二维列表。"""
    tables = []
    for table in doc.tables:
        rows_data = []
        for row in table.rows:
            row_data = [cell.text.strip() for cell in row.cells]
            rows_data.append(row_data)
        tables.append(rows_data)
    return tables


# ═══════════════════════════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════════════════════════

def sanitize_filename(name):
    """去掉文件名中不合法的字符，并限制长度。"""
    name = re.sub(r'[/\\:*?"<>|]', "-", name)
    if len(name) > 120:
        name = name[:120]
    return name


def save_table_to_xlsx(table_data, xlsx_path):
    """将一个二维列表保存为 Excel 文件。空数据则创建一个空 sheet。"""
    wb = Workbook()
    ws = wb.active
    if table_data:
        for row_data in table_data:
            ws.append(row_data)
    wb.save(xlsx_path)


def detect_doc_type(filename):
    """从文件名推断文档类型：表格 / 清单 / 未知"""
    basename = filename.lower()
    if "清单" in filename:
        return "清单"
    if "表格" in filename or "table" in basename:
        return "表格"
    if "listing" in basename:
        return "清单"
    return "表格"  # 默认按表格处理


def process_one(docx_path, output_dir, doc_type=None):
    """处理单个 docx 文件，导出 Excel 到 output_dir。"""
    if not os.path.exists(docx_path):
        print(f"⚠ 文件不存在，跳过: {docx_path}")
        return

    if doc_type is None:
        doc_type = detect_doc_type(os.path.basename(docx_path))

    print(f"处理: {docx_path}  (类型: {doc_type})")

    # ── 只打开一次文档 ──
    doc = Document(docx_path)

    # ── 第1步：TOC 驱动建立标题索引 ──
    titles, extra_toc_titles, warnings, match_toc_indices = build_table_index(doc, doc_type)
    for w in warnings:
        print(f"  {w}")

    # ── 第2步：提取表格数据 ──
    tables = extract_tables_from_docx(doc)
    print(f"  原文表格数: {len(tables)}  标题数: {len(titles)}"
          + (f"  TOC 多余标题: {len(extra_toc_titles)}" if extra_toc_titles else ""))

    os.makedirs(output_dir, exist_ok=True)

    # ── 构建输出列表：body表 + 空文件按正确位置插排 ──
    # extra_toc_titles = [(toc_index, title), ...]
    # match_toc_indices = [toc_index or None, ...] 每个 body 表匹配的 TOC 序号
    #
    # 插排规则：对每个 extra(toc_pos)，找到 body 中第一个 toc > toc_pos 的位置，
    # 插在它前面；若没有则追加到末尾。
    extra_sorted = sorted(extra_toc_titles, key=lambda x: x[0])

    # 构建 body 条目列表: [{body_idx, title}]
    body_entries = [{'body_idx': i, 'title': titles[i], 'toc': match_toc_indices[i]}
                    for i in range(len(tables))]

    # 插排空条目
    merged = []
    next_extra = 0
    for bi, entry in enumerate(body_entries):
        body_toc = entry['toc']
        # 插入所有 toc < body_toc 的空条目
        while next_extra < len(extra_sorted):
            extra_toc, extra_title = extra_sorted[next_extra]
            if body_toc is None or extra_toc < body_toc:
                merged.append({'body_idx': None, 'title': extra_title, 'toc': extra_toc})
                next_extra += 1
            else:
                break
        merged.append(entry)
    # 尾部剩余
    for extra_toc, extra_title in extra_sorted[next_extra:]:
        merged.append({'body_idx': None, 'title': extra_title, 'toc': extra_toc})

    # ── 输出 ──
    for seq, slot in enumerate(merged, 1):
        safe = sanitize_filename(slot['title'])
        filename = f"{seq:02d}-{safe}.xlsx"
        xlsx_path = os.path.join(output_dir, filename)
        if slot['body_idx'] is not None:
            table_data = tables[slot['body_idx']]
            save_table_to_xlsx(table_data, xlsx_path)
            rows = len(table_data)
            cols = max((len(r) for r in table_data), default=0)
            status = ""
            if slot['title'] == "未命名":
                status = "  ⚠ 无标题"
            toc_info = f"  (TOC#{slot['toc']})" if slot['toc'] else ""
            print(f"  → {filename}  ({rows} 行 × {cols} 列){status}{toc_info}")
        else:
            save_table_to_xlsx([], xlsx_path)
            print(f"  → {filename}  (空文件  — TOC#{slot['toc']} 有标题但正文无对应表格)")

    print(f"  已保存到: {output_dir}\n")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    args = sys.argv[1:]
    if not args:
        print("用法:")
        print("  python3 extract_tables.py <表格.docx> <清单.docx> [输出目录]")
        print("  python3 extract_tables.py <文件.docx> [--out 输出目录] [--type 表格|清单]")
        sys.exit(1)

    # 解析参数
    output_base = os.getcwd()
    doc_type_override = None
    files = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out" and i + 1 < len(args):
            i += 1
            output_base = args[i]
        elif a == "--type" and i + 1 < len(args):
            i += 1
            doc_type_override = args[i]
        else:
            files.append(a)
        i += 1

    if not files:
        print("错误: 未指定输入文件")
        sys.exit(1)

    # 双文件模式：自动分配 表格/ 和 清单/ 子目录
    if len(files) == 2 and doc_type_override is None:
        for docx_path in files:
            basename = os.path.basename(docx_path)
            doc_type = detect_doc_type(basename)
            out_dir = os.path.join(output_base, doc_type)
            process_one(docx_path, out_dir, doc_type)
    else:
        # 单文件模式
        for docx_path in files:
            doc_type = doc_type_override or detect_doc_type(os.path.basename(docx_path))
            out_dir = os.path.join(output_base, doc_type) if len(files) > 1 else output_base
            process_one(docx_path, out_dir, doc_type)

    print("完成。")


if __name__ == "__main__":
    main()
