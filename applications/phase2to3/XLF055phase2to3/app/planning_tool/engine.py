"""Thin frontend adapter for the registered V2.3 scenario backend.

No statistical formula is implemented in this module. All scenario computation
is delegated to the registered trial-specific backend.
"""

from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path
import sys
from typing import Any

import pandas as pd


# Pandas 3 defaults inferred strings to Arrow; Streamlit executes in a worker
# thread where the installed Arrow build is unsafe. Python-backed strings keep
# identical values while avoiding the native-thread crash.
pd.options.mode.string_storage = "python"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.recurrence_scenario_engine_v2_3 import (  # noqa: E402
    RecurrenceScenarioEngineV23,
)


ENGINE_VERSION = "2.3.0"
REGISTRY_RELATIVE = (
    "outputs/model_registry/v2_3/"
    "registered_arm_scenario_backend_candidate.json"
)
SUBJECT_MASTER_RELATIVE = "outputs/analysis_datasets/phase2_subject_master.parquet"
RECURRENCE_ANALYSIS_RELATIVE = (
    "outputs/analysis_datasets/phase2_recurrence_analysis.parquet"
)
POPULATION_FEATURES = (
    "age_years",
    "baseline_bmi",
    "baseline_vaginal_ph",
    "baseline_nugent_score",
    "baseline_av_score",
    "any_medical_history",
    "baseline_lactobacillus_grade",
)
RECURRENCE_OUTCOME_COLUMN = "recurrence_by_d104_observed"
POPULATION_SCOPES: dict[str, dict[str, Any]] = {
    "fas_ss": {
        "label": "FAS / 安全集",
        "description": "进入二期主要疗效与安全性分析的74名受试者。",
        "expected_n": 74,
    },
    "pps": {
        "label": "符合方案集（PPS）",
        "description": "符合方案分析要求的57名受试者。",
        "expected_n": 57,
    },
    "d24_cured": {
        "label": "D24治愈目标人群",
        "description": "二期D24达到治愈、进入后续复发问题的34名受试者。",
        "expected_n": 34,
    },
    "d104_evaluable": {
        "label": "D104可评价人群",
        "description": "D24治愈且D104累计复发结局明确的31名受试者，也是当前模型的来源人群。",
        "expected_n": 31,
    },
}
POPULATION_OUTCOME_GROUPS: dict[str, dict[str, Any]] = {
    "all": {
        "label": "全部所选人群",
        "description": "不按D104结局进一步分组。",
        "expected_n": None,
    },
    "d104_evaluable": {
        "label": "D104可评价",
        "description": "D104累计复发结局明确。",
        "expected_n": 31,
    },
    "d104_recurrence": {
        "label": "D104观察复发",
        "description": "D104可评价且观察到复发。",
        "expected_n": 16,
    },
    "d104_nonrecurrence": {
        "label": "D104观察未复发",
        "description": "D104可评价且未观察到复发。",
        "expected_n": 15,
    },
    "d104_unknown": {
        "label": "D104结局未知",
        "description": "D24治愈，但D104累计复发结局不能明确判断。",
        "expected_n": 3,
    },
}
OUTCOME_GROUPS_BY_POPULATION = {
    "fas_ss": ("all",),
    "pps": ("all",),
    "d24_cured": (
        "all",
        "d104_evaluable",
        "d104_recurrence",
        "d104_nonrecurrence",
        "d104_unknown",
    ),
    "d104_evaluable": (
        "all",
        "d104_recurrence",
        "d104_nonrecurrence",
    ),
}


@lru_cache(maxsize=1)
def registered_engine() -> RecurrenceScenarioEngineV23:
    """Load the registered backend once per application process."""
    engine = RecurrenceScenarioEngineV23(PROJECT_ROOT / REGISTRY_RELATIVE)
    # Pandas 3 may retain Arrow-backed strings from Parquet. Converting this
    # 31-row support-only table to plain objects avoids an Arrow thread crash
    # under Streamlit; values, distances, thresholds and model draws are unchanged.
    engine.support_source = engine.support_source.astype(object).copy(deep=True)
    return engine


def evaluate_scenario(
    scenario: dict[str, Any], config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Evaluate a scenario without persistence or input echo."""
    del config
    return registered_engine().evaluate(scenario)


def engine_health() -> dict[str, Any]:
    engine = registered_engine()
    return {
        "status": "ready",
        "engine_version": ENGINE_VERSION,
        "registry_status": engine.registry["status"],
        "evidence_status": engine.registry["evidence_status"],
        "model_version": engine.registry["model_version"],
        "support_threshold_q75": engine.support_threshold,
        "source_observed_labels": 31,
        "source_events": 16,
        "patient_input_persistence": False,
        "artifact_hashes_verified": True,
    }


@lru_cache(maxsize=1)
def phase2_population_sources() -> dict[str, pd.DataFrame]:
    """Load governed Phase II analysis populations for aggregate display only."""
    master = pd.read_parquet(PROJECT_ROOT / SUBJECT_MASTER_RELATIVE)
    recurrence = pd.read_parquet(PROJECT_ROOT / RECURRENCE_ANALYSIS_RELATIVE)
    required_master = {*POPULATION_FEATURES, "fas_flag", "safety_flag", "pps_flag"}
    required_recurrence = {*POPULATION_FEATURES, RECURRENCE_OUTCOME_COLUMN}
    if not required_master.issubset(master.columns):
        raise RuntimeError("Phase II subject-master population contract failed")
    if not required_recurrence.issubset(recurrence.columns):
        raise RuntimeError("Phase II recurrence population contract failed")
    if len(master) != 144 or len(recurrence) != 34:
        raise RuntimeError("Phase II governed population counts changed")

    frames = {
        "fas_ss": master.loc[
            master["fas_flag"].eq(1) & master["safety_flag"].eq(1),
            list(POPULATION_FEATURES),
        ],
        "pps": master.loc[
            master["pps_flag"].eq(1), list(POPULATION_FEATURES)
        ],
        "d24_cured": recurrence.loc[
            :, [*POPULATION_FEATURES, RECURRENCE_OUTCOME_COLUMN]
        ],
        "d104_evaluable": recurrence.loc[
            recurrence[RECURRENCE_OUTCOME_COLUMN].notna(),
            [*POPULATION_FEATURES, RECURRENCE_OUTCOME_COLUMN],
        ],
    }
    for scope, frame in frames.items():
        expected_n = int(POPULATION_SCOPES[scope]["expected_n"])
        if len(frame) != expected_n:
            raise RuntimeError(f"Unexpected Phase II population count: {scope}")
        frames[scope] = frame.astype(object).copy(deep=True)
    return frames


def population_summary(
    filters: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    population_scope: str = "d104_evaluable",
    outcome_group: str = "all",
) -> dict[str, Any]:
    """Return aggregate-only Phase II population information.

    Filters are limited to registered baseline fields. This authorized
    screening view returns exact aggregate counts, including groups below five.
    """
    del config
    engine = registered_engine()
    payload = engine.payload
    support_reference = engine.support_reference
    if population_scope not in POPULATION_SCOPES:
        raise ValueError("Unknown Phase II population scope")
    if outcome_group not in OUTCOME_GROUPS_BY_POPULATION[population_scope]:
        raise ValueError("Outcome group is unavailable for the selected population")
    source = phase2_population_sources()[population_scope].copy(deep=True)
    scope_contract = POPULATION_SCOPES[population_scope]
    outcome_contract = POPULATION_OUTCOME_GROUPS[outcome_group]
    if outcome_group == "d104_evaluable":
        source = source[source[RECURRENCE_OUTCOME_COLUMN].notna()]
    elif outcome_group == "d104_recurrence":
        source = source[source[RECURRENCE_OUTCOME_COLUMN].eq(1)]
    elif outcome_group == "d104_nonrecurrence":
        source = source[source[RECURRENCE_OUTCOME_COLUMN].eq(0)]
    elif outcome_group == "d104_unknown":
        source = source[source[RECURRENCE_OUTCOME_COLUMN].isna()]
    expected_outcome_n = outcome_contract["expected_n"]
    if expected_outcome_n is not None and len(source) != int(expected_outcome_n):
        raise RuntimeError("Unexpected Phase II outcome-group count")
    source = source.loc[:, list(POPULATION_FEATURES)]
    source_n = int(len(source))
    selected = source.copy(deep=True)
    filters = filters or {}
    active_filter_labels: list[str] = []

    numeric_specs = {
        "age_years": ("年龄", "岁"),
        "baseline_bmi": ("BMI", ""),
        "baseline_vaginal_ph": ("阴道pH", ""),
    }
    for field, (label, unit) in numeric_specs.items():
        key = f"{field}_range"
        if key not in filters:
            continue
        values = filters[key]
        if not isinstance(values, (list, tuple)) or len(values) != 2:
            raise ValueError(f"Invalid aggregate filter: {key}")
        lower, upper = float(values[0]), float(values[1])
        if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
            raise ValueError(f"Invalid aggregate filter bounds: {key}")
        selected = selected[
            selected[field].notna()
            & selected[field].astype(float).between(lower, upper, inclusive="both")
        ]
        active_filter_labels.append(f"{label} {lower:g}–{upper:g}{unit}")

    value_specs: dict[str, tuple[str, set[object]]] = {
        "baseline_nugent_score": ("Nugent评分", {7.0, 8.0, 9.0, 10.0}),
        "baseline_av_score": ("AV评分", {0.0, 1.0, 2.0, 3.0, 4.0}),
        "any_medical_history": ("既往病史", {0, 1}),
        "baseline_lactobacillus_grade": (
            "乳杆菌分级",
            {"I级或II级", "III级或IV级"},
        ),
    }
    for field, (label, allowed) in value_specs.items():
        key = f"{field}_values"
        if key not in filters:
            continue
        raw_values = filters[key]
        if not isinstance(raw_values, (list, tuple, set)) or not raw_values:
            raise ValueError(f"Invalid aggregate filter: {key}")
        values = set(raw_values)
        if not values.issubset(allowed):
            raise ValueError(f"Unregistered aggregate filter values: {key}")
        selected = selected[selected[field].isin(values)]
        display_values = []
        for value in sorted(values, key=str):
            if field == "any_medical_history":
                display_values.append("有" if int(value) == 1 else "无")
            else:
                display_values.append(
                    f"{value:g}" if isinstance(value, float) else str(value)
                )
        active_filter_labels.append(f"{label}：{'、'.join(display_values)}")

    selected_n = int(len(selected))

    def summarize_numeric(frame: pd.DataFrame) -> list[dict[str, Any]]:
        rows = []
        denominator = int(len(frame))
        for field in payload["source_support"]["numeric_ranges"]:
            values = pd.to_numeric(frame[field], errors="coerce").dropna()
            if values.empty:
                continue
            rows.append(
                {
                    "field": field,
                    "source_n": int(values.size),
                    "minimum": float(values.min()),
                    "median": float(values.median()),
                    "maximum": float(values.max()),
                    "missing_n_in_selected": denominator - int(values.size),
                    "missing_n_in_scope": denominator - int(values.size),
                }
            )
        return rows

    full_numeric = summarize_numeric(source)
    numeric = summarize_numeric(selected)
    numeric_distributions: dict[str, list[dict[str, Any]]] = {}
    full_by_field = {row["field"]: row for row in full_numeric}
    for field in payload["source_support"]["numeric_ranges"]:
        values = pd.to_numeric(selected[field], errors="coerce").dropna()
        if values.empty:
            numeric_distributions[field] = []
            continue
        if field in {"baseline_nugent_score", "baseline_av_score"}:
            counts = values.value_counts().sort_index()
            numeric_distributions[field] = [
                {
                    "category": f"{float(category):g}",
                    "count": int(count),
                    "percentage": float(count) / selected_n,
                    "small_cell": int(count) < 5,
                }
                for category, count in counts.items()
            ]
            continue
        full = full_by_field[field]
        lower = float(full["minimum"])
        upper = float(full["maximum"])
        if math.isclose(lower, upper):
            numeric_distributions[field] = [
                {
                    "category": f"{lower:g}",
                    "count": int(values.size),
                    "percentage": float(values.size) / selected_n,
                    "small_cell": int(values.size) < 5,
                }
            ]
            continue
        step = (upper - lower) / 4.0
        edges = [lower + step * index for index in range(5)]
        edges[-1] = upper + max(abs(upper), 1.0) * 1e-10
        labels = [
            f"{edges[index]:.1f}–{(upper if index == 3 else edges[index + 1]):.1f}"
            for index in range(4)
        ]
        binned = pd.cut(
            values,
            bins=edges,
            labels=labels,
            include_lowest=True,
            right=False,
        )
        counts = binned.value_counts(sort=False)
        numeric_distributions[field] = [
            {
                "category": str(category),
                "count": int(count),
                "percentage": float(count) / selected_n,
                "small_cell": int(count) < 5,
            }
            for category, count in counts.items()
            if int(count) > 0
        ]
    category_counts: dict[str, dict[str, int]] = {}
    for field in ["any_medical_history", "baseline_lactobacillus_grade"]:
        values = selected[field].astype(object).where(
            selected[field].notna(), "missing"
        )
        category_counts[field] = {
            str(category): int(count)
            for category, count in values.value_counts(dropna=False).items()
        }

    return {
        "status": "limited",
        "planning_stage": True,
        "source_population": {
            "screened_n": 144,
            "fas_ss_n": 74,
            "pps_n": 57,
            "d24_cured_n": 34,
            "d104_observed_n": 31,
            "d104_recurrence_n": 16,
            "d104_nonrecurrence_n": 15,
            "d104_unknown_n": 3,
            "observed_rate": 16 / 31,
            "composite_sensitivity_rate": 19 / 34,
        },
        "population_scope": {
            "id": population_scope,
            "label": str(scope_contract["label"]),
            "description": str(scope_contract["description"]),
            "source_n": source_n,
            "model_source_population": population_scope == "d104_evaluable",
        },
        "outcome_group": {
            "id": outcome_group,
            "label": str(outcome_contract["label"]),
            "description": str(outcome_contract["description"]),
            "source_n": source_n,
            "outcome_defined": outcome_group != "all",
        },
        "filter_summary": {
            "active": bool(active_filter_labels),
            "labels": active_filter_labels,
            "status": "empty" if selected_n == 0 else "available",
            "selected_n": selected_n,
            "selected_n_display": str(selected_n),
            "source_n": source_n,
            "retention_rate": selected_n / source_n if source_n else 0.0,
            "retention_display": (
                f"{100 * selected_n / source_n:.1f}%" if source_n else "0.0%"
            ),
            "endpoint_rate_available": False,
        },
        "full_numeric_summaries": full_numeric,
        "numeric_summaries": numeric,
        "numeric_distributions": numeric_distributions,
        "category_counts": category_counts,
        "joint_support": {
            "method": "leave-one-out mean 5-nearest-neighbor Gower distance",
            "reference_n": 31,
            "applicable_to_population_scope": population_scope == "d104_evaluable",
            "grade_a_threshold_q75": engine.support_threshold,
            "minimum": support_reference["aggregate_reference"][
                "leave_one_out_mean_5nn"
            ]["minimum"],
            "median": support_reference["aggregate_reference"][
                "leave_one_out_mean_5nn"
            ]["median"],
            "maximum": support_reference["aggregate_reference"][
                "leave_one_out_mean_5nn"
            ]["maximum"],
        },
        "small_cell_policy": (
            "exact aggregate counts are displayed for the authorized screening workflow"
        ),
        "treatment_specific_output": "not displayed",
        "privacy": (
            "aggregate only; no patient rows or identifiers; exact counts enabled "
            "for authorized screening"
        ),
    }


def warning_catalog() -> dict[str, dict[str, str]]:
    engine = registered_engine()
    return dict(engine.warning_catalog)


def registry_snapshot() -> dict[str, Any]:
    """Return a safe, aggregate registry subset for reports."""
    engine = registered_engine()
    registry = engine.registry
    return {
        "engine_version": registry["engine_version"],
        "model_version": registry["model_version"],
        "status": registry["status"],
        "evidence_status": registry["evidence_status"],
        "support_threshold_q75": registry["support_reference"][
            "grade_a_threshold_q75"
        ],
        "internal_validation": registry["internal_validation"],
        "release_conditions": registry["release_conditions"],
    }


def deterministic_signature(payload: dict[str, Any]) -> str:
    """Stable JSON for session-only duplicate detection; never written to logs."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
