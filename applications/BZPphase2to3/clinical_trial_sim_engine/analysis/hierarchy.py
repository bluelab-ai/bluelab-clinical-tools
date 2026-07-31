from __future__ import annotations

import numpy as np


def hierarchy_success(primary: np.ndarray, supportive: np.ndarray, hierarchy: str) -> tuple[np.ndarray, np.ndarray]:
    joint = primary & supportive
    if hierarchy in {"co_primary", "co_primary_strict_sensitivity"}:
        return joint, joint
    return primary, joint
