# Phase 3 外部核查 · 详细说明

> **只在需要跑 Phase 3 时读本文档**——即用户上传了外部 `人群划分表.xlsx` 和/或 外部 `随机表.xlsx`。都没上传就直接进 Phase 4，本文档跳过。

**触发条件**：至少上传 1 个外部权威表（人群划分表 / 随机表）。

**核心思想**：外部表当权威 GT，用 subagent 核查 TFL 里 `人群划分表` / `病例分布表` / `入组病例表` 三类相关表的分中心 / 分析集 / 随机入组 / 剔除原因字段。

**产物**：
- `tables_output/external_ref.json`：`{by_center, by_analysis_set, randomization, exclusion_reasons}` —— subagent 用作 GT
- `qc_output/qc_ext_<编号>.json` + `qc_output/qc_ext_<编号>.md`：每张相关 TFL 表一份外部核查报告

---

## 1. 构建 external_ref.json

三种上传情形对应三条命令：

```bash
# 情形 A: 两个都上传（推荐）——脚本内部先按"筛选号"合并再聚合
python3 scripts/prepare_external_ref.py \
    --population    "<外部人群划分表.xlsx>" \
    --randomization "<外部随机表.xlsx>" \
    --out ./tables_output/external_ref.json

# 情形 B: 只上传人群划分表
python3 scripts/prepare_external_ref.py \
    --population "<外部人群划分表.xlsx>" \
    --out ./tables_output/external_ref.json

# 情形 C: 只上传随机表
python3 scripts/prepare_external_ref.py \
    --randomization "<外部随机表.xlsx>" \
    --out ./tables_output/external_ref.json
```

`prepare_external_ref.py` 会尽力抽 4 个字段；抽不到的字段留空（下游规则遇空自动跳过）：

| 情形 | 通常能抽 | 通常抽不到 |
|---|---|---|
| A（都有，合并） | 4 字段全齐 | — |
| B（仅人群划分） | `by_analysis_set` / `exclusion_reasons` | `by_center` / `randomization` |
| C（仅随机） | `by_center` / `randomization` | `by_analysis_set` / `exclusion_reasons` |

**约定**：外部 xlsx 键列固定叫"筛选号"（默认）。若列名不同，可用 `merge_by_key.py --key <列名>` 手动合并后再喂给 `prepare_external_ref.py`。

**多 sheet 兼容**：外部随机表常按中心分 sheet（"01中心" / "02中心" / …），脚本自动扫全部含"筛选号"的 sheet 并拼接。

---

## 2. dispatch subagent 核查相关 TFL 表

找出 `tables_output/` 里所有 `*-人群划分表-*.xlsx`、`*-病例分布表-*.xlsx`、`*-入组病例表-*.xlsx`。**每张一个 subagent**（一表一 subagent 铁律见 SKILL.md §5.1）。

Phase 3 subagent 提示模板（每张相关表一个 Task）：

```
你是一个临床试验方面的高级统计师，正在执行 **Phase 3 外部核查**——用外部权威数据核查本表分中心/人群相关字段。

## 本表信息
- 表型: <人群划分表 | 病例分布表 | 入组病例表>
- 表格文件: tables_output/<编号-类型-标题-分析集>.xlsx
- 规则文档: assets/<表型>.md（**只读 §2.4 "用外部参照的规则片段"这一段**）
- 外部参照: tables_output/external_ref.json

## 步骤
1. 加载 external_ref.json
2. 读 xlsx，定位分中心行 / 分析集列 / 剔除原因行等（这是你的语义工作）
3. 按 §2.4 代码模板跑 R-050~R-053（本表适用哪几条就跑哪几条；ext_ref 里没抽到的字段静默跳过）
4. 双产物：
   - JSON: `qc_output/qc_ext_<编号>.json`（Issues.to_json，table_type 用本表表型）
   - MD:   `qc_output/qc_ext_<编号>.md`（严格按 reference/subagent_output_template.md）

## 纪律
- 本阶段**只跑 R-050~R-053**——本表其他内部规则由 Phase 4/5 负责，不在这里重复
- external_ref 里没有的字段 → 静默跳过，不产 Finding，不算"通过"
- 数字对不上 → MAJOR；文本对不上（剔除原因措辞差异）→ MINOR
```

---

## 3. Phase 3 与 Phase 4/5 分工

| 步骤 | 输入 | 输出 | 范围 |
|---|---|---|---|
| Phase 3 | 外部 xlsx + TFL 里 3 类相关表 | `external_ref.json` + `qc_ext_*.json/md` | R-050~R-053（跨源核查） |
| Phase 4 | TFL 人群划分表 | `baseline.json` + `qc_<编号>.json/md` | 内部自一致性（R-020/031/合计） + 抽数 |
| Phase 5 | TFL 所有其他表 | `qc_<编号>.json/md` | 每张表内规则 + baseline 类规则 |

**Phase 4/5 subagent 不重跑 §2.4**——规则文档 §2.4 已在 Phase 3 处理，下游只跑 §2.2 / §2.3。

---

## 4. 常见坑

1. **`筛选号`键列缺失**：外部表若把键列叫"筛选编号"或"受试者编号"，`prepare_external_ref.py` 会报"未找到键列 '筛选号'"。修法：用 `merge_by_key.py --key <实际列名>` 先合并出中间 xlsx，再喂给 prepare_external_ref。
2. **多 sheet 表头不一致**：`merge_by_key.py` 自动模式假设各 sheet 表头一致；如果外部随机表有一个 sheet 表头列多了/少了 → stderr 告警并跳过该 sheet。可用 `--right-sheet <name>` 只读一个 sheet。
3. **中心号别名不齐**：external_ref 里键是 "01"，TFL 表里可能是 "1" 或 "中心 01"。subagent 应做前导零去除 + 前缀剥离归一，两侧都尝试。
4. **剔除原因文本措辞差异**：外部写"未收集到主要指标"，TFL 表写"主要指标缺失" → R-053 报 MINOR "外部有该文本，未匹配"。这是正常告警，请人工核对措辞。
5. **只有一个外部表时的静默跳过**：情形 B/C 下 subagent 会发现 external_ref 部分字段为空 → 对应规则**不产 Finding、不算通过**。总体报告"待人工"数不会增加。
