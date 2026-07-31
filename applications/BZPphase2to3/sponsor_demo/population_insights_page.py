from __future__ import annotations

from collections.abc import Callable
import html
import json

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
from sponsor_demo.population_insights import build_population_insights
from sponsor_demo.service import (
    DOSE_LABELS,
    MISSING_LABELS,
    MISSING_OPTIONS,
    build_config,
    format_pct,
)


INSIGHT_HELP = {
    "parameter_source": "可读取当前会话已保存的探索情景，也可在本页重新手动选择用于二期人群汇总的条件。",
    "saved_scenario": "读取已保存情景中的剂量、缺失处理、NIHSS范围和富集条件；本页不会重新运行模拟。",
    "dose": "选择需要查看的二期剂量组；仅改变剂量组来源汇总和与安慰剂组的结局概况。",
    "missing_rule": "规定Day90结局缺失和死亡在本页结局概况中的处理口径。",
    "nihss_range": "拖动左右端点设置基线NIHSS最低分和最高分；点击“应用筛选”后更新二期来源人群汇总。",
    "enrichment_conditions": "可再选择最多2项基线特征。条件越多，符合比例和二期来源人数通常越低。",
    "prior_stroke": "选择是否限制患者具有既往卒中史。有既往卒中时可继续限定卒前mRS。",
    "prestroke_mrs": "仅用于有既往卒中的患者；用于限定本次卒中前的功能状态。",
    "feature_levels": "选择该基线特征允许纳入的一个或多个水平；不选择水平时不增加该项限制。",
    "motor": "按基线NIHSS双侧上下肢运动项目合计划分的探索性条件，不是原试验或拟议三期已确认的分层因素。",
    "age_mode": "年龄阈值适合快速查看预设人群；自定义区间可同时限定最低和最高年龄。",
    "age_range": "拖动左右端点设置年龄闭区间，左右边界均纳入筛选。点击应用筛选后更新二期汇总。",
}


AGE_THRESHOLD_LABELS = {
    "lt65": "<65岁",
    "ge65": "≥65岁",
    "ge70": "≥70岁",
    "ge75": "≥75岁",
    "ge80": "≥80岁",
}


def _manual_age_condition() -> dict:
    mode = st.segmented_control(
        "年龄筛选方式",
        ["预设阈值", "自定义区间"],
        default="预设阈值",
        key="insight_age_mode",
        help=INSIGHT_HELP["age_mode"],
    )
    if mode == "自定义区间":
        lower, upper = st.slider(
            "年龄范围",
            min_value=AGE_SOURCE_MIN,
            max_value=AGE_SOURCE_MAX,
            value=(70, 75),
            step=1,
            key="insight_age_range",
            help=INSIGHT_HELP["age_range"],
        )
        st.caption(f"当前条件：{lower}岁≤年龄≤{upper}岁（含边界）")
        return {"feature": "age", "levels": [age_range_code(lower, upper)]}

    level = st.selectbox(
        "年龄阈值",
        list(AGE_THRESHOLD_LABELS),
        index=1,
        format_func=lambda code: AGE_THRESHOLD_LABELS[code],
        key="insight_age_threshold",
        help="按单一年龄阈值筛选。≥80岁仅用于查看二期来源构成。",
    )
    return {"feature": "age", "levels": [level]}

CHART_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "responsive": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
}


def _format_point_change(value: float) -> str:
    if 0 < abs(value) < 0.05:
        return "+<0.1" if value > 0 else "−<0.1"
    return f"{value:+.1f}"


def _insight_metric_delta(
    current: dict,
    previous: dict | None,
    key: str,
    *,
    kind: str = "count",
    favorable: str = "up",
) -> tuple[str | None, str]:
    if not previous:
        return None, "off"
    current_value = current.get(key)
    previous_value = previous.get(key)
    if current_value is None or previous_value is None:
        return None, "off"
    difference = float(current_value) - float(previous_value)
    if kind == "percentage_point":
        text = _format_point_change(difference * 100)
    else:
        relative = None if float(previous_value) == 0 else difference / abs(float(previous_value)) * 100
        text = f"{difference:+,.0f}人"
        if relative is not None:
            text += f"（{relative:+.1f}%）"
    if favorable == "neutral" or abs(difference) < 1e-12:
        return text, "off"
    return text, "normal" if favorable == "up" else "inverse"


def _population_change_html(current: dict, previous: dict) -> str:
    metric_rows = [
        ("当前条件人数", "eligible_n", "count", "up"),
        ("符合比例", "eligible_proportion", "pct", "up"),
        (f"所选剂量组（{current['dose']}）", "selected_dose_n", "count", "neutral"),
        ("安慰剂组", "placebo_n", "count", "neutral"),
    ]

    def scaled_value(payload: dict, key: str, kind: str) -> float:
        value = float(payload.get(key) or 0)
        return value * 100 if kind == "pct" else value

    def delta_badge(end: float, start: float, kind: str, favorable: str) -> str:
        difference = end - start
        arrow = "↑" if difference > 0 else ("↓" if difference < 0 else "→")
        if kind == "pct":
            label = _format_point_change(difference)
        else:
            relative = None if start == 0 else difference / abs(start) * 100
            label = f"{difference:+,.0f}人"
            if relative is not None:
                label += f"（{relative:+.1f}%）"
        if favorable == "neutral" or abs(difference) < 1e-12:
            tone = "neutral"
        else:
            improved = (difference > 0 and favorable == "up") or (difference < 0 and favorable == "down")
            tone = "favorable" if improved else "unfavorable"
        return f'<small class="delta {tone}">{arrow} {label}</small>'

    cards = []
    for label, key, kind, favorable in metric_rows:
        start = scaled_value(previous, key, kind)
        end = scaled_value(current, key, kind)
        initial = f"{start:.1f}%" if kind == "pct" else f"{int(round(start)):,}"
        cards.append(
            f'<div class="metric"><span>{html.escape(label)}</span>'
            f'<strong class="counter" data-start="{start:.6f}" data-end="{end:.6f}" '
            f'data-kind="{kind}">{initial}</strong>{delta_badge(end, start, kind, favorable)}</div>'
        )

    previous_flow = previous.get("flow", [])
    current_flow = current.get("flow", [])
    source_n = max(int(current.get("source_n") or 0), 1)
    funnel_rows = []
    colors = ["#98a2b3", "#3b82f6", "#0f766e"]
    for index, row in enumerate(current_flow):
        start = int(previous_flow[index]["n"]) if index < len(previous_flow) else 0
        end = int(row["n"])
        difference = end - start
        relative = None if start == 0 else difference / abs(start) * 100
        arrow = "↑" if difference > 0 else ("↓" if difference < 0 else "→")
        change = f"{arrow} {difference:+,}人"
        if relative is not None:
            change += f"（{relative:+.1f}%）"
        start_width = max(0.0, min(100.0, start / source_n * 100))
        end_width = max(0.0, min(100.0, end / source_n * 100))
        stage = html.escape(str(row.get("stage", "")))
        funnel_rows.append(
            f"<div class=funnel-row><div class=funnel-head><span>{stage}</span>"
            f"<div><strong class=counter data-start={start:.6f} data-end={end:.6f} data-kind=count>{start:,}</strong>"
            f"<small>{change}</small></div></div><div class=funnel-track>"
            f"<i class=funnel-fill data-end-width={end_width:.4f} style=width:{start_width:.4f}%;background:{colors[min(index, 2)]}></i></div></div>"
        )
    retained = float(current.get("eligible_proportion") or 0) * 100
    excluded = max(0, int(current.get("source_n") or 0) - int(current.get("eligible_n") or 0))
    support = html.escape(str(current.get("support_status") or "不可估计"))
    funnel_summary = f"当前条件保留 {retained:.1f}%，排除 {excluded:,} 人；数据支持状态：{support}。"
    duration = 650
    empty_changes = '<div class="empty">基线NIHSS构成无可显示变化。</div>'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}} body{{margin:0;font-family:"Microsoft YaHei",Arial,sans-serif;color:#182230;background:#fff}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:20px}}
.metric{{min-height:92px;padding:12px 13px;border:1px solid #e4e7ec;border-radius:6px;background:#fbfcfd}}
.metric span{{display:block;color:#667085;font-size:12px;margin-bottom:7px}}
.metric strong{{display:block;font-size:21px;font-variant-numeric:tabular-nums}}
.delta{{display:block;margin-top:5px;font-size:11px;font-weight:700;line-height:1.3}}
.favorable{{color:#087a55}} .unfavorable{{color:#c2413b}} .neutral{{color:#667085}}
h4{{font-size:14px;margin:0 0 10px;color:#344054}}
.funnel-row{{margin:10px 0}}
.funnel-head{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:5px}}
.funnel-head span{{font-size:12px;color:#475467}} .funnel-head div{{display:flex;align-items:baseline;gap:8px}}
.funnel-head strong{{font-size:13px;font-variant-numeric:tabular-nums}} .funnel-head small{{font-size:11px;color:#667085}}
.funnel-track{{height:11px;background:#f2f4f7;border-radius:2px;overflow:hidden}}
.funnel-fill{{display:block;height:11px;border-radius:2px;transition:width {duration}ms cubic-bezier(.22,1,.36,1)}}
.funnel-summary{{margin-top:11px;padding:9px 11px;background:#f8fafc;border-left:3px solid #0f766e;color:#475467;font-size:12px}}
@media(max-width:700px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(prefers-reduced-motion:reduce){{.funnel-fill{{transition:none!important}}}}
</style></head><body>
<div class="grid">{''.join(cards)}</div><h4>筛选影响路径</h4>{''.join(funnel_rows)}<div class="funnel-summary">{funnel_summary}</div>
<script>
const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;const duration=reduce?0:{duration};
function format(v,kind){{return kind==='pct'?v.toFixed(1)+'%':Math.round(v).toLocaleString('zh-CN')}}
function ease(t){{return 1-Math.pow(1-t,3)}}
requestAnimationFrame(()=>{{document.querySelectorAll('.funnel-fill').forEach(el=>el.style.width=el.dataset.endWidth+'%');
if(!duration){{document.querySelectorAll('.counter').forEach(el=>el.textContent=format(Number(el.dataset.end),el.dataset.kind));return}}
const started=performance.now();function tick(now){{const t=Math.min(1,(now-started)/duration),e=ease(t);document.querySelectorAll('.counter').forEach(el=>{{const a=Number(el.dataset.start),b=Number(el.dataset.end);el.textContent=format(a+(b-a)*e,el.dataset.kind)}});if(t<1)requestAnimationFrame(tick)}}requestAnimationFrame(tick)}});
</script></body></html>'''


@st.dialog("人群变化速览", width="large")
def _show_population_change_dialog(current: dict, previous: dict) -> None:
    components.html(_population_change_html(current, previous), height=440, scrolling=False)
    st.caption("变化量均相对上一已应用筛选；比例差异单位为百分点。筛选路径仅表示人数变化，不代表临床获益或风险方向。")


@st.dialog("放大查看", width="large")
def _show_chart_dialog(title: str, figure: go.Figure, key: str) -> None:
    st.markdown(f"### {title}")
    expanded = go.Figure(figure)
    expanded.update_layout(
        title=dict(text=""),
        height=740,
        autosize=True,
        margin=dict(l=90, r=70, t=90, b=70),
        legend=dict(orientation="h", x=0, y=1.04, xanchor="left", yanchor="bottom"),
        transition=dict(duration=0),
    )
    st.plotly_chart(expanded, use_container_width=True, config=CHART_CONFIG, key=f"{key}_dialog")


def _render_chart(figure: go.Figure, title: str, key: str) -> None:
    motion_enabled = st.session_state.get("result_motion_enabled", True)
    st.markdown(f"### {title}")
    figure.update_layout(
        title=dict(text=""),
        transition=dict(duration=650 if motion_enabled else 0, easing="cubic-in-out"),
        uirevision=key,
    )
    st.plotly_chart(figure, use_container_width=True, config=CHART_CONFIG, key=f"{key}_chart")
    _, action = st.columns([10, 1])
    if action.button(
        "放大",
        key=f"{key}_expand",
        icon=":material/fullscreen:",
        help=f"放大查看“{title}”",
        type="tertiary",
        use_container_width=True,
    ):
        _show_chart_dialog(title, figure, key)


@st.dialog("放大表格", width="large")
def _show_table_dialog(frame: pd.DataFrame) -> None:
    st.dataframe(frame, use_container_width=True, hide_index=True, height=360)


def _visible_distribution_rows(rows: list[dict], show_zero_levels: bool) -> list[dict]:
    if show_zero_levels:
        return rows
    visible = [row for row in rows if float(row["full_pct"]) > 0 or float(row["eligible_pct"]) > 0]
    return visible or rows[:1]


def _display_count(value: int) -> str:
    return f"{int(value):,}"


def _distribution_change_chart(rows: list[dict], show_zero_levels: bool) -> go.Figure:
    visible = _visible_distribution_rows(rows, show_zero_levels)
    labels = [str(row["level"]) for row in visible]
    differences = [(float(row["eligible_pct"]) - float(row["full_pct"])) * 100 for row in visible]
    customdata = [
        [
            _display_count(row.get("full_n", 0)),
            format(int(row.get("full_denominator", 0)), ","),
            format(float(row.get("full_pct", 0)) * 100, ".1f"),
            _display_count(row.get("eligible_n", 0)),
            format(int(row.get("eligible_denominator", 0)), ","),
            format(float(row.get("eligible_pct", 0)) * 100, ".1f"),
            _format_point_change(difference),
        ]
        for row, difference in zip(visible, differences)
    ]
    limit = max(2.0, max((abs(value) for value in differences), default=0) * 1.35 + 0.5)
    text = ["" if abs(value) < 0.05 else _format_point_change(value) for value in differences]
    colors = ["#0f766e" if value > 0 else ("#64748b" if value < 0 else "#cbd5e1") for value in differences]
    fig = go.Figure(go.Bar(
        x=differences, y=labels, orientation="h", marker_color=colors, text=text,
        textposition="outside", textfont=dict(size=13), cliponaxis=False, customdata=customdata,
        hovertemplate=(
            "<b>%{y}</b><br>Phase II全人群：%{customdata[0]}/%{customdata[1]}（%{customdata[2]}%）"
            "<br>当前条件人群：%{customdata[3]}/%{customdata[4]}（%{customdata[5]}%）"
            "<br>差异：%{customdata[6]}个百分点<extra></extra>"
        ),
    ))
    fig.add_vline(x=0, line_width=1, line_color="#98a2b3")
    fig.update_layout(
        height=max(360, len(labels) * 48 + 130), margin=dict(l=70, r=105, t=35, b=60),
        xaxis=dict(title="当前条件人群 − Phase II全人群（百分点）", range=[-limit, limit], gridcolor="#e4e7ec", tickfont=dict(size=12)),
        yaxis=dict(type="category", title="", autorange="reversed", automargin=True, categoryorder="array", categoryarray=labels, tickfont=dict(size=12)),
        plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", showlegend=False,
        font=dict(family="Microsoft YaHei, Arial", size=13, color="#182230"),
    )
    return fig


def _distribution_reference_bar_chart(rows: list[dict], show_zero_levels: bool) -> go.Figure:
    visible = _visible_distribution_rows(rows, show_zero_levels)
    labels = [str(row["level"]) for row in visible]
    full_values = [float(row["full_pct"]) * 100 for row in visible]
    eligible_values = [float(row["eligible_pct"]) * 100 for row in visible]
    differences = [current - full for current, full in zip(eligible_values, full_values)]
    customdata = [
        [
            _display_count(row.get("full_n", 0)),
            format(int(row.get("full_denominator", 0)), ","),
            format(float(row.get("full_pct", 0)) * 100, ".1f"),
            _display_count(row.get("eligible_n", 0)),
            format(int(row.get("eligible_denominator", 0)), ","),
            format(float(row.get("eligible_pct", 0)) * 100, ".1f"),
            _format_point_change(difference),
        ]
        for row, difference in zip(visible, differences)
    ]
    hover = (
        "<b>%{y}</b><br>Phase II全人群：%{customdata[0]}/%{customdata[1]}（%{customdata[2]}%）"
        "<br>当前条件人群：%{customdata[3]}/%{customdata[4]}（%{customdata[5]}%）"
        "<br>差异：%{customdata[6]}个百分点<extra></extra>"
    )
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Phase II全人群", x=full_values, y=labels, orientation="h", offsetgroup="full",
        marker_color="#cbd5e1", text=[f"{value:.1f}%" if value > 0 else "" for value in full_values],
        textposition="outside", textfont=dict(size=13, color="#667085"), cliponaxis=False,
        customdata=customdata, hovertemplate=hover,
    ))
    fig.add_trace(go.Bar(
        name="当前条件人群", x=eligible_values, y=labels, orientation="h", offsetgroup="current",
        marker_color="#0f766e", text=[f"{value:.1f}%" if value > 0 else "" for value in eligible_values],
        textposition="outside", textfont=dict(size=13, color="#0f766e"), cliponaxis=False,
        customdata=customdata, hovertemplate=hover,
    ))
    upper = max(10.0, max(full_values + eligible_values, default=0) * 1.25 + 5)
    fig.update_layout(
        barmode="group", bargap=0.24, bargroupgap=0.10, height=max(380, len(labels) * 58 + 135),
        margin=dict(l=70, r=110, t=65, b=60),
        xaxis=dict(title="人群内占比（%）", range=[0, upper], gridcolor="#e4e7ec", tickfont=dict(size=12)),
        yaxis=dict(type="category", title="", autorange="reversed", automargin=True, categoryorder="array", categoryarray=labels, tickfont=dict(size=12)),
        plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
        legend=dict(orientation="h", x=0, y=1.04, xanchor="left", yanchor="bottom", font=dict(size=13)),
        font=dict(family="Microsoft YaHei, Arial", size=13, color="#182230"),
    )
    return fig


def _distribution_chart(rows: list[dict], view: str, show_zero_levels: bool) -> go.Figure:
    if view == "完整分布":
        return _distribution_reference_bar_chart(rows, show_zero_levels)
    return _distribution_change_chart(rows, show_zero_levels)



def _manual_conditions() -> list[dict]:
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
        key="insight_features",
        help=INSIGHT_HELP["enrichment_conditions"],
    )
    conditions = []
    for feature_code in selected_features:
        if feature_code == "prior_function":
            stroke_status = st.radio(
                "既往卒中状态",
                ["no", "yes"],
                format_func=lambda code: {"no": "无既往卒中", "yes": "有既往卒中"}[code],
                horizontal=True,
                key="insight_prior_stroke_status",
                help=INSIGHT_HELP["prior_stroke"],
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
                    key="insight_prestroke_mrs_level",
                    help=INSIGHT_HELP["prestroke_mrs"],
                )
                if prestroke_level == "unrestricted":
                    conditions.append({"feature": "previous_stroke", "levels": ["yes"]})
                else:
                    conditions.append({"feature": "prestroke_mrs", "levels": [prestroke_level]})
            else:
                conditions.append({"feature": "previous_stroke", "levels": ["no"]})
            continue

        if feature_code == "age":
            conditions.append(_manual_age_condition())
            continue
        levels = [level for level in FEATURES[feature_code].levels if level.code != "unrestricted"]
        selected_levels = st.multiselect(
            f"{FEATURES[feature_code].label_zh}范围",
            [level.code for level in levels],
            format_func=lambda code, choices=levels: next(level.label_zh for level in choices if level.code == code),
            key=f"insight_levels_{feature_code}",
            help=INSIGHT_HELP["feature_levels"],
        )
        if selected_levels:
            conditions.append({"feature": feature_code, "levels": selected_levels})

    use_motor = st.checkbox(
        "启用基线肢体运动探索条件",
        value=False,
        disabled=len(conditions) >= 2,
        help=INSIGHT_HELP["motor"],
        key="insight_use_motor",
    )
    if use_motor and len(conditions) < 2:
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
            key="insight_motor_level",
        )
        conditions.append({"feature": "motor", "levels": [motor_level]})
        st.caption("4分阈值为项目探索性预设，仅用于敏感性查看。")
    return conditions


def _manual_config() -> dict:
    left, right = st.columns(2, gap="large")
    with left:
        dose = st.selectbox(
            "剂量",
            list(DOSE_LABELS),
            index=1,
            key="insight_dose",
            help=INSIGHT_HELP["dose"],
        )
        missing_rule = st.selectbox(
            "缺失处理",
            list(MISSING_OPTIONS),
            format_func=lambda value: MISSING_LABELS[value],
            key="insight_missing_rule",
            help=INSIGHT_HELP["missing_rule"],
        )
        nihss_range = st.slider(
            "基线NIHSS范围",
            min_value=6,
            max_value=20,
            value=(6, 20),
            key="insight_nihss_range",
            help=INSIGHT_HELP["nihss_range"],
        )
    with right:
        conditions = _manual_conditions()
    st.caption("参数调整后点击“应用筛选”更新轻量汇总；本页不运行Monte Carlo或Bayesian计算。")
    return build_config(
        dose_label=dose,
        missing_rule=missing_rule,
        nihss_min=int(nihss_range[0]),
        nihss_max=int(nihss_range[1]),
        conditions=conditions,
    )


def _source_config(saved: list[dict]) -> dict:
    source_options = ["手动选择参数"]
    if saved:
        source_options.insert(0, "读取已保存情景")
    source_mode = st.radio(
        "参数来源",
        source_options,
        horizontal=True,
        key="insight_source_mode",
        help=INSIGHT_HELP["parameter_source"],
    )
    if source_mode == "手动选择参数":
        if not saved:
            st.info("当前会话尚无已保存情景，也可直接手动选择参数查看。")
        return _manual_config()

    selected_index = st.selectbox(
        "选择情景",
        list(range(len(saved))),
        format_func=lambda index: saved[index]["name"],
        key="insight_saved_scenario",
        help=INSIGHT_HELP["saved_scenario"],
    )
    selected = saved[selected_index]
    config = selected["result"]["normalized_config"]
    step = config["step24a"]
    st.info(
        f"已读取“{selected['name']}”："
        f"{str(config['trial']['dose']).replace('BZP ', '')}，"
        f"NIHSS {step['nihss_min']}–{step['nihss_max']}分，"
        f"{selected['result']['condition_summary_zh']}。"
    )
    st.caption("样本量、效应假设和模拟次数不会改变Phase II来源人群构成，本页不重新运行模拟。")
    return config


def _overview(insights: dict, previous: dict | None) -> None:
    st.markdown("### 当前人群概览")
    st.write(
        f"**NIHSS范围：** {insights['nihss_interval_zh']}　"
        f"**其他条件：** {insights['condition_summary_zh']}　"
        f"**结局比较：** {insights['dose']}组 vs 安慰剂组"
    )
    if previous:
        st.caption("箭头与变化量均相对上一已应用筛选；比例差异单位：百分点。人数增加表示来源支持增加，不代表疗效提高。")

    eligible_n_delta = _insight_metric_delta(insights, previous, "eligible_n")
    eligible_pct_delta = _insight_metric_delta(
        insights, previous, "eligible_proportion", kind="percentage_point"
    )
    dose_delta = _insight_metric_delta(insights, previous, "selected_dose_n", favorable="neutral")
    placebo_delta = _insight_metric_delta(insights, previous, "placebo_n", favorable="neutral")

    primary_metrics = st.columns(3)
    primary_metrics[0].metric(
        "Phase II FAS",
        insights["source_n"],
        help="二期全分析集且具有本页所需基线信息的来源人数；该固定基准不随筛选条件变化。",
    )
    primary_metrics[1].metric(
        "当前条件人数",
        insights["eligible_n"],
        delta=eligible_n_delta[0],
        delta_color=eligible_n_delta[1],
        help="满足当前NIHSS范围和全部富集条件的二期来源人数；变化量相对上一已应用筛选。",
    )
    primary_metrics[2].metric(
        "符合比例",
        format_pct(insights["eligible_proportion"]),
        delta=eligible_pct_delta[0],
        delta_color=eligible_pct_delta[1],
        help="当前条件人数占Phase II FAS来源人数的比例；变化量使用百分点。",
    )
    arm_metrics = st.columns(2)
    arm_metrics[0].metric(
        f"所选剂量组（{insights['dose']}）",
        insights["selected_dose_n"],
        delta=dose_delta[0],
        delta_color=dose_delta[1],
        help="当前条件人群中原随机至所选剂量组的人数；灰色变化仅表示构成差异。",
    )
    arm_metrics[1].metric(
        "安慰剂组",
        insights["placebo_n"],
        delta=placebo_delta[0],
        delta_color=placebo_delta[1],
        help="当前条件人群中原随机至安慰剂组的人数；灰色变化仅表示构成差异。",
    )
    if insights["support_warning_zh"]:
        st.warning(f"数据支持状态：{insights['support_status']}。{insights['support_warning_zh']}")
    else:
        st.success(f"数据支持状态：{insights['support_status']}")
    if insights["eligible_n"] == 0:
        st.error("当前条件在Phase II FAS中无来源病例，请调整筛选条件。")



def _flow_and_dose(insights: dict) -> None:
    flow = insights["flow"]
    dose_rows = insights["dose_distribution"]

    flow_values = [row["n"] for row in flow]
    fig = go.Figure(
        go.Bar(
            x=flow_values,
            y=[row["stage"] for row in flow],
            orientation="h",
            marker_color=["#98a2b3", "#3b82f6", "#0f766e"],
            texttemplate="%{x:.0f}",
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}：%{x}例<extra></extra>",
        )
    )
    fig.update_layout(
        title="人群筛选流程",
        height=340,
        margin=dict(l=45, r=70, t=60, b=45),
        xaxis=dict(
            title="人数",
            range=[0, max(flow_values, default=0) * 1.18 + 5],
            gridcolor="#e4e7ec",
            automargin=True,
        ),
        yaxis=dict(type="category", title="", autorange="reversed", automargin=True),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        font=dict(family="Microsoft YaHei, Arial", color="#182230"),
    )
    _render_chart(fig, "人群筛选流程", "population_flow")

    dose_values = [row["n"] for row in dose_rows]
    fig = go.Figure(
        go.Bar(
            x=[row["dose"] for row in dose_rows],
            y=dose_values,
            marker_color=["#60a5fa", "#0f766e", "#d97706", "#98a2b3"],
            texttemplate="%{y:.0f}",
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}：%{y}例<extra></extra>",
        )
    )
    fig.update_layout(
        title="当前条件人群的原随机组构成",
        height=360,
        margin=dict(l=45, r=45, t=65, b=65),
        yaxis=dict(
            title="人数",
            range=[0, max(dose_values, default=0) * 1.20 + 3],
            gridcolor="#e4e7ec",
            automargin=True,
        ),
        xaxis=dict(title="", automargin=True),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        font=dict(family="Microsoft YaHei, Arial", color="#182230"),
    )
    _render_chart(fig, "当前条件人群的原随机组构成", "dose_composition")



def _view_controls(insights: dict) -> tuple[str, bool]:
    zero_rows = []
    for rows in (insights["nihss_distribution"], insights["age_distribution"], insights["mrs_distribution"]):
        zero_rows.extend(
            str(row["level"]) for row in rows
            if float(row["full_pct"]) == 0 and float(row["eligible_pct"]) == 0
        )
    controls = st.columns([1.5, 1])
    with controls[0]:
        view = st.segmented_control(
            "页面比较模式",
            ["完整分布", "相对全人群变化"],
            default="完整分布",
            key="insight_distribution_view",
            help="完整分布显示两组原始占比；相对全人群变化同时切换基线分布和Day90结局图。",
        )
    with controls[1]:
        show_zero_levels = st.toggle(
            f"显示零占比分层（{len(zero_rows)}）",
            value=False,
            disabled=not zero_rows,
            key="insight_show_zero_levels",
            help="开启后显示两组占比均为0的分层；关闭后重建分类轴并压缩图表高度。",
        )
    if zero_rows and not show_zero_levels:
        st.caption(f"已隐藏{len(zero_rows)}个零占比分层：{"、".join(zero_rows)}。比例差异单位：百分点。")
    else:
        st.caption("人群构成变化不代表临床获益方向；精确人数、分母、占比与差异可悬停查看。")
    return view or "完整分布", bool(show_zero_levels)


def _distributions(insights: dict, view: str, show_zero_levels: bool) -> None:
    distributions = [
        ("基线NIHSS分布", "nihss_distribution", insights["nihss_distribution"]),
        ("年龄分布", "age_distribution", insights["age_distribution"]),
        ("本次卒中筛选期mRS分布", "mrs_distribution", insights["mrs_distribution"]),
    ]
    characteristic_rows = [
        {
            "level": f"{row["variable"]} · {row["level"]}",
            "full_n": row["full_n"],
            "full_denominator": row["full_denominator"],
            "full_pct": row["full_pct"],
            "eligible_n": row["eligible_n"],
            "eligible_denominator": row["eligible_denominator"],
            "eligible_pct": row["eligible_pct"],
        }
        for row in insights["characteristics"]
    ]
    distributions.append(("关键基线特征", "baseline_characteristics", characteristic_rows))
    for title, key, rows in distributions:
        chart_key = f"{key}_{view}_{int(show_zero_levels)}"
        _render_chart(_distribution_chart(rows, view, show_zero_levels), title, chart_key)


def _outcome_custom(row: dict) -> list[str]:
    response = "样本过少" if row["response_rate"] is None else f"{float(row["response_rate"]) * 100:.1f}%"
    expected = "不可展示" if row["suppressed"] else f"{float(row["expected_responders"]):.1f}"
    return [
        _display_count(row["n"]),
        _display_count(row["available_n"]),
        _display_count(row["missing_n"]),
        expected,
        response,
    ]


def _outcome(insights: dict, view: str) -> None:
    current_rows = insights["outcome"]
    full_rows = insights["full_outcome"]
    if view == "完整分布":
        fig = go.Figure()
        for name, rows, color, offset in (
            ("Phase II全人群", full_rows, "#cbd5e1", "full"),
            ("当前条件人群", current_rows, "#0f766e", "current"),
        ):
            values = [None if row["response_rate"] is None else float(row["response_rate"]) * 100 for row in rows]
            labels = ["样本过少" if value is None else f"{value:.1f}%" for value in values]
            fig.add_trace(go.Bar(
                name=name, x=[row["arm"] for row in rows], y=values, offsetgroup=offset, marker_color=color,
                text=labels, textposition="outside", textfont=dict(size=13), cliponaxis=False,
                customdata=[_outcome_custom(row) for row in rows],
                hovertemplate=(
                    f"<b>%{{x}} · {name}</b><br>来源人数：%{{customdata[0]}}"
                    "<br>进入分析人数：%{customdata[1]}<br>缺失人数：%{customdata[2]}"
                    "<br>估计响应人数：%{customdata[3]}<br>mRS 0–1比例：%{customdata[4]}<extra></extra>"
                ),
            ))
        fig.update_layout(
            barmode="group", bargap=0.34, bargroupgap=0.10, height=420, margin=dict(l=55, r=55, t=65, b=65),
            yaxis=dict(title="mRS 0–1比例（%）", range=[0, 100], gridcolor="#e4e7ec", tickfont=dict(size=12)),
            xaxis=dict(title="", tickfont=dict(size=13)), plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
            legend=dict(orientation="h", x=0, y=1.04, xanchor="left", yanchor="bottom", font=dict(size=13)),
            font=dict(family="Microsoft YaHei, Arial", size=13, color="#182230"),
        )
    else:
        full_map = {row["arm"]: row for row in full_rows}
        current_map = {row["arm"]: row for row in current_rows}
        labels = []
        differences = []
        customdata = []
        for arm in current_map:
            full = full_map[arm]
            current = current_map[arm]
            if full["response_rate"] is None or current["response_rate"] is None:
                continue
            difference = (float(current["response_rate"]) - float(full["response_rate"])) * 100
            labels.append(arm)
            differences.append(difference)
            customdata.append([f"{float(full["response_rate"]) * 100:.1f}%", f"{float(current["response_rate"]) * 100:.1f}%", _format_point_change(difference), _display_count(full["n"]), _display_count(current["n"])])
        if len(full_rows) == 2 and len(current_rows) == 2 and all(row["response_rate"] is not None for row in full_rows + current_rows):
            full_contrast = (float(full_rows[0]["response_rate"]) - float(full_rows[1]["response_rate"])) * 100
            current_contrast = (float(current_rows[0]["response_rate"]) - float(current_rows[1]["response_rate"])) * 100
            contrast_change = current_contrast - full_contrast
            labels.append("治疗差异")
            differences.append(contrast_change)
            customdata.append([f"{full_contrast:.1f}个百分点", f"{current_contrast:.1f}个百分点", _format_point_change(contrast_change), "—", "—"])
        colors = ["#0f766e" if value > 0 else ("#64748b" if value < 0 else "#cbd5e1") for value in differences]
        limit = max(3.0, max((abs(value) for value in differences), default=0) * 1.35 + 0.5)
        fig = go.Figure(go.Bar(
            x=differences, y=labels, orientation="h", marker_color=colors,
            text=[_format_point_change(value) for value in differences], textposition="outside", textfont=dict(size=13),
            customdata=customdata, cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>Phase II全人群：%{customdata[0]}（n=%{customdata[3]}）"
                "<br>当前条件人群：%{customdata[1]}（n=%{customdata[4]}）"
                "<br>变化：%{customdata[2]}个百分点<extra></extra>"
            ),
        ))
        fig.add_vline(x=0, line_width=1, line_color="#98a2b3")
        fig.update_layout(
            height=400, margin=dict(l=70, r=100, t=35, b=65),
            xaxis=dict(title="当前条件人群 − Phase II全人群（百分点）", range=[-limit, limit], gridcolor="#e4e7ec"),
            yaxis=dict(type="category", title="", autorange="reversed", categoryorder="array", categoryarray=labels),
            plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", showlegend=False,
            font=dict(family="Microsoft YaHei, Arial", size=13, color="#182230"),
        )
    _render_chart(fig, "Day90 mRS 0–1结局概况", f"day90_outcome_{view}")
    st.caption(
        "结局比例沿用所选缺失处理口径；多重插补下估计响应人数可为小数。"
        "治疗差异为所选剂量组减安慰剂组的描述性差值，不构成亚组疗效结论。"
    )


def render_population_insights_page(
    saved_scenarios: list[dict],
    render_header: Callable[[str, str], None],
) -> None:
    render_header("二期人群洞察", "查看当前富集条件在Phase II来源人群中的构成、覆盖范围与结局概况。")
    draft_config = _source_config(saved_scenarios)
    draft_signature = json.dumps(draft_config, ensure_ascii=False, sort_keys=True)

    if "insight_applied_signature" not in st.session_state:
        initial_insights = build_population_insights(draft_config)
        st.session_state.insight_applied_signature = draft_signature
        st.session_state.insight_applied_config = draft_config
        st.session_state.insight_applied_data = initial_insights
        st.session_state.insight_previous_data = None
        st.session_state.insight_change_revision = 0

    dirty = draft_signature != st.session_state.insight_applied_signature
    if dirty:
        st.info("参数已调整。下方仍显示上一已应用筛选，请点击“应用筛选”更新结果。")

    apply_clicked = st.button(
        "应用筛选",
        type="primary",
        disabled=not dirty,
        use_container_width=True,
        help="确认当前参数并更新二期人群汇总；不会运行Monte Carlo或Bayesian计算。",
        key="insight_apply_filters",
    )
    if apply_clicked:
        previous = st.session_state.insight_applied_data
        current = build_population_insights(draft_config)
        st.session_state.insight_previous_data = previous
        st.session_state.insight_applied_data = current
        st.session_state.insight_applied_config = draft_config
        st.session_state.insight_applied_signature = draft_signature
        st.session_state.insight_change_revision += 1
        if st.session_state.get("result_motion_enabled", True) and previous:
            _show_population_change_dialog(current, previous)
        else:
            st.toast("二期人群汇总已更新。")

    insights = st.session_state.insight_applied_data
    previous_insights = st.session_state.insight_previous_data
    _overview(insights, previous_insights)
    view, show_zero_levels = _view_controls(insights)
    _flow_and_dose(insights)
    _distributions(insights, view, show_zero_levels)
    _outcome(insights, view)
    st.info("所有图表均为Phase II去标识化数据的情景级汇总，不包含患者明细；仅用于探索性、规划阶段。")
