#!/usr/bin/env python3
"""
从表格目录汇总 MD 文件中提取所有表格，输出为 JSON
"""

import re
import json
import sys
from pathlib import Path


def _classify_data_source(category: str, name: str) -> str:
    """
    根据分类名和表格名判断数据来源。
    只对已明确分类的类别返回标签，其余返回 None（不标记）。

    Returns:
        "none"  — 固定项目
        "crf"   — CRF自动提取
        "fill"  — 根据表格名填充
    """
    # 固定项目
    none_categories = ["病例分布", "人口学信息", "不良事件", "心电图检查", "合并用药", "器械缺陷"]
    for kw in none_categories:
        if kw in category:
            return "none"
    none_names = ["不良事件", "不良事件编码", "严重不良事件编码", "合并用药", "器械缺陷"]
    for kw in none_names:
        if kw in name:
            return "none"

    # CRF自动提取
    crf_categories = ["病史", "基线信息", "次要疗效终点分析", "安全性终点", "实验室检查", "生命体征", "体格检查"]
    for kw in crf_categories:
        if kw in category:
            return "crf"

    # 根据表格名填充
    fill_categories = ["主要疗效终点分析"]
    for kw in fill_categories:
        if kw in category:
            return "fill"

    return "crf"


def extract_tables_from_md(md_path: str) -> list[dict]:
    """
    从 MD 文件中提取表格

    Args:
        md_path: MD 文件路径

    Returns:
        表格列表，每个表格包含 category, index, name, data_source 字段，
        以及可选的 source_category 字段（从 [from:xxx] 标记解析）
    """
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    tables = []
    current_category = ""

    # 按行处理
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # 检测分类标题 (## xxx)
        if line.startswith("## "):
            current_category = line[3:].strip()
            i += 1
            continue

        # 检测表格行 (| 序号 | 表格名称 |)
        # 匹配格式: | 数字 | 表名 |
        # 排除 "### 补充分析" 这样的小标题
        match = re.match(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|$", line)
        if match:
            index = int(match.group(1))
            raw_name = match.group(2).strip()
            # 跳过小标题行
            if raw_name.startswith("###"):
                i += 1
                continue
            # 解析 [from:xxx] 标记
            source_category = ""
            from_match = re.search(r'\[from:(\w+)\]', raw_name)
            if from_match:
                source_category = from_match.group(1)
                raw_name = re.sub(r'\s*\[from:\w+\]', '', raw_name).strip()
            ds = _classify_data_source(current_category, raw_name)
            entry = {
                "category": current_category,
                "index": index,
                "name": raw_name,
                "data_source": ds,
            }
            if ds == "title":
                entry["locked"] = True
            if source_category:
                entry["source_category"] = source_category
            tables.append(entry)

        i += 1

    return tables


def extract_tables_grouped(md_path: str) -> dict:
    """
    从 MD 文件中提取表格，按分类分组

    Args:
        md_path: MD 文件路径

    Returns:
        按分类分组的表格字典
    """
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    grouped = {}
    current_category = ""

    lines = content.split("\n")
    for line in lines:
        line = line.strip()

        # 检测分类标题
        if line.startswith("## "):
            current_category = line[3:].strip()
            if current_category not in grouped:
                grouped[current_category] = []
            continue

        # 检测表格行
        match = re.match(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|$", line)
        if match and current_category:
            index = int(match.group(1))
            name = match.group(2).strip()
            grouped[current_category].append({
                "index": index,
                "name": name
            })

    return grouped


def main():
    # 默认路径
    default_md = "/Users/xulei/项目/sap/sap_toolkit/形状/表格目录_汇总.md"

    md_path = sys.argv[1] if len(sys.argv) > 1 else default_md

    if not Path(md_path).exists():
        print(f"错误: 文件不存在 - {md_path}", file=sys.stderr)
        sys.exit(1)

    # 提取表格（扁平列表）
    tables = extract_tables_from_md(md_path)

    # 输出 JSON
    output = {
        "total": len(tables),
        "tables": tables
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
