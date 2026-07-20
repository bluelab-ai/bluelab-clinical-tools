#!/usr/bin/env python3
"""临床试验表格-清单匹配工具 v4

基于模型余弦相似度的语义匹配

使用:
    python3 match_tables_listings.py <表格文件.docx> <清单文件.docx> [输出.json]
"""

import re
import sys
from lxml import etree
from docx import Document
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

nsmap = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

# ═══════════════════════════════════════════════════════════════════════════
# 标题解析 — LLM 批量 + 正则兜底
# ═══════════════════════════════════════════════════════════════════════════

_llm_title_cache: dict[str, dict] = {}  # raw_title → {core_subject, population}

# 已知分析集枚举
_POP_ACRONYMS = {'FAS', 'PPS', 'SS', 'ITT', 'mITT'}
_POP_FULL_NAMES = {
    '安全性分析集': 'SS', '安全性分析人群': 'SS', '安全性数据集': 'SS',
    '随机化人群': '随机化人群',
    'Safety Set': 'SS', 'Safety Population': 'SS',
    'Full Analysis Set': 'FAS',
    'Per Protocol Set': 'PPS',
    'Intention to Treat': 'ITT', 'Intention-To-Treat': 'ITT',
    'Modified Intention to Treat': 'mITT', 'Modified Intention-To-Treat': 'mITT',
}

_TITLE_PARSE_SYSTEM_PROMPT = """You are a clinical trial data specialist. Parse the given table/listing titles.

For each title, extract two fields:

**core_subject**: The core clinical concept in its original language.
Strip these if present (in any language, Chinese or English):
- Stratification prefixes: 各中心/各年龄分层/各术式/各分层因素/By Center/Per Stratum...
- Time/visit modifiers: 术后6个月/筛选期/基线期/Post-operative 6 Months/Visit 1/Screening...
- Safety/relation modifiers: 与器械相关/与治疗相关/Device-related/Treatment-related...
- Endpoint labels: 次要疗效指标/主要疗效指标/Secondary Endpoint:/Primary Endpoint:
- Analysis set labels in brackets/parentheses: (FAS)/(SS)/【PPS】...
- Statistical method suffixes: 发生率/协方差分析/Incidence/ANCOVA/cross-tabulation...
- Generic suffixes: 情况/描述/汇总/Summary/Description/Overview/Listing

Strip the "清单" suffix from listing titles.

Keep intact: the clinical domain name, measurement name, and any essential distinguishing words.

**population**: Analysis set mentioned anywhere in the title text.
- Acronyms: FAS, PPS, SS, ITT, mITT
- 随机化人群 as-is
- Full names mapped to acronyms: Safety Set → SS, Full Analysis Set → FAS, etc.
- If none found, output "-"

Return a flat JSON array with one object per title, in the SAME order as input.
Each object MUST have exactly two keys: "core_subject" and "population".
Example: [{"core_subject": "...", "population": "FAS"}, ...]"""


def extract_population(title):
    """提取分析集标识。优先 LLM 缓存，其次正则兜底。"""
    if title in _llm_title_cache:
        return _llm_title_cache[title].get('population', '-')
    return _extract_population_regex(title)


def strip_title(title):
    """剥离干扰前缀后缀，返回核心主题词。优先 LLM 缓存，其次正则兜底。"""
    if title in _llm_title_cache:
        core = _llm_title_cache[title].get('core_subject', '')
        if core:
            return core
    return _strip_title_regex(title)


def reset_llm_cache():
    """清除 LLM 解析缓存（切换文件时调用）"""
    _llm_title_cache.clear()


def _batch_resolve_titles_llm(titles: list[str], api_key: str,
                               api_base: str = "https://api.deepseek.com/anthropic",
                               model: str = "deepseek-v4-pro") -> bool:
    """批量调用 LLM 解析所有标题，填充缓存。返回是否成功。

    默认值与 tfl_qc_workflow.py / ~/.claude/settings.json 对齐。
    """
    if not titles or not api_key:
        return False

    try:
        import anthropic
    except ImportError:
        print("  ⚠ anthropic SDK 未安装，使用正则提取")
        return False

    client = anthropic.Anthropic(api_key=api_key, base_url=api_base,
                                 timeout=120, max_retries=2)

    indexed = [f"[{i}] {t}" for i, t in enumerate(titles)]
    user_prompt = f"Titles to parse:\n\n" + "\n".join(indexed)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=0,
            thinking={"type": "disabled"},
            system=_TITLE_PARSE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        print(f"  ⚠ LLM 标题解析失败: {e}")
        return False

    # 解析 LLM 输出：提取所有 TextBlock 内容
    text_parts = []
    if response.content:
        for block in response.content:
            if hasattr(block, 'text'):
                text_parts.append(block.text)
    content = "".join(text_parts)
    if not content:
        print("  ⚠ LLM 返回空内容，使用正则提取")
        return False
    try:
        # 尝试提取 JSON 块
        import json
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            print("  ⚠ LLM 输出中未找到 JSON 数组，使用正则提取")
            return False
        items = json.loads(json_match.group(0))
        # 按顺序匹配（prompt 要求 LLM 按输入顺序返回）
        for idx, item in enumerate(items):
            if idx < len(titles):
                _llm_title_cache[titles[idx]] = {
                    'core_subject': item.get('core_subject', titles[idx]),
                    'population': item.get('population', '-'),
                }
        print(f"  ✅ LLM 解析了 {len(_llm_title_cache)}/{len(titles)} 个标题")
        return True
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"  ⚠ LLM 输出解析失败: {e}")
        return False


def _extract_population_regex(title):
    """正则提取分析集（兜底）"""
    m = re.search(r'[（(【\[]\s*(' + '|'.join(_POP_ACRONYMS) + r')\s*[）)】\]]',
                  title, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    bracket_pat = r'[（(【\[]\s*(' + '|'.join(map(re.escape, _POP_FULL_NAMES.keys())) + r')\s*[）)】\]]'
    m = re.search(bracket_pat, title, re.IGNORECASE)
    if m:
        return _POP_FULL_NAMES[m.group(1)]

    for full_name, acronym in sorted(_POP_FULL_NAMES.items(), key=lambda x: -len(x[0])):
        if full_name in title:
            return acronym

    m = re.search(r'\b(FAS|PPS|SS|ITT|mITT)\s*'
                  r'(?:人群|分析集|集|population|analysis set|set|分析人群)',
                  title, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    return '-'


def _strip_title_regex(title):
    """正则剥离前缀后缀（兜底）"""
    core = title
    # 去前缀
    core = re.sub(r'^(?:各\S+(?:分层|因素)?\s*|By\s+\S+\s+|Per\s+\S+\s+)', '', core)
    core = re.sub(r'^(?:次要疗效指标|主要疗效指标|安全性指标|基线信息)[—-]?', '', core)
    core = re.sub(r'^(?:Secondary|Primary|Safety|Exploratory)\s+Endpoint[:\s—-]*', '', core, flags=re.IGNORECASE)
    # 去后缀（分析集括号）
    core = re.sub(r'\s*[（(【\[]\s*(?:' + '|'.join(_POP_ACRONYMS) + r')\s*[）)】\]]\s*$', '', core, flags=re.IGNORECASE)
    core = re.sub(r'\s*[（(【\[]\s*(?:FAS&PPS)\s*[）)】\]]\s*$', '', core, flags=re.IGNORECASE)
    # 去后缀（统计方法）
    core = re.sub(r'\s*(?:发生率|发生情况|变化情况|情况|清单|描述|汇总)$', '', core)
    core = re.sub(r'\s*(?:Incidence|Rate|Summary|Description|Overview|Listing)$', '', core, flags=re.IGNORECASE)
    core = re.sub(r'\s*协方差分析\s*[（(][^）)]*[）)]?\s*$', '', core)
    core = re.sub(r'\s*(?:ANCOVA|Analysis\s+of\s+Covariance)\s*[（(][^）)]*[）)]?\s*$', '', core, flags=re.IGNORECASE)
    core = core.strip()
    return core if core else title


# ============================================================
# 提取：表格内容 + 清单内容
# ============================================================

def get_element_text(elem):
    """从 w:p 或 w:tc 等元素提取所有 <w:t> 文本"""
    return ''.join(t.text or '' for t in elem.iter(f'{{{nsmap["w"]}}}t'))


# ═══════════════════════════════════════════════════════════════════════════
# TOC 提取（语言无关，穿透 sdt 嵌套）
# ═══════════════════════════════════════════════════════════════════════════

def is_toc_paragraph(elem):
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
        if is_toc_paragraph(p):
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
# 表格/清单标题的模式识别
# ═══════════════════════════════════════════════════════════════════════════

_TABLE_TITLE_RE = re.compile(r'^(?:表|Table)\s*[\d.]+\s+(.+)', re.IGNORECASE)
_TABLE_NUM_RE  = re.compile(r'^(?:表|Table)\s*([\d.]+)', re.IGNORECASE)
_LISTING_TITLE_RE = re.compile(r'^(?:清单|Listing)\s+([\d.]+)\s+(.+)', re.IGNORECASE)


def _parse_table_title(toc_text):
    """从 TOC 条目文本提取表格标题和自身人群。
    '表 11.1.1.1 各中心病例分布情况（随机化人群）4' → ('各中心病例分布情况（随机化人群）', '随机化人群')
    """
    m = _TABLE_TITLE_RE.match(toc_text)
    if not m:
        return toc_text, '-'
    title = m.group(1).strip()
    # 去掉末尾页码
    title = re.sub(r'\s*\d+$', '', title)
    pop = extract_population(title)
    return title, pop


def _parse_listing_title(toc_text):
    """从 TOC 条目文本提取清单编号和名称。
    '清单 1 剔除脱落情况清单（随机化人群）2' → ('1', '剔除脱落情况清单（随机化人群）')
    """
    m = _LISTING_TITLE_RE.match(toc_text)
    if not m:
        return '', toc_text
    section_id = m.group(1)
    name = m.group(2).strip()
    # 去掉末尾页码
    name = re.sub(r'\s*\d+$', '', name)
    return section_id, name


# ═══════════════════════════════════════════════════════════════════════════
# 提取函数（TOC 驱动，语言无关）
# ═══════════════════════════════════════════════════════════════════════════

def extract_tables_with_columns(path, api_key=None, api_base=None, model="deepseek-v4-pro"):
    """从文档 TOC 提取表格标题和人群（含上级标题继承 + body 校验）。
    语言无关。如果提供 api_key，使用 LLM 批量解析标题。

    三阶段:
      A. TOC → 标题队列（含 LLM 解析 + 人群继承）
      B. body 遍历 → 按序消费标题队列
      C. 差异报告
    确保表格数量/顺序与 extract_tables.py 完全一致。
    """
    doc = Document(path)
    toc = _extract_toc(doc)

    if not toc:
        print("  ⚠ 未检测到自动目录，回退到正文遍历模式")
        return _extract_tables_fallback(doc)

    # ── 阶段A-1：收集所有表格标题，批量 LLM 解析 ──
    if api_key:
        raw_titles_for_llm = []
        for _level, text in toc:
            if _TABLE_TITLE_RE.match(text):
                title, _ = _parse_table_title(text)
                raw_titles_for_llm.append(title)
        if raw_titles_for_llm:
            _batch_resolve_titles_llm(raw_titles_for_llm, api_key, api_base, model=model)

    # ── 阶段A-2：TOC 遍历 → 构建标题队列（含人群继承）──
    pop_stack = []   # [(level, population), ...]
    title_queue = []  # [{title, population, num}, ...]

    for level, text in toc:
        while pop_stack and pop_stack[-1][0] >= level:
            pop_stack.pop()

        own_pop = extract_population(text)

        if _TABLE_TITLE_RE.match(text):
            title, _ = _parse_table_title(text)
            ancestor_pop = pop_stack[-1][1] if pop_stack else '-'
            # LLM 优先，正则兜底
            llm_pop = _llm_title_cache.get(title, {}).get('population', '')
            if llm_pop and llm_pop != '-':
                effective_pop = llm_pop
            else:
                effective_pop = own_pop if own_pop != '-' else ancestor_pop
            # 标题也使用 LLM 剥离后的核心主题词
            llm_core = _llm_title_cache.get(title, {}).get('core_subject', '')
            stored_title = llm_core if llm_core else title
            # 提取表号，用于 body 精准匹配
            num_m = _TABLE_NUM_RE.match(text)
            table_num = num_m.group(1) if num_m else stored_title
            title_queue.append({
                'title': stored_title, 'population': effective_pop,
                'num': table_num,
            })
            continue

        if own_pop != '-':
            pop_stack.append((level, own_pop))

    if not title_queue:
        print("  ⚠ TOC 中未提取到表格标题，回退到正文遍历模式")
        return _extract_tables_fallback(doc)

    print(f"  📑 TOC 提取到 {len(title_queue)} 个表格标题")

    # ── 阶段B：body 遍历 + TOC插排 → 合并输出 ──
    queue = list(title_queue)  # [{title, population, num}, ...]
    last_num = None
    last_body_title = ""
    body_entries = []  # [{title, population, toc_index or None}, ...]
    # 建立 TOC 编号→序号映射
    toc_num_to_idx = {}
    for idx, item in enumerate(title_queue):
        toc_num_to_idx[item['num']] = idx + 1  # 1-based

    for child in doc.element.body:
        tag = etree.QName(child).localname
        if tag == 'p':
            text = get_element_text(child).strip()
            if text:
                m = _TABLE_NUM_RE.match(text)
                if m:
                    last_num = m.group(1)
                    body_title, _ = _parse_table_title(text)
                    llm_core = _llm_title_cache.get(body_title, {}).get('core_subject', '')
                    last_body_title = llm_core if llm_core else body_title
        elif tag == 'tbl':
            matched = False
            if last_num is not None:
                for i, item in enumerate(queue):
                    if item['num'] == last_num:
                        toc_idx = toc_num_to_idx.get(item['num'])
                        body_entries.append({
                            'title': item['title'],
                            'population': item['population'],
                            'toc': toc_idx,
                        })
                        queue.pop(i)
                        matched = True
                        break
            if not matched:
                body_entries.append({
                    'title': last_body_title if last_body_title else '未命名',
                    'population': extract_population(last_body_title)
                                  if last_body_title else '-',
                    'toc': None,  # body-only
                })

    # 重建空条目（queue剩余）
    extra_sorted = []
    for item in queue:
        toc_idx = toc_num_to_idx.get(item['num'])
        if toc_idx:
            extra_sorted.append((toc_idx, item))
    extra_sorted.sort(key=lambda x: x[0])

    # 合并：body表 + 空插槽，按TOC位置
    merged = []
    next_extra = 0
    for be in body_entries:
        body_toc = be['toc']
        while next_extra < len(extra_sorted):
            etoc, eitem = extra_sorted[next_extra]
            if body_toc is None or etoc < body_toc:
                merged.append({
                    'title': eitem['title'],
                    'population': eitem['population'],
                    'toc': etoc, 'empty': True,
                })
                next_extra += 1
            else:
                break
        merged.append({**be, 'empty': False})
    # 尾部剩余
    for etoc, eitem in extra_sorted[next_extra:]:
        merged.append({
            'title': eitem['title'], 'population': eitem['population'],
            'toc': etoc, 'empty': True,
        })

    # ── 阶段C：差异诊断 ──
    body_only = sum(1 for be in body_entries if be['toc'] is None)
    empty_count = len(extra_sorted)
    if body_only:
        positions = [i + 1 for i, be in enumerate(body_entries) if be['toc'] is None]
        preview = positions[:10]
        suffix = "..." if len(positions) > 10 else ""
        print(f"  ⚠ {body_only} 个表格 TOC 无匹配，用 body 标题兜底（位置: {preview}{suffix}）")
    if empty_count:
        preview = ", ".join(f'"{t["title"][:40]}"' for _, t in extra_sorted[:3])
        suffix = " ..." if empty_count > 3 else ""
        print(f"  📭 TOC 中 {empty_count} 个标题无对应表格，已插入空占位: {preview}{suffix}")

    tables = [{
        'title': m['title'],
        'population': m['population'],
    } for m in merged]

    return tables


def extract_listings_with_variables(path, api_key=None, api_base=None, model="deepseek-v4-pro"):
    """从文档 TOC 提取清单编号、标题和人群（含上级标题继承 + body 校验）。
    语言无关。如果提供 api_key，使用 LLM 批量解析标题。

    三阶段:
      A. TOC → 标题队列（含 LLM 解析 + 人群继承）
      B. body 遍历 → 按序消费标题队列
      C. 差异报告
    确保清单数量/顺序与 extract_tables.py 完全一致。
    """
    doc = Document(path)
    toc = _extract_toc(doc)

    if not toc:
        print("  ⚠ 未检测到自动目录，回退到正文遍历模式")
        return _extract_listings_fallback(doc)

    # ── 阶段A-1：收集所有清单标题，批量 LLM 解析 ──
    if api_key:
        raw_titles_for_llm = []
        for _level, text in toc:
            m = _LISTING_TITLE_RE.match(text)
            if m:
                name = m.group(2).strip()
                name = re.sub(r'\s*\d+$', '', name)
                raw_titles_for_llm.append(name)
        if raw_titles_for_llm:
            _batch_resolve_titles_llm(raw_titles_for_llm, api_key, api_base, model=model)

    # ── 阶段A-2：TOC 遍历 → 构建标题队列（含人群继承）──
    pop_stack = []        # [(level, population), ...]
    title_queue = []       # [{title, population, section_id}, ...]
    seen_sections: set[str] = set()

    for level, text in toc:
        while pop_stack and pop_stack[-1][0] >= level:
            pop_stack.pop()

        own_pop = extract_population(text)

        m = _LISTING_TITLE_RE.match(text)
        if m:
            section_id, name = _parse_listing_title(text)
            if section_id in seen_sections:
                continue
            seen_sections.add(section_id)

            ancestor_pop = pop_stack[-1][1] if pop_stack else '-'
            # LLM 优先，正则兜底
            llm_pop = _llm_title_cache.get(name, {}).get('population', '')
            if llm_pop and llm_pop != '-':
                effective_pop = llm_pop
            else:
                effective_pop = own_pop if own_pop != '-' else ancestor_pop
            # 标题也使用 LLM 剥离后的核心主题词
            llm_core = _llm_title_cache.get(name, {}).get('core_subject', '')
            stored_title = llm_core if llm_core else name

            title_queue.append({
                'title': stored_title,
                'population': effective_pop,
                'section_id': section_id,
            })
            continue

        if own_pop != '-':
            pop_stack.append((level, own_pop))

    if not title_queue:
        print("  ⚠ TOC 中未提取到清单标题，回退到正文遍历模式")
        return _extract_listings_fallback(doc)

    print(f"  📑 TOC 提取到 {len(title_queue)} 个清单标题")

    # ── 阶段B：body 遍历 + TOC插排 → 合并输出 ──
    queue = list(title_queue)  # [{title, population, section_id}, ...]
    last_num = None
    last_body_title = ""
    # 建立 section_id → 原始TOC序号
    toc_id_to_idx = {}
    for idx, item in enumerate(title_queue):
        toc_id_to_idx[item['section_id']] = idx + 1  # 1-based
    body_entries = []  # [{title, population, variables, toc or None}, ...]

    for child in doc.element.body:
        tag = etree.QName(child).localname
        if tag == 'p':
            text = get_element_text(child).strip()
            if text:
                m = _LISTING_TITLE_RE.match(text)
                if m:
                    last_num = m.group(1)
                    _, body_name = _parse_listing_title(text)
                    llm_core = _llm_title_cache.get(body_name, {}).get('core_subject', '')
                    last_body_title = llm_core if llm_core else body_name
        elif tag == 'tbl':
            matched = False
            if last_num is not None:
                for i, item in enumerate(queue):
                    if item['section_id'] == last_num:
                        toc_idx = toc_id_to_idx.get(item['section_id'])
                        body_entries.append({
                            'title': item['title'],
                            'population': item['population'],
                            'variables': [], 'toc': toc_idx,
                        })
                        queue.pop(i)
                        matched = True
                        break
            if not matched:
                own_pop = extract_population(last_body_title) if last_body_title else '-'
                body_entries.append({
                    'title': last_body_title if last_body_title else '未命名',
                    'population': own_pop if own_pop != '-' else '-',
                    'variables': [], 'toc': None,
                })

    # 重建空条目
    extra_sorted = []
    for item in queue:
        toc_idx = toc_id_to_idx.get(item['section_id'])
        if toc_idx:
            extra_sorted.append((toc_idx, item))
    extra_sorted.sort(key=lambda x: x[0])

    # 合并
    merged = []
    next_extra = 0
    for be in body_entries:
        body_toc = be['toc']
        while next_extra < len(extra_sorted):
            etoc, eitem = extra_sorted[next_extra]
            if body_toc is None or etoc < body_toc:
                merged.append({
                    'title': eitem['title'], 'population': eitem['population'],
                    'variables': [], 'toc': etoc, 'empty': True,
                })
                next_extra += 1
            else:
                break
        merged.append({**be, 'empty': False})
    for etoc, eitem in extra_sorted[next_extra:]:
        merged.append({
            'title': eitem['title'], 'population': eitem['population'],
            'variables': [], 'toc': etoc, 'empty': True,
        })

    # ── 阶段C：差异诊断 ──
    body_only = sum(1 for be in body_entries if be['toc'] is None)
    empty_count = len(extra_sorted)
    if body_only:
        positions = [i + 1 for i, be in enumerate(body_entries) if be['toc'] is None]
        preview = positions[:10]
        suffix = "..." if len(positions) > 10 else ""
        print(f"  ⚠ {body_only} 个清单 TOC 无匹配，用 body 标题兜底（位置: {preview}{suffix}）")
    if empty_count:
        preview = ", ".join(f'"{t["title"][:40]}"' for _, t in extra_sorted[:3])
        suffix = " ..." if empty_count > 3 else ""
        print(f"  📭 TOC 中 {empty_count} 个标题无对应清单，已插入空占位: {preview}{suffix}")

    seq = 0
    listings = []
    for m in merged:
        seq += 1
        listings.append({
            'num': seq, 'title': m['title'],
            'variables': m.get('variables', []),
            'population': m['population'],
        })

    return listings


# ═══════════════════════════════════════════════════════════════════════════
# Fallback：正文遍历模式（当文档无 TOC 时）
# ═══════════════════════════════════════════════════════════════════════════

def _extract_tables_fallback(doc):
    """兜底：正文遍历提取表格标题 + 人群"""
    tables = []
    current_title = None
    section_pop = '-'

    for child in doc.element.body:
        tag = etree.QName(child).localname
        if tag == 'p':
            if is_toc_paragraph(child):
                continue
            text = get_element_text(child).strip()
            text = text.split('\t')[0].strip()
            m = _TABLE_TITLE_RE.match(text)
            if m:
                current_title = m.group(1).strip()
            else:
                pop = extract_population(text)
                if pop != '-':
                    section_pop = pop
        elif tag == 'tbl':
            if current_title is None:
                continue
            own_pop = extract_population(current_title)
            effective_pop = own_pop if own_pop != '-' else section_pop
            tables.append({'title': current_title, 'population': effective_pop})
            current_title = None

    return tables


def _extract_listings_fallback(doc):
    """兜底：正文遍历提取清单标题 + 变量 + 人群"""
    listings = []
    seen_sections: set[str] = set()
    current_num = None
    current_title = None
    section_pop = '-'

    for child in doc.element.body:
        tag = etree.QName(child).localname
        if tag == 'p':
            if is_toc_paragraph(child):
                continue
            text = get_element_text(child).strip()
            text = text.split('\t')[0].strip()
            m = _LISTING_TITLE_RE.match(text)
            if m:
                section_id = m.group(1)
                name = m.group(2).strip()
                name = re.sub(r'\s*\d+$', '', name)
                if section_id in seen_sections:
                    continue
                seen_sections.add(section_id)
                current_num = len(seen_sections)
                current_title = name
            else:
                pop = extract_population(text)
                if pop != '-':
                    section_pop = pop
        elif tag == 'tbl':
            if current_num is None:
                continue
            rows = child.findall(f'{{{nsmap["w"]}}}tr')
            if not rows:
                continue
            variables = [get_element_text(tc).strip()
                        for tc in rows[0].findall(f'{{{nsmap["w"]}}}tc')]
            variables = [v for v in variables if v]
            generic = {'中心号', '中心编号', '单位编号', '筛选号', '组别', '随机组别', '实际组别',
                       '随机号', '随机编号', 'FAS', 'PPS', 'SS', '是否完成试验', '是否完成实验',
                       '序号', '编号', '受试者编号', '受试者筛选号'}
            variables = [v for v in variables if v not in generic]
            own_pop = extract_population(current_title)
            effective_pop = own_pop if own_pop != '-' else section_pop
            listings.append({
                'num': current_num, 'title': current_title,
                'variables': variables, 'population': effective_pop,
            })
            current_num = None

    return listings


# ============================================================
# 关键字匹配（优先于余弦相似度）
# ============================================================

# 表格核心词 → 在清单中搜索时的同义词/缩写映射
KW_MAPPING = {
    'X胸片': 'X线胸片',
    '磁共振': '核磁共振',
    'Rankin': '修正Rankin',
    '手术成功率': '器械和手术评价',
    '器械成功率': '器械和手术评价',
    '手术信息': '手术史',
    '封堵成功率': '试验完成情况',
    '非劣效': '试验完成情况',
}


def _extract_core(title):
    """从 TFL 标题中剥离人群后缀和清单后缀，返回核心主题词。"""
    import re
    core = re.sub(r'[（(][^）)]*[）)]', '', title).strip()
    core = re.sub(r'清单$', '', core).strip()
    return core


def _strip_continuation(title):
    """去掉标题末尾的续表标记，返回可比对的核心。
    '严重不良事件清单（SS）- 续表 1' → '严重不良事件清单（SS）'
    '不良事件清单（SS）- 续表'    → '不良事件清单（SS）'
    """
    return re.sub(r'\s*[-—–]\s*续表\s*[\d一二三]*\s*$', '', title).strip()


def _find_sibling_listings(listings, best_idx):
    """找到与最佳匹配清单同属一组的所有清单（主表+续表）。

    判定：剥离续表标记后的标题相同 → 同一组的跨页拆分。
    返回按 num 排序的清单列表 [{num, title, population}, ...]
    """
    best = listings[best_idx]
    best_stripped = _strip_continuation(best['title'])
    siblings = []
    for l in listings:
        if _strip_continuation(l['title']) == best_stripped:
            siblings.append(l)
    # 按 num 排序，确保主表在前、续表在后
    siblings.sort(key=lambda l: l['num'])
    return [{
        '清单编号': l['num'], '清单名称': l['title'],
        '清单人群': l.get('population', '-'),
    } for l in siblings]


def _lcs_len(a, b):
    """最长公共子串长度（动态规划）。"""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    max_len = 0
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                max_len = max(max_len, dp[i][j])
    return max_len


def try_keyword_match(table_title, listing_titles, sim_scores=None):
    """从表格标题直接提取核心词，用最长公共子串匹配清单。

    策略：
    1. 剥离人群后缀得到核心词
    2. 在清单核心词中搜索最长公共子串 (LCS)
    3. 直接包含（A in B 或 B in A）→ 高置信度关键字匹配
    4. 非包含但 LCS >= 2 → 需余弦相似度 >= 0.5 作为质量门槛
    5. 否则退回余弦匹配

    返回 (listing_index, keyword) 或 (None, None)
    """
    core = _extract_core(table_title)
    if len(core) < 2:
        return None, None

    listing_cores = [_extract_core(lt) for lt in listing_titles]

    best_score = 0
    best_indices = []
    all_scores = []  # (score, lcs, contained, j) for all listings
    for j, lcore in enumerate(listing_cores):
        lcs = _lcs_len(core, lcore)
        contained = core in lcore or lcore in core
        score = lcs + (10 if contained else 0)
        all_scores.append((score, lcs, contained, j))

        if score > best_score:
            best_score = score
            best_indices = [j]
        elif score == best_score:
            best_indices.append(j)

    if best_score < 2 or not best_indices:
        return None, None

    # 直接包含 → 高置信度，直接通过
    if best_score >= 12:
        if len(best_indices) == 1:
            return best_indices[0], core
        if sim_scores is not None and len(sim_scores) > 0:
            return max(best_indices, key=lambda j: sim_scores[j]), core
        return best_indices[0], core

    # 非包含匹配：LCS 接近但余弦更高的候选也纳入考虑
    # 避免因 1-2 个字符的 LCS 差异错过语义更匹配的清单
    candidate_indices = set(best_indices)
    if sim_scores is not None and len(sim_scores) > 0:
        best_cos = max(sim_scores[j] for j in best_indices) if best_indices else 0
        for score, lcs, contained, j in all_scores:
            if j in candidate_indices:
                continue
            if score < 2:
                continue
            # 条件A: LCS 分差 ≤ 2 且余弦比当前最佳高 ≥ 0.05
            near_lcs = (best_score - score <= 2
                        and sim_scores[j] >= best_cos + 0.05)
            # 条件B: 余弦 ≥ 0.75 且显著高于最佳-LCS 候选（兜底高余弦命中）
            high_cos = (sim_scores[j] >= 0.75
                        and sim_scores[j] >= best_cos + 0.05)
            if near_lcs or high_cos:
                candidate_indices.add(j)

    # 滑动余弦门槛：LCS 越短要求余弦越高，避免弱关联误匹配
    if sim_scores is not None and len(sim_scores) > 0:
        lcs_only = best_score - (10 if best_score >= 12 else 0)
        if lcs_only >= 8:
            min_cos = 0.50
        elif lcs_only >= 5:
            min_cos = 0.60
        elif lcs_only >= 3:
            min_cos = 0.70
        else:
            min_cos = 0.78

        qualified = [j for j in candidate_indices if sim_scores[j] >= min_cos]
        if not qualified:
            return None, None
        return max(qualified, key=lambda j: sim_scores[j]), core

    return None, None


# ============================================================
# 匹配：关键字优先 → 余弦相似度兜底
# ============================================================

def match(tables, listings, model_name="BAAI/bge-large-zh-v1.5"):
    import os
    local_path = os.path.expanduser("~/.cache/huggingface/hub/models--BAAI--bge-large-zh-v1.5/snapshots/79e7739b6ab944e86d6171e44d24c997fc1e0116/")
    model = SentenceTransformer(local_path, local_files_only=True)

    table_cores = [strip_title(t['title']) for t in tables]
    listing_titles = [l['title'] for l in listings]

    # 始终计算余弦相似度（用于候选列表和分差参考）
    title_table_embs = model.encode([f"表格: {t}" for t in table_cores], normalize_embeddings=True)
    title_listing_embs = model.encode([f"清单: {t}" for t in listing_titles], normalize_embeddings=True)
    sim = cosine_similarity(title_table_embs, title_listing_embs)
    sim = np.clip(sim, 0, 1)

    results = []
    for i, t in enumerate(tables):
        top3 = np.argsort(sim[i])[::-1][:3]

        # ---- 先尝试关键字匹配 ----
        kw_idx, kw_name = try_keyword_match(t['title'], listing_titles, sim[i])

        if kw_idx is not None:
            # 关键字命中 → 直接采用，高置信度
            l = listings[kw_idx]
            sim_scores = sim[i].copy()
            sim_scores[kw_idx] = -1
            second_j = int(np.argmax(sim_scores))
            gap = round(float(sim[i][kw_idx] - sim[i][second_j]), 4)

            # 查找同组的所有清单（主表+续表）
            match_list = _find_sibling_listings(listings, kw_idx)

            results.append({
                "表格名称": t['title'],
                "表格人群": t.get('population', '-'),
                "最佳匹配_清单编号": l['num'],
                "最佳匹配_清单名称": l['title'],
                "清单人群": l.get('population', '-'),
                "余弦相似度": round(float(sim[i][kw_idx]), 4),
                "分差": gap,
                "来源类型": "关键字匹配",
                "置信度": "高",
                "是否需要人工审核": "否",
                "匹配清单列表": match_list,
                "候选": [
                    {"清单编号": listings[j]['num'], "清单名称": listings[j]['title'],
                     "余弦相似度": round(float(sim[i][j]), 4)}
                    for j in top3
                ],
            })
        else:
            # ---- 关键字未命中 → 余弦相似度 ----
            best_j = int(top3[0])
            second_j = int(top3[1]) if len(top3) > 1 else best_j
            l = listings[best_j]

            gap = round(float(sim[i][best_j] - sim[i][second_j]), 4)
            final_score = round(float(sim[i][best_j]), 4)

            if gap >= 0.06:
                source_type = "直接匹配"
            else:
                source_type = "多源候选"

            if source_type == "多源候选":
                conf = "低"
            elif final_score >= 0.70:
                conf = "高"
            elif final_score >= 0.58:
                conf = "中"
            else:
                conf = "低"

            if source_type == "多源候选" or conf in ("低", "中"):
                need_review = "是"
            else:
                need_review = "否"

            candidates = []
            for j in top3:
                candidates.append({
                    "清单编号": listings[j]['num'],
                    "清单名称": listings[j]['title'],
                    "余弦相似度": round(float(sim[i][j]), 4),
                })

            # 查找同组的所有清单（主表+续表）
            match_list = _find_sibling_listings(listings, best_j)

            results.append({
                "表格名称": t['title'],
                "表格人群": t.get('population', '-'),
                "最佳匹配_清单编号": l['num'],
                "最佳匹配_清单名称": l['title'],
                "清单人群": l.get('population', '-'),
                "余弦相似度": final_score,
                "分差": gap,
                "来源类型": source_type,
                "置信度": conf,
                "是否需要人工审核": need_review,
                "匹配清单列表": match_list,
                "候选": candidates,
            })

    return results


# ============================================================
# 输出
# ============================================================

def write_json(results, path):
    """输出 JSON 文件"""
    import json
    output = []
    for i, r in enumerate(results):
        method_label = r['来源类型'].replace('直接匹配', '余弦相似度匹配').replace('多源候选', '余弦相似度匹配')
        output.append({
            "表格编号": i + 1,
            "表格名称": r['表格名称'],
            "表格人群": r['表格人群'],
            "最佳匹配": {
                "清单编号": r['最佳匹配_清单编号'],
                "清单名称": r['最佳匹配_清单名称'],
                "清单人群": r['清单人群'],
            },
            "余弦相似度": r['余弦相似度'],
            "分差": r['分差'],
            "匹配方法": method_label,
            "是否需要人工审核": r['是否需要人工审核'],
            "匹配清单列表": r.get('匹配清单列表', [
                {"清单编号": r['最佳匹配_清单编号'],
                 "清单名称": r['最佳匹配_清单名称'],
                 "清单人群": r['清单人群']},
            ]),
            "候选匹配": r['候选'],
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"已写入 JSON: {path}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    import argparse
    import os as _os

    parser = argparse.ArgumentParser(description="临床试验表格-清单匹配工具 v5")
    parser.add_argument("table", help="表格文件路径 (.docx)")
    parser.add_argument("listing", help="清单文件路径 (.docx)")
    parser.add_argument("output", nargs="?", default="表格-清单-映射表.json",
                        help="输出 JSON 路径")
    parser.add_argument("--api-key", default=_os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
                        help="API Key。也支持环境变量 ANTHROPIC_AUTH_TOKEN")
    parser.add_argument("--api-base", default="https://api.deepseek.com/anthropic",
                        help="API Base URL（默认 DeepSeek）")
    parser.add_argument("--model", default="deepseek-v4-pro",
                        help="LLM 模型（默认 deepseek-v4-pro，与 Claude Code 全局配置对齐）")
    args = parser.parse_args()

    reset_llm_cache()

    tables   = extract_tables_with_columns(args.table, api_key=args.api_key or None,
                                            api_base=args.api_base, model=args.model)
    listings = extract_listings_with_variables(args.listing, api_key=args.api_key or None,
                                                api_base=args.api_base, model=args.model)

    print(f"表格: {len(tables)}  清单: {len(listings)}")
    print(f"策略: 关键字优先 → 余弦相似度兜底 | 模型: BAAI/bge-large-zh-v1.5")
    print(f"判定: 关键字命中→关键字匹配 | 分差≥0.06→直接匹配 | <0.06→多源候选")

    if tables:
        print(f"\n表格样例: {tables[0]['title']}")
    if listings:
        print(f"清单样例: {listings[0]['title']}")

    results = match(tables, listings)
    json_path = args.output.rsplit('.', 1)[0] + '.json' if '.' in args.output else args.output + '.json'
    write_json(results, json_path)

    direct = sum(1 for r in results if r["来源类型"] == "直接匹配")
    multi  = sum(1 for r in results if r["来源类型"] == "多源候选")
    kw     = sum(1 for r in results if r["来源类型"] == "关键字匹配")
    review = sum(1 for r in results if r["是否需要人工审核"] == "是")
    print(f"关键字匹配: {kw}  直接匹配: {direct}  多源候选: {multi}  需人工审核: {review}")
    print(f"平均余弦相似度: {np.mean([r['余弦相似度'] for r in results]):.4f}")
