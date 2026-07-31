from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "clinical_trial_sim_engine/assets/private/phase2_2026_virtual_population.npz"


def load_private_population_asset() -> dict[str, np.ndarray]:
    with np.load(ASSET, allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def generate_virtual_population(config: dict[str, Any], rng: np.random.Generator) -> dict[str, np.ndarray]:
    asset = load_private_population_asset()
    n = int(config["trial"]["total_n"])
    population = config["trial"]["population"]
    mask = np.ones(len(asset["age"]), dtype=bool)
    if population == "age_40_64":
        mask &= (asset["age"] >= 40) & (asset["age"] <= 64)
    elif population == "age_65_80":
        mask &= (asset["age"] >= 65) & (asset["age"] <= 80)
    elif population == "baseline_nihss_le7":
        mask &= asset["baseline_nihss"] <= 7
    elif population == "baseline_nihss_ge8":
        mask &= asset["baseline_nihss"] >= 8
    indices = np.flatnonzero(mask)
    if len(indices) < 20:
        raise ValueError("所选预定义人群的可用模型样本不足。")
    sampled = rng.choice(indices, size=n, replace=True)
    allocation = config["trial"].get("allocation", "1:1")
    p_active = 0.5 if allocation == "1:1" else 2 / 3
    treatment = np.zeros(n, dtype=np.int8)
    active_n = int(round(n * p_active))
    treatment[rng.choice(n, size=active_n, replace=False)] = 1
    return {
        "age": asset["age"][sampled],
        "sex_male": asset["sex_male"][sampled],
        "baseline_nihss": asset["baseline_nihss"][sampled],
        "baseline_mrs": asset["baseline_mrs"][sampled],
        "treatment": treatment,
    }
