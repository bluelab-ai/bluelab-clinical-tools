from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from ..enrichment.final_condition_builder import condition_mask


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "clinical_trial_sim_engine/assets/private/step22_phase2_2026_population.parquet"
REGISTRY = ROOT / "clinical_trial_sim_engine/assets/private/step23r_level_interactions.csv"
OUTCOMES = {"death6_locf_like": "mrs01_locf", "death6_multiple_imputation": "mrs01_mi_probability", "death6_conservative_nonresponder": "mrs01_nonresponder", "observed_available_case": "mrs01_observed"}


@lru_cache(maxsize=1)
def population() -> pd.DataFrame:
    return pd.read_parquet(ASSET)


def fit_condition_interaction(feature: str, levels: list[str], dose: str, missing_method: str, frame: pd.DataFrame | None = None) -> dict:
    data = (frame if frame is not None else population()).copy()
    outcome = OUTCOMES[missing_method]
    pair = data[data.dose.isin([dose, "placebo"])].copy()
    pair["treatment"] = pair.dose.eq(dose).astype(float)
    pair["selected"] = condition_mask(pair, [{"feature": feature, "levels": levels}]).astype(float)
    model_data = pair[[outcome, "treatment", "selected"]].dropna().copy()
    model_data["interaction"] = model_data.treatment * model_data.selected
    selected = model_data[model_data.selected.eq(1)]
    active = selected[selected.treatment.eq(1)]
    control = selected[selected.treatment.eq(0)]
    selected_n, active_n, control_n = len(selected), len(active), len(control); complement_n = len(model_data)-selected_n
    active_events = float(active[outcome].sum())
    control_events = float(control[outcome].sum())
    zero_cells = int(sum(value <= 1e-12 for value in [active_events, active_n-active_events, control_events, control_n-control_events]))
    base = {
        "feature": feature, "levels_json": json.dumps(sorted(levels), ensure_ascii=False), "dose": dose, "missing_method": missing_method,
        "source_n": len(model_data), "complement_n": complement_n, "eligible_n": selected_n, "selected_dose_n": active_n, "placebo_n": control_n,
        "treatment_responders": active_events, "placebo_responders": control_events,
        "treatment_nonresponders": active_n-active_events, "placebo_nonresponders": control_n-control_events,
        "zero_cell_count": zero_cells, "feature_prevalence": float(model_data.selected.mean()) if len(model_data) else 0.0,
        "standard_converged": False, "standard_beta_t": np.nan, "standard_beta_x": np.nan, "standard_beta_tx": np.nan,
        "standard_interaction_se": np.nan, "penalized_beta_t": np.nan, "penalized_beta_x": np.nan, "penalized_beta_tx": np.nan,
        "penalized_method": "ridge logistic, alpha=0.01", "coefficient_used": np.nan, "coefficient_source": "none",
        "data_support_status": "不可估计", "usable_interaction": False, "warning_zh": "",
    }
    if selected_n == 0:
        return base | {"data_support_status": "无Ⅱ期数据", "warning_zh": "所选水平在Phase2_2026 FAS中无受试者。"}
    if active_n == 0 or control_n == 0:
        return base | {"data_support_status": "不可估计", "warning_zh": "所选水平缺少候选剂量组或安慰剂组来源病例。"}
    if active_n < 3 or control_n < 3:
        return base | {"data_support_status": "不可估计", "warning_zh": "所选水平候选剂量组或安慰剂组少于3例。"}
    if complement_n < 3:
        return base | {"data_support_status": "不可估计", "warning_zh": "所选水平组合的模型补集少于3例，无法识别交互对比。"}
    X = sm.add_constant(model_data[["treatment", "selected", "interaction"]], has_constant="add").astype(float)
    y = model_data[outcome].astype(float)
    try:
        standard = sm.GLM(y, X, family=sm.families.Binomial()).fit(maxiter=300)
        base.update({"standard_converged": bool(standard.converged), "standard_beta_t": float(standard.params["treatment"]), "standard_beta_x": float(standard.params["selected"]), "standard_beta_tx": float(standard.params["interaction"]), "standard_interaction_se": float(standard.bse["interaction"])})
    except Exception:
        standard = None
    try:
        penalized = sm.GLM(y, X, family=sm.families.Binomial()).fit_regularized(alpha=.01, L1_wt=0, maxiter=500)
        base.update({"penalized_beta_t": float(penalized.params["treatment"]), "penalized_beta_x": float(penalized.params["selected"]), "penalized_beta_tx": float(penalized.params["interaction"])})
    except Exception:
        penalized = None
    unstable = selected_n < 20 or zero_cells > 0 or not base["standard_converged"] or not np.isfinite(base["standard_beta_tx"]) or abs(base["standard_beta_tx"]) > 3 or (np.isfinite(base["standard_interaction_se"]) and base["standard_interaction_se"] > 2)
    penalized_valid = penalized is not None and np.isfinite(base["penalized_beta_tx"]) and abs(base["penalized_beta_tx"]) <= 3
    if unstable:
        if penalized_valid:
            base.update({"coefficient_used": base["penalized_beta_tx"], "coefficient_source": "ridge_penalized", "data_support_status": "模型不稳定", "usable_interaction": True, "warning_zh": "普通Logistic存在分离、极端系数或收敛风险；使用预设岭惩罚估计并保留强警示。"})
        else:
            base.update({"data_support_status": "不可估计", "warning_zh": "交互模型在预设惩罚后仍不能形成可辩护估计。"})
    elif selected_n < 40 or active_n < 10 or control_n < 10:
        base.update({"coefficient_used": base["standard_beta_tx"], "coefficient_source": "standard", "data_support_status": "数据有限", "usable_interaction": True, "warning_zh": "来源亚组样本有限，结果波动可能较大。"})
    else:
        base.update({"coefficient_used": base["standard_beta_tx"], "coefficient_source": "standard", "data_support_status": "可模拟", "usable_interaction": True, "warning_zh": ""})
    return base


@lru_cache(maxsize=1)
def registry() -> pd.DataFrame:
    if not REGISTRY.exists():
        raise FileNotFoundError("富集水平交互注册表尚未生成。")
    return pd.read_csv(REGISTRY)


def condition_model(feature: str, levels: list[str], dose: str, missing_method: str) -> dict:
    canonical = json.dumps(sorted(levels), ensure_ascii=False)
    if len(levels) == 1 and REGISTRY.exists():
        rows = registry()
        selected = rows[(rows.feature.eq(feature)) & (rows.levels_json.eq(canonical)) & (rows.dose.eq(dose)) & (rows.missing_method.eq(missing_method))]
        if not selected.empty:
            return selected.iloc[0].to_dict()
    return fit_condition_interaction(feature, levels, dose, missing_method)
