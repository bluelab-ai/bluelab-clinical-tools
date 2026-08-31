from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import threading
import time

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from planning_tool.engine import (  # noqa: E402
    engine_health,
    evaluate_scenario,
    population_summary,
)
import app as frontend_app  # noqa: E402
import planning_tool.feedback as feedback_module  # noqa: E402
import planning_tool.reporting as reporting_module  # noqa: E402
from planning_tool.feedback import (  # noqa: E402
    FeedbackError,
    aggregate_status,
    database_path,
    email_channel_status,
    feedback_root,
    process_email_outbox,
    submit_feedback,
    upload_root,
)
from planning_tool.reporting import build_scenario_report  # noqa: E402


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


def test_registered_engine_and_default_scenario() -> None:
    health = engine_health()
    result = evaluate_scenario(default_scenario())
    assert health["engine_version"] == "2.3.0"
    assert health["source_observed_labels"] == 31
    assert health["source_events"] == 16
    assert health["patient_input_persistence"] is False
    assert result["contract_version"] == "2.3.0"
    assert result["engine_status"] == "scenario_available"
    assert result["support"]["grade"] == "A"
    assert result["anchors"]["primary_observed"]["rate"] == pytest.approx(16 / 31)
    assert result["anchors"]["composite_sensitivity"]["rate"] == pytest.approx(19 / 34)


def test_lower_barrier_optional_missing_and_minimum_support_gate() -> None:
    one_missing = default_scenario()
    one_missing["baseline_av_score"] = "missing"
    result = evaluate_scenario(one_missing)
    assert result["engine_status"] == "scenario_available"
    assert result["support"]["grade"] == "B"
    assert "secondary_input_missing" in result["support"]["reason_codes"]

    all_missing = default_scenario()
    all_missing.update(
        {
            "baseline_av_score": "missing",
            "any_medical_history": "missing",
            "baseline_lactobacillus_grade": "missing",
        }
    )
    blocked = evaluate_scenario(all_missing)
    assert blocked["engine_status"] != "scenario_available"
    assert blocked["support"]["grade"] == "unavailable"
    assert "fewer_than_five_comparable_support_fields" in blocked["reason_codes"]


def test_age_only_extrapolation_requires_explicit_opt_in() -> None:
    scenario = default_scenario()
    scenario["age_years"] = 53.0
    blocked = evaluate_scenario(scenario)
    assert blocked["engine_status"] != "scenario_available"
    assert "age_extrapolation_requires_explicit_opt_in" in blocked["reason_codes"]

    scenario["mode"] = "exploratory_age_extrapolation"
    allowed = evaluate_scenario(scenario)
    assert allowed["engine_status"] == "scenario_available"
    assert allowed["support"]["grade"] == "C"
    assert allowed["support"]["extrapolation"] == "age_only"


def test_d21_not_cured_is_not_applicable_not_low_risk() -> None:
    scenario = default_scenario()
    scenario["d21_status"] = "not_cured"
    result = evaluate_scenario(scenario)
    assert result["engine_status"] == "not_applicable"
    assert result["scenario_estimate"] is None
    assert result["support"]["grade"] == "not_evaluated"


def test_prohibited_fields_are_blocked_without_echo() -> None:
    scenario = default_scenario()
    scenario["USUBJID"] = "not-a-real-subject"
    result = evaluate_scenario(scenario)
    rendered = json.dumps(result, ensure_ascii=False)
    assert result["engine_status"] == "invalid_input"
    assert "unknown_or_prohibited_fields" in result["reason_codes"]
    assert "not-a-real-subject" not in rendered


def test_population_insight_is_aggregate_only() -> None:
    result = population_summary()
    assert result["source_population"]["d104_observed_n"] == 31
    assert result["source_population"]["d104_recurrence_n"] == 16
    assert result["privacy"].startswith("aggregate only")
    rendered = json.dumps(result)
    for identifier in ["USUBJID", "SUBJID", "RANDID"]:
        assert identifier not in rendered


def test_phase2_population_scopes_use_governed_counts() -> None:
    expected = {
        "fas_ss": 74,
        "pps": 57,
        "d24_cured": 34,
        "d104_evaluable": 31,
    }
    for scope, source_n in expected.items():
        result = population_summary(population_scope=scope)
        assert result["population_scope"]["id"] == scope
        assert result["population_scope"]["source_n"] == source_n
        assert result["filter_summary"]["selected_n"] == source_n
        assert result["filter_summary"]["source_n"] == source_n
        assert result["population_scope"]["model_source_population"] is (
            scope == "d104_evaluable"
        )
        rendered = json.dumps(result)
        for identifier in ["USUBJID", "SUBJID", "RANDID"]:
            assert identifier not in rendered


def test_phase2_outcome_groups_are_selectable_with_exact_counts() -> None:
    expected = {
        "d104_evaluable": 31,
        "d104_recurrence": 16,
        "d104_nonrecurrence": 15,
        "d104_unknown": 3,
    }
    for outcome_group, source_n in expected.items():
        result = population_summary(
            population_scope="d24_cured",
            outcome_group=outcome_group,
        )
        assert result["outcome_group"]["id"] == outcome_group
        assert result["outcome_group"]["source_n"] == source_n
        assert result["filter_summary"]["selected_n"] == source_n
        assert result["filter_summary"]["status"] == "available"
    unknown = population_summary(
        population_scope="d24_cured",
        outcome_group="d104_unknown",
    )
    assert unknown["filter_summary"]["selected_n_display"] == "3"
    assert "exact counts enabled" in unknown["privacy"]


def test_population_filters_show_exact_small_group_counts() -> None:
    filtered = population_summary({"age_years_range": [20, 45]})
    assert filtered["filter_summary"]["status"] == "available"
    assert filtered["filter_summary"]["selected_n"] == 24
    assert filtered["filter_summary"]["retention_display"] == "77.4%"
    assert filtered["filter_summary"]["endpoint_rate_available"] is False
    assert filtered["numeric_summaries"]

    sparse = population_summary({"age_years_range": [18.48, 18.49]})
    assert sparse["filter_summary"]["status"] == "available"
    assert sparse["filter_summary"]["selected_n"] == 1
    assert sparse["filter_summary"]["selected_n_display"] == "1"
    assert sparse["numeric_summaries"]
    assert sparse["category_counts"]
    rendered = json.dumps(sparse)
    for identifier in ["USUBJID", "SUBJID", "RANDID"]:
        assert identifier not in rendered


def test_report_preserves_versions_and_explicit_limitations() -> None:
    scenario = default_scenario()
    result = evaluate_scenario(scenario)
    report = build_scenario_report(
        scenario_name="synthetic-test",
        scenario=scenario,
        result=result,
    )
    assert report["report"]["planning_stage"] == "exploratory"
    assert report["registry"]["engine_version"] == "2.3.0"
    assert "三期成功率" in report["interpretation"]["not_allowed"]
    assert "患者高、中、低风险分类" in report["interpretation"]["not_allowed"]


def test_frontend_asset_failures_are_fail_closed_and_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> object:
        raise OSError("synthetic registered asset failure")

    monkeypatch.setattr(frontend_app, "engine_health", unavailable)
    health = frontend_app.safe_engine_health()
    assert health["status"] == "unavailable"
    assert health["artifact_hashes_verified"] is False
    assert health["source_observed_labels"] == "不可用"

    monkeypatch.setattr(frontend_app, "population_summary", unavailable)
    monkeypatch.setattr(frontend_app, "registry_snapshot", unavailable)
    monkeypatch.setattr(frontend_app, "warning_catalog", unavailable)
    assert frontend_app.safe_population_summary() is None
    assert frontend_app.safe_registry_snapshot()["internal_validation"] is None
    catalog = frontend_app.safe_warning_catalog()
    assert set(catalog) == {f"W{index:03d}" for index in range(1, 15)}
    assert all("数值功能已阻断" in item["display_zh"] for item in catalog.values())


def test_direction_accessible_labels_never_expose_internal_encodings() -> None:
    known = frontend_app.direction_parameter_label("num:age_years")
    unknown = frontend_app.direction_parameter_label("num:unknown_internal_field")
    assert known == "年龄"
    assert unknown == "其他基线特征"
    assert "num:" not in known + unknown


def test_report_registry_failure_preserves_report_without_substitute_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = default_scenario()
    result = evaluate_scenario(scenario)

    def unavailable() -> object:
        raise OSError("synthetic registry failure")

    monkeypatch.setattr(reporting_module, "registry_snapshot", unavailable)
    report = reporting_module.build_scenario_report(
        scenario_name="synthetic-registry-fallback",
        scenario=scenario,
        result=result,
    )
    assert report["registry"]["status"] == "unavailable"
    assert report["registry"]["engine_version"] == "2.3.0"
    assert "no substitute statistics" in report["registry"]["note"]


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_feedback_local_save_target_and_receipt_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "0")
    monkeypatch.setenv(
        "XLF055_FEEDBACK_NOTIFY_TO", "feedback@example.com"
    )
    monkeypatch.setenv(
        "XLF055_FEEDBACK_SMTP_PASSWORD_FILE", str(tmp_path / "absent")
    )
    result = submit_feedback(
        category="功能问题",
        impact="一般建议",
        source_page="主界面",
        title="合成验收反馈",
        description="仅用于本地自动化验收，不包含病例信息。",
        reproduction_steps="打开页面",
        expected_behavior="安全保存",
        contact="qa@example.com",
        app_version="frontend-2.3.0/backend-2.2.0",
        attachments=[("safe.png", _png_bytes())],
    )
    assert result["stored_locally"] is True
    assert result["queued_messages"] == 2
    assert result["delivery_status"] == "queued_email_channel_not_enabled"
    path = database_path()
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with sqlite3.connect(path) as connection:
        recipients = {
            row[0]
            for row in connection.execute(
                "SELECT recipient FROM email_outbox"
            ).fetchall()
        }
        assert recipients == {"feedback@example.com", "qa@example.com"}
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM email_outbox WHERE status='pending'"
            ).fetchone()[0]
            == 2
        )


def test_feedback_rejects_invalid_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "0")
    with pytest.raises(FeedbackError, match="PNG或JPG"):
        submit_feedback(
            category="功能问题",
            impact="一般建议",
            source_page="主界面",
            title="无效附件",
            description="测试无效附件。",
            reproduction_steps="",
            expected_behavior="",
            contact="",
            app_version="frontend-2.3.0/backend-2.2.0",
            attachments=[("fake.png", b"not-an-image")],
        )



def test_feedback_recipient_comes_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "0")
    monkeypatch.setenv("XLF055_FEEDBACK_NOTIFY_TO", "feedback-team@example.com")
    monkeypatch.setenv("SPONSOR_FEEDBACK_NOTIFY_TO", "legacy@example.com")
    submit_feedback(
        category="功能问题",
        impact="一般建议",
        source_page="主界面",
        title="固定收件人验收",
        description="不包含病例信息。",
        reproduction_steps="",
        expected_behavior="",
        contact="",
        app_version="frontend-2.3.0/backend-2.2.0",
    )
    with sqlite3.connect(database_path()) as connection:
        recipient = connection.execute(
            "SELECT recipient FROM email_outbox"
        ).fetchone()[0]
    assert recipient == "feedback-team@example.com"
    assert email_channel_status()["notify_to"] == "feedback-team@example.com"


def test_bad_smtp_configuration_never_turns_saved_feedback_into_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "1")
    monkeypatch.setenv("XLF055_FEEDBACK_SMTP_PORT", "not-an-integer")
    result = submit_feedback(
        category="功能问题",
        impact="一般建议",
        source_page="主界面",
        title="坏配置仍保存",
        description="本地保存与SMTP解析解耦。",
        reproduction_steps="",
        expected_behavior="",
        contact="",
        app_version="frontend-2.3.0/backend-2.2.0",
    )
    assert result["stored_locally"] is True
    assert result["email_delivery_requested"] is True
    worker = process_email_outbox(limit=1)
    assert worker["configured"] is False
    assert worker["config_error"] is True
    assert worker["pending_email_count"] == 1


def test_postcommit_hardening_failure_never_misreports_feedback_as_unsaved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "0")
    original = feedback_module._harden_database_files
    calls = 0

    def fail_only_after_commit() -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("synthetic post-commit chmod failure")
        original()

    monkeypatch.setattr(
        feedback_module, "_harden_database_files", fail_only_after_commit
    )
    result = submit_feedback(
        category="功能问题",
        impact="一般建议",
        source_page="问题反馈",
        title="提交后权限复核异常",
        description="已提交记录不能误报为未保存。",
        reproduction_steps="",
        expected_behavior="返回已保存并提示管理员复核权限",
        contact="",
        app_version="frontend-2.3.0/backend-2.2.0",
    )
    assert result["stored_locally"] is True
    assert result["storage_hardening_verified"] is False
    with sqlite3.connect(database_path()) as connection:
        count = connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    assert count == 1


def test_attachment_failure_cleans_previously_written_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "0")
    with pytest.raises(FeedbackError, match="PNG或JPG"):
        submit_feedback(
            category="功能问题",
            impact="一般建议",
            source_page="主界面",
            title="附件回滚",
            description="第二张附件失败时清理第一张。",
            reproduction_steps="",
            expected_behavior="",
            contact="",
            app_version="frontend-2.3.0/backend-2.2.0",
            attachments=[
                ("first.png", _png_bytes()),
                ("second.png", b"invalid-image"),
            ],
        )
    assert list(upload_root().iterdir()) == []
    assert aggregate_status()["feedback_count"] == 0


def test_feedback_rejects_mail_header_control_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "0")
    with pytest.raises(FeedbackError, match="控制字符"):
        submit_feedback(
            category="功能问题",
            impact="一般建议",
            source_page="主界面",
            title="标题\n伪造头",
            description="测试邮件头清洗。",
            reproduction_steps="",
            expected_behavior="",
            contact="",
            app_version="frontend-2.3.0/backend-2.2.0",
        )


def test_outbox_claim_is_single_and_smtp_does_not_hold_database_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "1")
    submit_feedback(
        category="功能问题",
        impact="一般建议",
        source_page="问题反馈",
        title="并发领取验收",
        description="仅使用本地fake SMTP。",
        reproduction_steps="",
        expected_behavior="只发送一次",
        contact="",
        app_version="frontend-2.3.0/backend-2.2.0",
    )
    fake_settings = {
        "host": "fake.local",
        "port": 465,
        "sender": "sender@example.com",
        "password": "never-used",
        "notify_to": "feedback@example.com",
        "from_name": "XLF055规划工具",
    }
    monkeypatch.setattr(feedback_module, "smtp_settings", lambda: fake_settings)
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    calls_lock = threading.Lock()

    class BlockingSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "BlockingSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def login(self, *args: object) -> None:
            pass

        def send_message(self, message: object) -> None:
            with calls_lock:
                calls.append("send")
            started.set()
            if not release.wait(timeout=10):
                raise TimeoutError("synthetic SMTP release timeout")

    monkeypatch.setattr(feedback_module.smtplib, "SMTP_SSL", BlockingSMTP)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(process_email_outbox, 1)
        assert started.wait(timeout=5)
        second_worker = process_email_outbox(limit=1)
        before = time.monotonic()
        second_feedback = submit_feedback(
            category="功能问题",
            impact="一般建议",
            source_page="问题反馈",
            title="SMTP阻塞期间写入",
            description="网络发送期间数据库仍可短事务写入。",
            reproduction_steps="",
            expected_behavior="快速保存",
            contact="",
            app_version="frontend-2.3.0/backend-2.2.0",
        )
        elapsed = time.monotonic() - before
        release.set()
        first_worker = future.result(timeout=10)
    assert first_worker["selected"] == 1
    assert first_worker["sent"] == 1
    assert second_worker["selected"] == 0
    assert second_feedback["stored_locally"] is True
    assert elapsed < 2.0
    assert calls == ["send"]


def test_feedback_storage_permissions_include_database_wal_and_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "0")
    result = submit_feedback(
        category="界面体验",
        impact="一般建议",
        source_page="问题反馈",
        title="权限验收",
        description="验证私有目录与文件权限。",
        reproduction_steps="",
        expected_behavior="目录0700且文件0600",
        contact="",
        app_version="frontend-2.3.0/backend-2.2.0",
        attachments=[("safe.png", _png_bytes())],
    )
    assert result["storage_hardening_verified"] is True
    assert stat.S_IMODE(feedback_root().stat().st_mode) == 0o700
    assert stat.S_IMODE(upload_root().stat().st_mode) == 0o700
    with sqlite3.connect(database_path()) as connection:
        attachment_json = connection.execute(
            "SELECT attachments_json FROM feedback"
        ).fetchone()[0]
    relative = json.loads(attachment_json)[0]["relative_path"]
    attachment = feedback_root() / relative
    assert stat.S_IMODE(attachment.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(attachment.stat().st_mode) == 0o600
    connection = feedback_module._connect()
    try:
        assert stat.S_IMODE(database_path().stat().st_mode) == 0o600
        sidecars = [
            Path(str(database_path()) + "-wal"),
            Path(str(database_path()) + "-shm"),
        ]
        assert all(candidate.exists() for candidate in sidecars)
        assert all(stat.S_IMODE(candidate.stat().st_mode) == 0o600 for candidate in sidecars)
    finally:
        connection.close()


def test_outbox_reaches_explicit_terminal_failure_after_four_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "1")
    submit_feedback(
        category="功能问题",
        impact="一般建议",
        source_page="主界面",
        title="重试终态",
        description="不发送真实邮件。",
        reproduction_steps="",
        expected_behavior="",
        contact="",
        app_version="frontend-2.3.0/backend-2.2.0",
    )
    fake_settings = {
        "host": "invalid.local",
        "port": 465,
        "sender": "sender@example.com",
        "password": "never-used",
        "notify_to": "feedback@example.com",
        "from_name": "XLF055规划工具",
    }
    monkeypatch.setattr(feedback_module, "smtp_settings", lambda: fake_settings)

    class BrokenSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise OSError("synthetic SMTP failure")

    monkeypatch.setattr(feedback_module.smtplib, "SMTP_SSL", BrokenSMTP)
    latest = None
    for attempt in range(4):
        latest = process_email_outbox(limit=1)
        if attempt < 3:
            with sqlite3.connect(database_path()) as connection:
                connection.execute(
                    "UPDATE email_outbox SET next_attempt_at='' WHERE status='retry'"
                )
                connection.commit()
    assert latest is not None
    assert latest["permanent_failed"] == 1
    assert latest["terminal_failed_count"] == 1
    assert latest["pending_email_count"] == 0
    with sqlite3.connect(database_path()) as connection:
        status_value, attempts = connection.execute(
            "SELECT status, attempts FROM email_outbox"
        ).fetchone()
    assert status_value == "failed"
    assert attempts == 4
