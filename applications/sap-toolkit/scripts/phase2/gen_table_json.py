#!/usr/bin/env python3
"""
从生命体征和实验室检查 JSON 生成表格 JSON
==========================================
读取 04_项目详情 中的生命体征.json 和实验室检查.json，
为缺少的表格生成对应的 JSON 文件到 05_表格信息/。

用法:
    python -m scripts.phase2.gen_table_json <输出目录> [--details-dir <04_项目详情目录>]
"""

import os
import sys
import json


# 评价分类（前后交叉表用）
EVAL_CATEGORIES = ["正常", "异常无临床意义", "异常有临床意义", "未查"]


def load_visits_from_phase1(content_dir):
    """从阶段1的JSON中加载生命体征、心电图检查、体格检查的visits信息

    Args:
        content_dir: 02_内容提取 目录路径

    Returns:
        dict: {项目名称: visits数组} 的映射
    """
    visits_map = {}

    # 查找试验流程_第一个访视项目.json
    visit_file = None
    for fname in os.listdir(content_dir):
        if "第一个访视项目" in fname and fname.endswith(".json"):
            visit_file = os.path.join(content_dir, fname)
            break

    if not visit_file or not os.path.exists(visit_file):
        return visits_map

    with open(visit_file, "r", encoding="utf-8") as f:
        visit_data = json.load(f)

    # 从 vital_signs、ecg、physical_examination 中提取 visits
    for key in ["vital_signs", "ecg", "physical_examination"]:
        items = visit_data.get(key, [])
        for item in items:
            name = item.get("name", "")
            visits = item.get("visits", [])
            if name and visits:
                visits_map[name] = visits

    return visits_map


def gen_vital_sign_tables(vital_data, output_dir, visits_map=None):
    """从生命体征.json 生成各生命体征子表

    当 only_in_first_visit=false 时（多个访视都检查），在 projects 中添加一个基线项目
    如果有 visits 信息，也会添加到输出JSON中
    """
    items = vital_data.get("analysis_items", [])
    created = []

    for item in items:
        name = item["name"]
        unit = item.get("unit", "")
        only_in_first_visit = item.get("only_in_first_visit", False)
        table_name = f"生命体征-{name}（SS）"
        # 处理文件名中的特殊字符（如 /）
        safe_table_name = table_name.replace("/", "_")
        table_file = os.path.join(output_dir, f"{safe_table_name}.json")

        if os.path.exists(table_file):
            continue

        # 构建 projects 列表（统一不添加基线项目）
        projects = [
            {
                "name": name,
                "unit": unit
            }
        ]

        table_json = {
            "table_name": table_name,
            "projects": projects
        }

        # 如果有 visits 信息，添加到输出JSON中
        if visits_map:
            # 优先使用具体项目名称的visits
            if name in visits_map:
                table_json["visits"] = visits_map[name]
            # 其次检查项目名称是否包含在visits_map的key中（如"收缩压"包含在"血压"中）
            elif any(name in key or key in name for key in visits_map.keys()):
                for key, visits in visits_map.items():
                    if name in key or key in name:
                        table_json["visits"] = visits
                        break
            # 特殊处理：血压相关的项目（收缩压、舒张压）使用"血压"的visits
            elif name.endswith("压") and "血压" in visits_map:
                table_json["visits"] = visits_map["血压"]
            # 最后使用"生命体征"的visits
            elif "生命体征" in visits_map:
                table_json["visits"] = visits_map["生命体征"]

        with open(table_file, "w", encoding="utf-8") as f:
            json.dump(table_json, f, ensure_ascii=False, indent=2)
        created.append(table_name)

    return created


def gen_cross_tables(lab_data, output_dir, exclude_categories=None):
    """从实验室检查.json 生成前后交叉表

    Args:
        exclude_categories: 需要排除的分类列表（如基线指标）
    """
    items = lab_data.get("analysis_items", [])
    category_map = {
        "血常规": "血常规",
        "肝功能": "肝功能",
        "肾功能": "肾功能",
        "凝血功能": "凝血功能",
    }
    # 默认排除基线指标
    if exclude_categories is None:
        exclude_categories = ["传染病筛查", "其他"]
    created = []

    for item in items:
        name = item["name"]
        category = item.get("category", "")
        only_in_first_visit = item.get("only_in_first_visit", False)

        # 跳过基线指标
        if category in exclude_categories:
            continue

        # 只处理多个访视都检查的项目（与生命体征一致）
        if only_in_first_visit:
            continue

        group = category_map.get(category, category)

        table_name = f"{group}-{name}前后交叉表（SS）"
        safe_name = table_name.replace("/", "_")
        table_file = os.path.join(output_dir, f"{safe_name}.json")

        if os.path.exists(table_file):
            continue

        table_json = {
            "table_name": table_name,
            "projects": [
                {
                    "name": name,
                    "categories": EVAL_CATEGORIES
                }
            ]
        }

        with open(table_file, "w", encoding="utf-8") as f:
            json.dump(table_json, f, ensure_ascii=False, indent=2)
        created.append(table_name)

    return created


def gen_ecg_table(details_dir, output_dir, visits_map=None):
    """从心电图.json 生成心电图检查（SS）.json，添加visits信息

    Args:
        details_dir: 04_项目详情 目录路径
        output_dir: 05_表格信息 目录路径
        visits_map: 访视信息映射

    Returns:
        创建的表格名称，如果没有创建则返回None
    """
    table_name = "心电图检查（SS）"
    safe_name = table_name.replace("/", "_")
    table_file = os.path.join(output_dir, f"{safe_name}.json")

    # 如果文件不存在，返回None
    if not os.path.exists(table_file):
        return None

    # 读取现有文件
    with open(table_file, "r", encoding="utf-8") as f:
        table_json = json.load(f)

    # 如果已经有visits，不需要添加
    if "visits" in table_json:
        return table_name

    # 添加visits信息
    if visits_map:
        # 优先使用"心电图"的visits
        if "心电图" in visits_map:
            table_json["visits"] = visits_map["心电图"]
        # 其次检查ecg中是否有其他名称
        elif "ecg" in visits_map:
            table_json["visits"] = visits_map["ecg"]
        # 最后使用任何包含"心电图"的key
        else:
            for key, visits in visits_map.items():
                if "心电图" in key or "ecg" in key.lower():
                    table_json["visits"] = visits
                    break

    with open(table_file, "w", encoding="utf-8") as f:
        json.dump(table_json, f, ensure_ascii=False, indent=2)

    return table_name


def gen_urea_table(lab_data, output_dir):
    """生成尿素/尿素氮(UREA/BUN)（SS）.json（多模板：定性+定量）"""
    table_name = "尿素/尿素氮(UREA/BUN)（SS）"
    safe_name = table_name.replace("/", "_")
    table_file = os.path.join(output_dir, f"{safe_name}.json")

    if os.path.exists(table_file):
        return None

    # 从实验室检查中找 UREA 和 BUN
    urea_unit = ""
    bun_unit = ""
    for item in lab_data.get("analysis_items", []):
        if "UREA" in item["name"]:
            urea_unit = item.get("unit", "")
        if "BUN" in item["name"]:
            bun_unit = item.get("unit", "")

    table_json = {
        "table_name": table_name,
        "projects": [
            {
                "name": "尿素（UREA）",
                "categories": EVAL_CATEGORIES
            },
            {
                "name": "尿素氮（BUN）",
                "categories": EVAL_CATEGORIES
            },
            {
                "name": "尿素（UREA）检测结果",
                "unit": urea_unit or "mmol/L"
            },
            {
                "name": "尿素氮（BUN）检测结果",
                "unit": bun_unit or "mmol/L"
            }
        ]
    }

    with open(table_file, "w", encoding="utf-8") as f:
        json.dump(table_json, f, ensure_ascii=False, indent=2)

    return table_name


def main(details_dir, output_dir, content_dir=None):
    os.makedirs(output_dir, exist_ok=True)

    # 读取生命体征
    vital_path = os.path.join(details_dir, "生命体征.json")
    if os.path.exists(vital_path):
        with open(vital_path, "r", encoding="utf-8") as f:
            vital_data = json.load(f)
    else:
        # 尝试从 _summary.json 读取
        summary_path = os.path.join(details_dir, "_summary.json")
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            vital_data = summary.get("safety_items", {}).get("results", {}).get("生命体征", {})
        else:
            print("⚠️ 未找到生命体征数据", file=sys.stderr)
            vital_data = {}

    # 读取实验室检查
    lab_path = os.path.join(details_dir, "实验室检查.json")
    if os.path.exists(lab_path):
        with open(lab_path, "r", encoding="utf-8") as f:
            lab_data = json.load(f)
    else:
        summary_path = os.path.join(details_dir, "_summary.json")
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            lab_data = summary.get("safety_items", {}).get("results", {}).get("实验室检查", {})
        else:
            print("⚠️ 未找到实验室检查数据", file=sys.stderr)
            lab_data = {}

    # 读取阶段1的visits信息（生命体征、心电图检查、体格检查）
    visits_map = {}
    if content_dir:
        visits_map = load_visits_from_phase1(content_dir)
        if visits_map:
            print(f"✅ 已加载访视信息: {list(visits_map.keys())}", file=sys.stderr)

    all_created = []

    # 1. 生命体征子表
    if vital_data:
        created = gen_vital_sign_tables(vital_data, output_dir, visits_map)
        all_created.extend(created)
        print(f"✅ 生命体征子表: {len(created)} 个", file=sys.stderr)

    # 2. 前后交叉表
    if lab_data:
        created = gen_cross_tables(lab_data, output_dir)
        all_created.extend(created)
        print(f"✅ 前后交叉表: {len(created)} 个", file=sys.stderr)

    # 3. 尿素/尿素氮
    if lab_data:
        result = gen_urea_table(lab_data, output_dir)
        if result:
            all_created.append(result)
            print(f"✅ 尿素/尿素氮表: 1 个", file=sys.stderr)

    # 4. 心电图检查（添加visits）
    result = gen_ecg_table(details_dir, output_dir, visits_map)
    if result:
        all_created.append(result)
        print(f"✅ 心电图检查表: 1 个", file=sys.stderr)

    # 5. 基线表 JSON（从子表合并生成）
    created = gen_baseline_tables(details_dir, output_dir, content_dir)
    all_created.extend(created)

    print(f"\n共生成 {len(all_created)} 个表格 JSON", file=sys.stderr)
    return all_created


def gen_baseline_tables(details_dir, output_dir, content_dir=None):
    """从安全性详情中聚合生成基线表格 JSON

    从 02_内容提取/试验流程_第一个访视项目.json 中读取 only_in_first_visit=true 的安全性项目，
    再从 04_项目详情/ 中读取对应的 analysis_items，按父类聚合生成基线 JSON。

    Args:
        details_dir: 04_项目详情 目录路径
        output_dir: 05_表格信息 目录路径
        content_dir: 02_内容提取 目录路径

    Returns:
        创建的表格名称列表
    """
    if not content_dir:
        print("⚠️ 未指定 02_内容提取 目录，跳过基线表生成", file=sys.stderr)
        return []

    # 1. 读取第一个访视项目，找出 only_in_first_visit=true 的安全性项目
    visit_file = None
    for fname in os.listdir(content_dir):
        if "第一个访视项目" in fname and fname.endswith(".json"):
            visit_file = os.path.join(content_dir, fname)
            break

    if not visit_file or not os.path.exists(visit_file):
        print("⚠️ 未找到访视项目文件，跳过基线表生成", file=sys.stderr)
        return []

    with open(visit_file, "r", encoding="utf-8") as f:
        visit_data = json.load(f)

    # 2. 收集需要迁移为基线的安全性项目
    #    key: 安全性类别名, value: 基线表名列表
    baseline_items = {}  # {"血生化": [...子项], "生命体征": [...子项]}

    # 实验室检查：按 parent 聚合
    # 访视项目中每个大类（如"血生化"）标记了 only_in_first_visit，
    # 该大类下所有子项都属于基线
    lab_items = visit_data.get("laboratory", [])
    lab_baseline_parents = set()  # 需要迁移的 parent 集合
    for item in lab_items:
        if item.get("only_in_first_visit", False):
            lab_baseline_parents.add(item.get("name", ""))

    if lab_baseline_parents:
        detail_path = os.path.join(details_dir, "实验室检查.json")
        if os.path.exists(detail_path):
            with open(detail_path, "r", encoding="utf-8") as f:
                lab_detail = json.load(f)
            for sub_item in lab_detail.get("analysis_items", []):
                parent = sub_item.get("parent", "其他")
                if parent in lab_baseline_parents:
                    if parent not in baseline_items:
                        baseline_items[parent] = []
                    baseline_items[parent].append(sub_item)

    # 生命体征、体格检查、心电图：直接聚合作为一张基线表
    safety_detail_map = {
        "vital_signs": ("生命体征", "生命体征"),
        "physical_examination": ("体格检查", "体格检查"),
        "ecg": ("心电图", "心电图"),
    }
    for visit_key, (detail_name, baseline_label) in safety_detail_map.items():
        items = visit_data.get(visit_key, [])
        should_migrate = any(item.get("only_in_first_visit", False) for item in items)
        if should_migrate:
            detail_path = os.path.join(details_dir, f"{detail_name}.json")
            if os.path.exists(detail_path):
                with open(detail_path, "r", encoding="utf-8") as f:
                    detail = json.load(f)
                # 整个大类迁移，收集所有子项
                sub_items = detail.get("analysis_items", [])
                if sub_items:
                    if baseline_label not in baseline_items:
                        baseline_items[baseline_label] = []
                    baseline_items[baseline_label].extend(sub_items)

    if not baseline_items:
        print("⚠️ 没有需要迁移为基线的安全性项目", file=sys.stderr)
        return []

    # 3. 为每个聚合的父类生成基线 JSON（覆盖 CRF 提取的版本）
    created = []
    for parent_name, sub_items in baseline_items.items():
        table_name = f"基线信息-{parent_name}（FAS）"
        safe_name = table_name.replace("/", "_")
        table_file = os.path.join(output_dir, f"{safe_name}.json")

        # 构建 projects：每个子项作为一个 project
        projects = []
        for sub_item in sub_items:
            proj = {"name": sub_item.get("name", "")}
            if "unit" in sub_item:
                proj["unit"] = sub_item["unit"]
            elif "categories" in sub_item:
                proj["categories"] = sub_item["categories"]
            if proj["name"]:
                projects.append(proj)

        if not projects:
            continue

        table_json = {
            "table_name": table_name,
            "projects": projects
        }

        with open(table_file, "w", encoding="utf-8") as f:
            json.dump(table_json, f, ensure_ascii=False, indent=2)
        created.append(table_name)
        print(f"✅ 基线表: {table_name} ({len(projects)}个项目)", file=sys.stderr)

    print(f"✅ 基线表: 共 {len(created)} 个", file=sys.stderr)
    return created


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="从生命体征和实验室检查生成表格 JSON")
    parser.add_argument("output_dir", help="输出目录（05_表格信息）")
    parser.add_argument("--details-dir", default=None, help="04_项目详情目录")
    parser.add_argument("--content-dir", default=None, help="02_内容提取目录（用于读取visits信息）")

    args = parser.parse_args()

    if args.details_dir is None:
        # 默认从输出目录的上级找 04_项目详情
        parent = os.path.dirname(args.output_dir)
        args.details_dir = os.path.join(parent, "04_项目详情")

    if args.content_dir is None:
        # 默认从输出目录的上级找 02_内容提取
        parent = os.path.dirname(args.output_dir)
        args.content_dir = os.path.join(parent, "02_内容提取")

    main(args.details_dir, args.output_dir, args.content_dir)
