from __future__ import annotations

import numpy as np


def simulate_continuous_trials(rng: np.random.Generator, n_simulations: int, true_difference: float, se: float) -> tuple[np.ndarray, np.ndarray]:
    estimates = rng.normal(true_difference, se, size=n_simulations)
    z_values = -estimates / max(se, 1e-9)
    return estimates, z_values
