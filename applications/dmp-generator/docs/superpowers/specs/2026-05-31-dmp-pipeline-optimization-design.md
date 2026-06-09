# DMP 生成管线优化设计

## 目标

在局部重构范围内，优化 DMP 生成管线的执行时间、稳定性和输出质量，三者均衡。同时新增填充置信度评分体系，让用户能快速识别需人工审核的字段。

现状：单次生成 5-10 分钟，偶尔 AI 中途卡住无输出。模型 `deepseek-v4-pro`，预算 $30，超时 20 分钟。

## 关键发现：CLI vs API 语义审查质量对比

通过各 20 次基准测试对比两种语义审查方式（同一模型 deepseek-v4-pro）：

| 维度 | API 结构化输出 | CLI 逐字段 Edit |
|---|---|---|
| 自身一致性（同输入 20 次） | **78.1%** | **100%** |
| 主要终点字段一致性 | 42% | 100% |
| 其他终点字段一致性 | 47% | 100% |
| 平均耗时 | 58.4s | 64.0s |

**结论：CLI 的 tool-use roundtrip 不是纯开销，而是质量机制。** 逐字段 Edit 每次提供一个独立的「专注→决策→提交」认知循环，类似 Chain-of-Thought——分解步骤提高准确率。API 批量模式下注意力被稀释，边界模糊字段严重摇摆。

因此修正方案：**脚本前置到 backend 消除机械 tool-use，但语义审查保留在 CLI 确保质量一致性。**

## 架构变更

```
backend/start_dmp()
│
├─ Layer 1: 预处理（backend subprocess，无 AI 参与）
│   ├─ build_dmp_trace.py      ← 原阶段2，纯规则提取 + 初评置信度
│   └─ review_trace.py prepare  ← 原阶段3a，准备审查上下文
│
├─ Layer 2: Claude CLI（压缩 prompt，AI 判断步骤）
│   ├─ 阶段0: 读取规则
│   ├─ 阶段1: 模板选择 + 耦合字段检查
│   ├─ 阶段3b: 语义审查 + few-shot 审核（保留在 CLI，逐字段 Edit）
│   ├─ 阶段3c: review_trace.py apply
│   ├─ 阶段4: 交叉检查
│   ├─ 阶段6: 顺序确认门
│   ├─ 阶段7: 模板标记清理
│   └─ 阶段8: QA 检查（含低置信度项重点核查）
│
└─ Layer 3: 后处理（backend subprocess，无 AI 参与）
    ├─ apply_trace_to_template.py  ← 原阶段5，生成初稿 + 标注版
    └─ AI 披露生成                ← 原阶段9
```

阶段 2 和 3a 前置到 backend 消除机械 tool-use，阶段 3b 保留在 CLI 保证质量。

## Layer 1：预处理层（backend subprocess）

1. **build_dmp_trace.py** — 输出 dmp_trace.json + dmp_questions.md + protocol_dump.txt。**新增：为每个 trace item 计算置信度初评分。** 耗时 ~10-30 秒。失败则 SSE error 终止。
2. **review_trace.py --mode prepare** — 输出 review_input.json。耗时 ~2-5 秒。

## Layer 2：Claude CLI 层（压缩 prompt）

### Prompt 压缩

原 prompt ~280 行 → ~80-100 行，保留铁律、输出纪律、精简阶段指令（引用 SKILL.md）。

### 心跳机制

90 秒无输出 → keepalive SSE，连续 3 次 → kill + 报错。

## Layer 3：后处理层（backend subprocess）

1. **apply_trace_to_template.py** — 输入最终 dmp_trace.json，输出：

   - **DMP-初稿.docx**（常规生成版）
   - **DMP-初稿标注版.docx**（带置信度颜色标注 + 批注的审阅版）
   - **DMP生成报告.md**（含置信度汇总章节）

2. **AI 披露** — 扫描 trace 中 AI 修改项，生成披露文本。

---

## 置信度评分体系

### 评分维度（每项 0-100）

| 维度 | 含义 | 高分示例 | 低分示例 |
|---|---|---|---|
| extraction_accuracy | 提取准确性 | 方案编号从封面表格直接提取 → 95 | 样本量从长文本 regex 模糊匹配 → 55 |
| completeness | 完整性 | 统计分析人群列出 FAS+PPS+SS 三种 → 90 | 主要终点只抓到一个，遗漏 co-primary → 40 |
| hallucination_risk | 幻觉风险（反向） | 值来自 protocol 原文逐字引用 → 5 | few-shot 格式化添加了原文没有的句子 → 75 |
| overall_confidence | 综合分 | 加权平均 | — |

### 评分计算：两阶段

**阶段 A：提取时初评分（build_dmp_trace.py，规则驱动，不消耗 token）**

```
extraction_accuracy 初评：
  literal_table_extract: 95   直接字段映射: 90
  regex_extract: 70           keyword_extract: 50
  ai_semantic_extract: 40     default/empty: 10

completeness 初评：
  checklist 定义了 expected_subfields → 按覆盖率评分
  无子字段定义 → 根据值的长度/结构估算

hallucination_risk 初评：
  值有精确 evidence_snippet 对应 → 5
  多个 evidence 拼接 → 20
  AI 改写/总结 → 50
  few-shot 模板填充 → 40
  无 evidence → 95
```

**阶段 B：审查时调整分（阶段 3b，CLI 逐字段审查时同步完成）**

review_input.json 中每个 item 增加 confidence_adjustment 字段。CLI 在设置 review_decision 的同时调整置信度（不增加额外轮次）。例如：发现值来自不完整提取 → 降 completeness；确认值与原文精确匹配 → 升 extraction_accuracy。

### 置信度呈现

**DMP生成报告.md — 新增「填充置信度汇总」章节**

按综合分三档展示：
- ≥ 80 分（绿色/可信）：可直接使用
- 50-79 分（黄色/需审核）：建议人工核对
- < 50 分（红色/不可信）：必须人工修正

含低分项明细表：章节、字段、各维度评分、说明。

**DMP-初稿标注版.docx — 可视化标注**

- 绿色高亮 + Comment "置信度 85，直接引用自方案第3页" → overall ≥ 80
- 黄色高亮 + Comment "置信度 62，regex 提取，请核对完整性" → 50-79
- 红色高亮 + Comment "置信度 35，值来自 AI 推断，必须人工修正" → < 50

含置信度图例封面页。

---

## 预估收益

| 指标 | 现状 | 优化后 |
|---|---|---|
| 端到端耗时 | 5-10 分钟 | 3-5 分钟 |
| 语义审查稳定性 | — | 保持 CLI 100% 一致性 |
| Token 消耗 | 基线 | 降低 20-30%（机械步骤不再消耗 token） |
| 假死卡住 | 偶发 | 心跳主动 kill + 清晰报错 |
| 质量透明度 | 无 | 每项填充有三维置信度评分 |

## 文件变更清单

| 文件 | 改动 |
|---|---|
| `backend/app/services/dmp_orchestrator.py` | 新增 `_run_preprocess()`, `_run_postprocess()`；重构 `start_dmp()`；压缩 prompt；心跳机制 |
| `.claude/skills/protocol-to-dmp/scripts/build_dmp_trace.py` | 新增置信度初评逻辑 |
| `.claude/skills/protocol-to-dmp/scripts/review_trace.py` | 支持 confidence_adjustment 字段 |
| `.claude/skills/protocol-to-dmp/scripts/apply_trace_to_template.py` | 新增 `--annotated` 模式生成标注版 docx |
| `.claude/skills/protocol-to-dmp/SKILL.md` | 阶段 8 QA 清单增加低置信度项核查要求 |
| `backend/app/config.py` | 移除不再需要的 BATCH_REVIEW 配置项 |
| 前端 | 无需改动（SSE 格式不变） |

## 不在范围内

- API 结构化输出替代 CLI 语义审查（实验证明 CLI 质量更优）
- 方案 C 的增量重跑 + checkpoint
- 前端变更
