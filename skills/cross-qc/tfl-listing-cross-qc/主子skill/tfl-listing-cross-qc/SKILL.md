---
name: tfl-listing-cross-qc
description: Use when the user provides clinical trial TFL (Tables/Figures/Listings) files in docx or PDF format and asks to QC them, verify tables against listings, check analysis set consistency, audit subject counts, or cross-validate AE/SAE/lab data. Triggers on: TFL QC, 表格清单核查, 临床试验质控, table listing cross-check, AE SAE一致性, 分析集核对, listing反推, 反向核查.
---

# TFL-Listing Cross-Validation QC

## Overview

Three-phase pipeline: match tables→listings (keyword→cosine→DeepSeek), extract tables to Excel files, then batch-QC every keyword-matched pair by reverse-deriving Table numbers from Listing records.

Core principle: **Every count, event, and percentage in a Table must be reproducible from the corresponding Listing.**

## When to Use

- User provides `.docx`/`.pdf` TFL files and asks for QC, cross-validation, or consistency checks
- User mentions: 表格清单QC, TFL核查, listing反推, AE/SAE一致性, 分析集核对, 反向核查
- User wants automated batch QC of many table-listing pairs

**Skip when:** only a single pair needs QC (use subagent template directly), files already matched+extracted (start at Phase 3), or user only wants format conversion.

## Quick Reference

| Phase | What | Key Command |
|-------|------|-------------|
| 1. 匹配 | Keyword-first matching + DeepSeek fallback | `match_tables_listings.py` (docx) / `match_tables_listings_pdf.py` (PDF) → `deepseek_match.py --retry` |
| 1b. 复核 | Interactive HTML review page for manual correction | Subagent generates `映射复核.html` |
| 2. 提取 | Extract tables from docx → Excel files with titles | `extract_tables.py <表格.docx> <清单.docx>` |
| 3. 批量QC | Parallel subagents, one per pair, QC=是 + (keyword-matched or manual) | Dispatch per subagent template below |
| 4. 合并 | Merge `QC结果-Pair{N}.md` into single well-structured report | `python3 scripts/merge_qc.py <project_dir> [output.md]` |
| 5. 清理 | Delete intermediate files, keep only originals + final reports | `python3 scripts/cleanup_qc.py <project_dir> [-n] [-y]` |

**QC scope:** Pairs where `是否QC=是` AND (`匹配方法=关键字匹配` OR `匹配方法=人工指定`). Cosine/direct-match pairs must be changed to 人工指定 in Phase 1b before they can enter QC.

## Execution Discipline（执行纪律）

### Phase gating（阶段门控）

**每个 Phase 必须通过 Done check 后才能进入下一个 Phase。** 未验证产出物就跳入下一阶段是禁止行为。

| Phase | 进入条件 | 完成确认（Done check） |
|-------|---------|----------------------|
| 1. 匹配 | 原始 docx/pdf 存在 | `表格-清单-映射表.json` 存在，`python3 -c "import json; d=json.load(open('表格-清单-映射表.json')); print(len(d))"` 输出 > 0 |
| 1b. 复核 | Phase 1 完成 + 用户确认需要 | `映射复核.html` 已生成，用户已提供 `表格-清单-映射表-已复核.json` 或明确说跳过 |
| 2. 提取 | Phase 1/1b 完成 | `表格/` 和 `清单/` 文件夹存在，各含以编号-标题命名的 .xlsx 文件 |
| 3. 批量QC | Phase 2 完成 + 已确认 keyword-matched 对数 N | 所有 `QC结果-Pair{1..N}.md` 文件存在，数量 == N |
| 4. 合并 | Phase 3 全部 agent 完成 | `QC报告-汇总.md` 已生成，封面分级计数与各 pair 结论一致 |
| 5. 清理 | Phase 4 完成 | 仅保留原始文件 + 汇总报告 |

### Waiting rules（等待规则）

等待 background agent 完成时：

- **禁止轮询。** 不得用 `ls` 循环检查 `QC结果-Pair*.md` 文件。系统会通过 task-notification 自动通知每个 agent 完成。
- **收到通知后才计数。** 只根据 task-notification 判断进度，不去扫文件系统。
- **两次轮询之间最少间隔 30 秒。** 如果确实需要检查文件状态（例如确认 notification 是否遗漏），每次 `ls` 间隔 ≥ 30 秒。
- **超时处理。** 如果某个 agent 超过 10 分钟未完成，向用户报告该 pair 仍在运行并询问是否跳过。

### Phase 3 batch dispatch（批次调度）

```
1. 计算总数 N = keyword-matched pairs
2. 按 table 编号排序，分配 Pair 序号 1..N
3. 全部 N 个 agent 一次性并行启动（不拆分多批），每个 agent 写入独立文件
4. 静待 task-notification，收到一个计数一次
5. 当完成计数 == N 时，进入 Phase 4
```

## Phase 1: Match

根据文件格式选择匹配脚本：

**docx 文件：**

```bash
cd <project_dir>
python3 scripts/match_tables_listings.py 表格附件.docx 清单附件.docx 表格-清单-映射表.json
python3 scripts/deepseek_match.py --retry 表格-清单-映射表.json --docx 清单附件.docx --api-key <KEY>
```

**PDF 文件：**

```bash
cd <project_dir>
python3 scripts/match_tables_listings_pdf.py 表格附件.pdf 清单附件.pdf 表格-清单-映射表.json
python3 scripts/deepseek_match.py --retry 表格-清单-映射表.json --docx 清单附件.pdf --api-key <KEY>
```

Strategy: keyword detection (clinical terms + synonym map) → cosine similarity (`BAAI/bge-large-zh-v1.5`) → DeepSeek LLM retry for cosine-matched rows. Populations (FAS/PPS/SS) extracted from table/listing titles with parent-section inheritance.

**PDF 匹配 vs docx 匹配：** 匹配算法完全一致（复用 `match_tables_listings` 的 `match()`/`write_json()`），仅标题提取方式不同。PDF 版使用 `pdfplumber` 逐页提取标题，不依赖后续表格是否存在；docx 版要求清单标题后紧跟 `<tbl>` 才记录。

Output: `表格-清单-映射表.json` (machine-readable, used by Phase 1b and Phase 3).

## Phase 1b: Interactive Review (人工复核)

After matching, generate an interactive HTML page from the template to let the user review and correct the auto-matched mapping before proceeding to QC.

**Trigger:** After Phase 1 completes, ask the user: "是否需要生成交互式复核页面来审查和修正匹配结果？" If yes, generate the page.

### Generation procedure

Use the template at `assets/映射复核.html` — it contains the full HTML/CSS/JS with two placeholders:
- `__MAPPING_DATA__` — replace with compact JSON of the mapping array
- `__LISTINGS_DATA__` — replace with compact JSON of sorted unique listing names

Steps:
1. Read `assets/映射复核.html` and `<project>/表格-清单-映射表.json`
2. Extract all unique listing names from the JSON (union of `最佳匹配.清单名称` and all `候选匹配[].清单名称`, sorted)
3. Replace placeholders with compact JSON and write to `<project>/映射复核.html`

One-liner:
```bash
cd <project>
python3 -c "
import json
with open('<skill>/assets/映射复核.html') as f: tpl = f.read()
with open('表格-清单-映射表.json') as f: data = json.load(f)
listings = sorted(set(c['清单名称'] for d in data for c in [d['最佳匹配']]+d.get('候选匹配',[])))
html = tpl.replace('__MAPPING_DATA__', json.dumps(data, ensure_ascii=False, separators=(',',':')))
html = html.replace('__LISTINGS_DATA__', json.dumps(listings, ensure_ascii=False))
with open('映射复核.html','w') as f: f.write(html)
print(f'Generated, size: {len(html)} bytes')
"
```

### Exported JSON format (v2.0)

The template exports `表格-清单-映射表-已复核.json` with the following structure per table:

```json
{
  "表格编号": 1,
  "表格名称": "...",
  "表格人群": "FAS",
  "匹配清单列表": [
    {"清单编号": 3, "清单名称": "人口学信息清单（FAS）", "清单人群": "FAS"},
    {"清单编号": 4, "清单名称": "病史清单（FAS）", "清单人群": "FAS"}
  ],
  "匹配方法": "关键字匹配",
  "是否QC": "是"
}
```

Each table can have 1+ listings in `匹配清单列表` — all selected listings are used together to cross-validate the table in a single QC pair.

### After user review

1. User opens `映射复核.html` in browser, reviews and edits mappings
2. User clicks "导出修改" to download `表格-清单-映射表-已复核.json`
3. User places the reviewed JSON back into the project directory
4. Phase 3 QC uses the reviewed mapping — each table = 1 QC pair (referencing 1+ listings together), filter `是否QC=是` AND (`匹配方法=关键字匹配` OR `匹配方法=人工指定`)
5. If user doesn't provide a reviewed file, fall back to the original `表格-清单-映射表.json` (v1 single-listing format)

## Phase 2: Extract

**进入条件：** `表格-清单-映射表.json` 存在且非空。

根据文件格式选择提取脚本：

**docx 文件：**

```bash
cd <project_dir>
python3 scripts/extract_tables.py 表格文件.docx 清单文件.docx
```

Pipeline: 第一遍遍历 body XML 建标题索引 → 第二遍用 `doc.tables` 提取表格数据 → 输出为 `{编号}-{标题}.xlsx`。

**PDF 文件：**

```bash
cd <project_dir>
python3 scripts/extract_tables_pdf.py 表格文件.pdf 清单文件.pdf
```

Pipeline: 逐页提取 → 同页碎片合并 → 跨页同名表格/清单合并（仅相邻且列标题行一致时）→ 输出为 `{编号:02d}-{标题}.xlsx`。

- 表格标题识别：`表 X.X.X.X 标题...` 模式
- 清单标题识别：`清单 N 标题...` 模式
- 自动跳过目录页（TOC 检测）
- 单列碎片自动过滤
- 跨页合并后标注页码范围，如 `标题（p12-15，第2部分）.xlsx`

输出结构（两种格式输出结构完全一致）：
```
表格/
  01-表 7.1.1.1 各中心病例分布情况.xlsx
  02-表 7.1.1.2 各中心人群划分情况.xlsx
  ...
清单/
  01-清单 1 脱落剔除清单（随机化人群）（第1部分）.xlsx
  02-清单 1 脱落剔除清单（随机化人群）（p3-8，第2部分）.xlsx
  ...
```

**Excel 文件定位规则（Phase 3 使用）：**
- 表格：文件名包含表格名称中的关键词（如 `不良事件`）
- 清单：文件名包含 `清单 {编号}`（如 `清单 24`）

**完成确认：** `表格/` 和 `清单/` 文件夹存在，各含以编号开头的 .xlsx 文件，数量与映射表中的唯一表格/清单数一致。

## Phase 3: Batch QC

**进入条件：** Phase 2 完成确认通过（两个 Excel 文件夹存在且非空），已计算出 keyword-matched 对数 N。

### Execution

1. If `表格-清单-映射表-已复核.json` exists, use it; otherwise fall back to `表格-清单-映射表.json`.
2. Filter: `是否QC=是` AND (`匹配方法=关键字匹配` OR `匹配方法=人工指定`). Each table = 1 QC pair, regardless of how many listings it references.
3. **One table, multiple listings**: The subagent uses ALL selected listings in `匹配清单列表` together to cross-validate the table.
4. Assign each QC pair a unique sequence number (1, 2, 3, ... N) in table-number order.
5. **一次性并行启动全部 N 个 subagent** — 每个 subagent 一个 pair，写入独立文件 `QC结果-Pair{N}.md`。不拆分批，全部同时启动。
6. 静待 task-notification 通知每个 agent 完成。收到一个计数一次。禁止轮询文件系统。
7. 当完成计数 == N 后，进入 Phase 4。

**Why one-pair-per-agent:** Each subagent must parse Excel files, write Python parsing code, and generate reports — all of which stays in context. One table may reference multiple listings (e.g. AE table needs both AE listing + SAE listing), so the subagent's listing-parsing cost is proportional to the number of selected listings. One pair per agent keeps each agent's context bounded.

### Subagent dispatch (one per table)

Each subagent invokes the **`tfl-pair-qc`** skill, which contains the full single-pair QC workflow (read rules → locate Excel → explore structure → write QC script → output report).

Subagent prompt:

```
使用 tfl-pair-qc 技能，对此表格执行反向质控核查。

表格名称: {表格名称}
表格人群: {表格人群}
参考清单: [{清单编号: {n}, 清单名称: {name}, 清单人群: {pop}}, ...]
Pair序号: {N}
项目目录: <project_dir>
表格搜索: {表格编号:02d}-*.xlsx
清单搜索: 清单 {编号}
输出文件: QC结果-Pair{N}.md
```

The `tfl-pair-qc` skill handles: reading qc_rules.md + subagent_output_template.md, Excel file location, Phase A (explore) → Phase B (full QC script), META-anchored report output, and problem grading (Critical/Major/Minor/Suggestion).

### Report output

Each pair writes `QC结果-Pair{N}.md` (individual file, no write conflicts). After all batches complete, the main process merges all individual pair files into a single consolidated report:

- `QC报告-汇总.md` — unified report with all pairs. Structure: 核查概览 (按四级分级的统计: PASS/CRITICAL/MAJOR/MINOR/SUGGESTION) → 问题分级标准 → 目录 → 逐对详情 (仅问题对展开，PASS 对简要标注"未发现问题")。
- Individual `QC结果-Pair{N}.md` files are retained for traceability; the merged report is the primary deliverable.

**Merge procedure (run by main process after all batches complete):**

```bash
cd <project_dir>
python3 <skill>/scripts/merge_qc.py . QC报告-汇总.md
# 同时生成层次分明的 QC结果-全部合并.md（默认输出）
python3 <skill>/scripts/merge_qc.py .
```

The script `scripts/merge_qc.py` does the following:
1. Collects all `QC结果-Pair{N}.md` files, sorts by N
2. Extracts table name and conclusion (PASS/CRITICAL/MAJOR/MINOR/SUGGESTION) from each file
3. Generates a structured document with:
   - **Cover**: date, file info, 分级统计表
   - **问题分级标准**: 四级标准定义表
   - **Table of contents**: clickable links with severity badges
   - **Per-pair sections**: `## Pair N: 表格名称` with demoted nested headers (original `#`→`##`, `##`→`###`, `###`→`####`) for proper hierarchy
   - **`---` separators** between pairs
4. Outputs `QC结果-全部合并.md` (default) or a custom filename
5. Verifies no pairs are missing (count files = total keyword-matched pairs)

## Phase 4: Merge

**进入条件：** Phase 3 全部 N 个 agent 已完成（完成计数 == N）。

After all QC subagents complete, merge individual `QC结果-Pair{N}.md` files into a single well-structured report.

```bash
cd <project_dir>

# Generate structured merged report (default output: QC结果-全部合并.md)
python3 <skill>/scripts/merge_qc.py .

# Specify custom output filename
python3 <skill>/scripts/merge_qc.py . QC报告-汇总.md
```

The merge script auto-extracts table names and conclusions from each file, builds a clickable table of contents, and demotes all markdown headers by one level to create proper document hierarchy:

```
# TFL 反向质控核查 — QC 结果报告     ← document title
├── 核查概览 (分级统计表)
├── 问题分级标准
├── ## 目录 (clickable TOC with severity badges)
├── ## Pair 1: 表格名称             ← pair section
│   ├── (original # → ##)
│   ├── (original ## → ###)
│   └── (original ### → ####)
├── ## Pair 2: 表格名称
│   └── ...
└── ...
```

## Phase 5: Cleanup

**进入条件：** Phase 4 完成，`QC报告-汇总.md` 封面计数已人工/脚本确认与各 pair 一致。

After merging, remove all intermediate files, keeping only the original inputs and final reports.

```bash
cd <project_dir>

# Preview what will be deleted (safe, no actual deletion)
python3 <skill>/scripts/cleanup_qc.py . --dry-run

# Delete with confirmation prompt
python3 <skill>/scripts/cleanup_qc.py .

# Delete without prompt (for automated pipelines)
python3 <skill>/scripts/cleanup_qc.py . --yes
```

**Files deleted (intermediate):**
- `表格-清单-映射表.json` — Phase 1 matching output
- `映射复核.html` — Phase 1b review page
- `表格/` `清单/` — Phase 2 extracted Excel files
- `QC结果-Pair*.md` — individual pair reports (merged already)
- `qc_pair*.py` — subagent temporary scripts

**Files kept (final):**
- `*.docx` — original input files
- `QC报告-汇总.md` — consolidated QC summary report
- `QC结果-全部合并.md` — full merged detail report

## Common Mistakes

1. **Skipping population inheritance.** Tables may inherit FAS/PPS/SS from parent section headings. The extraction scripts handle this; verify analysis set in QC code.
2. **Subagent 定位 Excel 文件失败。** 表格名称中的特殊字符可能导致搜索不匹配。subagent 应先用 `ls` 列出文件夹所有文件，再模糊匹配。调度时提供表格编号前缀（如 `05-*.xlsx`）可减少此问题。
3. **Aggregating multiple pairs into one agent.** Each subagent must handle exactly one pair. One agent = one pair = one file.
4. **Multiple subagents writing to the same file.** Parallel subagents must NOT write to a shared file. Each agent writes to its own `QC结果-Pair{N}.md`, and the main process merges them sequentially after all agents complete.
5. **Polling for results instead of waiting for notifications.** Use task-notification, not `ls` loops, to track agent completion.
6. **Launching cosine-matched pairs without review.** Only keyword-matched pairs or pairs manually marked 是否QC=是 in Phase 1b should enter QC. Cosine-matched pairs with 是否QC≠是 must be excluded.

Pair-level QC mistakes (confusing 例次 vs 人数, using non-final SAE records, SOC hierarchy, wrong rules for table type, skipping multi-row headers, merged cell handling) are documented in `tfl-pair-qc` skill.
