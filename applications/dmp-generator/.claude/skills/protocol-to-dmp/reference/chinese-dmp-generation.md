# Chinese DMP Generation Rules

## Source Priority

Read the DM log before the protocol for base Word template selection. Use the protocol for study facts after the template has been selected.

| Checklist `来源类型` | Required handling |
| --- | --- |
| `方案` | Extract from the clinical trial protocol. Preserve protocol names, numbers, versions, objectives, endpoints, sample sizes, and analysis populations as written. If only an inferred value is available, mark `uncertain` and ask. |
| `DM日志` | Prefer the DM log for project-reality fields such as dates, systems, vendors, deliverables, service scope, QC level, and decisions confirmed outside the protocol. Exact DM-log keys matching `非固定内容` are strong evidence. |
| `暂不处理` | Do not auto-fill unless the user confirms. Keep template default/fixed content unchanged and list the item as `manual_confirm` or `not_processed`. |
| blank/null | Treat as a governance or QC row. Use it to check trace quality, conflicts, or missing values; do not write it into the DMP as content. |

When protocol and DM log disagree, do not choose silently. Record both source excerpts and ask the user to confirm the final value.

Never encode example-project facts in the skill or scripts. A sample protocol may demonstrate behavior, but names, identifiers, sponsors, indications, vendors, URLs, endpoints, dates, and decisions must always come from the active input files and checklist trace.

## Base Template Selection

Select exactly one Word template from the current DM log before reading or applying template content:

| DM log decision | Base template |
| --- | --- |
| `是否使用随机系统 = 是` | `DMP-随机系统.docx` |
| `是否使用随机系统 != 是` and `是否使用登记系统 = 是` | `DMP-登记系统.docx` |
| both `是否使用随机系统` and `是否使用登记系统` are `否` | `DMP-无随机无登记.docx` |

Do not infer the base template from protocol text unless the DM log is missing or unclear and the user confirms. If the DM log uses nested fields, flattened keys, or equivalent field names, use semantic key matching; if the decision still cannot be made, stop and ask.

After this base template is selected, all extraction, replacement, and drafting must use only that selected Word file. Do not mix content from other base templates.

## Strict Project Identifiers

The following fields must be extracted from the current protocol and/or DM log, never invented:

- `方案名称` / `临床试验方案名称`
- `方案编号`
- `申办方名称` / `申办者名称`
- `数据管理单位名称`

Look in the protocol first and also check the DM log for confirmed project metadata. If both sources provide incompatible values, mark `conflict` and ask. If neither source provides the field, leave it unresolved and ask. Do not fill generic sponsor, protocol, or data-management-unit placeholders silently.

## Protocol Semantic Matching

Checklist source locations are guidance, not exact heading requirements. If a row says to use `试验摘要`, equivalent protocol areas such as `方案摘要`, `研究摘要`, `临床试验摘要`, or a table containing the same summary fields may be used. The extracted value must still be clearly present in the protocol evidence.

For Section `3 试验概述`, prefer the protocol summary table/section and paste the protocol wording as directly as possible for study name, design, purpose, sample size, endpoints, and analysis population. If the summary is incomplete, search equivalent sections such as study design, endpoints, and analysis dataset chapters before asking.

When the protocol is `.docx`, extraction should be structure-first: use Word tables, row labels, cell paragraph order, and adjacent semantic blocks. Do not replace cell newlines with generated separators such as `|`, and do not truncate endpoint or objective text using punctuation such as `；`, `;`, `,`, `，`, or `。`. For example, if the main endpoint has a following definition paragraph in the same summary cell, keep that definition with the main endpoint until the next endpoint category begins.

For `其他终点`, collect all non-primary endpoint content that is clearly present in the protocol summary or equivalent overview area. This includes secondary endpoints, safety endpoints, and exploratory endpoints, whether they appear in one summary cell or in separate adjacent rows such as `安全性指标` or `探索性终点`. Preserve the row label when it is needed to keep the endpoint type clear.

When the protocol is `.pdf` or plain text, use semantic matching against the extracted text but keep the same conservative standard. If the source structure does not make the full endpoint/objective/design block clear, mark it `uncertain` or `missing` and ask the user.

For text like `研究设计类型为xxx`, replace `xxx` with the protocol's study-design wording, preferably from the protocol summary/trial design row. Do not standardize or rewrite the design wording if the protocol text is clear.

## Version Revision History

Generate the DMP version revision table from DM-log version records:

- one DM-log version record -> one table row
- multiple DM-log version records -> one table row per record
- incomplete version fields -> ask for the missing fields

Preserve the selected template's revision table structure. Do not merge version records and do not invent version numbers, dates, authors, or revision content.

Sort version records from oldest to newest by version date, then by version number, so the revision history reads chronologically downward.

## Multi-Round DM Log (多轮对话)

When the DM log JSON contains an array of multiple entries (e.g. `[{...}, {...}, {...}]`):

- **Latest entry wins for non-version fields**: Use the last entry in the array for all project-state fields such as `项目类型`, `EDC系统供应商`, `随机系统供应商`, `是否涉及外部数据`, `是否有阶段性分析`, `项目质量控制等级`, etc. The last entry represents the most current project reality.
- **All entries contribute to version history**: Every entry that contains version fields (`DMP版本号`, `DMP版本日期`, `撰写者/修订者`, `版本修订记录`) becomes a row in the version revision history table, sorted from oldest to newest.
- **DMP version metadata**: The latest entry's `DMP版本号` and `DMP版本日期` are used as the current DMP version for cover pages, headers, and signature pages.
- If the DM log is a single entry (not an array), behavior is unchanged from the single-round case.

Do not infer which entry to use from protocol text. The DM log array order is authoritative: first entry = oldest, last entry = newest.

## Checklist Statuses

Use these statuses in the trace:

- `filled`: value is supported by the specified source and can be used.
- `uncertain`: a plausible value exists but evidence is not strong enough.
- `missing`: required value is absent from the specified source.
- `conflict`: protocol and DM log provide incompatible values.
- `manual_confirm`: checklist says the item needs user confirmation or is `暂不处理`.
- `not_processed`: item should not be automatically handled in this first version.
- `qc_rule`: row is a quality/control rule, not a DMP field.

Only `filled` values should be applied automatically. User answers may be written back into the trace as `filled` with `source_used: user_confirmation`.

## Missing-Info Questions

Group unresolved questions by DMP section. Each question should include:

- DMP section/application scope from `规则文档章节/应用范围`
- Non-fixed content item from `非固定内容`
- Expected value from `需要填写/替换的具体内容`
- Required source from `来源类型`
- Why it is needed, based on `统一判断/模板选择规则`
- Current evidence, if any

Avoid asking vague questions like "please confirm project info." Ask for the exact field or decision.

## Template-Faithful Drafting

Always start from the Word template by copying it. Do not generate a DMP from a blank document.

Safe automatic fills:

- Cover/version labels when a value is confirmed.
- Trial overview table rows whose first cell exactly matches a checklist field.
- Specific placeholder words such as `XXXX` or `xxx` only when the surrounding sentence clearly matches the checklist item.
- Body, cover, signature-page, header, and footer placeholders when the field is confirmed, including synonymous placeholders such as `请输入申办者`, `请输入申办者名称`, `请输入临床监查方`, and `请输入临床监察方`.
- Writer placeholders on signature pages when the DM log provides `撰写者/修订者`; replace all writer-name placeholders consistently and normalize duplicate labels such as `撰写人：撰写人：姓名`.
- Protocol version number/date should come from the protocol body first. If Word extraction produces a visibly incomplete value but the file name provides the missing version/date, the file name may be used as lower-priority evidence and recorded in the trace.

Unsafe automatic edits:

- Rewriting fixed paragraphs.
- Removing template sections without a checklist rule and confirmed evidence.
- Reconstructing tables manually.
- Applying inferred values without asking.
- Using the example protocol as a format requirement.

## In-Template Block Selection

For checklist rows with `判断粒度` such as `统一模板选择`, `适用性判断`, or `统一联动判断`:

1. Confirm the governing decision once in the trace.
2. Locate the relevant existing `/模板.../` block in the Word template.
3. Keep the selected block's wording as-is except for governed placeholders.
4. Remove non-selected blocks only outside protected table-like sections and only when the decision is `filled`.
5. If no existing block fits, ask the user. Do not draft a new block.

Template-selection code may map generic checklist values to existing template markers, for example `EDC` -> EDC blocks or a current system string containing `太美` and `V6` -> the bundled `太美系统V6` block. Do not map by project name, protocol number, sponsor, disease, or example-file identity.

If a selection row is `conflict`, keep the conflict in the questions/report. If a draft must still be produced, any provisional selection must be based on generic source evidence and clearly remain pending confirmation; never hide the conflict.

## Protected Table-Like Sections

The first version must preserve all existing items in these sections:

- Section 9
- Section 15.2
- Section 26.1
- Section 27.1
- Section 27.2
- Section 27.3
- Section 29

For these sections, do not attempt to infer checkbox status, selected items, deletion, or applicability. Keep all current template rows/items exactly so the data manager can adjust them later.

It is acceptable to replace inline `/模板1/… /模板2/…` text inside a protected table cell with the selected wording when the row itself is preserved and the checklist provides a confirmed generic decision. Do not remove protected rows/items automatically.

## Final QA

Before delivery, verify:

- The DMP was produced from the template `.docx`.
- Fixed sections were not rewritten.
- Section numbering and heading hierarchy are unchanged unless the user explicitly required a confirmed template-block removal.
- Table count and protected table contents remain intact.
- Each non-fixed modification has a trace entry with evidence or user confirmation.
- Missing/conflicting items are either answered by the user or clearly listed as pending.
