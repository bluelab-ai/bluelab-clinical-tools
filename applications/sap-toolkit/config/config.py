"""
SAP Toolkit 配置文件
===================
集中管理 API 密钥、模型配置等敏感信息。
"""

# API 配置
API_KEY = "tp-cuw69l6jpailrlau85thw2jr1w408lwk8jfwzx0xv8pinicc"
BASE_URL = "https://token-plan-cn.xiaomimimo.com/anthropic"

# 模型配置
MODEL = "mimo-v2.5"           # 普通任务模型（页面读取、目录判断）
MODEL_PRO = "mimo-v2.5-pro"   # 复杂任务模型（数据提取、分析）

# 思考模式配置
THINKING_ENABLED = True       # 是否开启思考模式
THINKING_BUDGET_TOKENS = 2000 # 思考模式token预算

def get_thinking_config(enabled: bool = None, budget_tokens: int = None) -> dict:
    """
    获取思考模式配置

    Args:
        enabled: 是否开启思考模式，默认使用全局配置
        budget_tokens: 思考模式token预算，默认使用全局配置

    Returns:
        思考模式配置字典
    """
    if enabled is None:
        enabled = THINKING_ENABLED
    if budget_tokens is None:
        budget_tokens = THINKING_BUDGET_TOKENS

    if enabled:
        return {
            'thinking': {
                'type': 'enabled',
                'budget_tokens': budget_tokens
            }
        }
    else:
        return {
            'thinking': {
                'type': 'disabled'
            }
        }

# 提取任务配置
EXTRACTION_TASKS = [
    {
        "name": "主要评价终点",
        "output_filename": "主要评价终点.md",
        "prompt": "请提取SAP文档中的主要评价终点（Primary Endpoints）内容，包括评价指标名称、定义、测量方法、统计分析方法等详细信息。"
    },
    {
        "name": "次要评价终点",
        "output_filename": "次要评价终点.md",
        "prompt": "请提取SAP文档中的次要评价终点（Secondary Endpoints）内容，包括评价指标名称、定义、测量方法、统计分析方法等详细信息。"
    },
    {
        "name": "安全性评价",
        "output_filename": "安全性评价终点.md",
        "prompt": "请提取SAP文档中的安全性评价（Safety Evaluation）内容，包括安全性指标、不良事件定义、安全性分析人群、安全性统计方法等详细信息。"
    },
    {
        "name": "统计分析计划",
        "output_filename": "试验流程.md",
        "prompt": "请提取SAP文档中的统计分析计划（Statistical Analysis Plan）内容，包括分析人群、统计方法、缺失数据处理、多重比较调整、期中分析等详细信息。同时提取试验流程和访视安排。"
    },
    {
        "name": "基线分析",
        "output_filename": "基线分析.md",
        "prompt": "请提取SAP文档中的基线分析（Baseline Analysis）章节内容，包括基线分析的指标、分析方法、分析人群等详细信息。"
    },
    {
        "name": "试验样本",
        "output_filename": "试验样本.md",
        "prompt": "请提取SAP文档中的试验样本信息，包括样本量计算（假设、效应量、检验效能、显著性水平、脱落率、计算公式）、随机化方法（类型、分配比例、分层因素、区组大小）、盲法设计（单盲/双盲/开放、设盲对象）、分组方法（各组名称和人数）等详细信息。"
    },
    {
        "name": "统计方法",
        "output_filename": "统计方法.md",
        "prompt": "请提取SAP文档中的统计方法信息，包括缺失值处理方法、一般统计方法（描述性分析、正态性检验、数据转换等）、多重性调整方法、期中分析计划、协变量选择、分析人群定义（FAS、PPS、mITT、SS等）等详细信息。"
    }
]
