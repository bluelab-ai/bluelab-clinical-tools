from __future__ import annotations

import numpy as np


def ordinal_success_z(estimates: np.ndarray, standard_error: float) -> np.ndarray:
    return estimates / max(standard_error, 1e-9)
