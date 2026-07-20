#!/usr/bin/env python3
"""从 Word 文档中提取所有表格为 Excel 文件，按标题命名，并输出标题索引 JSON 供匹配脚本消费。

用法:
    python3 extract_tables.py <表格.docx> <清单.docx> [输出目录]
    python3 extract_tables.py <文件.docx> [--out 输出目录] [--type 表格|清单]
    python3 extract_tables.py ... --api-key sk-xxx   # 必须提供 API key

提取策略:
  1. 提取 TOC（自动目录）→ LLM 输出本章节分析集
  2. Body 遍历，每个表格取上方最近几段发给 LLM 提取编号/标题/分析集
  3. 表格自身无分析集时用 TOC 章节分析集补全

产出:
  表格/  01-标题.xlsx  ...  +  表格-标题索引.json
  清单/  01-标题.xlsx  ...  +  清单-标题索引.json
"""

import json
import os
import re
import sys
import time

from docx import Document
from lxml import etree
from openpyxl import Workbook

_sys_path_add = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
if _sys_path_add not in sys.path:
    sys.path.insert(0, _sys_path_add)
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL

# ── 工具函数 ──

def _sanitize_filename(name: str) -> str:
    """清洗文件名：替换非法字符，限制长度"""
    name = re.sub(r'[/\\:*?"<>|]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 120:
        name = name[:120]
    return name

# ═══════════════════════════════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════════════════════════════

nsmap = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

# 表格标题紧贴表格上方，采集最近几段即可
CONTEXT_WINDOW_SIZE = 5

_EXTRACT_SYSTEM_PROMPT = """你是临床试验文档解析专家。给定紧贴表格上方的几段文本，提取当前表格的标题。

文本按从上到下排列，最末尾行紧贴表格。如果有多条标题，取最后一行。标题正文去掉编号前缀和分析集后缀，中间一字不改。

返回 JSON（仅 JSON，不要其他任何内容）：
{"table_num": "编号", "title": "标题正文", "population": "人群", "is_continued": false}

提取规则：
1. table_num: 编号，从标题行提取。确实没有时为 ""
2. title: 去掉编号前缀和分析集后缀，保留中间正文原文
3. population: 分析集，从括号标注推断。标准化为 FAS/PPS/SS/ITT/mITT/"随机化人群"/"筛选人群"等。无标注返回 "-"
4. is_continued: 仅当包含"续表"/"Continued"时为 true

示例：
- "表 11.1.1.1 各中心病例分布（FAS） 25" → {"table_num":"11.1.1.1","title":"各中心病例分布","population":"FAS","is_continued":false}
- "清单 10 X线胸片清单\n清单 11 超声心动图检查清单\n清单 12 声学造影清单" → 取最后一行 → {"table_num":"12","title":"声学造影清单","population":"-","is_continued":false}
- "表 7.1.1.1 各中心病例分布情况" → {"table_num":"7.1.1.1","title":"各中心病例分布情况","population":"-","is_continued":false}
- "11.1 不良事件" → {"table_num":"","title":"","population":"-","is_continued":false}"""

_TOC_POPULATION_PROMPT = """给定目录（TOC），找出每个带括号标注的章节。编号用点分隔，分析集原文照搬。

仅返回 JSON。示例：
  7.1 病例分布
    7.1.1 各中心病例分布和人群划分情况（随机化人群）
      表 7.1.1.1 各中心病例分布情况
  7.2 不良事件（SS）
返回：
{"7.1.1":"随机化人群","7.2":"SS"}"""


# ═══════════════════════════════════════════════════════════════════════════
# TOC 提取（Word 自动目录字段解析）
# ═══════════════════════════════════════════════════════════════════════════

def _is_toc_paragraph(elem) -> bool:
    """判断段落是否为 TOC 条目（含 fldChar begin+separate 且有 dot leader）。"""
    fld = [fc.get(f'{{{nsmap["w"]}}}fldCharType') for fc in elem.findall(f'.//{{{nsmap["w"]}}}fldChar')]
    has_fld = 'begin' in fld and 'separate' in fld
    has_dot = any(t.get(f'{{{nsmap["w"]}}}leader') == 'dot' for t in elem.findall(f'.//{{{nsmap["w"]}}}tab'))
    return has_fld and has_dot


def _toc_text(elem) -> str:
    """从 TOC 段落提取纯文本（跳过 instrText）。"""
    return ''.join(t.text or '' for t in elem.iter(f'{{{nsmap["w"]}}}t')
                   if etree.QName(t.getparent()).localname != 'instrText').strip()


def _toc_style_level(name: str) -> int | None:
    """从段落样式名提取 TOC 层级（如 TOC1→1, TOC2→2, 目录 1→1）。"""
    for pat in [r'^TOC\s*(\d+)$', r'^(目录|目次)\s*(\d+)$', r'^TM\s*(\d+)$', r'^TDC\s*(\d+)$']:
        m = re.match(pat, name, re.IGNORECASE)
        if m: return int(m.group(1) if len(m.groups()) == 1 else m.group(2))
    m = re.match(r'^TOC\s*Heading$', name, re.IGNORECASE)
    return 1 if m else None


def _extract_toc(doc) -> list[tuple[int, str]]:
    """提取 Word 自动目录，返回 [(层级, 文本), ...]。无目录返回空列表。"""
    ns = f'{{{nsmap["w"]}}}'
    entries = []
    for p in doc.element.body.iter(f'{ns}p'):
        if _is_toc_paragraph(p):
            s = p.find(f'{ns}pPr/{ns}pStyle')
            style = s.get(f'{ns}val', '') if s is not None else ''
            t = _toc_text(p)
            if t: entries.append((style, t))
    if not entries: return []

    s2l = {}
    for style, _ in entries:
        if style not in s2l:
            lv = _toc_style_level(style)
            if lv is not None: s2l[style] = lv
    unseen = [s for s, _ in entries if s not in s2l]
    base = max(s2l.values()) + 1 if s2l else 1
    for i, s in enumerate(unseen): s2l[s] = base + i
    return [(s2l[style], text) for style, text in entries]


def _call_llm_toc_populations(toc: list[tuple[int, str]], api_key: str,
                                api_base: str, model: str) -> dict[str, str]:
    """调用 LLM 从 TOC 中提取每个表格编号的继承分析集。返回 {table_num: population}。"""
    if not toc or not api_key:
        return {}

    try:
        import anthropic
    except ImportError:
        return {}

    # 缩进表示层级
    lines = ['  ' * (level - 1) + text for level, text in toc]
    toc_text = '\n'.join(lines)

    client = anthropic.Anthropic(api_key=api_key, base_url=api_base,
                                  timeout=120, max_retries=3)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=model, max_tokens=2048, temperature=0,
                thinking={"type": "disabled"},
                system=_TOC_POPULATION_PROMPT,
                messages=[{"role": "user", "content": toc_text}],
            )
        except Exception as e:
            print(f"  ⚠ TOC 分析集提取失败 (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
                continue
            return {}

        text = "".join(b.text for b in (resp.content or []) if hasattr(b, 'text'))
        if not text:
            if attempt < max_retries - 1:
                print(f"  ⚠ TOC 分析集返回空，{(attempt + 1) * 2}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep((attempt + 1) * 2)
                continue
            return {}

        try:
            m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

        if attempt < max_retries - 1:
            print(f"  ⚠ TOC 分析集解析失败，{(attempt + 1) * 2}s 后重试 ({attempt + 1}/{max_retries})...")
            time.sleep((attempt + 1) * 2)
            continue
        return {}

    return {}


# ═══════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════

def _extract_paragraph_text(elem) -> str:
    """从 <w:p> XML 元素提取纯文本（跳过 instrText 指令文本）。"""
    parts = []
    for t in elem.iter(f'{{{nsmap["w"]}}}t'):
        parent_tag = etree.QName(t.getparent()).localname if t.getparent() is not None else ''
        if parent_tag == 'instrText':
            continue
        if t.text:
            parts.append(t.text)
    return ''.join(parts).strip()


# ═══════════════════════════════════════════════════════════════════════════
# LLM 单表提取
# ═══════════════════════════════════════════════════════════════════════════

def _call_llm_extract(context_text: str, api_key: str, api_base: str,
                      model: str) -> dict | None:
    """调用 Anthropic SDK 从上下文文本中提取单个表格的索引信息。

    Returns: {table_num, title, population, is_continued} | None
    """
    if not context_text or not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic(api_key=api_key, base_url=api_base,
                                  timeout=60, max_retries=3)

    user_prompt = f"表格上方文本：\n\n{context_text}\n\n请提取表格索引信息（仅返回 JSON）："

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=256,
                temperature=0,
                thinking={"type": "disabled"},
                system=_EXTRACT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as e:
            print(f"  ⚠ LLM 调用失败 (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
                continue
            return None

        text = "".join(b.text for b in (resp.content or []) if hasattr(b, 'text'))
        if not text:
            if attempt < max_retries - 1:
                print(f"  ⚠ LLM 返回空，{(attempt + 1) * 2}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep((attempt + 1) * 2)
                continue
            return None

        try:
            m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if not m:
                if attempt < max_retries - 1:
                    print(f"  ⚠ LLM 输出无 JSON，{(attempt + 1) * 2}s 后重试 ({attempt + 1}/{max_retries})...")
                    time.sleep((attempt + 1) * 2)
                    continue
                return None
            data = json.loads(m.group(0))
            return {
                'table_num': data.get('table_num', ''),
                'title': data.get('title', ''),
                'population': data.get('population', '-'),
                'is_continued': data.get('is_continued', False),
            }
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  ⚠ LLM 输出解析失败 (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
                continue
            return None

    return None


# ═══════════════════════════════════════════════════════════════════════════
# 续表合并
# ═══════════════════════════════════════════════════════════════════════════

def _merge_continued(results: list[dict]) -> list[dict]:
    """将 is_continued=True 的条目合并到前一个非续表条目。"""
    merged = []
    for r in results:
        if r.get('is_continued') and merged:
            r['table_num'] = merged[-1]['table_num']
            r['title'] = merged[-1]['title']
            if r.get('population', '-') == '-':
                r['population'] = merged[-1].get('population', '-')
            r['_was_continued'] = True
        merged.append(r)
    return merged


# ═══════════════════════════════════════════════════════════════════════════
# 标题索引构建（body 遍历 + LLM 逐表提取）
# ═══════════════════════════════════════════════════════════════════════════

def build_table_index(doc, doc_type: str, api_key=None, api_base=None,
                      model=None, toc_pop_map: dict[str, str] | None = None,
                      ) -> list[dict]:
    """遍历 body XML，每个 <w:tbl> 取上方最近几段发给 LLM 提取索引。
    分析集缺失时从 TOC 继承表补全。

    Returns: [{title, table_num, population, is_continued}, ...]
    """
    window: list[str] = []
    results: list[dict] = []
    pop_map = toc_pop_map or {}
    use_llm = bool(api_key)
    llm_ok_count = 0
    llm_fail_count = 0
    inherited_count = 0

    for child in doc.element.body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            text = _extract_paragraph_text(child)
            if text:
                window.append(text)

        elif tag == "tbl":
            context = '\n'.join(window[-CONTEXT_WINDOW_SIZE:])
            window = []
            info = None

            if use_llm:
                info = _call_llm_extract(
                    context, api_key,
                    api_base or LLM_API_BASE,
                    model or LLM_MODEL,
                )
                if info is not None:
                    llm_ok_count += 1
                else:
                    llm_fail_count += 1

            if info is None:
                info = {'table_num': '', 'title': '未命名', 'population': '-', 'is_continued': False}

            if info.get('population', '-') == '-':
                num = info.get('table_num', '')
                inherited = None
                if num:
                    parts = num.split('.')
                    for i in range(len(parts), 0, -1):
                        prefix = '.'.join(parts[:i])
                        if prefix in pop_map:
                            inherited = pop_map[prefix]
                            break
                if not inherited and pop_map:
                    inherited = next(iter(pop_map.values()))
                if inherited:
                    info['population'] = inherited
                    inherited_count += 1

            results.append(info)

    results = _merge_continued(results)

    if use_llm:
        print(f"  ✅ LLM 提取: {llm_ok_count}/{len(results)} 个表格"
              + (f"  ({llm_fail_count} 个失败)" if llm_fail_count else "")
              + (f"  TOC继承: {inherited_count}" if inherited_count else ""))
    else:
        print(f"  📝 简易提取: {len(results)} 个表格（无 API key）")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 表格数据提取
# ═══════════════════════════════════════════════════════════════════════════

def extract_tables_from_docx(doc):
    tables = []
    for table in doc.tables:
        rows_data = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        tables.append(rows_data)
    return tables


# ═══════════════════════════════════════════════════════════════════════════
# Excel 输出
# ═══════════════════════════════════════════════════════════════════════════

def save_table_to_xlsx(table_data, xlsx_path):
    wb = Workbook()
    ws = wb.active
    for row_data in table_data:
        ws.append(row_data)
    wb.save(xlsx_path)


def detect_doc_type(filename):
    basename = filename.lower()
    if "清单" in filename:
        return "清单"
    if "表格" in filename or "table" in basename:
        return "表格"
    if "listing" in basename:
        return "清单"
    return "表格"


# ═══════════════════════════════════════════════════════════════════════════
# 主处理函数
# ═══════════════════════════════════════════════════════════════════════════

def process_one(docx_path, output_dir, doc_type=None,
                api_key=None, api_base=None, model=None):
    if not os.path.exists(docx_path):
        print(f"⚠ 文件不存在，跳过: {docx_path}")
        return

    if doc_type is None:
        doc_type = detect_doc_type(os.path.basename(docx_path))

    print(f"处理: {docx_path}  (类型: {doc_type})")

    doc = Document(docx_path)
    tables = extract_tables_from_docx(doc)

    # 提取 TOC → LLM 输出继承表 { "7.1":"FAS", "2":"FAS", ... }
    toc_pop_map = {}
    if api_key:
        toc = _extract_toc(doc)
        if toc:
            print(f"  📑 TOC: {len(toc)} 条")
            toc_pop_map = _call_llm_toc_populations(
                toc, api_key, api_base or LLM_API_BASE, model or LLM_MODEL,
            )
            if toc_pop_map:
                print(f"  📑 章节继承: {toc_pop_map}")

    index_entries = build_table_index(
        doc, doc_type,
        api_key=api_key, api_base=api_base, model=model,
        toc_pop_map=toc_pop_map,
    )

    if len(index_entries) != len(tables):
        print(f"  ⚠ 索引条目数({len(index_entries)})与表格数({len(tables)})不一致，以表格数为准")
        while len(index_entries) < len(tables):
            index_entries.append(
                {'table_num': '', 'title': '未命名', 'population': '-', 'is_continued': False})
        index_entries = index_entries[:len(tables)]

    num_unnamed = sum(1 for e in index_entries if not e['title'] or e['title'] == '未命名')
    num_continued = sum(1 for e in index_entries if e.get('_was_continued'))
    print(f"  表格数: {len(tables)}  有标题: {len(tables) - num_unnamed}"
          + (f"  续表: {num_continued}" if num_continued else ""))

    os.makedirs(output_dir, exist_ok=True)

    index_data: list[dict] = []

    for seq, (entry, table_data) in enumerate(zip(index_entries, tables), 1):
        title = entry['title']
        num = entry.get('table_num', '')

        pop = entry.get('population', '-')

        safe = _sanitize_filename(title)
        pop_suffix = f"-{pop}" if pop and pop != '-' else ""
        filename = f"{seq:02d}-{safe}{pop_suffix}.xlsx"
        xlsx_path = os.path.join(output_dir, filename)

        rows, cols = len(table_data), max((len(r) for r in table_data), default=0)
        save_table_to_xlsx(table_data, xlsx_path)
        status = "  ⚠ 无标题" if title == "未命名" else ""
        continued_mark = "  (续表)" if entry.get('_was_continued') else ""
        print(f"  → {filename}  ({rows} 行 × {cols} 列){status}{continued_mark}")

        index_data.append({
            'num': num if num else str(seq),
            'title': title,
            'population': pop,
        })

    label = "表格" if doc_type == "表格" else "清单"
    index_path = os.path.join(output_dir, f"{label}-标题索引.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    print(f"  → {label}-标题索引.json  ({len(index_data)} 条)")

    stats = {
        "total": len(index_data),
        "unnamed": num_unnamed,
        "continued": num_continued,
        "llm_used": bool(api_key),
        "body_tables": len(tables),
    }
    stats_path = os.path.join(output_dir, "_extraction_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  → _extraction_stats.json  ({json.dumps(stats, ensure_ascii=False)})")

    print(f"  已保存到: {output_dir}\n")
    return index_data


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    args = sys.argv[1:]
    if not args:
        print("用法:")
        print("  python3 extract_tables.py <表格.docx> <清单.docx> [输出目录]")
        print("  python3 extract_tables.py <文件.docx> [--out DIR] [--type 表格|清单]")
        print("选项: --api-key KEY  --api-base URL  --model NAME")
        sys.exit(1)

    output_base = os.getcwd()
    doc_type_override = None
    api_key = LLM_API_KEY
    api_base = LLM_API_BASE
    model = LLM_MODEL
    files = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out" and i + 1 < len(args):
            i += 1; output_base = args[i]
        elif a == "--type" and i + 1 < len(args):
            i += 1; doc_type_override = args[i]
        elif a == "--api-key" and i + 1 < len(args):
            i += 1; api_key = args[i]
        elif a == "--api-base" and i + 1 < len(args):
            i += 1; api_base = args[i]
        elif a == "--model" and i + 1 < len(args):
            i += 1; model = args[i]
        else:
            files.append(a)
        i += 1

    if not files:
        print("错误: 未指定输入文件"); sys.exit(1)

    if len(files) == 2 and doc_type_override is None:
        for docx_path in files:
            dt = detect_doc_type(os.path.basename(docx_path))
            out_dir = os.path.join(output_base, dt)
            process_one(docx_path, out_dir, dt,
                        api_key=api_key, api_base=api_base, model=model)
    else:
        for docx_path in files:
            dt = doc_type_override or detect_doc_type(os.path.basename(docx_path))
            out_dir = os.path.join(output_base, dt) if len(files) > 1 else output_base
            process_one(docx_path, out_dir, dt,
                        api_key=api_key, api_base=api_base, model=model)

    print("完成。")


if __name__ == "__main__":
    main()
