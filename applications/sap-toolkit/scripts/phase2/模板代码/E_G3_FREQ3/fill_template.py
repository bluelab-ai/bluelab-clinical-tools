#!/usr/bin/env python3
"""
E_G3_FREQ3 填充脚本（不良事件发生情况表-多组-SOC/PT）
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

    # 遍历每个 project 的 categories
    for proj in projects:
        categories = proj.get("categories", [])
        for cat in categories:
            # 分类行（带缩进）
            rows.append({
                "label_values": [cat],
                "data_values": ["x", "n2(x.x %)", "x", "n2(x.x %)", "x", "n2(x.x %)", "x", "n2(x.x %)", "x.xxx"],
                "applies_to": ["组别1 (N=n1)_例次", "组别1 (N=n1)_人数%", "组别2 (N=n1)_例次", "组别2 (N=n1)_人数%", "组别3 (N=n1)_例次", "组别3 (N=n1)_人数%", "合计 (N=n1)_例次", "合计 (N=n1)_人数%", "P值"],
                "indent": 1
            })

    result["rows"] = rows
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "E_G3_FREQ3.json")
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
