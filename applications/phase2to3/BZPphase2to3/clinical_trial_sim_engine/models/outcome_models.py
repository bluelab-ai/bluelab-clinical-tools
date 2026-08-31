from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "outputs/step19_dynamic_chinese_mvp/model_assets/effect_source_registry.csv"

ENDPOINT_LABELS = {
    "day90_mrs01": "Day90 mRS 0-1应答",
    "day90_mrs02": "Day90 mRS 0-2应答",
    "day90_mrs_ordinal": "Day90 mRS等级位移",
    "day14_nihss_change": "Day14 NIHSS较基线变化",
    "day14_nihss_response": "Day14 NIHSS应答",
}


def _rows() -> list[dict[str, str]]:
    with REGISTRY.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def get_effect_source(config: dict[str, Any]) -> dict[str, Any]:
    trial, endpoint, missing = config["trial"], config["endpoint"], config["missing_death"]
    target = {
        "endpoint": endpoint["primary_endpoint"],
        "dose": trial["dose"],
        "population": trial["population"],
        "missing_rule": missing.get("sensitivity_rule", "death6_conservative_nonresponder"),
    }
    candidates = [row for row in _rows() if all(row.get(key) == value for key, value in target.items())]
    if not candidates and trial["population"] != "phase2_2026_allcomers":
        target["population"] = "phase2_2026_allcomers"
        candidates = [row for row in _rows() if all(row.get(key) == value for key, value in target.items())]
    if not candidates:
        raise ValueError(f"不支持的效应源组合：{target}")
    row = candidates[0]
    if row.get("supported", "yes") != "yes":
        raise ValueError(f"效应源未通过支持性审核：{target}")
    numeric = ["control_outcome", "treatment_effect", "uncertainty_estimate", "residual_sd", "source_n"]
    result: dict[str, Any] = dict(row)
    for key in numeric:
        result[key] = float(row[key]) if row.get(key) not in (None, "") else None
    return result


def effective_effect(source: dict[str, Any], shrinkage: float) -> float:
    retained = min(max(1.0 - float(shrinkage), 0.0), 1.0)
    return float(source["treatment_effect"]) * retained
