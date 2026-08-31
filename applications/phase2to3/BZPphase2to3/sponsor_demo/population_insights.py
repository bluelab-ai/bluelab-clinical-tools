from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from clinical_trial_sim_engine.enrichment.final_condition_builder import (
    condition_mask,
    condition_summary_zh,
)
from clinical_trial_sim_engine.models.final_level_interactions import OUTCOMES, population
from clinical_trial_sim_engine.simulation.step24a_engine import (
    normalize_step24a_config,
    preview_source_support,
)


SMALL_CELL_LIMIT = 5


def _dose_code(config: dict[str, Any]) -> str:
    return str(config["trial"]["dose"]).replace("BZP ", "").replace(" BID", "")


def _distribution(
    full: pd.Series,
    eligible: pd.Series,
    levels: list[Any],
    labels: list[str] | None = None,
) -> list[dict[str, Any]]:
    labels = labels or [str(level) for level in levels]
    rows = []
    for level, label in zip(levels, labels):
        full_n = int(full.eq(level).sum())
        eligible_n = int(eligible.eq(level).sum())
        rows.append(
            {
                "level": label,
                "full_n": full_n,
                "full_pct": full_n / len(full) if len(full) else 0.0,
                "full_denominator": int(len(full)),
                "eligible_n": eligible_n,
                "eligible_pct": eligible_n / len(eligible) if len(eligible) else 0.0,
                "eligible_denominator": int(len(eligible)),
            }
        )
    return rows


def _binary_rows(
    full: pd.DataFrame,
    eligible: pd.DataFrame,
    column: str,
    variable: str,
    levels: list[tuple[Any, str]],
) -> list[dict[str, Any]]:
    rows = _distribution(
        full[column], eligible[column], [level for level, _ in levels], [label for _, label in levels]
    )
    for row in rows:
        row["variable"] = variable
    return rows


def _age_distribution(full: pd.DataFrame, eligible: pd.DataFrame) -> list[dict[str, Any]]:
    bins = [39, 49, 59, 64, 69, 74, 100]
    labels = ["40–49岁", "50–59岁", "60–64岁", "65–69岁", "70–74岁", "≥75岁"]
    full_group = pd.cut(full["age"], bins=bins, labels=labels, include_lowest=True)
    eligible_group = pd.cut(eligible["age"], bins=bins, labels=labels, include_lowest=True)
    return _distribution(full_group, eligible_group, labels, labels)


def _outcome_rows(frame: pd.DataFrame, dose: str, outcome: str) -> list[dict[str, Any]]:
    pair = frame[frame["dose"].isin([dose, "placebo"])]
    rows = []
    for arm_code, arm_label in ((dose, f"{dose}组"), ("placebo", "安慰剂组")):
        arm = pair[pair["dose"].eq(arm_code)]
        values = arm[outcome].dropna()
        n = int(len(arm))
        available_n = int(len(values))
        rows.append(
            {
                "arm": arm_label,
                "n": n,
                "available_n": available_n,
                "missing_n": n - available_n,
                "expected_responders": float(values.sum()) if available_n else 0.0,
                "response_rate": float(values.mean()) if available_n >= SMALL_CELL_LIMIT else None,
                "suppressed": available_n < SMALL_CELL_LIMIT,
            }
        )
    return rows


def build_population_insights(config: dict[str, Any]) -> dict[str, Any]:
    """Return aggregate-only Phase II cohort summaries for a planning configuration."""
    cfg = normalize_step24a_config(config)
    data = population()
    step = cfg["step24a"]

    nihss_mask = data["baseline_nihss"].between(step["nihss_min"], step["nihss_max"])
    after_nihss = data.loc[nihss_mask]
    final_mask = nihss_mask.copy()
    if step["conditions"]:
        final_mask &= condition_mask(data, step["conditions"])
    eligible = data.loc[final_mask].copy()

    dose = _dose_code(cfg)
    outcome = OUTCOMES[cfg["missing_death"]["sensitivity_rule"]]
    support = preview_source_support(cfg)
    outcome_rows = _outcome_rows(eligible, dose, outcome)
    full_outcome_rows = _outcome_rows(data, dose, outcome)

    dose_rows = []
    dose_labels = {"200mg": "200mg组", "400mg": "400mg组", "600mg": "600mg组", "placebo": "安慰剂组"}
    for code in ("200mg", "400mg", "600mg", "placebo"):
        dose_rows.append({"dose": dose_labels[code], "n": int(eligible["dose"].eq(code).sum())})

    characteristics = []
    characteristics.extend(_binary_rows(data, eligible, "sex_male", "性别", [(1.0, "男性"), (0.0, "女性")]))
    characteristics.extend(
        _binary_rows(data, eligible, "onset_within_24h", "发病至首次给药", [(1.0, "≤24小时"), (0.0, ">24小时")])
    )
    characteristics.extend(
        _binary_rows(data, eligible, "previous_stroke_corrected", "既往卒中", [(1.0, "有"), (0.0, "无")])
    )
    motor_full = (data["limb_motor_sum"] >= 4).astype(float)
    motor_eligible = (eligible["limb_motor_sum"] >= 4).astype(float)
    motor_rows = _distribution(motor_full, motor_eligible, [0.0, 1.0], ["较轻（<4分）", "较重（≥4分）"])
    for row in motor_rows:
        row["variable"] = "基线肢体运动缺损"
    characteristics.extend(motor_rows)

    selection_payload = {
        "dose": dose,
        "missing_rule": cfg["missing_death"]["sensitivity_rule"],
        "nihss_min": step["nihss_min"],
        "nihss_max": step["nihss_max"],
        "conditions": step["conditions"],
    }
    selection_hash = hashlib.sha256(
        json.dumps(selection_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]

    return {
        "selection_hash": selection_hash,
        "source_n": int(len(data)),
        "after_nihss_n": int(len(after_nihss)),
        "eligible_n": int(len(eligible)),
        "eligible_proportion": float(len(eligible) / len(data)) if len(data) else 0.0,
        "selected_dose_n": int(eligible["dose"].eq(dose).sum()),
        "placebo_n": int(eligible["dose"].eq("placebo").sum()),
        "dose": dose,
        "missing_rule": cfg["missing_death"]["sensitivity_rule"],
        "nihss_interval_zh": f"{step['nihss_min']}–{step['nihss_max']}分",
        "condition_summary_zh": condition_summary_zh(step["conditions"]),
        "support_status": support.get("support_status", "不可估计"),
        "support_warning_zh": support.get("support_warning_zh", ""),
        "flow": [
            {"stage": "Phase II FAS", "n": int(len(data))},
            {"stage": f"NIHSS {step['nihss_min']}–{step['nihss_max']}分", "n": int(len(after_nihss))},
            {"stage": "叠加其他条件后", "n": int(len(eligible))},
        ],
        "dose_distribution": dose_rows,
        "nihss_distribution": _distribution(
            data["baseline_nihss"], eligible["baseline_nihss"], list(range(6, 21))
        ),
        "age_distribution": _age_distribution(data, eligible),
        "mrs_distribution": _distribution(
            data["baseline_mrs"], eligible["baseline_mrs"], [2.0, 3.0, 4.0, 5.0], ["2分", "3分", "4分", "5分"]
        ),
        "characteristics": characteristics,
        "outcome": outcome_rows,
        "full_outcome": full_outcome_rows,
        "outcome_column": outcome,
        "small_cell_limit": SMALL_CELL_LIMIT,
        "contains_patient_rows": False,
    }
