from __future__ import annotations

import base64
import hmac
import html
import logging
import mimetypes
import os
from pathlib import Path
import statistics
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from clinical_trial_sim_engine.enrichment.final_condition_builder import (
    AGE_SOURCE_MAX,
    AGE_SOURCE_MIN,
    FEATURES,
    age_range_code,
)
from sponsor_demo.local_collaboration import (
    MAX_ATTACHMENTS,
    LocalContentError,
    changelog_media_root,
    email_delivery_configured,
    load_changelog_entries,
    submit_feedback,
)
from sponsor_demo.population_insights_page import render_population_insights_page
from sponsor_demo.service import (
    DISCLAIMER,
    DOSE_LABELS,
    EFFECT_LABELS,
    EFFECT_OPTIONS,
    MISSING_LABELS,
    MISSING_OPTIONS,
    SERVICE,
    build_config,
    export_csv,
    export_html,
    format_pct,
    resolve_comparison_reference,
    result_for_session,
    warning_messages,
)


ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "sponsor_demo/assets/blueballon_logo_temp.png"
ALL_POPULATION_REFERENCE_ID = "__all_population__"
APP_VERSION = os.environ.get("SPONSOR_DEMO_VERSION", "开发试用版 2026.07").strip() or "开发试用版 2026.07"
LOGGER = logging.getLogger(__name__)


PARAMETER_HELP = {
    "dose": "选择拟用于情景计算或二期人群汇总的剂量组。剂量变化会改变对应的二期效应锚点和来源人数。",
    "total_n": "计划在三期试验中随机入组的总人数，当前默认按1:1分配至试验组和安慰剂组。",
    "missing_rule": "规定Day90结局缺失和死亡在分析中的处理方式。不同处理口径用于评估结果对缺失假设的敏感程度。",
    "effect_assumption": "设定三期计算采用的治疗效应。默认保守情景使用二期原始观察风险差的50%；自定义情景可调整为50%至150%。",
    "effect_multiplier": "以二期原始观察风险差为100%。低于100%表示效应折减，高于100%表示乐观外推敏感性，不代表疗效提升已得到证实。",
    "nihss_preset": "限定三期拟入组患者的基线NIHSS范围。快捷范围用于常见情景，自定义可通过双端滑块设置6至20分。",
    "nihss_range": "拖动左右端点设置允许入组的最低和最高基线NIHSS分数。范围越窄，二期来源人数通常越少。",
    "enrichment_conditions": "可再选择最多2项基线特征作为探索性富集条件。条件越多，符合比例和二期来源人数通常越低。",
    "prior_stroke": "选择是否限制患者具有既往卒中史。有既往卒中时可继续限定卒前mRS。",
    "prestroke_mrs": "仅用于有既往卒中的患者；用于限定本次卒中前的功能状态。",
    "feature_levels": "选择该基线特征允许纳入的一个或多个水平；不选择水平时不增加该项限制。",
    "simulation_mode": "快速探索使用1,000次模拟，适合调整参数；稳定复核使用5,000次模拟，随机误差更小但耗时更长。",
    "random_seed": "控制随机模拟的可重复性。参数和随机种子相同时，可复现相同的模拟结果。",
    "motor": "按基线NIHSS双侧上下肢运动项目合计划分的探索性条件，不是原试验或拟议三期已确认的分层因素。",
    "age_mode": "年龄阈值适合快速查看预设人群；自定义区间可同时限定最低和最高年龄。",
    "age_range": "拖动左右端点设置年龄闭区间，左右边界均纳入筛选。区间越窄，二期来源通常越少。",
}


AGE_THRESHOLD_LABELS = {
    "lt65": "<65岁",
    "ge65": "≥65岁",
    "ge70": "≥70岁",
    "ge75": "≥75岁",
    "ge80": "≥80岁",
}


def render_age_condition(key_prefix: str) -> dict:
    mode = st.segmented_control(
        "年龄筛选方式",
        ["预设阈值", "自定义区间"],
        default="预设阈值",
        key=f"{key_prefix}_age_mode",
        help=PARAMETER_HELP["age_mode"],
    )
    if mode == "自定义区间":
        lower, upper = st.slider(
            "年龄范围",
            min_value=AGE_SOURCE_MIN,
            max_value=AGE_SOURCE_MAX,
            value=(70, 75),
            step=1,
            key=f"{key_prefix}_age_range",
            help=PARAMETER_HELP["age_range"],
        )
        st.caption(f"当前条件：{lower}岁≤年龄≤{upper}岁（含边界）")
        return {"feature": "age", "levels": [age_range_code(lower, upper)]}

    level = st.selectbox(
        "年龄阈值",
        list(AGE_THRESHOLD_LABELS),
        index=1,
        format_func=lambda code: AGE_THRESHOLD_LABELS[code],
        key=f"{key_prefix}_age_threshold",
        help="按单一年龄阈值筛选。≥80岁来源极少，仅可在二期人群洞察中查看。",
    )
    return {"feature": "age", "levels": [level]}


st.set_page_config(
    page_title="BZP Phase III规划探索",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
<style>
:root { --ink:#182230; --muted:#667085; --line:#d0d5dd; --accent:#0f766e; --navy:#073b4c; --canvas:#f4f7f8; }
.stApp { background:var(--canvas); color:var(--ink); }
.stApp::before {
    content:""; position:fixed; inset:0 0 0 auto; width:28vw; pointer-events:none;
    background:rgba(7,59,76,.025); border-left:1px solid rgba(15,118,110,.05);
    clip-path:polygon(38% 0,100% 0,100% 100%,0 100%);
}
[data-testid="stHeader"] { background:rgba(244,247,248,.96); }
[data-testid="stSidebar"] {
    background:#fbfdfe;
    border-right:1px solid var(--line);
    min-width:280px;
    max-width:280px;
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top:1.25rem; }
.block-container { position:relative; z-index:1; max-width:1240px; padding-top:2rem; padding-bottom:3rem; }
[data-testid="stSidebar"] [data-testid="stImage"] { margin:0 auto 10px; }
[data-testid="stSidebar"] [data-testid="stImage"] img { max-height:126px; object-fit:contain; }
.sidebar-brand { display:flex; align-items:center; gap:12px; padding:4px 2px 18px; }
.sidebar-monogram {
    width:38px; height:38px; display:flex; align-items:center; justify-content:center;
    border-radius:6px; background:#073b4c; color:#ffffff; font-weight:800; font-size:1.05rem;
    box-shadow:0 3px 10px rgba(7,59,76,.16);
}
.sidebar-brand-copy strong { display:block; color:#12394a; font-size:.93rem; line-height:1.2; }
.sidebar-brand-copy span { display:block; color:#0f766e; font-size:.68rem; font-weight:700; margin-top:3px; }
.sidebar-product { color:#182230; font-size:1rem; font-weight:700; margin:2px 0 3px; }
.sidebar-subtitle { color:#667085; font-size:.77rem; margin-bottom:20px; }
.sidebar-section { color:#98a2b3; font-size:.69rem; font-weight:700; margin:4px 0 7px; }
[data-testid="stSidebar"] .stButton button {
    justify-content:flex-start;
    min-height:42px;
    border-radius:6px;
    padding-left:12px;
    font-weight:600;
    transition:background-color .16s ease, color .16s ease, border-color .16s ease;
}
[data-testid="stSidebar"] .stButton button[kind="tertiary"] { color:#475467; }
[data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover {
    background:#f2f6f7; color:#12394a; border-color:transparent;
}
[data-testid="stSidebar"] .stButton button[kind="primary"] {
    background:#e7f3f2; color:#0b5d57; border-color:#c4dfdc; box-shadow:none;
}
.sidebar-status {
    border-top:1px solid #e4e7ec; margin-top:18px; padding-top:15px;
    color:#667085; font-size:.74rem; line-height:1.6;
}
.status-dot {
    display:inline-block; width:7px; height:7px; border-radius:50%;
    background:#159a78; margin-right:7px; box-shadow:0 0 0 3px rgba(21,154,120,.10);
}
h1 { font-size:2rem !important; letter-spacing:0 !important; }
h2, h3 { letter-spacing:0 !important; }
.eyebrow { color:#0f766e; font-weight:700; font-size:.82rem; margin-bottom:.2rem; }
.boundary { color:var(--muted); font-size:.9rem; border-left:3px solid #98a2b3; padding-left:.75rem; }
.reference-banner {
    display:flex; align-items:center; justify-content:space-between; gap:16px; margin:1rem 0 1.35rem;
    padding:11px 14px; border:1px solid #c9dedc; border-left:4px solid var(--accent);
    border-radius:6px; background:#f8fcfc; color:#344054;
}
.reference-banner strong { color:#0b5d57; }
.reference-banner span { color:#667085; font-size:.8rem; text-align:right; }
.result-strip { border-top:1px solid var(--line); border-bottom:1px solid var(--line); padding:1rem 0; margin:.8rem 0 1.2rem; }
div[data-testid="stMetric"] {
    background:#fff; border:1px solid #e4e7ec; border-radius:6px; padding:13px; min-height:104px;
    transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease, background-color .18s ease;
}
div[data-testid="stMetric"]:hover, div[data-testid="stMetric"]:focus-within {
    transform:translateY(-3px);
    border-color:#75aaa5;
    background:#fcffff;
    box-shadow:0 8px 20px rgba(15,118,110,.11);
}
div[data-testid="stMetricLabel"] { color:#475467; }
.mode-note { color:#475467; font-size:.86rem; }
.manual-step { border-left:4px solid #0f766e; padding:.25rem 0 .25rem 1rem; margin:.8rem 0 1.2rem; }
.small-muted { color:#667085; font-size:.82rem; }
.support-status {
    background:#fff; border:1px solid #e4e7ec; border-left:4px solid #0f766e;
    border-radius:6px; padding:12px 14px; min-height:104px;
    transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.support-status:hover, .support-status:focus {
    transform:translateY(-3px); border-color:#75aaa5;
    box-shadow:0 8px 20px rgba(15,118,110,.11); outline:none;
}
.support-status b { display:block; color:#344054; font-size:.83rem; margin-bottom:7px; }
.support-status strong { display:block; color:#182230; font-size:1.02rem; line-height:1.35; overflow-wrap:anywhere; }
.support-status span { display:block; color:#667085; font-size:.76rem; line-height:1.4; margin-top:6px; }
.warning-card { position:relative; border:1px solid; border-radius:6px; padding:12px 46px 12px 14px; margin:.45rem 0; transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease; }
.warning-card:hover, .warning-card:focus-within { transform:translateY(-2px); box-shadow:0 8px 20px rgba(16,24,40,.10); outline:none; }
.warning-card.ordinary { background:#eff8ff; border-color:#b2ddff; color:#1849a9; }
.warning-card.caution { background:#fffaeb; border-color:#fedf89; color:#93370d; }
.warning-card.strong { background:#fff4ed; border-color:#f7b27a; color:#9c2a10; }
.warning-card.block { background:#fef3f2; border-color:#fda29b; color:#912018; }
.warning-title { display:flex; align-items:center; gap:8px; font-weight:750; margin-bottom:4px; }
.warning-level { font-size:.70rem; border:1px solid currentColor; border-radius:4px; padding:1px 5px; opacity:.82; white-space:nowrap; }
.warning-text { font-size:.88rem; line-height:1.55; color:#344054; }
.warning-help { position:absolute; right:14px; top:12px; width:22px; height:22px; display:flex; align-items:center; justify-content:center; border:1px solid currentColor; border-radius:50%; font-size:.76rem; font-weight:800; cursor:help; }
.warning-tooltip { position:absolute; z-index:20; right:0; top:29px; width:250px; padding:9px 10px; border-radius:5px; background:#101828; color:#fff; font-size:.75rem; line-height:1.45; font-weight:400; opacity:0; visibility:hidden; transform:translateY(-4px); transition:opacity .16s ease, transform .16s ease, visibility .16s; pointer-events:none; }
.warning-help:hover .warning-tooltip, .warning-help:focus .warning-tooltip { opacity:1; visibility:visible; transform:translateY(0); }
[data-testid="stAlert"] { transition:transform .18s ease, box-shadow .18s ease; }
[data-testid="stAlert"]:hover { transform:translateY(-2px); box-shadow:0 7px 18px rgba(16,24,40,.08); }
.change-feed { position:relative; margin:1.35rem 0 .5rem 12px; padding-left:30px; }
.change-feed::before { content:""; position:absolute; left:6px; top:10px; bottom:16px; width:2px; background:#c9dedc; }
.change-post {
    position:relative; margin:0 0 18px; padding:16px 18px; background:#fff;
    border:1px solid #e4e7ec; border-radius:6px;
}
.change-post::before {
    content:""; position:absolute; left:-30px; top:20px; width:12px; height:12px;
    border-radius:50%; background:#0f766e; border:3px solid #f4f7f8;
}
.change-meta { display:flex; align-items:center; flex-wrap:wrap; gap:8px; color:#667085; font-size:.76rem; }
.change-badge { border:1px solid #b9d8d5; border-radius:4px; padding:2px 6px; color:#0b5d57; background:#eff8f7; font-weight:700; }
.change-post h3 { margin:.65rem 0 .35rem; font-size:1.05rem; }
.change-body { color:#475467; font-size:.9rem; line-height:1.65; }
.change-highlights { margin:.65rem 0 0; padding-left:1.2rem; color:#344054; font-size:.87rem; line-height:1.65; }
.change-media-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; margin-top:14px; }
.change-media { margin:0; padding:10px; border:1px solid #e4e7ec; border-radius:6px; background:#f9fbfc; }
.change-media.wide { grid-column:1 / -1; }
.change-media img { display:block; width:100%; height:auto; max-height:360px; object-fit:contain; background:#fff; border-radius:4px; }
.change-media figcaption { margin-top:7px; color:#667085; font-size:.76rem; line-height:1.45; }
.local-storage-note {
    border:1px solid #c9dedc; border-left:4px solid #0f766e; border-radius:6px;
    background:#f8fcfc; padding:12px 14px; margin:1rem 0 1.25rem; color:#344054; font-size:.86rem;
}
.feedback-receipt {
    border:1px solid #86c7b5; border-left:4px solid #159a78; border-radius:6px;
    background:#f2fbf7; padding:13px 15px; margin:1rem 0 1.25rem;
}
.feedback-receipt strong { display:block; color:#075e54; font-size:1rem; margin-bottom:4px; }
.feedback-receipt span { color:#475467; font-size:.82rem; }
.demo-login-shell { max-width:620px; margin:8vh auto 0; }
.demo-login-card { background:rgba(255,255,255,.96); border:1px solid #d0d5dd; border-top:4px solid #0f766e; border-radius:8px; padding:30px 32px 28px; box-shadow:0 18px 44px rgba(15,59,76,.08); }
.demo-login-brand { display:flex; align-items:center; gap:14px; margin-bottom:18px; }
.demo-login-brand img { width:58px; height:58px; object-fit:contain; }
.demo-login-brand strong { display:block; color:#12394a; font-size:1.16rem; }
.demo-login-brand span { display:block; color:#667085; font-size:.82rem; margin-top:4px; }
.demo-login-boundary { border-left:3px solid #0f766e; background:#f4fbfa; color:#475467; padding:10px 12px; margin:15px 0 4px; font-size:.82rem; line-height:1.55; }
.demo-login-footer { margin-top:14px; color:#98a2b3; font-size:.76rem; line-height:1.5; }
.demo-access-state { border-top:1px solid #eaecf0; margin-top:18px; padding-top:14px; color:#667085; font-size:.76rem; }
div.stButton > button, div.stDownloadButton > button { border-radius:5px; }
@media(max-width:760px) {
    .stApp::before { display:none; }
    .reference-banner { align-items:flex-start; flex-direction:column; gap:4px; }
    .reference-banner span { text-align:left; }
    .change-media-grid { grid-template-columns:1fr; }
}
</style>
""",
    unsafe_allow_html=True,
)


def _positive_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def _clear_demo_access() -> None:
    for key in (
        "_demo_access_granted",
        "_demo_access_granted_at",
        "_demo_access_failed_attempts",
        "_demo_access_locked_until",
    ):
        st.session_state.pop(key, None)


def demo_access_enabled() -> bool:
    return bool(os.environ.get("SPONSOR_DEMO_PASSWORD", "").strip())


def require_demo_access() -> None:
    expected_password = os.environ.get("SPONSOR_DEMO_PASSWORD", "").strip()
    if not expected_password:
        return

    expected_user = os.environ.get("SPONSOR_DEMO_USERNAME", "bzp-sponsor")
    session_minutes = _positive_int_env("SPONSOR_DEMO_SESSION_MINUTES", 480, 15, 1440)
    max_failures = _positive_int_env("SPONSOR_DEMO_MAX_FAILURES", 5, 3, 10)
    lock_seconds = _positive_int_env("SPONSOR_DEMO_LOCK_SECONDS", 60, 15, 900)
    now = time.time()
    granted_at = float(st.session_state.get("_demo_access_granted_at") or 0)
    if st.session_state.get("_demo_access_granted") and now - granted_at < session_minutes * 60:
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
            'alt="BlueBalloon BlueLab">'
        )
    st.markdown(
        '<div class="demo-login-shell"><div class="demo-login-card">'
        f'<div class="demo-login-brand">{logo_html}<div><strong>BlueBalloon BlueLab</strong>'
        '<span>Phase III规划探索 · 甲方试用环境</span></div></div>'
        '<div class="eyebrow">受保护访问</div><h1>欢迎登录</h1>'
        '<div class="demo-login-boundary">本工具仅用于探索性、规划阶段的情景讨论。'
        '请使用项目团队提供的账号和访问口令，勿共享患者级数据或登录凭据。</div>',
        unsafe_allow_html=True,
    )
    notice = str(st.session_state.pop("_demo_access_notice", "") or "")
    if notice:
        st.info(notice)
    if remaining:
        st.warning(f"为保护试用账号，请在约{remaining}秒后重试。")
    else:
        with st.form("demo_access_login", clear_on_submit=False):
            username = st.text_input("访问账号", autocomplete="username")
            password = st.text_input("访问口令", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("登录", type="primary", use_container_width=True)
        if submitted:
            valid_user = hmac.compare_digest(username.strip(), expected_user)
            valid_password = hmac.compare_digest(password, expected_password)
            if valid_user and valid_password:
                st.session_state["_demo_access_granted"] = True
                st.session_state["_demo_access_granted_at"] = now
                st.session_state["_demo_access_failed_attempts"] = 0
                st.session_state["_demo_access_locked_until"] = 0
                st.rerun()
            failures = int(st.session_state.get("_demo_access_failed_attempts") or 0) + 1
            st.session_state["_demo_access_failed_attempts"] = failures
            if failures >= max_failures:
                st.session_state["_demo_access_locked_until"] = now + lock_seconds
                st.error("尝试次数过多，请稍后再试。")
            else:
                st.error("账号或访问口令不正确。")
    st.markdown(
        '<div class="demo-login-footer">试用会话最长保留约'
        f'{session_minutes}分钟；结束后需重新登录。若无法访问，请联系项目团队。</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    st.stop()


require_demo_access()


def init_state() -> None:
    defaults = {
        "current_result": None,
        "current_run_meta": None,
        "saved_scenarios": [],
        "duration_history": [],
        "page_navigation_recalc_count": 0,
        "report_download_recalc_count": 0,
        "active_page": "探索分析",
        "result_motion_enabled": True,
        "comparison_previous_snapshot": [],
        "anchor_scenario_id": None,
        "anchor_revision": 0,
        "feedback_form_revision": 0,
        "feedback_receipt": None,
        "feedback_source_page": "探索分析",
        "_last_rendered_page": None,
        "_page_just_entered": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _saved_scenario_id(item: dict, index: int = 0) -> str:
    return str(item.get("scenario_id") or f"{item.get('result', {}).get('config_hash', index)}-{item.get('name', index)}")


def _set_anchor(anchor_id: str | None) -> None:
    normalized = None if not anchor_id or anchor_id == ALL_POPULATION_REFERENCE_ID else str(anchor_id)
    if st.session_state.get("anchor_scenario_id") == normalized:
        return
    st.session_state.anchor_scenario_id = normalized
    st.session_state.anchor_revision = int(st.session_state.get("anchor_revision", 0)) + 1


def _anchor_widget_changed(widget_key: str) -> None:
    selected = st.session_state.get(widget_key)
    _set_anchor(None if selected == ALL_POPULATION_REFERENCE_ID else selected)
    st.session_state[f"_{widget_key}_anchor_revision"] = st.session_state.anchor_revision


def render_anchor_selector(widget_key: str, label: str = "比较锚点") -> str:
    entries = [
        (_saved_scenario_id(item, index), item)
        for index, item in enumerate(st.session_state.saved_scenarios)
    ]
    labels = {item_id: str(item.get("name") or "已保存情景") for item_id, item in entries}
    options = [ALL_POPULATION_REFERENCE_ID, *labels]
    desired = str(st.session_state.get("anchor_scenario_id") or ALL_POPULATION_REFERENCE_ID)
    if desired not in options:
        _set_anchor(None)
        desired = ALL_POPULATION_REFERENCE_ID

    revision_key = f"_{widget_key}_anchor_revision"
    revision = int(st.session_state.get("anchor_revision", 0))
    if (
        widget_key not in st.session_state
        or st.session_state.get(widget_key) not in options
        or st.session_state.get(revision_key) != revision
    ):
        st.session_state[widget_key] = desired
        st.session_state[revision_key] = revision

    selected = st.selectbox(
        label,
        options,
        format_func=lambda item_id: (
            "同设计全人群（默认）"
            if item_id == ALL_POPULATION_REFERENCE_ID
            else f"已保存情景：{labels[item_id]}"
        ),
        key=widget_key,
        on_change=_anchor_widget_changed,
        args=(widget_key,),
        help="选择已保存情景后，结果卡片、变化箭头和动画均与该情景比较；不会改变模拟计算。未设置时固定与同设计全人群比较。",
    )
    if len(options) == 1:
        st.caption("保存至少一个情景后，可在此将其设为后续探索的固定比较锚点。")
    return selected


def _active_anchor_item() -> dict | None:
    anchor_id = st.session_state.get("anchor_scenario_id")
    if not anchor_id:
        return None
    for index, item in enumerate(st.session_state.saved_scenarios):
        if _saved_scenario_id(item, index) == str(anchor_id):
            return item
    _set_anchor(None)
    return None


def _comparison_reference(result: dict) -> tuple[dict, str, str]:
    reference, label, kind, valid_anchor_id = resolve_comparison_reference(
        result,
        st.session_state.saved_scenarios,
        st.session_state.get("anchor_scenario_id"),
    )
    if st.session_state.get("anchor_scenario_id") and valid_anchor_id is None:
        _set_anchor(None)
    return reference, label, kind


def render_reference_banner() -> None:
    anchor = _active_anchor_item()
    if anchor:
        name = html.escape(str(anchor.get("name") or "已保存情景"))
        st.markdown(
            f'<div class="reference-banner"><div><strong>当前锚定：{name}</strong><br>'
            '后续结果统一与该已保存情景比较。</div>'
            '<span>仅改变显示参照，不改变模拟计算</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="reference-banner"><div><strong>当前参照：同设计全人群</strong><br>'
            '未设置锚点时，结果与当前剂量、样本量和效应假设下的全人群比较。</div>'
            '<span>比较不再依赖运行顺序</span></div>',
            unsafe_allow_html=True,
        )


def render_header(title: str, subtitle: str) -> None:
    st.markdown('<div class="eyebrow">BZP2607 · 探索性规划</div>', unsafe_allow_html=True)
    st.title(title)
    st.caption(subtitle)
    st.markdown(f'<div class="boundary">{DISCLAIMER}</div>', unsafe_allow_html=True)


def render_warning(item: dict[str, str]) -> None:
    levels = {
        "ordinary": ("规划提示", "一般规划说明，不阻止运行；用于提醒参数含义或结果边界。"),
        "caution": ("谨慎解释", "数据支持或实施可行性有限；结果需结合来源人数、筛查负担和设计假设解释。"),
        "strong": ("强警示", "来源稀疏、外推程度较高或模型稳定性有限；仅适合敏感性查看。"),
        "block": ("无法运行", "当前参数不满足计算或数据支持要求；需要调整条件后再运行。"),
    }
    level = str(item.get("level", "ordinary"))
    if level not in levels:
        level = "ordinary"
    label, meaning = levels[level]
    title = html.escape(str(item.get("title", "提示")))
    body = html.escape(str(item.get("text", "")))
    st.markdown(
        f'<div class="warning-card {level}" tabindex="0" role="status">'
        f'<div class="warning-title"><span class="warning-level">{label}</span>{title}</div>'
        f'<div class="warning-text">{body}</div>'
        f'<span class="warning-help" tabindex="0" aria-label="{label}说明">?'
        f'<span class="warning-tooltip">{html.escape(meaning)}</span></span></div>',
        unsafe_allow_html=True,
    )


def calculation_unavailable_reasons(preview: dict) -> list[str]:
    reasons = [str(message) for message in preview.get("errors_zh", []) if message]
    eligible = int(preview.get("eligible_n") or 0)
    active = int(preview.get("selected_dose_n") or 0)
    placebo = int(preview.get("placebo_n") or 0)
    if not reasons and eligible == 0:
        reasons.append("当前筛选组合在Phase II FAS中没有来源患者，无法生成经验型虚拟人群。")
    elif preview.get("extrapolation_flag"):
        reasons.append(
            f"当前来源共{eligible}例，其中所选剂量组{active}例、安慰剂组{placebo}例，"
            "低于核心概率结果的数据支持阈值；PoS与Bayesian保证概率将显示为不可估计。"
        )
    return list(dict.fromkeys(reasons))


def render_calculation_availability(preview: dict) -> list[str]:
    reasons = calculation_unavailable_reasons(preview)
    if not reasons:
        return []
    st.markdown("#### 当前组合的计算可用性")
    for reason in reasons:
        st.error(f"不可形成核心概率结果：{reason}")
    if preview.get("extrapolation_flag") and int(preview.get("eligible_n") or 0) > 0:
        st.caption("仍可运行以保留模型外推敏感性记录，但该结果不进入核心PoS、保证概率或推荐排序。")
    else:
        st.caption("请放宽筛选范围、移除冲突条件，或修正参数后再运行。")
    return reasons


def _format_point_change(value: float) -> str:
    if 0 < abs(value) < 0.05:
        return "+<0.1" if value > 0 else "−<0.1"
    return f"{value:+.1f}"


def _metric_delta(
    current: dict,
    previous: dict | None,
    key: str,
    *,
    kind: str = "percentage_point",
    favorable: str = "up",
) -> tuple[str | None, str]:
    if not previous or previous.get("status") == "blocked":
        return None, "off"
    current_value = current.get(key)
    previous_value = previous.get(key)
    if current_value is None or previous_value is None:
        return None, "off"

    difference = float(current_value) - float(previous_value)
    if kind == "percentage_point":
        delta = difference * 100
        text = _format_point_change(delta)
    else:
        delta = difference
        relative = None if float(previous_value) == 0 else difference / abs(float(previous_value)) * 100
        text = f"{delta:+,.0f}人"
        if relative is not None:
            text += f"（{relative:+.1f}%）"

    if favorable == "neutral" or abs(difference) < 1e-12:
        return text, "off"
    return text, "normal" if favorable == "up" else "inverse"


def result_chart(result: dict) -> go.Figure:
    labels = ["当前情景PoS", "全人群参照PoS", "Bayesian保证概率"]
    values = [
        result.get("enriched_population_pos"),
        result.get("all_population_pos"),
        result.get("bayesian_assurance"),
    ]
    plot_values = [0 if value is None else float(value) * 100 for value in values]
    colors = ["#0f766e", "#3b82f6", "#d97706"]
    fig = go.Figure(
        go.Bar(
            x=plot_values,
            y=labels,
            orientation="h",
            marker_color=colors,
            text=["不可估计" if value is None else f"{value:.1%}" for value in values],
            textposition="outside",
            hovertemplate="%{y}：%{x:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        height=260,
        margin=dict(l=20, r=55, t=20, b=35),
        xaxis=dict(title="概率（%）", range=[0, max(100, max(plot_values, default=0) + 10)], gridcolor="#e4e7ec"),
        yaxis=dict(autorange="reversed", title=""),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        showlegend=False,
        transition=dict(
            duration=650 if st.session_state.get("result_motion_enabled", True) else 0,
            easing="cubic-in-out",
        ),
        font=dict(family="Microsoft YaHei, Arial", color="#182230"),
    )
    return fig


def _result_animation_html(
    current: dict, reference: dict | None, reference_label: str, reference_kind: str
) -> str:
    reference_valid = bool(reference and reference.get("status") != "blocked")
    percent_rows = [
        ("当前情景PoS", "enriched_population_pos", "#0f766e", "up"),
        ("Bayesian保证概率", "bayesian_assurance", "#d97706", "up"),
        ("全人群参照PoS", "all_population_pos", "#3b82f6", "up"),
    ]
    count_rows = [
        ("Phase II符合比例", "eligible_proportion", "pct", "up"),
        ("预计筛查人数", "estimated_screened_n", "int", "down"),
        ("当前来源人数", "eligible_n", "int", "up"),
    ]

    def number(value, scale=1.0):
        if value is None:
            return None
        return float(value) * scale

    def delta_badge(end, start, kind: str, favorable: str) -> str:
        if not reference_valid or end is None or start is None:
            return ""
        difference = float(end) - float(start)
        arrow = "↑" if difference > 0 else ("↓" if difference < 0 else "→")
        if kind == "pct":
            label = _format_point_change(difference)
        else:
            relative = None if float(start) == 0 else difference / abs(float(start)) * 100
            label = f"{difference:+,.0f}人"
            if relative is not None:
                label += f"（{relative:+.1f}%）"
        if abs(difference) < 1e-12:
            tone = "neutral"
        else:
            improved = (difference > 0 and favorable == "up") or (difference < 0 and favorable == "down")
            tone = "favorable" if improved else "unfavorable"
        return f"<small class=\"delta-badge {tone}\">{arrow} {label}</small>"

    bars = []
    for label, key, color, favorable in percent_rows:
        end = number(current.get(key), 100)
        start = number(reference.get(key), 100) if reference_valid else end
        if end is None:
            bars.append(
                f'<div class="bar-row"><div class="bar-meta"><span>{html.escape(label)}</span>'
                '<strong>不可估计</strong></div><div class="track unavailable"></div></div>'
            )
            continue
        if start is None:
            start = end
        bars.append(
            f'<div class="bar-row{" first-run" if not reference_valid else ""}">'
            f'<div class="bar-meta"><span>{html.escape(label)}</span><div class="value-stack">'
            f'<strong class="counter" data-start="{start:.6f}" data-end="{end:.6f}" data-kind="pct">{start:.1f}%</strong>'
            f'{delta_badge(end, start, "pct", favorable)}</div></div>'
            f'<div class="track"><div class="fill" data-start="{start:.6f}" data-end="{end:.6f}" '
            f'style="width:{max(0, min(100, start)):.3f}%;background:{color}"></div></div></div>'
        )

    cards = []
    for label, key, kind, favorable in count_rows:
        scale = 100 if kind == "pct" else 1
        end = number(current.get(key), scale)
        start = number(reference.get(key), scale) if reference_valid else end
        if end is None:
            value_html = '<strong>不可估计</strong>'
        else:
            if start is None:
                start = end
            initial = f"{start:.1f}%" if kind == "pct" else f"{int(round(start)):,}"
            value_html = (
                f'<strong class="counter" data-start="{start:.6f}" data-end="{end:.6f}" '
                f'data-kind="{kind}">{initial}</strong>'
            )
        badge = delta_badge(end, start, kind, favorable) if end is not None else ""
        cards.append(f'<div class="mini"><span>{html.escape(label)}</span>{value_html}{badge}</div>')

    current_pos = current.get("enriched_population_pos")
    reference_pos = reference.get("enriched_population_pos") if reference_valid else None
    all_pos = current.get("all_population_pos")

    def delta_text(label: str, left, right) -> str:
        if left is None or right is None:
            return f'<span>{html.escape(label)}：不可比较</span>'
        delta = (float(left) - float(right)) * 100
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        magnitude = _format_point_change(abs(delta)).lstrip("+")
        return f'<span>{html.escape(label)}：{arrow} {magnitude}</span>'

    comparison = [delta_text("较同设计全人群", current_pos, all_pos)]
    if reference_kind == "anchor" and reference_valid:
        comparison.insert(0, delta_text(f"较锚定情景“{reference_label}”", current_pos, reference_pos))

    duration = 650
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"Microsoft YaHei",Arial,sans-serif; color:#182230; background:#fff; }}
.summary {{ padding:4px 2px 0; }}
.bar-row {{ margin:0 0 17px; }}
.bar-row.first-run {{ animation:fadeIn .45s ease both; }}
.bar-meta {{ display:flex; justify-content:space-between; align-items:baseline; gap:16px; margin-bottom:7px; }}
.bar-meta span {{ color:#475467; font-size:14px; font-weight:600; }}
.bar-meta strong {{ color:#182230; font-size:22px; font-variant-numeric:tabular-nums; }}
.value-stack {{ display:flex; flex-direction:column; align-items:flex-end; gap:3px; }}
.delta-badge {{ display:block; font-size:12px; font-weight:700; line-height:1.25; font-variant-numeric:tabular-nums; }}
.delta-badge.favorable {{ color:#087a55; }}
.delta-badge.unfavorable {{ color:#c2413b; }}
.delta-badge.neutral {{ color:#667085; }}
.track {{ width:100%; height:12px; border-radius:3px; background:#eef2f4; overflow:visible; }}
.track.unavailable {{ opacity:.55; }}
.fill {{ height:12px; border-radius:3px; transition:width {duration}ms cubic-bezier(.22,1,.36,1); }}
.comparison {{ display:flex; flex-wrap:wrap; gap:8px 18px; margin:4px 0 18px; color:#475467; font-size:13px; }}
.mini-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }}
.mini {{ min-height:76px; padding:12px 13px; border:1px solid #e4e7ec; border-radius:6px; background:#fbfcfd; }}
.mini span {{ display:block; color:#667085; font-size:12px; margin-bottom:8px; }}
.mini strong {{ display:block; color:#182230; font-size:20px; font-variant-numeric:tabular-nums; }}
@keyframes fadeIn {{ from {{ opacity:0; transform:translateY(3px); }} to {{ opacity:1; transform:none; }} }}
@media (max-width:560px) {{ .mini-grid {{ grid-template-columns:1fr; }} .mini {{ min-height:64px; }} }}
@media (prefers-reduced-motion:reduce) {{ .fill,.bar-row.first-run {{ transition:none!important; animation:none!important; }} }}
</style>
</head>
<body>
<div class="summary">
  {''.join(bars)}
  <div class="comparison">{''.join(comparison)}</div>
  <div class="mini-grid">{''.join(cards)}</div>
</div>
<script>
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const duration = reduce ? 0 : {duration};
const counters = [...document.querySelectorAll('.counter')];
const fills = [...document.querySelectorAll('.fill')];
function format(v, kind) {{
  if (kind === 'pct') return v.toFixed(1) + '%';
  return Math.round(v).toLocaleString('zh-CN');
}}
function ease(t) {{ return 1 - Math.pow(1 - t, 3); }}
requestAnimationFrame(() => {{
  fills.forEach(el => {{ el.style.width = Math.max(0, Math.min(100, Number(el.dataset.end))) + '%'; }});
  if (!duration) {{
    counters.forEach(el => el.textContent = format(Number(el.dataset.end), el.dataset.kind));
    return;
  }}
  const started = performance.now();
  function tick(now) {{
    const t = Math.min(1, (now - started) / duration);
    const e = ease(t);
    counters.forEach(el => {{
      const start = Number(el.dataset.start), end = Number(el.dataset.end);
      el.textContent = format(start + (end - start) * e, el.dataset.kind);
    }});
    if (t < 1) requestAnimationFrame(tick);
  }}
  requestAnimationFrame(tick);
}});
</script>
</body>
</html>
"""


@st.dialog("结果变化速览", width="large")
def show_result_change_dialog(
    current: dict,
    reference: dict,
    reference_label: str,
    reference_kind: str,
    meta: dict | None,
) -> None:
    if meta and meta.get("cache_hit"):
        st.caption("本次结果来自缓存，数值与相同参数的既有计算一致。")
    components.html(
        _result_animation_html(current, reference, reference_label, reference_kind),
        height=410,
        scrolling=False,
    )
    st.caption(f"变化量相对{reference_label}；比例差异单位为百分点。锚定仅改变展示参照，不改变计算结果。")


def render_results(result: dict, meta: dict | None) -> None:
    if result.get("status") == "blocked":
        for message in result.get("errors_zh", ["当前情景无法计算。"]):
            st.error(message)
        return

    st.subheader("核心结果")
    if meta and meta.get("cache_hit"):
        st.success("已从缓存读取结果")
    if result.get("enriched_population_pos") is None and result.get("bayesian_assurance") is None:
        st.error("当前参数组合未形成可展示的核心PoS或Bayesian保证概率。")
        reasons = [str(message) for message in result.get("warnings_zh", []) if message]
        if result.get("evidence_support_status") == "模型外推敏感性":
            reasons.insert(0, "Phase II来源总数或组别人数低于核心结果支持阈值；按预设规则仅保留模型外推敏感性，不进入推荐排序。")
        for reason in list(dict.fromkeys(reasons))[:4]:
            st.markdown(f"- {reason}")
        st.caption("请放宽筛选条件后重新运行；工具不会用合并效应或伪精确数值替代不可估计结果。")
    comparison_reference, comparison_label, comparison_kind = _comparison_reference(result)
    st.caption(f"箭头与变化量均相对{comparison_label}；比例差异单位：百分点。")
    pos_delta = _metric_delta(result, comparison_reference, "enriched_population_pos")
    assurance_delta = _metric_delta(result, comparison_reference, "bayesian_assurance")
    reference_delta = _metric_delta(result, comparison_reference, "all_population_pos")
    relative_pos_delta = _metric_delta(result, comparison_reference, "delta_pos")
    eligible_delta = _metric_delta(result, comparison_reference, "eligible_proportion")
    screening_delta = _metric_delta(
        result, comparison_reference, "estimated_screened_n", kind="count", favorable="down"
    )
    source_delta = _metric_delta(result, comparison_reference, "eligible_n", kind="count")

    cols = st.columns(4)
    cols[0].metric(
        "当前情景PoS",
        format_pct(result.get("enriched_population_pos")),
        delta=pos_delta[0],
        delta_color=pos_delta[1],
        help=f"在当前设计假设下，Monte Carlo模拟达到统计成功标准的比例；变化量相对{comparison_label}。",
    )
    cols[1].metric(
        "Bayesian保证概率",
        format_pct(result.get("bayesian_assurance")),
        delta=assurance_delta[0],
        delta_color=assurance_delta[1],
        help=f"对治疗效应不确定性进行积分后达到成功标准的概率；变化量相对{comparison_label}。",
    )
    cols[2].metric(
        "全人群参照PoS",
        format_pct(result.get("all_population_pos")),
        delta=reference_delta[0],
        delta_color=reference_delta[1],
        help=f"保持剂量和样本量不变、不附加富集条件时的参照成功比例；变化量相对{comparison_label}中的全人群结果。",
    )
    cols[3].metric(
        "相对全人群PoS差异",
        format_pct(result.get("delta_pos"), signed=True),
        delta=relative_pos_delta[0],
        delta_color=relative_pos_delta[1],
        help=f"当前情景PoS减去同设计全人群参照PoS；下方变化量比较{comparison_label}中的该差值。",
    )
    cols = st.columns([1, 1, 1, 1.25])
    cols[0].metric(
        "Phase II符合比例",
        format_pct(result.get("eligible_proportion")),
        delta=eligible_delta[0],
        delta_color=eligible_delta[1],
        help=f"Phase II来源数据中满足当前条件的患者比例；变化量相对{comparison_label}。",
    )
    cols[1].metric(
        "预计筛查人数",
        result.get("estimated_screened_n") or "不可估计",
        delta=screening_delta[0],
        delta_color=screening_delta[1],
        help="达到目标随机样本量可能需要筛查的人数；筛查负担下降显示为有利变化。",
    )
    cols[2].metric(
        "当前来源人数",
        result.get("eligible_n") or 0,
        delta=source_delta[0],
        delta_color=source_delta[1],
        help=f"Phase II来源数据中满足当前全部条件的人数；变化量相对{comparison_label}。",
    )
    support_status = str(result.get("evidence_support_status") or "不可估计")
    support_detail = {
        "数据支持较充分": "来源样本及两组人数达到当前工具的预设支持标准。",
        "数据有限": "来源或部分组别样本偏少，结果仅作方向性探索。",
        "模型外推敏感性": "来源明显稀疏，不形成数据支持的富集结论。",
        "不可估计": "当前条件没有足够来源，工具不会生成估计值。",
    }.get(support_status, "请结合来源人数、组别人数及页面预警解释。")
    cols[3].markdown(
        '<div class="support-status" tabindex="0" title="根据当前来源总人数、剂量组人数、安慰剂组人数及稀疏情况综合分级。"><b>数据支持状态</b>'
        f"<strong>{html.escape(support_status)}</strong>"
        f"<span>{html.escape(support_detail)}</span></div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.45, 1])
    with left:
        st.plotly_chart(
            result_chart(result),
            use_container_width=True,
            config={"displayModeBar": False},
            key="core_result_chart",
        )
    with right:
        st.markdown("#### 当前解读")
        st.write(
            "当前结果用于比较设计情景的相对变化。请将PoS、保证概率与筛查负担一起判断，"
            "不要将单一数值视为Ⅲ期成功承诺。"
        )
        for item in result.get("warnings_ui", [])[:3]:
            render_warning(item)

    st.markdown("---")
    name_col, save_col = st.columns([2, 1], vertical_alignment="bottom")
    name = name_col.text_input(
        "情景名称",
        value=f"情景{len(st.session_state.saved_scenarios) + 1}",
        max_chars=24,
        key=f"scenario_name_{result.get('config_hash')}",
    )
    if save_col.button("保存情景", type="primary", use_container_width=True):
        saved = st.session_state.saved_scenarios
        if any(item["result"]["config_hash"] == result["config_hash"] for item in saved):
            st.info("相同参数情景已保存。")
        elif len(saved) >= 8:
            st.warning("最多保存8个情景，请先删除一个已有情景。")
        else:
            saved.append(
                {
                    "scenario_id": f"{result['config_hash']}-{time.time_ns()}",
                    "name": name.strip() or f"情景{len(saved) + 1}",
                    "result": result_for_session(result),
                }
            )
            st.success("情景已保存，可在探索分析中设为锚点，或进入“情景比较与管理”查看。")

    st.markdown("#### 下载当前情景")
    html_data = export_html(result, comparison_reference, comparison_label)
    csv_data = export_csv(result, comparison_reference, comparison_label)
    dl1, dl2 = st.columns(2)
    dl1.download_button(
        "下载中文HTML报告",
        data=html_data,
        file_name=f"BZP探索报告_{result['config_hash']}.html",
        mime="text/html",
        on_click="ignore",
        use_container_width=True,
    )
    dl2.download_button(
        "下载CSV结果",
        data=csv_data,
        file_name=f"BZP探索结果_{result['config_hash']}.csv",
        mime="text/csv",
        on_click="ignore",
        use_container_width=True,
    )
    st.caption("下载内容复用本次计算结果，不会重新运行模拟；文件仅含情景级汇总。")


def exploration_page() -> None:
    render_header("探索分析", "调整关键设计参数，运行一个情景，并同时查看收益与筛查负担。")
    st.markdown("#### 比较基准")
    render_anchor_selector("exploration_anchor_selector")
    render_reference_banner()
    st.subheader("设计参数")
    left, right = st.columns([1, 1], gap="large")
    with left:
        dose = st.selectbox("剂量", list(DOSE_LABELS), index=1, help=PARAMETER_HELP["dose"])
        total_n = st.number_input(
            "目标随机样本量N",
            min_value=200,
            max_value=3000,
            value=1122,
            step=2,
            help=PARAMETER_HELP["total_n"],
        )
        missing_rule = st.selectbox(
            "缺失处理",
            list(MISSING_OPTIONS),
            format_func=lambda value: MISSING_LABELS[value],
            help=PARAMETER_HELP["missing_rule"],
        )
        effect = st.selectbox(
            "治疗效应假设",
            list(EFFECT_OPTIONS),
            format_func=lambda value: EFFECT_LABELS[value],
            help=PARAMETER_HELP["effect_assumption"],
        )
        if effect == "custom_multiplier":
            multiplier_pct = st.slider(
                "相对Phase II原始效应系数",
                min_value=50,
                max_value=150,
                value=100,
                step=5,
                format="%d%%",
                help=PARAMETER_HELP["effect_multiplier"],
            )
            st.caption("50%=默认保守情景；100%=原始观察效应；110%/120%=高于原始效应的乐观敏感性。")
        else:
            multiplier_pct = 100
            st.caption("默认情景固定采用Phase II原始观察风险差的50%。")
    with right:
        preset = st.radio(
            "NIHSS范围快捷选择",
            ["6–20", "6–15", "6–10", "11–20", "自定义"],
            horizontal=True,
            help=PARAMETER_HELP["nihss_preset"],
        )
        preset_ranges = {"6–20": (6, 20), "6–15": (6, 15), "6–10": (6, 10), "11–20": (11, 20)}
        if preset == "自定义":
            nihss_min, nihss_max = st.slider(
                "自定义NIHSS范围",
                min_value=6,
                max_value=20,
                value=(6, 20),
                step=1,
                help=PARAMETER_HELP["nihss_range"],
                key="nihss_custom_range",
            )
        else:
            nihss_min, nihss_max = preset_ranges[preset]
            st.caption(f"当前范围：NIHSS {nihss_min}–{nihss_max}分")

        feature_labels = {
            "prior_function": "既往卒中及卒前功能",
            "age": FEATURES["age"].label_zh,
            "sex": FEATURES["sex"].label_zh,
            "onset": FEATURES["onset"].label_zh,
            "screening_mrs": FEATURES["screening_mrs"].label_zh,
        }
        selected_features = st.multiselect(
            "其他富集条件（最多2项）",
            list(feature_labels),
            format_func=lambda code: feature_labels[code],
            max_selections=2,
            help=PARAMETER_HELP["enrichment_conditions"],
        )
        conditions = []
        for feature_code in selected_features:
            if feature_code == "prior_function":
                stroke_status = st.radio(
                    "既往卒中状态",
                    ["no", "yes"],
                    format_func=lambda code: {"no": "无既往卒中", "yes": "有既往卒中"}[code],
                    horizontal=True,
                    key="prior_stroke_status",
                    help=PARAMETER_HELP["prior_stroke"],
                )
                if stroke_status == "yes":
                    prestroke_level = st.selectbox(
                        "卒前mRS（仅有既往卒中者）",
                        ["unrestricted", "recorded_0", "recorded_1"],
                        format_func=lambda code: {
                            "unrestricted": "不进一步限制",
                            "recorded_0": "mRS=0",
                            "recorded_1": "mRS=1",
                        }[code],
                        key="prestroke_mrs_level",
                        help=PARAMETER_HELP["prestroke_mrs"],
                    )
                    if prestroke_level == "unrestricted":
                        conditions.append({"feature": "previous_stroke", "levels": ["yes"]})
                    else:
                        conditions.append({"feature": "prestroke_mrs", "levels": [prestroke_level]})
                else:
                    conditions.append({"feature": "previous_stroke", "levels": ["no"]})
                continue
            if feature_code == "age":
                conditions.append(render_age_condition("exploration"))
                continue
            levels = [level for level in FEATURES[feature_code].levels if level.code != "unrestricted"]
            selected_levels = st.multiselect(
                f"{FEATURES[feature_code].label_zh}范围",
                [level.code for level in levels],
                format_func=lambda code, choices=levels: next(level.label_zh for level in choices if level.code == code),
                key=f"levels_{feature_code}",
                help=PARAMETER_HELP["feature_levels"],
            )
            if selected_levels:
                conditions.append({"feature": feature_code, "levels": selected_levels})

    with st.expander("高级设置"):
        mode = st.radio(
            "模拟模式",
            ["快速探索", "稳定复核"],
            horizontal=True,
            help=PARAMETER_HELP["simulation_mode"],
        )
        st.markdown(
            '<div class="mode-note">快速探索使用1,000次模拟；稳定复核使用5,000次模拟。两种模式使用同一效应锚点和成功规则。</div>',
            unsafe_allow_html=True,
        )
        random_seed = st.number_input(
            "随机种子",
            min_value=1,
            max_value=2_147_483_647,
            value=20260717,
            help=PARAMETER_HELP["random_seed"],
        )
        motor_disabled = len(conditions) >= 2
        use_motor = st.checkbox(
            "启用基线肢体运动探索条件",
            value=False,
            disabled=motor_disabled,
            help=PARAMETER_HELP["motor"],
        )
        if motor_disabled:
            st.caption("当前已选择2项富集条件；如需启用肢体运动条件，请先减少一项。")
        elif use_motor:
            motor_level = st.radio(
                "基线肢体运动缺损",
                ["low", "le4", "high", "gt4"],
                format_func=lambda code: {
                    "low": "较轻（NIHSS双侧上下肢四项合计<4分）",
                    "le4": "敏感性阈值：四项合计≤4分",
                    "high": "较重（NIHSS双侧上下肢四项合计≥4分）",
                    "gt4": "敏感性阈值：四项合计>4分",
                }[code],
                horizontal=True,
            )
            conditions.append({"feature": "motor", "levels": [motor_level]})
            st.caption("4分阈值为项目探索性预设；该指标与总NIHSS及筛选期mRS可能存在信息重叠。")
    n_simulations = 1000 if mode == "快速探索" else 5000

    config = build_config(
        dose_label=dose,
        total_n=int(total_n),
        missing_rule=missing_rule,
        effect_assumption=effect,
        effect_multiplier=float(multiplier_pct) / 100,
        nihss_min=int(nihss_min),
        nihss_max=int(nihss_max),
        conditions=conditions,
        n_simulations=n_simulations,
        random_seed=int(random_seed),
    )
    preview = SERVICE.preview(config)
    live_warnings = warning_messages(config, preview)
    if live_warnings:
        st.markdown("#### 参数提示")
        for item in live_warnings[:3]:
            render_warning(item)
    render_calculation_availability(preview)

    run_disabled = preview.get("status") == "blocked" or int(preview.get("eligible_n") or 0) == 0
    if st.button("运行模拟", type="primary", disabled=run_disabled, use_container_width=True):
        progress = st.progress(0, text="准备运行")
        status = st.empty()
        history = st.session_state.duration_history
        expected = statistics.median(history) if history else None

        def progress_callback(percent: int, label: str, elapsed: float) -> None:
            progress.progress(percent, text=label)
            if expected is None:
                eta = "首次运行，预计20–40秒"
            else:
                remaining = max(0.0, expected - elapsed)
                eta = "计算仍在进行" if elapsed > expected else f"预计剩余约{remaining:.0f}秒"
            status.caption(f"已用时间 {elapsed:.1f}秒 · {eta}")

        result, meta = SERVICE.run(config, progress_callback)
        current_result = result_for_session(result)
        st.session_state.current_result = current_result
        st.session_state.current_run_meta = meta
        if not meta["cache_hit"]:
            history.append(meta["elapsed_seconds"])
            st.session_state.duration_history = history[-8:]
        if meta["cache_hit"]:
            progress.progress(100, text="已从缓存读取结果")
        status.caption(f"本次用时 {meta['elapsed_seconds']:.1f}秒")
        if st.session_state.result_motion_enabled:
            reference, reference_label, reference_kind = _comparison_reference(current_result)
            show_result_change_dialog(
                current_result, reference, reference_label, reference_kind, meta
            )
        else:
            st.toast("模拟完成，结果已直接更新。")

    current = st.session_state.current_result
    if current:
        st.markdown('<div class="result-strip"></div>', unsafe_allow_html=True)
        render_results(current, st.session_state.current_run_meta)
    else:
        st.info("设置参数后点击“运行模拟”。调整控件不会自动计算。")


def _comparison_animation_html(current_items: list[dict], previous_items: list[dict], motion_enabled: bool) -> str:
    current_map = {str(item["id"]): item for item in current_items}
    previous_map = {str(item["id"]): item for item in previous_items}
    ordered_ids = [str(item["id"]) for item in previous_items]
    ordered_ids.extend(item_id for item_id in current_map if item_id not in previous_map)
    current_order = {str(item["id"]): index for index, item in enumerate(current_items)}
    previous_order = {str(item["id"]): index for index, item in enumerate(previous_items)}
    current_count = max(len(current_items), 1)
    previous_count = max(len(previous_items), 1)
    groups = []
    for item_id in ordered_ids:
        current = current_map.get(item_id)
        previous = previous_map.get(item_id)
        label = html.escape(str((current or previous or {}).get("name", "情景")))
        deleted = current is None
        previous_index = previous_order.get(item_id, -1)
        current_index = current_order.get(item_id, -1)
        bars = []
        for key, color in (("pos", "#0f766e"), ("assurance", "#d97706")):
            start = float(previous.get(key, 0) if previous else 0)
            end = float(current.get(key, 0) if current else 0)
            initial = start if motion_enabled else end
            bars.append(
                f"<div class=bar-wrap><span class=value data-start={initial:.6f} data-end={end:.6f} style=bottom:{initial:.3f}%>{initial:.1f}%</span>"
                f"<i class=bar data-end={end:.6f} style=height:{initial:.3f}%;background:{color}></i></div>"
            )
        deleted_flag = "true" if deleted else "false"
        groups.append(
            f"<div class=group data-deleted={deleted_flag} data-prev-index={previous_index} data-current-index={current_index} data-prev-count={previous_count} data-current-count={current_count}><div class=bars>{''.join(bars)}</div>"
            f"<div class=label>{label}</div></div>"
        )
    duration = 650 if motion_enabled else 0
    axis_html = "".join(f"<span style=bottom:{tick}%>{tick}</span>" for tick in (0, 20, 40, 60, 80, 100))
    grid_html = "".join(f"<i class=grid-line style=bottom:{tick}%></i>" for tick in (20, 40, 60, 80, 100))
    group_html = "".join(groups)
    return f"""<!doctype html><html lang=zh-CN><head><meta charset=utf-8><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Microsoft YaHei,Arial,sans-serif;color:#182230;background:#fff}}
.legend{{display:flex;gap:18px;height:30px;align-items:center;font-size:12px;color:#475467}}
.legend i{{display:inline-block;width:10px;height:10px;margin-right:6px;border-radius:2px}}
.chart-shell{{display:grid;grid-template-columns:42px minmax(0,1fr);height:310px}}
.axis{{position:relative;height:242px;margin-top:18px;color:#667085;font-size:11px}}.axis span{{position:absolute;right:8px;transform:translateY(50%)}}
.plot{{position:relative;height:310px;overflow:hidden}}
.plot-area{{position:absolute;inset:18px 0 auto 0;height:242px;border-left:1px solid #d0d5dd;border-bottom:1px solid #d0d5dd}}
.grid-line{{position:absolute;left:0;right:0;border-top:1px solid #eaecf0}}
.groups{{position:absolute;inset:0 8px auto 8px;height:300px}}
.group{{position:absolute;top:0;height:300px;display:grid;grid-template-rows:260px 40px;transition:left {duration}ms cubic-bezier(.22,1,.36,1),width {duration}ms cubic-bezier(.22,1,.36,1),opacity {duration}ms ease}}
.bars{{display:flex;align-items:flex-end;justify-content:center;gap:8%;min-height:0;padding:18px 12% 0}}
.bar-wrap{{position:relative;flex:1 1 0;min-width:10px;height:100%;display:flex;align-items:flex-end}}
.bar{{display:block;width:100%;border-radius:3px 3px 0 0;transition:height {duration}ms cubic-bezier(.22,1,.36,1),opacity {duration}ms ease}}
.value{{position:absolute;left:50%;transform:translate(-50%,-5px);font-size:10px;font-weight:700;white-space:nowrap;transition:bottom {duration}ms cubic-bezier(.22,1,.36,1)}}
.label{{padding:7px 3px;text-align:center;font-size:11px;color:#475467;overflow:hidden;text-overflow:ellipsis}}
@media(prefers-reduced-motion:reduce){{.bar,.value,.group{{transition:none!important}}}}
</style></head><body><div class=legend><span><i style=background:#0f766e></i>当前情景PoS</span><span><i style=background:#d97706></i>Bayesian保证概率</span></div>
<div class=chart-shell><div class=axis>{axis_html}</div><div class=plot><div class=plot-area>{grid_html}</div><div class=groups>{group_html}</div></div></div>
<script>const duration={duration};function ease(t){{return 1-Math.pow(1-t,3)}}
const container=document.querySelector(".groups"),groupEls=[...document.querySelectorAll(".group")];
function geometry(index,count){{const width=container.clientWidth,slot=width/Math.max(count,1),cap=count===1?360:(count===2?280:210),groupWidth=Math.max(68,Math.min(cap,slot*.78));return{{left:(index+.5)*slot-groupWidth/2,width:groupWidth}}}}
function setGeometry(el,g,opacity){{el.style.left=g.left+"px";el.style.width=g.width+"px";el.style.opacity=opacity}}
groupEls.forEach(el=>{{const pi=Number(el.dataset.prevIndex),ci=Number(el.dataset.currentIndex),pc=Number(el.dataset.prevCount),cc=Number(el.dataset.currentCount);let start;if(duration&&pi>=0)start=geometry(pi,pc);else{{const finish=geometry(Math.max(ci,0),cc);start=duration?{{left:finish.left+finish.width/2,width:0}}:finish}}setGeometry(el,start,duration&&pi<0?0:1)}});
requestAnimationFrame(()=>requestAnimationFrame(()=>{{groupEls.forEach(el=>{{const ci=Number(el.dataset.currentIndex),cc=Number(el.dataset.currentCount);if(ci>=0)setGeometry(el,geometry(ci,cc),1);else{{const left=parseFloat(el.style.left)||0,width=parseFloat(el.style.width)||0;setGeometry(el,{{left:left+width/2,width:0}},0)}}}});document.querySelectorAll(".bar").forEach(el=>{{const end=Number(el.dataset.end);el.style.height=end+"%";el.style.opacity=end===0?0:1}});document.querySelectorAll(".value").forEach(el=>el.style.bottom=Number(el.dataset.end)+"%");if(!duration){{document.querySelectorAll(".value").forEach(el=>el.textContent=Number(el.dataset.end).toFixed(1)+"%");return}}const started=performance.now();function tick(now){{const t=Math.min(1,(now-started)/duration),e=ease(t);document.querySelectorAll(".value").forEach(el=>{{const a=Number(el.dataset.start),b=Number(el.dataset.end);el.textContent=(a+(b-a)*e).toFixed(1)+"%"}});if(t<1)requestAnimationFrame(tick)}}requestAnimationFrame(tick)}}));</script></body></html>"""


@st.dialog("确认删除情景")
def confirm_delete_scenarios(scenario_id: str | None = None) -> None:
    saved = list(st.session_state.saved_scenarios)
    entries = [(_saved_scenario_id(item, index), item) for index, item in enumerate(saved)]
    targets = entries if scenario_id is None else [
        (item_id, item) for item_id, item in entries if item_id == scenario_id
    ]
    if not targets:
        st.info("该情景已不存在，无需再次删除。")
        if st.button("关闭", use_container_width=True):
            st.rerun()
        return

    target_ids = {item_id for item_id, _ in targets}
    target_names = "、".join(f"“{item.get('name') or '未命名情景'}”" for _, item in targets)
    removes_anchor = str(st.session_state.get("anchor_scenario_id") or "") in target_ids
    if scenario_id is None:
        st.error(f"将永久删除全部{len(targets)}个已保存情景：{target_names}")
    else:
        st.warning(f"将永久删除{target_names}。")
    if removes_anchor:
        st.error("其中包含当前锚点。确认删除后，比较基准将自动恢复为同设计全人群。")
    st.caption("删除只影响会话中的已保存情景，不会修改计算引擎或原始数据；删除后不可在当前会话中恢复。")

    cancel_col, confirm_col = st.columns(2)
    if cancel_col.button("取消", use_container_width=True, key=f"cancel_delete_{scenario_id or 'all'}"):
        st.rerun()
    if confirm_col.button(
        "确认删除",
        type="primary",
        use_container_width=True,
        key=f"confirm_delete_{scenario_id or 'all'}",
    ):
        st.session_state.saved_scenarios = [
            item for index, item in enumerate(saved)
            if _saved_scenario_id(item, index) not in target_ids
        ]
        st.session_state.comparison_selected_ids = [
            item_id for item_id in st.session_state.get("comparison_selected_ids", [])
            if item_id not in target_ids
        ]
        st.session_state.comparison_known_ids = [
            item_id for item_id in st.session_state.get("comparison_known_ids", [])
            if item_id not in target_ids
        ]
        st.session_state.comparison_previous_snapshot = [
            item for item in st.session_state.get("comparison_previous_snapshot", [])
            if str(item.get("id")) not in target_ids
        ]
        if removes_anchor:
            _set_anchor(None)
        st.toast("情景已删除。")
        st.rerun()


def comparison_page() -> None:
    render_header("情景比较与管理", "并列查看、筛选和管理已保存情景，并可统一设置比较锚点。")
    saved = st.session_state.saved_scenarios
    if not saved:
        st.info("尚未保存情景。请在“探索分析”完成模拟后点击“保存情景”。")
        return
    scenario_entries = [
        (_saved_scenario_id(item, index), item)
        for index, item in enumerate(saved)
    ]
    scenario_ids = [item_id for item_id, _ in scenario_entries]
    scenario_labels = {item_id: item["name"] for item_id, item in scenario_entries}

    render_anchor_selector("comparison_anchor_selector", "统一比较锚点")
    active_anchor = st.session_state.get("anchor_scenario_id")
    if active_anchor:
        st.success(f"已锚定“{scenario_labels[active_anchor]}”。后续探索结果将统一与其比较。")
    else:
        st.info("未锚定情景：后续探索结果固定与当前设计参数下的全人群参照比较。")
    st.caption("锚点仅控制结果卡片、箭头、动画和下载文件中的方案比较基准；相对全人群PoS差异始终保留。")

    known_ids = list(st.session_state.get("comparison_known_ids", []))
    selected_ids = [item_id for item_id in st.session_state.get("comparison_selected_ids", []) if item_id in scenario_ids]
    selected_ids.extend(item_id for item_id in scenario_ids if item_id not in known_ids and item_id not in selected_ids)
    if "comparison_selected_ids" not in st.session_state:
        selected_ids = list(scenario_ids)
    st.session_state.comparison_selected_ids = selected_ids
    st.session_state.comparison_known_ids = list(scenario_ids)
    selected_ids = st.multiselect(
        "选择参与比较的情景",
        scenario_ids,
        format_func=lambda item_id: scenario_labels[item_id],
        key="comparison_selected_ids",
        help="勾选或取消已保存情景；比较图的位置和柱宽会随所选数量平滑调整。",
    )
    selected_set = set(selected_ids)
    st.caption(f"已选择{len(selected_ids)}/{len(scenario_ids)}个已保存情景。")

    rows = []
    for identity, item in scenario_entries:
        if identity not in selected_set:
            continue
        result = item["result"]
        config = result["normalized_config"]
        step = config["step24a"]
        severity = {"ordinary": 0, "caution": 1, "strong": 2, "block": 3}
        highest = max(
            (warning["level"] for warning in result.get("warnings_ui", [])),
            key=lambda level: severity[level],
            default="ordinary",
        )
        rows.append(
            {
                "情景名称": item["name"],
                "剂量": str(config["trial"]["dose"]).replace("BZP ", ""),
                "N": config["trial"]["total_n"],
                "缺失方法": MISSING_LABELS[config["missing_death"]["sensitivity_rule"]],
                "效应假设": EFFECT_LABELS[step["effect_assumption"]],
                "NIHSS范围": result["nihss_interval_zh"],
                "其他条件": result["condition_summary_zh"],
                "PoS": format_pct(result.get("enriched_population_pos")),
                "保证概率": format_pct(result.get("bayesian_assurance")),
                "相对全人群PoS差异": format_pct(result.get("delta_pos"), signed=True),
                "符合比例": format_pct(result.get("eligible_proportion")),
                "预计筛查人数": result.get("estimated_screened_n"),
                "预警状态": highest,
            }
        )
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("当前未勾选比较情景。请从上方列表中至少选择一个情景。")
    current_snapshot = []
    for identity, item in scenario_entries:
        if identity not in selected_set:
            continue
        result = item["result"]
        current_snapshot.append(
            {
                "id": identity,
                "name": item["name"],
                "pos": float(result.get("enriched_population_pos") or 0) * 100,
                "assurance": float(result.get("bayesian_assurance") or 0) * 100,
            }
        )
    motion_enabled = st.session_state.get("result_motion_enabled", True)
    previous_snapshot = st.session_state.get("comparison_previous_snapshot", [])
    if st.session_state.get("_page_just_entered", False):
        previous_snapshot = []
    components.html(
        _comparison_animation_html(current_snapshot, previous_snapshot, motion_enabled),
        height=360,
        scrolling=False,
    )
    st.session_state.comparison_previous_snapshot = current_snapshot
    st.caption("纵轴固定为0–100%；进入页面、勾选、取消勾选和删除情景时播放变化，关闭‘结果动画’后立即显示最终状态。")

    st.markdown("#### 管理情景列表")
    for index, item in enumerate(list(saved)):
        identity = _saved_scenario_id(item, index)
        is_anchor = identity == st.session_state.get("anchor_scenario_id")
        name_col, anchor_col, delete_col = st.columns([4, 1.25, 1])
        name_col.write(f"{item['name']} {'· 当前锚点' if is_anchor else ''}")
        if anchor_col.button(
            "当前锚点" if is_anchor else "设为锚点",
            key=f"anchor_{identity}",
            disabled=is_anchor,
            use_container_width=True,
        ):
            _set_anchor(identity)
            st.rerun()
        if delete_col.button("删除", key=f"delete_{identity}", use_container_width=True):
            confirm_delete_scenarios(identity)
    if st.button("清空全部情景"):
        confirm_delete_scenarios()
    st.caption("本页只读取和管理已保存的情景级结果，不会运行模型。删除操作需要再次确认。")


def manual_page() -> None:
    render_header("使用说明", "运行前先了解三步操作、指标含义和边界。")
    st.markdown(
        """
### 三步完成一次探索
<div class="manual-step"><b>1. 选择参数</b><br>选择剂量、样本量、缺失处理、效应假设和NIHSS范围。</div>
<div class="manual-step"><b>2. 运行模拟</b><br>点击“运行模拟”，查看真实阶段进度、已用时间与预计时间。</div>
<div class="manual-step"><b>3. 保存、锚定并下载</b><br>保存有价值的情景，可在探索分析或情景比较与管理中设为固定锚点，再下载中文HTML报告或CSV结果。</div>
""",
        unsafe_allow_html=True,
    )
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("### 主要指标")
        st.markdown(
            """
- **PoS**：当前设计假设下达到统计成功标准的模拟比例，用于情景间比较。
- **Bayesian保证概率**：在效应存在不确定性时，设计达到成功标准的概率。
- **相对全人群PoS差异**：当前情景相对同剂量、同样本量全人群参照的差异。
- **符合比例**：Phase II来源数据中满足当前条件的比例。
- **预计筛查人数**：按符合比例估算，为达到目标随机样本量可能需要筛查的人数。
- **数据支持状态**：依据来源总人数、剂量组人数、安慰剂组人数及零单元格情况分级。
"""
        )
    with right:
        st.markdown("### 预警含义")
        st.info("蓝色：普通规划提示，不阻止运行。")
        st.warning("黄色：来源或筛查负担需要谨慎解释。")
        st.error("红色：来源极少、外推或逻辑冲突；无来源时禁止计算。")
        st.markdown("**示例**：400 mg BID、N=1122、MI、NIHSS 6–20可作为全人群参照情景。")
    st.markdown("### 协作功能")
    st.markdown(
        """
- **更新日志**：只读查看项目团队已发布的功能更新、问题修复和使用提示。
- **问题反馈**：提交文字、PNG/JPG截图及可选的当前情景摘要；当前记录只保存在服务器本地，并返回唯一反馈编号。
"""
    )
    st.markdown("### 常见问题")
    with st.expander("数值越高是否就代表应选择该人群？"):
        st.write("不是。还要同时检查来源人数、符合比例、筛查负担和预警；无稳定交互时不能解释为药物在该人群更有效。")
    with st.expander("自定义效应百分比如何理解？"):
        st.write("自定义百分比以Phase II原始观察风险差为基准：50%与默认保守情景相当，100%表示不折减，110%和120%表示原始观察效应的1.10倍和1.20倍。超过100%属于乐观外推敏感性，不代表效应提升已经得到证实。")
    with st.expander("年龄阈值和自定义区间有什么区别？"):
        st.write("年龄阈值用于快速查看预设下限；自定义区间同时限定最低和最高年龄，左右边界均纳入筛选。区间越窄，越需要关注二期来源人数和数据支持提示。")
    with st.expander("锚定情景会改变计算吗？"):
        st.write("不会。锚定只固定后续结果卡片、箭头、动画和下载文件中的比较基准。相对全人群PoS差异仍按同设计全人群定义计算；未锚定时自动与同设计全人群比较。")
    with st.expander("为什么相同参数第二次运行很快？"):
        st.write("应用会按完整计算参数缓存情景级结果。缓存不保存患者级记录。")
    with st.expander("下载报告会再次运行模型吗？"):
        st.write("不会。HTML和CSV都直接使用当前已完成的结果。")
    with st.expander("问题反馈如何通知和回执？"):
        st.write("反馈会先写入服务器本地并生成唯一编号。邮件功能启用后，系统再通过独立队列发送内部提醒；填写联系邮箱的提交者还会收到自动回执。邮件临时失败不影响本地保存。")
    with st.expander("方法与限制"):
        st.markdown(
            """
结果使用已完成内部校准和一致性验证的探索性模拟引擎。Day90前死亡按mRS 6处理；当前计算不合并历史二期研究数据。
默认保守效应采用Phase II观察风险差的50%。快速探索与稳定复核只改变模拟次数，不改变效应锚点或成功规则。

Phase III样本量、成功标准、剂量、多重性和最终缺失处理规则尚未全部锁定。来源稀疏或范围外推会降低稳定性。
本工具不重新寻找富集人群，不提供确证性推荐，也不代表最终Ⅲ期成功概率。
"""
        )
    st.caption("打开本页不会运行模型，也不会生成虚拟人群。")


def _changelog_images_html(images: list[dict]) -> str:
    media_root = changelog_media_root().resolve()
    figures: list[str] = []
    for image in images:
        relative_path = str(image.get("path") or "").strip()
        candidate = (media_root / relative_path).resolve()
        if candidate.parent != media_root or not candidate.is_file():
            continue
        try:
            encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
        except OSError:
            continue
        mime_type = mimetypes.guess_type(candidate.name)[0] or "image/png"
        caption = html.escape(str(image.get("caption") or ""))
        caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
        figure_class = "change-media wide" if image.get("wide") else "change-media"
        figures.append(
            f'<figure class="{figure_class}">'
            f'<img src="data:{mime_type};base64,{encoded}" alt="{caption}" loading="lazy">'
            f"{caption_html}</figure>"
        )
    if not figures:
        return ""
    return f'<div class="change-media-grid">{"".join(figures)}</div>'


def changelog_page() -> None:
    render_header("更新日志", "按时间查看试用工具已发布的功能、修复与使用提示。")
    st.markdown(
        '<div class="local-storage-note"><strong>只读更新流</strong><br>'
        '日志由项目团队统一发布，按置顶状态和发布时间倒序显示；本页不会运行模型或修改情景。</div>',
        unsafe_allow_html=True,
    )
    try:
        entries = load_changelog_entries()
    except LocalContentError as exc:
        LOGGER.exception("Unable to load local changelog")
        st.error("更新日志暂时无法读取，请稍后重试。")
        st.caption(str(exc))
        return

    if not entries:
        st.info("当前暂无已发布更新。后续版本说明、功能调整和已修复问题会在此按时间连续展示。")
        st.caption(f"当前版本：{APP_VERSION}")
        return

    posts: list[str] = []
    for entry in entries:
        category = html.escape(str(entry.get("category") or "功能更新"))
        published_at = html.escape(str(entry.get("published_at") or ""))
        version = html.escape(str(entry.get("version") or ""))
        title = html.escape(str(entry.get("title") or "更新"))
        body = "<br>".join(html.escape(str(entry.get("body") or "")).splitlines())
        meta_parts = [f'<span class="change-badge">{category}</span>']
        if entry.get("pinned"):
            meta_parts.append('<span class="change-badge">置顶</span>')
        if version:
            meta_parts.append(f"<span>{version}</span>")
        if published_at:
            meta_parts.append(f"<span>{published_at}</span>")
        highlights = "".join(
            f"<li>{html.escape(str(item))}</li>" for item in entry.get("highlights", [])
        )
        highlights_html = f'<ul class="change-highlights">{highlights}</ul>' if highlights else ""
        body_html = f'<div class="change-body">{body}</div>' if body else ""
        images_html = _changelog_images_html(entry.get("images", []))
        posts.append(
            '<article class="change-post">'
            f'<div class="change-meta">{"".join(meta_parts)}</div>'
            f"<h3>{title}</h3>{body_html}{highlights_html}{images_html}</article>"
        )
    st.markdown(f'<div class="change-feed">{"".join(posts)}</div>', unsafe_allow_html=True)
    st.caption(f"当前版本：{APP_VERSION} · 本页只读取已发布的更新内容。")


def _json_scalar(value: object) -> object:
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _feedback_scenario_context(result: dict | None) -> dict:
    if not result:
        return {}
    normalized = result.get("normalized_config") or {}
    trial = normalized.get("trial") or {}
    step24a = normalized.get("step24a") or {}
    missing_death = normalized.get("missing_death") or {}
    fields = {
        "config_hash": result.get("config_hash"),
        "dose": trial.get("dose"),
        "total_n": trial.get("total_n"),
        "missing_rule": missing_death.get("sensitivity_rule"),
        "effect_assumption": step24a.get("effect_assumption"),
        "effect_multiplier": step24a.get("effect_multiplier"),
        "nihss_interval": result.get("nihss_interval_zh"),
        "condition_summary": result.get("condition_summary_zh"),
        "enriched_population_pos": result.get("enriched_population_pos"),
        "bayesian_assurance": result.get("bayesian_assurance"),
        "delta_pos_vs_all_population": result.get("delta_pos"),
        "eligible_n": result.get("eligible_n"),
        "estimated_screened_n": result.get("estimated_screened_n"),
        "evidence_support_status": result.get("evidence_support_status"),
    }
    return {key: _json_scalar(value) for key, value in fields.items()}


def feedback_page() -> None:
    render_header("问题反馈", "提交使用问题、页面截图或改进建议，并获得可追踪的反馈编号。")
    mail_ready = email_delivery_configured()
    storage_detail = (
        "反馈先写入本地反馈库，再由邮件队列发送内部提醒；填写联系邮箱后会收到自动回执。"
        if mail_ready
        else "反馈先写入本地反馈库；邮件配置尚未启用，当前不会发送提醒或自动回执。"
    )
    st.markdown(
        '<div class="local-storage-note"><strong>本地可靠保存 · 邮件异步通知</strong><br>'
        f'{storage_detail} PNG/JPG截图经校验并移除图片元数据后单独保存。</div>',
        unsafe_allow_html=True,
    )

    receipt = st.session_state.get("feedback_receipt")
    if receipt:
        feedback_id = html.escape(str(receipt.get("feedback_id") or ""))
        created_at = html.escape(str(receipt.get("created_at") or "").replace("T", " "))
        attachment_count = int(receipt.get("attachment_count") or 0)
        internal_queued = bool(receipt.get("internal_notification_queued"))
        acknowledgement_queued = bool(receipt.get("acknowledgement_queued"))
        mail_status = "内部提醒已进入发送队列" if internal_queued else "邮件提醒未启用"
        if acknowledgement_queued:
            mail_status += " · 自动回执已进入发送队列"
        st.markdown(
            '<div class="feedback-receipt"><strong>反馈已保存：'
            f"{feedback_id}</strong><span>提交时间：{created_at} · 截图{attachment_count}张 · 状态：待处理 · "
            f'{html.escape(mail_status)}。请保留该编号，便于后续核对。</span></div>',
            unsafe_allow_html=True,
        )

    source_pages = [
        "探索分析",
        "二期人群洞察",
        "情景比较与管理",
        "使用说明",
        "更新日志",
        "登录或访问",
        "其他",
    ]
    default_source = str(st.session_state.get("feedback_source_page") or "探索分析")
    if default_source not in source_pages:
        default_source = "其他"
    revision = int(st.session_state.get("feedback_form_revision", 0))
    current_result = st.session_state.get("current_result")

    form_col, guide_col = st.columns([2.15, 1], gap="large")
    with form_col:
        st.markdown("### 填写反馈")
        with st.form(f"feedback_form_{revision}"):
            meta_a, meta_b, meta_c = st.columns(3)
            category = meta_a.selectbox(
                "问题类型",
                ["功能异常", "界面或排版", "计算结果疑问", "功能建议", "其他"],
                key=f"feedback_category_{revision}",
            )
            impact = meta_b.selectbox(
                "影响程度",
                ["一般建议", "影响部分使用", "无法继续使用"],
                key=f"feedback_impact_{revision}",
            )
            source_page = meta_c.selectbox(
                "问题发生页面",
                source_pages,
                index=source_pages.index(default_source),
                key=f"feedback_source_{revision}",
            )
            title = st.text_input(
                "问题标题",
                max_chars=80,
                placeholder="用一句话概括问题",
                key=f"feedback_title_{revision}",
            )
            description = st.text_area(
                "问题描述",
                height=150,
                max_chars=4000,
                placeholder="请说明您看到了什么、当时选择了哪些参数，以及问题如何影响使用。",
                key=f"feedback_description_{revision}",
            )
            reproduction_steps = st.text_area(
                "复现步骤（可选）",
                height=100,
                max_chars=2000,
                placeholder="例如：进入二期人群洞察 → 选择年龄70–75岁 → 点击运行。",
                key=f"feedback_steps_{revision}",
            )
            expected_behavior = st.text_area(
                "期望结果（可选）",
                height=85,
                max_chars=1200,
                placeholder="说明您原本期望页面如何显示或响应。",
                key=f"feedback_expected_{revision}",
            )
            uploaded_files = st.file_uploader(
                f"上传截图（可选，最多{MAX_ATTACHMENTS}张）",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=True,
                help="每张不超过5 MB。服务器仅保留重新编码后的图片，不保留EXIF等图片元数据。",
                key=f"feedback_uploads_{revision}",
            )
            contact = st.text_input(
                "联系邮箱（可选）",
                max_chars=254,
                placeholder="填写后可接收自动回执",
                help="仅用于发送本次反馈的自动回执及必要回访；不填写不影响提交。",
                key=f"feedback_contact_{revision}",
            )
            include_scenario = st.checkbox(
                "关联当前探索情景的参数与汇总结果",
                value=bool(current_result),
                disabled=current_result is None,
                help="仅保存当前情景级参数与汇总值，不保存患者级数据。",
                key=f"feedback_scenario_{revision}",
            )
            privacy_confirmed = st.checkbox(
                "我确认反馈文字和截图不包含患者姓名、病历号、身份证号、联系方式或其他可识别信息。",
                key=f"feedback_privacy_{revision}",
            )
            submitted = st.form_submit_button("提交反馈", type="primary", use_container_width=True)

        if submitted:
            files = list(uploaded_files or [])
            if not privacy_confirmed:
                st.error("提交前请确认反馈中不包含患者隐私或可识别信息。")
            elif len(files) > MAX_ATTACHMENTS:
                st.error(f"一次最多上传{MAX_ATTACHMENTS}张截图，请减少后重试。")
            else:
                try:
                    saved = submit_feedback(
                        category=category,
                        impact=impact,
                        source_page=source_page,
                        title=title,
                        description=description,
                        reproduction_steps=reproduction_steps,
                        expected_behavior=expected_behavior,
                        contact=contact,
                        app_version=APP_VERSION,
                        scenario_context=(
                            _feedback_scenario_context(current_result) if include_scenario else None
                        ),
                        attachments=[(item.name, item.getvalue()) for item in files],
                    )
                except LocalContentError as exc:
                    st.error(str(exc))
                except Exception:
                    LOGGER.exception("Unexpected local feedback submission failure")
                    st.error("反馈暂时无法保存，请稍后重试。")
                else:
                    st.session_state.feedback_receipt = saved
                    st.session_state.feedback_form_revision = revision + 1
                    st.rerun()

    with guide_col:
        st.markdown("### 提交建议")
        st.markdown(
            """
- 标明问题发生页面和影响程度。
- 写清能够稳定复现的操作顺序。
- 截图尽量保留完整控件名称和提示信息。
- 计算疑问可关联当前情景，便于复核参数。
"""
        )
        if current_result:
            st.success("当前会话已有模拟结果，可选择关联情景级参数与汇总值。")
        else:
            st.info("当前会话尚无模拟结果；仍可提交文字和截图反馈。")
        st.warning("请勿提交患者级数据、受试者编号或任何个人可识别信息。")
        if mail_ready:
            st.caption("反馈提交后先本地保存，再异步发送内部提醒；填写邮箱的提交者会收到 BlueBalloon BlueLab 自动回执。")
        else:
            st.caption("邮件功能尚未启用；反馈仍会完整保存在服务器本地。")


init_state()
if st.session_state.active_page == "情景比较":
    st.session_state.active_page = "情景比较与管理"

WORKSPACE_NAV_ITEMS = [
    ("探索分析", ":material/tune:", "nav_exploration"),
    ("二期人群洞察", ":material/groups:", "nav_population"),
    ("情景比较与管理", ":material/compare_arrows:", "nav_comparison"),
    ("使用说明", ":material/menu_book:", "nav_manual"),
]
COLLABORATION_NAV_ITEMS = [
    ("更新日志", ":material/history:", "nav_changelog"),
    ("问题反馈", ":material/bug_report:", "nav_feedback"),
]


def render_sidebar_navigation(items: list[tuple[str, str, str]]) -> None:
    for label, icon, key in items:
        is_active = st.session_state.active_page == label
        if st.button(
            label,
            key=key,
            icon=icon,
            type="primary" if is_active else "tertiary",
            use_container_width=True,
        ):
            previous_page = st.session_state.active_page
            if label == "问题反馈" and previous_page != "问题反馈":
                st.session_state.feedback_source_page = previous_page
            st.session_state.active_page = label
            st.rerun()


with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=190)
    st.markdown(
        """
<div class="sidebar-product">Phase III规划探索</div>
<div class="sidebar-subtitle">临床开发决策支持工具</div>
<div class="sidebar-section">工作区</div>
""",
        unsafe_allow_html=True,
    )
    render_sidebar_navigation(WORKSPACE_NAV_ITEMS)
    st.markdown('<div class="sidebar-section" style="margin-top:16px">协作</div>', unsafe_allow_html=True)
    render_sidebar_navigation(COLLABORATION_NAV_ITEMS)
    st.markdown('<div class="sidebar-section" style="margin-top:16px">显示设置</div>', unsafe_allow_html=True)
    st.toggle(
        "结果动画",
        key="result_motion_enabled",
        help="开启后，模拟完成时显示动态结果速览；关闭后直接更新结果。仅影响展示，不改变计算或报告。",
    )
    if demo_access_enabled():
        st.markdown(
            '<div class="demo-access-state">已登录：甲方试用账号<br>会话将在闲置或达到期限后要求重新登录。</div>',
            unsafe_allow_html=True,
        )
        if st.button("退出登录", icon=":material/logout:", use_container_width=True):
            _clear_demo_access()
            st.session_state["_demo_access_notice"] = "您已安全退出。"
            st.rerun()
    st.markdown(
        """
<div class="sidebar-status">
  <div><span class="status-dot"></span>试用环境运行中</div>
  <div>探索性 / 规划阶段</div>
</div>
""",
        unsafe_allow_html=True,
    )

page = st.session_state.active_page
st.session_state._page_just_entered = st.session_state.get("_last_rendered_page") != page
st.session_state._last_rendered_page = page

if page == "探索分析":
    exploration_page()
elif page == "二期人群洞察":
    render_population_insights_page(st.session_state.saved_scenarios, render_header)
elif page == "情景比较与管理":
    comparison_page()
elif page == "使用说明":
    manual_page()
elif page == "更新日志":
    changelog_page()
elif page == "问题反馈":
    feedback_page()
else:
    st.session_state.active_page = "探索分析"
    st.rerun()
