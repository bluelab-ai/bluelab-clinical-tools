#!/usr/bin/env python3
"""V2.2 local exploratory D104 recurrence-scenario backend.

The engine reuses the registered V2.1 model without refitting. It adds the
frozen V2.2 relative-position, stability, joint-support and age-only
extrapolation contract. It never logs, persists, or echoes case values.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPTS))

from v21_bayesian_core import (  # noqa: E402
    FittedPreprocessor,
    P3_CONTROL,
    interval,
    treatment_blind_draw_probabilities,
)


VERSION = "2.2.0"
CORE_NUMERIC = [
    "age_years",
    "baseline_bmi",
    "baseline_vaginal_ph",
    "baseline_nugent_score",
]
SECONDARY = [
    "baseline_av_score",
    "any_medical_history",
    "baseline_lactobacillus_grade",
]
CONTINUOUS = CORE_NUMERIC + ["baseline_av_score"]
CATEGORICAL = ["any_medical_history", "baseline_lactobacillus_grade"]
SUPPORT_FIELDS = CONTINUOUS + CATEGORICAL
ALLOWED_KEYS = set(CORE_NUMERIC + SECONDARY + ["d21_status", "mode"])
ALLOWED_MODES = {"data_supported", "exploratory_age_extrapolation"}
ALWAYS_WARNING_IDS = ["W001", "W002", "W003", "W004", "W005", "W013", "W014"]
PROHIBITED_LABELS = [
    "高风险患者",
    "中风险患者",
    "低风险患者",
    "准确概率",
    "真实个体风险",
    "AI预测",
    "三期成功率",
]
LACTO_TO_SOURCE = {
    "I_or_II": "I级或II级",
    "III_or_IV": "III级或IV级",
}
POSITION_LABELS = {
    "relative_higher_scenario": "相对偏高情景",
    "near_anchor_or_direction_uncertain": "接近人群锚点或方向不确定",
    "relative_lower_scenario": "相对偏低情景",
}
STABILITY_LABELS = {
    "insufficient": "方向证据不足",
    "low": "低稳定性",
    "moderate": "中等稳定性",
    "relatively_stable": "相对稳定",
}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() == "missing":
        return True
    return False


class RecurrenceScenarioEngineV22:
    """Deterministic, local, frontend-integration backend with strict gates."""

    def __init__(
        self,
        registry_path: str | Path | None = None,
        *,
        allow_validated_candidate: bool = False,
    ) -> None:
        if registry_path is None:
            registry_path = (
                ROOT
                / "outputs"
                / "model_registry"
                / "v2_2"
                / "registered_frontend_ready_limited_scenario_engine.json"
            )
        self.registry_path = Path(registry_path)
        if self.registry_path.exists():
            self.registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if self.registry["status"] != "registered_frontend_ready_limited_scenario_engine":
                raise RuntimeError("Registry is not released for V2.2 frontend integration")
            self._load(verify_hashes=True)
        elif allow_validated_candidate:
            v21_path = (
                ROOT
                / "outputs"
                / "model_registry"
                / "v2_1"
                / "registered_limited_scenario_engine.json"
            )
            v21 = json.loads(v21_path.read_text(encoding="utf-8"))
            self.registry = {
                "status": "validated_candidate_backend_test_only",
                "engine_version": "2.2.0-candidate",
                "model_version": v21["model_version"],
                "model_payload": v21["model_payload"],
                "posterior_draws": v21["posterior_draws"],
                "direction_evidence": v21["direction_evidence"],
                "cv_summary": v21["cv_summary"],
                "source_data": v21["source_data"],
                "sha256": v21["sha256"],
                "support_reference": {
                    "relative_path": "outputs/model_development/v2_2_backend_extension/support_reference_v2_2.json",
                },
                "warning_catalog": {
                    "relative_path": "outputs/frontend_freeze_v2_2/warning_catalog_v2_2.csv",
                },
            }
            self._load(verify_hashes=False)
        else:
            raise RuntimeError("Registered V2.2 limited scenario engine is unavailable")

    def _load(self, verify_hashes: bool) -> None:
        payload_path = ROOT / self.registry["model_payload"]
        draws_path = ROOT / self.registry["posterior_draws"]
        direction_path = ROOT / self.registry["direction_evidence"]
        cv_path = ROOT / self.registry["cv_summary"]
        support_path = ROOT / self.registry["support_reference"]["relative_path"]
        warning_path = ROOT / self.registry["warning_catalog"]["relative_path"]
        data_path = ROOT / self.registry["source_data"]["relative_path"]
        if verify_hashes:
            expected = self.registry["sha256"]
            actual = {
                "model_payload": sha256(payload_path),
                "posterior_draws": sha256(draws_path),
                "direction_evidence": sha256(direction_path),
                "cv_summary": sha256(cv_path),
            }
            if actual != expected:
                raise RuntimeError("Registered model artifact hash mismatch")
            if sha256(support_path) != self.registry["support_reference"]["sha256"]:
                raise RuntimeError("Registered support-reference hash mismatch")
            if sha256(warning_path) != self.registry["warning_catalog"]["sha256"]:
                raise RuntimeError("Registered warning-catalog hash mismatch")
            if sha256(data_path) != self.registry["source_data"]["sha256"]:
                raise RuntimeError("Registered source-analysis-data hash mismatch")

        self.payload = json.loads(payload_path.read_text(encoding="utf-8"))
        self.draws = np.load(draws_path)["draws"]
        if self.draws.shape[0] != 20000 or not np.isfinite(self.draws).all():
            raise RuntimeError("Registered posterior draws invalid")
        self.preprocessor = FittedPreprocessor.from_dict(self.payload["preprocessor"])
        self.directions = pd.read_csv(direction_path)
        self.cv_summary = pd.read_csv(cv_path).set_index("model_id")
        self.support_reference = json.loads(support_path.read_text(encoding="utf-8"))
        self.support_threshold = float(
            self.support_reference["aggregate_reference"]["grade_a_threshold_q75"]
        )
        self.ranges = {
            field: (
                float(spec["minimum"]),
                float(spec["maximum"]),
            )
            for field, spec in self.support_reference["algorithm"][
                "continuous_ranges"
            ].items()
        }
        source = pd.read_parquet(data_path)
        source = source.loc[
            source["recurrence_by_d104_observed"].notna(), SUPPORT_FIELDS
        ].reset_index(drop=True)
        if len(source) != 31:
            raise RuntimeError("Support reference population must contain 31 records")
        self.support_source = source
        with warning_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.warning_catalog = {row["warning_id"]: row for row in rows}
        if set(ALWAYS_WARNING_IDS) - set(self.warning_catalog):
            raise RuntimeError("Warning catalog is incomplete")

    @staticmethod
    def input_schema() -> dict[str, Any]:
        return {
            "contract_version": VERSION,
            "required_core": CORE_NUMERIC + ["d21_status"],
            "optional_secondary": SECONDARY,
            "mode": sorted(ALLOWED_MODES),
            "categories": {
                "any_medical_history": ["yes", "no", "missing"],
                "baseline_lactobacillus_grade": [
                    "I_or_II",
                    "III_or_IV",
                    "missing",
                ],
                "d21_status": ["pending", "cured", "not_cured"],
            },
            "prohibited": [
                "randomized treatment arm",
                "post-dose variables",
                "adverse events",
                "direct identifiers",
                "ongoing Phase III outcomes",
            ],
        }

    def anchors(self) -> dict[str, Any]:
        return {
            "primary_observed": {
                "status": "observed",
                "population": "Phase II D24-cured FAS with observed D104 classification",
                "events": 16,
                "n": 31,
                "rate": self.payload["anchors"]["observed"]["rate"],
                "uncertainty_method": "Jeffreys binomial interval",
                "lower_95": self.payload["anchors"]["observed"]["jeffreys_95"][0],
                "upper_95": self.payload["anchors"]["observed"]["jeffreys_95"][1],
                "missing_rule": "No recurrence requires observed D104; otherwise unknown.",
            },
            "composite_sensitivity": {
                "status": "observed_sensitivity",
                "population": "All Phase II D24-cured FAS",
                "events": 19,
                "n": 34,
                "rate": self.payload["anchors"]["composite_sensitivity"]["rate"],
                "missing_rule": "Unknown without earlier recurrence counted as recurrence.",
            },
        }

    def _warnings(self, warning_ids: list[str]) -> list[dict[str, str]]:
        ordered = []
        seen = set()
        for warning_id in warning_ids:
            if warning_id in seen:
                continue
            seen.add(warning_id)
            row = self.warning_catalog[warning_id]
            ordered.append(
                {
                    "id": warning_id,
                    "severity": row["severity"],
                    "message": row["display_zh"],
                    "placement": row["placement"],
                }
            )
        return ordered

    def _base(self, status: str, extra_warning_ids: list[str] | None = None) -> dict:
        warning_ids = ALWAYS_WARNING_IDS + list(extra_warning_ids or [])
        return {
            "contract_version": VERSION,
            "engine_status": status,
            "output_name": "二期数据锚定的探索性D104复发情景估计",
            "evidence_status": "limited_scenario_only",
            "anchors": self.anchors(),
            "warning_ids": list(dict.fromkeys(warning_ids)),
            "warnings": self._warnings(warning_ids),
            "provenance": {
                "engine_version": self.registry["engine_version"],
                "model_version": self.registry["model_version"],
                "target": "BV recurrence through D104 conditional on protocol-defined D21 cure",
                "source_population": "Phase II D24±3-cured FAS",
                "source_observed_labels": 31,
                "source_events": 16,
                "primary_missing_rule": "observed-label",
                "model_status": "modeled_exploratory",
                "validated_individual_probability": False,
                "risk_ranking_supported": False,
                "ongoing_phase3_outcomes_used": False,
            },
        }

    def _unavailable(
        self,
        status: str,
        reason_codes: list[str],
        extra_warning_ids: list[str] | None = None,
    ) -> dict:
        result = self._base(status, list(extra_warning_ids or []) + ["W011"])
        result["reason_codes"] = reason_codes
        result["scenario_estimate"] = None
        result["scenario_position"] = None
        result["direction_stability"] = None
        result["direction_panel"] = []
        result["support"] = {
            "grade": "unavailable",
            "display_zh": "不可计算",
            "reason_codes": reason_codes,
        }
        return result

    def _parse_numeric(
        self, request: dict[str, Any], field: str, *, required: bool
    ) -> tuple[float | None, str | None]:
        value = request.get(field)
        if is_missing(value):
            return None, ("missing_core" if required else None)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None, "not_finite_numeric"
        if not math.isfinite(numeric):
            return None, "not_finite_numeric"
        return numeric, None

    @staticmethod
    def _is_integer(value: float) -> bool:
        return abs(value - round(value)) <= 1e-12

    def _pair_distance(
        self, profile: dict[str, Any], source_row: pd.Series
    ) -> tuple[float, int]:
        components: list[float] = []
        for field in CONTINUOUS:
            left = profile.get(field)
            right = source_row[field]
            if left is None or pd.isna(right):
                continue
            low, high = self.ranges[field]
            components.append(min(abs(float(left) - float(right)) / (high - low), 1.0))
        for field in CATEGORICAL:
            left = profile.get(field)
            right = source_row[field]
            if left is None or pd.isna(right):
                continue
            components.append(0.0 if str(left) == str(right) else 1.0)
        if len(components) < 5:
            return float("nan"), len(components)
        return float(np.mean(components)), len(components)

    def _support(
        self,
        profile: dict[str, Any],
        *,
        age_extrapolated: bool,
        missing_secondary: list[str],
    ) -> dict[str, Any]:
        distances = []
        minimum_comparable = 7
        maximum_comparable = 0
        for _, row in self.support_source.iterrows():
            distance, comparable = self._pair_distance(profile, row)
            minimum_comparable = min(minimum_comparable, comparable)
            maximum_comparable = max(maximum_comparable, comparable)
            if np.isfinite(distance):
                distances.append(distance)
        if len(distances) < 5:
            return {
                "grade": "unavailable",
                "display_zh": "不可计算",
                "reason_codes": ["fewer_than_five_valid_reference_neighbors"],
                "valid_reference_neighbors": len(distances),
                "reference_n": 31,
            }
        mean_5nn = float(np.mean(np.sort(np.asarray(distances))[:5]))
        if age_extrapolated:
            grade = "C"
            display = "C：探索性外推"
            reasons = ["age_only_extrapolation_opted_in"]
        elif missing_secondary or mean_5nn > self.support_threshold:
            grade = "B"
            display = "B：组合稀疏或信息不完整"
            reasons = []
            if missing_secondary:
                reasons.append("secondary_input_missing")
            if mean_5nn > self.support_threshold:
                reasons.append("sparse_joint_profile")
        else:
            grade = "A"
            display = "A：来源数据支持较好"
            reasons = ["within_source_range_common_profile"]
        return {
            "grade": grade,
            "display_zh": display,
            "reason_codes": reasons,
            "joint_distance_mean_5nn": mean_5nn,
            "grade_a_threshold_q75": self.support_threshold,
            "valid_reference_neighbors": len(distances),
            "reference_n": 31,
            "minimum_comparable_fields_across_valid_pairs": minimum_comparable,
            "maximum_comparable_fields": maximum_comparable,
            "optional_inputs_complete": not missing_secondary,
            "extrapolation": "age_only" if age_extrapolated else "none",
        }

    @staticmethod
    def _position(above: float, below: float) -> tuple[str, str]:
        if above >= 0.60:
            value = "relative_higher_scenario"
        elif below >= 0.60:
            value = "relative_lower_scenario"
        else:
            value = "near_anchor_or_direction_uncertain"
        return value, POSITION_LABELS[value]

    @staticmethod
    def _stability(score: float) -> tuple[str, str]:
        if score < 0.60:
            value = "insufficient"
        elif score < 0.70:
            value = "low"
        elif score < 0.80:
            value = "moderate"
        else:
            value = "relatively_stable"
        return value, STABILITY_LABELS[value]

    def evaluate(self, request: dict[str, Any]) -> dict:
        """Evaluate one scenario without logging, persisting, or echoing inputs."""
        if not isinstance(request, dict):
            return self._unavailable("invalid_input", ["request_not_json_object"])
        extra = sorted(set(request) - ALLOWED_KEYS)
        if extra:
            return self._unavailable(
                "invalid_input",
                ["unknown_or_prohibited_fields"],
            )

        mode = request.get("mode", "data_supported")
        if mode == "clinical_assumption":
            result = self._unavailable(
                "assumption_mode_unavailable",
                ["clinical_assumption_parameters_not_registered"],
                ["W012"],
            )
            return result
        if mode not in ALLOWED_MODES:
            return self._unavailable("invalid_input", ["invalid_mode"])

        d21 = request.get("d21_status")
        if d21 is None:
            return self._unavailable(
                "anchors_only_missing_core", ["missing_core_d21_status"]
            )
        if d21 not in {"pending", "cured", "not_cured"}:
            return self._unavailable("invalid_input", ["invalid_d21_status"])
        if d21 == "not_cured":
            result = self._base("not_applicable", ["W010"])
            result["d21_workflow"] = {
                "status": "not_cured",
                "interpretation": "D104复发情景不适用；当前为D21未治愈。",
            }
            result["reason_codes"] = ["d21_not_cured"]
            result["scenario_estimate"] = None
            result["scenario_position"] = None
            result["direction_stability"] = None
            result["direction_panel"] = []
            result["support"] = {
                "grade": "not_evaluated",
                "display_zh": "未评估：D21未治愈",
                "reason_codes": ["d21_not_cured"],
            }
            return result

        profile: dict[str, Any] = {}
        missing_core = []
        for field in CORE_NUMERIC:
            value, error = self._parse_numeric(request, field, required=True)
            if error == "missing_core":
                missing_core.append(field)
            elif error:
                return self._unavailable(
                    "invalid_input", [f"{field}_{error}"]
                )
            profile[field] = value
        if missing_core:
            return self._unavailable(
                "anchors_only_missing_core",
                ["missing_core_inputs"],
            )

        nugent = float(profile["baseline_nugent_score"])
        if not self._is_integer(nugent) or int(round(nugent)) not in {7, 8, 9, 10}:
            return self._unavailable(
                "anchors_only_unsupported_range",
                ["baseline_nugent_score_outside_target_range"],
            )
        profile["baseline_nugent_score"] = float(round(nugent))

        missing_secondary = []
        av, av_error = self._parse_numeric(
            request, "baseline_av_score", required=False
        )
        if av_error:
            return self._unavailable("invalid_input", [f"baseline_av_score_{av_error}"])
        if av is None:
            missing_secondary.append("baseline_av_score")
        elif not self._is_integer(av) or not 0 <= int(round(av)) <= 4:
            return self._unavailable(
                "anchors_only_unsupported_range",
                ["baseline_av_score_outside_frozen_range"],
            )
        profile["baseline_av_score"] = None if av is None else float(round(av))

        mh = request.get("any_medical_history")
        if is_missing(mh):
            profile["any_medical_history"] = None
            missing_secondary.append("any_medical_history")
        elif mh == "yes":
            profile["any_medical_history"] = 1
        elif mh == "no":
            profile["any_medical_history"] = 0
        else:
            return self._unavailable(
                "anchors_only_unseen_category",
                ["any_medical_history_unknown_category"],
            )

        lacto = request.get("baseline_lactobacillus_grade")
        if is_missing(lacto):
            profile["baseline_lactobacillus_grade"] = None
            missing_secondary.append("baseline_lactobacillus_grade")
        elif lacto in LACTO_TO_SOURCE:
            profile["baseline_lactobacillus_grade"] = LACTO_TO_SOURCE[str(lacto)]
        else:
            return self._unavailable(
                "anchors_only_unseen_category",
                ["baseline_lactobacillus_grade_unknown_category"],
            )

        age = float(profile["age_years"])
        source_age_min, source_age_max = self.ranges["age_years"]
        if age < 18.0 or age > 55.0:
            return self._unavailable(
                "anchors_only_unsupported_range",
                ["age_outside_phase3_documented_range"],
            )
        age_extrapolated = age < source_age_min or age > source_age_max
        if age_extrapolated and mode != "exploratory_age_extrapolation":
            return self._unavailable(
                "anchors_only_extrapolation_opt_in_required",
                ["age_extrapolation_requires_explicit_opt_in"],
            )

        for field in [
            "baseline_bmi",
            "baseline_vaginal_ph",
        ]:
            value = float(profile[field])
            low, high = self.ranges[field]
            if value < low or value > high:
                return self._unavailable(
                    "anchors_only_unsupported_range",
                    [f"{field}_outside_phase2_range"],
                )

        if len(missing_secondary) == 3:
            return self._unavailable(
                "anchors_only_insufficient_support_fields",
                ["fewer_than_five_comparable_support_fields"],
            )

        support = self._support(
            profile,
            age_extrapolated=age_extrapolated,
            missing_secondary=missing_secondary,
        )
        if support["grade"] == "unavailable":
            return self._unavailable(
                "anchors_only_insufficient_support_fields",
                support["reason_codes"],
            )

        model_profile = dict(profile)
        model_profile["efficacy_treatment"] = P3_CONTROL
        frame = pd.DataFrame([model_profile])
        average, _, _, unseen = treatment_blind_draw_probabilities(
            frame, self.preprocessor, self.draws
        )
        if any(unseen.values()):
            return self._unavailable(
                "anchors_only_unseen_category",
                ["model_preprocessor_unseen_category"],
            )
        values = average[0]
        stats = interval(values)
        anchor = float(self.payload["anchors"]["observed"]["rate"])
        above = float(np.mean(values > anchor))
        below = float(np.mean(values < anchor))
        position_value, position_display = self._position(above, below)
        stability_score = max(above, below)
        stability_value, stability_display = self._stability(stability_score)
        dynamic_warnings = ["W008"]
        if d21 == "pending":
            dynamic_warnings.append("W009")
        if support["grade"] == "B":
            dynamic_warnings.append("W006")
        elif support["grade"] == "C":
            dynamic_warnings.append("W007")
        result = self._base("scenario_available", dynamic_warnings)
        result["d21_workflow"] = {
            "status": d21,
            "interpretation": (
                "结果以未来达到D21治愈为条件。"
                if d21 == "pending"
                else "已达到D21治愈，显示条件性D104复发情景。"
            ),
        }
        result["scenario_estimate"] = {
            "status": "modeled_exploratory",
            "posterior_median": stats["median"],
            "lower_95": stats["lower_95"],
            "upper_95": stats["upper_95"],
            "posterior_mean": stats["mean"],
            "difference_from_primary_anchor_percentage_points": 100
            * (stats["median"] - anchor),
            "treatment_blind_standardization": "0.5 test + 0.5 control, draw-wise",
            "internal_validation_auc": float(
                self.cv_summary.loc["B1_STRONG_SHRINK_PRIMARY", "mean_roc_auc"]
            ),
        }
        result["scenario_position"] = {
            "value": position_value,
            "display_zh": position_display,
            "posterior_probability_above_anchor": above,
            "posterior_probability_below_anchor": below,
            "display_threshold": 0.60,
            "interpretation": "宽松的探索性相对方向，不是患者风险等级。",
        }
        result["direction_stability"] = {
            "value": stability_value,
            "display_zh": stability_display,
            "score": stability_score,
            "interpretation": "仅表示当前模型抽样相对锚点的方向一致性，不是准确度。",
        }
        result["support"] = support
        direction_rows = self.directions[
            self.directions["display_eligible"].astype(str).str.lower().eq("true")
        ]
        result["direction_panel"] = [
            {
                "parameter": row["coefficient"],
                "label": row["final_label"],
                "band": row["final_band"],
                "stability": float(row["primary_stability"]),
                "interpretation": "探索性、非因果、非确认性",
            }
            for _, row in direction_rows.iterrows()
        ]
        return result


def evaluate_json_v2_2(
    request_json: str, registry_path: str | Path | None = None
) -> str:
    """JSON adapter that never logs the request."""
    try:
        request = json.loads(request_json)
    except json.JSONDecodeError:
        return json.dumps(
            {
                "contract_version": VERSION,
                "engine_status": "invalid_json",
                "output_name": "二期数据锚定的探索性D104复发情景估计",
                "reason_codes": ["invalid_json"],
                "warning_ids": ["W011"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    result = RecurrenceScenarioEngineV22(registry_path=registry_path).evaluate(request)
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
