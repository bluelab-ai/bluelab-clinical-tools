---
name: inner-qc
description: Use when the user provides clinical trial table files (docx/pdf) and asks to QC them internally (表内一致性核查), classify tables by phenotype, or batch-validate table self-consistency (counts, percentages, N-values, metadata). Triggers on 内部QC, 表格QC, 表内核查, 表型分类, 规则QC, 临床表格质控.
---

# 内部 QC — 表格表内一致性核查

## Overview

六阶段流水线：

```
①提取 docx/pdf → 逐张 xlsx
②判型并重命名为「编号-类型-标题-分析集.xlsx」
③（可选）外部核查：若用户上传 人群划分表.xlsx 和/或 随机表.xlsx，
   构建 external_ref.json，起 subagent 用它核查 TFL 里的 人群划分表 / 病例分布表 / 入组病例表
   （跑 R-050~R-053）→ 产 qc_ext_<编号>.json + qc_ext_<编号>.md
   —— 用户未上传外部表 → 整个 Phase 3 跳过
④建 baseline：subagent 从 TFL 里的"人群划分表"抽 {分析集:{组:人数}} → baseline.json
   —— 同时跑本表内部自一致性（R-020 / R-031 / 合计=各组和）
⑤并行 subagent 核查所有其他表格（跳过 Phase 4 已处理的 人群划分表；
   病例分布表 / 入组病例表 subagent 跳过 §2.4 因为 Phase 3 已做过外部核查）
⑥合并：build_reports.py 一站式跑跨表规则(R-021/R-029) → 总体报告 + HTML 可视化报告
```

Core principle: **每张表的数据必须符合其表型对应的 QC 规则，数值自洽、元数据合规。算术核查交给代码（`qc_lib.py`），语义定位交给 subagent。**

## When to Use

- 用户提供临床试验表格 docx/pdf，要求内部 QC 或表内一致性核查
- 触发词：内部QC、表格QC、表内核查、表型分类、规则QC、临床表格质控、QC表格
- 用户想批量自动核查多张表，按表型分发不同规则

**Skip when:** 需与 listing 交叉核查（用 tfl-listing-cross-qc）、对照方案检查（用 protocol-tfl-qc）、或只提取表格不核查。


## 脚本与规则速查

| 资源 | 路径 | 用途 |
|------|------|------|
| `extract_tables.py` | `scripts/extract_tables.py` | docx → 逐张 xlsx + 顺便落盘 `tables_meta.json`（含父节路径） |
| `extract_tables_pdf.py` | `scripts/extract_tables_pdf.py` | pdf → 逐张 xlsx（跨页合并 + 质量分） |
| `classify_and_rename.py` | `scripts/classify_and_rename.py` | 判型 + 推断分析集 + 重命名为 `编号-类型-标题-分析集.xlsx`（自洽，无外部依赖） |
| `merge_by_key.py` | `scripts/merge_by_key.py` | 通用两表按共同键（默认"筛选号"）合并；自动识别多 sheet 并加追溯列 |
| `prepare_external_ref.py` | `scripts/prepare_external_ref.py` | 外部 人群划分表 [+ 随机表] → `external_ref.json`（含 by_center / by_analysis_set / randomization / exclusion_reasons），Phase 3 subagent 用它跑 R-050~R-053 |
| `qc_lib.py` | `scripts/qc_lib.py` | 共享确定性核查库，subagent import |
| `build_reports.py` | `scripts/build_reports.py` | Phase 6 一站式：合并 qc_*.json 跑跨表规则 → `总体QC报告.md` + 读 qc_*.md/xlsx → `QC可视化报告.html`（侧边栏 + 严重程度徽章 + 悬停预览 + 审查意见/原始表格切换） |

**类型 → 规则文档**（直接读取对应文档）：

| 文件名里的类型 | 规则文档 | 本表内规则 | 需基准的规则 |
|---|---|---|---|
| `标准定性定量表` | `assets/标准定性定量表.md` | R-006/007/016/017/025 | R-003/009/028/036 |
| `事件表` | `assets/事件表.md` | R-015 | R-009/028/036 |
| `交叉表` | `assets/交叉表.md` | R-026 | R-009/028/036 |
| `病例分布表` | `assets/病例分布表.md` | R-010 | R-050/053（Phase 3 外部核查） |
| `入组病例表` | `assets/入组病例表.md` | R-017（仅"随机入组"行/列） | R-009（随机化人群）、R-050/052（Phase 3 外部核查） |
| `人群划分表` | `assets/人群划分表.md` | 合计=各组和、R-020 | R-031（外部随机表）、R-050/051/053（Phase 3 外部核查）、抽 baseline（Phase 4） |
| `协方差` | `assets/协方差表.md` | 跳过数值，仅 CI 方向 | — |
| `other`（未识别） | 无 | — | 整表标"待人工" |

> 「偏离情况表」不再单列表型：方案偏离/重要偏离等表与基线/疗效表版式一致（项目+指标列、例数(缺失)、n(%)），统一按 `标准定性定量表` 判型与核查。

**分析集字段**（文件名最后一段，由 `classify_and_rename.py` 自动推断）：

| 取值 | 命中条件 |
|---|---|
| `随机化人群` | 表型 ∈ {人群划分表、病例分布表、入组病例表} |
| `FAS` / `ITT` / `mITT` / `PPS` / `SS` | 表题末尾括号（如`…（FAS）` `…（mITT）`）或父节标题括号（如`7.2 人口学信息和基线资料（ITT）`）——括号里允许出现"人群""集"等后缀（如`（ITT 人群）`），但**抽出后只保留纯 acronym** |
| `-` | 以上都没匹配到。**表题不含分析集说明不视为错误**，subagent 正常核查即可，无需"待人工" |

> **命名硬约束**：分析集字段只能是上述五个 acronym 之一、`随机化人群`、或 `-`——**禁止**写成 `FAS人群`、`ITT集`、`SS 人群` 这种带后缀的形式。`classify_and_rename.py` 已保证正确抽取；若手工重命名文件也须遵守。
> **ITT vs mITT 大小写敏感**：`mITT` 首字母小写、其余大写；`ITT` 全大写。regex 会保留原大小写，不要"矫正"成全大写。

## Phase 1: 提取表格

```bash
# docx
python3 scripts/extract_tables.py "<表格.docx>" --out ./tables_output
# 或 pdf
python3 scripts/extract_tables_pdf.py "<表格.pdf>" --out ./tables_output
```

输出 `tables_output/01-表 X.X.X 标题.xlsx` … `NN-…`，并在同目录写出 `tables_meta.json`（每张表的 `title` + `parents` 章节路径，仅 docx 模式）。该 meta 供 Phase 2 推断分析集时使用——pdf 模式暂无父节路径，未带括号的表只能落到 `-`。

> docx 合并单元格会被 python-docx 重复填充到每个被合并的格子里——读表时遇到表头重复值属正常，按内容去重判断分组。

## Phase 2: 表型分类与重命名

```bash
python3 scripts/classify_and_rename.py ./tables_output
```

文件名变为 `编号-类型-标题-分析集.xlsx`。七种表型 + `other`；分析集来自表型固定值 / 表题括号 / 父节括号（顺序见上节"分析集字段"速查）。

> **盯住 `other`**：类型为 `other` 的表没有匹配规则 → Phase 5 必须单独标"待人工"，不能漏。
> 分析集为 `-` 不视为问题（表题/父节未声明分析集是允许的），subagent 按现有数据正常核查。
> 把分类统计 + 分析集分布贴给用户确认。

## Phase 3（可选）: 外部核查

用户上传了外部 `人群划分表.xlsx` 和/或 外部 `随机表.xlsx` → 用它们对 TFL 里 `人群划分表` / `病例分布表` / `入组病例表` 三类相关表跑 R-050~R-053，产出 `qc_ext_<编号>.json/md`。
**没上传外部表 → 整个 Phase 3 跳过**，直接进 Phase 4。

要跑 Phase 3 时，**先完整读** [reference/phase3_external_qc.md](reference/phase3_external_qc.md)，里面有：3 种上传情形的 `prepare_external_ref.py` 命令、字段覆盖策略、subagent 提示模板、Phase 3 与 Phase 4/5 分工、常见坑。

## Phase 4: 建 baseline（subagent 抽 TFL 人群划分表）

Phase 5 里绝大多数表都需要 baseline `{分析集:{组:人数}}` 做核查。**baseline 来自 TFL 内的"人群划分表"**（不再依赖外部）。

### 4.1 dispatch

找出 `tables_output/*-人群划分表-*.xlsx`（一般 1 张）：
- **有** → 起一个 subagent（**只此一个**）
- **无** → `baseline.json` 缺席；Phase 5 的基准类规则（R-003/009/028/036）静默跳过，留合并阶段或人工

### 4.2 Phase 4 subagent 提示模板

```
你是一个临床试验方面的高级统计师，正在执行 **Phase 4：抽取 baseline + 人群划分表自一致性核查**。

## 本表信息
- 表型: 人群划分表
- 表格文件: tables_output/<编号-人群划分表-标题-分析集>.xlsx
- 规则文档: assets/人群划分表.md（**只读 §2.1 骨架 + §2.2 本表规则 + §2.3 写基准；§2.4 已在 Phase 3 处理，本阶段跳过**）

## 步骤
1. grid = qc_lib.read_grid(xlsx)；语义定位表头、分组、分析集
2. 按 §2.2 跑：合计=各组和、R-020 分析集边界、R-031 与外部随机表/决议一致（若 ref 存在）
3. 抽出 pop = {"FAS":{"试验组":..,"对照组":..,"合计":..}, "PPS":{...}, "SS":{...}, ...}
4. 按 §2.3 写 `tables_output/baseline.json`（若已存在则**不覆盖**，只做一致性告警）
5. 双产物：
   - JSON: `qc_output/qc_<编号>.json`
   - MD:   `qc_output/qc_<编号>.md`

## 纪律
- 与 Phase 3 边界：R-050~R-053 已由 Phase 3 处理，**本阶段不重复**
- baseline.json 已存在（Phase 3 情形 A 会顺手产出）→ 尊重原值，只对比、不覆写
- 数字算术用 qc_lib，不要眼算
```

### 4.3 baseline.json 结构（供 Phase 5 与合并阶段用）

```json
{
  "FAS":  {"试验组": 109, "对照组": 109, "合计": 218},
  "PPS":  {"试验组": 107, "对照组": 107, "合计": 214},
  "SS":   {"试验组": 109, "对照组": 109, "合计": 218},
  "ITT":  {...},
  "mITT": {...}
}
```

## Phase 5: 逐表 QC（一表一 subagent，并行）

> 这里的"并行"指**同时跑 N 个各自只管一张表的 subagent**，不是"一个脚本/一个 subagent 批处理多张表"。下面 5.1 是本阶段最容易被效率理由架空的硬规则，先读它。

### 5.1 一表一 subagent（硬性规则，不可合并）

**铁律：表数 N → 恰好 N 个 subagent（N 次 Task 调用），每个 Task 的 prompt 里有且仅有一张表。**
开 Phase 5 前先数出待核查表数 N（`tables_output` 里的 xlsx，**减去** Phase 4 已处理的"人群划分表"）；收尾时 `qc_output` 应有 N 套新产物（含 Phase 3/4 的产物合起来才是完整集合）。**N 对不上就是没做对，回来补齐，不能进 Phase 6。**

根据 `classify_and_rename.py` 输出的文件名，每个 subagent 读对应表型规则文档，独立核查它那一张表（表内一致性 + 基准比对 + 元数据）。

**为什么必须逐表（别用效率理由覆盖这条）：**
- 每个subagent必须解析Excel文件、编写python解析代码、生成报告——所有这些都保留在上下文中。每个表格的表头位置、分组方式、数据区范围都可能不同，通用解析逻辑无法保证在多张表上都正确。一对一的subagent可以专注于一张表，确保解析和核查的准确性和上下文的有界。

**禁止——以下是本阶段最常见的"自作聪明"，出现任一即判违规：**
- ❌ 写一个脚本 `for` 循环遍历多张表统一核查。通用解析逻辑靠正则/启发式定位表头，遇到结构变体（子组嵌套、多层级分类）必漏检或误判。
- ❌ 一个 subagent / 一个 Task 里塞多张表。
- ❌ 借口"表结构相似"复用同一套解析逻辑跨表批处理。

### 5.2 每个 subagent 的标准提示

```
你是一个临床试验方面的高级统计师，你要对此表格进行内部 QC（表内一致性核查）。

## 本表信息
- 表型: <类型>
- 分析集: <FAS|ITT|mITT|PPS|SS|随机化人群|->（取自文件名末段，与表题/父节括号一致；只填纯 acronym，不带"人群/集"后缀）
- 规则文档: assets/<类型>.md
- 共享库: scripts/qc_lib.py
- 人数基准: tables_output/baseline.json（存在则加载，用于 R-003/009/028/036）
- 表格文件: tables_output/<编号-类型-标题-分析集>.xlsx

## 步骤（每张表）
1. 先完整读 assets/<类型>.md，理解 自然语言规则 + 代码模板
2. grid = qc_lib.read_grid(xlsx)；定位表头/分组/数据区（这是你的语义工作）
3. 参考规则文档 §二 代码模板，结合本表实际表头位置编写完整 QC 脚本（python 文件或内联），再用 Bash 执行
4. 双产物（同一轮内完成）：
   - **机器读 JSON**：`iss.to_json(f"qc_output/qc_{IDX}.json")` —— 供 Phase 6 `build_reports.py` 跨表合并
   - **人读 markdown**：严格按 `reference/subagent_output_template.md` 模板用 write 工具写到 `qc_output/qc_{IDX}.md`

## 纪律
- 缺数据/N=0/取不到值 → 静默跳过，不产 Finding（不是"通过"）
- 判不了但疑似异常 → level="待人工"
- 表型为 `other` → 至少产一条 level="待人工"
- 分析集为 `-` 不视为问题，按数据照常核查
- **不要基于表名/表题关键词判断"疗效表 vs 安全性/AE 表"，也不要据此对分析集（FAS/ITT/mITT/PPS/SS）合不合规下结论**——原 R-030 已删除，当前规则库无此维度。文件名声明的分析集是什么就按什么核查，不要自造"疗效表却用了 SS"这类质疑
- **Phase 边界**：本表若是 `病例分布表` 或 `入组病例表`，规则文档 §2.4（外部参照类 R-050~R-053）已在 Phase 3 处理，本阶段**跳过 §2.4**，只跑 §2.2 / §2.3
```

### 5.3 内联的两类通用核查

每个 subagent 在本表规则之外，统一补这类（baseline 存在时）：

**N 值一致性**：表头各组 N、表内合计，应等于 baseline 里该分析集对应人数（`check_le`）。

**表格元数据/表题合规**：
- R-028 表题分析集下的本表合计超过基准（> `baseline[表题集]["合计"]`）→ MAJOR；相等或子集不报。
- R-036 表头出现的 FAS/ITT/mITT/PPS/SS 必须 ⊆ 表题声明的分析集 → 否则 MAJOR。



**分级标准**（与 json 的 level 对齐）：

| 级别 | 定义 | 示例 |
|------|------|------|
| Critical | 可能影响主要/安全性结论 | N值严重矛盾、主要终点不可复现 |
| Major | 影响报告质量或可追溯性 | 表题分析集与分母不一致、Σn≠N、%≠n/N |
| Minor | 格式/脚注/编码/表号 | N标注不统一、表号引用错误 |
| Suggestion | 非错误，建议改进 | 补脚注、措辞统一 |

**禁止**：META_CONCLUSION 取 PASS 却列了问题；PASS 表只写"未发现问题"不搬原表；用独立清单代替原表标注；原表结构与原始不一致。

### 5.4 输出报告格式

每个subagent必须严格按照reference/subagent_output_template.md输出。

关键硬性要求：

1. 文件前面必须有4行metadata：
```
##META_TABLE: <表格完整标题>
##META_TYPE: <表型>
##META_ANALYSIS_SET: <FAS|ITT|mITT|PPS|SS|随机化人群|->
##META_CONCLUSION: PASS|CRITICAL|MAJOR|MINOR|SUGGESTION
```
   `##META_ANALYSIS_SET` 取值与文件名末段一致；文件名为 `-` 时此处也填 `-`，不再强制产"待人工"。

2. 报告核查出现的问题
3. 完整的模板和反例见：reference/subagent_output_template.md


## Phase 6: 合并报告

进入条件：Phase 3（若跑了）+ Phase 4 + Phase 5 的所有 subagent 都已完成。`qc_output/` 里应有：
- `qc_ext_<编号>.json/md`（Phase 3 产出，若外部核查跑了）
- `qc_<编号>.json/md`（Phase 4/5 产出，覆盖所有 TFL 表）

**一条命令产两份报告**（原 merge_qc + build_report_viewer 已合成 `build_reports.py`）：

```bash
python3 scripts/build_reports.py ./qc_output \
    --tables-dir ./tables_output \
    --baseline   ./tables_output/baseline.json \
    --source     "<原始docx/pdf文件名>"
# 默认输出：./qc_output/总体QC报告.md + ./qc_output/QC可视化报告.html
# 可覆盖：--md-out <path> / --html-out <path> / --project-name <名字>
```

**Markdown 总报告**（读所有 `qc_*.json`，含 `qc_ext_*.json`）：
- **R-029 表号唯一**：全文档表号重复 → MINOR
- **R-021 同一分析集跨表分母一致**：任一表合计 > baseline 该分析集人数 → MAJOR（小于属子集，正常）
- 报告含：概要（结论分布/表型分布/问题数/待人工数）、按表格汇总、按级别归并的问题清单、待人工复核、已通过列表

**HTML 可视化报告**（读所有 `qc_*.md` + 原表 xlsx）：
- 按 `qc_<编号>.md` 与 `tables_output/<编号>-*.xlsx` 的前导编号配对
- 优先用同名 `qc_<编号>.json` 拿 `conclusion`/`pending` 作严重度归类（MAJOR > pending>0 待人工 > PASS 核查无误 > 未核查）
- 单页自包含：左侧搜索筛选、悬停预览、点击固定、顶部切换"审查意见 ↔ 原始表格"

> 依赖：`openpyxl`（已有）+ `markdown`（`pip install markdown`，Phase 6 需要）。

## Common Pitfalls

1. **先 classify_and_rename 再分发**：dispatch 依赖文件名里的类型字段和分析集字段。
2. **Phase 3 是可选、Phase 4 是必需**：
   - Phase 3 仅当用户上传外部 人群划分表 / 随机表 时才跑（`prepare_external_ref.py` + subagent 跑 R-050~R-053）；未上传就整段跳过——静默不是"通过"。
   - Phase 4 是唯一 baseline 来源（subagent 从 TFL 内"人群划分表"抽）。若 TFL 也没有人群划分表 → baseline 缺席，Phase 5 的基准类规则（R-003/009/028/036）静默跳过，留合并阶段或人工。
3. **阶段边界不重复**：Phase 3 subagent 只跑规则文档 §2.4（R-050~R-053）；Phase 4/5 subagent 跳过 §2.4。
4. **读表用 `qc_lib.read_grid`，不要照抄规则文档历史遗留的 `pd.read_csv`**：实际是 xlsx（文档已回填为 import）。
5. **算术用 `qc_lib`，不要 LLM 眼算**：求和/百分比/次序统一调函数。
6. **基准比对用 ≤**：PPS⊂FAS、亚组、妊娠检、基线化验分母更小都正常；只有**超过**才报。
7. **SOC-PT 去重**：SOC 人数 ≤ ΣPT 是 MedDRA 正常行为，不是错误。
8. **缺数据静默跳过 ≠ 通过**：N=0/取不到值不产 Finding；判不了但疑似异常才标"待人工"。
9. **盯住 `other`**：无规则可跑，必须显式"待人工"，别让它悄悄变成 PASS。分析集 `-` 不在此列——表题不声明分析集是允许的，按现有数据正常核查。
10. **pdf 模式没有父节路径**：`extract_tables_pdf.py` 暂不输出 `tables_meta.json`，未带括号的表题分析集只能取 `-`，需人工补。
11. **分析集字段只写纯 acronym**：手工重命名文件时也必须只写 `FAS`/`ITT`/`mITT`/`PPS`/`SS`，不可写成 `FAS人群`/`ITT集`——文件名末段是 dispatch 的解析源，带后缀会破坏后续脚本匹配。
12. **一表一 subagent，禁止合并批处理**：N 张表必须 N 个 Task，每个 Task 只管一张表。不许写脚本 `for` 循环跨表核查、不许一个 subagent 塞多张表——通用解析逻辑遇结构变体会漏检/误判（曾刷出 R-025 假阳性）。详见 Phase 5.1。
