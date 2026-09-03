#!/usr/bin/env python3
"""
F_G2_QUANSITE_N_N 填充脚本（定量指标-两组-无缺失-中心）
在普通定量指标模板基础上增加中心编号列
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
    将指标数据填入 F_G2_QUANSITE_N_N 语义模板

    参数:
        semantic: F_G2_QUANSITE_N_N.json 语义模板
        projects: [{"name": "收缩压", "unit": "mmHg"}, ...]

    返回:
        填充后的 dict，可直接用于 gen_docx
    """
    result = copy.deepcopy(semantic)
    row_template = result["sections"][0]["rows"]
    slot = result["repeat_pattern"]["variable_slots"][0]  # "指标XXX (单位)"
    has_unit = "单位" in slot

    indicators = []
    for proj in projects:
        name = proj["name"]
        unit = proj.get("unit", "")
        display = f"{name} ({unit})" if has_unit and unit else name

        # 复制行模板，跳过占位行，首行填指标名，其余留空
        rows = []
        for j, row in enumerate(row_template):
            if row.get("metric", "") in ("……", "...", "…"):
                continue
            # 从 label_values 提取 metric（行标签）
            label_vals = row.get("label_values", [])
            metric = label_vals[1] if len(label_vals) > 1 else ""
            # 从 data_values 提取 placeholder（数据格式）
            data_vals = row.get("data_values", [])
            placeholder = data_vals[0] if data_vals else ""

            new_row = {
                "metric": metric,
                "placeholder": placeholder,
                "applies_to": row.get("applies_to", []),
                "indicator": display if j == 0 else "",
            }
            rows.append(new_row)

        indicators.append({
            "name": name,
            "unit": unit,
            "display": display,
            "rows": rows,
        })

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)

    return result


def main():
    # 默认路径
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_QUANSITE_N_N.json")
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
