#!/usr/bin/env python3
"""临床试验表格-清单匹配工具 v5

读取提取脚本产出的标题索引 JSON，执行关键字+余弦相似度匹配。

使用:
    python3 match_tables_listings.py <表格-标题索引.json> <清单-标题索引.json> [输出.json]
"""

import json
import os
import re
import sys

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# ============================================================
# 关键字匹配（优先于余弦相似度）
# ============================================================

KW_MAPPING = {
    'X胸片': 'X线胸片', '磁共振': '核磁共振', 'Rankin': '修正Rankin',
    '手术成功率': '器械和手术评价', '器械成功率': '器械和手术评价',
    '手术信息': '手术史', '封堵成功率': '试验完成情况', '非劣效': '试验完成情况',
}


def _strip_continuation(title):
    return re.sub(r'\s*[-—–]\s*(?:续表\s*[\d一二三]*|Continued?\s*\d*)\s*$', '', title, flags=re.IGNORECASE).strip()


def _find_sibling_listings(listings, best_idx):
    best = listings[best_idx]
    best_stripped = _strip_continuation(best['title'])
    siblings = []
    for l in listings:
        if _strip_continuation(l['title']) == best_stripped:
            siblings.append(l)
    siblings.sort(key=lambda l: l.get('num', l.get('seq', 0)))
    return [{'清单编号': l.get('num', l.get('seq')), '清单名称': l['title'],
             '清单人群': l.get('population', '-')} for l in siblings]


def _lcs_len(a, b):
    m, n = len(a), len(b)
    if m == 0 or n == 0: return 0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    max_len = 0
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                max_len = max(max_len, dp[i][j])
    return max_len


def try_keyword_match(table_title, listing_titles, sim_scores=None):
    # JSON 中的 title 已经过 _strip_title 处理
    if len(table_title) < 3: return None, None

    best_lcs, best_idx = 0, None
    for j, lt in enumerate(listing_titles):
        lcs = _lcs_len(table_title, lt)
        if lcs > best_lcs:
            best_lcs, best_idx = lcs, j

    if best_lcs >= 3:
        return best_idx, table_title
    return None, None


# ============================================================
# 匹配主函数
# ============================================================

def match(tables, listings, model_name="BAAI/bge-large-zh-v1.5"):
    import os as _os
    local_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))),
        "models--BAAI--bge-large-zh-v1.5",
        "snapshots",
        "79e7739b6ab944e86d6171e44d24c997fc1e0116",
    )
    model = SentenceTransformer(local_path, local_files_only=True)

    # JSON 中的 title 已经过 _strip_title，可以直接用
    table_cores = [t['title'] for t in tables]
    listing_titles = [l['title'] for l in listings]

    te = model.encode([f"表格: {t}" for t in table_cores], normalize_embeddings=True)
    le = model.encode([f"清单: {t}" for t in listing_titles], normalize_embeddings=True)
    sim = cosine_similarity(te, le)
    sim = np.clip(sim, 0, 1)

    results = []
    for i, t in enumerate(tables):
        top3 = np.argsort(sim[i])[::-1][:3]
        kw_idx, kw_name = try_keyword_match(t['title'], listing_titles, sim[i])

        if kw_idx is not None:
            l = listings[kw_idx]
            sc = sim[i].copy(); sc[kw_idx] = -1
            second_j = int(np.argmax(sc))
            gap = round(float(sim[i][kw_idx] - sim[i][second_j]), 4)
            match_list = _find_sibling_listings(listings, kw_idx)
            results.append({
                "表格名称": t['title'], "表格人群": t.get('population', '-'),
                "最佳匹配_清单编号": l.get('num', l.get('seq')),
                "最佳匹配_清单名称": l['title'],
                "清单人群": l.get('population', '-'),
                "余弦相似度": round(float(sim[i][kw_idx]), 4), "分差": gap,
                "来源类型": "关键字匹配", "置信度": "高", "是否需要人工审核": "否",
                "匹配清单列表": match_list,
                "候选": [{"清单编号": listings[j].get('num', listings[j].get('seq')),
                          "清单名称": listings[j]['title'],
                          "清单人群": listings[j].get('population', '-'),
                          "余弦相似度": round(float(sim[i][j]), 4)} for j in top3],
            })
        else:
            best_j = int(top3[0])
            second_j = int(top3[1]) if len(top3) > 1 else best_j
            l = listings[best_j]
            gap = round(float(sim[i][best_j] - sim[i][second_j]), 4)
            final_score = round(float(sim[i][best_j]), 4)
            source_type = "直接匹配" if gap >= 0.06 else "多源候选"

            if source_type == "多源候选": conf = "低"
            elif final_score >= 0.70: conf = "高"
            elif final_score >= 0.58: conf = "中"
            else: conf = "低"

            need_review = "是" if (source_type == "多源候选" or conf in ("低", "中")) else "否"
            match_list = _find_sibling_listings(listings, best_j)
            results.append({
                "表格名称": t['title'], "表格人群": t.get('population', '-'),
                "最佳匹配_清单编号": l.get('num', l.get('seq')),
                "最佳匹配_清单名称": l['title'],
                "清单人群": l.get('population', '-'),
                "余弦相似度": final_score, "分差": gap,
                "来源类型": source_type, "置信度": conf, "是否需要人工审核": need_review,
                "匹配清单列表": match_list,
                "候选": [{"清单编号": listings[j].get('num', listings[j].get('seq')),
                          "清单名称": listings[j]['title'],
                          "清单人群": listings[j].get('population', '-'),
                          "余弦相似度": round(float(sim[i][j]), 4)} for j in top3],
            })

    return results


# ============================================================
# 输出
# ============================================================

def write_json(results, path):
    output = []
    for i, r in enumerate(results):
        method_label = r['来源类型'].replace('直接匹配', '余弦相似度匹配').replace('多源候选', '余弦相似度匹配')
        output.append({
            "表格编号": i + 1, "表格名称": r['表格名称'], "表格人群": r['表格人群'],
            "最佳匹配": {
                "清单编号": r['最佳匹配_清单编号'],
                "清单名称": r['最佳匹配_清单名称'],
                "清单人群": r['清单人群'],
            },
            "余弦相似度": r['余弦相似度'], "分差": r['分差'], "匹配方法": method_label,
            "是否需要人工审核": r['是否需要人工审核'],
            "匹配清单列表": r.get('匹配清单列表', [
                {"清单编号": r['最佳匹配_清单编号'], "清单名称": r['最佳匹配_清单名称'],
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

    parser = argparse.ArgumentParser(description="临床试验表格-清单匹配工具 v5")
    parser.add_argument("table_index", help="表格-标题索引.json 路径（由 extract_tables.py 产出）")
    parser.add_argument("listing_index", help="清单-标题索引.json 路径（由 extract_tables.py 产出）")
    parser.add_argument("output", nargs="?", default="表格-清单-映射表.json", help="输出 JSON 路径")
    args = parser.parse_args()

    with open(args.table_index) as f: tables = json.load(f)
    with open(args.listing_index) as f: listings = json.load(f)

    print(f"表格: {len(tables)}  清单: {len(listings)}")
    print(f"策略: 关键字优先 → 余弦相似度兜底 | 模型: BAAI/bge-large-zh-v1.5")

    if tables: print(f"\n表格样例: {tables[0]['title']}")
    if listings: print(f"清单样例: {listings[0]['title']}")

    results = match(tables, listings)
    json_path = args.output.rsplit('.', 1)[0] + '.json' if '.' in args.output else args.output + '.json'
    write_json(results, json_path)

    direct = sum(1 for r in results if r["来源类型"] == "直接匹配")
    multi  = sum(1 for r in results if r["来源类型"] == "多源候选")
    kw     = sum(1 for r in results if r["来源类型"] == "关键字匹配")
    review = sum(1 for r in results if r["是否需要人工审核"] == "是")
    print(f"关键字匹配: {kw}  直接匹配: {direct}  多源候选: {multi}  需人工审核: {review}")
    print(f"平均余弦相似度: {np.mean([r['余弦相似度'] for r in results]):.4f}")
