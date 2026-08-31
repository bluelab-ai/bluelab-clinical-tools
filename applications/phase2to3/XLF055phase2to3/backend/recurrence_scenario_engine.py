#!/usr/bin/env python3
"""JSON-compatible backend for the V2.1 exploratory D104 recurrence scenario.

This engine intentionally does not persist or log input values. It is not a
clinical prediction service and does not expose treatment-arm-specific output.
"""

from __future__ import annotations

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


CORE = [
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
NUMERIC = [
    "age_years",
    "baseline_bmi",
    "baseline_vaginal_ph",
    "baseline_nugent_score",
    "baseline_av_score",
]
ALLOWED_KEYS = set(CORE + SECONDARY + ["d21_status", "mode"])
PROHIBITED_LABELS = ["准确复发概率", "真实个体概率", "临床预测", "治愈保证", "三期成功率"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class RecurrenceScenarioEngine:
    """Deterministic local computation engine with frozen fallback behavior."""

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
                / "v2_1"
                / "registered_limited_scenario_engine.json"
            )
        self.registry_path = Path(registry_path)
        if self.registry_path.exists():
            self.registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if self.registry["status"] != "registered_limited_scenario_engine":
                raise RuntimeError("Registry is not released for the limited scenario engine")
            self._load_from_registry()
        elif allow_validated_candidate:
            validation_path = (
                ROOT
                / "outputs"
                / "validation"
                / "v2_1_bayesian_model_fit_validation.json"
            )
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            if validation["decision"] != "model_fit_accepted_and_backend_development_authorized":
                raise RuntimeError("Validated model candidate is not authorized")
            self.registry = {
                "status": "validated_candidate_backend_test_only",
                "model_version": "2.1.0-candidate",
                "model_payload": "outputs/model_development/v2_1_bayesian_model_fit/restricted/candidate_model_payload.json",
                "posterior_draws": "outputs/model_development/v2_1_bayesian_model_fit/restricted/primary_posterior_draws.npz",
                "direction_evidence": "outputs/model_development/v2_1_bayesian_model_fit/directional_evidence.csv",
                "cv_summary": "outputs/model_development/v2_1_bayesian_model_fit/cv_summary.csv",
            }
            self._load_from_registry(verify_hashes=False)
        else:
            raise RuntimeError("Registered V2.1 limited scenario engine is unavailable")

    def _load_from_registry(self, verify_hashes: bool = True) -> None:
        payload_path = ROOT / self.registry["model_payload"]
        draws_path = ROOT / self.registry["posterior_draws"]
        direction_path = ROOT / self.registry["direction_evidence"]
        cv_path = ROOT / self.registry["cv_summary"]
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
        self.payload = json.loads(payload_path.read_text(encoding="utf-8"))
        self.draws = np.load(draws_path)["draws"]
        if self.draws.shape[0] != 20000 or not np.isfinite(self.draws).all():
            raise RuntimeError("Registered posterior draws invalid")
        self.preprocessor = FittedPreprocessor.from_dict(self.payload["preprocessor"])
        self.directions = pd.read_csv(direction_path)
        self.cv_summary = pd.read_csv(cv_path).set_index("model_id")

    @staticmethod
    def input_schema() -> dict:
        return {
            "required_core": CORE,
            "optional_secondary": SECONDARY,
            "d21_status": ["pending", "cured", "not_cured"],
            "mode": ["data_evidence"],
            "prohibited": [
                "randomized treatment arm",
                "post-dose variables",
                "adverse events",
                "direct identifiers",
            ],
        }

    def anchors(self) -> dict:
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

    def _base(self, status: str, warnings: list[str]) -> dict:
        return {
            "engine_status": status,
            "output_name": "二期数据锚定的探索性D104复发情景估计",
            "evidence_status": "limited_scenario_only",
            "anchors": self.anchors(),
            "warnings": warnings,
            "provenance": {
                "model_version": self.registry["model_version"],
                "target": "BV recurrence through D104 conditional on protocol-defined D21 cure",
                "source_population": "Phase II D24±3-cured FAS",
                "primary_missing_rule": "observed-label",
                "model_status": "modeled_exploratory",
                "validated_individual_probability": False,
                "risk_ranking_supported": False,
            },
        }

    def evaluate(self, request: dict[str, Any]) -> dict:
        """Evaluate one scenario without echoing or persisting input values."""
        if not isinstance(request, dict):
            return self._base("invalid_input", ["输入必须为JSON对象；未执行情景计算。"])
        extra = sorted(set(request) - ALLOWED_KEYS)
        if extra:
            return self._base(
                "invalid_input",
                [f"存在未允许字段：{', '.join(extra)}。治疗组、标识符和治疗后变量均不得输入。"],
            )
        mode = request.get("mode", "data_evidence")
        if mode != "data_evidence":
            return self._base(
                "assumption_mode_unavailable",
                ["临床假设模式尚未获得甲方参数审核和注册，当前不可用。"],
            )
        d21 = request.get("d21_status", "pending")
        if d21 not in {"pending", "cured", "not_cured"}:
            return self._base(
                "invalid_input",
                ["D21状态必须为pending、cured或not_cured。"],
            )
        warnings = [
            "该结果是二期小样本锚定的探索性情景估计，不是经验证的个体复发概率。",
            "模型内部表现弱于人群率基准，不支持风险排序或临床决策。",
            "不得因情景估计较低而减少方案规定的随访，也不得据此自动改变治疗。",
            "二期D24治愈人群向三期D21治愈人群运输存在不确定性。",
        ]
        if d21 == "not_cured":
            result = self._base("not_applicable", warnings)
            result["d21_workflow"] = {
                "status": "not_cured",
                "interpretation": "D104复发情景不适用；当前为D21未治愈。",
            }
            result["scenario_estimate"] = None
            result["direction_panel"] = []
            return result

        normalized: dict[str, Any] = {}
        missing_core = []
        for col in CORE:
            value = request.get(col)
            if value is None:
                missing_core.append(col)
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                return self._base("invalid_input", [f"{col}必须为有限数值。"])
            if not math.isfinite(value):
                return self._base("invalid_input", [f"{col}必须为有限数值。"])
            normalized[col] = value
        if missing_core:
            result = self._base(
                "anchors_only_missing_core",
                warnings + [f"核心变量缺失：{', '.join(missing_core)}；仅返回人群锚点。"],
            )
            result["scenario_estimate"] = None
            result["direction_panel"] = []
            return result

        for col in NUMERIC:
            if col not in request or request.get(col) is None:
                normalized[col] = None
                if col not in CORE:
                    warnings.append(f"{col}缺失，使用注册的训练数据预处理并标注不确定性。")
                continue
            try:
                value = float(request[col])
            except (TypeError, ValueError):
                return self._base("invalid_input", [f"{col}必须为有限数值。"])
            if not math.isfinite(value):
                return self._base("invalid_input", [f"{col}必须为有限数值。"])
            normalized[col] = value

        mh = request.get("any_medical_history")
        if mh is None:
            normalized["any_medical_history"] = None
            warnings.append("既往病史缺失，使用注册的训练数据预处理并标注不确定性。")
        elif isinstance(mh, bool):
            normalized["any_medical_history"] = int(mh)
        else:
            try:
                mh_num = float(mh)
            except (TypeError, ValueError):
                return self._base("invalid_input", ["any_medical_history必须为0/1或布尔值。"])
            if mh_num not in {0.0, 1.0}:
                return self._base("invalid_input", ["any_medical_history必须为0/1或布尔值。"])
            normalized["any_medical_history"] = int(mh_num)

        lacto = request.get("baseline_lactobacillus_grade")
        allowed_lacto = {"III级或IV级", "I级或II级"}
        if lacto is None:
            normalized["baseline_lactobacillus_grade"] = None
            warnings.append("基线乳杆菌分级缺失，使用来源数据中的显式缺失类别。")
        elif str(lacto) not in allowed_lacto:
            result = self._base(
                "anchors_only_unseen_category",
                warnings + ["基线乳杆菌分级不属于二期来源数据已观察类别；仅返回人群锚点。"],
            )
            result["scenario_estimate"] = None
            result["direction_panel"] = []
            return result
        else:
            normalized["baseline_lactobacillus_grade"] = str(lacto)

        ranges = self.payload["source_support"]["numeric_ranges"]
        out_of_range = []
        for col in NUMERIC:
            value = normalized.get(col)
            if value is None:
                continue
            if value < ranges[col]["source_min"] or value > ranges[col]["source_max"]:
                out_of_range.append(col)
        if out_of_range:
            result = self._base(
                "anchors_only_out_of_range",
                warnings
                + [f"以下变量超出二期来源范围：{', '.join(out_of_range)}；仅返回人群锚点。"],
            )
            result["scenario_estimate"] = None
            result["direction_panel"] = []
            return result

        normalized["efficacy_treatment"] = P3_CONTROL
        frame = pd.DataFrame([normalized])
        avg, pt, pc, unseen = treatment_blind_draw_probabilities(
            frame, self.preprocessor, self.draws
        )
        if any(unseen.values()):
            result = self._base(
                "anchors_only_unseen_category",
                warnings + ["输入包含模型未见类别；仅返回人群锚点。"],
            )
            result["scenario_estimate"] = None
            result["direction_panel"] = []
            return result
        values = avg[0]
        stats = interval(values)
        anchor = self.payload["anchors"]["observed"]["rate"]
        result = self._base("scenario_available", warnings)
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
        result["support"] = {
            "status": "within_phase2_source_ranges",
            "core_complete": True,
            "source_observed_labels": 31,
            "source_events": 16,
        }
        return result


def evaluate_json(request_json: str, registry_path: str | Path | None = None) -> str:
    """Convenience adapter; returns JSON and never logs the request."""
    try:
        request = json.loads(request_json)
    except json.JSONDecodeError:
        return json.dumps(
            {
                "engine_status": "invalid_json",
                "output_name": "二期数据锚定的探索性D104复发情景估计",
                "warnings": ["输入不是有效JSON。"],
            },
            ensure_ascii=False,
        )
    result = RecurrenceScenarioEngine(registry_path=registry_path).evaluate(request)
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
