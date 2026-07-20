---
name: subagent-output-template
description: 所有 QC subagent 必须严格遵循的输出模板，供 merge_qc.py 确定性解析
---

# Subagent QC 输出模板（v3.0 — 四级问题分级）

**每个 subagent 必须严格按照此模板输出，不得增删或移动元数据行。**

---

## 输出文件格式

```
##META_TABLE: <表格名称>
##META_CONCLUSION: PASS|CRITICAL|MAJOR|MINOR|SUGGESTION
##META_LISTING: <清单名称>|<清单人群>

### <表格名称>

| 参考清单 | 清单人群 |
|----------|----------|
| <清单名称> | <清单人群> |

## 发现的问题

| 编号 | 分级 | 问题描述 | 说明 |
|------|------|----------|------|
| 1 | Major | 分析集不一致 | Table标注FAS(N=15)，Listing为SS(N=15)，虽人数一致但标注不同 |
| 2 | Minor | 表头N格式 | ... |
| ... | ... | ... | ... |

（若未发现任何问题，此行写"**未发现问题**"）

## 核查详情

<仅描述与问题相关的具体数值和受试者编号。无问题则写"无。">
```

---

## 严格规则

### 1. 元数据行（必须放在文件最前面，每行独立，不可省略）

```
##META_TABLE: 人口学信息（FAS）
##META_CONCLUSION: MAJOR
##META_LISTING: 人口学信息清单（FAS）|FAS
```

- `##META_TABLE:` 后直接跟表格名称，与映射表中的名称完全一致
- `##META_CONCLUSION:` 后只能是 `PASS`、`CRITICAL`、`MAJOR`、`MINOR`、`SUGGESTION` 之一，不能带任何后缀
  - `PASS` = 未发现任何问题
  - `CRITICAL`/`MAJOR`/`MINOR`/`SUGGESTION` = 取所有发现问题的**最高级别**
- `##META_LISTING:` 后跟 `清单名称|清单人群`，多个清单用 `||` 分隔
- 元数据行之间不能有空行，必须连续放在文件最开头

### 2. 问题分级标准

| 级别 | 定义 | 示例 |
|------|------|------|
| **Critical** | 可能影响主要结论、分析集、主要终点、安全性结论或监管判断 | 主要终点人数无法从Listing反推；P值和结论不一致；SS归组错误；死亡人数前后不一致 |
| **Major** | 可能影响报告质量、可追溯性或审评理解，但不一定直接改变结论 | SAP预设敏感性分析未报告；Table无对应Listing；表题分析集与分母不一致；人群划分与Listing不符 |
| **Minor** | 格式、表号、脚注、版本、编码等问题 | 表号引用错误；表名重复；N标注格式不统一；百分比四舍五入不一致（≤0.2%） |
| **Suggestion** | 不构成错误，但建议改得更清楚 | 补充特殊受试者脚注；建议补充缺失清单；措辞统一建议 |

### 3. 只报告问题

- 没有问题的 pair 只需写 `##META_CONCLUSION: PASS` 和简短 "未发现问题"，无需逐项罗列通过的检查
- 有问题的 pair 列出所有发现的问题，每行标注级别，META_CONCLUSION 取最高级别
- 说明列必须包含具体数值（Table=X, Listing=Y）

### 4. 反例（禁止出现）

```
❌ 综合结论: **PASS**
❌ **结论**: FAIL — 总例次数不一致
❌ 结论行缺失
❌ 元数据行不在文件最开头
❌ ##META_CONCLUSION: FAIL — 有差异   （应为 FAIL）
❌ ##META_CONCLUSION: WARNING          （应为 WARN）
❌ ##META_CONCLUSION: WARN             （旧格式，已废弃）
❌ META_CONCLUSION 取 PASS 但问题表列出了问题
❌ 问题表缺少"分级"列
❌ PASS 的 pair 罗列了所有通过的检查项
```
