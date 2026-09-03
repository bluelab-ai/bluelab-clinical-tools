#!/usr/bin/env python3
"""
F_G3_QUANVIS 填充脚本（定量指标访视比较表-两组）
visits 第一个固定为基线，后续依次填入 XX访视
"""

import json, os, sys, copy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fill_template(semantic, projects, visits):
    result = copy.deepcopy(semantic)
    row_template = result["sections"][0]["rows"]

    # 找到基线和访视的分界点
    baseline_end = 0
    for i, row in enumerate(row_template):
        label_vals = row.get("label_values", [])
        if label_vals and "XX访视" in label_vals:
            baseline_end = i
            break

    baseline_rows = row_template[:baseline_end]  # 包含基线标题行
    visit_template = row_template[baseline_end:]  # 从XX访视开始

    indicators = []
    for proj in projects:
        name = proj["name"]
        unit = proj.get("unit", "")
        display = f"{name} ({unit})" if unit else name

        rows = []

        # 基线部分：第一行合并指标名和"基线"，统计行缩进4格
        for i, row in enumerate(baseline_rows):
            label_vals = row.get("label_values", [])
            metric = label_vals[1] if len(label_vals) > 1 else ""
            # 统计行加缩进
            if i > 0:
                metric = "    " + metric
            data_vals = row.get("data_values", [])
            placeholder = data_vals[0] if data_vals else ""
            rows.append({
                "metric": metric,
                "placeholder": placeholder,
                "applies_to": row.get("applies_to", []),
                "indicator": display if i == 0 else ""
            })

        # 访视部分：从 visits[1] 开始（visits[0] 是基线）
        for visit in visits[1:]:
            for row in visit_template:
                label_vals = row.get("label_values", [])
                metric = label_vals[1] if len(label_vals) > 1 else ""
                metric = metric.replace("XX访视", visit)
                # 访视标题不缩进，统计行缩进4格
                visit_headers = [visit, f"{visit}较基线变化值", f"{visit}较基线变化值与0比较", f"{visit}较基线变化率(%)", f"{visit}较基线变化率与0比较"]
                if metric and metric not in visit_headers:
                    metric = "    " + metric
                data_vals = row.get("data_values", [])
                placeholder = data_vals[0] if data_vals else ""
                rows.append({
                    "metric": metric,
                    "placeholder": placeholder,
                    "applies_to": row.get("applies_to", []),
                    "indicator": ""
                })

        indicators.append({"name": name, "unit": unit, "display": display, "rows": rows})

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G3_QUANVIS.json")
    output_path = os.path.join(SCRIPT_DIR, "填充结果.json")

    for p in [data_path, semantic_path]:
        if not os.path.exists(p):
            print(f"错误: 找不到 {p}"); sys.exit(1)

    data = load_json(data_path)
    semantic = load_json(semantic_path)
    result = fill_template(semantic, data["projects"], data["visits"])
    save_json(output_path, result)
    print(f"✓ 填充完成: {', '.join(i['display'] for i in result['indicators'])} → {output_path}")

if __name__ == "__main__":
    main()
