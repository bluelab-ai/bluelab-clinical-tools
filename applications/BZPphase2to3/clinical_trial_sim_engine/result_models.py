from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SimulationResult:
    scenario_id: str
    config_hash: str
    status: str
    method_used: str
    formal_pos: float | None = None
    bayesian_assurance: float | None = None
    mc_standard_error: float | None = None
    mc_confidence_interval: list[float] | None = None
    assurance_mc_standard_error: float | None = None
    control_outcome: float | None = None
    treatment_outcome: float | None = None
    assumed_effect: float | None = None
    effect_scale: str | None = None
    supportive_evidence: dict[str, Any] = field(default_factory=dict)
    joint_success_probability: float | None = None
    endpoint_statistics: dict[str, Any] = field(default_factory=dict)
    missing_death_summary: dict[str, Any] = field(default_factory=dict)
    prior_summary: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    warnings_zh: list[dict[str, str]] = field(default_factory=list)
    locked_or_invalid_flags: list[str] = field(default_factory=list)
    recommendation_category_zh: str = "探索性设计情景"
    runtime_seconds: float = 0.0
    n_simulations: int = 0
    random_seed: int = 0
    precision_status: str = "未评估"
    model_version: str = "step19-v1.0"
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
