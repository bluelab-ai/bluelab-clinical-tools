#!/usr/bin/env python3
"""
F_G2_QUANCOM_Y_N 填充脚本（两组定量-有缺失）
从 填充数据.json 读取指标，按语义模板生成填充后的表格 JSON
"""

import json
import os
import sys
import copy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fill_template(semantic, projects):
    """
    将指标数据填入 F_G2_QUANCOM_Y_N 语义模板

    参数:
        semantic: F_G2_QUANCOM_Y_N.json 语义模板
        projects: [{"name": "收缩压", "unit": "mmHg"}, ...]

    返回:
        填充后的 dict
    """
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
            row = section["rows"][0]
            metric = section.get("metric", "")
            placeholder = section.get("placeholder", "")

            rows.append({
                "metric": metric,
                "placeholder": placeholder,
                "applies_to": row.get("applies_to", []),
                "indicator": display if first else ""
            })
            first = False

        indicators.append({
            "name": name,
            "unit": unit,
            "display": display,
            "rows": rows
        })

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)

    return result


def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_QUANCOM_Y_N.json")
    output_path = os.path.join(SCRIPT_DIR, "填充结果.json")

    if not os.path.exists(data_path):
        print(f"错误: 找不到 {data_path}")
        sys.exit(1)
    if not os.path.exists(semantic_path):
        print(f"错误: 找不到 {semantic_path}")
        sys.exit(1)

    data = load_json(data_path)
    semantic = load_json(semantic_path)

    result = fill_template(semantic, data["projects"])
    save_json(output_path, result)

    names = [i["display"] for i in result["indicators"]]
    print(f"✓ 填充完成: {', '.join(names)} → {output_path}")


if __name__ == "__main__":
    main()
