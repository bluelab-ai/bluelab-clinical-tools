from __future__ import annotations

import numpy as np


def simulate_ordinal_trials(rng: np.random.Generator, n_simulations: int, true_log_or: float, se: float) -> tuple[np.ndarray, np.ndarray]:
    estimates = rng.normal(true_log_or, se, size=n_simulations)
    z_values = estimates / max(se, 1e-9)
    return estimates, z_values
