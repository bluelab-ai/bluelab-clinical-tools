# protocol-to-dmp — 临床试验 DMP 初稿生成工具

基于临床试验方案（Protocol）和数据管理日志（DM Log），自动生成中文数据管理计划（DMP）初稿。

## 功能概述

- 根据 DM 日志自动选择匹配的 DMP Word 模板（随机系统 / 登记系统 / 无随机无登记）
- 从方案中提取试验关键信息，填入模板中所有非固定内容字段
- 对高风险字段（样本量、研究设计、终点、分析人群）进行语义审核修正
- 支持 few-shot 格式约束，确保输出风格与示例一致
- 保留模板中所有固定内容，不擅自改写、重排或增删
- 逐项询问未解决的字段，不批量堆砌、不编造数据

## 前置要求

```bash
pip install python-docx openpyxl
```

所有脚本使用 Python 3，通过标准库和上述两个依赖运行，不依赖 AI SDK。

## 文件结构

```
protocol-to-dmp/
├── SKILL.md                          # Claude Code skill 定义与完整工作流
├── README.md                         # 本文件
├── assets/
│   ├── DMP-随机系统.docx              # 使用随机系统的 DMP 模板
│   ├── DMP-登记系统.docx              # 使用登记系统（无随机）的 DMP 模板
│   ├── DMP-无随机无登记.docx          # 无随机无登记的 DMP 模板
│   ├── DMP非固定内容清单.xlsx         # 非固定内容字段清单与填写规则
│   └── fewshot.md                    # few-shot 格式示例
├── scripts/
│   ├── build_dmp_trace.py            # 解析方案 + DM 日志，构建证据 trace
│   ├── review_trace.py               # 组合式语义审核 + few-shot 格式约束（单次 prepare→review→apply）
│   ├── semantic_review.py            # 独立语义审核（仅需语义审核时使用）
│   ├── fewshot_format.py             # 独立 few-shot 格式约束（仅需格式约束时使用）
│   ├── apply_trace_to_template.py    # 将确认值填入 Word 模板生成初稿
│   └── update_dm_log.py              # 用户确认后更新 DM 日志最新条目
├── reference/
│   ├── chinese-dmp-generation.md     # 完整规则手册（14 节，权威参考）
│   └── confidence-scoring.md         # 证据提取置信度评分说明
├── example/
│   ├── dm 日志示例.json               # 示例 DM 日志
│   └── 临床试验方案_完全脱敏示例版.docx # 示例方案（脱敏）
├── input/
│   ├── dm日志测试数据示例1.json        # 测试用 DM 日志
│   └── 临床试验方案V1.4-...docx       # 测试用方案
└── 版本更新说明/
    ├── log.md                         # 更新日志
    └── image.png                      # 更新说明图片
```

## 核心流程

```
方案 (docx/pdf/txt)  +  DM 日志 (json/xlsx)
              │
              ▼
     build_dmp_trace.py        ← 选择模板、提取字段、构建证据 trace
              │
              ▼
     review_trace.py           ← 语义审核 + few-shot 格式（prepare → 人工审核 → apply）
              │
              ▼
     用户逐项确认              ← 高风险/冲突字段一对一确认
              │
              ▼
     apply_trace_to_template.py ← 填入模板，生成 DMP 初稿
              │
              ▼
     质量检查 + AI 审核披露     ← 最终 QA 与交付
```

## 快速开始

```bash
# 1. 构建证据 trace
python3 scripts/build_dmp_trace.py \
  --protocol 方案.docx \
  --dm-log dm-log.json \
  --template-dir assets \
  --checklist assets/DMP非固定内容清单.xlsx \
  --out dmp_trace.json \
  --questions dmp_questions.md \
  --protocol-dump protocol_dump.txt

# 2. 准备语义 + few-shot 审核上下文
python3 scripts/review_trace.py \
  --mode prepare \
  --trace dmp_trace.json \
  --protocol-text protocol_dump.txt \
  --fewshot assets/fewshot.md \
  --out review_input.json

# 3. 人工审核 review_input.json 后应用修正
python3 scripts/review_trace.py \
  --mode apply \
  --trace dmp_trace.json \
  --review review_input.json \
  --out dmp_trace.json

# 4. 用户确认后更新 DM 日志（可选）
python3 scripts/update_dm_log.py \
  --dm-log dm-log.json \
  --set "撰写人=张三" \
  --set "数据管理单位名称=XX公司"

# 5. 生成 DMP 初稿
python3 scripts/apply_trace_to_template.py \
  --trace dmp_trace.json \
  --out DMP初稿.docx \
  --report DMP生成报告.md
```

## 模板选择规则

| DM 日志 `是否使用随机系统` | DM 日志 `是否使用登记系统` | 选用模板 |
|---|---|---|
| 是 | 否 | `DMP-随机系统.docx` |
| 否 | 是 | `DMP-登记系统.docx` |
| 否 | 否 | `DMP-无随机无登记.docx` |
| 是 | 是 | ❌ 冲突，需用户澄清 |

## 设计原则

- **保守填写** — 只填有证据支持的字段，不确定的逐项询问，不编造
- **固定内容不动** — 模板中固定文字逐字保留，不润色、不总结、不重排
- **一站式输出** — 每条 checklist 行有完整 trace（来源、证据、置信度、状态）
- **AI 辅助而非替代** — 语义审核和格式约束为建议，高风险修正需人工确认
