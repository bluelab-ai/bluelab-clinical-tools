#!/usr/bin/env python3
"""
F_G1_QUALCOM_Y_N_F_G1_QUANCOM_Y_N 填充脚本
混合定性+定量指标的单组比较表（有缺失）

判断逻辑：
- 有 categories 字段 → 定性指标，按 F_G1_QUALCOM_Y_N 方式填充（每个分类 n(%) + 95%CI）
- 有 unit 字段且无 categories → 定量指标，按 F_G1_QUANCOM_Y_N 方式填充（含均值/中位数95%CI）
"""

import json, os, sys, copy, re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_qualitative(proj):
    """判断是否为定性指标（有categories字段）"""
    return "categories" in proj and len(proj.get("categories", [])) > 0


def is_quantitative(proj):
    """判断是否为定量指标（有unit字段且无categories）"""
    return "unit" in proj and not is_qualitative(proj)


def fill_qualitative(qual_section, categories, display):
    """填充定性指标（每个分类 n(%) + 95%CI）"""
    rows = []
    first = True

    for row_idx, row in enumerate(qual_section.get("rows", [])):
        label_vals = row.get("label_values", [])
        metric = label_vals[1] if len(label_vals) > 1 else ""
        data_vals = row.get("data_values", [])
        placeholder = data_vals[0] if data_vals else ""
        applies_to = row.get("applies_to", [])

        if row_idx == 0:
            # 第一行：例数(缺失)
            rows.append({
                "metric": metric,
                "placeholder": placeholder,
                "applies_to": applies_to,
                "indicator": display if first else ""
            })
            first = False
        elif "分类" in metric and "n(%)" in metric:
            # 分类行：展开所有 categories，每个分类两行（n(%)+CI）
            for cat_name in categories:
                rows.append({
                    "metric": f"{cat_name} n(%)",
                    "placeholder": placeholder,
                    "applies_to": applies_to,
                    "indicator": display if first else ""
                })
                first = False
                rows.append({
                    "metric": f"{cat_name}的双侧95% CI(%)",
                    "placeholder": "x.x %, x.x %",
                    "applies_to": applies_to,
                    "indicator": ""
                })
            break  # 分类展开后跳出

    return rows


def fill_quantitative(quant_section, display):
    """填充定量指标（含均值/中位数95%CI）"""
    rows = []
    first = True

    for row in quant_section.get("rows", []):
        label_vals = row.get("label_values", [])
        metric = label_vals[1] if len(label_vals) > 1 else ""
        data_vals = row.get("data_values", [])
        placeholder = data_vals[0] if data_vals else ""
        applies_to = row.get("applies_to", [])

        rows.append({
            "metric": metric,
            "placeholder": placeholder,
            "applies_to": applies_to,
            "indicator": display if first else ""
        })
        first = False

    return rows


def fill_template(semantic, projects):
    """
    混合填充定性+定量指标（单组有缺失版本）

    参数:
        semantic: 语义模板
        projects: [{"name": "性别", "categories": ["男", "女"]}, {"name": "收缩压", "unit": "mmHg"}, ...]

    返回:
        填充后的 dict
    """
    result = copy.deepcopy(semantic)

    qual_section = None
    quant_section = None

    for section in result.get("sections", []):
        if section.get("type") == "qualitative_group":
            qual_section = section
        elif section.get("type") == "quantitative_group":
            quant_section = section

    if not qual_section and not quant_section:
        sections = result.get("sections", [])
        if sections:
            qual_section = sections[0]
            quant_section = sections[0]

    indicators = []

    for proj in projects:
        name = proj["name"]

        if is_qualitative(proj):
            display = name
            unit = ""
            categories = proj.get("categories", [])
            rows = fill_qualitative(qual_section, categories, display)
        elif is_quantitative(proj):
            unit = proj.get("unit", "")
            display = f"{name} ({unit})" if unit else name
            rows = fill_quantitative(quant_section, display)
        else:
            display = name
            unit = ""
            categories = proj.get("categories", [])
            rows = fill_qualitative(qual_section, categories, display)

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
    semantic_path = os.path.join(SCRIPT_DIR, "F_G1_QUALCOM_Y_N_F_G1_QUANCOM_Y_N.json")
    output_path = os.path.join(SCRIPT_DIR, "填充结果.json")

    for p in [data_path, semantic_path]:
        if not os.path.exists(p):
            print(f"错误: 找不到 {p}")
            sys.exit(1)

    data = load_json(data_path)
    semantic = load_json(semantic_path)
    result = fill_template(semantic, data["projects"])
    save_json(output_path, result)

    qual_count = sum(1 for p in data["projects"] if is_qualitative(p))
    quant_count = sum(1 for p in data["projects"] if is_quantitative(p))
    print(f"✓ 填充完成: {len(result['indicators'])} 个指标 (定性: {qual_count}, 定量: {quant_count}) → {output_path}")


if __name__ == "__main__":
    main()
