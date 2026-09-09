#!/usr/bin/env python3
"""Fill the two-group time-to-event shell from extracted endpoints."""

from __future__ import annotations

import copy


TRIAL_GROUP = "试验组 (N=n1)"
CONTROL_GROUP = "对照组 (N=n1)"


def _metric(row: dict, endpoint_name: str, unit: str) -> str:
    labels = row.get("label_values", [])
    metric = labels[-1] if labels else ""
    if metric == "XXX（天/月/年）":
        return f"{endpoint_name}（{unit}）"
    return metric


def _row(indicator: str, metric: str, values: list[str], applies_to: list[str]) -> dict:
    return {
        "indicator": indicator,
        "metric": metric,
        "values": values,
        "applies_to": applies_to,
    }


def _separator() -> dict:
    return _row("", "", ["", ""], [])


def _endpoint_rows(sections: list[dict], endpoint: dict) -> list[dict]:
    endpoint_name = str(endpoint.get("name") or endpoint.get("endpoint") or "指标XXX")
    unit = str(endpoint.get("unit") or "天")
    section_by_type = {section.get("type"): section for section in sections}
    rows = []

    for index, row in enumerate(section_by_type["indicator_group"]["rows"]):
        rows.append(
            _row(
                endpoint_name if index == 0 else "",
                _metric(row, endpoint_name, unit),
                row.get("data_values", ["", ""]),
                row.get("applies_to", [TRIAL_GROUP, CONTROL_GROUP]),
            )
        )

    rows.append(_separator())

    for row in section_by_type["survival_time"]["rows"]:
        rows.append(
            _row(
                "",
                _metric(row, endpoint_name, unit),
                row.get("data_values", ["", ""]),
                row.get("applies_to", [TRIAL_GROUP, CONTROL_GROUP]),
            )
        )

    rows.append(_separator())
    rows.append(_row("", "Logrank检验", ["", ""], []))
    for row in section_by_type["logrank_test"]["rows"]:
        rows.append(
            _row(
                "",
                _metric(row, endpoint_name, unit),
                row.get("data_values", ["", ""]),
                row.get("applies_to", [TRIAL_GROUP]),
            )
        )

    rows.append(_separator())
    rows.append(_row("", "Cox回归", ["", ""], []))
    for row in section_by_type["cox_regression"]["rows"]:
        rows.append(
            _row(
                "",
                _metric(row, endpoint_name, unit),
                row.get("data_values", ["", ""]),
                row.get("applies_to", [TRIAL_GROUP]),
            )
        )

    return rows


def fill_template(semantic: dict, projects: list[dict]) -> dict:
    """Create one repeated row sequence for every extracted survival endpoint."""
    result = copy.deepcopy(semantic)
    sections = result.get("sections", [])
    rows = []

    for endpoint in projects:
        if isinstance(endpoint, dict):
            rows.extend(_endpoint_rows(sections, endpoint))

    result["rows"] = rows
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result
