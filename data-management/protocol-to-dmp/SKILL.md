---
name: protocol-to-dmp
description: Use when the user provides a clinical trial protocol, DM log, DMP rule/template document, or DMP non-fixed-content checklist and asks to generate, draft, update, or automate a Chinese Data Management Plan (DMP/数据管理计划) that must follow a fixed Word template and Excel rules.
---

# Protocol to Chinese DMP

Generate a Chinese DMP draft by selecting one governed Word template, filling only governed non-fixed content, and preserving fixed wording.

## Non-Negotiable Rules

- Read the DM log first and select exactly one base template before any drafting:  
  - **If both `是否使用随机系统` and `是否使用登记系统` are `是`, stop and ask the user to clarify.** A project will not use both a randomization system and a registration system simultaneously; one of the two DM log fields is incorrect. 
  - `是否使用随机系统 = 是` -> `assets/DMP-随机系统.docx`
  - else `是否使用登记系统 = 是` -> `assets/DMP-登记系统.docx`
  - else both are `否` -> `assets/DMP-无随机无登记.docx`

- Do not infer the base template from the protocol unless the DM log is missing/unclear; ask the user before generating if the DM log cannot determine it.
- Use `assets/DMP非固定内容清单.xlsx` as the primary source of truth for every non-fixed item unless the user provides a newer checklist.
- Copy fixed content exactly. Do not rewrite, polish, summarize, translate, reorder, renumber, or add sections.
- Use the protocol as the main source for study-level facts and the DM log as the supplementary/project-reality source.
- Strictly extract `方案名称/临床试验方案名称`, `方案编号`, `申办方/申办者名称`, and `数据管理单位名称` from the current protocol and/or DM log. If sources conflict or neither source provides the value, ask; never fabricate or use example-project defaults.
- Never hard-code facts from any example project. Example protocols and DM logs may be used for regression tests only; production generation must derive project names, sponsor names, systems, vendors, dates, endpoints, and template choices from the current protocol, current DM log, and current checklist trace.
- Do not guess. If a required value is missing, uncertain, or conflicting, ask the user with the DMP section, missing field, reason, and expected source.
- For Section `3 试验概述`, prefer protocol summary/study summary/trial summary content, including semantically equivalent headings such as `方案摘要`, `研究摘要`, or `临床试验摘要`. Preserve protocol wording as directly as possible.
- When the protocol is Word, extract Section `3 试验概述` from Word structure first: table rows, cell paragraphs, and adjacent semantic blocks. Preserve paragraph/newline order and do not split medical content by punctuation such as `；`, `,`, `。`, or by generated separators such as `|`.
- For `其他终点`, include all clearly identified non-primary endpoint blocks, including secondary/other endpoints and separate safety or exploratory endpoint rows when present. Do not stop after the first secondary endpoint block if the protocol summary has additional safety/exploratory rows.
- When the protocol is PDF or plain text, use the same conservative semantic evidence standard. If the source text structure is not clear enough to identify the full semantic block, ask instead of guessing.
- Replace every `研究设计类型为xxx` occurrence with the study design wording extracted from the protocol summary when clearly available.
- Generate the DMP version revision history table with one row per DM-log version record, sorted from oldest to newest by version date. Do not merge records or invent missing version information.
- When the DM log contains multiple entries (多轮对话/多版本记录), use the latest entry's values for all non-version fields (e.g. system choices, service scope, QC level) while preserving all version records in the revision history table in chronological order.
- Apply confirmed placeholders across the whole Word package: body text, tables, cover page, signature pages, headers, and footers. Support common synonymous placeholders such as `请输入申办者`, `请输入申办者名称`, `请输入临床监查方`, and `请输入临床监察方`. For signature-page writer placeholders, replace every writer-name placeholder consistently and do not duplicate labels such as `撰写人：撰写人：...`.
- Preserve table-like manual-selection sections in this first version: sections `9`, `15.2`, `26.1`, `27.1`, `27.2`, `27.3`, and `29`. Do not delete, simplify, or decide/check items in these sections.
- Keep a trace for each checklist row: section, item, source type, value, evidence, status, and question if unresolved.
- When a `fewshot.md` file is provided, apply few-shot format constraints to matching fields AFTER semantic review correction. The few-shot file defines per-field reference examples; reformat the corrected trace values to match the example style (conciseness, sentence template, placeholder substitution) before drafting.

## Workflow

1. Resolve inputs:
   - Protocol: user-provided `.docx`, `.pdf`, `.txt`, or `.md`.
   - DM log: user-provided `.json`, `.xlsx`, `.txt`, or `.md`.
   - Template/checklist: use bundled assets unless newer files are provided. If newer templates are provided, they must include the same three-template choices.
   - Use the Codex bundled Python runtime when available; the scripts require `python-docx` and `openpyxl`.
2. Build an evidence trace. The script reads the DM log first, selects the base Word template, then reads the checklist and protocol:

   ```bash
   python scripts/build_dmp_trace.py \
     --protocol /path/to/protocol.docx \
     --dm-log /path/to/dm-log.json \
     --template-dir assets \
     --checklist assets/DMP非固定内容清单.xlsx \
     --out /path/to/dmp_trace.json \
     --questions /path/to/dmp_questions.md
   ```

3. **Semantic review of high-risk fields** (new). The trace extractors use pure rules (table structure, regex, keyword matching) without semantic understanding. Fields such as `样本量`, `研究设计`, `主要有效性终点`, `其他终点`, and `统计分析人群` are prone to extraction errors — e.g., picking an intermediate sample size (184例) instead of the final total (205例). Run semantic review BEFORE drafting:

   ```bash
   # Step 3a: Prepare review context
   python scripts/semantic_review.py \
     --mode prepare \
     --trace /path/to/dmp_trace.json \
     --protocol /path/to/protocol.docx \
     --out /path/to/semantic_review_input.json

   # Step 3b: Review each field semantically. Read semantic_review_input.json.
   # For each review_item, examine current_value + evidence_snippet + protocol_context.
   # Set review_decision to one of:
   #   "accept"  – the value is correct, no change needed
   #   "correct" – the value is wrong; set corrected_value and correction_reason
   #   "flag"    – unclear, needs user input; note the ambiguity
   # Common checks:
   #   样本量: is this the FINAL total sample size (including dropout), not an
   #           intermediate calculation? Look for "最终样本量", "总样本量", "所需样本量",
   #           "考虑脱落率后" in the surrounding context. Take the largest number when
   #           multiple are present.
   #   研究设计: does the value capture the full study design (phase, arms, blinding,
   #             control type)? Check the protocol summary row for completeness.
   #   主要有效性终点: is the primary endpoint complete and correctly identified
   #                   (not a secondary or safety endpoint)?
   #   其他终点: are ALL secondary, safety, and exploratory endpoints captured?
   #             Check for missing endpoint categories like 安全性指标 or 探索性终点.
   #   统计分析人群: are all analysis populations included (FAS, PPS, SS)?
   # Edit the review JSON file directly to fill in review_decision, corrected_value,
   # and correction_reason for each item before proceeding.

   # Step 3c: Apply corrections back to the trace
   python scripts/semantic_review.py \
     --mode apply \
     --trace /path/to/dmp_trace.json \
     --review /path/to/semantic_review_input.json \
     --out /path/to/dmp_trace.json
   ```

   # Step 3d: Few-shot format constraint (optional – skip if no fewshot.md provided).
   # Constrain the output style of fields to match reference examples in fewshot.md.
   # This step runs AFTER semantic review so values are already corrected before reformatting.

   ```bash
   # Step 3d-i: Prepare few-shot review context
   python scripts/fewshot_format.py \
     --mode prepare \
     --trace /path/to/dmp_trace.json \
     --fewshot /path/to/fewshot.md \
     --out /path/to/fewshot_review.json

   # Step 3d-ii: Review each field semantically against the few-shot examples.
   # Read fewshot_review.json. For each review_item, examine current_value and
   # fewshot_examples. Set format_decision to one of:
   #   "accept"    – the value already matches the example format, no change needed
   #   "reformat"  – rewrite current_value to match the few-shot style
   #   "flag"      – unclear, needs user input; note the ambiguity
   # Common checks:
   #   研究设计: is the value a single concise sentence (type + arms + blinding +
   #             center + control), or does it include sample size / evaluation /
   #             period / administration details that belong in other fields?
   #   样本量: does the value follow the template sentence pattern shown in the
   #           few-shot example, with actual numbers replacing placeholders?
   # Edit the review JSON file directly to fill in format_decision, formatted_value,
   # and format_reason for each item before proceeding.

   # Step 3d-iii: Apply few-shot formatting back to the trace
   python scripts/fewshot_format.py \
     --mode apply \
     --trace /path/to/dmp_trace.json \
     --review /path/to/fewshot_review.json \
     --out /path/to/dmp_trace.json
   ```

4. Review the corrected `dmp_trace.json` before drafting:
   - Accept `filled` values only when their evidence supports the checklist rule.
   - Treat `uncertain`, `missing`, `conflict`, `manual_confirm`, and `not_processed` as unresolved unless the Excel row explicitly allows a default.
   - Ask the user grouped questions from `dmp_questions.md` before filling unresolved required content.
5. Apply confirmed values conservatively to a copy of the template:

   ```bash
   python scripts/apply_trace_to_template.py \
     --trace /path/to/dmp_trace.json \
     --out /path/to/DMP初稿.docx \
     --report /path/to/DMP生成报告.md
   ```

6. Finish template selection only where the checklist requires it and evidence is confirmed:
   - Select among existing template blocks in the Word template.
   - Do not invent new text when no matching option exists; ask the user or leave a clear pending marker outside fixed text.
   - Never perform automatic selection/deletion inside the protected table-like sections listed above.
   - Resolve `/模板1/`, `/模版2/`, `/*模版...*/`, and similar marker labels across the whole draft. Selected marker labels must not appear in the final DMP.
   - Use generic mapping rules based on checklist item values, such as EDC/PDC mode or current vendor/system text; do not branch on project names, protocol numbers, sponsors, disease areas, or example-file strings.
   - Treat helper-script output as a draft assist; manually review any report item listed as "已确认但需人工按模板规则处理".
7. Quality-check the final `.docx`:
   - Section order, numbering, headings, tables, and fixed wording remain based on the template.
   - All non-fixed changes are backed by trace evidence or user confirmation.
   - No unresolved required fields remain silently blank.
   - Protocol and DM log conflicts are listed for confirmation, not auto-overwritten.

## Bundled Resources

- `assets/DMP-随机系统.docx`: DMP base template for projects using a randomization system.
- `assets/DMP-登记系统.docx`: DMP base template for projects using a registration system but no randomization system.
- `assets/DMP-无随机无登记.docx`: DMP base template for projects using neither randomization nor registration.
- `assets/DMP非固定内容清单.xlsx`: non-fixed-content checklist and decision rules.
- `scripts/build_dmp_trace.py`: parse sources and create the evidence/missing-info trace.
- `scripts/semantic_review.py`: LLM-assisted semantic review of high-risk fields (sample size, endpoints, study design, analysis population) that are prone to regex extraction errors. Two modes: `prepare` (extracts review context) and `apply` (writes corrections back to trace).
- `scripts/fewshot_format.py`: LLM-assisted few-shot format constraint for fields after semantic review. Reads `fewshot.md` examples and constrains output style to match reference format. Two modes: `prepare` (extracts fields + fewshot examples) and `apply` (writes reformatted values back to trace).
- `scripts/apply_trace_to_template.py`: copy the template and perform conservative field/table fills.
- `reference/chinese-dmp-generation.md`: detailed source, missing-info, protected-section, and QA rules.

Read `reference/chinese-dmp-generation.md` when handling template selection, conflicts, missing fields, or manual Word edits beyond the helper script.
