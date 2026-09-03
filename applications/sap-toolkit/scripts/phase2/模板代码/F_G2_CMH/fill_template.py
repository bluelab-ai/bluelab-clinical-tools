#!/usr/bin/env python3
"""
F_G2_CMH 填充脚本（分类指标比较表-两组-CMH检验）
定性指标，带置信区间和率差
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

    indicators = []
    for proj in projects:
        name = proj["name"]
        categories = proj.get("categories", [])
        display = name

        rows = []

        # 遍历每个分类
        for cat_idx, cat in enumerate(categories):
            # 从sections获取行结构
            for row_idx, row in enumerate(sections[0]["rows"]):
                label_vals = row.get("label_values", [])
                data_vals = row.get("data_values", [])
                applies_to = row.get("applies_to", [])

                # 替换占位符
                metric = label_vals[1] if len(label_vals) > 1 else ""
                metric = metric.replace("XX分类", cat)

                # 第一行显示指标名
                indicator_name = name if row_idx == 0 else ""

                rows.append({
                    "indicator": indicator_name,
                    "metric": metric,
                    "placeholder": data_vals[0] if data_vals else "",
                    "applies_to": applies_to
                })

        indicators.append({"name": name, "display": display, "rows": rows})

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_CMH.json")
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
