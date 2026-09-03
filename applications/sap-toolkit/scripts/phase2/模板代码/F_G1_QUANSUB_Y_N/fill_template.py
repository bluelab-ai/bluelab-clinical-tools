#!/usr/bin/env python3
"""
F_G1_QUANSUB_Y_N 填充脚本（定量指标亚组-单组-有缺失）
按亚组分组，每个亚组内为多个指标重复6行统计结构（含缺失）
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
    row_template = result["sections"][0]["rows"]
    slot = result["repeat_pattern"]["variable_slots"][1]  # "指标XXX (单位)"
    has_unit = "单位" in slot

    indicators = []
    for proj in projects:
        name = proj["name"]
        unit = proj.get("unit", "")
        display = f"{name} ({unit})" if has_unit and unit else name

        subgroup_data = []
        for subgroup in subgroups:
            rows = []
            for j, row in enumerate(row_template):
                if row.get("metric", "") in ("……", "...", "…"):
                    continue
                label_vals = row.get("label_values", [])
                metric = label_vals[2] if len(label_vals) > 2 else ""
                data_vals = row.get("data_values", [])
                placeholder = data_vals[0] if data_vals else ""
                rows.append({
                    "metric": metric,
                    "placeholder": placeholder,
                    "applies_to": row.get("applies_to", [])
                })
            subgroup_data.append({"name": subgroup, "rows": rows})

        indicators.append({
            "name": name,
            "unit": unit,
            "display": display,
            "subgroups": subgroup_data
        })

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G1_QUANSUB_Y_N.json")
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