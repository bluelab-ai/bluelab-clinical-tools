#!/usr/bin/env python3
"""
F_G1_QUALCOM_N_N 填充脚本（定性指标比较表-单组-无缺失）
定性指标，按 categories 展开分类行
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
        first = True  # 标记是否是第一行（例数行）

        # 从sections获取行结构
        for row_idx, row in enumerate(sections[0]["rows"]):
            label_vals = row.get("label_values", [])
            data_vals = row.get("data_values", [])
            applies_to = row.get("applies_to", [])

            # 分类行（第2行开始）需要根据 categories 展开
            if row_idx >= 1 and row_idx < 1 + len(categories):
                # 替换分类名
                cat = categories[row_idx - 1]
                metric = f"{cat} n(%)"
                rows.append({
                    "indicator": display if first else "",
                    "metric": metric,
                    "placeholder": data_vals[0] if data_vals else "",
                    "applies_to": applies_to
                })
                first = False
            elif row_idx == 0:
                # 第一行：例数(缺失)
                rows.append({
                    "indicator": display if first else "",
                    "metric": label_vals[1] if len(label_vals) > 1 else "",
                    "placeholder": data_vals[0] if data_vals else "",
                    "applies_to": applies_to
                })
                first = False

        indicators.append({"name": name, "display": display, "rows": rows})

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G1_QUALCOM_N_N.json")
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
