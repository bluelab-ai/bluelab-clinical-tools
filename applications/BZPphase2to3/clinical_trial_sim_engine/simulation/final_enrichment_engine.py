from __future__ import annotations

import copy
import hashlib
import json
import math
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from scipy.stats import norm

from ..config_loader import deep_merge, load_default_config
from ..enrichment.final_condition_builder import FEATURES, condition_mask, condition_summary_zh, migrate_removed_conditions, normalize_conditions
from ..models.final_level_interactions import OUTCOMES, condition_model, population
from ..models.outcome_models import effective_effect, get_effect_source


WARNING = "本结果用于候选Ⅲ期入组人群的探索性比较。多条件场景使用单变量交互贡献加和近似，PoS取决于Ⅱ期来源数据、所选富集条件及模型假设。"
BASELINE_CACHE: dict[str, dict] = {}
DEFAULT_CONFIG = load_default_config()
SAFE_COLUMNS = ["dose", "site_id", "site_name", "age", "sex_male", "baseline_nihss", "baseline_mrs", "ocsp_taci", "ocsp_paci", "ocsp_laci", "ocsp_poci", "onset_within_24h", "previous_stroke_corrected", "prestroke_mrs_corrected", "limb_motor_sum", "bmi", "mrs01_locf", "mrs01_mi_probability", "mrs01_nonresponder"]


def normalize_final_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = config or {}
    base = deep_merge(DEFAULT_CONFIG, raw)
    base["trial"]["population"] = "phase2_2026_allcomers"
    base["trial"]["analysis_population"] = "FAS"
    base["effect"]["shrinkage"] = .5
    base["effect"]["borrowing_weight_2022"] = 0
    final = {"conditions": [], "center_mode": "all", "selected_center_ids": [], "effect_multiplier": 1.0, "interaction_retention": .25, "effect_mode": "interaction"}
    final.update(raw.get("final_demo", {}))
    migrated, migration_warnings = migrate_removed_conditions(final.get("conditions"))
    existing_warnings = list(final.get("migration_warnings_zh", []))
    final["conditions"] = normalize_conditions(migrated)
    combined_warnings = list(dict.fromkeys(existing_warnings + migration_warnings))
    if combined_warnings:
        final["migration_warnings_zh"] = combined_warnings
    else:
        final.pop("migration_warnings_zh", None)
    final["selected_center_ids"] = sorted({str(x).zfill(2) for x in final.get("selected_center_ids", [])})
    base["final_demo"] = final
    return base


def config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(normalize_final_config(config), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _dose(config):
    return config["trial"]["dose"].replace("BZP ", "").replace(" BID", "")


def _validate(config):
    final = config["final_demo"]
    errors = []
    if not .5 <= float(final["effect_multiplier"]) <= 1.5:
        errors.append("相对当前模型基准效应的假设系数必须在50%至150%之间。")
    if not 0 <= float(final["interaction_retention"]) <= 1:
        errors.append("亚组交互效应保留比例必须在0%至100%之间。")
    if final["effect_mode"] not in {"interaction", "composition_only"}:
        errors.append("未知治疗效应处理方式。")
    known = set(population().site_id.astype(str).str.zfill(2))
    centers = final["selected_center_ids"]
    if any(x not in known for x in centers):
        errors.append("所选中心不在结构化中心注册表中。")
    if final["center_mode"] == "single" and len(centers) != 1:
        errors.append("单中心模式必须选择一个中心。")
    if final["center_mode"] == "multiple" and len(centers) < 2:
        errors.append("多中心模式至少选择两个中心。")
    return errors


def _center_source(config):
    data = population()
    final = config["final_demo"]
    centers = [] if final["center_mode"] == "all" else final["selected_center_ids"]
    return data if not centers else data[data.site_id.astype(str).str.zfill(2).isin(centers)]


def eligible_source(config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized = normalize_final_config(config)
    center = _center_source(normalized)
    mask = condition_mask(center, normalized["final_demo"]["conditions"])
    return center, center.loc[mask].copy()


def _base_effect(config):
    source_config = copy.deepcopy(config)
    source_config.pop("final_demo", None)
    source = get_effect_source(source_config)
    pc = float(source["control_outcome"])
    pt = float(np.clip(pc + effective_effect(source, .5), .001, .999))
    return source, pc, float(logit(pt)-logit(pc))


def _support(config, center, eligible):
    outcome = OUTCOMES[config["missing_death"]["sensitivity_rule"]]
    dose = _dose(config)
    active = eligible[eligible.dose.eq(dose)]
    control = eligible[eligible.dose.eq("placebo")]
    active_events = float(active[outcome].sum(skipna=True))
    control_events = float(control[outcome].sum(skipna=True))
    prevalence = len(eligible)/len(center) if len(center) else 0
    zero_cells = int(sum(x <= 1e-12 for x in [active_events, len(active)-active_events, control_events, len(control)-control_events])) if len(active) and len(control) else 4
    if len(eligible) == 0:
        status, warning = "无Ⅱ期数据", "所选条件组合在来源数据中没有合格病例。"
    elif len(active) == 0 or len(control) == 0:
        status, warning = "不可估计", "合格来源子集缺少所选剂量组或安慰剂组。"
    elif len(active) < 3 or len(control) < 3:
        status, warning = "不可估计", "合格来源子集的所选剂量组或安慰剂组少于3例。"
    elif len(eligible) < 40 or len(active) < 10 or len(control) < 10:
        status, warning = "数据有限", "合格来源子集样本有限。"
    else:
        status, warning = "可模拟", ""
    return {"center_source_n": len(center), "eligible_n": len(eligible), "eligible_proportion": prevalence, "selected_dose_n": len(active), "placebo_n": len(control), "treatment_responders": active_events, "placebo_responders": control_events, "treatment_nonresponders": len(active)-active_events, "placebo_nonresponders": len(control)-control_events, "missing_endpoint_n": int(eligible[outcome].isna().sum()), "zero_cell_count": zero_cells, "data_support_status": status, "support_warning_zh": warning}


def preview_source_support(config: dict[str, Any]) -> dict:
    normalized = normalize_final_config(config)
    errors = _validate(normalized)
    if errors:
        return {"status": "blocked", "errors_zh": errors}
    center, eligible = eligible_source(normalized)
    support = _support(normalized, center, eligible)
    target = int(normalized["trial"]["total_n"])
    support["target_randomized_n"] = target
    support["estimated_screened_n"] = target/support["eligible_proportion"] if support["eligible_proportion"] > 0 else None
    support["condition_summary_zh"] = condition_summary_zh(normalized["final_demo"]["conditions"])
    return support


def generate_eligible_population(config: dict[str, Any], seed: int | None = None) -> pd.DataFrame:
    normalized = normalize_final_config(config)
    _, eligible = eligible_source(normalized)
    n = int(normalized["trial"]["total_n"])
    if eligible.empty:
        return pd.DataFrame(columns=SAFE_COLUMNS + ["randomized_arm"])
    rng = np.random.default_rng(int(seed if seed is not None else normalized["simulation"]["random_seed"]))
    sampled = eligible.iloc[rng.integers(0, len(eligible), size=n)][SAFE_COLUMNS].reset_index(drop=True).copy()
    allocation = normalized["trial"]["allocation"]
    n_active = int(round(n*2/3)) if allocation == "2:1" else n//2
    arms = np.array(["试验组"]*n_active + ["安慰剂组"]*(n-n_active), dtype=object)
    rng.shuffle(arms)
    sampled["randomized_arm"] = arms
    return sampled


def _simulate(seed, nsim, total_n, allocation, pc, pt):
    rng = np.random.default_rng(seed)
    n1 = int(round(total_n*2/3)) if allocation == "2:1" else total_n//2
    n0 = total_n-n1
    a = rng.binomial(n1, pt, nsim); c = rng.binomial(n0, pc, nsim)
    rd = a/n1-c/n0
    se = np.sqrt(np.maximum((a/n1)*(1-a/n1)/n1+(c/n0)*(1-c/n0)/n0, 1e-12))
    success = rd/se > norm.ppf(.975)
    pos = float(success.mean()); mcse = float(math.sqrt(pos*(1-pos)/nsim))
    return pos, mcse


def _assurance(seed, nsim, total_n, allocation, pc, effect, uncertainty):
    rng = np.random.default_rng(seed+7919)
    n1 = int(round(total_n*2/3)) if allocation == "2:1" else total_n//2; n0 = total_n-n1
    true = rng.normal(effect, max(float(uncertainty), .05), nsim)
    pt = expit(logit(pc)+true); se = np.sqrt(pt*(1-pt)/n1+pc*(1-pc)/n0)
    observed = pt-pc+rng.normal(0, se)
    success = observed/se > norm.ppf(.975)
    assurance = float(success.mean())
    return assurance, float(math.sqrt(assurance*(1-assurance)/nsim))


def _baseline_key(config):
    design = {"dose": _dose(config), "n": config["trial"]["total_n"], "allocation": config["trial"]["allocation"], "missing": config["missing_death"]["sensitivity_rule"], "multiplier": config["final_demo"]["effect_multiplier"], "center_mode": config["final_demo"]["center_mode"], "centers": config["final_demo"]["selected_center_ids"], "seed": config["simulation"]["random_seed"], "nsim": config["simulation"]["n_simulations"]}
    return hashlib.sha256(json.dumps(design, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def shared_baseline(config):
    key = _baseline_key(config)
    if key in BASELINE_CACHE:
        return BASELINE_CACHE[key]
    source, base_pc, base_log_or = _base_effect(config)
    center = _center_source(config)
    outcome = OUTCOMES[config["missing_death"]["sensitivity_rule"]]
    observed_pc = center.loc[center.dose.eq("placebo"), outcome].mean()
    pc = base_pc if len(center) == len(population()) else float(np.clip(.5*base_pc+.5*(observed_pc if pd.notna(observed_pc) else base_pc), .001, .999))
    effect = base_log_or*float(config["final_demo"]["effect_multiplier"])
    pt = float(expit(logit(pc)+effect))
    nsim, seed, n, allocation = int(config["simulation"]["n_simulations"]), int(config["simulation"]["random_seed"]), int(config["trial"]["total_n"]), config["trial"]["allocation"]
    mc, mcse = _simulate(seed, nsim, n, allocation, pc, pt)
    bayes, bayes_se = _assurance(seed, nsim, n, allocation, pc, effect, source.get("uncertainty_estimate") or .07)
    result = {"cache_key": key, "monte_carlo_pos": mc, "bayesian_assurance": bayes, "control_probability": pc, "treatment_probability": pt, "effect_log_or": effect, "mc_standard_error": mcse, "assurance_standard_error": bayes_se}
    BASELINE_CACHE[key] = result
    return result


def _interaction_components(config):
    final = config["final_demo"]
    if final["effect_mode"] == "composition_only":
        return [], True, []
    dose, missing, retention = _dose(config), config["missing_death"]["sensitivity_rule"], float(final["interaction_retention"])
    components, usable, warnings = [], True, []
    for condition in final["conditions"]:
        model = condition_model(str(condition["feature"]), list(condition["levels"]), dose, missing)
        raw = float(model["coefficient_used"]) if pd.notna(model["coefficient_used"]) else None
        contribution = raw*retention*(1-float(model["feature_prevalence"])) if raw is not None and bool(model["usable_interaction"]) else None
        warning_text = "" if pd.isna(model["warning_zh"]) else str(model["warning_zh"])
        item = {"feature": condition["feature"], "feature_label_zh": FEATURES[str(condition["feature"])].label_zh, "levels": condition["levels"], "raw_interaction": raw, "feature_prevalence": model["feature_prevalence"], "interaction_retention": retention, "retained_centered_contribution": contribution, "coefficient_source": model["coefficient_source"], "data_support_status": model["data_support_status"], "usable_interaction": bool(model["usable_interaction"]), "warning_zh": warning_text}
        components.append(item)
        if not item["usable_interaction"]:
            usable = False
        if item["warning_zh"]:
            warnings.append(f"{item['feature_label_zh']}：{item['warning_zh']}")
    return components, usable, warnings


def _na_result(config, key, support, baseline, warnings, reason):
    return {"scenario_id": f"BZP23R-{key[:10].upper()}", "config_hash": key, "status": "pass_with_warnings", "evidence_support_status": support["data_support_status"], "target_randomized_n": int(config["trial"]["total_n"]), "generated_randomized_n": 0, "all_population_pos": baseline["monte_carlo_pos"], "enriched_population_pos": None, "delta_pos": None, "monte_carlo_pos": None, "bayesian_assurance": None, "eligible_n": support["eligible_n"], "eligible_proportion": support["eligible_proportion"], "estimated_screened_n": None if support["eligible_proportion"] == 0 else int(math.ceil(int(config["trial"]["total_n"])/support["eligible_proportion"])), "candidate_direction_label": "不可估计", "condition_summary_zh": condition_summary_zh(config["final_demo"]["conditions"]), "warnings_zh": list(dict.fromkeys(warnings+[reason])), "required_warning_zh": WARNING, "normalized_config": config, "exploratory": True, "death_as_mrs6": True, "borrowing_weight_2022": 0, "model_version": "step23r-final-v1.0", "source_support": support, "shared_baseline": baseline, "interaction_components": []}


def run_final_scenario(scenario_config: dict[str, Any]) -> dict[str, Any]:
    config = normalize_final_config(scenario_config); key = config_hash(config); errors = _validate(config)
    if errors:
        return {"scenario_id": f"BZP23R-{key[:10].upper()}", "config_hash": key, "status": "blocked", "errors_zh": errors, "exploratory": True}
    center, eligible = eligible_source(config); support = _support(config, center, eligible); baseline = shared_baseline(config)
    warnings = list(config["final_demo"].get("migration_warnings_zh", []))
    if support["support_warning_zh"]:
        warnings.append(support["support_warning_zh"])
    # Explicitly unsupported levels cannot fall back to a pooled effect.
    if support["eligible_n"] == 0:
        return _na_result(config, key, support, baseline, warnings, "所选条件无Ⅱ期数据，未生成虚拟患者，PoS与保证概率返回NA。")
    if support["selected_dose_n"] == 0 or support["placebo_n"] == 0 or support["selected_dose_n"] < 3 or support["placebo_n"] < 3:
        return _na_result(config, key, support, baseline, warnings, "所选条件缺少充分的候选剂量或安慰剂来源，未使用合并默认PoS。")
    components, interactions_usable, interaction_warnings = _interaction_components(config); warnings += interaction_warnings
    if config["final_demo"]["effect_mode"] == "interaction" and not interactions_usable:
        return _na_result(config, key, support, baseline, warnings, "交互效应在预设惩罚后仍不可估计；交互调整PoS返回NA。")
    generated = generate_eligible_population(config)
    if len(generated) != int(config["trial"]["total_n"]):
        return _na_result(config, key, support, baseline, warnings, "未能直接生成目标随机入组N，情景停止。")
    source, base_pc, base_log_or = _base_effect(config)
    outcome = OUTCOMES[config["missing_death"]["sensitivity_rule"]]
    observed_pc = eligible.loc[eligible.dose.eq("placebo"), outcome].mean()
    pc = float(np.clip(.5*base_pc+.5*(observed_pc if pd.notna(observed_pc) else base_pc), .001, .999)) if config["final_demo"]["conditions"] or len(center) != len(population()) else base_pc
    total_interaction = sum(float(x["retained_centered_contribution"]) for x in components if x["retained_centered_contribution"] is not None)
    effect = base_log_or*float(config["final_demo"]["effect_multiplier"])+total_interaction
    pt = float(expit(logit(pc)+effect))
    nsim, seed, n, allocation = int(config["simulation"]["n_simulations"]), int(config["simulation"]["random_seed"]), int(config["trial"]["total_n"]), config["trial"]["allocation"]
    mc, mcse = _simulate(seed, nsim, n, allocation, pc, pt)
    bayes, bayes_se = _assurance(seed, nsim, n, allocation, pc, effect, source.get("uncertainty_estimate") or .07)
    delta = mc-baseline["monte_carlo_pos"]
    severe = support["data_support_status"] in {"不可估计", "无Ⅱ期数据"} or any(x["data_support_status"] == "模型不稳定" for x in components)
    label = "结果波动较大" if severe else ("PoS变化较小" if abs(delta) < .03 else ("优先探索" if delta >= .10 and support["eligible_proportion"] >= .10 else ("可考虑" if delta >= .03 else "结果波动较大")))
    estimated = int(math.ceil(n/support["eligible_proportion"])) if support["eligible_proportion"] > 0 else None
    return {"scenario_id": f"BZP23R-{key[:10].upper()}", "config_hash": key, "status": "pass_with_warnings" if warnings else "pass", "evidence_support_status": "模型不稳定" if any(x["data_support_status"] == "模型不稳定" for x in components) else support["data_support_status"], "target_randomized_n": n, "generated_randomized_n": len(generated), "all_population_pos": baseline["monte_carlo_pos"], "all_population_bayesian_assurance": baseline["bayesian_assurance"], "enriched_population_pos": mc, "delta_pos": delta, "monte_carlo_pos": mc, "mc_standard_error": mcse, "bayesian_assurance": bayes, "assurance_standard_error": bayes_se, "eligible_n": support["eligible_n"], "eligible_proportion": support["eligible_proportion"], "estimated_screened_n": estimated, "screening_burden_label_zh": "基于Ⅱ期人群构成估算的筛查负担", "candidate_direction_label": label, "condition_summary_zh": condition_summary_zh(config["final_demo"]["conditions"]), "control_probability": pc, "treatment_probability": pt, "risk_difference": pt-pc, "odds_ratio": math.exp(effect), "base_step22_log_or": base_log_or, "effect_multiplier": float(config["final_demo"]["effect_multiplier"]), "interaction_retention": float(config["final_demo"]["interaction_retention"]), "total_interaction_contribution": total_interaction, "final_subgroup_log_or": effect, "interaction_components": components, "multifeature_approximation": len(components) > 1, "generation_method": "合格来源子集整行经验重抽样", "all_generated_conditions_satisfied": bool(condition_mask(generated, config["final_demo"]["conditions"]).all()), "source_support": support, "shared_baseline": baseline, "warnings_zh": list(dict.fromkeys(warnings)), "required_warning_zh": WARNING, "normalized_config": config, "exploratory": True, "death_as_mrs6": True, "borrowing_weight_2022": 0, "model_version": "step23r-final-v1.0"}
