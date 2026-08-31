#!/usr/bin/env python3
"""V2.3 hypothetical-arm extension of the registered XLF055 scenario engine.

This candidate reuses the registered V2.1 model, preprocessor and 20,000
posterior draws through the validated V2.2 backend.  It adds simultaneous
hypothetical test/control regimen summaries and their draw-wise 1:1 average.
It never accepts or uses an actual randomized treatment assignment.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPTS))

from backend.recurrence_scenario_engine_v2_2 import (  # noqa: E402
    LACTO_TO_SOURCE,
    RecurrenceScenarioEngineV22,
    is_missing,
)
from v21_bayesian_core import (  # noqa: E402
    P3_CONTROL,
    P3_TEST,
    interval,
    treatment_blind_draw_probabilities,
)


VERSION = "2.3.0"
REGISTRY_STATUS = "registered_backend_candidate_for_frontend_v2_6"
DEFAULT_REGISTRY = (
    ROOT
    / "outputs"
    / "model_registry"
    / "v2_3"
    / "registered_arm_scenario_backend_candidate.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probability_summary(values: np.ndarray) -> dict[str, Any]:
    stats = interval(np.asarray(values, dtype=float))
    return {
        "status": "modeled_exploratory",
        "posterior_median": stats["median"],
        "lower_95": stats["lower_95"],
        "upper_95": stats["upper_95"],
        "posterior_mean": stats["mean"],
        "scale": "probability_0_to_1",
    }


def percentage_point_summary(values: np.ndarray) -> dict[str, Any]:
    stats = interval(100.0 * np.asarray(values, dtype=float))
    return {
        "status": "modeled_exploratory",
        "posterior_median": stats["median"],
        "lower_95": stats["lower_95"],
        "upper_95": stats["upper_95"],
        "posterior_mean": stats["mean"],
        "scale": "risk_difference_test_minus_control",
        "unit": "percentage_points",
    }


class RecurrenceScenarioEngineV23(RecurrenceScenarioEngineV22):
    """Registered V2.2 engine plus non-input-driven hypothetical arm detail."""

    def __init__(self, registry_path: str | Path | None = None) -> None:
        release_path = Path(registry_path) if registry_path else DEFAULT_REGISTRY
        if not release_path.is_file():
            raise RuntimeError("Registered V2.3 arm-scenario candidate is unavailable")
        release = json.loads(release_path.read_text(encoding="utf-8"))
        if release.get("status") != REGISTRY_STATUS:
            raise RuntimeError("V2.3 registry status is not an accepted candidate status")
        if release.get("engine_version") != VERSION:
            raise RuntimeError("V2.3 registry engine version mismatch")

        base_item = release["base_backend"]
        base_registry_path = ROOT / base_item["registry_relative_path"]
        if not base_registry_path.is_file() or sha256(base_registry_path) != base_item["sha256"]:
            raise RuntimeError("Registered V2.2 base-backend hash mismatch")

        contract_item = release["upgrade_contract"]
        contract_path = ROOT / contract_item["relative_path"]
        if not contract_path.is_file() or sha256(contract_path) != contract_item["sha256"]:
            raise RuntimeError("Frozen V2.6 upgrade-contract hash mismatch")

        backend_item = release["backend"]
        backend_path = ROOT / backend_item["relative_path"]
        if not backend_path.is_file() or sha256(backend_path) != backend_item["sha256"]:
            raise RuntimeError("Registered V2.3 backend hash mismatch")

        super().__init__(registry_path=base_registry_path)
        self.base_registry = self.registry
        self.registry_path = release_path
        self.registry = release
        self.arm_context = release["arm_context"]

    @staticmethod
    def input_schema() -> dict[str, Any]:
        schema = RecurrenceScenarioEngineV22.input_schema()
        schema["contract_version"] = VERSION
        schema["hypothetical_arm_output"] = (
            "always simultaneous and derived internally; never an input"
        )
        return schema

    def _base(
        self, status: str, extra_warning_ids: list[str] | None = None
    ) -> dict[str, Any]:
        result = super()._base(status, extra_warning_ids)
        result["contract_version"] = VERSION
        result["arm_scenario_detail"] = None
        result["provenance"]["engine_version"] = VERSION
        result["provenance"]["base_engine_version"] = "2.2.0"
        result["provenance"]["model_version"] = "2.1.0"
        result["provenance"]["actual_randomized_arm_used"] = False
        return result

    @staticmethod
    def _model_profile_from_valid_request(request: dict[str, Any]) -> dict[str, Any]:
        """Normalize only after V2.2 has accepted the request as calculable."""
        av_value = request.get("baseline_av_score")
        if is_missing(av_value):
            av = None
        else:
            av = float(round(float(av_value)))

        mh_value = request.get("any_medical_history")
        mh = None if is_missing(mh_value) else (1 if mh_value == "yes" else 0)

        lacto_value = request.get("baseline_lactobacillus_grade")
        lacto = None if is_missing(lacto_value) else LACTO_TO_SOURCE[str(lacto_value)]

        return {
            "age_years": float(request["age_years"]),
            "baseline_bmi": float(request["baseline_bmi"]),
            "baseline_vaginal_ph": float(request["baseline_vaginal_ph"]),
            "baseline_nugent_score": float(round(float(request["baseline_nugent_score"]))),
            "baseline_av_score": av,
            "any_medical_history": mh,
            "baseline_lactobacillus_grade": lacto,
            # This placeholder is overwritten for both hypothetical regimens
            # by treatment_blind_draw_probabilities.
            "efficacy_treatment": P3_CONTROL,
        }

    def _arm_detail(self, request: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
        profile = self._model_profile_from_valid_request(request)
        frame = pd.DataFrame([profile])
        average, test, control, unseen = treatment_blind_draw_probabilities(
            frame, self.preprocessor, self.draws
        )
        if any(unseen.values()):
            raise RuntimeError("Unexpected unseen category after V2.2 acceptance")

        average_draws = average[0]
        test_draws = test[0]
        control_draws = control[0]
        identity_error = float(
            np.max(np.abs(average_draws - (0.5 * test_draws + 0.5 * control_draws)))
        )
        tolerance = 1e-12

        one_to_one = probability_summary(average_draws)
        existing = scenario["scenario_estimate"]
        for key in ["posterior_median", "lower_95", "upper_95", "posterior_mean"]:
            if not np.isclose(one_to_one[key], existing[key], rtol=0.0, atol=1e-15):
                raise RuntimeError("V2.3 one-to-one summary differs from frozen V2.2 result")

        observed = self.arm_context["phase2_direct_observed"]
        assumptions = self.arm_context["phase3_protocol_planning_assumptions"]
        return {
            "status": "modeled_exploratory_hypothetical_scenarios",
            "actual_randomized_arm_input_accepted": False,
            "actual_randomized_arm_used": False,
            "both_hypothetical_regimens_returned_together": True,
            "individual_treatment_effect_supported": False,
            "standardization": {
                "method": "draw-wise weighted average",
                "test_weight": 0.5,
                "control_weight": 0.5,
                "allocation_label": "1:1",
            },
            "one_to_one_standardized": one_to_one,
            "test_regimen": {
                "scenario_id": "hypothetical_test_regimen",
                "display_zh": "假设采用试验方案",
                "regimen": P3_TEST,
                **probability_summary(test_draws),
            },
            "control_regimen": {
                "scenario_id": "hypothetical_control_regimen",
                "display_zh": "假设采用对照方案",
                "regimen": P3_CONTROL,
                **probability_summary(control_draws),
            },
            "contrast_test_minus_control": percentage_point_summary(
                test_draws - control_draws
            ),
            "draw_wise_identity_check": {
                "formula": "p_1to1_draw = 0.5*p_test_draw + 0.5*p_control_draw",
                "maximum_absolute_error": identity_error,
                "tolerance": tolerance,
                "passed": identity_error <= tolerance,
            },
            "evidence_context": {
                "phase2_direct_observed": observed,
                "phase3_protocol_planning_assumptions": assumptions,
                "sources_are_separate": True,
            },
            "interpretation": (
                "两组数值是在同一基线画像下切换方案得到的探索性假设情景；"
                "不是受试者实际分组、个体治疗获益、因果效应或治疗建议。"
            ),
        }

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        result = super().evaluate(request)
        result["contract_version"] = VERSION
        if result.get("engine_status") != "scenario_available":
            result["arm_scenario_detail"] = None
            return result
        detail = self._arm_detail(request, result)
        if not detail["draw_wise_identity_check"]["passed"]:
            raise RuntimeError("Draw-wise 1:1 arm identity check failed")
        result["arm_scenario_detail"] = detail
        return result


def evaluate_json_v2_3(
    request_json: str, registry_path: str | Path | None = None
) -> str:
    """JSON adapter that never logs or echoes input values."""
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
                "arm_scenario_detail": None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    result = RecurrenceScenarioEngineV23(registry_path=registry_path).evaluate(request)
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
