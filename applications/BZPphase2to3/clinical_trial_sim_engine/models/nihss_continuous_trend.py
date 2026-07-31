from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import rankdata

from .final_level_interactions import population


ROOT = Path(__file__).resolve().parents[2]
MODEL_ASSET = ROOT / "clinical_trial_sim_engine/assets/private/step24a_nihss_trend_models.json"
DOSES = ("200mg", "400mg", "600mg")
OUTCOMES = {
    "death6_multiple_imputation": ("mrs01_mi_probability", "多重插补 MI"),
    "death6_locf_like": ("mrs01_locf", "LOCF"),
    "death6_conservative_nonresponder": ("mrs01_nonresponder", "缺失视为未应答"),
    "observed_available_case": ("mrs01_observed", "实际观察病例"),
}
SCORES = np.arange(6, 21, dtype=float)
KNOTS = (6.0, 8.0, 12.0)
RIDGE_ALPHA = 0.01


def _rcs_non_linear(x: np.ndarray) -> np.ndarray:
    """One nonlinear restricted-cubic-spline basis for three fixed knots."""
    x = np.asarray(x, dtype=float)
    k1, k2, k3 = KNOTS
    cube = lambda value: np.maximum(x - value, 0.0) ** 3
    return (cube(k1) - cube(k3) * (k2 - k1) / (k3 - k2)
            + cube(k2) * (k3 - k1) / (k3 - k2)) / (k3 - k1) ** 2


def design_matrix(nihss: np.ndarray, treatment: np.ndarray, form: str) -> np.ndarray:
    x = (np.asarray(nihss, dtype=float) - 8.0) / 4.0
    t = np.asarray(treatment, dtype=float)
    spline = _rcs_non_linear(np.asarray(nihss, dtype=float)) / 4.0
    columns = [np.ones(len(x)), t, x, spline]
    if form in {"linear_interaction", "spline_interaction"}:
        columns.append(t * x)
    if form == "spline_interaction":
        columns.append(t * spline)
    return np.column_stack(columns)


def _fit_ridge(X: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    penalty = np.ones(X.shape[1], dtype=float)
    penalty[0] = 0.0

    def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
        eta = X @ beta
        p = np.clip(expit(eta), 1e-8, 1 - 1e-8)
        loss = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
        value = loss + RIDGE_ALPHA * np.sum(penalty * beta**2) / 2
        gradient = X.T @ (p - y) / len(y) + RIDGE_ALPHA * penalty * beta
        return float(value), gradient

    result = minimize(
        lambda beta: objective(beta)[0],
        np.zeros(X.shape[1]),
        jac=lambda beta: objective(beta)[1],
        method="L-BFGS-B",
        options={"maxiter": 400, "ftol": 1e-11},
    )
    beta = np.asarray(result.x, dtype=float)
    probabilities = np.clip(expit(X @ beta), 1e-7, 1 - 1e-7)
    log_loss = float(-np.mean(y * np.log(probabilities) + (1 - y) * np.log(1 - probabilities)))
    calibration_error = float(abs(np.mean(probabilities) - np.mean(y)))
    if len(np.unique(y)) > 1:
        ranks = rankdata(probabilities)
        positives = y > 0.5
        auc = float((ranks[positives].sum() - positives.sum() * (positives.sum() + 1) / 2)
                    / (positives.sum() * (~positives).sum()))
    else:
        auc = math.nan
    return {
        "coefficients": beta,
        "converged": bool(result.success),
        "iterations": int(result.nit),
        "log_loss": log_loss,
        "calibration_error": calibration_error,
        "auc": auc,
    }


def _curve(coefficients: np.ndarray, form: str) -> dict[str, np.ndarray]:
    zeros = np.zeros(len(SCORES))
    ones = np.ones(len(SCORES))
    unconstrained_p0 = expit(design_matrix(SCORES, zeros, form) @ coefficients)
    unconstrained_p1 = expit(design_matrix(SCORES, ones, form) @ coefficients)
    p0 = np.clip(unconstrained_p0, 1e-6, 1 - 1e-6)
    p1 = np.clip(unconstrained_p1, 1e-6, 1 - 1e-6)
    log_or = np.log(p1 / (1 - p1)) - np.log(p0 / (1 - p0))
    return {"placebo_probability": p0, "treatment_probability": p1,
            "risk_difference": p1 - p0, "log_odds_ratio": log_or,
            "odds_ratio": np.exp(log_or),
            "unconstrained_placebo_probability": unconstrained_p0,
            "unconstrained_treatment_probability": unconstrained_p1}


def _model_frame(dose: str, missing_method: str, frame: pd.DataFrame | None = None) -> pd.DataFrame:
    data = population() if frame is None else frame
    outcome = OUTCOMES[missing_method][0]
    pair = data[data.dose.isin([dose, "placebo"])].copy()
    pair["treatment"] = pair.dose.eq(dose).astype(float)
    return pair[["baseline_nihss", "treatment", outcome]].dropna().rename(columns={outcome: "outcome"})


def fit_candidate_models(dose: str, missing_method: str, stability_resamples: int = 100,
                         seed: int = 20260716) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = _model_frame(dose, missing_method)
    rng = np.random.default_rng(seed + DOSES.index(dose) * 1009 + list(OUTCOMES).index(missing_method) * 9173)
    forms = ("no_interaction", "linear_interaction", "spline_interaction")
    rows: list[dict[str, Any]] = []
    fitted: dict[str, dict[str, Any]] = {}
    for form in forms:
        X = design_matrix(frame.baseline_nihss.to_numpy(), frame.treatment.to_numpy(), form)
        model = _fit_ridge(X, frame.outcome.to_numpy(dtype=float))
        curve = _curve(model["coefficients"], form)
        bootstrap_ok = 0
        extreme = 0
        coefficient_draws = []
        curve_draws = []
        for _ in range(stability_resamples):
            index = rng.integers(0, len(frame), len(frame))
            fit = _fit_ridge(X[index], frame.outcome.to_numpy(dtype=float)[index])
            bootstrap_ok += int(fit["converged"])
            draw_curve = _curve(fit["coefficients"], form)
            extreme += int(np.any((draw_curve["odds_ratio"] > 4.5) | (draw_curve["odds_ratio"] < 0.22)))
            coefficient_draws.append(fit["coefficients"])
            curve_draws.append(draw_curve["log_odds_ratio"])
        draw_matrix = np.vstack(coefficient_draws)
        draw_curves = np.vstack(curve_draws)
        coefficient_stability = float(np.nanmax(np.std(draw_matrix, axis=0)))
        tail = SCORES >= 13
        tail_slopes = np.diff(curve["log_odds_ratio"][tail])
        nonzero_tail_slopes = np.sign(tail_slopes[np.abs(tail_slopes) > 1e-8])
        tail_direction_changes = int(np.sum(nonzero_tail_slopes[1:] != nonzero_tail_slopes[:-1])) if len(nonzero_tail_slopes) > 1 else 0
        point_tail_sign = np.sign(curve["log_odds_ratio"][tail])
        tail_sign_stability = float(np.min(np.mean(np.sign(draw_curves[:, tail]) == point_tail_sign, axis=0)))
        row = {
            "dose": dose,
            "missing_method": missing_method,
            "missing_method_zh": OUTCOMES[missing_method][1],
            "model_form": form,
            "source_n": len(frame),
            "converged": model["converged"],
            "log_loss": model["log_loss"],
            "calibration_error": model["calibration_error"],
            "auc_supportive_only": model["auc"],
            "bootstrap_fit_rate": bootstrap_ok / stability_resamples,
            "bootstrap_extreme_curve_rate": extreme / stability_resamples,
            "max_bootstrap_coefficient_sd": coefficient_stability,
            "point_min_odds_ratio": float(curve["odds_ratio"].min()),
            "point_max_odds_ratio": float(curve["odds_ratio"].max()),
            "tail_direction_changes": tail_direction_changes,
            "tail_sign_stability_min": tail_sign_stability,
            "effective_interaction_df": 0 if form == "no_interaction" else (1 if form == "linear_interaction" else 2),
            "scientific_probability_floor": False,
            "scientific_odds_ratio_floor": False,
            "ridge_alpha": RIDGE_ALPHA,
            "knots": "6|8|12",
        }
        rows.append(row)
        fitted[form] = model | {"curve": curve}

    comparison = pd.DataFrame(rows)
    linear = comparison.loc[comparison.model_form.eq("linear_interaction")].iloc[0]
    spline = comparison.loc[comparison.model_form.eq("spline_interaction")].iloc[0]
    spline_supported = bool(
        spline.converged
        and spline.bootstrap_fit_rate >= 0.90
        and spline.bootstrap_extreme_curve_rate <= 0.10
        and spline.log_loss <= linear.log_loss - 0.001
        and spline.tail_direction_changes == 0
        and spline.tail_sign_stability_min >= 0.65
        and spline.point_min_odds_ratio >= 0.10
        and spline.point_max_odds_ratio <= 10.0
    )
    linear_supported = bool(
        linear.converged
        and linear.bootstrap_fit_rate >= 0.90
        and linear.bootstrap_extreme_curve_rate <= 0.20
        and linear.tail_sign_stability_min >= 0.55
        and linear.point_min_odds_ratio >= 0.05
        and linear.point_max_odds_ratio <= 20.0
    )
    selected = "spline_interaction" if spline_supported else ("linear_interaction" if linear_supported else "no_interaction")
    if spline_supported:
        reason = "惩罚限制性三次样条满足拟合、校准、自助法和稀疏尾部稳定性预设标准。"
    elif linear_supported:
        reason = "惩罚样条未通过稀疏尾部稳定性或增量拟合标准；回退到惩罚线性交互。"
    else:
        reason = "样条与线性交互均未通过稀疏尾部稳定性标准；回退到无治疗×NIHSS交互。"
    comparison["selected_primary"] = comparison.model_form.eq(selected)
    comparison["selection_reason_zh"] = reason
    selected_model = fitted[selected] | {
        "model_form": selected,
        "selection_reason_zh": reason,
        "source_n": len(frame),
    }
    return comparison, selected_model


def fit_all_trends(bootstrap_resamples: int = 500, stability_resamples: int = 100,
                   seed: int = 20260716) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    data = population()
    trend_rows: list[dict[str, Any]] = []
    comparison_tables: list[pd.DataFrame] = []
    asset: dict[str, Any] = {
        "version": "step24ar-nihss-continuous-v2.0",
        "knots": list(KNOTS),
        "ridge_alpha": RIDGE_ALPHA,
        "bootstrap_resamples": bootstrap_resamples,
        "models": {},
    }
    for dose in DOSES:
        for missing_method in OUTCOMES:
            comparison, selected = fit_candidate_models(dose, missing_method, stability_resamples, seed)
            comparison_tables.append(comparison)
            frame = _model_frame(dose, missing_method)
            X = design_matrix(frame.baseline_nihss.to_numpy(), frame.treatment.to_numpy(), selected["model_form"])
            y = frame.outcome.to_numpy(dtype=float)
            rng = np.random.default_rng(seed + DOSES.index(dose) * 13007 + list(OUTCOMES).index(missing_method) * 17011)
            draws = []
            for _ in range(bootstrap_resamples):
                index = rng.integers(0, len(frame), len(frame))
                draw = _fit_ridge(X[index], y[index])
                if draw["converged"]:
                    curve = _curve(draw["coefficients"], selected["model_form"])
                    draws.append(np.column_stack([
                        curve["placebo_probability"], curve["treatment_probability"],
                        curve["risk_difference"], curve["odds_ratio"], curve["log_odds_ratio"],
                    ]))
            draw_array = np.stack(draws)
            point = _curve(selected["coefficients"], selected["model_form"])
            key = f"{dose}|{missing_method}"
            asset["models"][key] = {
                "model_form": selected["model_form"],
                "selection_reason_zh": selected["selection_reason_zh"],
                "coefficients": selected["coefficients"].tolist(),
                "bootstrap_curve_draws": np.round(draw_array, 6).tolist(),
            }
            for index, score in enumerate(SCORES.astype(int)):
                score_data = data[data.baseline_nihss.eq(score)]
                active = score_data[score_data.dose.eq(dose)]
                placebo = score_data[score_data.dose.eq("placebo")]
                source_n = len(score_data)
                if source_n >= 20 and len(active) >= 5 and len(placebo) >= 5:
                    support = "数据支持较充分"
                elif source_n >= 8 and len(active) >= 2 and len(placebo) >= 2:
                    support = "数据有限"
                elif source_n > 0:
                    support = "明显稀疏/主要依赖平滑外推"
                else:
                    support = "不可估计"
                rd_draws = draw_array[:, index, 2]
                point_sign = np.sign(point["risk_difference"][index])
                sign_stability = float(np.mean(np.sign(rd_draws) == point_sign)) if point_sign else 0.5
                trend_rows.append({
                    "dose": dose,
                    "missing_method": missing_method,
                    "missing_method_zh": OUTCOMES[missing_method][1],
                    "nihss_score": score,
                    "selected_model": selected["model_form"],
                    "knots": "6|8|12",
                    "treatment_probability": point["treatment_probability"][index],
                    "placebo_probability": point["placebo_probability"][index],
                    "marginal_risk_difference": point["risk_difference"][index],
                    "marginal_odds_ratio": point["odds_ratio"][index],
                    "treatment_probability_lower95": np.quantile(draw_array[:, index, 1], 0.025),
                    "treatment_probability_upper95": np.quantile(draw_array[:, index, 1], 0.975),
                    "placebo_probability_lower95": np.quantile(draw_array[:, index, 0], 0.025),
                    "placebo_probability_upper95": np.quantile(draw_array[:, index, 0], 0.975),
                    "risk_difference_lower95": np.quantile(rd_draws, 0.025),
                    "risk_difference_upper95": np.quantile(rd_draws, 0.975),
                    "odds_ratio_lower95": np.quantile(draw_array[:, index, 3], 0.025),
                    "odds_ratio_upper95": np.quantile(draw_array[:, index, 3], 0.975),
                    "interaction_sign_stability": sign_stability,
                    "source_n": source_n,
                    "treatment_arm_n": len(active),
                    "placebo_n": len(placebo),
                    "support_status": support,
                    "exploratory": True,
                })
    return pd.DataFrame(trend_rows), pd.concat(comparison_tables, ignore_index=True), asset


def save_model_asset(asset: dict[str, Any], path: Path = MODEL_ASSET) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asset, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    load_model_asset.cache_clear()


@lru_cache(maxsize=1)
def load_model_asset() -> dict[str, Any]:
    if not MODEL_ASSET.exists():
        raise FileNotFoundError("NIHSS连续趋势模型资产尚未生成。")
    return json.loads(MODEL_ASSET.read_text(encoding="utf-8"))


def model_curve(dose: str, missing_method: str) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    model = load_model_asset()["models"][f"{dose}|{missing_method}"]
    coefficients = np.asarray(model["coefficients"], dtype=float)
    point = _curve(coefficients, model["model_form"])
    frame = pd.DataFrame({"nihss_score": SCORES.astype(int), **point})
    draws = np.asarray(model["bootstrap_curve_draws"], dtype=float)
    return frame, draws, model
