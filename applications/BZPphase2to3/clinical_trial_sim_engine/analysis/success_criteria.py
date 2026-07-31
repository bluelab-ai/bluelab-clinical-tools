from __future__ import annotations

import numpy as np


def frequentist_success(z_values: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    threshold = 1.959963984540054 if alpha == 0.05 else 1.6448536269514722
    return z_values > threshold


def pos_summary(success: np.ndarray) -> tuple[float, float, list[float]]:
    n = len(success)
    pos = float(np.mean(success))
    se = float(np.sqrt(pos * (1 - pos) / max(n, 1)))
    return pos, se, [max(0.0, pos - 1.96 * se), min(1.0, pos + 1.96 * se)]
