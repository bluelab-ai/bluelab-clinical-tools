from __future__ import annotations

import copy
import csv
import html
import io
import json
import math
import time
from datetime import datetime
from typing import Any, Callable

from clinical_trial_sim_engine.enrichment.final_condition_builder import condition_summary_zh
from clinical_trial_sim_engine.models.nihss_continuous_trend import OUTCOMES
from clinical_trial_sim_engine.simulation.step24a_engine import (
    EFFECT_SOURCES,
    config_hash,
    default_step24a_config,
    generate_target_population,
    normalize_step24a_config,
    preview_source_support,
    run_step24a_scenario,
    validate_step24a_config,
)

ProgressCallback = Callable[[int, str, float], None]

DOSE_LABELS = {
    "200 mg BID": "BZP 200mg BID",
    "400 mg BID": "BZP 400mg BID",
    "600 mg BID": "BZP 600mg BID",
}
MISSING_LABELS = {code: label for code, (_, label) in OUTCOMES.items()}
MISSING_OPTIONS = (
    "death6_multiple_imputation",
    "death6_locf_like",
    "death6_conservative_nonresponder",
)
EFFECT_LABELS = {
    "phase2_model": "默认保守效应（原始效应的50%）",
    "custom_multiplier": "自定义：相对Phase II原始效应",
    "v03_design": "方案设计假设对照（后台留档）",
}
EFFECT_OPTIONS = ("phase2_model", "custom_multiplier")
DISCLAIMER = "本工具用于规划阶段的情景探索；结果依赖当前数据与假设，不代表最终Ⅲ期成功概率。"


def build_config(
    *,
    dose_label: str = "400 mg BID",
    total_n: int = 1122,
    missing_rule: str = "death6_multiple_imputation",
    effect_assumption: str = "phase2_model",
    effect_multiplier: float = 1.0,
    nihss_min: int = 6,
    nihss_max: int = 20,
    conditions: list[dict[str, Any]] | None = None,
    n_simulations: int = 1000,
    random_seed: int = 20260717,
) -> dict[str, Any]:
    config = default_step24a_config()
    config["trial"].update(
        {
            "dose": DOSE_LABELS[dose_label],
            "total_n": int(total_n),
            "allocation": "1:1",
        }
    )
    config["missing_death"]["sensitivity_rule"] = missing_rule
    config["simulation"].update(
        {
            "method_type": "both",
            "n_simulations": int(n_simulations),
            "random_seed": int(random_seed),
        }
    )
    config["step24a"].update(
        {
            "nihss_min": int(nihss_min),
            "nihss_max": int(nihss_max),
            "conditions": conditions or [],
            "effect_assumption": effect_assumption,
            "effect_multiplier": float(effect_multiplier),
        }
    )
    return normalize_step24a_config(config)


def _emit(callback: ProgressCallback | None, percent: int, label: str, started: float) -> None:
    if callback:
        callback(percent, label, time.perf_counter() - started)


def warning_messages(
    config: dict[str, Any],
    preview: dict[str, Any],
    result: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    step = config["step24a"]
    if step["effect_assumption"] == "phase2_model":
        warnings.append(
            {
                "level": "ordinary",
                "title": "默认保守效应",
                "text": "当前情景固定采用Phase II原始观察风险差的50%。结果仅用于方案讨论。",
            }
        )
    elif step["effect_assumption"] == "custom_multiplier":
        multiplier = float(step["effect_multiplier"])
        if multiplier > 1:
            warnings.append(
                {
                    "level": "caution",
                    "title": "乐观效应外推",
                    "text": f"当前假设为Phase II原始观察风险差的{multiplier:.0%}，高于原始观察效应，仅用于乐观敏感性分析。",
                }
            )
        else:
            warnings.append(
                {
                    "level": "ordinary",
                    "title": "自定义效应",
                    "text": f"当前假设为Phase II原始观察风险差的{multiplier:.0%}；其中50%与默认保守情景相当，100%表示不折减。",
                }
            )
    if preview.get("status") == "blocked":
        for message in preview.get("errors_zh", []):
            warnings.append({"level": "block", "title": "无法运行", "text": str(message)})
        return warnings

    eligible = int(preview.get("eligible_n") or 0)
    active = int(preview.get("selected_dose_n") or 0)
    placebo = int(preview.get("placebo_n") or 0)
    proportion = float(preview.get("eligible_proportion") or 0)
    selected_conditions = len(step.get("conditions", []))
    screening_ratio = math.inf if proportion == 0 else 1 / proportion
    support_warning = str(preview.get("support_warning_zh") or "").strip()

    if eligible == 0:
        warnings.append(
            {
                "level": "block",
                "title": "无来源患者",
                "text": "当前参数组合在Phase II中无来源患者，无法进行数据驱动模拟，请调整条件。",
            }
        )
    elif eligible < 20 or active < 5 or placebo < 5:
        warnings.append(
            {
                "level": "strong",
                "title": "来源极少",
                "text": f"当前来源共{eligible}例，所选剂量组{active}例、安慰剂组{placebo}例。结果主要依赖外推，仅可作敏感性查看。",
            }
        )
    elif eligible < 40 or active < 10 or placebo < 10:
        warnings.append(
            {
                "level": "caution",
                "title": "来源有限",
                "text": f"当前来源共{eligible}例，部分组别样本偏少。请将结果视为方向性探索。",
            }
        )

    elif support_warning:
        warnings.append(
            {
                "level": "caution",
                "title": "来源有限",
                "text": support_warning,
            }
        )

    if int(step["nihss_min"]) >= 16:
        warnings.append(
            {
                "level": "strong",
                "title": "高分段外推",
                "text": "NIHSS 16分以上的Phase II来源有限。该范围结果属于模型外推敏感性，不形成富集推荐。",
            }
        )
    if selected_conditions >= 2:
        warnings.append(
            {
                "level": "caution",
                "title": "组合筛选",
                "text": "多个条件同时使用会快速缩小来源人群。请同时关注符合比例与预计筛查人数。",
            }
        )
    if screening_ratio > 3 and math.isfinite(screening_ratio):
        warnings.append(
            {
                "level": "caution",
                "title": "筛查负担",
                "text": f"预计每随机1例约需筛查{screening_ratio:.1f}例。入组可行性需要单独评估。",
            }
        )
    if result and result.get("trend_model") == "no_interaction":
        warnings.append(
            {
                "level": "ordinary",
                "title": "交互证据",
                "text": "未检出稳定的治疗×NIHSS交互。人群范围差异不应解释为药物在该人群更有效。",
            }
        )
    if result:
        for message in result.get("warnings_zh", []):
            if message and not any(message in item["text"] for item in warnings):
                warnings.append({"level": "caution", "title": "模型提示", "text": str(message)})
    return warnings


class DemoService:
    """In-process cache and orchestration for the validated planning engine."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self.execution_count = 0

    def clear_cache(self) -> None:
        self._cache.clear()

    def preview(self, config: dict[str, Any]) -> dict[str, Any]:
        return preview_source_support(normalize_step24a_config(config))

    def run(
        self,
        config: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started = time.perf_counter()
        normalized = normalize_step24a_config(config)
        key = config_hash(normalized)
        if key in self._cache:
            result = copy.deepcopy(self._cache[key])
            return result, {
                "cache_hit": True,
                "elapsed_seconds": time.perf_counter() - started,
                "progress_events": [],
                "execution_count": self.execution_count,
            }

        events: list[dict[str, Any]] = []

        def stage(percent: int, label: str) -> None:
            elapsed = time.perf_counter() - started
            events.append({"percent": percent, "label": label, "elapsed_seconds": elapsed})
            _emit(progress_callback, percent, label, started)

        stage(5, "正在检查参数")
        errors = validate_step24a_config(normalized)
        if errors:
            result = {
                "status": "blocked",
                "config_hash": key,
                "errors_zh": errors,
                "normalized_config": normalized,
                "warnings_ui": warning_messages(normalized, {"status": "blocked", "errors_zh": errors}),
            }
            stage(100, "参数检查未通过")
            return result, self._metadata(False, started, events)

        stage(15, "正在识别Phase II来源人群")
        preview = preview_source_support(normalized)
        if int(preview.get("eligible_n") or 0) == 0:
            result = {
                "status": "blocked",
                "config_hash": key,
                "errors_zh": ["当前参数组合在Phase II中无来源患者，无法进行数据驱动模拟，请调整条件。"],
                "normalized_config": normalized,
                "source_support": preview,
                "warnings_ui": warning_messages(normalized, preview),
                "enriched_population_pos": None,
                "bayesian_assurance": None,
            }
            stage(100, "无来源患者，已停止")
            return result, self._metadata(False, started, events)

        stage(30, "正在构建目标虚拟人群")
        generated = generate_target_population(normalized)
        requested_n = int(normalized["trial"]["total_n"])
        if len(generated) != requested_n:
            result = {
                "status": "blocked",
                "config_hash": key,
                "errors_zh": [f"目标人群生成数量异常：请求{requested_n}例，实际{len(generated)}例。"],
                "normalized_config": normalized,
            }
            stage(100, "目标人群构建失败")
            return result, self._metadata(False, started, events)

        stage(55, "正在运行Monte Carlo与Bayesian联合计算")
        self.execution_count += 1
        result = run_step24a_scenario(normalized)
        stage(95, "正在生成图表与报告数据")
        result["warnings_ui"] = warning_messages(normalized, preview, result)
        result["demo_generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        result["demo_backend_label"] = "内部验证版本"
        stage(100, "模拟完成")
        self._cache[key] = copy.deepcopy(result)
        return copy.deepcopy(result), self._metadata(False, started, events)

    def _metadata(
        self, cache_hit: bool, started: float, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "cache_hit": cache_hit,
            "elapsed_seconds": time.perf_counter() - started,
            "progress_events": events,
            "execution_count": self.execution_count,
        }


SERVICE = DemoService()


def format_pct(value: Any, signed: bool = False) -> str:
    if value is None:
        return "不可估计"
    prefix = "+" if signed and float(value) > 0 else ""
    return f"{prefix}{float(value):.1%}"


def all_population_comparison_reference(result: dict[str, Any]) -> dict[str, Any]:
    target_n = int(result.get("target_randomized_n") or 0)
    source_n = int(result.get("all_population_source_n") or 440)
    return {
        "status": "pass",
        "enriched_population_pos": result.get("all_population_pos"),
        "bayesian_assurance": result.get("all_population_bayesian_assurance"),
        "all_population_pos": result.get("all_population_pos"),
        "delta_pos": 0.0,
        "eligible_proportion": float(result.get("all_population_eligible_proportion") or 1.0),
        "estimated_screened_n": int(result.get("all_population_estimated_screened_n") or target_n),
        "eligible_n": source_n,
    }


def resolve_comparison_reference(
    result: dict[str, Any],
    saved_scenarios: list[dict[str, Any]],
    anchor_scenario_id: str | None,
) -> tuple[dict[str, Any], str, str, str | None]:
    if anchor_scenario_id:
        for item in saved_scenarios:
            if str(item.get("scenario_id")) != str(anchor_scenario_id):
                continue
            anchor_result = item.get("result") or {}
            if anchor_result.get("status") != "blocked":
                return anchor_result, str(item.get("name") or "已保存情景"), "anchor", str(anchor_scenario_id)
    return all_population_comparison_reference(result), "同设计全人群", "all_population", None


def _comparison_delta(current: Any, reference: Any) -> float | None:
    if current is None or reference is None:
        return None
    return float(current) - float(reference)


def _config_summary(result: dict[str, Any]) -> dict[str, str]:
    config = result["normalized_config"]
    step = config["step24a"]
    dose = str(config["trial"]["dose"]).replace("BZP ", "")
    return {
        "剂量": dose,
        "目标随机样本量": str(config["trial"]["total_n"]),
        "随机分配": str(config["trial"]["allocation"]),
        "缺失处理": MISSING_LABELS[config["missing_death"]["sensitivity_rule"]],
        "效应假设": EFFECT_LABELS[step["effect_assumption"]],
        "相对Phase II原始效应系数": f"{step['effect_multiplier']:.0%}",
        "基线NIHSS范围": f"{step['nihss_min']}–{step['nihss_max']}分",
        "其他条件": condition_summary_zh(step["conditions"]),
        "模拟模式": "快速探索" if config["simulation"]["n_simulations"] <= 1000 else "稳定复核",
        "模拟次数": str(config["simulation"]["n_simulations"]),
    }


def export_csv(
    result: dict[str, Any],
    comparison_reference: dict[str, Any] | None = None,
    comparison_label: str = "同设计全人群",
) -> bytes:
    summary = _config_summary(result)
    reference = comparison_reference or all_population_comparison_reference(result)
    row = {
        **summary,
        "当前情景PoS": result.get("enriched_population_pos"),
        "Bayesian保证概率": result.get("bayesian_assurance"),
        "全人群参照PoS": result.get("all_population_pos"),
        "全人群参照Bayesian保证概率": result.get("all_population_bayesian_assurance"),
        "相对全人群PoS差异": _comparison_delta(
            result.get("enriched_population_pos"), result.get("all_population_pos")
        ),
        "相对全人群保证概率差异": _comparison_delta(
            result.get("bayesian_assurance"), result.get("all_population_bayesian_assurance")
        ),
        "比较基准": comparison_label,
        "相对比较基准PoS变化": _comparison_delta(result.get("enriched_population_pos"), reference.get("enriched_population_pos")),
        "相对比较基准保证概率变化": _comparison_delta(result.get("bayesian_assurance"), reference.get("bayesian_assurance")),
        "Phase II来源人数": result.get("eligible_n"),
        "Phase II符合比例": result.get("eligible_proportion"),
        "预计筛查人数": result.get("estimated_screened_n"),
        "数据支持状态": result.get("evidence_support_status"),
        "探索性规划": True,
    }
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def export_html(
    result: dict[str, Any],
    comparison_reference: dict[str, Any] | None = None,
    comparison_label: str = "同设计全人群",
) -> bytes:
    summary = _config_summary(result)
    reference = comparison_reference or all_population_comparison_reference(result)
    reference_pos_delta = _comparison_delta(result.get("enriched_population_pos"), reference.get("enriched_population_pos"))
    reference_assurance_delta = _comparison_delta(result.get("bayesian_assurance"), reference.get("bayesian_assurance"))
    full_population_pos_delta = _comparison_delta(
        result.get("enriched_population_pos"), result.get("all_population_pos")
    )
    full_population_assurance_delta = _comparison_delta(
        result.get("bayesian_assurance"), result.get("all_population_bayesian_assurance")
    )
    values = [
        ("当前情景PoS", result.get("enriched_population_pos"), "#0f766e"),
        ("全人群参照PoS", result.get("all_population_pos"), "#3b82f6"),
        ("Bayesian保证概率", result.get("bayesian_assurance"), "#d97706"),
    ]
    bars = []
    for label, value, color in values:
        width = 0 if value is None else max(0, min(100, float(value) * 100))
        bars.append(
            f'<div class="bar-row"><span>{html.escape(label)}</span>'
            f'<div class="track"><i style="width:{width:.1f}%;background:{color}"></i></div>'
            f'<strong>{format_pct(value)}</strong></div>'
        )
    params = "".join(
        f"<tr><th>{html.escape(key)}</th><td>{html.escape(value)}</td></tr>"
        for key, value in summary.items()
    )
    warning_rows = "".join(
        f'<li class="{html.escape(item["level"])}"><b>{html.escape(item["title"])}</b>：'
        f'{html.escape(item["text"])}</li>'
        for item in result.get("warnings_ui", [])
    ) or "<li>当前未触发额外预警。</li>"
    generated = html.escape(result.get("demo_generated_at") or datetime.now().astimezone().isoformat(timespec="seconds"))
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>BZP探索情景报告</title>
<style>
body{{font-family:"Microsoft YaHei",Arial,sans-serif;color:#172033;background:#f7f8fa;margin:0}}
main{{max-width:900px;margin:0 auto;padding:36px}} h1{{font-size:28px;margin:0 0 8px}} h2{{font-size:19px;margin-top:30px}}
.meta,.note{{color:#5d6675}} .panel{{background:#fff;border:1px solid #dfe3e8;border-radius:6px;padding:20px;margin:16px 0}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}} .metric{{border-left:4px solid #0f766e;padding:10px 14px;background:#f3f7f7}}
.metric b{{display:block;font-size:24px;margin-top:6px}} table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:9px;border-bottom:1px solid #e6e8eb}}
th{{width:32%;color:#4b5563}} .bar-row{{display:grid;grid-template-columns:160px 1fr 70px;gap:12px;align-items:center;margin:13px 0}}
.track{{height:14px;background:#e7eaee}} .track i{{display:block;height:100%}} li{{margin:8px 0}} .strong,.block{{color:#b42318}} .caution{{color:#a15c00}}
footer{{border-top:1px solid #dfe3e8;margin-top:34px;padding-top:16px;color:#5d6675;font-size:13px}}
@media(max-width:650px){{main{{padding:20px}}.metrics{{grid-template-columns:1fr}}.bar-row{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>BZP Phase III规划探索情景报告</h1><div class="meta">生成时间：{generated}</div>
<p class="note">{DISCLAIMER}</p>
<section class="metrics">
<div class="metric">当前情景PoS<b>{format_pct(result.get("enriched_population_pos"))}</b></div>
<div class="metric">全人群参照PoS<b>{format_pct(result.get("all_population_pos"))}</b></div>
<div class="metric">相对全人群PoS差异<b>{format_pct(full_population_pos_delta, signed=True)}</b></div>
<div class="metric">Bayesian保证概率<b>{format_pct(result.get("bayesian_assurance"))}</b></div>
</section>
<section class="panel"><h2>情景参数</h2><table>{params}</table></section>
<section class="panel"><h2>核心结果</h2>{''.join(bars)}
<table><tr><th>比较基准</th><td>{html.escape(comparison_label)}</td></tr>
<tr><th>当前Bayesian保证概率</th><td>{format_pct(result.get("bayesian_assurance"))}</td></tr>
<tr><th>全人群参照Bayesian保证概率</th><td>{format_pct(result.get("all_population_bayesian_assurance"))}</td></tr>
<tr><th>相对全人群PoS差异</th><td>{format_pct(full_population_pos_delta, signed=True)}</td></tr>
<tr><th>相对全人群保证概率差异</th><td>{format_pct(full_population_assurance_delta, signed=True)}</td></tr>
<tr><th>相对当前比较基准PoS变化</th><td>{format_pct(reference_pos_delta, signed=True)}</td></tr>
<tr><th>相对当前比较基准保证概率变化</th><td>{format_pct(reference_assurance_delta, signed=True)}</td></tr>
<tr><th>Phase II来源人数</th><td>{result.get("eligible_n", "不可估计")}</td></tr>
<tr><th>符合比例</th><td>{format_pct(result.get("eligible_proportion"))}</td></tr>
<tr><th>预计筛查人数</th><td>{result.get("estimated_screened_n", "不可估计")}</td></tr>
<tr><th>数据支持状态</th><td>{html.escape(str(result.get("evidence_support_status", "不可估计")))}</td></tr></table></section>
<section class="panel"><h2>当前预警</h2><ul>{warning_rows}</ul></section>
<section class="panel"><h2>如何理解</h2>
<p>PoS用于比较当前假设下不同设计情景的相对变化；Bayesian保证概率额外考虑效应不确定性。无论是否设置锚点，报告均单独保留相对同设计全人群的PoS和保证概率差异。符合比例与预计筛查人数用于评估入组负担。</p>
<p>本报告未检验最终方案、样本量、成功标准、多重性及缺失数据规则是否已锁定，因此不能作为Ⅲ期成功概率承诺。</p></section>
<section class="panel"><h2>方法与限制</h2>
<p>结果使用已完成内部校准和一致性验证的探索性模拟引擎。Day90前死亡按mRS 6处理；当前计算不合并历史二期研究数据。默认保守效应采用Phase II观察风险差的50%；NIHSS范围和其他条件属于探索性规划。</p>
<p>来源稀疏、零单元格或模型外推会降低稳定性。未检出稳定治疗×NIHSS交互时，不应把范围差异解释为药物对该人群更有效。</p></section>
<footer>仅含情景级汇总，不含患者级记录或患者标识。探索性 / 规划阶段。</footer>
</main></body></html>"""
    return document.encode("utf-8")


def result_for_session(result: dict[str, Any]) -> dict[str, Any]:
    """Keep only scenario-level content used by the UI."""
    allowed = {
        "scenario_id", "config_hash", "status", "target_randomized_n", "generated_randomized_n",
        "all_population_pos", "all_population_bayesian_assurance", "enriched_population_pos", "delta_pos", "bayesian_assurance",
        "all_population_source_n", "all_population_eligible_proportion", "all_population_estimated_screened_n",
        "eligible_n", "selected_dose_n", "placebo_n", "eligible_proportion",
        "estimated_screened_n", "evidence_support_status", "nihss_interval_zh",
        "condition_summary_zh", "candidate_direction_label", "warnings_ui", "warnings_zh",
        "normalized_config", "demo_generated_at", "demo_backend_label", "trend_model",
        "required_warning_zh", "phase3_alignment_disclaimer_zh", "extrapolation_flag",
        "sensitivity_extrapolated_pos", "sensitivity_extrapolated_assurance", "errors_zh",
    }
    return {key: copy.deepcopy(value) for key, value in result.items() if key in allowed}


def canonical_json(config: dict[str, Any]) -> str:
    return json.dumps(normalize_step24a_config(config), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
