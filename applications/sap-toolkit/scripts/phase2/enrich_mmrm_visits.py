"""Populate real visit names only for the two-group repeated-measures MMRM shell."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


TARGET_TEMPLATE_CODE = "F_G2_MMRM_02_P2"


def _safe_table_filename(table_name: str) -> str:
    return table_name.replace("/", "_").replace("\\", "_")


def _endpoint_name(table_data: dict) -> str:
    endpoint = table_data.get("endpoint", {})
    if endpoint.get("name"):
        return str(endpoint["name"])
    projects = table_data.get("projects", [])
    if projects and projects[0].get("name"):
        return str(projects[0]["name"])
    return ""


def extract_endpoint_visits(trial_flow: str, endpoint_name: str) -> list[str]:
    """Use the same trial-flow source and X-column logic used for safety visit extraction."""
    import anthropic

    from config import API_KEY, BASE_URL, MODEL
    from config.config import MAX_TOKENS

    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": f"""请从下列试验流程表中提取终点“{endpoint_name}”实际评估的访视名称。

规则：
- 与安全性访视提取一致，只查看试验流程表的实际访视/时间点列；
- 找到该终点、其同义表述或对应评估项目所在行，记录标有 X 的列；
- 使用列头中的实际访视名称，不要输出访视编号、窗口期、计划外访视或推测的名称；
- 按流程表从左到右排序并去重；
- 无法可靠判断时返回空数组。

试验流程：
{trial_flow}""",
            }
        ],
        tools=[
            {
                "name": "write_mmrm_visits",
                "description": "输出该 MMRM 终点实际评估的访视名称",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "visits": {
                            "type": "array",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["visits"],
                },
            }
        ],
        tool_choice={"type": "any"},
    )
    for content in response.content:
        if content.type == "tool_use" and content.name == "write_mmrm_visits":
            return [
                visit.strip()
                for visit in content.input.get("visits", [])
                if isinstance(visit, str) and visit.strip()
            ]
    return []


def enrich_mmrm_visits(
    output_dir: str | Path,
    visit_extractor: Callable[[str, str], list[str]] = extract_endpoint_visits,
) -> dict[str, int]:
    """Write missing real visits into F_G2_MMRM_02_P2 data files without touching other tables."""
    output_path = Path(output_dir)
    codes_path = output_path / "模板代码结果.json"
    trial_flow_path = output_path / "02_内容提取" / "试验流程.md"
    counts = {"updated": 0, "preserved": 0, "unavailable": 0}

    if not codes_path.is_file() or not trial_flow_path.is_file():
        return counts

    codes = json.loads(codes_path.read_text(encoding="utf-8"))
    trial_flow = trial_flow_path.read_text(encoding="utf-8")
    info_dir = output_path / "05_表格信息"

    for table in codes.get("tables", []):
        if table.get("template_code") != TARGET_TEMPLATE_CODE:
            continue
        table_name = table.get("name", "")
        info_path = info_dir / f"{_safe_table_filename(table_name)}.json"
        if not info_path.is_file():
            counts["unavailable"] += 1
            continue

        table_data = json.loads(info_path.read_text(encoding="utf-8"))
        if table_data.get("visits"):
            counts["preserved"] += 1
            continue

        endpoint_name = _endpoint_name(table_data)
        visits = visit_extractor(trial_flow, endpoint_name) if endpoint_name else []
        if not visits:
            counts["unavailable"] += 1
            continue

        table_data["visits"] = visits
        info_path.write_text(
            json.dumps(table_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        counts["updated"] += 1

    return counts
