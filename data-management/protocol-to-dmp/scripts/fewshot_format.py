#!/usr/bin/env python3
"""Few-shot format constraint for trace fields after semantic review.

Two modes:
  prepare  – extract fields matching fewshot.md examples for LLM reformatting
  apply    – apply LLM-reformatted values back to the trace JSON

The fewshot.md file defines per-field formatting examples. After semantic review
corrects the raw values, this step constrains the output style to match the
reference format shown in the examples.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_fewshot(fewshot_path: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Parse fewshot.md into ({field_name: [examples]}, {field_name: output_rule_prompt}).

    Header-driven parsing: each section starts with a header line matching one of:
      - "研究设计示例：" or "研究设计：" → few-shot examples
      - "研究目的的输出规范（...）：" → output-rule prompt (not format examples)

    Section content runs from the header to the next header (or EOF).
    Multi-paragraph prompts with internal blank lines are preserved intact.
    """
    text = fewshot_path.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    prompts: dict[str, str] = {}

    # Pattern for any section header line
    PROMPT_HEADER_RE = re.compile(r"^(.+?)的输出规范(?:（[^）]*）)?[：:]")

    # Find all header lines and their positions
    lines = text.split("\n")
    header_positions: list[tuple[int, str, bool]] = []  # (line_index, field_name, is_prompt)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        prompt_match = PROMPT_HEADER_RE.match(stripped)
        if prompt_match:
            header_positions.append((i, prompt_match.group(1).strip(), True))
            continue
        # Few-shot example header: "XXX示例：" or "XXX：" on its own line
        # Must be a short field-name-like header, not body text or example lines
        field_match = re.match(r"^(.+?)(?:示例)[：:]$", stripped)
        if not field_match:
            field_match = re.match(r"^(.{2,8})[：:]$", stripped)
        if field_match:
            field_name = field_match.group(1).strip()
            # Exclude example-number lines (示例1, 例2) and known non-field text
            if re.match(r"^(?:示例|例)\s*\d+$", field_name):
                continue
            if field_name and "注意" not in field_name and "输出规范" not in field_name:
                header_positions.append((i, field_name, False))

    # Extract content for each section
    for idx, (start_line, field_name, is_prompt) in enumerate(header_positions):
        # For prompts, the header line itself may contain prompt text after "："
        header_line = lines[start_line].strip()
        if is_prompt:
            # Extract text after the first "：" on the header line
            colon_pos = header_line.find("：")
            if colon_pos == -1:
                colon_pos = header_line.find(":")
            header_body = header_line[colon_pos + 1:].strip() if colon_pos >= 0 else ""
            content_start = start_line + 1
        else:
            header_body = ""
            content_start = start_line + 1

        # Content ends at the next header (or EOF)
        if idx + 1 < len(header_positions):
            content_end = header_positions[idx + 1][0]
        else:
            content_end = len(lines)

        # Collect content lines
        content_parts: list[str] = []
        if header_body:
            content_parts.append(header_body)
        for j in range(content_start, content_end):
            content_parts.append(lines[j])

        content = "\n".join(content_parts).strip()
        if not content:
            continue

        if is_prompt:
            prompts[field_name] = content
        else:
            examples: list[str] = []
            for line in content.split("\n"):
                line = line.strip()
                if not line:
                    continue
                match = re.match(r"(?:示例\s*\d+|例\s*\d+)[：:]\s*(.+)", line)
                if match:
                    examples.append(match.group(1).strip())
                elif not line.startswith("示例") and not line.startswith("例"):
                    examples.append(line)
            if examples:
                sections[field_name] = examples

    return sections, prompts


def cmd_prepare(trace_path: Path, fewshot_path: Path, out_path: Path) -> None:
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    fewshot, prompts = parse_fewshot(fewshot_path)

    if not fewshot and not prompts:
        print("No few-shot sections or output-rule prompts found in fewshot.md – nothing to prepare.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"review_items": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    items = trace.get("items", [])

    review_items: list[dict] = []
    matched_fields: list[str] = []
    seen_fields: set[str] = set()

    # Process few-shot examples
    for field_name, examples in fewshot.items():
        matched = None
        for item in items:
            if item.get("item") == field_name:
                matched = item
                break

        if not matched:
            print(f"  [SKIP] {field_name}: no matching trace item found")
            continue

        if matched.get("status") not in {"filled", "uncertain"}:
            continue

        matched_fields.append(field_name)
        seen_fields.add(field_name)
        review_items.append({
            "key": matched["key"],
            "item": matched["item"],
            "section": matched.get("section", ""),
            "current_value": matched.get("value"),
            "current_status": matched.get("status"),
            "fewshot_examples": examples,
            "field_prompt": prompts.get(field_name, ""),
            "formatted_value": None,
            "format_reason": "",
            "format_decision": "",  # "accept" | "reformat" | "flag"
        })

    # Process output-rule prompts for fields without fewshot examples
    for field_name, prompt_text in prompts.items():
        if field_name in seen_fields:
            continue
        matched = None
        for item in items:
            if item.get("item") == field_name:
                matched = item
                break

        if not matched:
            print(f"  [SKIP prompt] {field_name}: no matching trace item found")
            continue

        if matched.get("status") not in {"filled", "uncertain"}:
            continue

        matched_fields.append(field_name)
        seen_fields.add(field_name)
        review_items.append({
            "key": matched["key"],
            "item": matched["item"],
            "section": matched.get("section", ""),
            "current_value": matched.get("value"),
            "current_status": matched.get("status"),
            "fewshot_examples": [],
            "field_prompt": prompt_text,
            "formatted_value": None,
            "format_reason": "",
            "format_decision": "",  # "accept" | "reformat" | "flag"
        })

    out = {
        "metadata": trace.get("metadata", {}),
        "fewshot_path": str(fewshot_path),
        "review_items": review_items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if matched_fields:
        preview = ", ".join(
            f"{ri['item']}({ri['current_value'][:40] if ri['current_value'] else 'None'}...)"
            for ri in review_items
        )
        print(f"Prepared {len(review_items)} review items: {preview}")
    else:
        print("No matching trace items for few-shot fields.")


def cmd_apply(review_path: Path, trace_path: Path, out_path: Path) -> None:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    items = trace.get("items", [])

    reformats: dict[str, dict] = {}
    for ri in review.get("review_items", []):
        if ri.get("format_decision") == "reformat" and ri.get("formatted_value"):
            reformats[ri["key"]] = ri

    if not reformats:
        print("No reformats found in review – trace unchanged.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    for item in items:
        key = item.get("key")
        if key in reformats:
            ref = reformats[key]
            old_value = item.get("value")
            new_value = ref["formatted_value"]
            item["value"] = new_value
            item["status"] = "filled"
            item["source_used"] = item.get("source_used", "方案") + " + few-shot格式化"
            old_evidence = item.get("evidence", [])
            item["evidence"] = old_evidence + [
                f"few-shot格式化: {ref.get('format_reason', '按fewshot示例格式约束输出')}",
                f"格式化前值: {old_value}",
            ]
            item["question"] = None
            print(f"REFORMATTED [{key}]: {old_value[:60] if old_value else 'None'}... → {new_value[:60]}...")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Applied {len(reformats)} reformats to trace.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Few-shot format constraint for DMP trace fields"
    )
    parser.add_argument("--mode", required=True, choices=["prepare", "apply"])
    parser.add_argument("--trace", required=True, type=Path, help="dmp_trace.json path")
    parser.add_argument("--fewshot", type=Path, help="fewshot.md path (required for prepare)")
    parser.add_argument("--review", type=Path, help="review JSON path (for apply, defaults to --out)")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    if args.mode == "prepare":
        if not args.fewshot:
            raise SystemExit("--fewshot is required for prepare mode")
        cmd_prepare(args.trace, args.fewshot, args.out)
    else:
        review_in = args.review or args.out
        cmd_apply(review_in, args.trace, args.out)


if __name__ == "__main__":
    main()
