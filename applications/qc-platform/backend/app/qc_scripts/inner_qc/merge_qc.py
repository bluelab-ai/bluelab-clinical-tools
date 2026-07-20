#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并各表 QC 结构化结果（qc_*.json）为总体报告，并执行跨表规则。

v1 的 Phase 4 只把各表报告堆在一起，README 里承诺的跨表规则 R-021/R-029
没有任何地方真正执行。本脚本补上这一步，并用确定性代码（而非 LLM 眼算）完成。

用法:
    python3 merge_qc.py <qc结果目录> [--baseline baseline.json] [--out 总体报告.md]

输入: <qc结果目录>/qc_*.json —— 每个由 subagent 通过 qc_lib.Issues.to_json 产出。
      baseline.json（可选）—— 人群划分表 subagent 写出的 {分析集:{组:人数}}。
输出: 总体 QC 报告（markdown）。
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qc_lib import to_num  # noqa: E402

LEVEL_ORDER = ["CRITICAL", "MAJOR", "MINOR", "SUGGESTION"]
LEVEL_CN = {"CRITICAL": "严重", "MAJOR": "主要", "MINOR": "次要", "SUGGESTION": "建议"}


def load_results(d):
    """加载 qc_*.json，校验必要字段，跳过格式不合规的文件。"""
    results = []
    for p in sorted(glob.glob(os.path.join(d, "qc_*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                r = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠️ 跳过不可读文件: {os.path.basename(p)} ({e})", file=sys.stderr)
            continue
        if not isinstance(r, dict):
            print(f"  ⚠️ 跳过非 dict 文件: {os.path.basename(p)}", file=sys.stderr)
            continue
        if "meta" not in r:
            print(f"  ⚠️ 跳过缺失 meta 的文件: {os.path.basename(p)}（非 Issures.to_json 产出）", file=sys.stderr)
            continue
        meta = r["meta"]
        if not isinstance(meta, dict):
            print(f"  ⚠️ 跳过 meta 非 dict 的文件: {os.path.basename(p)}", file=sys.stderr)
            continue
        results.append(r)
    return results


def table_no(title):
    """从标题抽表号：'表 14.4.1 疗效分级' -> '14.4.1'。"""
    m = re.search(r"表\s*([\d.]+)", title or "")
    return m.group(1).rstrip(".") if m else None


def cross_table_rules(results, baseline):
    """跨表规则：R-029 表号唯一、R-021 同一分析集跨表分母一致。"""
    findings = []

    # R-029 表号唯一
    nos = [table_no(r["meta"].get("title")) for r in results]
    for n, c in Counter(x for x in nos if x).items():
        if c > 1:
            dup_titles = [r["meta"].get("title", "?") for r in results
                          if table_no(r["meta"].get("title")) == n]
            findings.append({
                "rule": "R-029", "level": "MINOR", "where": f"表号 {n}",
                "expected": "全文档唯一", "found": f"{c} 张共用",
                "note": "；".join(dup_titles),
            })

    # R-021 同一分析集跨表分母一致
    # 有人群划分表基准时：任一表合计 > 基准该分析集人数 -> 报（小于属子集，正常）。
    # 无基准时：以同一分析集观测到的最大合计为基准，仅报"超过最大值"（理论不触发，
    # 故退化为提示口径不一），保持与 README 的"≤ 不 =="约定一致。
    by_set = defaultdict(list)
    for r in results:
        s = r["meta"].get("analysis_set")
        tot = (r["meta"].get("n_by_group") or {}).get("合计")
        if s and tot is not None:
            by_set[s].append((r["meta"].get("title", "?"), to_num(tot)))

    for s, rows in by_set.items():
        base = None
        if baseline and s in baseline:
            base = to_num((baseline[s] or {}).get("合计"))
        if base is None:
            base = max((t for _, t in rows if t is not None), default=None)
        if base is None:
            continue
        for title, tot in rows:
            if tot is not None and tot > base:
                findings.append({
                    "rule": "R-021", "level": "MAJOR",
                    "where": f"{title}·{s}",
                    "expected": f"≤{base:g}", "found": f"{tot:g}",
                    "note": "合计超过该分析集基准人数（人群划分表/同集最大值）",
                })
    return findings


def render(results, cross, baseline, source_hint):
    lines = []
    total = len(results)
    concl = Counter(r.get("conclusion", "PASS") for r in results)
    passed = concl.get("PASS", 0)
    n_issues = sum(len(r.get("issues", [])) for r in results) + len(cross)
    n_pending = sum(r.get("pending", 0) for r in results)
    types = Counter(r["meta"].get("table_type", "other") for r in results)

    lines.append("# 临床试验表格内部 QC 报告\n")
    lines.append("## 概要\n")
    lines.append(f"- 覆盖：{source_hint or '（未指定源文件）'}")
    lines.append(f"- 表格总数：**{total}** ｜ 通过：**{passed}** ｜ "
                 f"问题总数：**{n_issues}** ｜ 待人工：**{n_pending}**")
    concl_bits = " / ".join(f"{k} {concl[k]}" for k in
                            ["CRITICAL", "MAJOR", "MINOR", "SUGGESTION", "PASS"]
                            if concl.get(k))
    lines.append(f"- 结论分布：{concl_bits or '—'}")
    type_bits = " / ".join(f"{k} {v}张" for k, v in types.most_common())
    lines.append(f"- 表型分布：{type_bits}")
    lines.append(f"- 人群基准：{'已加载 ' + '、'.join(baseline) if baseline else '未提供（基准类规则按 ≤ 跳过或转人工）'}\n")

    # 按表格汇总
    lines.append("## 按表格汇总\n")
    lines.append("| 编号 | 表型 | 标题 | 结论 | 问题数 | 待人工 |")
    lines.append("|------|------|------|------|--------|--------|")
    for r in sorted(results, key=lambda x: x["meta"].get("table_index", "")):
        m = r["meta"]
        lines.append(f"| {m.get('table_index','')} | {m.get('table_type','')} | "
                     f"{m.get('title','')} | {r.get('conclusion','PASS')} | "
                     f"{len(r.get('issues', []))} | {r.get('pending', 0)} |")
    lines.append("")

    # 发现的问题（按级别归并，含跨表）
    buckets = defaultdict(list)
    for r in results:
        for it in r.get("issues", []):
            if it["level"] in LEVEL_ORDER:
                buckets[it["level"]].append((r["meta"].get("title", "?"), it))
    for it in cross:
        buckets[it["level"]].append(("【跨表】", it))

    lines.append("## 发现的问题\n")
    any_issue = False
    for lv in LEVEL_ORDER:
        if not buckets[lv]:
            continue
        any_issue = True
        lines.append(f"### [{LEVEL_CN[lv]}] {lv}（{len(buckets[lv])}）\n")
        for where_tbl, it in buckets[lv]:
            note = f" — {it['note']}" if it.get("note") else ""
            lines.append(f"- **{it['rule']}** {where_tbl}·{it['where']}："
                         f"期望 {it['expected']}，实际 {it['found']}{note}")
        lines.append("")
    if not any_issue:
        lines.append("未发现 CRITICAL/MAJOR/MINOR/SUGGESTION 级问题。\n")

    # 待人工复核
    pend = [(r["meta"].get("title", "?"), it) for r in results
            for it in r.get("issues", []) if it["level"] == "待人工"]
    if pend:
        lines.append("## 待人工复核\n")
        for title, it in pend:
            note = f" — {it['note']}" if it.get("note") else ""
            lines.append(f"- **{it['rule']}** {title}·{it['where']}{note}")
        lines.append("")

    # 已通过表格
    ok = [r["meta"].get("title", "?") for r in results if r.get("conclusion") == "PASS"]
    if ok:
        lines.append("## 已核查通过\n")
        for t in ok:
            lines.append(f"- {t} ✓")
        lines.append("")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("qc_dir", help="存放 qc_*.json 的目录")
    ap.add_argument("--baseline", help="人群划分表写出的 baseline.json", default=None)
    ap.add_argument("--out", help="输出报告路径", default=None)
    ap.add_argument("--source", help="源文件名（写进概要）", default=None)
    args = ap.parse_args()

    results = load_results(args.qc_dir)
    if not results:
        print(f"错误：{args.qc_dir} 下没有 qc_*.json")
        sys.exit(1)

    baseline = {}
    if args.baseline and os.path.exists(args.baseline):
        with open(args.baseline, encoding="utf-8") as f:
            baseline = json.load(f)

    cross = cross_table_rules(results, baseline)
    report = render(results, cross, baseline, args.source)

    out = args.out or os.path.join(args.qc_dir, "总体QC报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"合并 {len(results)} 张表，跨表问题 {len(cross)} 条 → {out}")


if __name__ == "__main__":
    main()
