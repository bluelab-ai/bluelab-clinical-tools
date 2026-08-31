from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
APP_FILE = APP_ROOT / "app.py"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import app as frontend_app  # noqa: E402
from planning_tool.engine import engine_health, evaluate_scenario  # noqa: E402


def default_scenario() -> dict[str, object]:
    return {
        "age_years": 35.7,
        "baseline_bmi": 21.6,
        "baseline_vaginal_ph": 4.8,
        "baseline_nugent_score": 8,
        "baseline_av_score": 2,
        "any_medical_history": "no",
        "baseline_lactobacillus_grade": "III_or_IV",
        "d21_status": "pending",
        "mode": "data_supported",
    }


def fresh_app(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.delenv("XLF055_APP_PASSWORD", raising=False)
    return AppTest.from_file(str(APP_FILE), default_timeout=120).run()


def button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def navigation(app: AppTest):
    return next(item for item in app.radio if item.label == "导航")


def page_text(app: AppTest) -> str:
    values: list[str] = []
    for collection in (
        app.markdown,
        app.caption,
        app.warning,
        app.info,
        app.error,
        app.success,
    ):
        values.extend(str(item.value) for item in collection)
    return "\n".join(values)


def test_v26_adapter_reuses_v21_and_returns_complete_hypothetical_pair() -> None:
    health = engine_health()
    result = evaluate_scenario(default_scenario())

    assert health["engine_version"] == "2.3.0"
    assert health["model_version"] == "2.1.0"
    assert (
        health["registry_status"]
        == "registered_backend_candidate_for_frontend_v2_6"
    )
    assert result["contract_version"] == "2.3.0"
    assert result["provenance"]["model_version"] == "2.1.0"
    assert result["provenance"]["actual_randomized_arm_used"] is False

    detail = result["arm_scenario_detail"]
    assert frontend_app.arm_scenario_detail_is_displayable(detail)
    assert detail["both_hypothetical_regimens_returned_together"] is True
    assert detail["actual_randomized_arm_input_accepted"] is False
    assert detail["individual_treatment_effect_supported"] is False
    for key in ("posterior_median", "lower_95", "upper_95", "posterior_mean"):
        assert detail["one_to_one_standardized"][key] == result[
            "scenario_estimate"
        ][key]
    assert detail["draw_wise_identity_check"]["passed"] is True
    assert detail["draw_wise_identity_check"]["maximum_absolute_error"] <= 1e-12


def test_pair_display_gate_fails_closed_for_any_partial_or_actual_arm_detail() -> None:
    detail = evaluate_scenario(default_scenario())["arm_scenario_detail"]
    partial = dict(detail)
    partial.pop("control_regimen")
    assert not frontend_app.arm_scenario_detail_is_displayable(partial)

    actual = dict(detail)
    actual["actual_randomized_arm_used"] = True
    assert not frontend_app.arm_scenario_detail_is_displayable(actual)

    changed_main = dict(
        evaluate_scenario(default_scenario())["scenario_estimate"]
    )
    changed_main["posterior_median"] += 0.01
    assert not frontend_app.arm_scenario_detail_is_displayable(
        detail, changed_main
    )

    context = detail["evidence_context"]
    assert frontend_app.arm_evidence_context_is_displayable(context)
    partial_context = dict(context)
    partial_observed = dict(context["phase2_direct_observed"])
    partial_observed.pop("control")
    partial_context["phase2_direct_observed"] = partial_observed
    assert not frontend_app.arm_evidence_context_is_displayable(partial_context)


def test_streamlit_shows_main_one_to_one_and_collapsed_pair_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = fresh_app(monkeypatch)
    button(app, "加载演示参数").click().run()
    button(app, "运行情景").click().run()
    assert not app.exception

    result = app.session_state["current_result"]
    detail = result["arm_scenario_detail"]
    for key in ("posterior_median", "lower_95", "upper_95", "posterior_mean"):
        assert result["scenario_estimate"][key] == detail[
            "one_to_one_standardized"
        ][key]
    assert any(
        item.label == "查看试验与对照方案详情" for item in app.expander
    )
    metric_labels = {item.label for item in app.metric}
    assert {
        "估计区间",
        "当前比较锚点",
        "假设采用试验方案",
        "假设采用对照方案",
        "假设方案差（试验－对照）",
    }.issubset(metric_labels)

    body = page_text(app)
    assert "不是受试者实际随机分组、个体治疗效应或治疗建议" in body
    assert "二期直接观察（小样本，不是模型预测）" in body
    assert "2/7" in body and "6/10" in body
    assert "三期方案规划假设（不是观察结果）" in body
    assert "33%" in body and "55%" in body

    widget_labels = {
        item.label
        for collection in (
            app.selectbox,
            app.number_input,
            app.checkbox,
            app.text_input,
        )
        for item in collection
    }
    assert not any(
        label in widget_labels
        for label in ("实际随机分组", "治疗组", "试验组", "对照组")
    )


def _aggregate_payload() -> dict[str, object]:
    return {
        "identity": {
            "name": "aggregate-only-test",
            "version": "2.6.1",
            "status": "early_descriptive_only",
        },
        "governance": {
            "p2_model_selection_frozen_before_p3_scoring": True,
            "p3_training_or_tuning": False,
            "actual_randomized_arm_used": False,
            "blind_key_accessed": False,
            "patient_rows_persisted": 0,
            "baseline_mapping_amendment_frozen_before_rescoring": True,
            "baseline_mapping_outcome_driven": False,
            "permitted_source_keys": ["canonical_blinded"],
        },
        "model": {
            "decision": "retain",
            "selected_model_id": "v2_1",
            "selected_model_version": "2.1.0",
        },
        "evidence": {
            "score_support": {
                "baseline_n": 20,
                "score_available_n": 20,
                "score_unavailable_n": 0,
                "patient_rows_persisted": 0,
            },
            "endpoint_counts": {
                "d104_maturity": {
                    "outcome_observed": 8,
                    "definitely_not_yet_due": 40,
                    "maturity_unresolved_without_d1_and_menstrual_context": 3,
                    "maturity_unknown_no_d21_date": 2,
                    "administrative_immaturity_coded_as_non_event": 0,
                }
            },
            "early_validation": {
                "d44_observed_label": {
                    "status": "early_descriptive_only",
                    "n": 14,
                    "events": 3,
                    "non_events": 11,
                    "observed_rate": 3 / 14,
                    "mean_predicted_probability": 0.45,
                    "target_alignment": "early_timepoint_direction_only_not_D104_accuracy",
                    "interpretability": "descriptive_direction_check_only",
                },
                "d74_cumulative_label": {
                    "status": "early_descriptive_only",
                    "n": 10,
                    "events": 4,
                    "non_events": 6,
                    "observed_rate": 0.4,
                    "mean_predicted_probability": 0.46,
                    "target_alignment": "early_cumulative_direction_only_not_D104_accuracy",
                    "interpretability": "descriptive_direction_check_only",
                },
                "d104_cumulative_label": {
                    "status": "early_descriptive_only",
                    "n": 8,
                    "events": 3,
                    "non_events": 5,
                    "observed_rate": 0.375,
                    "mean_predicted_probability": 0.45,
                    "brier": 0.26,
                    "log_loss": 0.71,
                    "calibration_in_the_large": None,
                    "observed_to_expected": None,
                    "roc_auc": None,
                    "metric_unavailable_reasons": ["too_few_labels"],
                    "interpretability": (
                        "not_interpretable_as_accuracy_due_to_"
                        "outcome_dependent_maturity"
                    ),
                    "outcome_availability_bias": True,
                },
            },
            "outcome_availability_bias": {
                "present": True,
                "mechanism": (
                    "Recurrence can become observed at D44/D74, whereas "
                    "non-recurrence requires an observed D104 NO"
                ),
                "consequence": (
                    "The observable-label subset is enriched for early "
                    "recurrence and is not an unbiased accuracy validation"
                ),
            },
        },
        "interpretation": {
            "conclusion": (
                "uncertain_due_to_maturity_and_outcome_availability_bias"
            ),
            "prohibited_claim": "validated accuracy or successful external validation",
            "outcome_availability_bias": (
                "Current metrics are not an unbiased accuracy validation"
            ),
        },
    }

def test_phase3_summary_loader_is_aggregate_only_and_fail_closed(
    tmp_path: Path,
) -> None:
    pending = frontend_app.load_phase3_early_consistency_summary(
        tmp_path / "missing.json"
    )
    assert pending["status"] == "pending"

    safe_path = tmp_path / "aggregate.json"
    safe_path.write_text(
        json.dumps(_aggregate_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    summary = frontend_app.load_phase3_early_consistency_summary(safe_path)
    assert summary["status"] == "available"
    assert summary["artifact_version"] == "2.6.1"
    assert summary["artifact_status"] == "early_descriptive_only"
    assert summary["model_version"] == "2.1.0"
    assert summary["patient_rows_persisted"] == 0
    assert summary["outcome_availability_bias"]["present"] is True
    assert set(summary["early_directional"]) == {
        "d44_observed_label",
        "d74_cumulative_label",
    }
    assert summary["d104"]["n"] == 8
    assert summary["d104_maturity"][
        "maturity_unresolved_without_d1_and_menstrual_context"
    ] == 3
    assert summary["actual_randomized_arm_used"] is False
    rendered = json.dumps(summary, ensure_ascii=False)
    assert "Subject_Id" not in rendered
    assert "TRT01A" not in rendered

    unsafe = _aggregate_payload()
    unsafe["governance"]["p3_training_or_tuning"] = True
    unsafe_path = tmp_path / "unsafe.json"
    unsafe_path.write_text(
        json.dumps(unsafe, ensure_ascii=False), encoding="utf-8"
    )
    blocked = frontend_app.load_phase3_early_consistency_summary(unsafe_path)
    assert blocked["status"] == "blocked"
    assert blocked["d104"] is None


@pytest.mark.parametrize(
    "case",
    [
        "wrong_version",
        "wrong_status",
        "mapping_not_frozen",
        "outcome_driven_mapping",
        "patient_rows_nonzero",
        "patient_rows_bool_false",
        "score_rows_nonzero",
        "missing_outcome_bias",
        "d104_bias_false",
        "d104_status_not_descriptive",
        "d44_not_direction_only",
        "immaturity_coded_non_event",
    ],
)
def test_phase3_261_contract_failures_block_all_metrics(
    tmp_path: Path,
    case: str,
) -> None:
    payload = _aggregate_payload()
    if case == "wrong_version":
        payload["identity"]["version"] = "2.6.0"
    elif case == "wrong_status":
        payload["identity"]["status"] = "validated"
    elif case == "mapping_not_frozen":
        payload["governance"][
            "baseline_mapping_amendment_frozen_before_rescoring"
        ] = False
    elif case == "outcome_driven_mapping":
        payload["governance"]["baseline_mapping_outcome_driven"] = True
    elif case == "patient_rows_nonzero":
        payload["governance"]["patient_rows_persisted"] = 1
    elif case == "patient_rows_bool_false":
        payload["governance"]["patient_rows_persisted"] = False
    elif case == "score_rows_nonzero":
        payload["evidence"]["score_support"]["patient_rows_persisted"] = 1
    elif case == "missing_outcome_bias":
        payload["evidence"].pop("outcome_availability_bias")
    elif case == "d104_bias_false":
        payload["evidence"]["early_validation"]["d104_cumulative_label"][
            "outcome_availability_bias"
        ] = False
    elif case == "d104_status_not_descriptive":
        payload["evidence"]["early_validation"]["d104_cumulative_label"][
            "status"
        ] = "validated"
    elif case == "d44_not_direction_only":
        payload["evidence"]["early_validation"]["d44_observed_label"][
            "target_alignment"
        ] = "accuracy_validation"
    elif case == "immaturity_coded_non_event":
        payload["evidence"]["endpoint_counts"]["d104_maturity"][
            "administrative_immaturity_coded_as_non_event"
        ] = 1

    path = tmp_path / f"{case}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    blocked = frontend_app.load_phase3_early_consistency_summary(path)
    assert blocked["status"] == "blocked"
    assert blocked["d104"] is None
    assert "early_directional" not in blocked


def test_formal_phase3_261_aggregate_is_accepted_without_accuracy_claim() -> None:
    summary = frontend_app.load_phase3_early_consistency_summary()
    assert summary["status"] == "available"
    assert summary["artifact_version"] == "2.6.1"
    assert summary["artifact_status"] == "early_descriptive_only"
    assert summary["patient_rows_persisted"] == 0
    assert summary["d104"]["status"] == "early_descriptive_only"
    assert summary["d104"]["n"] == 20
    assert summary["outcome_availability_bias"]["present"] is True
    assert summary["conclusion"] == (
        "uncertain_due_to_maturity_and_outcome_availability_bias"
    )


def test_usage_page_states_phase3_boundary_without_accuracy_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = fresh_app(monkeypatch)
    navigation(app).set_value("使用说明").run()
    assert not app.exception
    body = page_text(app)
    assert "从未用于模型训练、变量选择或调参" in body
    assert "规范盲态截断用于早期一致性检查" in body
    assert "不等于正式外部验证或准确率证明" in body
    assert "当前D104可观察子集会富集较早发生的复发" in body
    assert "不能解释为准确率验证" in body
    assert "D44和D74仅用于早期方向性观察" in body
    assert "不是D104预测准确率验证" in body
    assert "不构成准确率验证" in body
    assert any(
        "富集较早发生的复发" in str(item.value) for item in app.warning
    )


def test_v26_config_and_changelog_are_aligned() -> None:
    config = json.loads(
        (APP_ROOT / "project_config.json").read_text(encoding="utf-8")
    )
    assert config["project"]["frontend_version"] == "2.6.0"
    assert config["project"]["backend_version"] == "2.3.0"
    assert config["project"]["model_version"] == "2.1.0"
    assert (
        config["recurrence_scenario_engine"]["frontend_contract_version"]
        == "2.3.0"
    )
    assert config["website"]["patient_input_persistence"] is False
    assert "training" in config["governance"]["phase3_ongoing_data_use"]

    changelog = json.loads(
        (APP_ROOT / "runtime" / "changelog.json").read_text(encoding="utf-8")
    )
    latest = changelog["entries"][0]
    assert latest["frontend_version"] == "2.6.0"
    assert latest["backend_version"] == "2.3.0"
    assert latest["model_version"] == "2.1.0"
