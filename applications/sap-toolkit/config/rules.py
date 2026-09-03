"""
SAP Toolkit 规则配置
===================
集中管理方法名映射、出表规则、提取任务等可配置内容。
"""

# ===== 方法名映射表 =====
# 统计方法的标准名称和变体写法
METHOD_NAME_MAPPING = {
    "协方差分析": ["ANCOVA", "协方差分析", "Analysis of Covariance"],
    "混合效应模型重复测量": ["MMRM", "混合效应模型", "Mixed Model Repeated Measures"],
    "优效性检验": ["优效性检验", "Superiority Test"],
    "非劣效检验": ["非劣效检验", "Non-inferiority Test"],
    "等效性检验": ["等效性检验", "Equivalence Test"],
    "Logistic回归": ["Logistic回归", "Logistic Regression", "逻辑回归"],
    "Cox回归": ["Cox回归", "Cox Regression", "Cox比例风险模型"],
    "生存分析": ["生存分析", "Survival Analysis"],
    "Kaplan-Meier法": ["Kaplan-Meier法", "KM法", "K-M法"],
    "t检验": ["t检验", "t-test", "Student's t检验"],
    "卡方检验": ["卡方检验", "Chi-square Test", "χ²检验"],
    "CMH检验": ["CMH检验", "CMH", "Cochran-Mantel-Haenszel", "Cochran-Mantel-Haenszel检验"],
    "中心效应CMH检验": ["中心效应CMH检验", "中心效应CMH", "中心校正CMH", "stratified CMH"],
    "Fisher精确检验": ["Fisher精确检验", "Fisher's Exact Test"],
    "Wilcoxon检验": ["Wilcoxon检验", "Wilcoxon Rank Sum Test"],
    "Mann-Whitney U检验": ["Mann-Whitney U检验", "Mann-Whitney Test"],
    "描述性分析": ["描述性分析", "Descriptive Analysis"],
    "方差分析": ["方差分析", "ANOVA", "Analysis of Variance"],
    "重复测量方差分析": ["重复测量方差分析", "Repeated Measures ANOVA"],
    "广义估计方程": ["广义估计方程", "GEE", "Generalized Estimating Equations"],
    "广义线性模型": ["广义线性模型", "GLM", "Generalized Linear Model"],
    "多重比较": ["多重比较", "Multiple Comparisons"],
}


# ===== 出表类型规则 =====
# 定义不同统计方法的出表类型和数量

# 协方差分析 → 出4张表
ANCOVA_METHODS = ["协方差分析"]

# 混合效应模型 → 出4张表
MMRM_METHODS = ["混合效应模型重复测量"]

# 需要单独出表的方法 → 1张表
SINGLE_TABLE_METHODS = [
    "优效性检验", "非劣效检验", "等效性检验",
    "Logistic回归", "生存分析", "中心效应CMH检验",
]

# 不需要单独出表的方法（Cox回归、Kaplan-Meier、普通CMH等）
NONE_TABLE_METHODS = ["Cox回归", "Kaplan-Meier法", "CMH检验"]


def classify_table_type(method_name: str) -> str:
    """
    根据统计方法名称判断出表类型。

    返回值:
        "ancova"  - 协方差分析，出4张表
        "mmrm"    - 混合效应模型，出4张表
        "single"  - 需要单独出表的方法，出1张表
        "none"    - 不需要单独出表
    """
    name = method_name.strip()

    # 协方差分析
    if name in ANCOVA_METHODS:
        return "ancova"

    # 混合效应模型
    if name in MMRM_METHODS:
        return "mmrm"

    # 需要单独出表的方法
    if name in SINGLE_TABLE_METHODS:
        return "single"

    # 不需要单独出表
    return "none"


def normalize_method_name(name: str) -> str:
    """
    归一化统计方法名称

    将各种表述统一为标准名称。如果找不到映射，返回原文。
    """
    if not name:
        return name

    name_lower = name.lower().strip()

    for standard_name, variants in METHOD_NAME_MAPPING.items():
        for variant in variants:
            if variant.lower() == name_lower:
                return standard_name

    # 没有找到映射，返回原文
    return name


# ===== 提取任务定义 =====
# sap_workflow.py 使用的任务列表

EXTRACTION_TASKS = [
    {
        "name": "主要评价终点",
        "prompt": "提取主要评价终点的内容及其分析方法，写成md文件给我,标注来源，保持原文不要改动",
        "output_filename": "主要评价终点.md",
    },
    {
        "name": "次要评价终点",
        "prompt": "提取次要评价终点的内容及其分析方法，写成md文件给我,标注来源，保持原文不要改动",
        "output_filename": "次要评价终点.md",
    },
    {
        "name": "安全性评价",
        "prompt": "提取安全性评价终点的内容及其分析方法，写成md文件给我,标注来源，保持原文不要改动",
        "output_filename": "安全性评价终点.md",
    },
    {
        "name": "统计分析计划",
        "prompt": "提取试验流程内容，写成md文件给我,标注来源，保持原文不要改动",
        "output_filename": "试验流程.md",
    },
    {
        "name": "基线分析",
        "prompt": "提取基线分析章节内容，包括基线分析的指标、分析方法、分析人群等，写成md文件给我,标注来源，保持原文不要改动",
        "output_filename": "基线分析.md",
    },
    {
        "name": "试验样本",
        "prompt": "提取试验样本相关内容，包括样本量计算、随机化方法、盲法、分组方法等，写成md文件给我,标注来源，保持原文不要改动",
        "output_filename": "试验样本.md",
    },
    {
        "name": "统计方法",
        "prompt": "提取主次要终点和安全性评价之外的统计方法内容，包括缺失值处理、一般统计方法、多重性调整、期中分析等，写成md文件给我,标注来源，保持原文不要改动",
        "output_filename": "统计方法.md",
    },
]
