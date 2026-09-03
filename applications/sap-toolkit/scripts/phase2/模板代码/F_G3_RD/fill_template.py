#!/usr/bin/env python3
"""
F_G3_RD 填充脚本（率差比较表-多组vs对照）
categories 依次填入 XX分类
"""

import json, os, sys, copy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fill_template(semantic, projects):
    result = copy.deepcopy(semantic)
    rows_template = result["sections"][0]["rows"]

    # 分类行模板（率、率CI）
    cat_rows = rows_template[:2]
    # 间隔行
    separator = rows_template[2]
    # 汇总行（率差、率差CI）
    summary_rows = rows_template[3:]

    indicators = []
    for proj in projects:
        name = proj["name"]
        categories = proj.get("categories", [])
        display = name

        rows = []
        first = True
        if categories:
            # 按 categories 展开分类行
            for cat_name in categories:
                for row in cat_rows:
                    label_vals = row.get("label_values", [])
                    metric = label_vals[1] if len(label_vals) > 1 else ""
                    metric = metric.replace("XX分类", cat_name)
                    data_vals = row.get("data_values", [])
                    placeholder = data_vals[0] if data_vals else ""
                    rows.append({
                        "metric": metric,
                        "placeholder": placeholder,
                        "applies_to": row.get("applies_to", []),
                        "indicator": display if first else ""
                    })
                    first = False
            # 间隔行
            rows.append({
                "metric": "",
                "placeholder": "",
                "applies_to": [],
                "indicator": ""
            })
            # 汇总行（率差、率差CI）只出现一次
            for row in summary_rows:
                label_vals = row.get("label_values", [])
                metric = label_vals[1] if len(label_vals) > 1 else ""
                data_vals = row.get("data_values", [])
                placeholder = data_vals[0] if data_vals else ""
                rows.append({
                    "metric": metric,
                    "placeholder": placeholder,
                    "applies_to": row.get("applies_to", []),
                    "indicator": ""
                })
        else:
            for row in rows_template:
                label_vals = row.get("label_values", [])
                metric = label_vals[1] if len(label_vals) > 1 else ""
                if not metric and not label_vals[0]:
                    continue
                data_vals = row.get("data_values", [])
                placeholder = data_vals[0] if data_vals else ""
                rows.append({
                    "metric": metric,
                    "placeholder": placeholder,
                    "applies_to": row.get("applies_to", []),
                    "indicator": display if first else ""
                })
                first = False

        indicators.append({"name": name, "unit": "", "display": display, "rows": rows})

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G3_RD.json")
    output_path = os.path.join(SCRIPT_DIR, "填充结果.json")

    for p in [data_path, semantic_path]:
        if not os.path.exists(p):
            print(f"错误: 找不到 {p}"); sys.exit(1)

    data = load_json(data_path)
    semantic = load_json(semantic_path)
    result = fill_template(semantic, data["projects"])
    save_json(output_path, result)
    print(f"✓ 填充完成: {', '.join(i['display'] for i in result['indicators'])} → {output_path}")

if __name__ == "__main__":
    main()
