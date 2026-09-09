"""Fill the single-group time-to-event shell from extracted endpoints."""

from __future__ import annotations

import copy


def _metric(row: dict, endpoint_name: str, unit: str) -> str:
    labels = row.get("label_values", [])
    metric = labels[-1] if labels else ""
    if metric == "XXX（天/月/年）":
        return f"{endpoint_name}（{unit}）"
    return metric


def _endpoint_rows(template_rows: list[dict], endpoint: dict) -> list[dict]:
    endpoint_name = str(endpoint.get("name") or endpoint.get("endpoint") or "指标XXX")
    unit = str(endpoint.get("unit") or "天")
    rows = []

    for index, template_row in enumerate(template_rows):
        rows.append(
            {
                "indicator": endpoint_name if index == 0 else "",
                "metric": _metric(template_row, endpoint_name, unit),
                "values": list(template_row.get("data_values", [""])),
                "applies_to": list(template_row.get("applies_to", [])),
            }
        )

    return rows


def fill_template(semantic: dict, projects: list[dict]) -> dict:
    """Repeat the original single-group TTE block once for each endpoint."""
    result = copy.deepcopy(semantic)
    sections = result.get("sections", [])
    template_rows = sections[0].get("rows", []) if sections else []

    rows = []
    for endpoint in projects:
        if isinstance(endpoint, dict):
            rows.extend(_endpoint_rows(template_rows, endpoint))

    result["rows"] = rows
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result
