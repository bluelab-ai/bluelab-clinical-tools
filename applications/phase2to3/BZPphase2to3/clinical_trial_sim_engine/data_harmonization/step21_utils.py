from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyreadstat
import statsmodels.api as sm
from scipy.stats import fisher_exact, norm
from statsmodels.stats.proportion import confint_proportions_2indep


def read_dataset(path: str | Path, metadata_only: bool = False):
    path = Path(path)
    reader = pyreadstat.read_xport if path.suffix.lower() == ".xpt" else pyreadstat.read_sas7bdat
    errors=[]
    for encoding in ["GB18030", "GBK", None]:
        try:
            kwargs={"metadataonly":metadata_only}
            if encoding: kwargs["encoding"]=encoding
            return (*reader(str(path), **kwargs), f"pyreadstat:{encoding or 'default'}")
        except Exception as exc:
            errors.append(f"{encoding}:{type(exc).__name__}:{str(exc)[:100]}")
    raise RuntimeError(" | ".join(errors))


def stable_frame_hash(frame: pd.DataFrame) -> str:
    if frame.empty: return hashlib.sha256(b"").hexdigest()
    normalized=frame.copy()
    normalized.columns=[str(c).upper() for c in normalized.columns]
    normalized=normalized.reindex(sorted(normalized.columns),axis=1)
    for col in normalized: normalized[col]=normalized[col].astype(str).fillna("")
    normalized=normalized.sort_values(list(normalized.columns),kind="mergesort").reset_index(drop=True)
    return hashlib.sha256(pd.util.hash_pandas_object(normalized,index=False).values.tobytes()).hexdigest()


def clean_yes(value: Any) -> float:
    text=str(value).strip().upper()
    if text in {"Y","YES","是","1","1.0","TRUE"}: return 1.0
    if text in {"N","NO","否","0","0.0","FALSE","2","2.0"}: return 0.0
    return np.nan


def combine_datetime(date_value: Any, time_value: Any = None) -> pd.Timestamp:
    if pd.isna(date_value) or str(date_value).strip() in {"","NAT","NAN"}: return pd.NaT
    date_text=str(date_value).strip()
    if "T" in date_text or ":" in date_text:
        return pd.to_datetime(date_text,errors="coerce")
    if time_value is None or pd.isna(time_value) or str(time_value).strip() in {"","NAN"}:
        return pd.NaT
    return pd.to_datetime(f"{date_text} {str(time_value).strip()}",errors="coerce")


def derive_onset_hours(onset: Any, dose: Any) -> float:
    onset=pd.to_datetime(onset,errors="coerce"); dose=pd.to_datetime(dose,errors="coerce")
    if pd.isna(onset) or pd.isna(dose): return np.nan
    hours=(dose-onset).total_seconds()/3600
    return float(hours) if -1 <= hours <= 168 else np.nan


def derive_locf(records: pd.DataFrame, subjects: pd.DataFrame) -> pd.DataFrame:
    required={"subject_id","mrs_value","day","is_day90"}
    if not required.issubset(records): raise ValueError(f"missing columns {required-set(records)}")
    out=subjects[["subject_id","death_before_day90"]].copy()
    observed=records[records.is_day90 & records.mrs_value.notna()].sort_values(["subject_id","day"]).drop_duplicates("subject_id",keep="last")
    prior=records[(records.day>0)&(records.day<83)&records.mrs_value.notna()].sort_values(["subject_id","day"]).drop_duplicates("subject_id",keep="last")
    out=out.merge(observed[["subject_id","mrs_value","day"]].rename(columns={"mrs_value":"mrs_observed","day":"observed_day"}),on="subject_id",how="left")
    out=out.merge(prior[["subject_id","mrs_value","day"]].rename(columns={"mrs_value":"prior_mrs","day":"locf_source_day"}),on="subject_id",how="left")
    out["mrs_locf"]=out.mrs_observed
    missing=out.mrs_locf.isna() & ~out.death_before_day90.fillna(False)
    out.loc[missing,"mrs_locf"]=out.loc[missing,"prior_mrs"]
    out["locf_used"]=missing & out.prior_mrs.notna()
    out["no_postbaseline_for_locf"]=missing & out.prior_mrs.isna()
    out.loc[out.death_before_day90.fillna(False),"mrs_locf"]=6
    out.loc[out.death_before_day90.fillna(False),"locf_used"]=False
    return out


def multiple_impute_mrs(frame: pd.DataFrame, predictors: list[str], m: int = 20, seed: int = 20260721):
    data=frame.copy(); death=data.death_before_day90.fillna(False); observed=data.mrs_observed.notna() & ~death
    classes=sorted(data.loc[observed,"mrs_observed"].dropna().astype(int).unique())
    x=data[predictors].copy()
    for col in x:
        if pd.api.types.is_numeric_dtype(x[col]): x[col]=pd.to_numeric(x[col],errors="coerce").fillna(pd.to_numeric(x[col],errors="coerce").median())
        else: x[col]=x[col].astype(str).replace({"nan":"缺失","":"缺失"})
    x=pd.get_dummies(x,drop_first=False,dtype=float); x=sm.add_constant(x,has_constant="add")
    y=data.loc[observed,"mrs_observed"].astype(int)
    try:
        fit=sm.MNLogit(y,x.loc[observed]).fit_regularized(alpha=.05,L1_wt=0,maxiter=300,disp=False)
        probabilities=np.asarray(fit.predict(x))
        if probabilities.shape[1] != len(classes): raise ValueError("class mismatch")
        converged=True; method="regularized_multinomial_logit"
    except Exception:
        counts=y.value_counts(normalize=True).reindex(classes,fill_value=0).to_numpy(); probabilities=np.tile(counts,(len(data),1)); converged=False; method="marginal_multinomial_fallback"
    probabilities=np.clip(probabilities,1e-8,None); probabilities/=probabilities.sum(axis=1,keepdims=True)
    rng=np.random.default_rng(seed); imputations=[]
    for _ in range(m):
        values=data.mrs_observed.copy(); values.loc[death]=6
        for idx in data.index[values.isna()]: values.loc[idx]=rng.choice(classes,p=probabilities[data.index.get_loc(idx)])
        imputations.append(values.astype(float))
    stacked=np.column_stack(imputations)
    diagnostics={"m":m,"method":method,"converged":converged,"observed_n":int(observed.sum()),"imputed_n":int(data.mrs_observed.isna().sum()),"death_n":int(death.sum()),"death_overwrite_count":int(np.any(stacked[death.to_numpy()]!=6,axis=1).sum()) if death.any() else 0,"mean_between_imputation_sd":float(np.mean(np.std(stacked,axis=1)))}
    return imputations,diagnostics


def binary_effect(active: pd.Series, control: pd.Series) -> dict[str,float]:
    active=pd.to_numeric(active,errors="coerce").dropna().astype(int);control=pd.to_numeric(control,errors="coerce").dropna().astype(int)
    a=int(active.sum());n1=len(active);c=int(control.sum());n0=len(control)
    rd=a/n1-c/n0 if n1 and n0 else np.nan
    try: rd_low,rd_high=confint_proportions_2indep(a,n1,c,n0,method="newcomb")
    except Exception: rd_low=rd_high=np.nan
    aa,bb,cc,dd=a,n1-a,c,n0-c
    if min(aa,bb,cc,dd)==0: aa+=.5;bb+=.5;cc+=.5;dd+=.5
    log_or=math.log((aa*dd)/(bb*cc));se=math.sqrt(1/aa+1/bb+1/cc+1/dd);odds_ratio=math.exp(log_or)
    p=fisher_exact([[a,n1-a],[c,n0-c]],alternative="two-sided").pvalue if n1 and n0 else np.nan
    return {"n_active":n1,"events_active":a,"rate_active":a/n1 if n1 else np.nan,"n_control":n0,"events_control":c,"rate_control":c/n0 if n0 else np.nan,"risk_difference":rd,"rd_ci_low":rd_low,"rd_ci_high":rd_high,"odds_ratio":odds_ratio,"or_ci_low":math.exp(log_or-1.96*se),"or_ci_high":math.exp(log_or+1.96*se),"log_or":log_or,"log_or_se":se,"p_value":p,"favorable_direction":bool(rd>0) if not np.isnan(rd) else False}


def adjusted_logistic(frame: pd.DataFrame, outcome: str, treatment: str, covariates: list[str]):
    use=frame[[outcome,treatment,*covariates]].copy();use=use[use[outcome].notna()]
    for col in covariates:
        if pd.api.types.is_numeric_dtype(use[col]): use[col]=pd.to_numeric(use[col],errors="coerce").fillna(pd.to_numeric(use[col],errors="coerce").median())
        else: use[col]=use[col].astype(str).replace({"nan":"缺失","":"缺失"})
    x=pd.get_dummies(use[[treatment,*covariates]],drop_first=True,dtype=float);x=sm.add_constant(x,has_constant="add")
    treat_col=next((c for c in x if c==treatment or c.startswith(treatment+"_")),None)
    try:
        fit=sm.GLM(use[outcome].astype(float),x,family=sm.families.Binomial()).fit()
        b=float(fit.params[treat_col]);se=float(fit.bse[treat_col]);return {"adjusted_or":math.exp(b),"ci_low":math.exp(b-1.96*se),"ci_high":math.exp(b+1.96*se),"p_value":float(fit.pvalues[treat_col]),"converged":True,"n":len(use)}
    except Exception:
        return {"adjusted_or":np.nan,"ci_low":np.nan,"ci_high":np.nan,"p_value":np.nan,"converged":False,"n":len(use)}
