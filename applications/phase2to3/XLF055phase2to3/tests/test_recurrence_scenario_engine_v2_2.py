#!/usr/bin/env python3

import json
import math
import unittest

from backend.recurrence_scenario_engine_v2_2 import (
    ALWAYS_WARNING_IDS,
    PROHIBITED_LABELS,
    RecurrenceScenarioEngineV22,
    evaluate_json_v2_2,
)


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


class ScenarioEngineV22Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = RecurrenceScenarioEngineV22(allow_validated_candidate=True)

    def test_01_valid_scenario(self):
        out = self.engine.evaluate(dict(VALID))
        self.assertEqual(out["contract_version"], "2.2.0")
        self.assertEqual(out["engine_status"], "scenario_available")
        self.assertIn(out["support"]["grade"], {"A", "B"})
        self.assertIsNotNone(out["scenario_estimate"])

    def test_02_deterministic(self):
        a = self.engine.evaluate(dict(VALID))
        b = self.engine.evaluate(dict(VALID))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_03_anchors(self):
        out = self.engine.evaluate(dict(VALID))
        self.assertEqual((out["anchors"]["primary_observed"]["events"], out["anchors"]["primary_observed"]["n"]), (16, 31))
        self.assertEqual((out["anchors"]["composite_sensitivity"]["events"], out["anchors"]["composite_sensitivity"]["n"]), (19, 34))

    def test_04_posterior_comparison(self):
        out = self.engine.evaluate(dict(VALID))
        position = out["scenario_position"]
        self.assertGreaterEqual(position["posterior_probability_above_anchor"], 0)
        self.assertLessEqual(position["posterior_probability_above_anchor"], 1)
        self.assertAlmostEqual(
            position["posterior_probability_above_anchor"]
            + position["posterior_probability_below_anchor"],
            1.0,
            places=12,
        )

    def test_05_position_label(self):
        out = self.engine.evaluate(dict(VALID))
        self.assertIn(
            out["scenario_position"]["value"],
            {
                "relative_higher_scenario",
                "near_anchor_or_direction_uncertain",
                "relative_lower_scenario",
            },
        )

    def test_06_stability_label(self):
        out = self.engine.evaluate(dict(VALID))
        self.assertIn(
            out["direction_stability"]["value"],
            {"insufficient", "low", "moderate", "relatively_stable"},
        )

    def test_07_pending_is_conditional(self):
        out = self.engine.evaluate(dict(VALID))
        self.assertEqual(out["d21_workflow"]["status"], "pending")
        self.assertIn("W009", out["warning_ids"])

    def test_08_cured_activates(self):
        out = self.engine.evaluate(dict(VALID, d21_status="cured"))
        self.assertEqual(out["engine_status"], "scenario_available")
        self.assertNotIn("W009", out["warning_ids"])
        self.assertNotIn("W010", out["warning_ids"])

    def test_09_not_cured_is_not_applicable(self):
        out = self.engine.evaluate(dict(VALID, d21_status="not_cured"))
        self.assertEqual(out["engine_status"], "not_applicable")
        self.assertIsNone(out["scenario_estimate"])
        self.assertEqual(out["support"]["grade"], "not_evaluated")
        self.assertIn("W010", out["warning_ids"])

    def test_10_missing_d21(self):
        req = dict(VALID)
        del req["d21_status"]
        out = self.engine.evaluate(req)
        self.assertEqual(out["engine_status"], "anchors_only_missing_core")
        self.assertIsNone(out["scenario_estimate"])

    def test_11_missing_numeric_core(self):
        out = self.engine.evaluate(dict(VALID, baseline_vaginal_ph=None))
        self.assertEqual(out["engine_status"], "anchors_only_missing_core")
        self.assertEqual(out["support"]["grade"], "unavailable")

    def test_12_invalid_numeric(self):
        out = self.engine.evaluate(dict(VALID, baseline_bmi="abc"))
        self.assertEqual(out["engine_status"], "invalid_input")

    def test_13_nonfinite_numeric(self):
        for value in [float("nan"), float("inf"), -float("inf")]:
            with self.subTest(value=value):
                out = self.engine.evaluate(dict(VALID, baseline_bmi=value))
                self.assertEqual(out["engine_status"], "invalid_input")

    def test_14_nugent_allowed(self):
        for value in [7, 8, 9, 10]:
            with self.subTest(value=value):
                out = self.engine.evaluate(dict(VALID, baseline_nugent_score=value))
                self.assertEqual(out["engine_status"], "scenario_available")

    def test_15_nugent_invalid(self):
        for value in [6, 7.5, 11]:
            with self.subTest(value=value):
                out = self.engine.evaluate(dict(VALID, baseline_nugent_score=value))
                self.assertEqual(out["engine_status"], "anchors_only_unsupported_range")

    def test_16_av_allowed(self):
        for value in [0, 4]:
            with self.subTest(value=value):
                out = self.engine.evaluate(dict(VALID, baseline_av_score=value))
                self.assertEqual(out["engine_status"], "scenario_available")

    def test_17_av_outside_frozen_range(self):
        for value in [-1, 4.5, 5]:
            with self.subTest(value=value):
                out = self.engine.evaluate(dict(VALID, baseline_av_score=value))
                self.assertEqual(out["engine_status"], "anchors_only_unsupported_range")

    def test_18_medical_history_unknown(self):
        out = self.engine.evaluate(dict(VALID, any_medical_history="unknown"))
        self.assertEqual(out["engine_status"], "anchors_only_unseen_category")

    def test_19_lactobacillus_unknown(self):
        out = self.engine.evaluate(dict(VALID, baseline_lactobacillus_grade="unknown"))
        self.assertEqual(out["engine_status"], "anchors_only_unseen_category")

    def test_20_one_secondary_missing_is_b(self):
        out = self.engine.evaluate(dict(VALID, baseline_av_score="missing"))
        self.assertEqual(out["engine_status"], "scenario_available")
        self.assertEqual(out["support"]["grade"], "B")
        self.assertIn("W006", out["warning_ids"])

    def test_21_two_secondary_missing_is_b(self):
        out = self.engine.evaluate(
            dict(
                VALID,
                baseline_av_score="missing",
                baseline_lactobacillus_grade="missing",
            )
        )
        self.assertEqual(out["engine_status"], "scenario_available")
        self.assertEqual(out["support"]["grade"], "B")

    def test_22_all_secondary_missing_is_unavailable(self):
        out = self.engine.evaluate(
            dict(
                VALID,
                baseline_av_score="missing",
                any_medical_history="missing",
                baseline_lactobacillus_grade="missing",
            )
        )
        self.assertEqual(out["engine_status"], "anchors_only_insufficient_support_fields")
        self.assertIsNone(out["scenario_estimate"])

    def test_23_source_age_boundaries_supported(self):
        for value in [18.480492813141684, 51.67419575633128]:
            with self.subTest(value=value):
                out = self.engine.evaluate(dict(VALID, age_years=value))
                self.assertEqual(out["engine_status"], "scenario_available")
                self.assertIn(out["support"]["grade"], {"A", "B"})

    def test_24_age_extrapolation_requires_opt_in(self):
        out = self.engine.evaluate(dict(VALID, age_years=55.0))
        self.assertEqual(out["engine_status"], "anchors_only_extrapolation_opt_in_required")
        self.assertIsNone(out["scenario_estimate"])

    def test_25_lower_age_extrapolation(self):
        out = self.engine.evaluate(
            dict(VALID, age_years=18.0, mode="exploratory_age_extrapolation")
        )
        self.assertEqual(out["engine_status"], "scenario_available")
        self.assertEqual(out["support"]["grade"], "C")
        self.assertIn("W007", out["warning_ids"])

    def test_26_upper_age_extrapolation(self):
        out = self.engine.evaluate(
            dict(VALID, age_years=55.0, mode="exploratory_age_extrapolation")
        )
        self.assertEqual(out["engine_status"], "scenario_available")
        self.assertEqual(out["support"]["grade"], "C")

    def test_27_age_outside_phase3_range(self):
        for value in [17.9, 55.1]:
            with self.subTest(value=value):
                out = self.engine.evaluate(
                    dict(VALID, age_years=value, mode="exploratory_age_extrapolation")
                )
                self.assertEqual(out["engine_status"], "anchors_only_unsupported_range")

    def test_28_bmi_extrapolation_blocked(self):
        low = self.engine.ranges["baseline_bmi"][0] - 0.01
        high = self.engine.ranges["baseline_bmi"][1] + 0.01
        for value in [low, high]:
            with self.subTest(value=value):
                out = self.engine.evaluate(
                    dict(VALID, baseline_bmi=value, mode="exploratory_age_extrapolation")
                )
                self.assertEqual(out["engine_status"], "anchors_only_unsupported_range")

    def test_29_ph_extrapolation_blocked(self):
        for value in [4.19, 5.21]:
            with self.subTest(value=value):
                out = self.engine.evaluate(
                    dict(
                        VALID,
                        baseline_vaginal_ph=value,
                        mode="exploratory_age_extrapolation",
                    )
                )
                self.assertEqual(out["engine_status"], "anchors_only_unsupported_range")

    def test_30_extrapolation_mode_with_supported_age_is_not_c(self):
        out = self.engine.evaluate(
            dict(VALID, mode="exploratory_age_extrapolation")
        )
        self.assertEqual(out["engine_status"], "scenario_available")
        self.assertIn(out["support"]["grade"], {"A", "B"})

    def test_31_clinical_assumption_mode_unavailable(self):
        out = self.engine.evaluate(dict(VALID, mode="clinical_assumption"))
        self.assertEqual(out["engine_status"], "assumption_mode_unavailable")
        self.assertIn("W012", out["warning_ids"])

    def test_32_invalid_mode(self):
        out = self.engine.evaluate(dict(VALID, mode="anything"))
        self.assertEqual(out["engine_status"], "invalid_input")

    def test_33_treatment_input_rejected(self):
        out = self.engine.evaluate(dict(VALID, efficacy_treatment="test"))
        self.assertEqual(out["engine_status"], "invalid_input")

    def test_34_identifier_input_rejected(self):
        out = self.engine.evaluate(dict(VALID, subject_id="synthetic"))
        self.assertEqual(out["engine_status"], "invalid_input")

    def test_35_postbaseline_input_rejected(self):
        out = self.engine.evaluate(dict(VALID, postdose_adherence=1))
        self.assertEqual(out["engine_status"], "invalid_input")

    def test_36_no_case_value_echo(self):
        out = self.engine.evaluate(dict(VALID))
        text = json.dumps(out, ensure_ascii=False, sort_keys=True)
        for key in [
            "age_years",
            "baseline_bmi",
            "baseline_vaginal_ph",
            "baseline_nugent_score",
            "baseline_av_score",
            "any_medical_history",
            "baseline_lactobacillus_grade",
        ]:
            self.assertNotIn(f'"{key}"', text)

    def test_37_always_warnings(self):
        out = self.engine.evaluate(dict(VALID))
        self.assertTrue(set(ALWAYS_WARNING_IDS).issubset(set(out["warning_ids"])))
        self.assertEqual(len(out["warnings"]), len(out["warning_ids"]))

    def test_38_numeric_result_warning(self):
        out = self.engine.evaluate(dict(VALID))
        self.assertIn("W008", out["warning_ids"])

    def test_39_anchor_only_warning(self):
        out = self.engine.evaluate(dict(VALID, baseline_bmi=None))
        self.assertIn("W011", out["warning_ids"])

    def test_40_position_boundaries(self):
        self.assertEqual(self.engine._position(0.60, 0.40)[0], "relative_higher_scenario")
        self.assertEqual(self.engine._position(0.40, 0.60)[0], "relative_lower_scenario")
        self.assertEqual(self.engine._position(0.59, 0.41)[0], "near_anchor_or_direction_uncertain")

    def test_41_stability_boundaries(self):
        expected = [
            (0.59, "insufficient"),
            (0.60, "low"),
            (0.699999, "low"),
            (0.70, "moderate"),
            (0.799999, "moderate"),
            (0.80, "relatively_stable"),
        ]
        for score, label in expected:
            with self.subTest(score=score):
                self.assertEqual(self.engine._stability(score)[0], label)

    def test_42_force_a_and_b_support_rules(self):
        original = self.engine.support_threshold
        try:
            self.engine.support_threshold = 1.0
            a = self.engine.evaluate(dict(VALID))
            self.assertEqual(a["support"]["grade"], "A")
            self.engine.support_threshold = -1.0
            b = self.engine.evaluate(dict(VALID))
            self.assertEqual(b["support"]["grade"], "B")
            self.assertIn("sparse_joint_profile", b["support"]["reason_codes"])
        finally:
            self.engine.support_threshold = original

    def test_43_numeric_bounds(self):
        out = self.engine.evaluate(dict(VALID))
        values = out["scenario_estimate"]
        self.assertTrue(
            0
            <= values["lower_95"]
            <= values["posterior_median"]
            <= values["upper_95"]
            <= 1
        )
        self.assertTrue(math.isfinite(values["difference_from_primary_anchor_percentage_points"]))

    def test_44_no_prohibited_labels_or_risk_band(self):
        payload = self.engine.evaluate(dict(VALID))
        # W013 must explicitly state that Phase III success probability is not
        # an output. Scan result labels/claims, but retain the negative warning.
        payload["warnings"] = [
            {"id": item["id"], "severity": item["severity"]}
            for item in payload["warnings"]
        ]
        text = json.dumps(payload, ensure_ascii=False)
        for label in PROHIBITED_LABELS:
            self.assertNotIn(label, text)
        self.assertNotIn("risk_band", text)

    def test_45_invalid_json_adapter(self):
        out = json.loads(evaluate_json_v2_2("{bad json"))
        self.assertEqual(out["engine_status"], "invalid_json")

    def test_46_input_schema(self):
        schema = self.engine.input_schema()
        self.assertEqual(schema["contract_version"], "2.2.0")
        self.assertEqual(
            set(schema["mode"]),
            {"data_supported", "exploratory_age_extrapolation"},
        )

    def test_47_support_threshold_registered(self):
        self.assertAlmostEqual(self.engine.support_threshold, 0.15036710908886186, places=15)
        self.assertEqual(len(self.engine.support_source), 31)

    def test_48_direction_panel(self):
        out = self.engine.evaluate(dict(VALID))
        self.assertEqual(len(out["direction_panel"]), 7)
        self.assertTrue(
            all(
                row["interpretation"] == "探索性、非因果、非确认性"
                for row in out["direction_panel"]
            )
        )


if __name__ == "__main__":
    unittest.main()
