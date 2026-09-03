#!/usr/bin/env python3
"""
F_G2_CROSS 填充脚本（交叉汇总表-治疗前×治疗后）
定量指标，按 groups 展开组别行（试验组、对照组、合计）
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

    indicators = []
    for proj in projects:
        name = proj["name"]
        groups = proj.get("groups", ["试验组", "对照组", "合计"])
        display = name

        rows = []
        first = True

        # 表头行1：治疗后（合并）
        rows.append({
            "label_values": ["", "", "", "治疗后", "治疗后", "治疗后", "治疗后", "治疗后", ""],
            "data_values": [],
            "applies_to": [],
            "merge": [{"start": 3, "end": 8, "label": "治疗后"}],
            "indicator": ""
        })

        # 表头行2：项目、组别、治疗前、正常、异常无临床意义、异常有临床意义、未查、缺失、合一
        # 注意：组别列（第2列）与表头行1合并，所以这里留空
        rows.append({
            "label_values": ["项目", "", "治疗前", "正常", "异常无临床意义", "异常有临床意义", "未查", "缺失", "合计"],
            "data_values": [],
            "applies_to": [],
            "merge": [],
            "indicator": ""
        })

        # 指标名行（合并所有列）
        rows.append({
            "label_values": [display] * 9,
            "data_values": [],
            "applies_to": [],
            "indicator": display
        })

        # 按 groups 展开组别行
        group_rows = sections[1].get("repeat_pattern", {}).get("group_rows", [])
        for group in groups:
            group_label = f"{group}(N=n1)"
            for i, row in enumerate(group_rows):
                label_vals = row.get("label_values", [])
                # 替换 {group_label}
                metric = label_vals[2] if len(label_vals) > 2 else ""  # 治疗前分类
                data_vals = row.get("data_values", [])
                placeholder = data_vals[0] if data_vals else ""
                applies_to = row.get("applies_to", [])
                rows.append({
                    "metric": metric,
                    "placeholder": placeholder,
                    "applies_to": applies_to,
                    "group": group_label if i == 0 else ""  # 组别只在第一行显示
                })

        indicators.append({"name": name, "unit": "", "display": display, "rows": rows})

    result["indicators"] = indicators
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result

def main():
    data_path = os.path.join(SCRIPT_DIR, "填充数据.json")
    semantic_path = os.path.join(SCRIPT_DIR, "F_G2_CROSS.json")
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
