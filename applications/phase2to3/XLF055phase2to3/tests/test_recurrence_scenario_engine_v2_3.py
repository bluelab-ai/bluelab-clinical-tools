#!/usr/bin/env python3

from __future__ import annotations

import json
import math
from pathlib import Path
import unittest

from backend.recurrence_scenario_engine_v2_2 import RecurrenceScenarioEngineV22
from backend.recurrence_scenario_engine_v2_3 import (
    RecurrenceScenarioEngineV23,
    evaluate_json_v2_3,
)


ROOT = Path(__file__).resolve().parents[1]
VALID = {
    "age_years": 35.7,
    "baseline_bmi": 21.6,
    "baseline_vaginal_ph": 4.8,
    "baseline_nugent_score": 8,
    "baseline_av_score": 2,
    "any_medical_history": "yes",
    "baseline_lactobacillus_grade": "III_or_IV",
    "d21_status": "pending",
    "mode": "data_supported",
}


class ScenarioEngineV23Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = RecurrenceScenarioEngineV23()
        cls.base = RecurrenceScenarioEngineV22()

    def test_01_registered_candidate_identity(self) -> None:
        self.assertEqual(self.engine.registry["engine_version"], "2.3.0")
        self.assertEqual(self.engine.registry["model_version"], "2.1.0")
        self.assertEqual(
            self.engine.registry["status"],
            "registered_backend_candidate_for_frontend_v2_6",
        )
        self.assertEqual(self.engine.draws.shape[0], 20_000)

    def test_02_input_contract_never_accepts_an_arm(self) -> None:
        schema = self.engine.input_schema()
        self.assertEqual(schema["contract_version"], "2.3.0")
        self.assertNotIn("efficacy_treatment", schema["required_core"])
        self.assertNotIn("efficacy_treatment", schema["optional_secondary"])
        self.assertIn("never an input", schema["hypothetical_arm_output"])

    def test_03_valid_scenario_has_all_outputs(self) -> None:
        out = self.engine.evaluate(dict(VALID))
        self.assertEqual(out["contract_version"], "2.3.0")
        self.assertEqual(out["engine_status"], "scenario_available")
        detail = out["arm_scenario_detail"]
        self.assertEqual(
            detail["status"], "modeled_exploratory_hypothetical_scenarios"
        )
        self.assertTrue(detail["both_hypothetical_regimens_returned_together"])
        self.assertIn("one_to_one_standardized", detail)
        self.assertIn("test_regimen", detail)
        self.assertIn("control_regimen", detail)
        self.assertIn("contrast_test_minus_control", detail)

    def test_04_frozen_v22_main_result_is_unchanged(self) -> None:
        old = self.base.evaluate(dict(VALID))
        new = self.engine.evaluate(dict(VALID))
        self.assertEqual(new["scenario_estimate"], old["scenario_estimate"])
        self.assertEqual(new["anchors"], old["anchors"])
        self.assertEqual(new["support"], old["support"])
        self.assertEqual(new["scenario_position"], old["scenario_position"])
        self.assertEqual(new["direction_stability"], old["direction_stability"])

    def test_05_one_to_one_public_summary_matches_main(self) -> None:
        out = self.engine.evaluate(dict(VALID))
        main = out["scenario_estimate"]
        average = out["arm_scenario_detail"]["one_to_one_standardized"]
        for key in ["posterior_median", "lower_95", "upper_95", "posterior_mean"]:
            self.assertEqual(average[key], main[key])

    def test_06_draw_wise_identity(self) -> None:
        check = self.engine.evaluate(dict(VALID))["arm_scenario_detail"][
            "draw_wise_identity_check"
        ]
        self.assertTrue(check["passed"])
        self.assertLessEqual(check["maximum_absolute_error"], 1e-12)
        self.assertEqual(check["tolerance"], 1e-12)

    def test_07_arm_probability_intervals_are_valid(self) -> None:
        detail = self.engine.evaluate(dict(VALID))["arm_scenario_detail"]
        for key in ["one_to_one_standardized", "test_regimen", "control_regimen"]:
            item = detail[key]
            self.assertTrue(
                0
                <= item["lower_95"]
                <= item["posterior_median"]
                <= item["upper_95"]
                <= 1
            )
            self.assertTrue(math.isfinite(item["posterior_mean"]))

    def test_08_contrast_interval_is_draw_wise_percentage_points(self) -> None:
        contrast = self.engine.evaluate(dict(VALID))["arm_scenario_detail"][
            "contrast_test_minus_control"
        ]
        self.assertEqual(contrast["scale"], "risk_difference_test_minus_control")
        self.assertEqual(contrast["unit"], "percentage_points")
        self.assertLessEqual(
            contrast["lower_95"],
            contrast["posterior_median"],
        )
        self.assertLessEqual(
            contrast["posterior_median"],
            contrast["upper_95"],
        )
        self.assertTrue(
            all(
                math.isfinite(contrast[key])
                for key in [
                    "lower_95",
                    "posterior_median",
                    "upper_95",
                    "posterior_mean",
                ]
            )
        )

    def test_09_observed_and_assumed_evidence_are_separate(self) -> None:
        context = self.engine.evaluate(dict(VALID))["arm_scenario_detail"][
            "evidence_context"
        ]
        observed = context["phase2_direct_observed"]
        assumed = context["phase3_protocol_planning_assumptions"]
        self.assertEqual(observed["status"], "observed_sparse")
        self.assertEqual(
            (observed["test"]["events"], observed["test"]["n"]), (2, 7)
        )
        self.assertEqual(
            (observed["control"]["events"], observed["control"]["n"]),
            (6, 10),
        )
        self.assertAlmostEqual(observed["test"]["rate"], 2 / 7)
        self.assertAlmostEqual(observed["control"]["rate"], 6 / 10)
        self.assertEqual(assumed["status"], "planning_assumption_not_observed")
        self.assertEqual(assumed["test"]["rate"], 0.33)
        self.assertEqual(assumed["control"]["rate"], 0.55)
        self.assertTrue(context["sources_are_separate"])

    def test_10_no_actual_arm_is_accepted_or_used(self) -> None:
        for field in [
            "efficacy_treatment",
            "actual_randomized_arm",
            "treatment_arm",
            "TRT01P",
            "TRT01A",
        ]:
            with self.subTest(field=field):
                out = self.engine.evaluate(dict(VALID, **{field: "test"}))
                self.assertEqual(out["engine_status"], "invalid_input")
                self.assertIsNone(out["arm_scenario_detail"])
        out = self.engine.evaluate(dict(VALID))
        self.assertFalse(out["provenance"]["actual_randomized_arm_used"])
        self.assertFalse(
            out["arm_scenario_detail"]["actual_randomized_arm_input_accepted"]
        )
        self.assertFalse(out["arm_scenario_detail"]["actual_randomized_arm_used"])

    def test_11_not_cured_preserves_not_applicable_fallback(self) -> None:
        out = self.engine.evaluate(dict(VALID, d21_status="not_cured"))
        self.assertEqual(out["engine_status"], "not_applicable")
        self.assertIsNone(out["scenario_estimate"])
        self.assertIsNone(out["arm_scenario_detail"])
        self.assertIn("W010", out["warning_ids"])

    def test_12_missing_core_preserves_anchor_only_fallback(self) -> None:
        out = self.engine.evaluate(dict(VALID, baseline_bmi=None))
        self.assertEqual(out["engine_status"], "anchors_only_missing_core")
        self.assertIsNone(out["scenario_estimate"])
        self.assertIsNone(out["arm_scenario_detail"])
        self.assertIn("W011", out["warning_ids"])

    def test_13_range_and_category_fallbacks_have_no_arm_values(self) -> None:
        cases = [
            dict(VALID, baseline_nugent_score=6),
            dict(VALID, baseline_vaginal_ph=6.0),
            dict(VALID, baseline_lactobacillus_grade="unknown"),
        ]
        for request in cases:
            with self.subTest(request=request):
                out = self.engine.evaluate(request)
                self.assertNotEqual(out["engine_status"], "scenario_available")
                self.assertIsNone(out["arm_scenario_detail"])

    def test_14_pending_d21_remains_conditional(self) -> None:
        out = self.engine.evaluate(dict(VALID))
        self.assertEqual(out["d21_workflow"]["status"], "pending")
        self.assertIn("W009", out["warning_ids"])

    def test_15_optional_missing_and_age_extrapolation_still_work(self) -> None:
        missing = self.engine.evaluate(dict(VALID, baseline_av_score="missing"))
        self.assertEqual(missing["engine_status"], "scenario_available")
        self.assertEqual(missing["support"]["grade"], "B")
        self.assertIsNotNone(missing["arm_scenario_detail"])
        age = self.engine.evaluate(
            dict(VALID, age_years=55.0, mode="exploratory_age_extrapolation")
        )
        self.assertEqual(age["engine_status"], "scenario_available")
        self.assertEqual(age["support"]["grade"], "C")
        self.assertIsNotNone(age["arm_scenario_detail"])

    def test_16_output_is_deterministic(self) -> None:
        left = self.engine.evaluate(dict(VALID))
        right = self.engine.evaluate(dict(VALID))
        self.assertEqual(
            json.dumps(left, ensure_ascii=False, sort_keys=True),
            json.dumps(right, ensure_ascii=False, sort_keys=True),
        )

    def test_17_no_case_values_or_identifiers_are_echoed(self) -> None:
        text = json.dumps(self.engine.evaluate(dict(VALID)), ensure_ascii=False)
        for field in [
            "age_years",
            "baseline_bmi",
            "baseline_vaginal_ph",
            "baseline_nugent_score",
            "baseline_av_score",
            "any_medical_history",
            "baseline_lactobacillus_grade",
            "USUBJID",
            "SUBJID",
        ]:
            self.assertNotIn(f'"{field}"', text)

    def test_18_no_causal_or_accuracy_claim(self) -> None:
        detail = self.engine.evaluate(dict(VALID))["arm_scenario_detail"]
        self.assertFalse(detail["individual_treatment_effect_supported"])
        self.assertIn("不是受试者实际分组", detail["interpretation"])
        self.assertIn("不是", detail["interpretation"])
        self.assertIn("治疗建议", detail["interpretation"])

    def test_19_json_adapter(self) -> None:
        valid = json.loads(evaluate_json_v2_3(json.dumps(VALID)))
        self.assertEqual(valid["contract_version"], "2.3.0")
        self.assertIsNotNone(valid["arm_scenario_detail"])
        invalid = json.loads(evaluate_json_v2_3("{bad json"))
        self.assertEqual(invalid["engine_status"], "invalid_json")
        self.assertIsNone(invalid["arm_scenario_detail"])

    def test_20_registry_contains_no_phase3_subject_data_path(self) -> None:
        registry_path = (
            ROOT
            / "outputs/model_registry/v2_3/registered_arm_scenario_backend_candidate.json"
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        serialized = json.dumps(registry, ensure_ascii=False)
        self.assertNotIn("盲底", serialized)
        self.assertNotIn("疗效数据集", serialized)
        self.assertNotIn("USUBJID", serialized)
        self.assertNotIn("SUBJID", serialized)


if __name__ == "__main__":
    unittest.main()
