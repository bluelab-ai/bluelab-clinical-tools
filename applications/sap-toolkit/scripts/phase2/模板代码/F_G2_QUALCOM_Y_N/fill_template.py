#!/usr/bin/env python3
"""
F_G2_QUALCOM_Y_N 填充脚本（定性指标-两组-有缺失）
categories 依次填入 分类1, 分类2, ...，每个分类有 n(%) 和 95%CI 两行
"""

import json, os, sys, copy, re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fill_template(semantic, projects):
    result = copy.deepcopy(semantic)
    row_template = result["sections"][0]["rows"]
    cat_pattern = re.compile(r"^分类\d+")

    indicators = []
    for proj in projects:
        name = proj["name"]
        categories = proj.get("categories", [])
        display = name

        rows = []
        first = True
        cat_expanded = False
        for row in row_template:
            label_vals = row.get("label_values", [])
            metric = label_vals[1] if len(label_vals) > 1 else ""
            data_vals = row.get("data_values", [])
            placeholder = data_vals[0] if data_vals else ""
            applies_to = row.get("applies_to", [])

            # 分类行：按 categories 展开，每个分类两行（n(%)+CI）
            if categories and cat_pattern.match(metric):
                if not cat_expanded:
                    for cat_name in categories:
                        rows.append({
                            "metric": f"{cat_name} n(%)",
                            "placeholder": placeholder,
                            "applies_to": applies_to,
                            "indicator": display if first else ""
                        })
                        first = False
                        rows.append({
                            "metric": f"{cat_name}的双侧95% CI(%)",
                            "placeholder": "x.x %, x.x %",
                            "applies_to": applies_to,
                            "indicator": ""
                        })
                    cat_expanded = True
                continue

            # 跳过模板中的分类CI行（已展开）
            if "的双侧95% CI(%)" in metric:
                cat_base = metric.replace("的双侧95% CI(%)", "")
                if categories and cat_pattern.match(cat_base):
                    continue

            rows.append({
                "metric": metric,
                "placeholder": placeholder,
                "applies_to": applies_to,
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
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_QUALCOM_Y_N.json")
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
