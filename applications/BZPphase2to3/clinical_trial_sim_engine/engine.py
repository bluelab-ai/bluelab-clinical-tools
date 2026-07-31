from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cache import ResultCache
from .config_loader import config_hash, normalize_config
from .result_models import SimulationResult
from .scenario_validator import validate_scenario
from .simulation.bayesian_assurance_engine import run_bayesian_assurance
from .simulation.monte_carlo_engine import run_monte_carlo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "outputs/step19_dynamic_chinese_mvp"
FEATURE_FLAG = ROOT / "clinical_trial_sim_engine/assets/production_dynamic_engine_enabled.json"
AUDIT_LOG = OUTPUT_ROOT / "audit/scenario_audit_log.csv"
DISCLAIMER = "当前工具用于III期试验设计情景探索和决策支持。所示成功概率基于既定数据、模型和假设，不用于直接证明药物疗效，也不代表最终经申办方、统计分析计划或监管机构确认的III期成功概率。"


def production_dynamic_engine_enabled() -> bool:
    return FEATURE_FLAG.exists() and json.loads(FEATURE_FLAG.read_text(encoding="utf-8")).get("enabled") is True


def _audit(result: dict[str, Any], config: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "scenario_id": result["scenario_id"],
           "config_hash": result["config_hash"], "method": result["method_used"],
           "endpoint": config["endpoint"]["primary_endpoint"], "dose": config["trial"]["dose"],
           "total_n": config["trial"]["total_n"], "formal_pos": result.get("formal_pos"),
           "bayesian_assurance": result.get("bayesian_assurance"), "status": result["status"],
           "patient_level_data": "no"}
    exists = AUDIT_LOG.exists()
    with AUDIT_LOG.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if not exists: writer.writeheader()
        writer.writerow(row)


def run_scenario(scenario_config: dict[str, Any], *, use_cache: bool = True) -> dict[str, Any]:
    config = normalize_config(scenario_config); validation = validate_scenario(config, mode="advanced")
    key = config_hash(config); scenario_id = f"BZP-{key[:10].upper()}"
    if not validation["valid"]:
        return {"scenario_id": scenario_id, "config_hash": key, "status": "blocked", "formal_pos": None,
                "bayesian_assurance": None, "warnings_zh": validation["warnings"], "errors_zh": validation["errors"],
                "locked_or_invalid_flags": validation["locked_or_invalid_flags"], "disclaimer_zh": DISCLAIMER,
                "validation": validation}
    if not production_dynamic_engine_enabled():
        raise RuntimeError("生产动态引擎尚未通过强制测试，功能开关未启用。")
    cache = ResultCache()
    if use_cache:
        cached = cache.get(key)
        if cached is not None: return cached
    method = config["simulation"].get("method_type", "monte_carlo")
    result = SimulationResult(scenario_id=scenario_id, config_hash=key,
        status="pass_with_warnings" if validation["warnings"] else "pass", method_used=method,
        warnings_zh=validation["warnings"], locked_or_invalid_flags=validation["locked_or_invalid_flags"],
        assumptions=["效应来自Phase2_2026经审核汇总模型并按情景折减", "Phase2_2022正式借用权重固定为0", "结果为探索性规划阶段估计"])
    runtime = 0.0
    if method in {"monte_carlo", "both"}:
        mc = run_monte_carlo(config); runtime += mc.pop("runtime_seconds")
        for field, value in mc.items():
            if hasattr(result, field): setattr(result, field, value)
    if method in {"bayesian_assurance", "both"}:
        bayes = run_bayesian_assurance(config); runtime += bayes.pop("runtime_seconds")
        for field, value in bayes.items():
            if hasattr(result, field): setattr(result, field, value)
    result.runtime_seconds = runtime; result.n_simulations = int(config["simulation"]["n_simulations"])
    result.random_seed = int(config["simulation"]["random_seed"])
    payload = result.to_dict(); payload["validation"] = validation; payload["normalized_config"] = config
    payload["disclaimer_zh"] = DISCLAIMER; cache.set(key, payload); _audit(payload, config)
    return payload


def compare_scenarios(scenario_configs: list[dict[str, Any]]) -> dict[str, Any]:
    if not 2 <= len(scenario_configs) <= 5: raise ValueError("方案比较需要2至5个情景。")
    results = [run_scenario(config) for config in scenario_configs]
    table = [{"方案": item["scenario_id"], "探索性成功概率": item.get("formal_pos"),
              "贝叶斯保证概率": item.get("bayesian_assurance"), "方法": item.get("method_used"),
              "状态": item.get("status")} for item in results]
    ranked = sorted(table, key=lambda row: row["探索性成功概率"] if row["探索性成功概率"] is not None else -1, reverse=True)
    return {"scenario_comparison_table": table, "ranking": ranked,
            "assumption_burden_summary": {item["scenario_id"]: len(item.get("warnings_zh", [])) for item in results},
            "decision_notes_zh": ["排序仅用于探索性情景比较，不代表正式方案推荐。"], "results": results,
            "disclaimer_zh": DISCLAIMER}
