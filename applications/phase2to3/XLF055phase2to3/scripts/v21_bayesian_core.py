#!/usr/bin/env python3
"""Core deterministic modeling utilities for the V2.1 exploratory scenario model."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.stats import rankdata


P3_TEST = "XLF055+甲硝唑片"
P3_CONTROL = "XLF055模拟剂+甲硝唑片"
NUMERIC = [
    "age_years",
    "baseline_bmi",
    "baseline_vaginal_ph",
    "baseline_nugent_score",
    "baseline_av_score",
]
BINARY = ["any_medical_history"]
CATEGORICAL = ["baseline_lactobacillus_grade", "efficacy_treatment"]
REFERENCES = {
    "baseline_lactobacillus_grade": "III级或IV级",
    "efficacy_treatment": P3_CONTROL,
}
MISSING = "__MISSING__"


def stable_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass
class FittedPreprocessor:
    numeric: dict[str, dict[str, float | bool]]
    categorical_levels: dict[str, list[str]]
    categorical_references: dict[str, str]
    columns: list[str]

    def to_dict(self) -> dict:
        return {
            "numeric": self.numeric,
            "categorical_levels": self.categorical_levels,
            "categorical_references": self.categorical_references,
            "columns": self.columns,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FittedPreprocessor":
        return cls(
            numeric=d["numeric"],
            categorical_levels=d["categorical_levels"],
            categorical_references=d["categorical_references"],
            columns=d["columns"],
        )


def fit_preprocessor(frame: pd.DataFrame) -> FittedPreprocessor:
    numeric_specs: dict[str, dict[str, float | bool]] = {}
    columns: list[str] = []
    for col in NUMERIC + BINARY:
        x = pd.to_numeric(frame[col], errors="coerce")
        median = float(x.median()) if x.notna().any() else 0.0
        filled = x.fillna(median).to_numpy(float)
        mean = float(np.mean(filled))
        sd = float(np.std(filled, ddof=0))
        if not np.isfinite(sd) or sd < 1e-12:
            sd = 1.0
        has_missing = bool(x.isna().any())
        numeric_specs[col] = {
            "median": median,
            "mean": mean,
            "sd": sd,
            "has_missing_indicator": has_missing,
        }
        columns.append(f"num:{col}")
        if has_missing:
            columns.append(f"missing:{col}")

    categorical_levels: dict[str, list[str]] = {}
    for col in CATEGORICAL:
        values = frame[col].astype("string").fillna(MISSING).astype(str)
        levels = sorted(set(values.tolist()))
        reference = REFERENCES[col]
        if reference not in levels:
            levels = [reference] + levels
        categorical_levels[col] = levels
        for level in levels:
            if level != reference:
                columns.append(f"cat:{col}={level}")
    return FittedPreprocessor(
        numeric=numeric_specs,
        categorical_levels=categorical_levels,
        categorical_references=dict(REFERENCES),
        columns=columns,
    )


def transform(
    frame: pd.DataFrame, prep: FittedPreprocessor
) -> tuple[np.ndarray, dict[str, int]]:
    arrays: list[np.ndarray] = []
    unseen: dict[str, int] = {}
    for col in NUMERIC + BINARY:
        spec = prep.numeric[col]
        x = pd.to_numeric(frame[col], errors="coerce")
        missing = x.isna().to_numpy(float)
        filled = x.fillna(float(spec["median"])).to_numpy(float)
        arrays.append((filled - float(spec["mean"])) / float(spec["sd"]))
        if bool(spec["has_missing_indicator"]):
            arrays.append(missing)
    for col in CATEGORICAL:
        values = frame[col].astype("string").fillna(MISSING).astype(str)
        known = set(prep.categorical_levels[col])
        unseen[col] = int((~values.isin(known)).sum())
        reference = prep.categorical_references[col]
        for level in prep.categorical_levels[col]:
            if level != reference:
                arrays.append(values.eq(level).to_numpy(float))
    if arrays:
        matrix = np.column_stack(arrays).astype(float)
    else:
        matrix = np.empty((len(frame), 0), dtype=float)
    if matrix.shape[1] != len(prep.columns):
        raise RuntimeError("Transformed matrix does not match frozen column schema")
    return matrix, unseen


def design_with_intercept(matrix: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(matrix.shape[0]), matrix])


def neg_log_posterior(
    beta: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    prior_sd: np.ndarray,
) -> float:
    z = x @ beta
    return float(
        np.sum(np.logaddexp(0.0, z) - y * z)
        + 0.5 * np.sum((beta / prior_sd) ** 2)
    )


def fit_bayesian_logistic(
    matrix: np.ndarray,
    y: np.ndarray,
    coefficient_prior_sd: float,
    intercept_prior_sd: float = 1.5,
    max_iterations: int = 200,
    gradient_tolerance: float = 1e-9,
    step_tolerance: float = 1e-12,
) -> dict:
    x = design_with_intercept(matrix)
    y = np.asarray(y, dtype=float)
    prior_sd = np.concatenate(
        [[intercept_prior_sd], np.full(matrix.shape[1], coefficient_prior_sd)]
    )
    beta = np.zeros(x.shape[1], dtype=float)
    converged = False
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        p = expit(x @ beta)
        gradient = x.T @ (p - y) + beta / (prior_sd**2)
        weights = p * (1.0 - p)
        hessian = x.T @ (weights[:, None] * x) + np.diag(1.0 / (prior_sd**2))
        grad_norm = float(np.max(np.abs(gradient)))
        if grad_norm <= gradient_tolerance:
            converged = True
            break
        step = np.linalg.solve(hessian, gradient)
        old = neg_log_posterior(beta, x, y, prior_sd)
        directional = float(gradient @ step)
        scale = 1.0
        while scale >= 2.0**-40:
            candidate = beta - scale * step
            new = neg_log_posterior(candidate, x, y, prior_sd)
            if new <= old - 1e-4 * scale * directional:
                beta = candidate
                break
            scale *= 0.5
        if scale < 2.0**-40:
            raise RuntimeError("Newton backtracking failed")
        if float(np.max(np.abs(scale * step))) <= step_tolerance:
            p = expit(x @ beta)
            gradient = x.T @ (p - y) + beta / (prior_sd**2)
            if float(np.max(np.abs(gradient))) <= 1e-8:
                converged = True
                break
    p = expit(x @ beta)
    gradient = x.T @ (p - y) + beta / (prior_sd**2)
    weights = p * (1.0 - p)
    hessian = x.T @ (weights[:, None] * x) + np.diag(1.0 / (prior_sd**2))
    covariance = np.linalg.inv(hessian)
    eigenvalues = np.linalg.eigvalsh(covariance)
    return {
        "mode": beta,
        "covariance": covariance,
        "converged": converged,
        "iterations": iterations,
        "gradient_inf_norm": float(np.max(np.abs(gradient))),
        "covariance_min_eigenvalue": float(eigenvalues.min()),
        "covariance_max_asymmetry": float(np.max(np.abs(covariance - covariance.T))),
        "coefficient_prior_sd": coefficient_prior_sd,
        "intercept_prior_sd": intercept_prior_sd,
    }


def posterior_draws(fit: dict, draws: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    result = rng.multivariate_normal(
        mean=np.asarray(fit["mode"]),
        cov=np.asarray(fit["covariance"]),
        size=draws,
        method="cholesky",
    )
    if result.shape != (draws, len(fit["mode"])) or not np.isfinite(result).all():
        raise RuntimeError("Invalid posterior draws")
    return result


def posterior_probabilities(matrix: np.ndarray, draws: np.ndarray) -> np.ndarray:
    x = design_with_intercept(matrix)
    return expit(x @ draws.T)


def treatment_blind_draw_probabilities(
    frame: pd.DataFrame, prep: FittedPreprocessor, draws: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, int]]:
    test = frame.copy()
    control = frame.copy()
    test["efficacy_treatment"] = P3_TEST
    control["efficacy_treatment"] = P3_CONTROL
    xt, unseen_t = transform(test, prep)
    xc, unseen_c = transform(control, prep)
    pt = posterior_probabilities(xt, draws)
    pc = posterior_probabilities(xc, draws)
    avg = 0.5 * pt + 0.5 * pc
    unseen = {k: unseen_t.get(k, 0) + unseen_c.get(k, 0) for k in set(unseen_t) | set(unseen_c)}
    return avg, pt, pc, unseen


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(y) - np.asarray(p)) ** 2))


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p), 1e-12, 1 - 1e-12)
    y = np.asarray(y)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    n1 = int(y.sum())
    n0 = int(len(y) - n1)
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = rankdata(p, method="average")
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def calibration(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    p = np.clip(np.asarray(p), 1e-8, 1 - 1e-8)
    lp = np.log(p / (1 - p))
    matrix = lp[:, None]
    fit = fit_bayesian_logistic(
        matrix,
        np.asarray(y),
        coefficient_prior_sd=1000.0,
        intercept_prior_sd=1000.0,
        max_iterations=300,
        gradient_tolerance=1e-8,
    )
    return float(fit["mode"][0]), float(fit["mode"][1])


def stratified_folds(y: np.ndarray, folds: int, repeats: int, seed: int):
    y = np.asarray(y, dtype=int)
    idx0 = np.where(y == 0)[0]
    idx1 = np.where(y == 1)[0]
    rng = np.random.default_rng(seed)
    for repeat in range(repeats):
        a0 = rng.permutation(idx0)
        a1 = rng.permutation(idx1)
        parts0 = np.array_split(a0, folds)
        parts1 = np.array_split(a1, folds)
        for fold in range(folds):
            valid = np.sort(np.concatenate([parts0[fold], parts1[fold]]))
            train = np.setdiff1d(np.arange(len(y)), valid, assume_unique=True)
            yield repeat, fold, train, valid


def interval(values: np.ndarray) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    return {
        "median": float(np.quantile(values, 0.5)),
        "lower_95": float(np.quantile(values, 0.025)),
        "upper_95": float(np.quantile(values, 0.975)),
        "mean": float(np.mean(values)),
    }
