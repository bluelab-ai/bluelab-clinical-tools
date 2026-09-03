#!/usr/bin/env python3
"""
F_G2_RD 填充脚本（率差比较表-两组）
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
    sections = result.get("sections", [])

    # 分类：前3个 section（率、率CI、间隔行）
    # 汇总：后2个 section（率差、率差CI）
    cat_sections = sections[:2]   # 率、率CI
    sum_sections = sections[3:]   # 率差、率差CI

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
                for section in cat_sections:
                    label_vals = section.get("label_values", [])
                    metric = label_vals[1] if len(label_vals) > 1 else ""
                    metric = metric.replace("XX分类", cat_name)
                    data_vals = section.get("data_values", [])
                    placeholder = data_vals[0] if data_vals else ""
                    rows.append({
                        "metric": metric,
                        "placeholder": placeholder,
                        "applies_to": section.get("applies_to", []),
                        "indicator": display if first else ""
                    })
                    first = False
            # 汇总行（率差、率差CI）只出现一次
            for section in sum_sections:
                label_vals = section.get("label_values", [])
                metric = label_vals[1] if len(label_vals) > 1 else ""
                data_vals = section.get("data_values", [])
                placeholder = data_vals[0] if data_vals else ""
                rows.append({
                    "metric": metric,
                    "placeholder": placeholder,
                    "applies_to": section.get("applies_to", []),
                    "indicator": ""
                })
        else:
            for section in sections:
                label_vals = section.get("label_values", [])
                metric = label_vals[1] if len(label_vals) > 1 else ""
                if not metric and not label_vals[0]:
                    continue
                data_vals = section.get("data_values", [])
                placeholder = data_vals[0] if data_vals else ""
                rows.append({
                    "metric": metric,
                    "placeholder": placeholder,
                    "applies_to": section.get("applies_to", []),
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
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_RD.json")
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
