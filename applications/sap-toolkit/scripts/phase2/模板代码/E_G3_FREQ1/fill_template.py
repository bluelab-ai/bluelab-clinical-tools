#!/usr/bin/env python3
"""
E_G3_FREQ1 填充脚本（不良事件频率表-多组）
根据 categories 填充事件分类
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

    rows = []

    # 遍历每个 project
    for proj in projects:
        name = proj.get("name", "")
        categories = proj.get("categories", [])

        # 项目名称行（不缩进）
        if name:
            rows.append({
                "label_values": [name, ""],
                "data_values": ["x", "x", "x"],
                "applies_to": ["组别1 例次", "组别2 例次", "合计 例次"],
                "indent": 0
            })

        for cat in categories:
            # 每个分类有3行：例次、人数(%)、P值
            rows.append({
                "label_values": [cat, "例次"],
                "data_values": ["x", "x", "x"],
                "applies_to": ["组别1 例次", "组别2 例次", "合计 例次"],
                "indent": 1
            })
            rows.append({
                "label_values": ["", "人数(%)"],
                "data_values": ["n2(x.x %)", "n2(x.x %)", "n2(x.x %)"],
                "applies_to": ["组别1 人数(%)", "组别2 人数(%)", "合计 人数(%)"],
                "indent": 1
            })
            rows.append({
                "label_values": ["", "P值"],
                "data_values": ["x.xxx"],
                "applies_to": ["P值"],
                "indent": 1
            })

    result["rows"] = rows
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "E_G3_FREQ1.json")
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
