#!/usr/bin/env python3
"""临床试验表格-清单匹配工具（PDF版）

从 match_tables_listings.py 复用匹配算法，将 docx 提取部分替换为 pdfplumber 提取。
匹配逻辑（关键字→余弦→DeepSeek）完全一致，输出 JSON 格式完全兼容。

用法:
    python3 match_tables_listings_pdf.py <表格文件.pdf> <清单文件.pdf> [输出.json]
"""

import re
import sys
import os
import json
import pdfplumber
import numpy as np

# 从 docx 版复用匹配算法和输出函数
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import match_tables_listings as matcher


# ============================================================
# PDF 提取（替代 docx 版 extract_tables_with_columns / extract_listings_with_variables）
# ============================================================

def is_toc_page_pdf(page, doc_type):
    """判断是否为目录页"""
    text = page.extract_text()
    if not text:
        return False
    lines = text.split('\n')
    if '目录' in lines[:3]:
        return True
    prefix = '清单' if doc_type == '清单' else '表'
    toc = sum(1 for l in lines if re.match(rf'^({prefix})\s*\d', l.strip()))
    sep = sum(1 for l in lines if '........' in l or '……' in l)
    return (toc > 3 and sep > 3) if doc_type == '清单' else (toc > 5 and sep > 3)


def extract_tables_from_pdf(path):
    """从 PDF 提取表格：标题 + 人群（含上级标题人群继承）

    返回格式与 extract_tables_with_columns 兼容：
        [{'title': str, 'population': str}, ...]
    """
    tables = []
    section_pop = '-'
    seen_titles = set()

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if is_toc_page_pdf(page, '表格'):
                continue
            text = page.extract_text()
            if not text:
                continue

            for line in text.split('\n'):
                line = line.strip()

                # 检测上级标题的人群标识（不含表格/清单编号的段落）
                pop = matcher.extract_population(line)
                if pop != '-' and not re.match(r'^(表\s*\d|清单\s*\d)', line):
                    section_pop = pop

                # 检测表格标题
                m = re.match(r'^表\s*(\d[\d.]*)\s+(.+)', line)
                if not m:
                    continue

                title = m.group(2).strip()
                # 排除仅编号无实质内容的行
                if re.match(r'^表\s*\d[\d.]*\s*$', line):
                    continue
                # 排除统计方法/样板行（表格多行表头中的重复文本）
                if re.search(
                    r'(统计方法|检验统计量|P值\s*$|例数\(缺失\)|成功\s*n\(%|失败\s*n\(%|男\s*n\(%|女\s*n\()',
                    title
                ):
                    continue

                if title in seen_titles:
                    continue
                seen_titles.add(title)

                own_pop = matcher.extract_population(title)
                effective_pop = own_pop if own_pop != '-' else section_pop

                tables.append({
                    'title': title,
                    'population': effective_pop,
                })

    return tables


def extract_listings_from_pdf(path):
    """从 PDF 提取清单：标题 + 人群（含上级标题人群继承）

    返回格式与 extract_listings_with_variables 兼容：
        [{'num': int, 'title': str, 'variables': [], 'population': str}, ...]

    与 Word 版关键差异：
    - 不要求标题后紧跟表格，看到即记录（避免因书签/交叉引用造成的静默丢失）
    - 去重放在成功记录后，而非看到标题时（修复 Word 版 seen_num 时序缺陷）
    """
    listings = []
    section_pop = '-'
    seen_nums = set()

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if is_toc_page_pdf(page, '清单'):
                continue
            text = page.extract_text()
            if not text:
                continue

            for line in text.split('\n'):
                line = line.strip()

                # 检测上级标题的人群标识
                pop = matcher.extract_population(line)
                if pop != '-' and not re.match(r'^(表\s*\d|清单\s*\d)', line):
                    section_pop = pop

                # 检测清单标题
                m = re.match(r'^清单\s*(\d+)\s+(.+)', line)
                if not m:
                    continue

                num = int(m.group(1))
                name = m.group(2).strip()
                if '续' in name:
                    continue
                if num in seen_nums:
                    continue

                own_pop = matcher.extract_population(name)
                effective_pop = own_pop if own_pop != '-' else section_pop

                listings.append({
                    'num': num,
                    'title': name,
                    'variables': [],  # PDF 不提取变量名（匹配仅用标题）
                    'population': effective_pop,
                })
                seen_nums.add(num)  # 成功记录后才标记（而非看到标题时就标记）

    return listings


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python3 match_tables_listings_pdf.py <表格文件.pdf> <清单文件.pdf> [输出.json]")
        sys.exit(1)

    table_path = sys.argv[1]
    listing_path = sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else "表格-清单-映射表.json"

    tables = extract_tables_from_pdf(table_path)
    listings = extract_listings_from_pdf(listing_path)

    print(f"表格: {len(tables)}  清单: {len(listings)}")
    print(f"策略: 关键字优先 → 余弦相似度兜底 | 模型: BAAI/bge-large-zh-v1.5")
    print(f"判定: 关键字命中→关键字匹配 | 分差≥0.06→直接匹配 | <0.06→多源候选")
    print(f"(PDF 提取模式: 标题不依赖后续表格，去重后置)")

    if tables:
        print(f"\n表格样例: {tables[0]['title']}")
    if listings:
        print(f"清单样例: {listings[0]['title']}")

    results = matcher.match(tables, listings)
    json_path = out_path.rsplit('.', 1)[0] + '.json' if '.' in out_path else out_path + '.json'
    matcher.write_json(results, json_path)

    direct = sum(1 for r in results if r["来源类型"] == "直接匹配")
    multi = sum(1 for r in results if r["来源类型"] == "多源候选")
    kw = sum(1 for r in results if r["来源类型"] == "关键字匹配")
    review = sum(1 for r in results if r["是否需要人工审核"] == "是")
    print(f"关键字匹配: {kw}  直接匹配: {direct}  多源候选: {multi}  需人工审核: {review}")
    print(f"平均余弦相似度: {np.mean([r['余弦相似度'] for r in results]):.4f}")
