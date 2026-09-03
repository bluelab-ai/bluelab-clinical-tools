#!/usr/bin/env python3
"""
SAP 文档结构化提取及表格名称生成工具
一步完成：从 SAP 文档提取 JSON 并生成表格名称
使用 Anthropic SDK 实现
"""

import anthropic
import json
import sys
import os
import argparse
from datetime import datetime
from typing import List, Dict, Any

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    API_KEY, BASE_URL, MODEL,
    PRIMARY_SYSTEM_PROMPT, PRIMARY_EXTRACTION_RULES,
    SECONDARY_SYSTEM_PROMPT, SECONDARY_EXTRACTION_RULES,
    SAFETY_SYSTEM_PROMPT, SAFETY_EXTRACTION_RULES,
    SAMPLE_SYSTEM_PROMPT, SAMPLE_EXTRACTION_RULES,
    STAT_METHODS_SYSTEM_PROMPT, STAT_METHODS_EXTRACTION_RULES,
    METHOD_NAME_MAPPING, normalize_method_name, classify_table_type,
    get_thinking_config, APILogger,
)


# ===== 日志 =====
def log(msg: str, level: str = "INFO"):
    """输出日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "📋",
        "READ": "📖",
        "GEN": "🤖",
        "TABLE": "📊",
        "SAVE": "💾",
        "ERROR": "❌",
        "DONE": "✅",
    }.get(level, "  ")
    print(f"[{timestamp}] {prefix} {msg}", file=sys.stderr)


# ===== 文件读取 =====
def read_file(path: str) -> str:
    """读取文件内容"""
    log(f"读取文件: {path}", "READ")
    if not os.path.exists(path):
        log(f"文件不存在: {path}", "ERROR")
        raise FileNotFoundError(f"文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    log(f"  ✓ 读取完成: {len(content)} 字符", "READ")
    return content


def save_json(data: dict, path: str):
    """保存 JSON 文件"""
    log(f"保存 JSON: {path}", "SAVE")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"  ✓ 保存完成", "SAVE")


def save_text(content: str, path: str):
    """保存文本文件"""
    log(f"保存文件: {path}", "SAVE")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"  ✓ 保存完成: {len(content)} 字符", "SAVE")


# ===== Tool Schema 定义 =====
EXTRACTION_TOOL = {
    "name": "extract_sap_data",
    "description": "从 SAP 文档中提取主要评价终点、统计分析方法及子分析信息",
    "input_schema": {
        "type": "object",
        "properties": {
            "endpoints": {
                "type": "array",
                "description": "主要终点列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "终点名称"
                        },
                        "timepoint": {
                            "type": "string",
                            "description": "评价时间点"
                        },
                        "definition": {
                            "type": "string",
                            "description": "终点定义"
                        },
                        "categories": {
                            "type": "array",
                            "description": "定性终点的分类结果（如成功/失败、发生/未发生），定量终点不填此项",
                            "items": {"type": "string"},
                            "minItems": 1
                        },
                        "unit": {
                            "type": "string",
                            "description": "定量终点的测量单位（如分、mmHg、%），定性终点不填此项"
                        },
                        "mentions_mean": {
                            "type": "boolean",
                            "description": "该终点的文本中是否提到「均值」相关描述（如均值、mean、平均值等）"
                        },
                        "mentions_median": {
                            "type": "boolean",
                            "description": "该终点的文本中是否提到「中位数」相关描述（如中位数、median等）"
                        },
                        "mentions_rate_difference": {
                            "type": "boolean",
                            "description": "该终点的文本中是否提到「率差」相关描述（如率差、rate difference、风险差等）"
                        },
                        "mentions_odds_ratio": {
                            "type": "boolean",
                            "description": "该终点的文本中是否提到「比值比」相关描述（如比值比、OR、odds ratio等）"
                        },
                        "mentions_rate_ratio": {
                            "type": "boolean",
                            "description": "该终点的文本中是否提到「率比」相关描述（如率比、RR、rate ratio、相对风险等）"
                        },
                        "mentions_target": {
                            "type": "boolean",
                            "description": "该终点的文本中是否提到「目标值」相关描述（如目标值、界值、阈值、目标、target等）"
                        }
                    },
                    "required": ["name", "timepoint", "definition", "mentions_mean", "mentions_median", "mentions_rate_difference", "mentions_odds_ratio", "mentions_rate_ratio", "mentions_target"]
                }
            },
            "statistical_methods": {
                "type": "object",
                "description": "统计分析方法",
                "properties": {
                    "method_flags": {
                        "type": "object",
                        "description": "统计方法标记，文档中明确提到的方法设为 true",
                        "properties": {
                            "ancova": {"type": "boolean", "description": "协方差分析（ANCOVA）"},
                            "mmrm": {"type": "boolean", "description": "混合效应模型重复测量（MMRM）"},
                            "non_inferiority": {"type": "boolean", "description": "非劣效检验"},
                            "superiority": {"type": "boolean", "description": "优效性检验"},
                            "equivalence": {"type": "boolean", "description": "等效性检验"},
                            "logistic": {"type": "boolean", "description": "Logistic回归"},
                            "cox": {"type": "boolean", "description": "Cox回归"},
                            "survival": {"type": "boolean", "description": "生存分析（Kaplan-Meier等）"},
                            "t_test": {"type": "boolean", "description": "t检验"},
                            "chi_square": {"type": "boolean", "description": "卡方检验"},
                            "fisher": {"type": "boolean", "description": "Fisher精确检验"},
                            "wilcoxon": {"type": "boolean", "description": "Wilcoxon检验/Mann-Whitney U检验"},
                            "cmh": {"type": "boolean", "description": "CMH检验"},
                            "center_cmh": {"type": "boolean", "description": "中心效应CMH检验"},
                            "descriptive": {"type": "boolean", "description": "描述性分析"}
                        },
                        "required": ["ancova", "mmrm", "non_inferiority", "superiority", "equivalence", "logistic", "cox", "survival", "t_test", "chi_square", "fisher", "wilcoxon", "cmh", "center_cmh", "descriptive"]
                    },
                    "analysis_population": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "使用的分析人群列表，如 FAS、PPS、mITT 等，多人群分开列出"
                    },
                    "covariates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "协变量列表"
                    },
                    "output": {
                        "type": "string",
                        "description": "输出结果描述"
                    }
                },
                "required": ["method_flags", "analysis_population", "covariates", "output"]
            },
            "sub_analyses": {
                "type": "array",
                "description": "子分析列表（敏感性分析、补充分析、亚组分析等），如无子分析则为空数组",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["敏感性分析", "补充分析", "亚组分析", "探索性分析"],
                            "description": "子分析类型"
                        },
                        "name": {
                            "type": "string",
                            "description": "子分析名称"
                        },
                        "purpose": {
                            "type": "string",
                            "description": "分析目的"
                        },
                        "analysis_population": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "使用的分析人群列表，多人群分开列出"
                        },
                        "statistical_method": {
                            "type": "string",
                            "description": "具体统计方法"
                        },
                        "subgroup_variables": {
                            "type": "array",
                            "description": "亚组变量列表（仅亚组分析使用）",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "variable": {
                                        "type": "string",
                                        "description": "亚组变量名称"
                                    },
                                    "groups": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "分组列表"
                                    }
                                },
                                "required": ["variable", "groups"]
                            }
                        }
                    },
                    "required": ["type", "name", "purpose", "analysis_population", "statistical_method"]
                }
            }
        },
        "required": ["endpoints", "statistical_methods", "sub_analyses"]
    }
}


# ===== 次要终点 Tool Schema 定义 =====
SECONDARY_EXTRACTION_TOOL = {
    "name": "extract_secondary_endpoints",
    "description": "从 SAP 文档中提取次要评价终点、统计分析方法信息",
    "input_schema": {
        "type": "object",
        "properties": {
            "endpoints": {
                "type": "array",
                "description": "次要终点列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "终点名称（如器械成功率、手术成功率）"
                        },
                        "timepoint": {
                            "type": "string",
                            "description": "评价时间点"
                        },
                        "definition": {
                            "type": "string",
                            "description": "终点定义"
                        },
                        "categories": {
                            "type": "array",
                            "description": "定性终点的分类结果（如成功/失败、发生/未发生），定量终点不填此项",
                            "items": {"type": "string"},
                            "minItems": 1
                        },
                        "unit": {
                            "type": "string",
                            "description": "定量终点的测量单位（如分、mmHg、%），定性终点不填此项"
                        }
                    },
                    "required": ["name", "timepoint", "definition"]
                }
            },
            "statistical_methods": {
                "type": "object",
                "description": "统计分析方法",
                "properties": {
                    "method_flags": {
                        "type": "object",
                        "description": "统计方法标记，文档中明确提到的方法设为 true",
                        "properties": {
                            "ancova": {"type": "boolean", "description": "协方差分析（ANCOVA）"},
                            "mmrm": {"type": "boolean", "description": "混合效应模型重复测量（MMRM）"},
                            "non_inferiority": {"type": "boolean", "description": "非劣效检验"},
                            "superiority": {"type": "boolean", "description": "优效性检验"},
                            "equivalence": {"type": "boolean", "description": "等效性检验"},
                            "logistic": {"type": "boolean", "description": "Logistic回归"},
                            "cox": {"type": "boolean", "description": "Cox回归"},
                            "survival": {"type": "boolean", "description": "生存分析（Kaplan-Meier等）"},
                            "t_test": {"type": "boolean", "description": "t检验"},
                            "chi_square": {"type": "boolean", "description": "卡方检验"},
                            "fisher": {"type": "boolean", "description": "Fisher精确检验"},
                            "wilcoxon": {"type": "boolean", "description": "Wilcoxon检验/Mann-Whitney U检验"},
                            "cmh": {"type": "boolean", "description": "CMH检验"},
                            "center_cmh": {"type": "boolean", "description": "中心效应CMH检验"},
                            "descriptive": {"type": "boolean", "description": "描述性分析"}
                        },
                        "required": ["ancova", "mmrm", "non_inferiority", "superiority", "equivalence", "logistic", "cox", "survival", "t_test", "chi_square", "fisher", "wilcoxon", "cmh", "center_cmh", "descriptive"]
                    },
                    "analysis_population": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "使用的分析人群列表，必须使用缩写格式：FAS（全分析集）、PPS（符合方案集）、SS（安全性分析集）"
                    },
                    "covariates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "协变量列表"
                    },
                    "output": {
                        "type": "string",
                        "description": "输出结果描述"
                    }
                },
                "required": ["method_flags", "analysis_population", "covariates", "output"]
            },
            "sub_analyses": {
                "type": "array",
                "description": "子分析列表，如无则为空数组",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["敏感性分析", "补充分析", "亚组分析", "探索性分析"],
                            "description": "子分析类型"
                        },
                        "name": {
                            "type": "string",
                            "description": "子分析名称"
                        },
                        "purpose": {
                            "type": "string",
                            "description": "分析目的"
                        },
                        "analysis_population": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "使用的分析人群列表，必须使用缩写格式：FAS（全分析集）、PPS（符合方案集）、SS（安全性分析集）"
                        },
                        "statistical_method": {
                            "type": "string",
                            "description": "具体统计方法"
                        },
                        "subgroup_variables": {
                            "type": "array",
                            "description": "亚组变量列表（仅亚组分析使用）",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "variable": {
                                        "type": "string",
                                        "description": "亚组变量名称"
                                    },
                                    "groups": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "分组列表"
                                    }
                                },
                                "required": ["variable", "groups"]
                            }
                        }
                    },
                    "required": ["type", "name", "purpose", "analysis_population", "statistical_method"]
                }
            }
        },
        "required": ["endpoints", "statistical_methods", "sub_analyses"]
    }
}


# ===== 安全性终点 Tool Schema 定义 =====

SAFETY_EXTRACTION_TOOL = {
    "name": "extract_safety_endpoints",
    "description": "从 SAP 文档中提取安全性评价终点信息",
    "input_schema": {
        "type": "object",
        "properties": {
            "safety_endpoints": {
                "type": "array",
                "description": "具体安全性终点列表（如出血事件、卒中等），每个终点独立一条。注意：生命体征（体温、血压、心率等）、实验室检查（血常规、肝功能等）、体格检查、心电图检查、器械缺陷、合并用药、不良事件等不属于具体终点，不要放入此列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "终点名称（如出血事件、卒中等）"
                        },
                        "categories": {
                            "type": "array",
                            "description": "定性终点的分类结果（如发生/未发生、有/无），定量终点不填此项",
                            "items": {"type": "string"},
                            "minItems": 1
                        },
                        "unit": {
                            "type": "string",
                            "description": "定量终点的测量单位（如次、mmHg、%），定性终点不填此项"
                        }
                    },
                    "required": ["name"]
                }
            }
        },
        "required": ["safety_endpoints"]
    }
}


SAMPLE_EXTRACTION_TOOL = {
    "name": "extract_sample_info",
    "description": "从 SAP 文档中提取试验样本相关信息（样本量计算、随机化、盲法）",
    "input_schema": {
        "type": "object",
        "properties": {
            "sample_size": {
                "type": "object",
                "description": "样本量信息",
                "properties": {
                    "calculation": {
                        "type": "object",
                        "description": "样本量计算参数",
                        "properties": {
                            "assumptions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "计算假设（如事件率、效应量等）"
                            },
                            "effect_size": {
                                "type": "string",
                                "description": "效应量"
                            },
                            "power": {
                                "type": "string",
                                "description": "检验效能（power）"
                            },
                            "alpha": {
                                "type": "string",
                                "description": "显著性水平（alpha）"
                            },
                            "dropout_rate": {
                                "type": "string",
                                "description": "脱落率"
                            },
                            "formula": {
                                "type": "string",
                                "description": "计算公式或方法描述"
                            }
                        }
                    },
                    "total_n": {
                        "type": "string",
                        "description": "总样本量"
                    },
                    "groups": {
                        "type": "array",
                        "description": "分组信息（仅组名）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "组别名称"}
                            },
                            "required": ["name"]
                        }
                    }
                }
            },
            "randomization": {
                "type": "object",
                "description": "随机化信息",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "随机化方法（如区组随机、分层随机等）"
                    },
                    "ratio": {
                        "type": "string",
                        "description": "分配比例（如 1:1）"
                    },
                    "stratification_factors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "分层因素"
                    },
                    "block_size": {
                        "type": "string",
                        "description": "区组大小"
                    }
                }
            },
            "blinding": {
                "type": "object",
                "description": "盲法信息",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "盲法类型（单盲/双盲/开放）"
                    },
                    "description": {
                        "type": "string",
                        "description": "设盲描述（设盲对象等）"
                    }
                }
            }
        },
        "required": ["sample_size"]
    }
}


STAT_METHODS_EXTRACTION_TOOL = {
    "name": "extract_stat_methods",
    "description": "从 SAP 文档中提取主次要终点和安全性评价之外的统计方法内容",
    "input_schema": {
        "type": "object",
        "properties": {
            "confidence_interval": {
                "type": "object",
                "description": "置信区间相关信息",
                "properties": {
                    "required": {
                        "type": "boolean",
                        "description": "是否需要报告置信区间。仅当文档中明确出现\"置信区间\"、\"CI\"、\"confidence interval\"等字样时才设为 true，不要根据统计方法推断（如 t 检验、ANCOVA 等方法本身不意味着需要置信区间）"
                    }
                }
            },
            "missing_data": {
                "type": "array",
                "description": "各类分析的缺失值处理方法",
                "items": {
                    "type": "object",
                    "properties": {
                        "analysis_type": {
                            "type": "string",
                            "description": "分析类型（如一般分析、主要终点分析、次要终点分析、安全性分析等）"
                        },
                        "has_method": {
                            "type": "boolean",
                            "description": "是否有缺失值处理方法"
                        },
                        "method": {
                            "type": "string",
                            "description": "缺失值处理方法（has_method 为 false 时填空字符串）"
                        }
                    },
                    "required": ["analysis_type", "has_method", "method"]
                }
            },
            "general_methods": {
                "type": "array",
                "description": "一般统计方法（描述性分析、正态性检验、数据转换等）",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "方法名称"},
                        "description": {"type": "string", "description": "方法描述"}
                    },
                    "required": ["name"]
                }
            },
            "multiplicity": {
                "type": "object",
                "description": "多重性调整",
                "properties": {
                    "adjusted": {
                        "type": "boolean",
                        "description": "是否进行多重性调整"
                    },
                    "method": {
                        "type": "string",
                        "description": "调整方法（如 Bonferroni、Hochberg 等）"
                    },
                    "alpha": {
                        "type": "string",
                        "description": "调整后的显著性水平"
                    },
                    "details": {
                        "type": "string",
                        "description": "其他调整细节"
                    }
                }
            },
            "interim_analysis": {
                "type": "object",
                "description": "期中分析",
                "properties": {
                    "planned": {
                        "type": "boolean",
                        "description": "是否计划进行期中分析"
                    },
                    "timing": {
                        "type": "string",
                        "description": "期中分析时间点"
                    },
                    "stopping_rules": {
                        "type": "string",
                        "description": "停止规则"
                    },
                    "alpha_spending": {
                        "type": "string",
                        "description": "alpha 消耗函数"
                    }
                }
            },
            "analysis_populations": {
                "type": "array",
                "description": "分析人群定义",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "人群名称（如 FAS、PPS、SS）"},
                        "definition": {"type": "string", "description": "人群定义"}
                    },
                    "required": ["name", "definition"]
                }
            }
        },
        "required": ["confidence_interval"]
    }
}


def _normalize_method_names(data: dict) -> dict:
    """
    归一化提取结果中的方法名称

    遍历 statistical_methods.primary_analysis.methods 和 sub_analyses 中的
    statistical_method，将方法名称归一化为标准名称。
    """
    # 归一化主要分析方法
    if "statistical_methods" in data:
        primary = data["statistical_methods"].get("primary_analysis", {})
        if "methods" in primary:
            normalized_methods = []
            for method in primary["methods"]:
                if isinstance(method, dict) and "name" in method:
                    method["name"] = normalize_method_name(method["name"])
                elif isinstance(method, str):
                    method = normalize_method_name(method)
                normalized_methods.append(method)
            primary["methods"] = normalized_methods

    # 归一化子分析中的方法
    if "sub_analyses" in data:
        for sub in data["sub_analyses"]:
            if "statistical_method" in sub:
                sub["statistical_method"] = normalize_method_name(sub["statistical_method"])

    return data


# ===== 检查并修复 analysis_population =====
def _fix_analysis_population(data: dict) -> dict:
    """
    检查 statistical_methods 中的 analysis_population 是否为空，
    如果为空则默认使用 ["FAS", "PPS"]
    """
    statistical_methods = data.get("statistical_methods", {})
    if not statistical_methods:
        return data

    analysis_population = statistical_methods.get("analysis_population", [])
    if not analysis_population:  # 空数组、None 或不存在
        statistical_methods["analysis_population"] = ["FAS", "PPS"]
        log("  ⚠️ analysis_population 为空，已默认使用 ['FAS', 'PPS']", "INFO")

    return data


# ===== 结构化提取 =====
def extract_endpoints(sap_content: str, api_logger: APILogger = None) -> dict:
    """
    调用 AI 模型，使用 Tool Use 强制输出结构化 JSON
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = PRIMARY_SYSTEM_PROMPT

    user_message = f"""请按照以下规则从 SAP 文档中提取主要终点信息，并调用 extract_sap_data 工具输出结果。

# SAP 文档

{sap_content}

# 提取规则

{PRIMARY_EXTRACTION_RULES}"""

    log("调用 AI 模型进行结构化提取 (Tool Use 模式)...", "GEN")

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=2000)

    from scripts.ai_retry import call_ai_with_retry, has_tool_use

    def call_ai():
        return client.messages.create(
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_sap_data"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_sap_data")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_endpoints",
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_sap_data"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_sap_data":
            result = block.input
            # 处理 sub_analyses 可能是字符串的情况
            if isinstance(result.get("sub_analyses"), str):
                try:
                    result["sub_analyses"] = json.loads(result["sub_analyses"])
                except json.JSONDecodeError:
                    pass

            # 归一化方法名称
            result = _normalize_method_names(result)

            # 检查并修复 analysis_population
            result = _fix_analysis_population(result)

            log(f"  ✓ 提取完成", "GEN")
            return result
        elif block.type == "thinking":
            log(f"  思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 次要终点结构化提取 =====
def extract_secondary_endpoints(sap_content: str, api_logger: APILogger = None) -> dict:
    """
    调用 AI 模型，使用 Tool Use 强制输出结构化 JSON（次要终点）
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = SECONDARY_SYSTEM_PROMPT

    user_message = f"""请按照以下规则从 SAP 文档中提取次要终点信息，并调用 extract_secondary_endpoints 工具输出结果。

# SAP 文档

{sap_content}

# 提取规则

{SECONDARY_EXTRACTION_RULES}"""

    log("调用 AI 模型提取次要终点 (Tool Use 模式)...", "GEN")

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=2000)

    from scripts.ai_retry import call_ai_with_retry, has_tool_use

    def call_ai():
        return client.messages.create(
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            tools=[SECONDARY_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_secondary_endpoints"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_secondary_endpoints")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_secondary_endpoints",
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[SECONDARY_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_secondary_endpoints"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_secondary_endpoints":
            result = block.input
            # 处理 sub_analyses 可能是字符串的情况
            if isinstance(result.get("sub_analyses"), str):
                try:
                    result["sub_analyses"] = json.loads(result["sub_analyses"])
                except json.JSONDecodeError:
                    pass

            # 归一化方法名称
            result = _normalize_method_names(result)

            # 检查并修复 analysis_population
            result = _fix_analysis_population(result)

            log(f"  ✓ 提取完成", "GEN")
            return result
        elif block.type == "thinking":
            log(f"  思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 安全性终点结构化提取 =====
def extract_safety_endpoints(sap_content: str, api_logger: APILogger = None) -> dict:
    """
    调用 AI 模型，使用 Tool Use 强制输出结构化 JSON（安全性终点）
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = SAFETY_SYSTEM_PROMPT

    user_message = f"""请按照以下规则从 SAP 文档中提取安全性评价终点信息，并调用 extract_safety_endpoints 工具输出结果。

# SAP 文档

{sap_content}

# 提取规则

{SAFETY_EXTRACTION_RULES}"""

    log("调用 AI 模型提取安全性终点 (Tool Use 模式)...", "GEN")

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=2000)

    from scripts.ai_retry import call_ai_with_retry, has_tool_use

    def call_ai():
        return client.messages.create(
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            tools=[SAFETY_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_safety_endpoints"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_safety_endpoints")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_safety_endpoints",
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[SAFETY_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_safety_endpoints"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_safety_endpoints":
            result = block.input
            # 处理 sub_analyses 可能是字符串的情况
            if isinstance(result.get("sub_analyses"), str):
                try:
                    result["sub_analyses"] = json.loads(result["sub_analyses"])
                except json.JSONDecodeError:
                    pass

            log(f"  ✓ 提取完成", "GEN")
            return result
        elif block.type == "thinking":
            log(f"  思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 试验样本结构化提取 =====
def extract_sample_info(sap_content: str, api_logger: APILogger = None) -> dict:
    """
    调用 AI 模型，使用 Tool Use 强制输出结构化 JSON（试验样本）
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = SAMPLE_SYSTEM_PROMPT

    user_message = f"""请按照以下规则从 SAP 文档中提取试验样本信息，并调用 extract_sample_info 工具输出结果。

# SAP 文档

{sap_content}

# 提取规则

{SAMPLE_EXTRACTION_RULES}"""

    log("调用 AI 模型提取试验样本 (Tool Use 模式)...", "GEN")

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=2000)

    from scripts.ai_retry import call_ai_with_retry, has_tool_use

    def call_ai():
        return client.messages.create(
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            tools=[SAMPLE_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_sample_info"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_sample_info")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_sample_info",
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[SAMPLE_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_sample_info"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_sample_info":
            result = block.input
            log(f"  ✓ 提取完成", "GEN")
            return result
        elif block.type == "thinking":
            log(f"  思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 统计方法补充提取 =====
def extract_stat_methods(sap_content: str, api_logger: APILogger = None) -> dict:
    """
    调用 AI 模型，使用 Tool Use 强制输出结构化 JSON（统计方法补充）
    """
    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    system_prompt = STAT_METHODS_SYSTEM_PROMPT

    user_message = f"""请按照以下规则从 SAP 文档中提取统计方法补充信息，并调用 extract_stat_methods 工具输出结果。

# SAP 文档

{sap_content}

# 提取规则

{STAT_METHODS_EXTRACTION_RULES}"""

    log("调用 AI 模型提取统计方法补充 (Tool Use 模式)...", "GEN")

    messages = [{"role": "user", "content": user_message}]
    extra_body = get_thinking_config(budget_tokens=2000)

    from scripts.ai_retry import call_ai_with_retry, has_tool_use

    def call_ai():
        return client.messages.create(
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            tools=[STAT_METHODS_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_stat_methods"},
            extra_body=extra_body,
            messages=messages,
        )

    def validate(response):
        return has_tool_use(response, "extract_stat_methods")

    response = call_ai_with_retry(call_ai, validate, log_func=lambda msg: log(msg, "WARN"))

    # 记录 API 调用日志
    if api_logger:
        api_logger.log_call(
            func_name="extract_stat_methods",
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=[STAT_METHODS_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_stat_methods"},
            extra_body=extra_body,
            response=response,
        )

    # 从 tool_use 响应中提取 JSON
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_stat_methods":
            result = block.input
            log(f"  ✓ 提取完成", "GEN")
            return result
        elif block.type == "thinking":
            log(f"  思考过程: {block.thinking[:200]}...", "INFO")

    raise ValueError("未找到 tool_use 响应")


# ===== 表格名称生成 =====

# 出4张表的方法模板
ANCOVA_TABLES = [
    "{ep}-协方差分析（含交互项）（{pop}）",
    "{ep}-组间修正均数描述及比较（含交互项）（{pop}）",
    "{ep}-协方差分析（不含交互项）（{pop}）",
    "{ep}-组间修正均数描述及比较（不含交互项）（{pop}）",
]
MMRM_TABLES = [
    "{ep}-混合效应模型估计情况（{pop}）",      # P1
    "{ep}-最小二乘均数（{pop}）",              # P2
    "{ep}-重复测量的混合效应模型估计情况（含研究分组与随访交互效应）（{pop}）",  # 02_P1
    "{ep}-最小二乘均数（含组别与随访交互效应）（{pop}）",  # 02_P2
]
MMRM_TEMPLATE_CODES = ["P1", "P2", "02_P1", "02_P2"]

# 出1张表的方法
SINGLE_TABLE_METHODS = {
    "non_inferiority": "非劣效检验",
    "superiority": "优效性检验",
    "equivalence": "等效性检验",
    "logistic": "Logistic回归",
    "survival": "生存分析",
    "center_cmh": "中心效应CMH检验",
}


def generate_table_names(data: dict) -> List[Dict[str, Any]]:
    """
    根据 JSON 数据生成表格名称
    """
    result = []

    endpoints = data.get("endpoints", [])
    statistical_methods = data.get("statistical_methods", {})
    primary_analysis = statistical_methods.get("primary_analysis", {})
    method_flags = statistical_methods.get("method_flags", {})
    sub_analyses = data.get("sub_analyses", [])

    if not endpoints:
        log("未找到主要终点信息", "ERROR")
        return result

    populations = statistical_methods.get("analysis_population", ["文档未明确说明"])

    # 确保 populations 是列表
    if isinstance(populations, str):
        populations = [populations]

    category = "主要疗效终点分析"
    tables = []

    for endpoint in endpoints:
        endpoint_name = endpoint.get("name", "")

        # 主表
        for pop in populations:
            tables.append({"name": f"{endpoint_name}（{pop}）", "population": pop, "sub_type": ""})

        # 各中心表
        for pop in populations:
            tables.append({"name": f"各中心{endpoint_name}（{pop}）", "population": pop, "sub_type": ""})

        # 根据 mentions_* 生成描述统计表（目标值不单独出表）
        MENTION_TABLES = [
            ("mentions_mean", "均值"),
            ("mentions_median", "中位数"),
            ("mentions_rate_difference", "率差"),
            ("mentions_odds_ratio", "比值比"),
            ("mentions_rate_ratio", "率比"),
        ]
        for flag_key, label in MENTION_TABLES:
            if endpoint.get(flag_key):
                # 均值/率差/率比表：如果同时出现优效/非劣效/等效性检验，跳过
                if label in ("均值", "率差", "率比") and (method_flags.get("superiority") or method_flags.get("non_inferiority") or method_flags.get("equivalence")):
                    continue
                for pop in populations:
                    table_entry = {"name": f"{endpoint_name}-{label}（{pop}）", "population": pop, "sub_type": ""}
                    # 均值表：如果同时提到均值和目标值，加标记
                    if label == "均值" and endpoint.get("mentions_target"):
                        table_entry["has_mean_and_target"] = True
                    # 率差表：如果同时提到率差和目标值，加标记
                    if label == "率差" and endpoint.get("mentions_target"):
                        table_entry["has_rd_and_target"] = True
                    tables.append(table_entry)

        # 根据 method_flags 生成统计方法表
        if method_flags.get("ancova"):
            for tpl in ANCOVA_TABLES:
                for pop in populations:
                    tables.append({"name": tpl.format(ep=endpoint_name, pop=pop), "population": pop, "sub_type": ""})

        if method_flags.get("mmrm"):
            for tpl in MMRM_TABLES:
                for pop in populations:
                    tables.append({"name": tpl.format(ep=endpoint_name, pop=pop), "population": pop, "sub_type": ""})

        for flag_key, method_name in SINGLE_TABLE_METHODS.items():
            if method_flags.get(flag_key):
                for pop in populations:
                    tables.append({"name": f"{endpoint_name}-{method_name}（{pop}）", "population": pop, "sub_type": ""})

        # 子分析（按类型分组）
        grouped_subs = {}
        for sub in sub_analyses:
            sub_type = sub.get("type", "")
            if sub_type not in grouped_subs:
                grouped_subs[sub_type] = []
            grouped_subs[sub_type].append(sub)

        for sub_type in ["敏感性分析", "补充分析", "亚组分析", "探索性分析"]:
            if sub_type not in grouped_subs:
                continue

            subs = grouped_subs[sub_type]

            if sub_type == "亚组分析":
                for sub in subs:
                    sub_populations = sub.get("analysis_population", populations)
                    if isinstance(sub_populations, str):
                        sub_populations = [sub_populations]
                    subgroup_variables = sub.get("subgroup_variables", [])
                    for pop in sub_populations:
                        for var in subgroup_variables:
                            variable = var.get("variable", "")
                            groups = var.get("groups", [])
                            for group in groups:
                                table_name = f"亚组分析-{endpoint_name}-{variable}{group}（{pop}）"
                                tables.append({
                                    "name": table_name,
                                    "population": pop,
                                    "sub_type": sub_type,
                                    "variable": variable,
                                    "group": group
                                })
            else:
                for sub in subs:
                    sub_purpose = sub.get("purpose", "")
                    sub_populations = sub.get("analysis_population", populations)
                    if isinstance(sub_populations, str):
                        sub_populations = [sub_populations]
                    for pop in sub_populations:
                        table_name = f"{sub_type}-{endpoint_name}-{sub_purpose}（{pop}）"
                        tables.append({
                            "name": table_name,
                            "population": pop,
                            "sub_type": sub_type
                        })

    result.append({
        "category": category,
        "tables": tables
    })

    return result


# ===== 次要终点表格名称生成 =====
def generate_secondary_table_names(data: dict) -> List[Dict[str, Any]]:
    """
    根据次要终点 JSON 数据生成表格名称
    """
    result = []

    endpoints = data.get("endpoints", [])
    statistical_methods = data.get("statistical_methods", {})
    primary_analysis = statistical_methods.get("primary_analysis", {})
    method_flags = statistical_methods.get("method_flags", {})
    sub_analyses = data.get("sub_analyses", [])

    if not endpoints:
        log("未找到次要终点信息", "ERROR")
        return result

    # 次要终点共享同一套分析方法
    populations = statistical_methods.get("analysis_population", ["文档未明确说明"])

    # 确保 populations 是列表
    if isinstance(populations, str):
        populations = [populations]

    category = "次要疗效终点分析"
    tables = []

    # 为每个次要终点生成表格
    for endpoint in endpoints:
        endpoint_name = endpoint.get("name", "")

        for pop in populations:
            # 主表
            tables.append({"name": f"{endpoint_name}（{pop}）", "population": pop, "sub_type": ""})

            # 根据 mentions_* 生成描述统计表（目标值不单独出表）
            MENTION_TABLES = [
                ("mentions_mean", "均值"),
                ("mentions_median", "中位数"),
                ("mentions_rate_difference", "率差"),
                ("mentions_odds_ratio", "比值比"),
                ("mentions_rate_ratio", "率比"),
            ]
            for flag_key, label in MENTION_TABLES:
                if endpoint.get(flag_key):
                    # 均值/率差/率比表：如果同时出现优效/非劣效/等效性检验，跳过
                    if label in ("均值", "率差", "率比") and (method_flags.get("superiority") or method_flags.get("non_inferiority") or method_flags.get("equivalence")):
                        continue
                    table_entry = {"name": f"{endpoint_name}-{label}（{pop}）", "population": pop, "sub_type": ""}
                    # 均值表：如果同时提到均值和目标值，加标记
                    if label == "均值" and endpoint.get("mentions_target"):
                        table_entry["has_mean_and_target"] = True
                    # 率差表：如果同时提到率差和目标值，加标记
                    if label == "率差" and endpoint.get("mentions_target"):
                        table_entry["has_rd_and_target"] = True
                    tables.append(table_entry)

            # 根据 method_flags 生成统计方法表
            if method_flags.get("ancova"):
                for tpl in ANCOVA_TABLES:
                    tables.append({"name": tpl.format(ep=endpoint_name, pop=pop), "population": pop, "sub_type": ""})

            if method_flags.get("mmrm"):
                for tpl in MMRM_TABLES:
                    tables.append({"name": tpl.format(ep=endpoint_name, pop=pop), "population": pop, "sub_type": ""})

            for flag_key, method_name in SINGLE_TABLE_METHODS.items():
                if method_flags.get(flag_key):
                    tables.append({"name": f"{endpoint_name}-{method_name}（{pop}）", "population": pop, "sub_type": ""})

    result.append({
        "category": category,
        "tables": tables
    })

    return result


def format_table_output(table_data: List[Dict[str, Any]], format_type: str = "text") -> str:
    """格式化表格名称输出"""
    if format_type == "json":
        return json.dumps(table_data, ensure_ascii=False, indent=2)
    elif format_type == "csv":
        lines = ["序号,分类,子分类,表格名称,分析人群"]
        idx = 1
        for category_data in table_data:
            category = category_data["category"]
            for table in category_data["tables"]:
                name = table["name"]
                population = table.get("population", "")
                sub_type = table.get("sub_type", "")
                lines.append(f"{idx},{category},{sub_type},{name},{population}")
                idx += 1
        return "\n".join(lines)
    else:
        lines = []
        idx = 1
        for category_data in table_data:
            category = category_data["category"]
            lines.append(f"\n## {category}")
            lines.append("-" * 60)

            current_sub_type = None
            for table in category_data["tables"]:
                sub_type = table.get("sub_type", "")
                name = table["name"]

                if sub_type and sub_type != current_sub_type:
                    current_sub_type = sub_type
                    lines.append(f"\n### {sub_type}")

                lines.append(f"{idx}. {name}")
                idx += 1
        return "\n".join(lines)


# ===== 主函数 =====
def main():
    parser = argparse.ArgumentParser(
        description="SAP 文档结构化提取及表格名称生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 extract_and_generate.py
  python3 extract_and_generate.py --input 主要评价终点及分析方法.md
  python3 extract_and_generate.py --input doc.md --json-output result.json --table-output tables.txt
  python3 extract_and_generate.py --input doc.md --table-format csv --table-output tables.csv
        """,
    )
    parser.add_argument(
        "--input",
        default="主要评价终点及分析方法.md",
        help="输入文档路径 (默认: 主要评价终点及分析方法.md)",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="JSON 输出文件路径 (默认: 与 SAP 文件同名 .json)",
    )
    parser.add_argument(
        "--table-output",
        default=None,
        help="表格名称输出文件路径 (默认: 与 SAP 文件同名_表格名称.txt)",
    )
    parser.add_argument(
        "--table-format",
        choices=["text", "json", "csv"],
        default="text",
        help="表格名称输出格式 (默认: text)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="不保存文件，只输出到 stdout",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="保存 API 调用日志到指定目录",
    )

    args = parser.parse_args()

    # 设置默认输出路径
    sap_base = os.path.splitext(args.input)[0]
    if args.json_output is None:
        args.json_output = f"{sap_base}.json"
    if args.table_output is None:
        args.table_output = f"{sap_base}_表格名称.txt"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SAP 文档结构化提取及表格名称生成工具", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 初始化 API 日志记录器
    api_logger = APILogger(args.log_dir) if args.log_dir else None

    try:
        # 1. 读取输入文件
        sap_content = read_file(args.input)

        print(f"{'─'*60}", file=sys.stderr)

        # 2. 判断文档类型并提取
        is_safety = "安全" in args.input
        is_secondary = "次要" in args.input

        if is_safety:
            log("检测到安全性终点文档，使用安全性终点提取模式", "INFO")
            json_data = extract_safety_endpoints(sap_content, api_logger=api_logger)
        elif is_secondary:
            log("检测到次要终点文档，使用次要终点提取模式", "INFO")
            json_data = extract_secondary_endpoints(sap_content, api_logger=api_logger)
        else:
            log("检测到主要终点文档，使用主要终点提取模式", "INFO")
            json_data = extract_endpoints(sap_content, api_logger=api_logger)

        print(f"{'─'*60}", file=sys.stderr)

        # 3. 生成表格名称（安全性终点暂不生成表格）
        if is_safety:
            log("安全性终点：暂不生成表格名称", "INFO")
            table_data = None
        elif is_secondary:
            table_data = generate_secondary_table_names(json_data)
            total_tables = sum(len(cat["tables"]) for cat in table_data)
            log(f"生成 {len(table_data)} 个分类，共 {total_tables} 张表格", "TABLE")
        else:
            table_data = generate_table_names(json_data)
            total_tables = sum(len(cat["tables"]) for cat in table_data)
            log(f"生成 {len(table_data)} 个分类，共 {total_tables} 张表格", "TABLE")

        print(f"{'─'*60}", file=sys.stderr)

        # 4. 保存文件
        if not args.no_save:
            save_json(json_data, args.json_output)
            if table_data is not None:
                table_output = format_table_output(table_data, args.table_format)
                save_text(table_output, args.table_output)

        print(f"{'─'*60}", file=sys.stderr)

        # 5. 输出到 stdout
        print("\n=== JSON 提取结果 ===\n")
        print(json.dumps(json_data, ensure_ascii=False, indent=2))

        if table_data is not None:
            print("\n=== 表格名称 ===\n")
            print(format_table_output(table_data, args.table_format))

        if not args.no_save:
            if table_data is not None:
                log(f"完成！JSON: {args.json_output}，表格名称: {args.table_output}", "DONE")
            else:
                log(f"完成！JSON: {args.json_output}", "DONE")
        else:
            log("完成！", "DONE")

    except FileNotFoundError as e:
        log(str(e), "ERROR")
        sys.exit(1)
    except Exception as e:
        log(f"执行失败: {e}", "ERROR")
        raise


if __name__ == "__main__":
    main()
