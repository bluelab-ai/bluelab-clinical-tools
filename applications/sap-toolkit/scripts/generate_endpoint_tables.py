#!/usr/bin/env python3
"""
终点表格信息生成工具
==================

根据终点 JSON 和表格名称列表，生成每张表的 JSON 信息。

运行:
    python3 scripts/generate_endpoint_tables.py <终点.json> <表格名称.txt> --output-dir <输出目录>

输出:
    每张表对应一个 JSON 文件
"""

import os
import sys
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.rules import classify_table_type


def log(msg: str, level: str = "INFO"):
    """输出日志"""
    prefix = {
        "INFO": "📋",
        "SAVE": "💾",
        "DONE": "✅",
        "ERROR": "❌",
    }.get(level, "  ")
    print(f"{prefix} {msg}", file=sys.stderr)


def parse_table_names(txt_path: str) -> List[str]:
    """从表格名称 txt 文件中解析表名列表"""
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 匹配 "序号. 表名" 格式
    pattern = r'^\d+\.\s+(.+)$'
    tables = []
    for line in content.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            tables.append(match.group(1))

    return tables


def find_endpoint_for_table(table_name: str, endpoints: List[Dict]) -> Optional[Dict]:
    """根据表名找到对应的终点"""
    for ep in endpoints:
        ep_name = ep.get("name", "")
        if ep_name in table_name:
            return ep
    return None


def find_method_for_table(table_name: str, methods: List[Dict]) -> Optional[Dict]:
    """根据表名提取统计方法名"""
    # 已知方法关键词（用于判断是否为统计分析表）
    METHOD_KEYWORDS = [
        "协方差分析", "组间修正均数描述及比较",
        "混合效应模型估计情况", "最小二乘均数",
        "重复测量的混合效应模型估计情况",
        "非劣效检验", "优效性检验", "等效性检验",
        "Logistic回归", "生存分析", "中心效应CMH检验",
    ]

    for keyword in METHOD_KEYWORDS:
        if keyword in table_name:
            return {"name": keyword}

    return None


def get_table_count_for_method(method_name: str) -> int:
    """获取统计方法的出表数量"""
    table_type = classify_table_type(method_name)
    if table_type == "ancova":
        return 4
    elif table_type == "mmrm":
        return 4
    elif table_type == "single":
        return 1
    else:
        return 0


def generate_table_json(
    table_name: str,
    endpoints: List[Dict],
    methods: List[Dict],
) -> Dict[str, Any]:
    """为单张表生成 JSON 信息"""

    result = {"table_name": table_name}

    # 判断是否为亚组分析表
    if "亚组分析" in table_name:
        # 亚组分析表：从表名解析亚组信息
        # 表名格式：亚组分析-{endpoint_name}-{subgroup}（{pop}）
        # 例如：亚组分析-主要终点-年龄<65岁（FAS）
        import re
        match = re.search(r'亚组分析-(.+?)-(.+?)（.+）$', table_name)
        if match:
            endpoint_name = match.group(1)
            subgroup = match.group(2)  # 如 "年龄<65岁" 或 "性别男"

            # 构造亚组列表（每张表只有一个亚组）
            result["subgroups"] = [subgroup]

        # 取终点信息
        endpoint = find_endpoint_for_table(table_name, endpoints)
        if endpoint:
            # 构造 projects 格式（兼容模板）
            projects = []
            if "categories" in endpoint:
                projects.append({
                    "name": endpoint["name"],
                    "categories": endpoint["categories"]
                })
            if "unit" in endpoint:
                projects.append({
                    "name": endpoint["name"],
                    "unit": endpoint["unit"]
                })
            result["projects"] = projects

        return result

    # 判断是否为统计分析表（表名中包含统计方法名）
    method = find_method_for_table(table_name, methods)
    if method:
        result["method"] = {"name": method["name"]}
        # 统计方法表也包含终点信息
        endpoint = find_endpoint_for_table(table_name, endpoints)
        if endpoint:
            endpoint_info = {"name": endpoint["name"]}
            if "categories" in endpoint:
                endpoint_info["categories"] = endpoint["categories"]
            if "unit" in endpoint:
                endpoint_info["unit"] = endpoint["unit"]
            result["endpoint"] = endpoint_info

            # 同时写入 projects，供模板代码选择逻辑使用
            project_item = {"name": endpoint["name"]}
            if "categories" in endpoint:
                project_item["categories"] = endpoint["categories"]
            if "unit" in endpoint:
                project_item["unit"] = endpoint["unit"]
            result["projects"] = [project_item]
        return result

    # 普通终点表：取终点信息
    endpoint = find_endpoint_for_table(table_name, endpoints)
    if endpoint:
        endpoint_info = {"name": endpoint["name"]}
        if "categories" in endpoint:
            endpoint_info["categories"] = endpoint["categories"]
        if "unit" in endpoint:
            endpoint_info["unit"] = endpoint["unit"]
        result["endpoint"] = endpoint_info

        # 同时写入 projects，供模板代码选择逻辑使用
        project_item = {"name": endpoint["name"]}
        if "categories" in endpoint:
            project_item["categories"] = endpoint["categories"]
        if "unit" in endpoint:
            project_item["unit"] = endpoint["unit"]
        result["projects"] = [project_item]

        # 均值表：标记是否同时提到均值和目标值
        if "均值" in table_name:
            result["has_mean_and_target"] = bool(endpoint.get("mentions_mean") and endpoint.get("mentions_target"))
        # 率差表：标记是否同时提到率差和目标值
        if "率差" in table_name:
            result["has_rd_and_target"] = bool(endpoint.get("mentions_rate_difference") and endpoint.get("mentions_target"))

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="终点表格信息生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 generate_endpoint_tables.py 主要评价终点.json 主要评价终点_表格名称.txt --output-dir 05_表格信息
  python3 generate_endpoint_tables.py 安全性评价分析.json 安全性评价分析_表格名称.txt --output-dir 05_表格信息 --safety
        """,
    )
    parser.add_argument("endpoint_json", help="终点 JSON 文件路径")
    parser.add_argument("table_names_txt", help="表格名称 TXT 文件路径")
    parser.add_argument("--output-dir", default="05_表格信息", help="输出目录")
    parser.add_argument("--safety", action="store_true", help="安全性终点模式（只处理 safety_endpoints）")

    args = parser.parse_args()

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"终点表格信息生成工具", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 1. 读取终点 JSON
    with open(args.endpoint_json, "r", encoding="utf-8") as f:
        endpoint_data = json.load(f)

    if args.safety:
        # 安全性终点模式：只处理 safety_endpoints
        endpoints = endpoint_data.get("safety_endpoints", [])
        methods = []
        log(f"读取安全性终点 JSON: {len(endpoints)} 个终点", "INFO")
    else:
        endpoints = endpoint_data.get("endpoints", [])
        methods = endpoint_data.get("statistical_methods", {}).get("primary_analysis", {}).get("methods", [])
        log(f"读取终点 JSON: {len(endpoints)} 个终点, {len(methods)} 个方法", "INFO")

    # 2. 解析表格名称
    table_names = parse_table_names(args.table_names_txt)
    log(f"解析表格名称: {len(table_names)} 张表", "INFO")

    # 3. 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)

    # 4. 为每张表生成 JSON
    success_count = 0
    for table_name in table_names:
        # 安全性终点模式：只处理匹配 safety_endpoints 的表
        if args.safety:
            endpoint = find_endpoint_for_table(table_name, endpoints)
            if endpoint:
                endpoint_info = {"name": endpoint["name"]}
                if "categories" in endpoint:
                    endpoint_info["categories"] = endpoint["categories"]
                if "unit" in endpoint:
                    endpoint_info["unit"] = endpoint["unit"]

                # 同时写入 projects，供模板代码选择逻辑使用
                project_item = {"name": endpoint["name"]}
                if "categories" in endpoint:
                    project_item["categories"] = endpoint["categories"]
                if "unit" in endpoint:
                    project_item["unit"] = endpoint["unit"]

                table_json = {"table_name": table_name, "endpoint": endpoint_info, "projects": [project_item]}
            else:
                # 不匹配安全性终点，跳过
                continue
        else:
            table_json = generate_table_json(table_name, endpoints, methods)

        # 生成文件名（去掉括号中的特殊字符）
        safe_name = table_name.replace("/", "_").replace("\\", "_")
        output_file = os.path.join(args.output_dir, f"{safe_name}.json")

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(table_json, f, ensure_ascii=False, indent=2)

        log(f"  {table_name}", "SAVE")
        success_count += 1

    print(f"{'─'*60}", file=sys.stderr)
    log(f"完成！生成 {success_count} 个文件", "DONE")


if __name__ == "__main__":
    main()
