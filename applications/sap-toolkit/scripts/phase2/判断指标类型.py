#!/usr/bin/env python3
"""
判断 JSON 文件中的指标类型：
- 只有定量指标
- 只有定性指标
- 定量指标与定性指标都有

判断依据：
- 定性指标：有 categories 字段（分类枚举值）
- 定量指标：有 unit 字段（数值型，带单位）

实验组数判断：
- 基于 试验样本.json 中的 groups 数组长度
- 1组 → G1, 2组 → G2, 3组及以上 → G3
"""

import json
import os
import sys


def classify_indicators(json_file: str) -> dict:
    """分析 JSON 文件中的指标类型

    Args:
        json_file: JSON 文件路径

    Returns:
        包含分析结果的字典
    """
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    table_name = data.get("table_name", data.get("item_name", "未知表格"))
    projects = data.get("projects", data.get("analysis_items", []))

    # 兼容 endpoint 格式（单个对象转为列表）
    if not projects and "endpoint" in data:
        projects = [data["endpoint"]]

    quantitative = []  # 定量指标
    qualitative = []   # 定性指标

    for project in projects:
        name = project.get("name", "未知指标")
        has_categories = "categories" in project
        has_unit = "unit" in project

        if has_categories:
            # 有 categories → 定性（即使同时有 unit 也优先归为定性）
            qualitative.append({
                "name": name,
                "categories": project["categories"]
            })
        elif has_unit:
            # 只有 unit 没有 categories → 定量
            quantitative.append({
                "name": name,
                "unit": project["unit"]
            })

    # 判断类型
    has_quant = len(quantitative) > 0
    has_qual = len(qualitative) > 0

    if has_quant and has_qual:
        indicator_type = "定量指标与定性指标都有"
    elif has_quant:
        indicator_type = "只有定量指标"
    elif has_qual:
        indicator_type = "只有定性指标"
    else:
        indicator_type = "无指标"

    return {
        "table_name": table_name,
        "indicator_type": indicator_type,
        "quantitative_count": len(quantitative),
        "qualitative_count": len(qualitative),
        "quantitative": quantitative,
        "qualitative": qualitative,
        "has_quant": has_quant,
        "has_qual": has_qual
    }


def get_indicator_type_code(json_file: str) -> str | list[str]:
    """获取指标类型的简化代码

    Args:
        json_file: JSON 文件路径

    Returns:
        只有定性指标 → "QUALCOM"
        只有定量指标 → "QUANCOM"
        都有 → ["QUALCOM", "QUANCOM"]
    """
    result = classify_indicators(json_file)

    if result["has_quant"] and result["has_qual"]:
        return ["QUALCOM", "QUANCOM"]
    elif result["has_qual"]:
        return "QUALCOM"
    elif result["has_quant"]:
        return "QUANCOM"
    else:
        return []


def get_experiment_group(sample_file: str) -> str:
    """根据试验样本文件判断实验组数

    Args:
        sample_file: 试验样本 JSON 文件路径

    Returns:
        组数代码: G1, G2 或 G3
    """
    with open(sample_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    sample_size = data.get("sample_size", {})
    groups = sample_size.get("groups", [])
    group_count = len(groups)

    if group_count <= 1:
        return "G1"
    elif group_count == 2:
        return "G2"
    else:
        return "G3"


def has_confidence_interval(stats_file: str) -> str:
    """判断统计方法是否涉及置信区间

    Args:
        stats_file: 统计方法 JSON 文件路径

    Returns:
        涉及置信区间 → "Y_N"
        不涉及 → "N_N"
    """
    with open(stats_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    confidence_interval = data.get("confidence_interval", {})
    required = confidence_interval.get("required", False)

    return "Y_N" if required else "N_N"


def build_template_code(json_file: str, sample_file: str, stats_file: str) -> str | list[str]:
    """生成模板代码

    Args:
        json_file: 表格 JSON 文件路径
        sample_file: 试验样本 JSON 文件路径
        stats_file: 统计方法 JSON 文件路径

    Returns:
        模板代码，格式: F_Gx_类型代码_置信区间
        如果有多种类型，返回列表
    """
    type_code = get_indicator_type_code(json_file)
    group_code = get_experiment_group(sample_file)
    ci_code = has_confidence_interval(stats_file)

    # 如果类型代码是列表，生成多个模板代码
    if isinstance(type_code, list):
        return [f"F_{group_code}_{tc}_{ci_code}" for tc in type_code]
    else:
        return f"F_{group_code}_{type_code}_{ci_code}"


def load_all_endpoints(endpoint_dir: str) -> list[dict]:
    """从 03_表格目录 加载所有 endpoint 数据"""
    endpoints = []
    if not os.path.exists(endpoint_dir):
        return endpoints
    for f in os.listdir(endpoint_dir):
        if f.endswith(".json") and "评价终点" in f:
            with open(os.path.join(endpoint_dir, f), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            endpoints.extend(data.get("endpoints", []))
    return endpoints


def find_endpoint_mentions(table_name: str, endpoints: list[dict]) -> str | None:
    """根据表名找到对应的 endpoint，返回提到的指标类型（用于非劣效/优效/等效）"""
    for ep in endpoints:
        ep_name = ep.get("name", "")
        if ep_name in table_name:
            if ep.get("mentions_mean"):
                return "MEAN"
            if ep.get("mentions_rate_difference"):
                return "RD"
            if ep.get("mentions_rate_ratio"):
                return "RR"
    return None


def build_all_template_codes(tables_file: str,
                             info_dir: str,
                             other_dir: str,
                             sample_file: str,
                             stats_file: str,
                             endpoint_dir: str = "") -> list[dict]:
    """批量生成所有表格的模板代码

    Args:
        tables_file: tables.json 文件路径
        info_dir: 05_表格信息 文件夹路径
        other_dir: 其他json 文件夹路径（生命体征、心电图检查等）
        sample_file: 试验样本 JSON 文件路径
        stats_file: 统计方法 JSON 文件路径
        endpoint_dir: 03_表格目录 文件夹路径（读源 endpoint 数据）

    Returns:
        包含表格信息和模板代码的列表
    """
    with open(tables_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 加载源 endpoint 数据（用于非劣效等方法表判断指标类型）
    all_endpoints = load_all_endpoints(endpoint_dir) if endpoint_dir else []

    # 获取组数代码
    group_code = get_experiment_group(sample_file)

    # 前四张表格的特殊模板代码映射
    special_tables = {
        1: f"D_{group_code}_SITEDS",   # 各中心病例分布
        2: f"D_{group_code}_ST",         # 人群划分
        3: f"D_{group_code}_EN",         # 入组病例
        4: f"E_{group_code}_FREQ1",      # 方案偏离
    }

    results = []

    for table in data.get("tables", []):
        table_index = table.get("index")
        table_name = table.get("name", "")

        # 前四张表格使用特殊规则
        if table_index in special_tables:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": special_tables[table_index]
            })
        # 表名含有"交叉表"使用特殊规则
        elif "交叉表" in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_CROSS"
            })
        # 器械缺陷归为有json的处理方式（与合并用药相同）
        elif "器械缺陷" in table_name:
            safe_name = table_name.replace("/", "_")
            json_file = os.path.join(info_dir, f"{safe_name}.json")
            if os.path.exists(json_file):
                try:
                    template_code = build_template_code(json_file, sample_file, stats_file)
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "template_code": template_code
                    })
                except Exception as e:
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "error": str(e)
                    })
        # 不良事件/严重不良事件（不含编码）使用特殊规则
        elif ("不良事件" in table_name or "严重不良事件" in table_name) and "编码" not in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"E_{group_code}_FREQ1"
            })
        # 不良事件/严重不良事件（含编码）使用特殊规则
        elif ("不良事件" in table_name or "严重不良事件" in table_name) and "编码" in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"E_{group_code}_FREQ3"
            })
        # 合并用药归为有json的处理方式
        elif "合并用药" in table_name:
            safe_name = table_name.replace("/", "_")
            json_file = os.path.join(info_dir, f"{safe_name}.json")
            if os.path.exists(json_file):
                try:
                    template_code = build_template_code(json_file, sample_file, stats_file)
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "template_code": template_code
                    })
                except Exception as e:
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "error": str(e)
                    })
        # 非劣效/优效/等效检验表格：根据 endpoint 的 mentions_* 判断类型
        elif "非劣效" in table_name or "优效" in table_name or "等效" in table_name:
            ep_type = find_endpoint_mentions(table_name, all_endpoints)
            if ep_type:
                if "非劣效" in table_name:
                    suffix = "NIN"
                elif "优效" in table_name:
                    suffix = "SUP"
                else:
                    suffix = "EQU"
                results.append({
                    "index": table_index,
                    "category": table.get("category"),
                    "name": table_name,
                    "template_code": f"F_{group_code}_{ep_type}_{suffix}"
                })
        # CMH 表格
        elif "中心效应CMH检验" in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_CMH"
            })
        # Logistic 回归表格
        elif "Logistic回归" in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_LOGISTIC"
            })
        # 生存分析表格
        elif "生存分析" in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_TTE"
            })
        # MMRM 表格使用特殊类型码
        elif "混合效应模型" in table_name or "最小二乘均数" in table_name:
            if "含研究分组" in table_name or "含组别" in table_name:
                suffix = "02_P1" if "混合效应模型" in table_name else "02_P2"
            else:
                suffix = "P1" if "混合效应模型" in table_name else "P2"
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_MMRM_{suffix}"
            })
        # ANCOVA 表格使用特殊类型码
        elif "协方差分析" in table_name or "组间修正均数" in table_name:
            if "修正均数" in table_name:
                suffix = "03"
            elif "不含交互项" in table_name:
                suffix = "02"
            else:
                suffix = "01"
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_ANCOVA_{suffix}"
            })
        # 生命体征、心电图检查、体格检查使用特殊规则
        elif any(keyword in table_name for keyword in ["生命体征", "心电图检查", "体格检查"]):
            # 优先从05_表格信息中查找单独文件
            safe_name = table_name.replace("/", "_")
            json_file = os.path.join(info_dir, f"{safe_name}.json")
            # 如果05_表格信息中没有，再从其他json文件夹中查找
            if not os.path.exists(json_file):
                json_file = os.path.join(other_dir, f"{safe_name}.json")
            if not os.path.exists(json_file):
                # 尝试汇总文件：生命体征-体温（SS） → 生命体征.json
                for keyword in ["生命体征", "心电图检查", "体格检查"]:
                    if keyword in table_name:
                        consolidated = os.path.join(other_dir, f"{keyword}.json")
                        if os.path.exists(consolidated):
                            json_file = consolidated
                            break
            if os.path.exists(json_file):
                try:
                    # 获取指标类型
                    type_code = get_indicator_type_code(json_file)
                    ci_code = has_confidence_interval(stats_file)

                    # 根据类型生成不同的代码
                    if isinstance(type_code, list):
                        template_codes = []
                        for tc in type_code:
                            if tc == "QUALCOM":
                                template_codes.append(f"F_{group_code}_QUALVIS_{ci_code}")
                            else:
                                template_codes.append(f"F_{group_code}_QUANVIS")
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": template_codes
                        })
                    elif type_code == "QUALCOM":
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": f"F_{group_code}_QUALVIS_{ci_code}"
                        })
                    elif type_code == "QUANCOM":
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": f"F_{group_code}_QUANVIS"
                        })
                except Exception as e:
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "error": str(e)
                    })
        # 主要疗效终点中"各中心"开头的表格使用 SITE 模板（与普通模板相同但带标记）
        elif table.get("category", "").startswith("主要疗效") and table_name.startswith("各中心"):
            json_file = os.path.join(info_dir, f"{table_name}.json")
            if not os.path.exists(json_file):
                safe_name = table_name.replace("/", "_")
                json_file = os.path.join(info_dir, f"{safe_name}.json")

            if os.path.exists(json_file):
                try:
                    type_code = get_indicator_type_code(json_file)
                    ci_code = has_confidence_interval(stats_file)

                    if isinstance(type_code, list):
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": [f"F_{group_code}_QUALSITE_{ci_code}", f"F_{group_code}_QUANSITE_{ci_code}"]
                        })
                    elif type_code == "QUALCOM":
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": f"F_{group_code}_QUALSITE_{ci_code}"
                        })
                    elif type_code == "QUANCOM":
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": f"F_{group_code}_QUANSITE_{ci_code}"
                        })
                except Exception as e:
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "error": str(e)
                    })
        # 亚组表格使用特殊类型码
        elif "亚组" in table_name:
            json_file = os.path.join(info_dir, f"{table_name}.json")
            if not os.path.exists(json_file):
                json_file = os.path.join(other_dir, f"{table_name}.json")
            if not os.path.exists(json_file):
                safe_name = table_name.replace("/", "_")
                json_file = os.path.join(info_dir, f"{safe_name}.json")
                if not os.path.exists(json_file):
                    json_file = os.path.join(other_dir, f"{safe_name}.json")

            if os.path.exists(json_file):
                try:
                    type_code = get_indicator_type_code(json_file)
                    ci_code = has_confidence_interval(stats_file)

                    if isinstance(type_code, list):
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": [f"F_{group_code}_QUALSUB_{ci_code}", f"F_{group_code}_QUANSUB_{ci_code}"]
                        })
                    elif type_code == "QUALCOM":
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": f"F_{group_code}_QUALSUB_{ci_code}"
                        })
                    elif type_code == "QUANCOM":
                        results.append({
                            "index": table_index,
                            "category": table.get("category"),
                            "name": table_name,
                            "template_code": f"F_{group_code}_QUANSUB_{ci_code}"
                        })
                except Exception as e:
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "error": str(e)
                    })
        # 率差表格使用特殊类型码
        elif "率差" in table_name:
            json_file = os.path.join(info_dir, f"{table_name}.json")
            if not os.path.exists(json_file):
                json_file = os.path.join(other_dir, f"{table_name}.json")
            if not os.path.exists(json_file):
                safe_name = table_name.replace("/", "_")
                json_file = os.path.join(info_dir, f"{safe_name}.json")
                if not os.path.exists(json_file):
                    json_file = os.path.join(other_dir, f"{safe_name}.json")

            has_opc = False
            if os.path.exists(json_file):
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    has_opc = data.get("has_rd_and_target", False)
                except Exception:
                    pass

            code = f"F_{group_code}_RD_OPC" if has_opc else f"F_{group_code}_RD"
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": code
            })
        # 率比表格使用特殊类型码
        elif "率比" in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_RR"
            })
        # 比值比表格使用特殊类型码
        elif "比值比" in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_OR"
            })
        # 中位数表格使用特殊类型码
        elif "中位数" in table_name:
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": f"F_{group_code}_MEDIAN"
            })
        # 均值表格使用特殊类型码
        elif "均值" in table_name:
            json_file = os.path.join(info_dir, f"{table_name}.json")
            if not os.path.exists(json_file):
                json_file = os.path.join(other_dir, f"{table_name}.json")
            if not os.path.exists(json_file):
                safe_name = table_name.replace("/", "_")
                json_file = os.path.join(info_dir, f"{safe_name}.json")
                if not os.path.exists(json_file):
                    json_file = os.path.join(other_dir, f"{safe_name}.json")

            # 读取 has_mean_and_target 标记
            has_opc = False
            if os.path.exists(json_file):
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    has_opc = data.get("has_mean_and_target", False)
                except Exception:
                    pass

            code = f"F_{group_code}_MEAN_OPC" if has_opc else f"F_{group_code}_MEAN"
            results.append({
                "index": table_index,
                "category": table.get("category"),
                "name": table_name,
                "template_code": code
            })
        else:
            # 其他表格检查是否有对应的 json 文件
            json_file = os.path.join(info_dir, f"{table_name}.json")

            # 如果 05_表格信息 中没有，也检查 其他json
            if not os.path.exists(json_file):
                json_file = os.path.join(other_dir, f"{table_name}.json")

            # 文件名中 / 替换为 _（如 尿素/尿素氮 → 尿素_尿素氮）
            if not os.path.exists(json_file):
                safe_name = table_name.replace("/", "_")
                json_file = os.path.join(info_dir, f"{safe_name}.json")
                if not os.path.exists(json_file):
                    json_file = os.path.join(other_dir, f"{safe_name}.json")

            if os.path.exists(json_file):
                try:
                    template_code = build_template_code(json_file, sample_file, stats_file)
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "template_code": template_code
                    })
                except Exception as e:
                    results.append({
                        "index": table_index,
                        "category": table.get("category"),
                        "name": table_name,
                        "error": str(e)
                    })

    return results


def generate_template_codes(output_dir: str) -> dict:
    """从 graph 输出目录生成模板代码

    Args:
        output_dir: graph 输出目录，包含 tables.json, 02_内容提取/, 05_表格信息/ 等

    Returns:
        {"total": N, "tables": [...]}
    """
    tables_file = os.path.join(output_dir, "tables.json")
    info_dir = os.path.join(output_dir, "05_表格信息")
    other_dir = os.path.join(output_dir, "其他json")
    endpoint_dir = os.path.join(output_dir, "03_表格目录")

    # 基本信息来源：优先从基本信息来源/读，fallback 到 02_内容提取/
    sample_file = os.path.join(output_dir, "基本信息来源", "试验样本.json")
    if not os.path.exists(sample_file):
        sample_file = os.path.join(output_dir, "02_内容提取", "试验样本.json")
    stats_file = os.path.join(output_dir, "基本信息来源", "统计方法.json")
    if not os.path.exists(stats_file):
        stats_file = os.path.join(output_dir, "02_内容提取", "统计方法.json")

    # 检查必需文件
    for path, desc in [(tables_file, "tables.json"), (sample_file, "试验样本.json"), (stats_file, "统计方法.json")]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"缺少必需文件: {desc} ({path})")

    results = build_all_template_codes(tables_file, info_dir, other_dir, sample_file, stats_file, endpoint_dir)

    output = {
        "total": len(results),
        "tables": results
    }

    output_path = os.path.join(output_dir, "模板代码结果.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 模板代码生成完成: {len(results)} 张表 → {output_path}", file=sys.stderr)
    return output
