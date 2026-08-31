from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..analysis.binary_analysis import binary_z
from ..analysis.hierarchy import hierarchy_success
from ..analysis.success_criteria import frequentist_success, pos_summary
from ..models.outcome_models import effective_effect, get_effect_source
from .binary_endpoint import simulate_binary_trials
from .continuous_endpoint import simulate_continuous_trials
from .joint_endpoint import supportive_success_from_primary_z
from .missing_death import summarize_missing_death
from .ordinal_endpoint import simulate_ordinal_trials

BINARY_ENDPOINTS = {"day90_mrs01", "day90_mrs02", "day14_nihss_response"}


def _arm_sizes(total_n: int, allocation: str) -> tuple[int, int]:
    active = int(round(total_n * 2 / 3)) if allocation == "2:1" else total_n // 2
    return active, total_n - active


def _supportive_mean_z(config: dict[str, Any], n_active: int, n_control: int) -> float:
    support_cfg = {key: dict(value) if isinstance(value, dict) else value for key, value in config.items()}
    support_cfg["endpoint"] = dict(config["endpoint"])
    support_cfg["endpoint"]["primary_endpoint"] = config["endpoint"].get("supportive_endpoint", "day14_nihss_response")
    source = get_effect_source(support_cfg)
    effect = effective_effect(source, config["effect"]["shrinkage"])
    if support_cfg["endpoint"]["primary_endpoint"] == "day14_nihss_change":
        se = float(source["residual_sd"]) * np.sqrt(1 / n_active + 1 / n_control) * 0.78
        return abs(effect) / se
    control = float(source["control_outcome"])
    treatment = float(np.clip(control + effect, 0.001, 0.999))
    se = np.sqrt(treatment * (1 - treatment) / n_active + control * (1 - control) / n_control)
    return effect / se


def run_monte_carlo(config: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    rng = np.random.default_rng(int(config["simulation"]["random_seed"]))
    nsim = int(config["simulation"]["n_simulations"])
    endpoint = config["endpoint"]["primary_endpoint"]
    source = get_effect_source(config)
    effect = effective_effect(source, config["effect"]["shrinkage"])
    n_active, n_control = _arm_sizes(int(config["trial"]["total_n"]), config["trial"]["allocation"])
    method = config["success_criterion"]["analysis_method"]
    control = source["control_outcome"]
    treatment = None

    if endpoint in BINARY_ENDPOINTS:
        rd, se, p_active, p_control = simulate_binary_trials(rng, nsim, n_active, n_control, float(control), effect)
        primary_z = binary_z(rd, se, method)
        estimate_mean = float(np.mean(rd))
        control = float(np.mean(p_control))
        treatment = float(np.mean(p_active))
        effect_scale = "风险差"
    elif endpoint == "day90_mrs_ordinal":
        source_n = max(float(source.get("source_n") or 219), 1)
        trial_se = float(source["uncertainty_estimate"]) * np.sqrt(source_n / (n_active + n_control))
        estimates, primary_z = simulate_ordinal_trials(rng, nsim, effect, trial_se)
        estimate_mean = float(np.mean(estimates))
        effect_scale = "共同优势比的对数"
    elif endpoint == "day14_nihss_change":
        trial_se = float(source["residual_sd"]) * np.sqrt(1 / n_active + 1 / n_control) * 0.78
        estimates, primary_z = simulate_continuous_trials(rng, nsim, effect, trial_se)
        estimate_mean = float(np.mean(estimates))
        treatment = float(control + estimate_mean)
        effect_scale = "NIHSS分值差"
    else:
        raise ValueError(f"不支持的终点：{endpoint}")

    primary_success = frequentist_success(primary_z, config["success_criterion"].get("pvalue_alpha", 0.05))
    supportive_mean_z = _supportive_mean_z(config, n_active, n_control)
    supportive_success = supportive_success_from_primary_z(rng, primary_z, supportive_mean_z)
    formal_success, joint_success = hierarchy_success(primary_success, supportive_success, config["endpoint"]["endpoint_hierarchy"])
    formal_pos, mc_se, mc_ci = pos_summary(formal_success)
    supportive_pos, supportive_se, _ = pos_summary(supportive_success)
    precision_threshold = float(config["simulation"].get("mc_se_threshold", 0.01))
    return {
        "formal_pos": formal_pos,
        "mc_standard_error": mc_se,
        "mc_confidence_interval": mc_ci,
        "control_outcome": float(control) if control is not None else None,
        "treatment_outcome": treatment,
        "assumed_effect": effect,
        "effect_scale": effect_scale,
        "endpoint_statistics": {"mean_estimate": estimate_mean, "mean_z": float(np.mean(primary_z)), "n_active": n_active, "n_control": n_control, "success_rule_zh": "双侧95%置信区间下限大于0（方向按终点定义）"},
        "supportive_evidence": {"endpoint": config["endpoint"].get("supportive_endpoint"), "positive_probability": supportive_pos, "mc_standard_error": supportive_se, "formal_primary_pos_unchanged": config["endpoint"]["endpoint_hierarchy"] == "mrs_primary_nihss_supportive"},
        "joint_success_probability": float(np.mean(joint_success)),
        "missing_death_summary": summarize_missing_death(config),
        "precision_status": "达标" if mc_se <= precision_threshold else "需提高模拟次数",
        "runtime_seconds": time.perf_counter() - started,
        "n_simulations": nsim,
        "random_seed": int(config["simulation"]["random_seed"]),
        "model_source": source["source_file"],
        "model_version": source["model_version"],
    }
