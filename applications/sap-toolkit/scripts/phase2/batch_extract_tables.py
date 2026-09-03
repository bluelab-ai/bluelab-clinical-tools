#!/usr/bin/env python3
"""
批量提取表格信息
================

从 tables.json 读取表格列表，调用 extract_table_info 提取表格结构信息。

规则：
- 跳过固定的病例分布表（除入组病例外）
- 跳过：主要疗效终点分析、器械缺陷、不良事件、实验室检查、生命体征
- 入组病例使用特殊的prompt提取退出试验原因
- 每次并行提取5张表
- 只传表名给 extract_table_info
"""

import os
import sys
import json

from scripts.phase2.extract_table_info import extract_tables_parallel


def load_tables(json_path: str):
    """加载 tables.json 并返回需要提取的表格信息列表

    Returns:
        list[dict]: 每个元素包含 {"name": 表名, "category": 分类, "source_category": 原始类别}
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tables = data.get("tables", [])

    # 跳过的 category 关键词
    skip_keywords = ["主要疗效终点", "器械缺陷", "不良事件", "实验室检查", "生命体征", "合并用药"]

    # 跳过的固定表名（病例分布中的固定表，除入组病例和方案偏离外）
    skip_names = ["各中心病例分布情况", "各中心人群划分情况"]

    # 从安全性迁移到基线的表，由 gen_baseline_tables 生成 JSON，跳过 CRF 提取
    safety_source_categories = {"vital_signs", "physical_examination", "ecg", "laboratory"}

    filtered = []
    for t in tables:
        category = t.get("category", "")
        name = t.get("name", "")
        source_category = t.get("source_category", "")

        # 检查是否需要跳过（按category关键词）
        if any(kw in category for kw in skip_keywords):
            continue

        # 检查是否需要跳过（按固定表名）
        if any(skip_name in name for skip_name in skip_names):
            continue

        # 跳过从安全性迁移到基线的表（由 gen_baseline_tables 处理）
        if source_category in safety_source_categories:
            continue

        filtered.append({"name": name, "category": category, "source_category": source_category})

    return filtered
