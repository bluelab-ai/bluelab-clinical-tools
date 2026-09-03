#!/usr/bin/env python3
"""
F_G2_QUALSUB_N_N 填充脚本（定性指标亚组-两组-无缺失）
按亚组分组，每个亚组内为多个指标重复6行统计结构
"""

import json, os, sys, copy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fill_template(semantic, projects, subgroups):
    result = copy.deepcopy(semantic)
    # rows 嵌套在 sections[0]["sections"][0]["rows"] 中
    row_template = result["sections"][0]["sections"][0]["rows"]

    indicators = []
    for proj in projects:
        name = proj["name"]
        categories = proj.get("categories", [])

        # 构建行模板：例数、各分类、统计方法、检验统计量、P值
        rows = []
        for j, row in enumerate(row_template):
            label_vals = row.get("label_values", [])
            metric = label_vals[2] if len(label_vals) > 2 else ""
            data_vals = row.get("data_values", [])
            placeholder = data_vals[0] if data_vals else ""
            applies_to = row.get("applies_to", [])

            # 对于分类行，动态替换分类名称
            if metric.startswith("分类") and categories:
                # 根据分类索引替换
                cat_idx = int(metric[2]) - 1 if metric[2].isdigit() else 0
                if cat_idx < len(categories):
                    metric = f"{categories[cat_idx]} n(%)"

            rows.append({
                "metric": metric,
                "placeholder": placeholder,
                "applies_to": applies_to
            })

        subgroup_data = []
        for subgroup in subgroups:
            subgroup_data.append({"name": subgroup, "rows": rows})

        indicators.append({
            "name": name,
            "display": name,
            "categories": categories,
            "subgroups": subgroup_data
        })

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_QUALSUB_N_N.json")
    output_path = os.path.join(SCRIPT_DIR, "填充结果.json")

    for p in [data_path, semantic_path]:
        if not os.path.exists(p):
            print(f"错误: 找不到 {p}"); sys.exit(1)

    data = load_json(data_path)
    semantic = load_json(semantic_path)
    result = fill_template(semantic, data["projects"], data["subgroups"])
    save_json(output_path, result)
    print(f"✓ 填充完成: {', '.join(i['display'] for i in result['indicators'])} → {output_path}")

if __name__ == "__main__":
    main()