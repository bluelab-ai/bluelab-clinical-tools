from __future__ import annotations

import numpy as np

EFFICIENCY = {
    "unadjusted_newcombe_wilson_rd": 1.00,
    "stratified_rd_cmh_like": 0.96,
    "covariate_adjusted_logistic": 0.90,
    "covariate_adjusted_marginal_rd": 0.92,
}


def binary_z(rd: np.ndarray, se: np.ndarray, method: str) -> np.ndarray:
    return rd / np.maximum(se * EFFICIENCY.get(method, 1.0), 1e-9)
