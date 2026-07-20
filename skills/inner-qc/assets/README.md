# QC 规则文档（按表型拆分）

按 **7 种表型**各一个文档，每个文档自包含**两部分**：① 自然语言规则（要查什么）+ ② 代码模板（怎么写脚本）。用于 QC skill 的并行核查流程：

> **流程**（详见 ../SKILL.md 的 Phase 1–6）
> 1. **Phase 1** 把 TFL（docx/pdf）每张表提取成 xlsx；docx 模式同时写 `tables_meta.json`（标题 + 父节路径）。
> 2. **Phase 2** `classify_and_rename.py` 判型并推断分析集，重命名为 `编号-类型-标题-分析集.xlsx`。
> 3. **Phase 3（可选）** 外部核查：若上传外部人群划分表/随机表，`prepare_external_ref.py` 生成 `external_ref.json`；起 subagent 对 TFL 里 人群划分表/病例分布表/入组病例表 三类相关表跑 R-050~R-053（**仅** §2.4）→ 产 `qc_ext_<编号>.json/md`。未上传外部表 → 整个 Phase 3 跳过。
> 4. **Phase 4** 建 baseline：subagent 读 TFL 里"人群划分表" → 抽 `{分析集:{组:人数}}` 写 `tables_output/baseline.json`；同时跑该表的内部自一致性（R-020/R-031/合计=各组和）。
> 5. **Phase 5** 一表一 subagent 并行核查所有**其他表**（跳过 Phase 4 已处理的 人群划分表；病例分布表/入组病例表 subagent 跳过规则文档 §2.4）。
> 6. **Phase 6** `build_reports.py` 一站式：合并 `qc_*.json` 跑跨表规则 → `qc_output/总体QC报告.md` + 读 `qc_*.md`/xlsx → `qc_output/QC可视化报告.html`。

---

## 文件名"类型" → 规则文档 对照

文件名格式：`编号-类型-标题-分析集.xlsx`（分析集 ∈ {`FAS`, `ITT`, `mITT`, `PPS`, `SS`, `随机化人群`, `-`}）。分析集字段只写纯 acronym，不带"人群/集"后缀（如 `FAS人群` 是错的，`FAS` 才对）。

| 文件名里的类型 | 规则文档 | 主要规则 |
|---|---|---|
| `标准定性定量表` | [标准定性定量表.md](标准定性定量表.md) | R-006/007/016/017/025 + 基准类 |
| `事件表` | [事件表.md](事件表.md) | R-015 + 基准类 |
| `交叉表` | [交叉表.md](交叉表.md) | R-026 + 基准类 |
| `病例分布表` | [病例分布表.md](病例分布表.md) | R-010（Phase 5） + R-050/053（Phase 3） |
| `入组病例表` | [入组病例表.md](入组病例表.md) | R-017（Phase 5）+ R-009 + R-050/052（Phase 3） |
| `人群划分表` | [人群划分表.md](人群划分表.md) | R-020/031 + 合计自洽（Phase 4，同时抽 baseline）+ R-050/051/053（Phase 3） |
| `协方差` | [协方差表.md](协方差表.md) | 跳过数值核查，仅元数据 |

> 文件名类型字段即 `classify_and_rename.py` 的返回值，与文档名一致（`协方差`→`协方差表.md`）。
> `other`（未识别）：无对应文档，subagent 整表标"待人工"。
> 分析集字段由 `classify_and_rename.py` 自动推断；规则参见 ../SKILL.md 的"分析集字段"速查。分析集为 `-` 不再强制"待人工"——表题不含分析集说明是允许的。

---

## 每个文档的结构

```
对应类型：xxx
── 这类表是什么（一句话 + 例子）
一、自然语言规则
   · 本表内即可完成的规则（查什么 / 怎么算 / 怎么判）
   · 需要"人群划分表"基准的规则
   · 需要外部参照的规则（如有）
二、代码模板
   2.1 骨架（read_grid 读 xlsx + from qc_lib import 核查函数 + Issues 收集）
   2.2 本表规则核查片段
   2.3 需要基准的规则片段（如有）
   2.4 用 external_ref 的规则片段（如有；**Phase 3 专用**）
```
subagent 复制 2.1 骨架，再按当前阶段跑对应片段：Phase 3 只跑 §2.4；Phase 4/5 只跑 §2.2/§2.3。**算术一律调 `qc_lib`，不要眼算**。

---

## 两个约定

- **"人群划分表"是人数基准来源**：处理它的 subagent 要把抽出的 `FAS/PPS/SS × 各组人数` 写成基准 JSON（见 [人群划分表.md](人群划分表.md) §2.3），供其他 subagent（R-003/009/028/036）或合并阶段读取。
- **基准比对用"≤"不用"=="**：表内合计/表头N 与分析集人数比对时，只要"不超过"就算正常（子集表、亚组、妊娠检常见），只有**超过**才报错。唯一例外是 R-031 和 R-050~R-053（对外部权威表）要求精确相等。

## 外部参照（Phase 3 阶段规则）

若用户提供外部**人群划分表.xlsx** 和/或 **随机表.xlsx**，`prepare_external_ref.py` 会按"筛选号"合并（若两个都有）并聚合成 `tables_output/external_ref.json`：

```json
{
  "by_center": {
    "01": {
      "随机化人群": {"试验组": 15, "对照组": 10, "合计": 25},
      "FAS": {"试验组": 14, "对照组": 10, "合计": 24},
      "PPS": {"试验组": 13, "对照组": 10, "合计": 23},
      "SS":  {"试验组": 15, "对照组": 10, "合计": 25}
    },
    "02": {...},
    "合计": {"随机化人群":{...}, "FAS": {...}, "PPS": {...}, "SS": {...}}
  },
  "by_analysis_set":   {"FAS": {"试验组": 109, "对照组": 109, "合计": 218}, "PPS": {...}, "SS": {...}, "ITT": {...}, "mITT": {...}},
  "randomization":     {"total_screened": 244, "total_successful": 219, "total_failed": 25},
  "exclusion_reasons": {"未收集到主要指标": 4, "未使用试验器械": 1}
}
```

> `by_center` 按 `(中心, 分析集, 组别)` 三层嵌套：
> - `随机化人群` 槽 = 中心内每个筛选号一人（不过滤纳入/剔除），供入组病例表 / 病例分布表 R-050 使用
> - `FAS / PPS / SS / ITT / mITT` 槽 = 对应分析集列上被标"纳入"的受试者，剔除者不算
>
> 同时上传 population + randomization 时，合并后的宽表也会另存为 `external_merged.xlsx` 供人工回溯。

**Phase 3 subagent**（每张 人群划分表 / 病例分布表 / 入组病例表 一个）以此为权威基准跑：

- **R-050** 各中心的试验组/对照组/合计病例数一致（本表分析集 → `by_center[中心号][分析集]` 精确对比；本表若标"随机化人群"就查同名槽，标 `-` 则静默跳过）
- **R-051** 分析集人数一致（与 `by_analysis_set` 精确对比；人群划分表专用）
- **R-052** "随机入组"合计 = `randomization.total_successful`（入组病例表专用）
- **R-053** 剔除原因文本对应 `exclusion_reasons`（措辞不匹配 → MINOR）

外部参照没抽到的字段，对应规则自动静默跳过（不视为"通过"）。Phase 4/5 里这几张表的 subagent 不重复跑本节。

---

## 合并阶段的跨表规则（单表 subagent 做不了）

由 `../scripts/build_reports.py` 读取所有 `qc_*.json` 的 (表索引, 类型, 分析集, 合计N) 统一核查：

- **R-021 同一分析集跨表分母一致**：同一分析集的多张表，合计人数以人群划分表基准（或同集最大者）为准，比它小是子集表（正常），**大于基准才报**。
- **R-029 表号唯一**：全文档表索引不能重复。

---

## 相关文件

- 提取脚本：`../scripts/extract_tables.py`（docx，会同时写 `tables_meta.json`）/ `../scripts/extract_tables_pdf.py`（pdf）
- 表型分类脚本：`../scripts/classify_and_rename.py`（Phase 2 判型 + 推断分析集 + 重命名，自洽无外部依赖）
- Phase 3 外部核查脚本：
  - `../scripts/prepare_external_ref.py`（外部 人群划分表 [+ 随机表] → `external_ref.json`）
  - `../scripts/merge_by_key.py`（按共同键合并两 xlsx 的通用工具，`prepare_external_ref.py` 内部调用）
- 共享核查库：`../scripts/qc_lib.py`（所有 subagent import）
- Phase 6 脚本：`../scripts/build_reports.py`（一站式：跨表规则 + 总报告 + 单页 HTML 可视化报告）
- 总流程：`../SKILL.md`
