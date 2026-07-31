from __future__ import annotations

import numpy as np


def supportive_success_from_primary_z(
    rng: np.random.Generator,
    primary_z: np.ndarray,
    supportive_mean_z: float,
    correlation: float = 0.31,
) -> np.ndarray:
    centered = primary_z - float(np.mean(primary_z))
    noise = rng.normal(size=len(primary_z))
    supportive_z = supportive_mean_z + correlation * centered + np.sqrt(1 - correlation**2) * noise
    return supportive_z > 1.96
