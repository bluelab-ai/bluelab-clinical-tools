from __future__ import annotations

import numpy as np


def simulate_binary_trials(
    rng: np.random.Generator,
    n_simulations: int,
    n_active: int,
    n_control: int,
    control_rate: float,
    risk_difference: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    treatment_rate = float(np.clip(control_rate + risk_difference, 0.001, 0.999))
    y_active = rng.binomial(n_active, treatment_rate, size=n_simulations)
    y_control = rng.binomial(n_control, control_rate, size=n_simulations)
    p_active = y_active / n_active
    p_control = y_control / n_control
    rd = p_active - p_control
    se = np.sqrt(np.maximum(p_active * (1 - p_active) / n_active + p_control * (1 - p_control) / n_control, 1e-12))
    return rd, se, p_active, p_control
