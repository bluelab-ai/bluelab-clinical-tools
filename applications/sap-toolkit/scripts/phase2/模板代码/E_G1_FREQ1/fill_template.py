#!/usr/bin/env python3
"""
E_G1_FREQ1 填充脚本（频率分布表-单组）
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
    sections = result.get("sections", [])

    rows = []

    # 遍历每个 project
    for proj in projects:
        name = proj.get("name", "")
        categories = proj.get("categories", [])

        # 项目名称行（不缩进）
        if name:
            rows.append({
                "label_values": [name],
                "data_values": ["x", "n2(x.x %)"],
                "applies_to": ["例次", "人数(%)"],
                "indent": 0
            })

        # 分类行（带缩进）
        for cat in categories:
            rows.append({
                "label_values": [cat],
                "data_values": ["x", "n2(x.x %)"],
                "applies_to": ["例次", "人数(%)"],
                "indent": 1
            })

    result["rows"] = rows
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "E_G1_FREQ1.json")
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
