#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从外部人群划分表 / 随机表抽出 external_ref.json，作为 TFL 分中心/人群
一致性核查（R-050~R-053）的权威基准。

用法::

    # 同时上传两表：先按"筛选号"合并再抽 ref
    python3 prepare_external_ref.py \\
        --population 人群划分表.xlsx \\
        --randomization 随机表.xlsx \\
        --out tables_output/external_ref.json

    # 仅上传人群划分表
    python3 prepare_external_ref.py --population 人群划分表.xlsx \\
        --out tables_output/external_ref.json

    # 仅上传随机表
    python3 prepare_external_ref.py --randomization 随机表.xlsx \\
        --out tables_output/external_ref.json

产出 JSON 结构（字段能填就填，抽不到的静默留空——下游规则遇 None 就跳过）::

    {
      "by_center": {
        "01": {
          "随机化人群": {"试验组": 15, "对照组": 10, "合计": 25},
          "FAS": {"试验组": 14, "对照组": 10, "合计": 24},
          "PPS": {"试验组": 13, "对照组": 10, "合计": 23},
          "SS":  {"试验组": 15, "对照组": 10, "合计": 25}
        },
        "02": {...},
        ...
        "合计": {
          "随机化人群": {"试验组": ..., "对照组": ..., "合计": ...},
          "FAS": {"试验组": ..., "对照组": ..., "合计": ...},
          "PPS": {...}, "SS": {...}
        }
      },
      "by_analysis_set": {
        "FAS":  {"试验组": 50, "对照组": 48, "合计": 98},
        "PPS":  {...}, "SS": {...}, "ITT": {...}, "mITT": {...}
      },
      "randomization": {
        "total_screened":  244,   # 筛选总数（有筛选号）
        "total_successful": 219,  # 筛选成功
        "total_failed":     25    # 筛选失败
      },
      "exclusion_reasons": {"未收集到主要指标": 3, "违反纳排": 2, ...},
      "meta": {"sources": [...], "key": "筛选号", "n_rows": 244}
    }

设计约定::

- 列名匹配采用别名列表（"单位编号|中心号"、"剔除原因|脱落原因"），命中即用
- 分析集列（FAS/PPS/SS/ITT/mITT）通过精确列名匹配；单元格值为"纳入"计入，其他跳过
- 组别列匹配"组别"；值"试验组""对照组"计入；其他非空归入原始值（便于人工回溯）
- **by_center 分槽**：`随机化人群` 槽按中心 × 组别数人（每个筛选号一人，不过滤
  纳入/剔除），供入组病例表 / 病例分布表 R-050 使用；`FAS / PPS / SS / ITT / mITT`
  槽只计各分析集列被标"纳入"的受试者，剔除者不算。若外部表没有分析集列，只有
  `随机化人群` 槽会有值
- 同时产出 baseline.json（Phase 4 subagent 检测到后不会覆写），仅当 by_analysis_set 非空
- 若同时上传 population + randomization，合并后的宽表**另存为 xlsx**（默认
  `external_merged.xlsx` 与 external_ref.json 同目录），方便人工回溯
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge_by_key import load_table, merge, write_xlsx  # noqa: E402


# 列名别名（按顺序试，命中即用）
COL_ALIASES = {
    "center":  ["单位编号", "中心号", "中心编号", "研究中心"],
    "group":   ["组别", "分组", "治疗组"],
    "exclude": ["剔除原因", "脱落原因", "剔除/脱落原因"],
    "success": ["是否筛选成功", "筛选成功", "筛选结果"],
    "random_no": ["随机号", "随机编号"],
}
# 分析集列：精确匹配 acronym；外部合并表的原始列可能带后缀（"ITT人群"），用 startswith 兜底
SET_LABELS = ("mITT", "ITT", "FAS", "PPS", "SS")


def _stringify(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def find_col(headers, aliases):
    """按别名列表在 headers 里找列索引；找不到返回 None。"""
    for name in aliases:
        if name in headers:
            return headers.index(name)
    return None


def find_set_col(headers, label):
    """精确 or 带后缀（label + 人群/集）匹配分析集列，找不到返回 None。"""
    for i, h in enumerate(headers):
        if h == label:
            return i
        if h.startswith(label):
            rest = h[len(label):].strip()
            if rest in ("", "人群", "集"):
                return i
    return None


def load_source(pop_path, rand_path):
    """按输入组合读原始数据，返回 (headers, rows, source_list)。"""
    if pop_path and rand_path:
        headers, rows, _ = merge(pop_path, rand_path,
                                 key_name="筛选号", how="outer")
        return headers, rows, [pop_path, rand_path]
    single = pop_path or rand_path
    headers, rows, _, _ = load_table(single, "筛选号")
    return headers, rows, [single]


def build_ref(headers, rows):
    """基于合并/单表的 subject-level 数据聚合出 external_ref。"""
    ref = {"by_center": {}, "by_analysis_set": {},
           "randomization": {}, "exclusion_reasons": {}, "meta": {}}

    # 定位关键列
    col_center = find_col(headers, COL_ALIASES["center"])
    col_group = find_col(headers, COL_ALIASES["group"])
    col_exclude = find_col(headers, COL_ALIASES["exclude"])
    col_success = find_col(headers, COL_ALIASES["success"])
    col_random_no = find_col(headers, COL_ALIASES["random_no"])
    set_cols = {lab: find_set_col(headers, lab) for lab in SET_LABELS}

    # by_center：结构 {center: {analysis_set: {group: count}}}
    # - "随机化人群" 槽：只要中心+组别有值就计入，不过滤 纳入/剔除
    #   （每个筛选号一人；供入组病例表 / 病例分布表 R-050 使用）
    # - FAS / PPS / SS / ITT / mITT 槽：只计对应分析集列被标"纳入"的受试者
    #   （被标"剔除"或空的不算；供人群划分表 R-050 及各分析集专用表使用）
    valid_set_cols = [(lab, col) for lab, col in set_cols.items() if col is not None]
    if col_center is not None and col_group is not None:
        agg = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        for r in rows:
            c = _stringify(r[col_center]) if col_center < len(r) else ""
            g = _stringify(r[col_group]) if col_group < len(r) else ""
            if not c or c in ("NA", "nan", "None"):
                continue
            if g not in ("试验组", "对照组"):
                continue
            # 随机化人群（不过滤纳入）
            agg[c]["随机化人群"][g] += 1
            agg[c]["随机化人群"]["合计"] += 1
            agg["合计"]["随机化人群"][g] += 1
            agg["合计"]["随机化人群"]["合计"] += 1
            # 各分析集（"纳入" 才算）
            for lab, col in valid_set_cols:
                val = _stringify(r[col]) if col < len(r) else ""
                if val != "纳入":
                    continue
                agg[c][lab][g] += 1
                agg[c][lab]["合计"] += 1
                agg["合计"][lab][g] += 1
                agg["合计"][lab]["合计"] += 1
        ref["by_center"] = {
            c: {lab: dict(gv) for lab, gv in sv.items()}
            for c, sv in agg.items()
        }

    # by_analysis_set：分析集列值为"纳入"的按 group 计数
    if col_group is not None:
        for lab, col in set_cols.items():
            if col is None:
                continue
            per_group = defaultdict(int)
            for r in rows:
                val = _stringify(r[col]) if col < len(r) else ""
                grp = _stringify(r[col_group]) if col_group < len(r) else ""
                if val == "纳入" and grp in ("试验组", "对照组"):
                    per_group[grp] += 1
                    per_group["合计"] += 1
            if per_group:
                ref["by_analysis_set"][lab] = dict(per_group)

    # randomization：以 col_success 或 col_random_no 判断
    total = len(rows)
    success = failed = None
    if col_success is not None:
        success = sum(1 for r in rows
                      if col_success < len(r)
                      and _stringify(r[col_success]) == "是")
        failed = sum(1 for r in rows
                     if col_success < len(r)
                     and _stringify(r[col_success]) == "否")
    elif col_random_no is not None:
        success = sum(1 for r in rows
                      if col_random_no < len(r)
                      and _stringify(r[col_random_no]) not in ("", "NA", "None"))
        failed = total - success
    if success is not None:
        ref["randomization"] = {
            "total_screened": total,
            "total_successful": success,
            "total_failed": failed,
        }

    # exclusion_reasons：非空的剔除文本计数
    if col_exclude is not None:
        reasons = defaultdict(int)
        for r in rows:
            v = _stringify(r[col_exclude]) if col_exclude < len(r) else ""
            if v and v not in ("NA", "None", "nan"):
                reasons[v] += 1
        ref["exclusion_reasons"] = dict(reasons)

    return ref, {
        "col_center": col_center, "col_group": col_group,
        "col_exclude": col_exclude, "col_success": col_success,
        "col_random_no": col_random_no, "set_cols": set_cols,
    }


def write_baseline_from_ref(ref, out_dir):
    """如果抽到了 by_analysis_set，就顺便写 baseline.json（兼容旧下游）。

    仅当路径不存在时写；否则不覆盖（尊重用户已有基准）。
    """
    if not ref.get("by_analysis_set"):
        return None
    baseline_path = os.path.join(out_dir, "baseline.json")
    if os.path.exists(baseline_path):
        print(f"ℹ️  {baseline_path} 已存在，不覆盖（如需重生成请先删除）")
        return None
    os.makedirs(out_dir, exist_ok=True)
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(ref["by_analysis_set"], f, ensure_ascii=False, indent=2)
    return baseline_path


def main():
    ap = argparse.ArgumentParser(
        description="从外部人群划分表/随机表建立 external_ref.json，供 R-050~R-053 使用"
    )
    ap.add_argument("--population", help="外部人群划分表 xlsx（含'筛选号'列）")
    ap.add_argument("--randomization", help="外部随机表 xlsx（含'筛选号'列）")
    ap.add_argument("--out", default="tables_output/external_ref.json",
                    help="输出 external_ref.json 路径")
    ap.add_argument("--merged-xlsx", default=None,
                    help="两表都上传时合并后 xlsx 的落盘路径；默认与 external_ref.json"
                         " 同目录、命名 external_merged.xlsx。仅在同时给出 --population"
                         " 与 --randomization 时生效")
    args = ap.parse_args()

    if not args.population and not args.randomization:
        sys.exit("错误：至少要提供 --population 或 --randomization 中的一个")
    for p in (args.population, args.randomization):
        if p and not os.path.exists(p):
            sys.exit(f"错误：文件不存在 {p}")

    headers, rows, sources = load_source(args.population, args.randomization)

    # 两表都给了 → 顺手把合并宽表落盘，方便人工回溯
    merged_xlsx_path = None
    if args.population and args.randomization:
        merged_xlsx_path = args.merged_xlsx or os.path.join(
            os.path.dirname(os.path.abspath(args.out)) or ".",
            "external_merged.xlsx",
        )
        write_xlsx(headers, rows, merged_xlsx_path)

    ref, col_meta = build_ref(headers, rows)
    ref["meta"] = {
        "sources": [os.path.basename(p) for p in sources],
        "key": "筛选号",
        "n_rows": len(rows),
        "columns_located": {k: v for k, v in col_meta.items() if v is not None
                            and k != "set_cols"},
        "analysis_set_cols": {k: v for k, v in col_meta["set_cols"].items()
                              if v is not None},
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)

    # 兼容产出 baseline.json（如抽到分析集）
    out_dir = os.path.dirname(os.path.abspath(args.out))
    baseline_path = write_baseline_from_ref(ref, out_dir)

    # 摘要
    print(f"\n已写出 external_ref.json → {args.out}")
    if merged_xlsx_path:
        print(f"  合并宽表 → {merged_xlsx_path}")
    n_centers = sum(1 for c in ref["by_center"] if c != "合计")
    n_sets = len(ref["by_analysis_set"])
    n_reasons = len(ref["exclusion_reasons"])
    rand = ref.get("randomization", {})
    print(f"  分中心: {n_centers} 个中心（+合计），每中心嵌套 随机化人群 + 各分析集槽位")
    print(f"  分析集: {n_sets} 个 ({'、'.join(ref['by_analysis_set']) or '—'})")
    print(f"  随机化: 筛选 {rand.get('total_screened','—')}"
          f" / 成功 {rand.get('total_successful','—')}"
          f" / 失败 {rand.get('total_failed','—')}")
    print(f"  剔除原因: {n_reasons} 类")
    if baseline_path:
        print(f"  同时产出 baseline.json → {baseline_path}")


if __name__ == "__main__":
    main()
