#!/usr/bin/env python3
"""
D_G3_EN 填充脚本（受试者入组与完成情况表-多组）
根据 categories 填充提前中止退出原因
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

    rows = []

    # 遍历每个 section
    for section in sections:
        section_type = section.get("type", "")
        section_label = section.get("label", "")
        section_category = section.get("category", "")

        if section_type == "category_header":
            # 添加分类标题行（第一列填分类名，其余列空）
            rows.append({
                "label_values": [section_label, "", "", "", "", ""],
                "data_values": [],
                "applies_to": [],
                "is_category_header": True
            })
        elif section_type == "data_section":
            if section_category == "提前中止退出":
                # 用 categories 替换原因行
                for proj in projects:
                    categories = proj.get("categories", [])
                    for cat in categories:
                        rows.append({
                            "label_values": ["", cat],
                            "data_values": ["n2(x.x %)", "n2(x.x %)", "n2(x.x %)", "n2(x.x %)"],
                            "applies_to": ["组别1 (N=n1)", "组别2 (N=n1)", "…… (N=n1)", "合计 (N=n1)"]
                        })
            else:
                # 其他 section 直接复制
                for row in section.get("rows", []):
                    rows.append({
                        "label_values": row["label_values"],
                        "data_values": row.get("data_values", []),
                        "applies_to": row.get("applies_to", [])
                    })

    result["rows"] = rows
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "D_G3_EN.json")
    output_path = os.path.join(SCRIPT_DIR, "填充结果.json")

    for p in [data_path, semantic_path]:
        if not os.path.exists(p):
            print(f"错误: 找不到 {p}"); sys.exit(1)

    data = load_json(data_path)
    semantic = load_json(semantic_path)
    result = fill_template(semantic, data["projects"])
    save_json(output_path, result)
    print(f"✓ 填充完成 → {output_path}")

if __name__ == "__main__":
    main()
