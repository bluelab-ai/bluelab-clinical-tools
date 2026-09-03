#!/usr/bin/env python3
"""
F_G2_ANCOVA_03 填充脚本
组间修正均数描述及比较 - 两组比较
从数据文件读取指标，按语义模板生成填充后的表格 JSON
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
    将指标数据填入 F_G2_ANCOVA_03 语义模板

    参数:
        semantic: F_G2_ANCOVA_03.json 语义模板
        projects: [{"name": "收缩压", "unit": "mmHg"}, ...]

    返回:
        填充后的 dict，可直接用于 gen_docx
    """
    result = copy.deepcopy(semantic)
    sections = result.get("sections", [])

    indicators = []
    for proj in projects:
        name = proj["name"]
        unit = proj.get("unit", "")
        display = f"{name} ({unit})" if unit else name

        # 处理所有 section 的行
        rows = []
        for section in sections:
            section_rows = section.get("rows", [])
            for row in section_rows:
                new_row = copy.deepcopy(row)
                # 替换 label_values 中的占位符
                label_values = new_row.get("label_values", [])
                for i, val in enumerate(label_values):
                    if "指标XXX" in val:
                        label_values[i] = val.replace("指标XXX (单位)", display)
                new_row["label_values"] = label_values
                rows.append(new_row)

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
    # 默认路径
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_ANCOVA_03.json")
    output_path = os.path.join(SCRIPT_DIR, "填充结果.json")

    if not os.path.exists(data_path):
        print(f"错误: 找不到 {data_path}")
        sys.exit(1)
    if not os.path.exists(semantic_path):
        print(f"错误: 找不到 {semantic_path}")
        sys.exit(1)

    data = load_json(data_path)
    semantic = load_json(semantic_path)

    result = fill_template(semantic, data.get("projects", []))
    save_json(output_path, result)

    names = [i["display"] for i in result["indicators"]]
    print(f"✓ 填充完成: {', '.join(names)} → {output_path}")


if __name__ == "__main__":
    main()
