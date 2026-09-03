#!/usr/bin/env python3
"""F_G1_MEAN_OPC 填充脚本（F_G1_MEAN_OPC 填充脚本）"""

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
    slot = result["repeat_pattern"]["variable_slots"][0]
    has_unit = "单位" in slot

    indicators = []
    for proj in projects:
        name = proj["name"]
        unit = proj.get("unit", "")
        display = f"{name} ({unit})" if has_unit and unit else name

        rows = []
        first = True
        for section in sections:
            for row in section.get("rows", []):
                label_vals = row.get("label_values", [])
                metric = label_vals[1] if len(label_vals) > 1 else ""
                data_vals = row.get("data_values", [])
                placeholder = data_vals[0] if data_vals else ""
                rows.append({
                    "metric": metric,
                    "placeholder": placeholder,
                    "applies_to": row.get("applies_to", []),
                    "indicator": display if first else ""
                })
                first = False

        indicators.append({"name": name, "unit": unit, "display": display, "rows": rows})

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G1_MEAN_OPC.json")
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
