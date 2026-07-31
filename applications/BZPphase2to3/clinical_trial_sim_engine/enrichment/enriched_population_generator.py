from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .population_filter import FILTERS, apply_filters, validate_filters


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "clinical_trial_sim_engine/assets/private/step22_phase2_2026_population.parquet"
MISSING_COLUMNS = {
    "observed_available_case": "mrs01_observed",
    "death6_locf_like": "mrs01_locf",
    "death6_multiple_imputation": "mrs01_mi_probability",
    "death6_conservative_nonresponder": "mrs01_nonresponder",
}


def load_population() -> pd.DataFrame:
    if not ASSET.exists():
        raise FileNotFoundError("Step22私有虚拟人群资产尚未生成。")
    return pd.read_parquet(ASSET)


def summarize_enriched_population(config: dict[str, Any]) -> dict[str, Any]:
    frame = load_population(); enrichment = config.get("enrichment", {})
    source_mode = enrichment.get("source_mode", "phase2_2026_like")
    filters = validate_filters(enrichment.get("filters", []), source_mode)
    selected, mask = apply_filters(frame, filters)
    prevalence = float(mask.mean()); missing_rule = config["missing_death"]["sensitivity_rule"]
    outcome = MISSING_COLUMNS[missing_rule]
    dose = config["trial"]["dose"].replace("BZP ", "").replace(" BID", "")
    placebo = selected[selected.dose.eq("placebo")]; active = selected[selected.dose.eq(dose)]
    control_rate = float(placebo[outcome].mean()) if len(placebo) else np.nan
    treatment_rate = float(active[outcome].mean()) if len(active) else np.nan
    endpoint_evaluable = int(selected[outcome].notna().sum())
    warnings=[]
    if len(selected) < 40: warnings.append("富集后II期来源样本少于40例")
    if len(placebo) < 20 or len(active) < 20: warnings.append("富集后任一治疗组来源样本少于20例")
    if prevalence < .10: warnings.append("富集条件覆盖率低于10%，筛选负担高")
    if selected[outcome].isna().mean() > .10: warnings.append("终点不可评价比例超过10%")
    covariates={}
    for col in ["age","baseline_nihss","baseline_mrs","limb_motor_sum","bmi","sex_male","previous_stroke","ocsp_taci"]:
        if col in selected:
            covariates[col]={"mean":float(selected[col].mean()) if selected[col].notna().any() else None,"missing_rate":float(selected[col].isna().mean())}
    return {
        "filter_codes": filters,
        "filter_labels_zh": [FILTERS[x].label_zh for x in filters],
        "source_mode": source_mode,
        "source_subject_n": int(len(selected)),
        "source_total_n": int(len(frame)),
        "eligible_proportion": prevalence,
        "projected_screen_failure_rate": 1-prevalence,
        "endpoint_evaluable_n": endpoint_evaluable,
        "effective_source_sample_size": endpoint_evaluable,
        "control_response_probability_observed": control_rate,
        "treatment_response_probability_observed": treatment_rate,
        "missingness_expectation": float(selected[outcome].isna().mean()),
        "baseline_covariate_distribution": covariates,
        "small_cell_warning": bool(warnings),
        "warnings_zh": warnings,
    }


def sample_enriched_population(config: dict[str, Any], rng: np.random.Generator) -> pd.DataFrame:
    frame=load_population(); selected,_=apply_filters(frame,config.get("enrichment",{}).get("filters",[]))
    if len(selected)<20: raise ValueError("所选预设富集人群的来源样本不足20例。")
    return selected.iloc[rng.choice(len(selected),size=int(config["trial"]["total_n"]),replace=True)].reset_index(drop=True)
