from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm

from ..models.outcome_models import effective_effect, get_effect_source

ROOT = Path(__file__).resolve().parents[2]
PRIOR_REGISTRY = ROOT / "outputs/step19_dynamic_chinese_mvp/model_assets/bayesian_prior_registry.csv"


def _prior(name: str, source: dict[str, Any], mean_effect: float) -> dict[str, float | str]:
    with PRIOR_REGISTRY.open(encoding="utf-8-sig", newline="") as handle:
        row = next((item for item in csv.DictReader(handle) if item["prior_name"] == name), None)
    if row is None:
        raise ValueError(f"未知贝叶斯先验：{name}")
    source_se = float(source.get("uncertainty_estimate") or 0.065)
    return {"name": name, "mean": mean_effect * float(row["mean_multiplier"]), "sd": max(source_se * float(row["uncertainty_multiplier"]), abs(mean_effect) * 0.35, 0.015), "description_zh": row["description_zh"]}


def _trial_se(config: dict[str, Any], source: dict[str, Any], true_effect: float) -> float:
    total_n = int(config["trial"]["total_n"])
    active_n = total_n // 2 if config["trial"]["allocation"] == "1:1" else int(round(total_n * 2 / 3))
    control_n = total_n - active_n
    endpoint = config["endpoint"]["primary_endpoint"]
    if endpoint in {"day90_mrs01", "day90_mrs02", "day14_nihss_response"}:
        pc = float(source["control_outcome"]); pt = float(np.clip(pc + true_effect, 0.001, 0.999))
        return float(np.sqrt(pt * (1 - pt) / active_n + pc * (1 - pc) / control_n))
    if endpoint == "day90_mrs_ordinal":
        return float(source["uncertainty_estimate"]) * np.sqrt(float(source.get("source_n") or 219) / total_n)
    return float(source["residual_sd"]) * np.sqrt(1 / active_n + 1 / control_n) * 0.78


def run_bayesian_assurance(config: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter(); source = get_effect_source(config)
    mean_effect = effective_effect(source, config["effect"]["shrinkage"])
    prior_name = config["effect"].get("prior_type") or "base"
    if prior_name == "none": prior_name = "base"
    prior = _prior(prior_name, source, mean_effect)
    nsim = int(config["simulation"]["n_simulations"]); rng = np.random.default_rng(int(config["simulation"]["random_seed"]) + 7919)
    true_effects = rng.normal(float(prior["mean"]), float(prior["sd"]), size=nsim)
    favorable_sign = -1.0 if config["endpoint"]["primary_endpoint"] == "day14_nihss_change" else 1.0
    likelihood_se = _trial_se(config, source, float(prior["mean"])); observed = true_effects + rng.normal(0, likelihood_se, size=nsim)
    prior_var = float(prior["sd"]) ** 2; like_var = likelihood_se**2; posterior_var = 1 / (1 / prior_var + 1 / like_var)
    posterior_mean = posterior_var * (float(prior["mean"]) / prior_var + observed / like_var); posterior_sd = np.sqrt(posterior_var)
    posterior_favorable = norm.cdf(favorable_sign * posterior_mean / posterior_sd)
    threshold = float(config["success_criterion"].get("bayesian_threshold", 0.975)); success = posterior_favorable > threshold
    assurance = float(np.mean(success)); mc_se = float(np.sqrt(assurance * (1 - assurance) / nsim))
    return {"bayesian_assurance": assurance, "assurance_mc_standard_error": mc_se, "prior_summary": {"prior_name": prior_name, "prior_mean_effect": float(prior["mean"]), "prior_standard_deviation": float(prior["sd"]), "decision_threshold": threshold, "threshold_status_zh": "分析者设定，尚未获SAP确认", "description_zh": prior["description_zh"], "posterior_probability_median": float(np.median(posterior_favorable)), "posterior_probability_q05": float(np.quantile(posterior_favorable, 0.05)), "posterior_probability_q95": float(np.quantile(posterior_favorable, 0.95))}, "runtime_seconds": time.perf_counter() - started, "n_simulations": nsim, "random_seed": int(config["simulation"]["random_seed"]), "model_source": source["source_file"], "model_version": source["model_version"]}
