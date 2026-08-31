"""In-memory scenario report construction."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

from .engine import registry_snapshot


TZ = ZoneInfo("Asia/Shanghai")


def build_scenario_report(
    *,
    scenario_name: str,
    scenario: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Build a user-initiated report without server-side persistence."""
    try:
        registry = registry_snapshot()
    except Exception:
        provenance = result.get("provenance", {})
        registry = {
            "status": "unavailable",
            "evidence_status": "unavailable",
            "engine_version": provenance.get("engine_version", "unavailable"),
            "model_version": provenance.get("model_version", "unavailable"),
            "note": "Registry snapshot unavailable; no substitute statistics added.",
        }
    return {
        "report": {
            "name": scenario_name or "未命名情景",
            "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            "planning_stage": "exploratory",
            "persistence": "generated in memory; not stored by the application",
        },
        "endpoint": {
            "name": "D104±5内BV复发",
            "population": "以方案定义D21治愈为条件",
            "prediction_time": "首次给药前基线",
            "source_population": "二期D24±3治愈FAS",
            "missing_rule": "主要结果为观察标签；19/34为缺失按复发敏感性锚点",
            "status": "modeled_exploratory",
        },
        "scenario": scenario,
        "result": result,
        "registry": registry,
        "interpretation": {
            "allowed": "规划阶段相对情景探索与关注重点讨论",
            "not_allowed": [
                "个人真实复发概率",
                "患者高、中、低风险分类",
                "治疗、入组或排除决定",
                "减少方案规定随访",
                "三期成功率",
            ],
        },
    }


def report_json_bytes(report: dict[str, Any]) -> bytes:
    return (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
