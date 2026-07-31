from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd


ROOT=Path(__file__).resolve().parents[2]
REGISTRY=ROOT/"clinical_trial_sim_engine/assets/private/step23_interaction_coefficients.csv"


@lru_cache(maxsize=1)
def load_interaction_registry() -> pd.DataFrame:
    if not REGISTRY.exists():raise FileNotFoundError("Step23交互系数注册表尚未生成。")
    return pd.read_csv(REGISTRY)


def coefficient_row(dose: str,missing_method: str,filter_code: str) -> pd.Series:
    table=load_interaction_registry();rows=table[(table.dose.eq(dose))&(table.missing_method.eq(missing_method))&(table.filter_code.eq(filter_code))]
    if rows.empty:raise ValueError(f"缺少交互系数：{dose}/{missing_method}/{filter_code}")
    return rows.iloc[0]


def calibrated_interaction_component(row: pd.Series,retention_ratio: float) -> float:
    """Selected subgroup deviation from the full-FAS average interaction."""
    level=float(row.selected_level);prevalence=float(row.feature_prevalence)
    return float(row.raw_interaction_coefficient)*float(retention_ratio)*(level-prevalence)


def final_subgroup_log_or(base_treatment_log_or: float,phase3_effect_multiplier: float,row: pd.Series,retention_ratio: float) -> float:
    return float(base_treatment_log_or)*float(phase3_effect_multiplier)+calibrated_interaction_component(row,retention_ratio)
