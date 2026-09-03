#!/usr/bin/env python3
"""
F_G2_QUALSITE_N_N 填充脚本（定性指标-两组-无缺失-中心）
在普通定性指标模板基础上增加中心编号列
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
    """
    填充模板

    Args:
        semantic: 语义 JSON
        projects: 项目列表
    """
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
        for row_idx, row in enumerate(row_template):
            label_vals = row.get("label_values", [])
            metric = label_vals[1] if len(label_vals) > 1 else ""
            data_vals = row.get("data_values", [])
            placeholder = data_vals[0] if data_vals else ""
            applies_to = row.get("applies_to", [])

            # 跳过占位行（……）
            if metric in ("……", "...", "…") or row.get("placeholder"):
                continue

            # 分类行：只在第一个分类行展开所有 categories
            if categories and cat_pattern.match(metric):
                if not cat_expanded:
                    for cat_idx, cat_name in enumerate(categories):
                        rows.append({
                            "metric": f"{cat_name} n(%)",
                            "placeholder": placeholder,
                            "applies_to": applies_to,
                            "indicator": display if first else "",
                        })
                        first = False
                    cat_expanded = True
                continue

            rows.append({
                "metric": metric,
                "placeholder": placeholder,
                "applies_to": applies_to,
                "indicator": display if first else "",
            })
            first = False

        indicators.append({"name": name, "unit": "", "display": display, "rows": rows})

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_QUALSITE_N_N.json")
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
