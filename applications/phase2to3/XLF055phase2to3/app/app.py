from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import hmac
import html
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any
import uuid
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import streamlit as st


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from planning_tool.engine import (
    ENGINE_VERSION,
    OUTCOME_GROUPS_BY_POPULATION,
    POPULATION_OUTCOME_GROUPS,
    POPULATION_SCOPES,
    engine_health,
    evaluate_scenario,
    population_summary,
    registry_snapshot,
    warning_catalog,
)
from planning_tool.feedback import (
    FeedbackError,
    submit_feedback,
)
from planning_tool.reporting import build_scenario_report, report_json_bytes


# Labels retained for the governing Skill structural validator:
SKILL_FEATURE_LABELS = (
    "Scenario exploration",
    "Phase II population insights",
    "Scenario comparison and management",
    "Methods, assumptions, and limitations",
    "Changelog",
    "Feedback",
    "Save scenario",
    "Anchor scenario",
    "Download scenario report",
)
UNSUPPORTED_RESULT_STATUS = "unsupported"

CONFIG_PATH = APP_ROOT / "project_config.json"
CHANGELOG_PATH = APP_ROOT / "runtime" / "changelog.json"
P3_EARLY_CONSISTENCY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "model_development"
    / "v2_6_p3_early_validation"
    / "p3_blinded_early_validation_aggregate.json"
)
STYLE_PATH = APP_ROOT / "assets" / "style.css"
LOGO_PATH = APP_ROOT / "assets" / "blueballoon_logo.png"
TZ = ZoneInfo("Asia/Shanghai")
NAVIGATION = [
    "情景探索",
    "二期人群洞察",
    "情景对比",
    "使用说明",
    "更新日志",
    "问题反馈",
]
NAVIGATION_ICONS = {
    "情景探索": ":material/tune:",
    "二期人群洞察": ":material/groups:",
    "情景对比": ":material/compare_arrows:",
    "使用说明": ":material/menu_book:",
    "更新日志": ":material/history:",
    "问题反馈": ":material/bug_report:",
}
PRIMARY_ANCHOR_ID = "__population__"
SENSITIVITY_ANCHOR_ID = "__sensitivity__"
CORE_WARNING_IDS = ["W001", "W002", "W003", "W004", "W005", "W013", "W014"]
FRIENDLY_FIELDS = {
    "age_years": "年龄",
    "baseline_bmi": "BMI",
    "baseline_vaginal_ph": "阴道pH",
    "baseline_nugent_score": "Nugent评分",
    "baseline_av_score": "AV评分",
    "any_medical_history": "既往病史",
    "baseline_lactobacillus_grade": "乳杆菌分级",
}
DIRECTION_LABELS = {
    "num:age_years": "年龄",
    "num:baseline_bmi": "BMI",
    "num:baseline_vaginal_ph": "阴道pH",
    "num:baseline_nugent_score": "Nugent评分",
    "num:baseline_av_score": "AV评分",
    "num:any_medical_history": "既往病史",
    "cat:baseline_lactobacillus_grade=I级或II级": "乳杆菌I/II级",
}
REASON_MESSAGES = {
    "request_not_json_object": "输入结构无效。",
    "unknown_or_prohibited_fields": "请求包含未允许字段；治疗组、标识符和治疗后变量不能输入。",
    "invalid_mode": "当前模式未开放。",
    "clinical_assumption_parameters_not_registered": "当前没有足够依据支持这种计算方式。",
    "missing_core_d21_status": "请选择D21治愈状态。",
    "invalid_d21_status": "D21状态无效。",
    "missing_core_inputs": "请完整填写年龄、BMI、阴道pH和Nugent评分。",
    "baseline_nugent_score_outside_target_range": "Nugent评分请选择7、8、9或10。",
    "baseline_av_score_outside_frozen_range": "AV评分请选择0–4或“未提供”。",
    "any_medical_history_unknown_category": "既往病史选项无法识别。",
    "baseline_lactobacillus_grade_unknown_category": "乳杆菌分级选项无法识别。",
    "age_outside_phase3_documented_range": "年龄超出三期方案18–55岁范围。",
    "age_extrapolation_requires_explicit_opt_in": "年龄超出二期范围；如需继续，请勾选“允许年龄扩展探索”。",
    "baseline_bmi_outside_phase2_range": "BMI超出当前二期数据覆盖范围。",
    "baseline_vaginal_ph_outside_phase2_range": "阴道pH超出当前二期数据覆盖范围。",
    "fewer_than_five_comparable_support_fields": "请在AV评分、既往病史或乳杆菌分级中至少提供一项。",
    "fewer_than_five_valid_reference_neighbors": "二期数据中没有足够相近的组合。",
    "model_preprocessor_unseen_category": "当前数据中没有可比较的类别。",
    "d21_not_cured": "D21未治愈时，当前定义下不计算D104复发情景。",
}

USER_WARNING_MESSAGES = {
    "W006": "当前组合在二期样本中较少，结果波动可能更大。",
    "W007": "年龄超出二期数据范围，本结果包含年龄外推，请谨慎解读。",
    "W008": "估计区间较宽，具体百分比可能随样本变化。",
    "W009": "D21尚未评估：以下结果表示“如果D21治愈”的条件性探索估计。",
    "W010": "D21未治愈时，当前定义下不计算D104复发情景。",
    "W011": "当前输入暂时无法生成复发概率，请根据下方原因调整参数。",
    "W012": "当前未开放没有数据依据的临床假设模式。",
}
SUPPORT_LABELS = {
    "A": ("来源范围内", "当前组合在二期数据覆盖范围内。"),
    "B": ("样本支持较少", "当前组合仍可计算，但相近二期受试者较少或信息不完整。"),
    "C": ("包含年龄外推", "年龄在三期18–55岁范围内，但超出二期来源范围。"),
    "unavailable": ("暂不可估计", "当前输入不满足计算所需的数据范围或完整性。"),
}


def user_warning_message(item: dict[str, Any]) -> str:
    return USER_WARNING_MESSAGES.get(
        str(item.get("id")),
        str(item.get("message") or "当前结果存在需要谨慎解读的限制。"),
    )


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _is_exact_zero_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _blocked_phase3_summary(message: str, reason_code: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "message": message,
        "reason_code": reason_code,
        "d104": None,
    }


def load_phase3_early_consistency_summary(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load only the frozen 2.6.1 aggregate blinded Phase III artifact."""
    target = Path(path) if path is not None else P3_EARLY_CONSISTENCY_PATH
    pending = {
        "status": "pending",
        "message": "P2模型尚未冻结，三期早期一致性检查待完成。",
        "d104": None,
    }
    if not target.is_file():
        return pending
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "unavailable",
            "message": "三期早期一致性汇总暂不可读取。",
            "d104": None,
        }
    if not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "message": "三期早期一致性汇总格式不符合要求。",
            "d104": None,
        }

    identity = payload.get("identity", {})
    safe_identity = (
        isinstance(identity, dict)
        and identity.get("version") == "2.6.1"
        and identity.get("status") == "early_descriptive_only"
    )
    if not safe_identity:
        return _blocked_phase3_summary(
            "三期聚合汇总的版本或用途状态不符合当前契约，因此不在页面展示。",
            "identity_contract_failed",
        )

    governance = payload.get("governance", {})
    evidence = payload.get("evidence", {})
    score_support = (
        evidence.get("score_support", {}) if isinstance(evidence, dict) else {}
    )
    safe_governance = (
        isinstance(governance, dict)
        and governance.get("p2_model_selection_frozen_before_p3_scoring") is True
        and governance.get("p3_training_or_tuning") is False
        and governance.get("actual_randomized_arm_used") is False
        and governance.get("blind_key_accessed") is False
        and governance.get(
            "baseline_mapping_amendment_frozen_before_rescoring"
        )
        is True
        and governance.get("baseline_mapping_outcome_driven") is False
        and _is_exact_zero_count(governance.get("patient_rows_persisted"))
        and isinstance(score_support, dict)
        and _is_exact_zero_count(score_support.get("patient_rows_persisted"))
    )
    if not safe_governance:
        return _blocked_phase3_summary(
            "三期汇总未通过盲态、训练隔离、基线映射冻结或隐私检查，因此不在页面展示。",
            "governance_contract_failed",
        )

    early = evidence.get("early_validation", {}) if isinstance(evidence, dict) else {}
    endpoint_counts = (
        evidence.get("endpoint_counts", {}) if isinstance(evidence, dict) else {}
    )
    outcome_bias = (
        evidence.get("outcome_availability_bias", {})
        if isinstance(evidence, dict)
        else {}
    )
    maturity = (
        endpoint_counts.get("d104_maturity", {})
        if isinstance(endpoint_counts, dict)
        else {}
    )
    d104 = early.get("d104_cumulative_label") if isinstance(early, dict) else None
    bias_contract = (
        isinstance(d104, dict)
        and d104.get("status") == "early_descriptive_only"
        and d104.get("outcome_availability_bias") is True
        and d104.get("interpretability")
        == "not_interpretable_as_accuracy_due_to_outcome_dependent_maturity"
        and isinstance(outcome_bias, dict)
        and outcome_bias.get("present") is True
        and bool(str(outcome_bias.get("mechanism", "")).strip())
        and bool(str(outcome_bias.get("consequence", "")).strip())
        and isinstance(maturity, dict)
        and _is_exact_zero_count(
            maturity.get("administrative_immaturity_coded_as_non_event")
        )
    )
    if not bias_contract:
        return _blocked_phase3_summary(
            "三期D104结局可观察性偏倚或行政性未成熟标记不完整，因此不展示检查数值。",
            "d104_outcome_availability_contract_failed",
        )

    directional: dict[str, dict[str, Any]] = {}
    direction_contract = True
    for endpoint_id in ("d44_observed_label", "d74_cumulative_label"):
        item = early.get(endpoint_id) if isinstance(early, dict) else None
        item_valid = (
            isinstance(item, dict)
            and item.get("status") == "early_descriptive_only"
            and item.get("interpretability") == "descriptive_direction_check_only"
            and "direction_only" in str(item.get("target_alignment", ""))
        )
        direction_contract = direction_contract and item_valid
        if item_valid:
            directional[endpoint_id] = {
                key: item.get(key)
                for key in (
                    "status",
                    "n",
                    "events",
                    "non_events",
                    "observed_rate",
                    "mean_predicted_probability",
                    "target_alignment",
                )
            }
    if not direction_contract:
        return _blocked_phase3_summary(
            "三期D44或D74未明确限定为早期方向性检查，因此不展示检查数值。",
            "early_direction_contract_failed",
        )

    allowed_numeric = {
        key: d104.get(key)
        for key in (
            "n",
            "events",
            "non_events",
            "observed_rate",
            "mean_predicted_probability",
            "brier",
            "log_loss",
            "calibration_in_the_large",
            "observed_to_expected",
            "roc_auc",
        )
    }
    model = payload.get("model", {})
    interpretation = payload.get("interpretation", {})
    return {
        "status": "available",
        "artifact_version": "2.6.1",
        "artifact_status": "early_descriptive_only",
        "message": (
            "已读取当前规范盲态数据截断的聚合早期方向一致性检查；"
            "三期数据从未用于模型训练、变量选择或调参。"
        ),
        "d104": {
            "status": str(d104.get("status")),
            **allowed_numeric,
            "metric_unavailable_reasons": d104.get(
                "metric_unavailable_reasons", []
            ),
        },
        "early_directional": directional,
        "outcome_availability_bias": {
            "present": True,
            "mechanism": str(outcome_bias["mechanism"]),
            "consequence": str(outcome_bias["consequence"]),
        },
        "model_version": (
            str(model.get("selected_model_version", "unavailable"))
            if isinstance(model, dict)
            else "unavailable"
        ),
        "conclusion": (
            str(interpretation.get("conclusion", ""))
            if isinstance(interpretation, dict)
            else ""
        ),
        "d104_maturity": {
            key: maturity.get(key)
            for key in (
                "outcome_observed",
                "definitely_not_yet_due",
                "maturity_unresolved_without_d1_and_menstrual_context",
                "maturity_unknown_no_d21_date",
                "administrative_immaturity_coded_as_non_event",
            )
        },
        "actual_randomized_arm_used": False,
        "patient_rows_persisted": 0,
    }

def safe_engine_health() -> dict[str, Any]:
    try:
        return engine_health()
    except Exception:
        return {
            "status": "unavailable",
            "engine_version": "unavailable",
            "registry_status": "unavailable",
            "evidence_status": "unavailable",
            "model_version": "unavailable",
            "source_observed_labels": "不可用",
            "source_events": "不可用",
            "artifact_hashes_verified": False,
            "patient_input_persistence": False,
        }


def safe_warning_catalog() -> dict[str, dict[str, str]]:
    try:
        return warning_catalog()
    except Exception:
        return {
            warning_id: {
                "display_zh": "注册警示目录暂不可用；数值功能已阻断，请联系管理员。",
                "severity": "critical",
            }
            for warning_id in [f"W{index:03d}" for index in range(1, 15)]
        }


def safe_population_summary(
    filters: dict[str, Any] | None = None,
    population_scope: str = "d104_evaluable",
    outcome_group: str = "all",
) -> dict[str, Any] | None:
    try:
        return population_summary(
            filters=filters,
            population_scope=population_scope,
            outcome_group=outcome_group,
        )
    except Exception:
        return None


def safe_registry_snapshot() -> dict[str, Any]:
    try:
        return registry_snapshot()
    except Exception:
        return {
            "status": "unavailable",
            "evidence_status": "unavailable",
            "internal_validation": None,
        }


def direction_parameter_label(parameter: object) -> str:
    text = str(parameter)
    if text in DIRECTION_LABELS:
        return DIRECTION_LABELS[text]
    field = text.split(":", 1)[-1].split("=", 1)[0]
    return FRIENDLY_FIELDS.get(field, "其他基线特征")


def runtime_compatibility(config: dict[str, Any]) -> dict[str, Any]:
    health = safe_engine_health()
    expected_backend = config.get("project", {}).get("backend_version")
    expected_model = config.get("project", {}).get("model_version")
    expected_contract = config.get("recurrence_scenario_engine", {}).get(
        "frontend_contract_version"
    )
    checks = {
        "engine_ready": health.get("status") == "ready",
        "backend_version": health.get("engine_version") == expected_backend == "2.3.0",
        "model_version": health.get("model_version") == expected_model == "2.1.0",
        "registry_status": health.get("registry_status")
        == "registered_backend_candidate_for_frontend_v2_6",
        "contract_version": expected_contract == "2.3.0",
        "artifact_hashes": health.get("artifact_hashes_verified") is True,
    }
    return {"ready": all(checks.values()), "checks": checks, "health": health}


def initialize_state() -> None:
    defaults = {
        "saved_scenarios": [],
        "saved_population_views": [],
        "anchor_id": PRIMARY_ANCHOR_ID,
        "active_page": NAVIGATION[0],
        "navigation_shadow": NAVIGATION[0],
        "current_request": None,
        "current_result": None,
        "current_error": None,
        "scenario_name": "",
        "feedback_last_submit": 0.0,
        "result_motion_enabled": True,
        "ui_notice": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_session_state() -> None:
    # Explicit widget values prevent browser-side widget rehydration after clear.
    preserved = {
        key: value
        for key, value in st.session_state.items()
        if key.startswith("_demo_access_")
        or key in {"active_page", "navigation_shadow", "result_motion_enabled"}
    }
    st.session_state.clear()
    initialize_state()
    st.session_state.update(preserved)
    st.session_state.update(
        {
            "case_allow_age_extrapolation": False,
            "case_d21": "尚未评估（条件预测）",
            "case_age": None,
            "case_bmi": None,
            "case_ph": None,
            "case_nugent": None,
            "case_av": None,
            "case_mh": None,
            "case_lacto": None,
        }
    )


def inject_style() -> None:
    st.markdown(f"<style>{STYLE_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def _positive_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def _portal_ticket_is_valid(token: str, expected_tool: str) -> tuple[bool, str]:
    """Validate a short-lived ticket issued by the BlueLab portal."""
    secret = os.environ.get("PORTAL_TICKET_SECRET", "").strip()
    if not token or not secret:
        return False, ""
    try:
        body, encoded_signature = token.split(".", 1)
        padding = "=" * (-len(encoded_signature) % 4)
        received_signature = base64.urlsafe_b64decode(encoded_signature + padding)
        expected_signature = hmac.new(
            secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(received_signature, expected_signature):
            return False, ""

        body_padding = "=" * (-len(body) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(body + body_padding).decode("utf-8")
        )
        now = int(time.time())
        issued_at = int(payload.get("iat", 0))
        expires_at = int(payload.get("exp", 0))
        client_id = str(payload.get("clientId", "")).strip()
        valid = (
            payload.get("tool") == expected_tool
            and bool(client_id)
            and issued_at <= now + 30
            and expires_at >= now
            and 0 < expires_at - issued_at <= 180
        )
        return valid, client_id if valid else ""
    except (ValueError, TypeError, json.JSONDecodeError):
        return False, ""


def _accept_portal_ticket(now: float) -> None:
    raw_ticket = st.query_params.get("portal_ticket", "")
    if isinstance(raw_ticket, list):
        raw_ticket = raw_ticket[0] if raw_ticket else ""
    valid, client_id = _portal_ticket_is_valid(str(raw_ticket), "xlf")
    if not valid:
        return
    st.session_state["_demo_access_granted"] = True
    st.session_state["_demo_access_granted_at"] = now
    st.session_state["_demo_access_failed_attempts"] = 0
    st.session_state["_demo_access_locked_until"] = 0
    st.session_state["_portal_client_id"] = client_id
    try:
        del st.query_params["portal_ticket"]
    except KeyError:
        pass
    st.rerun()


def _clear_demo_access() -> None:
    for key in (
        "_demo_access_granted",
        "_demo_access_granted_at",
        "_demo_access_failed_attempts",
        "_demo_access_locked_until",
    ):
        st.session_state.pop(key, None)


def demo_access_enabled() -> bool:
    return bool(os.environ.get("XLF055_APP_PASSWORD", "").strip())


def require_demo_access() -> None:
    """Render local sponsor access control without persisting credentials."""
    expected_password = os.environ.get("XLF055_APP_PASSWORD", "").strip()
    if not expected_password:
        return

    expected_user = os.environ.get("XLF055_APP_USERNAME", "BlueBalloon").strip()
    session_minutes = _positive_int_env(
        "XLF055_APP_SESSION_MINUTES", 480, 15, 1440
    )
    max_failures = _positive_int_env("XLF055_APP_MAX_FAILURES", 5, 3, 10)
    lock_seconds = _positive_int_env("XLF055_APP_LOCK_SECONDS", 60, 15, 900)
    now = time.time()
    _accept_portal_ticket(now)
    granted_at = float(st.session_state.get("_demo_access_granted_at") or 0)
    if (
        st.session_state.get("_demo_access_granted")
        and now - granted_at < session_minutes * 60
    ):
        return
    if st.session_state.get("_demo_access_granted"):
        _clear_demo_access()
        st.session_state["_demo_access_notice"] = "会话已结束，请重新登录。"

    locked_until = float(st.session_state.get("_demo_access_locked_until") or 0)
    remaining = max(0, int(locked_until - now))
    logo_html = ""
    if LOGO_PATH.exists():
        logo_data = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
        logo_html = (
            f'<img src="data:image/png;base64,{logo_data}" '
            'alt="Blue Ballon BlueLab">'
        )
    with st.container(border=False, key="demo_login_panel"):
        st.markdown(
            '<div class="demo-login-brand">'
            f'{logo_html}<div class="demo-login-kicker">受保护访问 · 甲方试用环境</div>'
            '<h1>Phase III规划探索</h1>'
            '<p>临床开发决策支持工具</p></div>',
            unsafe_allow_html=True,
        )
        notice = str(st.session_state.pop("_demo_access_notice", "") or "")
        if notice:
            st.info(notice)
        if remaining:
            st.warning(f"为保护试用账号，请在约{remaining}秒后重试。")
        else:
            with st.form("demo_access_login", clear_on_submit=False, border=False):
                username = st.text_input(
                    "访问账号",
                    autocomplete="username",
                    placeholder="请输入访问账号",
                )
                password = st.text_input(
                    "访问口令",
                    type="password",
                    autocomplete="current-password",
                    placeholder="请输入访问口令",
                )
                submitted = st.form_submit_button(
                    "登录", type="primary", width="stretch"
                )
            if submitted:
                valid_user = hmac.compare_digest(username.strip(), expected_user)
                valid_password = hmac.compare_digest(password, expected_password)
                if valid_user and valid_password:
                    st.session_state["_demo_access_granted"] = True
                    st.session_state["_demo_access_granted_at"] = now
                    st.session_state["_demo_access_failed_attempts"] = 0
                    st.session_state["_demo_access_locked_until"] = 0
                    st.rerun()
                failures = (
                    int(st.session_state.get("_demo_access_failed_attempts") or 0)
                    + 1
                )
                st.session_state["_demo_access_failed_attempts"] = failures
                if failures >= max_failures:
                    st.session_state["_demo_access_locked_until"] = now + lock_seconds
                    st.error("尝试次数过多，请稍后再试。")
                else:
                    st.error("账号或访问口令不正确。")
        st.markdown(
            '<div class="demo-login-boundary"><strong>使用边界</strong>'
            "本工具仅供授权用户进行探索性规划，不代表三期成功承诺。"
            "请勿转发访问凭据或包含受试者信息的截图。</div>"
            '<div class="demo-login-footer">本地试用版 2026.08 · 会话最长保留约'
            f"{session_minutes}分钟<br>访问异常请联系项目团队</div>",
            unsafe_allow_html=True,
        )
    st.stop()


def inline_help(text: str, *, label: str = "查看说明") -> str:
    escaped = html.escape(text)
    return (
        f'<span class="inline-help" tabindex="0" role="button" '
        f'aria-label="{html.escape(label)}">?'
        f'<span class="inline-help-tooltip" role="tooltip">{escaped}</span>'
        "</span>"
    )


def page_header(title: str, subtitle: str) -> None:
    st.markdown('<div class="product-kicker">XLF055 · 探索性规划工具</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(
        f'<div class="product-subtitle">{html.escape(subtitle)}</div>',
        unsafe_allow_html=True,
    )


def render_data_table(rows: list[dict[str, Any]], *, empty_message: str = "暂无数据。") -> None:
    """Render a responsive table without Arrow serialization."""
    if not rows:
        st.info(empty_message)
        return
    headers = list(rows[0])
    head = "".join(
        f'<th scope="col">{html.escape(str(value))}</th>' for value in headers
    )
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(row.get(header, '')))}</td>"
            for header in headers
        )
        + "</tr>"
        for row in rows
    )
    st.markdown(
        f'<div class="table-scroll" role="region" aria-label="数据表" tabindex="0">'
        f'<table class="data-table"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def render_critical_panel() -> None:
    st.markdown(
        """
        <div class="critical-panel" role="note">
          <strong>请先确认工具边界</strong>
          <ul>
            <li>结果是小样本模型产生的探索性估计，不是经过外部验证的个人诊断。</li>
            <li>D104复发结果以D21治愈为条件；D21未治愈时不适用。</li>
            <li>年龄扩展探索和稀疏组合会增加不确定性，页面会在结果前提示。</li>
            <li>结果不能用于治疗、入排、风险分级或减少方案规定的随访。</li>
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(value: str, label: str) -> str:
    classes = {
        "relative_higher_scenario": "badge-blue",
        "relative_lower_scenario": "badge-teal",
        "near_anchor_or_direction_uncertain": "badge-gray",
        "insufficient": "badge-gray",
        "low": "badge-amber",
        "moderate": "badge-blue",
        "relatively_stable": "badge-blue",
        "A": "badge-blue",
        "B": "badge-amber",
        "C": "badge-purple",
        "unavailable": "badge-gray",
    }
    return f'<span class="badge {classes.get(value, "badge-gray")}">{html.escape(label)}</span>'


def parse_numeric_text(value: object) -> object:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return text


def synthetic_request_from_widgets(
    *,
    allow_age_extrapolation: bool,
    d21_label: str | None,
    age: object,
    bmi: object,
    vaginal_ph: object,
    nugent: object,
    av_label: str | None,
    mh_label: str | None,
    lacto_label: str | None,
) -> dict[str, Any]:
    return {
        "age_years": parse_numeric_text(age),
        "baseline_bmi": parse_numeric_text(bmi),
        "baseline_vaginal_ph": parse_numeric_text(vaginal_ph),
        "baseline_nugent_score": parse_numeric_text(nugent),
        "baseline_av_score": (
            "missing" if av_label in {None, "未提供"} else parse_numeric_text(av_label)
        ),
        "any_medical_history": {
            "有": "yes",
            "无": "no",
            "未提供": "missing",
            None: "missing",
        }[mh_label],
        "baseline_lactobacillus_grade": {
            "I级或II级": "I_or_II",
            "III级或IV级": "III_or_IV",
            "未提供": "missing",
            None: "missing",
        }[lacto_label],
        "d21_status": {
            "尚未评估（条件预测）": "pending",
            "已治愈": "cured",
            "未治愈（本情景不适用）": "not_cured",
            None: None,
        }[d21_label],
        "mode": (
            "exploratory_age_extrapolation"
            if allow_age_extrapolation
            else "data_supported"
        ),
    }

def probability_interval_figure(
    result: dict[str, Any],
    anchor_value: float | None = None,
    anchor_label: str = "二期已观察人群",
) -> go.Figure:
    estimate = result["scenario_estimate"]
    median = 100 * estimate["posterior_median"]
    lower = 100 * estimate["lower_95"]
    upper = 100 * estimate["upper_95"]
    anchor_value = (
        result["anchors"]["primary_observed"]["rate"]
        if anchor_value is None
        else anchor_value
    )
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[median],
            y=["当前情景"],
            mode="markers",
            marker={
                "size": 17,
                "color": "#2456A6",
                "line": {"width": 2, "color": "#ffffff"},
            },
            error_x={
                "type": "data",
                "symmetric": False,
                "array": [upper - median],
                "arrayminus": [median - lower],
                "thickness": 4,
                "width": 9,
                "color": "#2456A6",
            },
            hovertemplate=(
                "复发概率 %{x:.1f}%<br>"
                f"估计区间 {lower:.1f}%–{upper:.1f}%<extra></extra>"
            ),
            name="当前情景",
        )
    )
    figure.add_vline(
        x=100 * anchor_value,
        line_dash="dash",
        line_color="#6C7890",
        annotation_text=f"{anchor_label} {100 * anchor_value:.1f}%",
        annotation_position="top right",
    )
    figure.update_layout(
        height=275,
        margin={"l": 75, "r": 35, "t": 55, "b": 45},
        xaxis={"title": "D104复发概率（%）", "range": [0, 100], "ticksuffix": "%"},
        yaxis={"title": ""},
        showlegend=False,
        hovermode="closest",
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return figure


def posterior_direction_figure(result: dict[str, Any]) -> go.Figure:
    position = result["scenario_position"]
    above = 100 * position["posterior_probability_above_anchor"]
    below = 100 * position["posterior_probability_below_anchor"]
    figure = go.Figure()
    figure.add_bar(
        y=["相对锚点方向"],
        x=[below],
        orientation="h",
        name="低于锚点",
        marker_color="#2A868A",
        text=[f"{below:.0f}%"],
        textposition="inside" if below >= 15 else "outside",
        hovertemplate="低于16/31锚点的后验抽样：%{x:.1f}%<extra></extra>",
    )
    figure.add_bar(
        y=["相对锚点方向"],
        x=[above],
        orientation="h",
        name="高于锚点",
        marker_color="#416FAE",
        text=[f"{above:.0f}%"],
        textposition="inside" if above >= 15 else "outside",
        hovertemplate="高于16/31锚点的后验抽样：%{x:.1f}%<extra></extra>",
    )
    figure.update_layout(
        barmode="stack",
        height=260,
        margin={"l": 110, "r": 35, "t": 55, "b": 40},
        xaxis={"title": "后验抽样比例（%）", "range": [0, 100], "ticksuffix": "%"},
        yaxis={"title": ""},
        legend={"orientation": "h", "y": 1.18, "x": 0},
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return figure


def direction_panel_figure(rows: list[dict[str, Any]]) -> go.Figure:
    ordered = list(reversed(rows))
    colors = []
    for row in ordered:
        label = str(row["label"])
        if "增加" in label:
            colors.append("#416FAE")
        elif "降低" in label:
            colors.append("#2A868A")
        else:
            colors.append("#8C97A7")
    figure = go.Figure(
        go.Bar(
            x=[100 * float(row["stability"]) for row in ordered],
            y=[direction_parameter_label(row["parameter"]) for row in ordered],
            orientation="h",
            marker_color=colors,
            text=[f"{100 * float(row['stability']):.0f}%" for row in ordered],
            textposition="auto",
            cliponaxis=True,
            customdata=[[row["label"]] for row in ordered],
            hovertemplate=(
                "%{y}<br>%{customdata[0]}<br>"
                "模型方向一致性 %{x:.1f}%<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        height=max(390, 54 * len(rows)),
        margin={"l": 70, "r": 25, "t": 30, "b": 60},
        xaxis={"title": "模型方向一致性（%）", "range": [0, 112], "ticksuffix": "%", "automargin": True},
        yaxis={"title": "", "automargin": True},
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return figure


def render_anchor_cards(result: dict[str, Any]) -> None:
    primary = result["anchors"]["primary_observed"]
    sensitivity = result["anchors"]["composite_sensitivity"]
    left, right = st.columns(2)
    left.metric(
        "二期已观察人群",
        f"{100 * primary['rate']:.1f}%",
        help=(
            "二期D24治愈且D104结局明确的31人中，16人复发（16/31）。"
            "这是可评价人群的直接观察结果，不是全部34人的结果。"
        ),
    )
    right.metric(
        "二期缺失按复发处理",
        f"{100 * sensitivity['rate']:.1f}%",
        help=(
            "二期D24治愈的34人中，将3名D104结局未知者均按复发处理，"
            "得到19/34。这是保守敏感性参考，不是主要模型标签。"
        ),
    )


def render_warning_items(
    result: dict[str, Any],
    *,
    include_ids: set[str] | None = None,
    exclude_ids: set[str] | None = None,
    heading: str | None = None,
) -> None:
    items = [
        item
        for item in result.get("warnings", [])
        if item["id"] not in CORE_WARNING_IDS
        and item["id"] != "W012"
        and (include_ids is None or item["id"] in include_ids)
        and (exclude_ids is None or item["id"] not in exclude_ids)
    ]
    if not items:
        return
    if heading:
        st.subheader(heading)
    for item in items:
        text = user_warning_message(item)
        if item["severity"] in {"critical", "high"}:
            st.warning(text)
        else:
            st.info(text)


def anchor_option_ids() -> list[str]:
    return [PRIMARY_ANCHOR_ID, SENSITIVITY_ANCHOR_ID] + [
        item["id"] for item in st.session_state.saved_scenarios
    ]


def anchor_option_label(anchor_id: str) -> str:
    if anchor_id == PRIMARY_ANCHOR_ID:
        return "二期已观察人群 · 51.6%（16/31）"
    if anchor_id == SENSITIVITY_ANCHOR_ID:
        return "二期缺失按复发处理 · 55.9%（19/34）"
    for item in st.session_state.saved_scenarios:
        if item["id"] == anchor_id:
            probability = 100 * float(
                item["result"]["scenario_estimate"]["posterior_median"]
            )
            return f"{item['name']} · {probability:.1f}%"
    return "二期已观察人群 · 51.6%（16/31）"


def ensure_anchor_is_valid() -> None:
    if st.session_state.get("anchor_id") not in anchor_option_ids():
        st.session_state.anchor_id = PRIMARY_ANCHOR_ID


def anchor_display_map() -> dict[str, str]:
    return {anchor_option_label(anchor_id): anchor_id for anchor_id in anchor_option_ids()}


def _sync_anchor_from_widget() -> None:
    selected_label = st.session_state.get("anchor_selector")
    selected_id = anchor_display_map().get(str(selected_label))
    if selected_id is not None:
        st.session_state.anchor_id = selected_id


def render_anchor_selector() -> None:
    ensure_anchor_is_valid()
    display_map = anchor_display_map()
    labels = list(display_map)
    desired_label = anchor_option_label(st.session_state.anchor_id)
    selector_value = st.session_state.get("anchor_selector")
    sync_pending = st.session_state.pop("anchor_selector_sync_pending", False)
    if sync_pending or selector_value not in labels:
        st.session_state.anchor_selector = desired_label
    st.selectbox(
        "比较锚点",
        options=labels,
        key="anchor_selector",
        help=(
            "51.6%是二期D104结局明确者16/31的直接观察率；55.9%是将3名"
            "D104未知者均按复发处理后的19/34敏感性参考。锚点只用于比较"
            "百分点，不会改变模型概率；高于锚点仅表示当前模型情景较高，"
            "不代表发现了新的风险因素或达到临床风险阈值。"
        ),
        on_change=_sync_anchor_from_widget,
    )


def active_anchor_reference() -> tuple[float, str]:
    anchor_id = st.session_state.get("anchor_id", PRIMARY_ANCHOR_ID)
    if anchor_id == SENSITIVITY_ANCHOR_ID:
        return 19 / 34, "二期缺失按复发处理"
    if anchor_id != PRIMARY_ANCHOR_ID:
        for item in st.session_state.saved_scenarios:
            if item["id"] == anchor_id:
                value = item["result"]["scenario_estimate"]["posterior_median"]
                return float(value), item["name"]
    return 16 / 31, "二期已观察人群"


def _valid_interval(
    item: object, *, probability: bool
) -> bool:
    if not isinstance(item, dict):
        return False
    try:
        lower = float(item["lower_95"])
        median = float(item["posterior_median"])
        upper = float(item["upper_95"])
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (lower, median, upper)):
        return False
    if not lower <= median <= upper:
        return False
    return (0 <= lower and upper <= 1) if probability else (-100 <= lower and upper <= 100)


def arm_scenario_detail_is_displayable(
    detail: object,
    scenario_estimate: object | None = None,
) -> bool:
    """Require a complete simultaneous pair; never permit partial arm display."""
    if not isinstance(detail, dict):
        return False
    valid = (
        detail.get("both_hypothetical_regimens_returned_together") is True
        and detail.get("actual_randomized_arm_input_accepted") is False
        and detail.get("actual_randomized_arm_used") is False
        and detail.get("individual_treatment_effect_supported") is False
        and _valid_interval(detail.get("one_to_one_standardized"), probability=True)
        and _valid_interval(detail.get("test_regimen"), probability=True)
        and _valid_interval(detail.get("control_regimen"), probability=True)
        and _valid_interval(
            detail.get("contrast_test_minus_control"), probability=False
        )
    )
    if not valid or scenario_estimate is None:
        return valid
    if not isinstance(scenario_estimate, dict):
        return False
    one_to_one = detail["one_to_one_standardized"]
    try:
        return all(
            math.isclose(
                float(one_to_one[key]),
                float(scenario_estimate[key]),
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            for key in (
                "posterior_median",
                "lower_95",
                "upper_95",
                "posterior_mean",
            )
        )
    except (KeyError, TypeError, ValueError):
        return False


def arm_evidence_context_is_displayable(context: object) -> bool:
    """Show observed and assumed evidence only when both complete pairs exist."""
    if not isinstance(context, dict) or context.get("sources_are_separate") is not True:
        return False
    observed = context.get("phase2_direct_observed")
    assumed = context.get("phase3_protocol_planning_assumptions")
    if not isinstance(observed, dict) or not isinstance(assumed, dict):
        return False
    try:
        for arm in ("test", "control"):
            observed_arm = observed[arm]
            assumed_arm = assumed[arm]
            events = int(observed_arm["events"])
            total = int(observed_arm["n"])
            observed_rate = float(observed_arm["rate"])
            assumed_rate = float(assumed_arm["rate"])
            if not (
                total > 0
                and 0 <= events <= total
                and math.isfinite(observed_rate)
                and 0 <= observed_rate <= 1
                and math.isfinite(assumed_rate)
                and 0 <= assumed_rate <= 1
            ):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _percent_interval_caption(item: dict[str, Any]) -> str:
    return (
        f"95%估计区间：{100 * float(item['lower_95']):.1f}%–"
        f"{100 * float(item['upper_95']):.1f}%"
    )


def render_hypothetical_arm_detail(result: dict[str, Any]) -> None:
    detail = result.get("arm_scenario_detail")
    if not arm_scenario_detail_is_displayable(
        detail, result.get("scenario_estimate")
    ):
        st.warning("试验与对照方案详情暂不可用；不会展示不完整的单组结果。")
        return

    assert isinstance(detail, dict)
    test = detail["test_regimen"]
    control = detail["control_regimen"]
    contrast = detail["contrast_test_minus_control"]
    context = detail.get("evidence_context", {})
    with st.expander("查看试验与对照方案详情", expanded=False):
        st.caption(
            "上方主结果仍是两种方案按1:1分配后的标准化结果。"
            "以下是在同一基线画像下同时切换两种方案得到的假设情景，"
            "不是受试者实际随机分组、个体治疗效应或治疗建议。"
        )
        test_col, control_col = st.columns(2)
        test_col.metric(
            "假设采用试验方案",
            f"{100 * float(test['posterior_median']):.1f}%",
            help="同一基线画像在假设试验方案下的探索性模型结果；不是实际用药后的个人风险。",
        )
        test_col.caption(_percent_interval_caption(test))
        control_col.metric(
            "假设采用对照方案",
            f"{100 * float(control['posterior_median']):.1f}%",
            help="同一基线画像在假设对照方案下的探索性模型结果；不是实际用药后的个人风险。",
        )
        control_col.caption(_percent_interval_caption(control))

        difference = float(contrast["posterior_median"])
        st.metric(
            "假设方案差（试验－对照）",
            f"{difference:+.1f} 个百分点",
            help="由同一批模型抽样逐次计算试验方案概率减去对照方案概率；负值表示试验方案的模型复发概率较低。",
        )
        st.caption(
            "95%估计区间："
            f"{float(contrast['lower_95']):+.1f} 至 "
            f"{float(contrast['upper_95']):+.1f} 个百分点。"
        )

        observed = (
            context.get("phase2_direct_observed", {})
            if isinstance(context, dict)
            else {}
        )
        assumed = (
            context.get("phase3_protocol_planning_assumptions", {})
            if isinstance(context, dict)
            else {}
        )
        observed_ready = arm_evidence_context_is_displayable(context)
        if observed_ready:
            st.markdown("**二期直接观察（小样本，不是模型预测）**")
            render_data_table(
                [
                    {
                        "方案": "试验方案",
                        "复发/可评价": (
                            f"{int(observed['test']['events'])}/"
                            f"{int(observed['test']['n'])}"
                        ),
                        "观察复发率": f"{100 * float(observed['test']['rate']):.1f}%",
                    },
                    {
                        "方案": "对照方案",
                        "复发/可评价": (
                            f"{int(observed['control']['events'])}/"
                            f"{int(observed['control']['n'])}"
                        ),
                        "观察复发率": f"{100 * float(observed['control']['rate']):.1f}%",
                    },
                ]
            )
            st.caption(
                "二期直接观察仅有2/7与6/10，样本非常稀疏，不能据此认定稳定治疗差异。"
            )
            st.markdown("**三期方案规划假设（不是观察结果）**")
            render_data_table(
                [
                    {
                        "方案": "试验方案",
                        "方案假设复发率": f"{100 * float(assumed['test']['rate']):.0f}%",
                    },
                    {
                        "方案": "对照方案",
                        "方案假设复发率": f"{100 * float(assumed['control']['rate']):.0f}%",
                    },
                ]
            )
            st.caption(
                "33%与55%来自三期方案的规划假设，和上面的二期直接观察、"
                "以及本次模型输出是三类不同证据。"
            )
        else:
            st.info("观察数据与方案假设的成对依据暂不可用，因此两者均不展示。")


def render_result(result: dict[str, Any], config: dict[str, Any]) -> None:
    del config
    st.subheader("复发概率结果")
    workflow = result.get("d21_workflow")
    if workflow and workflow["status"] == "pending":
        render_warning_items(result, include_ids={"W009"})

    if result["engine_status"] != "scenario_available":
        if result["engine_status"] == "not_applicable":
            st.info("D21未治愈：当前定义下不计算D104复发情景。")
        else:
            st.warning("当前组合暂时无法估算复发概率。")
        reasons = result.get("reason_codes", [])
        for reason in reasons:
            st.markdown(
                f"- {REASON_MESSAGES.get(reason, '当前输入暂不满足计算条件。')}"
            )
        with st.expander("查看二期参考数据"):
            render_anchor_cards(result)
            st.caption("以上是二期总体参考值，不是当前输入的预测结果。")
        return

    render_warning_items(result, include_ids={"W006", "W007"})
    estimate = result["scenario_estimate"]
    support = result["support"]
    stability = result["direction_stability"]
    anchor_value, anchor_label = active_anchor_reference()
    probability = float(estimate["posterior_median"])
    difference = 100 * (probability - anchor_value)
    movement = (
        f"较“{anchor_label}”增加 {abs(difference):.1f} 个百分点"
        if difference > 0.05
        else (
            f"较“{anchor_label}”降低 {abs(difference):.1f} 个百分点"
            if difference < -0.05
            else f"与“{anchor_label}”基本一致"
        )
    )
    motion_class = (
        " result-animate"
        if st.session_state.get("result_motion_enabled", True)
        else ""
    )
    st.markdown(
        f"""
        <div class="probability-hero{motion_class}">
          <div class="probability-eyebrow">D104复发探索概率</div>
          <div class="probability-value">{100 * probability:.1f}%</div>
          <div class="probability-context">以D21治愈为条件</div>
          <div class="probability-delta">{html.escape(movement)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    interval_left, anchor_right = st.columns(2)
    interval_left.metric(
        "估计区间",
        f"{100 * estimate['lower_95']:.1f}%–{100 * estimate['upper_95']:.1f}%",
        help="表示当前小样本与模型假设下的后验估计区间，不是确定的个人风险范围。",
    )
    anchor_right.metric(
        "当前比较锚点",
        f"{100 * anchor_value:.1f}%",
        help="锚点仅用于计算百分点差异；在页面顶部可以随时更换。",
    )
    render_hypothetical_arm_detail(result)
    render_warning_items(result, include_ids={"W008"})

    support_title, support_text = SUPPORT_LABELS.get(
        support["grade"], SUPPORT_LABELS["unavailable"]
    )
    st.markdown(
        f"""
        <div class="result-summary-grid">
          <div class="result-summary-item" tabindex="0">
            <span>数据覆盖 {inline_help(support_text, label="数据覆盖说明")}</span>
            <strong>{html.escape(support_title)}</strong>
          </div>
          <div class="result-summary-item" tabindex="0">
            <span>方向稳定程度 {inline_help("表示重复模型抽样中，当前情景相对锚点保持相同高低方向的程度。越高表示方向较少翻转，但不代表概率更准确，也不能弥补数据外推。", label="方向稳定程度说明")}</span>
            <strong>{html.escape(stability["display_zh"])}</strong>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.plotly_chart(
        probability_interval_figure(result, anchor_value, anchor_label),
        width="stretch",
        config={"displayModeBar": False, "responsive": True},
        key="probability_interval_chart",
    )
    render_warning_items(
        result,
        exclude_ids={"W006", "W007", "W008", "W009", "W010", "W011"},
        heading="其他需要注意",
    )
    with st.expander("查看基线特征的模型方向"):
        st.caption(
            "模型方向一致性越高，表示重复抽样中该特征对应的高低方向越少翻转；"
            "它不表示效应大小、预测准确率或因果关系。结果仅用于提出关注点。"
        )
        st.plotly_chart(
            direction_panel_figure(result["direction_panel"]),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
            key="feature_direction_chart",
        )

def save_current_scenario(*, set_anchor: bool = False) -> str | None:
    result = st.session_state.current_result
    request = st.session_state.current_request
    if not result or result.get("engine_status") != "scenario_available":
        st.warning("请先成功运行一个情景。")
        return None
    if len(st.session_state.saved_scenarios) >= 20:
        st.warning("当前会话最多保存20个情景，请先删除不需要的情景。")
        return None
    name = st.session_state.get("scenario_name", "").strip()[:40]
    if not name:
        name = f"情景 {len(st.session_state.saved_scenarios) + 1}"
    existing = {item["name"] for item in st.session_state.saved_scenarios}
    base = name
    suffix = 2
    while name in existing:
        name = f"{base} ({suffix})"
        suffix += 1
    item_id = uuid.uuid4().hex[:12]
    st.session_state.saved_scenarios.append(
        {
            "id": item_id,
            "name": name,
            "scenario": request,
            "result": result,
            "saved_at": datetime.now(TZ).isoformat(timespec="seconds"),
        }
    )
    if set_anchor:
        st.session_state.anchor_id = item_id
        st.session_state.anchor_selector_sync_pending = True
        st.session_state.ui_notice = f"已保存“{name}”并设为比较锚点。"
    else:
        st.session_state.ui_notice = f"已在当前会话保存“{name}”。"
    return item_id


def load_synthetic_example() -> None:
    st.session_state.update(
        {
            "case_allow_age_extrapolation": False,
            "case_d21": "尚未评估（条件预测）",
            "case_age": 35.7,
            "case_bmi": 21.6,
            "case_ph": 4.8,
            "case_nugent": 8,
            "case_av": "2",
            "case_mh": "无",
            "case_lacto": "III级或IV级",
            "current_request": None,
            "current_result": None,
            "current_error": None,
        }
    )


def scenario_explorer(config: dict[str, Any]) -> None:
    page_header(
        "情景探索",
        "输入拟入组人群的基线信息，查看D21治愈条件下的D104复发探索概率。",
    )
    notice = st.session_state.pop("ui_notice", None)
    if notice:
        st.success(notice)

    action_left, anchor_right = st.columns([1, 1.45])
    if action_left.button(
        "加载演示参数",
        key="load_synthetic_example",
        width="stretch",
        help=(
            "加载一组非真实受试者参数：35.7岁、BMI 21.6、pH 4.8、"
            "Nugent 8、AV 2、无既往病史、乳杆菌III/IV级。"
        ),
    ):
        load_synthetic_example()
        st.rerun()
    with anchor_right:
        render_anchor_selector()

    st.subheader("输入参数")
    with st.form("scenario_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            d21_label = st.selectbox(
                "D21治愈状态",
                ["尚未评估（条件预测）", "已治愈", "未治愈（本情景不适用）"],
                index=0,
                key="case_d21",
                help=(
                    "新入组受试者通常选择“尚未评估”；结果表示如果D21治愈时，"
                    "截至D104发生复发的条件性情景。"
                ),
            )
            age = st.number_input(
                "年龄（岁）",
                min_value=18.0,
                max_value=55.0,
                value=None,
                step=0.1,
                format="%.1f",
                key="case_age",
                help="二期范围约18.5–51.7岁；18–55岁内可选择年龄扩展探索。",
            )
            bmi = st.number_input(
                "基线BMI（kg/m²）",
                min_value=16.2982,
                max_value=34.1422,
                value=None,
                step=0.1,
                format="%.1f",
                key="case_bmi",
                help="使用筛查/入组时的BMI；当前仅允许二期数据覆盖范围内取值。",
            )
            vaginal_ph = st.number_input(
                "基线阴道pH",
                min_value=4.2,
                max_value=5.2,
                value=None,
                step=0.1,
                format="%.1f",
                key="case_ph",
                help="使用治疗前阴道pH；当前仅允许二期数据覆盖范围内取值。",
            )
            allow_age_extrapolation = st.checkbox(
                "允许年龄在18–55岁内作扩展探索",
                key="case_allow_age_extrapolation",
                help="只放宽年龄；其他参数仍需处于二期数据范围内。",
            )
        with col2:
            nugent = st.selectbox(
                "基线Nugent评分",
                [7, 8, 9, 10],
                index=None,
                key="case_nugent",
                placeholder="请选择7–10",
                help="Nugent评分是阴道微生态的基线评分；本项目当前支持7–10分。",
            )
            av_label = st.selectbox(
                "基线AV评分",
                ["0", "1", "2", "3", "4", "未提供"],
                index=None,
                key="case_av",
                placeholder="请选择",
                help="AV评分为治疗前需氧性阴道炎评分；可选择未提供，但三个辅助字段至少提供一项。",
            )
            mh_label = st.selectbox(
                "是否有既往病史",
                ["有", "无", "未提供"],
                index=None,
                key="case_mh",
                placeholder="请选择",
                help="表示基线病史记录中是否存在既往病史；三个辅助字段至少提供一项。",
            )
            lacto_label = st.selectbox(
                "基线乳杆菌分级",
                ["III级或IV级", "I级或II级", "未提供"],
                index=None,
                key="case_lacto",
                placeholder="请选择",
                help="治疗前乳杆菌分级；可选择未提供，但三个辅助字段至少提供一项。",
            )
        run = st.form_submit_button(
            "运行情景",
            type="primary",
            width="stretch",
            help="根据当前基线参数生成探索性复发概率；不会保存病例参数。",
        )

    st.caption("请勿输入姓名或受试者编号；病例参数不会被持久保存。")
    if run:
        st.session_state.current_result = None
        st.session_state.current_error = None
        request = synthetic_request_from_widgets(
            allow_age_extrapolation=allow_age_extrapolation,
            d21_label=d21_label,
            age=age,
            bmi=bmi,
            vaginal_ph=vaginal_ph,
            nugent=nugent,
            av_label=av_label,
            mh_label=mh_label,
            lacto_label=lacto_label,
        )
        st.session_state.current_request = request
        gate = runtime_compatibility(config)
        if not gate["ready"]:
            st.session_state.current_error = (
                "计算服务当前未通过一致性检查，暂时不能生成数值。"
            )
        else:
            try:
                result = evaluate_scenario(request, config)
            except Exception:
                st.session_state.current_error = (
                    "计算服务暂时不可用，请稍后重试。"
                )
            else:
                provenance = result.get("provenance", {})
                compatible_result = (
                    result.get("contract_version") == "2.3.0"
                    and provenance.get("engine_version") == "2.3.0"
                    and provenance.get("model_version") == "2.1.0"
                )
                if not compatible_result:
                    st.session_state.current_error = (
                        "计算服务返回内容未通过一致性检查，暂时不能展示数值。"
                    )
                else:
                    st.session_state.current_result = result

    if st.session_state.current_error:
        st.error(st.session_state.current_error)
    elif st.session_state.current_result:
        render_result(st.session_state.current_result, config)
        if st.session_state.current_result.get("engine_status") == "scenario_available":
            st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
            st.subheader("保存与比较")
            st.text_input(
                "情景名称",
                key="scenario_name",
                max_chars=40,
                placeholder="例如：Nugent 8 · 无既往病史",
                help="名称只用于当前会话内识别和比较，不会随页面刷新永久保存。",
            )
            save_col, anchor_col, download_col = st.columns(3)
            if save_col.button(
                "保存情景",
                width="stretch",
                help="把当前参数和结果保存到本次浏览器会话。",
            ):
                if save_current_scenario():
                    st.rerun()
            if anchor_col.button(
                "保存并设为锚点",
                type="primary",
                width="stretch",
                help="保存当前情景，并把后续结果与它比较；不会改变预测算法。",
            ):
                if save_current_scenario(set_anchor=True):
                    st.rerun()
            report = build_scenario_report(
                scenario_name=st.session_state.get("scenario_name", ""),
                scenario=st.session_state.current_request,
                result=st.session_state.current_result,
            )
            download_col.download_button(
                "下载结果",
                data=report_json_bytes(report),
                file_name="xlf055_exploratory_scenario.json",
                mime="application/json",
                width="stretch",
                help="下载内容仅包含情景级汇总和必要的追溯信息。",
            )

def normalized_range_figure(rows: list[dict[str, Any]]) -> go.Figure:
    labels = []
    medians = []
    custom = []
    for row in rows:
        labels.append(FRIENDLY_FIELDS.get(row["field"], row["field"]))
        span = row["maximum"] - row["minimum"]
        medians.append(100 * (row["median"] - row["minimum"]) / span if span else 50)
        custom.append([row["minimum"], row["median"], row["maximum"]])
    labels = list(reversed(labels))
    medians = list(reversed(medians))
    custom = list(reversed(custom))
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=medians,
            y=labels,
            mode="markers",
            marker={"size": 14, "color": "#2456A6"},
            error_x={
                "type": "data",
                "symmetric": False,
                "array": [100 - x for x in medians],
                "arrayminus": medians,
                "thickness": 3,
                "width": 5,
                "color": "#A8B6C8",
            },
            customdata=custom,
            hovertemplate=(
                "%{y}<br>最小值 %{customdata[0]:.2f}<br>"
                "中位数 %{customdata[1]:.2f}<br>"
                "最大值 %{customdata[2]:.2f}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        height=410,
        margin={"l": 65, "r": 25, "t": 25, "b": 65},
        xaxis={
            "title": "中位数在观察范围中的相对位置（0%=最小值，100%=最大值）",
            "range": [-3, 103],
            "ticksuffix": "%",
        },
        yaxis={"title": "", "automargin": True},
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return figure


def completeness_figure(
    rows: list[dict[str, Any]], denominator: int
) -> go.Figure:
    labels = [FRIENDLY_FIELDS.get(row["field"], row["field"]) for row in rows]
    completeness = [
        100 * row["source_n"] / denominator if denominator else 0 for row in rows
    ]
    figure = go.Figure(
        go.Bar(
            x=completeness,
            y=labels,
            orientation="h",
            marker_color="#4E7CAF",
            text=[f"{value:.0f}%" for value in completeness],
            textposition="outside",
            cliponaxis=False,
            customdata=[[row["source_n"], denominator] for row in rows],
            hovertemplate=(
                "%{y}<br>可用 %{customdata[0]}/%{customdata[1]}"
                "<br>可用比例 %{x:.1f}%<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        height=380,
        margin={"l": 65, "r": 35, "t": 25, "b": 60},
        xaxis={
            "title": "当前人群中的数据可用比例",
            "range": [0, 108],
            "ticksuffix": "%",
            "automargin": True,
        },
        yaxis={"title": "", "autorange": "reversed", "automargin": True},
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return figure


def population_tick_step(source_n: int) -> int:
    if source_n <= 20:
        return 5
    if source_n <= 40:
        return 10
    return 20


def population_retention_figure(selected_n: int, source_n: int = 31) -> go.Figure:
    excluded = max(source_n - selected_n, 0)
    tick_step = population_tick_step(source_n)
    figure = go.Figure(go.Bar(
        y=["符合条件", "未纳入"],
        x=[selected_n, excluded],
        orientation="h",
        marker_color=["#2456A6", "#D0D9E5"],
        text=[
            f"{selected_n}人（{100 * selected_n / source_n:.1f}%）",
            f"{excluded}人（{100 * excluded / source_n:.1f}%）",
        ],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{y}<br>%{text}<extra></extra>",
    ))
    figure.update_layout(
        height=245,
        margin={"l": 78, "r": 130, "t": 28, "b": 45},
        xaxis={
            "title": "人数",
            "range": [0, max(source_n * 1.18, tick_step * 1.5)],
            "dtick": tick_step,
            "tickangle": 0,
            "tickformat": "d",
        },
        yaxis={"title": "", "autorange": "reversed"},
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
        transition={"duration": 250, "easing": "cubic-in-out"},
    )
    return figure


def phase2_population_flow_figure(source: dict[str, Any]) -> go.Figure:
    """Show the governed Phase II analysis populations without implying causality."""
    labels = [
        "筛选/登记",
        "FAS /<br>安全集",
        "符合方案集<br>（PPS）",
        "D24治愈<br>目标人群",
        "D104可评价<br>人群",
    ]
    values = [
        int(source["screened_n"]),
        int(source["fas_ss_n"]),
        int(source["pps_n"]),
        int(source["d24_cured_n"]),
        int(source["d104_observed_n"]),
    ]
    colors = ["#D6E4F0", "#8DB3D3", "#6D9BC3", "#3F79AD", "#175F97"]
    figure = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker_color=colors,
            text=[f"{value}人" for value in values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}<br>%{y}人<extra></extra>",
        )
    )
    figure.update_layout(
        height=330,
        margin={"l": 36, "r": 24, "t": 18, "b": 82},
        xaxis={"title": "", "tickangle": 0, "automargin": True},
        yaxis={
            "title": "人数",
            "range": [0, max(values) * 1.16],
            "nticks": 6,
            "tickangle": 0,
            "tickformat": "d",
        },
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return figure


def population_distribution_figure(
    field: str,
    rows: list[dict[str, Any]],
    selected_n: int,
) -> go.Figure:
    """Render privacy-protected horizontal bars with labels to the right."""
    ordered = list(reversed(rows))
    values = [int(row["count"]) for row in ordered]
    text = [
        f"{int(row['count'])}人（{100 * float(row['percentage']):.1f}%）"
        for row in ordered
    ]
    colors = ["#3B73AE" for _ in ordered]
    tick_step = population_tick_step(selected_n)
    figure = go.Figure(go.Bar(
        x=values,
        y=[str(row["category"]) for row in ordered],
        orientation="h",
        marker_color=colors,
        text=text,
        textposition="outside",
        cliponaxis=False,
        customdata=[[text_value] for text_value in text],
        hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>",
    ))
    figure.update_layout(
        title={"text": FRIENDLY_FIELDS.get(field, field), "x": 0.02, "xanchor": "left"},
        height=max(210, 44 * len(rows) + 100),
        margin={"l": 82, "r": 145, "t": 48, "b": 42},
        xaxis={
            "title": "人数",
            "range": [0, max(selected_n * 1.2, tick_step * 1.5)],
            "dtick": tick_step,
            "tickangle": 0,
            "tickformat": "d",
        },
        yaxis={"title": "", "automargin": True},
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
        transition={"duration": 250, "easing": "cubic-in-out"},
    )
    return figure


POPULATION_WIDGET_KEYS = (
    "insight_age_years",
    "insight_baseline_bmi",
    "insight_baseline_vaginal_ph",
    "insight_nugent",
    "insight_av",
    "insight_mh",
    "insight_lacto",
)


def _reset_population_scope_filters() -> None:
    st.session_state.pop("insight_outcome_group", None)
    _reset_population_outcome_filters()


def _reset_population_outcome_filters() -> None:
    st.session_state.pop("insight_selected_fields", None)
    for key in POPULATION_WIDGET_KEYS:
        st.session_state.pop(key, None)


def save_population_view(
    selected_fields: list[str],
    filters: dict[str, Any],
    population_scope: str,
    outcome_group: str,
) -> bool:
    saved = st.session_state.saved_population_views
    if len(saved) >= 20:
        st.warning("当前会话最多保存20个人群筛选，请先清空会话或复用已有筛选。")
        return False
    name = str(st.session_state.get("population_view_name", "")).strip()[:40]
    if not name:
        name = f"人群筛选 {len(saved) + 1}"
    existing = {item["name"] for item in saved}
    base = name
    suffix = 2
    while name in existing:
        name = f"{base} ({suffix})"
        suffix += 1
    widget_values = {
        key: st.session_state.get(key)
        for key in POPULATION_WIDGET_KEYS
        if key in st.session_state
    }
    saved.append({
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "population_scope": population_scope,
        "outcome_group": outcome_group,
        "selected_fields": list(selected_fields),
        "filters": json.loads(json.dumps(filters, ensure_ascii=False)),
        "widget_values": widget_values,
    })
    st.session_state.population_view_notice = f"已在当前会话保存“{name}”。"
    return True


def load_population_view(item: dict[str, Any]) -> None:
    st.session_state.insight_population_scope = item.get(
        "population_scope", "d104_evaluable"
    )
    st.session_state.insight_outcome_group = item.get("outcome_group", "all")
    st.session_state.insight_selected_fields = list(item["selected_fields"])
    for key in POPULATION_WIDGET_KEYS:
        st.session_state.pop(key, None)
    for key, value in item.get("widget_values", {}).items():
        st.session_state[key] = value
    st.session_state.population_view_notice = f"已载入“{item['name']}”。"


def population_insights_page() -> None:
    page_header(
        "二期人群洞察",
        "先查看二期分析人群全景，再选择人群和基线条件比较数据覆盖。",
    )
    overview_summary = safe_population_summary()
    if overview_summary is None:
        st.error("二期人群汇总暂时无法加载，请稍后重试。")
        return
    source = overview_summary["source_population"]
    notice = st.session_state.pop("population_view_notice", None)
    if notice:
        st.success(notice)
    overview = st.columns(4)
    overview[0].metric(
        "FAS / 安全集",
        f"{source['fas_ss_n']}人",
        help="进入二期主要疗效与安全性分析的人数。",
    )
    overview[1].metric(
        "符合方案集（PPS）",
        f"{source['pps_n']}人",
        help="符合方案分析要求的人数。",
    )
    overview[2].metric(
        "D24治愈目标人群",
        f"{source['d24_cured_n']}人",
        help="D24达到治愈、进入后续复发问题的人数。",
    )
    overview[3].metric(
        "D104可评价人群",
        f"{source['d104_observed_n']}人",
        help="D24治愈且D104累计复发结局明确的人数，也是当前模型来源人群。",
    )
    st.plotly_chart(
        phase2_population_flow_figure(source),
        width="stretch",
        config={"displayModeBar": False, "responsive": True},
        key="phase2_population_flow_chart",
    )
    st.caption(
        "PPS与D24治愈人群是面向不同分析问题的人群分支，并非彼此前后递进；"
        "当前模型仍仅来源于31名D104可评价受试者。"
    )

    saved_views = st.session_state.saved_population_views
    if saved_views:
        by_view_id = {item["id"]: item for item in saved_views}
        quick_left, quick_right = st.columns([1.45, 0.55])
        selected_view_id = quick_left.selectbox(
            "快速载入已保存的人群筛选",
            options=list(by_view_id),
            format_func=lambda item_id: by_view_id[item_id]["name"],
            key="population_quick_view_id",
            help="只载入人群筛选条件，不会载入或改变模型预测情景。",
        )
        with quick_right:
            st.write("")
            st.write("")
            if st.button("载入筛选", width="stretch", key="load_population_view"):
                load_population_view(by_view_id[selected_view_id])
                st.rerun()

    st.subheader("选择分析人群与条件")
    population_scope = st.selectbox(
        "第一步：分析人群",
        options=list(POPULATION_SCOPES),
        format_func=lambda scope: (
            f"{POPULATION_SCOPES[scope]['label']} · "
            f"{POPULATION_SCOPES[scope]['expected_n']}人"
        ),
        index=list(POPULATION_SCOPES).index("d104_evaluable"),
        key="insight_population_scope",
        on_change=_reset_population_scope_filters,
        help="切换后，下方筛选、数据覆盖和分布均以所选分析人群为分母。",
    )
    outcome_options = list(OUTCOME_GROUPS_BY_POPULATION[population_scope])
    if len(outcome_options) > 1:
        def outcome_label(group: str) -> str:
            expected_n = POPULATION_OUTCOME_GROUPS[group]["expected_n"]
            if group == "all":
                expected_n = POPULATION_SCOPES[population_scope]["expected_n"]
            return f"{POPULATION_OUTCOME_GROUPS[group]['label']} · {expected_n}人"

        outcome_group = st.selectbox(
            "第二步：结局状态",
            options=outcome_options,
            format_func=outcome_label,
            key="insight_outcome_group",
            on_change=_reset_population_outcome_filters,
            help=(
                "结局分组用于描述性筛查，不会作为模型输入，"
                "也不用于推断某项基线条件导致复发。"
            ),
        )
    else:
        outcome_group = "all"
        st.caption("第二步：该分析人群不再按D104结局细分。")
    base_summary = safe_population_summary(
        population_scope=population_scope,
        outcome_group=outcome_group,
    )
    if base_summary is None:
        st.error("所选二期人群暂时无法安全汇总，请稍后重试。")
        return
    scope = base_summary["population_scope"]
    if scope["model_source_population"]:
        st.info(scope["description"] + " 下方可同时查看当前模型适用性参考。")
    else:
        st.info(
            scope["description"]
            + " 下方仅展示基线分布；当前复发模型并非基于该完整人群建立。"
        )
    outcome = base_summary["outcome_group"]
    if outcome["outcome_defined"]:
        st.caption(
            f"当前结局分组：{outcome['label']}（{outcome['source_n']}人）。"
            "这是治疗后结局形成的人群，只用于描述性筛查。"
        )

    st.markdown("**第三步：基线条件（可选）**")
    filter_labels = {
        "age_years": "年龄",
        "baseline_bmi": "BMI",
        "baseline_vaginal_ph": "阴道pH",
        "baseline_nugent_score": "Nugent评分",
        "baseline_av_score": "AV评分",
        "any_medical_history": "既往病史",
        "baseline_lactobacillus_grade": "乳杆菌分级",
    }
    selected_fields = st.multiselect(
        "选择条件",
        options=list(filter_labels),
        format_func=lambda field: filter_labels[field],
        placeholder="可组合任意治疗前基线条件",
        help=(
            "可组合全部七项治疗前基线条件。条件越多，符合人数通常越少；"
            "当前受保护试用环境会显示筛选后的精确汇总人数。"
        ),
        key="insight_selected_fields",
    )
    full_rows = {
        row["field"]: row for row in base_summary["full_numeric_summaries"]
    }
    filters: dict[str, Any] = {}
    filter_columns = st.columns(2)
    for index, field in enumerate(selected_fields):
        with filter_columns[index % 2]:
            if field in {"age_years", "baseline_bmi", "baseline_vaginal_ph"}:
                row = full_rows[field]
                lower = float(row["minimum"])
                upper = float(row["maximum"])
                digits = 1 if field != "age_years" else 1
                selected_range = st.slider(
                    f"{filter_labels[field]}范围",
                    min_value=float(round(lower, digits)),
                    max_value=float(round(upper, digits)),
                    value=(
                        float(round(lower, digits)),
                        float(round(upper, digits)),
                    ),
                    step=0.1,
                    key=f"insight_{field}",
                    help="拖动左右端点设置纳入范围；边界值计入筛选。",
                )
                full_range = (
                    float(round(lower, digits)),
                    float(round(upper, digits)),
                )
                if tuple(selected_range) != full_range:
                    filters[f"{field}_range"] = list(selected_range)
            elif field == "baseline_nugent_score":
                values = st.multiselect(
                    "Nugent评分",
                    [7.0, 8.0, 9.0, 10.0],
                    default=[7.0, 8.0, 9.0, 10.0],
                    format_func=lambda value: str(int(value)),
                    key="insight_nugent",
                    help="选择允许纳入的治疗前Nugent评分；不减少选项表示不限。",
                )
                if values and len(values) < 4:
                    filters["baseline_nugent_score_values"] = values
            elif field == "baseline_av_score":
                values = st.multiselect(
                    "AV评分",
                    [0.0, 1.0, 2.0, 3.0, 4.0],
                    default=[0.0, 1.0, 2.0, 3.0, 4.0],
                    format_func=lambda value: str(int(value)),
                    key="insight_av",
                    help="选择允许纳入的治疗前AV评分；不减少选项表示不限。",
                )
                if values and len(values) < 5:
                    filters["baseline_av_score_values"] = values
            elif field == "any_medical_history":
                value = st.selectbox(
                    "既往病史",
                    ["不限", "有", "无"],
                    key="insight_mh",
                    help="按治疗前既往病史记录筛选；该条件不代表因果关系。",
                )
                if value != "不限":
                    filters["any_medical_history_values"] = [
                        1 if value == "有" else 0
                    ]
            else:
                value = st.selectbox(
                    "乳杆菌分级",
                    ["不限", "III级或IV级", "I级或II级"],
                    key="insight_lacto",
                    help="按治疗前乳杆菌分级筛选；该条件不代表因果关系。",
                )
                if value != "不限":
                    filters["baseline_lactobacillus_grade_values"] = [value]

    save_name_col, save_button_col = st.columns([1.45, 0.55])
    save_name_col.text_input(
        "保存当前人群筛选",
        key="population_view_name",
        max_chars=40,
        placeholder="例如：Nugent 8–10 · 无既往病史",
        help="仅保存在当前会话，并与模型预测情景分开管理。",
    )
    with save_button_col:
        st.write("")
        st.write("")
        if st.button("保存筛选", width="stretch", key="save_population_view"):
            if save_population_view(
                list(selected_fields), filters, population_scope, outcome_group
            ):
                st.rerun()

    summary = safe_population_summary(
        filters,
        population_scope,
        outcome_group,
    )
    if summary is None:
        st.error("当前筛选条件无法安全汇总，请调整后重试。")
        return
    filtered = summary["filter_summary"]
    selected_n = int(filtered["selected_n"])
    source_n = int(filtered["source_n"])
    scope_label = str(summary["population_scope"]["label"])
    if outcome_group != "all":
        scope_label += f" · {summary['outcome_group']['label']}"
    result_cols = st.columns(3)
    result_cols[0].metric(
        "符合条件",
        f"{selected_n}人",
        help=f"二期{source_n}名{scope_label}中符合当前条件的人数。",
    )
    result_cols[1].metric(
        "来源保留比例",
        filtered["retention_display"],
        help=f"符合条件人数除以{source_n}名{scope_label}。",
    )
    result_cols[2].metric(
        "未纳入",
        f"{source_n - selected_n}人",
        help="因当前筛选条件未纳入描述性汇总的人数。",
    )
    if filtered["labels"]:
        st.caption("当前条件：" + "；".join(filtered["labels"]))
    else:
        st.caption(
            f"当前未附加筛选条件，展示全部{source_n}名{scope_label}。"
        )

    st.subheader("人群保留情况")
    st.plotly_chart(
        population_retention_figure(selected_n, source_n),
        width="stretch",
        config={"displayModeBar": False, "responsive": True},
        key="population_retention_chart",
    )

    st.subheader("各基线参数的人群分布")
    distribution_rows = dict(summary.get("numeric_distributions", {}))
    category_display = {
        ("any_medical_history", "1"): "有",
        ("any_medical_history", "0"): "无",
        ("any_medical_history", "missing"): "未提供",
    }
    for field, counts in summary["category_counts"].items():
        distribution_rows[field] = [
            {
                "category": category_display.get((field, category), category),
                "count": int(count),
                "percentage": int(count) / selected_n,
                "small_cell": int(count) < 5,
            }
            for category, count in counts.items()
        ]
    ordered_fields = list(filter_labels)
    for start in range(0, len(ordered_fields), 2):
        columns = st.columns(2)
        for offset, field in enumerate(ordered_fields[start : start + 2]):
            rows = distribution_rows.get(field, [])
            with columns[offset]:
                if rows:
                    st.plotly_chart(
                        population_distribution_figure(field, rows, selected_n),
                        width="stretch",
                        config={"displayModeBar": False, "responsive": True},
                        key=f"population_distribution_{field}",
                    )
                else:
                    st.info(f"{filter_labels[field]}暂无可展示分布。")
    st.caption(
        "条形右侧显示精确人数和占当前人群比例；"
        "小于5人的汇总单元也会显示实际计数。"
    )
    st.info(
        "筛选结果只描述二期基线覆盖，不提供筛选亚组的复发概率，"
        "也不能证明某个条件会改变治疗效果。"
    )


def comparison_figure(
    items: list[dict[str, Any]],
    anchor_value: float,
    anchor_label: str,
) -> go.Figure:
    rows = list(reversed(items))
    medians = [
        100 * row["result"]["scenario_estimate"]["posterior_median"]
        for row in rows
    ]
    lowers = [
        100 * row["result"]["scenario_estimate"]["lower_95"]
        for row in rows
    ]
    uppers = [
        100 * row["result"]["scenario_estimate"]["upper_95"]
        for row in rows
    ]
    display_names = [
        row["name"] if len(row["name"]) <= 18 else row["name"][:17] + "…"
        for row in rows
    ]
    figure = go.Figure(
        go.Scatter(
            x=medians,
            y=display_names,
            mode="markers",
            marker={"size": 14, "color": "#2456A6"},
            error_x={
                "type": "data",
                "symmetric": False,
                "array": [
                    upper - median for upper, median in zip(uppers, medians)
                ],
                "arrayminus": [
                    median - lower for median, lower in zip(medians, lowers)
                ],
                "thickness": 3,
                "width": 6,
            },
            customdata=[
                [
                    row["name"],
                    row["result"]["direction_stability"]["display_zh"],
                    SUPPORT_LABELS.get(
                        row["result"]["support"]["grade"],
                        SUPPORT_LABELS["unavailable"],
                    )[0],
                ]
                for row in rows
            ],
            hovertemplate=(
                "%{customdata[0]}<br>复发概率 %{x:.1f}%<br>"
                "方向稳定程度 %{customdata[1]}<br>"
                "数据覆盖 %{customdata[2]}<extra></extra>"
            ),
        )
    )
    figure.add_vline(
        x=100 * anchor_value,
        line_dash="dash",
        line_color="#6C7890",
        annotation_text=f"{anchor_label} {100 * anchor_value:.1f}%",
        annotation_position="top right",
    )
    figure.update_layout(
        height=max(225, 58 * len(rows) + 105),
        margin={"l": 72, "r": 30, "t": 48, "b": 55},
        xaxis={
            "title": "D104复发概率（%）",
            "range": [0, 100],
            "ticksuffix": "%",
            "automargin": True,
        },
        yaxis={
            "title": "",
            "type": "category",
            "categoryorder": "array",
            "categoryarray": display_names,
            "automargin": True,
        },
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
        datarevision="|".join(
            f"{name}:{median:.8f}"
            for name, median in zip(display_names, medians)
        ),
        transition={"duration": 300, "easing": "cubic-in-out"},
    )
    return figure

def comparison_page() -> None:
    page_header(
        "情景对比",
        "选择一个比较锚点，直观看到各情景的复发概率和变化。",
    )
    saved = st.session_state.saved_scenarios
    if not saved:
        st.info("尚未保存情景。请先在“情景探索”中运行并保存一个情景。")
        return
    by_id = {item["id"]: item for item in saved}
    pending_selection = st.session_state.pop(
        "comparison_selection_reset_pending", None
    )
    if pending_selection is not None:
        st.session_state.comparison_selected_ids = [
            item_id for item_id in pending_selection if item_id in by_id
        ]
    elif "comparison_selected_ids" not in st.session_state:
        st.session_state.comparison_selected_ids = list(by_id)
    else:
        st.session_state.comparison_selected_ids = [
            item_id
            for item_id in st.session_state.comparison_selected_ids
            if item_id in by_id
        ]
    selected_ids = st.multiselect(
        "选择要比较的情景",
        options=list(by_id),
        format_func=lambda item_id: by_id[item_id]["name"],
        help="选择需要并排查看的已保存情景；不会重新计算概率。",
        key="comparison_selected_ids",
    )
    selected_items = [by_id[item_id] for item_id in selected_ids]
    render_anchor_selector()
    anchor_median, anchor_label = active_anchor_reference()
    if selected_items:
        grades = {
            item["result"]["support"]["grade"] for item in selected_items
        }
        if "C" in grades:
            st.warning("对比中包含年龄外推情景，解读时应更加谨慎。")
        elif "B" in grades:
            st.warning("对比中包含二期样本支持较少的组合。")
        card_rows = []
        for item in selected_items:
            result = item["result"]
            estimate = result["scenario_estimate"]
            support_label = SUPPORT_LABELS.get(
                result["support"]["grade"], SUPPORT_LABELS["unavailable"]
            )[0]
            card_rows.append(
                {
                    "情景": item["name"],
                    "复发概率": f"{100 * estimate['posterior_median']:.1f}%",
                    "估计区间": (
                        f"{100 * estimate['lower_95']:.1f}%–"
                        f"{100 * estimate['upper_95']:.1f}%"
                    ),
                    "较锚点变化": (
                        f"{100 * (estimate['posterior_median'] - anchor_median):+.1f}个百分点"
                    ),
                    "方向稳定程度": result["direction_stability"]["display_zh"],
                    "数据覆盖": support_label,
                }
            )
        st.plotly_chart(
            comparison_figure(selected_items, anchor_median, anchor_label),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
            key="scenario_comparison_chart",
        )
        cards = "".join(
            '<div class="result-summary-item">'
            f'<span>{html.escape(row["情景"])}</span>'
            f'<strong>{html.escape(row["复发概率"])}</strong>'
            f'<small>估计区间：{html.escape(row["估计区间"])}<br>'
            f'较锚点：{html.escape(row["较锚点变化"])}<br>'
            f'方向稳定程度：{html.escape(row["方向稳定程度"])}<br>'
            f'数据覆盖：{html.escape(row["数据覆盖"])}</small></div>'
            for row in card_rows
        )
        st.markdown(
            f'<div class="result-summary-grid">{cards}</div>',
            unsafe_allow_html=True,
        )
        st.caption("概率变化统一使用百分点；数值越低表示D104复发更少。")
    else:
        st.info("请选择至少一个情景。")

    st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
    st.subheader("管理已保存情景")
    if st.session_state.pop("manage_scenario_reset_pending", False):
        st.session_state.pop("manage_scenario_id", None)
    manage_id = st.selectbox(
        "选择情景",
        options=list(by_id),
        format_func=lambda item_id: by_id[item_id]["name"],
        key="manage_scenario_id",
    )
    manage_item = by_id[manage_id]
    rename_col, action_col = st.columns([2, 1])
    new_name = rename_col.text_input(
        "新名称", value=manage_item["name"], max_chars=40, key=f"rename_{manage_id}"
    )
    with action_col:
        st.write("")
        st.write("")
        if st.button("重命名", width="stretch"):
            cleaned = new_name.strip()
            if not cleaned:
                st.error("名称不能为空。")
            elif any(item["name"] == cleaned and item["id"] != manage_id for item in saved):
                st.error("名称已存在。")
            else:
                manage_item["name"] = cleaned
                st.rerun()
    if st.session_state.anchor_id != manage_id:
        if st.button("将所选情景设为锚点", width="stretch"):
            st.session_state.anchor_id = manage_id
            st.session_state.anchor_selector_sync_pending = True
            st.rerun()
    confirm_delete = st.checkbox(
        "我确认删除所选情景；如果它是锚点，将恢复使用二期已观察人群51.6%",
        key=f"delete_confirm_{manage_id}",
    )
    if st.button(
        "删除所选情景",
        disabled=not confirm_delete,
        width="stretch",
    ):
        st.session_state.saved_scenarios = [
            item for item in saved if item["id"] != manage_id
        ]
        st.session_state.comparison_selection_reset_pending = [
            item_id
            for item_id in st.session_state.get("comparison_selected_ids", [])
            if item_id != manage_id
        ]
        st.session_state.manage_scenario_reset_pending = True
        if st.session_state.anchor_id == manage_id:
            st.session_state.anchor_id = PRIMARY_ANCHOR_ID
            st.session_state.anchor_selector_sync_pending = True
        st.rerun()


def usage_page() -> None:
    page_header(
        "使用说明",
        "三步完成一次探索，并了解页面数值能够说明什么。",
    )
    st.markdown(
        """
        <div class="manual-grid">
          <div class="manual-step"><b>1 · 输入参数</b><span>填写基线信息；也可以先加载演示参数。</span></div>
          <div class="manual-step"><b>2 · 查看结果</b><span>运行后首先查看D104复发探索概率及估计区间。</span></div>
          <div class="manual-step"><b>3 · 保存比较</b><span>保存情景或设为锚点，比较后续组合变化了多少个百分点。</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_critical_panel()

    st.subheader("页面中的主要数值")
    st.markdown(
        """
        - **D21治愈状态**：D104复发结果以D21已经治愈为条件。尚未评估时，页面展示“如果D21治愈”的条件预测。
        - **D104复发探索概率**：模型根据输入参数给出的方向性估计，是页面最主要的结果。
        - **估计区间**：表示当前数据下结果可能波动的范围；区间越宽，不确定性越高。
        - **二期已观察人群锚点（51.6%）**：二期D104结局明确的31人中有16人复发，即16/31；不是全部34人的结果。
        - **二期缺失按复发处理锚点（55.9%）**：把3名D104未知者均按复发处理后为19/34，是保守敏感性参考。
        - **如何理解高于锚点**：只表示当前模型情景的复发概率高于所选参考，不代表发现了新的风险因素、达到临床阈值或证明个人会复发。
        - **已保存情景锚点**：可用任一已保存情景比较后续组合；锚点不会改变模型计算。
        - **百分点变化**：例如从50%变为55%，表示增加5个百分点。
        """
    )

    st.subheader("为什么有时不能计算")
    st.markdown(
        """
        - 年龄、BMI、阴道pH或Nugent评分没有填写完整。
        - D21选择“未治愈”，此时当前定义下不计算D104复发。
        - 年龄超出二期范围，但没有勾选年龄扩展探索。
        - AV评分、既往病史和乳杆菌分级三项全部未提供。
        - 输入组合距离现有二期数据过远，无法给出有意义的数值。
        """
    )
    st.info(
        "目前只开放年龄在三期18–55岁范围内的受控外推。"
        "BMI、阴道pH等参数没有足够依据定义外推边界，因此仍限制在二期数据范围内。"
    )

    st.subheader("二期参考数据")
    reference_cols = st.columns(2)
    reference_cols[0].metric("二期已观察人群", "51.6%")
    reference_cols[1].metric("二期缺失按复发处理", "55.9%")
    st.caption(
        "51.6%来自D104可评价者16/31；55.9%来自将D104缺失按复发处理后的19/34。"
        "它们是总体参考值，不是某个输入组合的预测结果。"
    )

    with st.expander("查看数据依据和主要局限"):
        st.markdown(
            """
            - 当前模型来源于二期D24治愈且D104可评价的31人，其中16人观察到复发。
            - 三期流程使用D21治愈条件，和二期D24治愈存在时间点差异。
            - 样本量很小，模型内部区分能力较弱；即使完成三期早期一致性检查，也不等于正式外部验证或准确率证明。
            - 当前估计区间不能覆盖所有模型选择、时间点转运和未来人群差异。
            - 三期进行中的数据从未用于模型训练、变量选择或调参；只允许当前规范盲态截断用于早期一致性检查。
            - 当前没有可用三期SAP，终点与缺失处理仍需统计负责人最终确认。
            """
        )
    st.subheader("三期早期一致性检查")
    p3_status = load_phase3_early_consistency_summary()
    if p3_status["status"] == "pending":
        st.info(p3_status["message"])
    elif p3_status["status"] != "available":
        st.warning(p3_status["message"])
    else:
        st.info(p3_status["message"])
        st.warning(
            "重要限制：当前D104可观察子集会富集较早发生的复发。"
            "复发可以在D44或D74提前被观察，而“未复发”必须等到D104明确记录；"
            "因此当前D104观察率和模型性能指标不能解释为准确率验证。"
        )
        directional = p3_status.get("early_directional") or {}
        d44 = directional.get("d44_observed_label") or {}
        d74 = directional.get("d74_cumulative_label") or {}
        if d44.get("n") is not None and d74.get("n") is not None:
            st.markdown(
                "- **D44和D74仅用于早期方向性观察**：当前可用记录分别为"
                f"{int(d44['n'])}人和{int(d74['n'])}人；"
                "它们不是D104预测准确率验证，也不能替代完整随访。"
            )
        else:
            st.markdown(
                "- **D44和D74仅用于早期方向性观察**，"
                "不是D104预测准确率验证，也不能替代完整随访。"
            )

        d104 = p3_status.get("d104") or {}
        if (
            d104.get("status") == "early_descriptive_only"
            and d104.get("n") is not None
        ):
            st.markdown(
                f"- 当前盲态截断中可用于D104描述性检查：**{int(d104['n'])}人**；"
                "这是结局可观察子集，不代表当前三期全体人群。"
            )
            if (
                d104.get("observed_rate") is not None
                and d104.get("mean_predicted_probability") is not None
            ):
                st.markdown(
                    "- 可观察子集的复发率与模型平均预测为："
                    f"**{100 * float(d104['observed_rate']):.1f}%** 对 "
                    f"**{100 * float(d104['mean_predicted_probability']):.1f}%**；"
                    "两者仅作描述，不能据此判断模型准确或不准确。"
                )
        else:
            st.markdown("- 当前D104成熟度仍不足，暂不能给出描述性检查数值。")

        maturity = p3_status.get("d104_maturity") or {}
        unresolved = sum(
            int(maturity.get(key) or 0)
            for key in (
                "maturity_unresolved_without_d1_and_menstrual_context",
                "maturity_unknown_no_d21_date",
            )
        )
        not_due = int(maturity.get("definitely_not_yet_due") or 0)
        if not_due:
            st.markdown(
                f"- 另有**{not_due}人**明确尚未到D104评价时间，"
                "不进入当前标签或指标。"
            )
        if unresolved:
            st.markdown(
                f"- 另有**{unresolved}人**当前成熟度无法确认，不进入当前标签或指标，"
                "不能记为未复发。"
            )
        st.caption(
            "该检查不拆分实际试验组或对照组，不读取盲底，不参与模型选择，"
            "不构成准确率验证，也不能替代三期完成后的正式验证。"
        )

    st.warning(
        "请把结果用于比较情景和提出重点关注方向，不要用于患者风险分级、"
        "治疗决定、入排决定、减少随访或声称三期试验成功率。"
    )


def changelog_page() -> None:
    page_header(
        "更新日志",
        "正式试用版本发布后，将从首个对外版本开始记录更新。",
    )
    st.info("当前为发布前整理阶段，暂不展示内部开发记录。")


def feedback_page() -> None:
    page_header(
        "问题反馈",
        "反馈将安全保存并由项目团队处理；如填写联系邮箱，可接收自动回执。",
    )
    st.markdown(
        '<div class="critical-panel" role="alert"><strong>隐私提示</strong>'
        "<ul><li>请勿填写姓名、受试者编号、病历号、联系方式以外的个人信息或任何病例级数据。</li>"
        "<li>系统不会自动附带当前情景参数、结果或屏幕截图。</li>"
        "<li>手工截图仅在确认不含患者信息后上传。</li></ul></div>",
        unsafe_allow_html=True,
    )
    with st.form("feedback_form", clear_on_submit=False):
        left, right = st.columns(2)
        category = left.selectbox(
            "问题类型",
            ["功能问题", "结果解释", "界面体验", "数据范围", "改进建议", "其他"],
        )
        impact = right.selectbox(
            "影响程度",
            ["一般建议", "影响使用", "无法继续操作", "可能导致错误解释"],
        )
        source_page = st.selectbox("问题发生页面", NAVIGATION)
        title = st.text_input("问题标题", max_chars=80)
        description = st.text_area(
            "问题描述", height=130, max_chars=4000
        )
        reproduction = st.text_area(
            "复现步骤（可选）", height=90, max_chars=2000
        )
        expected = st.text_area(
            "期望结果（可选）", height=80, max_chars=1200
        )
        contact = st.text_input(
            "联系邮箱（填写后发送自动回执）", max_chars=254
        )
        uploads = st.file_uploader(
            "截图（可选，最多3张，每张不超过5MB，仅PNG/JPG）",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )
        privacy_confirmed = st.checkbox(
            "我确认反馈文字和截图不包含患者、受试者或其他可识别个人信息"
        )
        submitted = st.form_submit_button(
            "提交反馈", type="primary", width="stretch"
        )
    if submitted:
        now = time.monotonic()
        if now - float(st.session_state.feedback_last_submit) < 20:
            st.error("提交过于频繁，请20秒后再试。")
            return
        if not privacy_confirmed:
            st.error("请先确认反馈中不包含可识别个人信息。")
            return
        if len(uploads or []) > 3:
            st.error("一次最多上传3张截图。")
            return
        if any(int(upload.size) > 5 * 1024 * 1024 for upload in (uploads or [])):
            st.error("每张截图不能超过5 MB。")
            return
        if sum(int(upload.size) for upload in (uploads or [])) > 10 * 1024 * 1024:
            st.error("截图总大小不能超过10 MB。")
            return
        attachments = [
            (upload.name, upload.getvalue()) for upload in (uploads or [])
        ]
        try:
            result = submit_feedback(
                category=category,
                impact=impact,
                source_page=source_page,
                title=title,
                description=description,
                reproduction_steps=reproduction,
                expected_behavior=expected,
                contact=contact,
                app_version=(
                    f"frontend-{load_config()['website']['frontend_version']}/"
                    f"backend-{ENGINE_VERSION}"
                ),
                attachments=attachments,
            )
        except FeedbackError as exc:
            st.error(str(exc))
        except Exception:
            st.error("反馈暂时无法安全保存，请稍后重试。")
        else:
            st.session_state.feedback_last_submit = now
            storage_verified = (
                result.get("storage_hardening_verified") is not False
            )
            saved_label = "反馈已安全保存" if storage_verified else "反馈已写入"
            st.success(
                f"{saved_label}，编号：{result["feedback_id"]}。请保留此编号。"
            )
            if not storage_verified:
                st.warning(
                    "不要重复提交；提交后的文件权限复核未完成，"
                    "请将反馈编号告知服务器管理员检查本地存储权限。"
                )
            if result["email_delivery_requested"]:
                st.info(
                    "项目团队通知已受理；如填写联系邮箱，"
                    "系统将在后台发送回执。"
                )
            else:
                st.info(
                    "反馈已保存。邮件通知将在服务可用时自动发送，"
                    "无需重复提交。"
                )


def _select_page(page: str) -> None:
    st.session_state.active_page = page
    st.session_state.navigation_sync_pending = True


def sidebar(config: dict[str, Any]) -> str:
    del config
    if LOGO_PATH.exists():
        with st.sidebar.container(key="sidebar_logo"):
            st.image(str(LOGO_PATH), width=168)
    st.sidebar.markdown(
        '<div class="sidebar-product">Phase III规划探索</div>'
        '<div class="sidebar-subtitle">临床开发决策支持工具</div>',
        unsafe_allow_html=True,
    )

    if st.session_state.pop("navigation_sync_pending", False):
        st.session_state.navigation_shadow = st.session_state.active_page
    with st.sidebar.container(key="navigation_contract"):
        shadow_page = st.radio(
            "导航",
            NAVIGATION,
            key="navigation_shadow",
            label_visibility="collapsed",
        )
    if shadow_page != st.session_state.active_page:
        st.session_state.active_page = shadow_page

    st.sidebar.markdown('<div class="sidebar-section">工作区</div>', unsafe_allow_html=True)
    for page in NAVIGATION[:4]:
        st.sidebar.button(
            page,
            key=f"nav_{NAVIGATION.index(page)}",
            icon=NAVIGATION_ICONS[page],
            type="primary" if st.session_state.active_page == page else "tertiary",
            width="stretch",
            on_click=_select_page,
            args=(page,),
        )
    st.sidebar.markdown('<div class="sidebar-section sidebar-section-spaced">协作</div>', unsafe_allow_html=True)
    for page in NAVIGATION[4:]:
        st.sidebar.button(
            page,
            key=f"nav_{NAVIGATION.index(page)}",
            icon=NAVIGATION_ICONS[page],
            type="primary" if st.session_state.active_page == page else "tertiary",
            width="stretch",
            on_click=_select_page,
            args=(page,),
        )

    st.sidebar.markdown("---")
    st.sidebar.toggle(
        "结果动画",
        key="result_motion_enabled",
        help="只影响结果出现时的动画反馈，不改变任何计算或保存内容。",
    )
    st.sidebar.caption(
        "已保存情景："
        f"{len(st.session_state.saved_scenarios)}/20"
    )
    st.sidebar.markdown(
        '<div class="sidebar-disclaimer">'
        '<strong>探索性规划工具</strong>'
        '<span>仅供研究讨论，不用于临床决策</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    if st.sidebar.button(
        "清空当前会话",
        icon=":material/delete_sweep:",
        width="stretch",
        help="清除当前输入、结果和已保存情景，但不会退出登录。",
    ):
        reset_session_state()
        st.rerun()
    if demo_access_enabled() and st.sidebar.button(
        "退出登录",
        icon=":material/logout:",
        width="stretch",
        help="结束当前登录会话并返回登录页。",
    ):
        _clear_demo_access()
        st.session_state["_demo_access_notice"] = "您已安全退出。"
        st.rerun()
    return str(st.session_state.active_page)


def main() -> None:
    st.set_page_config(
        page_title="XLF055 D104复发情景探索",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "Get help": None,
            "Report a bug": None,
            "About": "探索性规划工具，不用于临床决策。",
        },
    )
    inject_style()
    initialize_state()
    require_demo_access()
    config = load_config()
    page = sidebar(config)
    if page == "情景探索":
        scenario_explorer(config)
    elif page == "二期人群洞察":
        population_insights_page()
    elif page == "情景对比":
        comparison_page()
    elif page == "使用说明":
        usage_page()
    elif page == "更新日志":
        changelog_page()
    else:
        feedback_page()
    st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
    st.markdown(
        '<div class="footer-warning" role="note"><strong>请谨慎使用</strong><br>'
        "本工具用于探索不同参数组合下的复发概率变化，不能用于诊断、治疗、"
        "入排、风险分级、减少方案随访或替代统计复核。</div>",
        unsafe_allow_html=True,
    )
    st.caption("病例参数和已保存情景仅保留在当前会话中，刷新或会话结束后清除。")


if __name__ == "__main__":
    main()
