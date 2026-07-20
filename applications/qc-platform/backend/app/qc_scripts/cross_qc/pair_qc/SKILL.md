---
name: tfl-pair-qc
description: Use when performing reverse-derivation QC on a single clinical trial table-listing pair, when a subagent is dispatched by tfl-listing-cross-qc Phase 3, or when asked to cross-validate one specific table against its listing(s). Triggers on: single pair QC, 单对QC, 反向核查单个表格, pair qc, tfl pair check, 核对单表.
---

# TFL Pair QC — Single-Pair Reverse-Derivation

## Overview

Reverse-derive every count, event, and percentage in a clinical trial Table from the corresponding Listing(s). This skill is the unit of work dispatched by `tfl-listing-cross-qc` Phase 3, and can also be used standalone.

Core principle: **Every number in a Table must be reproducible from the Listing.**

## Input (from caller)

- 表格名称, 表格人群 (e.g. "不良事件编码（SOC/PT）", "SS")
- 参考清单: [{清单编号, 清单名称, 清单人群}, ...]
- Pair序号 (optional)
- 项目目录 (path containing 表格/ and 清单/ folders)
- 表格搜索提示 (table index number or name keyword)
- 清单搜索提示 (listing numbers)

## Execution Workflow

### Step 0: Read reference files FIRST (mandatory)

Before any file exploration, read both:
- `reference/qc_rules.md`
- `reference/subagent_output_template.md`

Skipping this step leads to wrong QC rules and malformed output.

### Step 1: Locate Excel files

```bash
# List all files, then grep/filter
ls 表格/ | grep "<keyword>"
ls 清单/ | grep "清单 <num>"
```

- 表格: search by table index (e.g. `05-*.xlsx`) or name keyword
- 清单: search by listing number with regex `清单\s*<num>\b` for exact match
- If multiple listings specified, locate ALL

### Step 2: Explore Excel structure (Phase A)

Print ALL rows of every Excel file to understand header/data/footnote layout:

```bash
python3 -c "
from openpyxl import load_workbook
wb = load_workbook('<file>')
ws = wb.active
for r in range(1, ws.max_row + 1):
    row = [str(ws.cell(row=r, column=c).value or '')[:50] for c in range(1, ws.max_column + 1)]
    print(f'Row{r}: {row}')
"
```

Pay attention to: how many header rows, column meanings, data start row, footnote rows, vertically merged cells (value only in first row).

### Step 3: Write and execute QC script (Phase B)

Write a complete Python script that:

1. Locates all Excel files
2. Parses the table — skip headers, parse formatted values (`"1(6.67%)"` → count + percentage)
3. Parses listing(s) — column-name→index mapping, iterate ALL rows (no empty-row filtering), handle merged cells with forward-fill
4. Selects QC rules based on table type:
   - 人口学/基线 → subject dedup, group consistency, analysis set match
   - AE/SAE → table↔listing totals, SAE in AE listing, death chain, 人数≤例次数
   - 事件类 → same event across tables, composite = Σ components
   - 实验室/生命体征 → abnormal↔crosstab, min≤Q1≤median≤Q3≤max, n+missing=N
5. Compares and prints results

Script pattern:

```bash
python3 << 'PYEOF'
"""Pair{N}: {table_name} → listing(s)"""
import os, re
from openpyxl import load_workbook
from collections import Counter

BASE = "<project_dir>"
TABLE_DIR = os.path.join(BASE, "表格")
LISTING_DIR = os.path.join(BASE, "清单")

table_file = next(f for f in os.listdir(TABLE_DIR) if "<keyword>" in f)
# ... parse table, parse listing(s), compare, print ...
PYEOF
```

### Step 4: Write QC report

Write to `<project>/QC结果-Pair{N}.md` strictly per `reference/subagent_output_template.md`.

**Hard requirements:**
- File MUST start with exactly 3 consecutive META lines (no blank lines between):
  ```
  ##META_TABLE: <exact table name from input>
  ##META_CONCLUSION: PASS|MAJOR|MINOR|SUGGESTION|PENDING
  ##META_LISTING: <listing name>|<population>
  ```
- `##META_CONCLUSION:` = highest severity among all findings, or `PASS` if none, or `PENDING` if the match is suspected wrong and needs human review
- Multiple listings use `||`: `AE清单|SS||SAE清单|SS`
- Only report problems; PASS pairs write "未发现问题"
- Every problem must include severity grade AND concrete numbers (Table=X, Listing=Y)
- **If the subagent suspects the table is matched to the wrong listing, DO NOT assign Major/Minor. Instead set META_CONCLUSION to `PENDING` and explain why the match is suspect.**

### Problem Grading

| Grade | Definition | Examples |
|-------|-----------|----------|
| **Major** | Obvious error: arithmetic mistakes, verifiable data inconsistency | Table total ≠ sum of groups; count/percentage mismatch verifiable from listing; N-value contradiction |
| **Minor** | Minor issues: format, footnotes, table numbers, coding, rounding | Table number reference error; N format inconsistency; rounding ≤0.2%; footnote missing |
| **Suggestion** | Suspected issue, cannot confirm from available data; or improvement suggestion | Possible inconsistency but data insufficient to confirm; suggest adding footnote; wording suggestion |
| **PASS** | No problems found | — |
| **PENDING** | Match is suspicious—table may be paired with wrong listing; requires human review | Listing content doesn't match table content semantically; listing population differs from what table data suggests |

## QC Rules Quick Reference

Full details in `reference/qc_rules.md`. Summary:

### General
- Subject dedup: Table count = listing dedup count
- 例次 can be > 人数; 人数 must be ≤ 例次
- Group consistency: listing aggregated by group → table groups
- Analysis set: Table FAS → FAS listing; Table SS → SS listing

### AE/SAE
- Table↔Listing totals match (both events AND subjects)
- Every SAE must appear in AE listing with SAE flag
- Death chain: deaths(AE) = deaths(SAE) = deaths(disposition)
- Subjects withdrawing due to AE must have AE records

### Lab/Vital Signs
- min ≤ Q1 ≤ median ≤ Q3 ≤ max (all groups, all parameters)
- n + missing = N (analysis set denominator)
- Text values must not enter continuous calculations
- Q1/Q3: SAS PCTLDEF=5 differs from numpy default; use SAS-equivalent when possible

### Event-type
- Same event in efficacy and safety tables should be consistent
- Composite endpoint = yes → at least one component = yes

## Common Mistakes

| # | Mistake | Fix |
|---|---------|-----|
| 1 | Confusing 例次 with 人数 | AE tables show both; check separately; 例次 ≥ 人数 |
| 2 | Using non-final SAE records | SAE listings may have initial+follow-up+summary per event |
| 3 | SOC: Σ(PT events) ≠ SOC events | Must equal; Σ(PT subjects) may exceed SOC subjects |
| 4 | Wrong QC rules for table type | Lab rules don't apply to AE tables; match check to content |
| 5 | Excel file not found | `ls` first, then fuzzy match; special chars break exact match |
| 6 | Skipping multi-row headers | TFL tables have 2-3 header rows; MUST print all rows first |
| 7 | Merged cell empty values | Forward-fill or group by blocks for vertically merged cells |
| 8 | Too-strict rounding check | Allow ≤0.2% for rounding strategy differences |
| 9 | Q1/Q3 algorithm mismatch | numpy.percentile ≠ SAS PCTLDEF=5; document which used |

## Interaction with tfl-listing-cross-qc

This skill is the Phase 3 workhorse. The parent skill handles:
1. Phase 1-1b: Match tables → listings, generate review page
2. Phase 2: Extract docx → Excel files
3. Phase 3: Dispatch N parallel agents, each invoking **this skill**
4. Phase 4: Merge all `QC结果-Pair{N}.md` → consolidated report
5. Phase 5: Cleanup intermediate files
