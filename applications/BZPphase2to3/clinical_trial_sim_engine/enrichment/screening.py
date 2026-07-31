from __future__ import annotations

import math
import numpy as np
import pandas as pd
import statsmodels.api as sm


def interaction_logistic(frame: pd.DataFrame,outcome: str,treatment: str,candidate: str):
    use=frame[[outcome,treatment,candidate]].dropna().copy();use["interaction"]=use[treatment].astype(float)*use[candidate].astype(float)
    x=sm.add_constant(use[[treatment,candidate,"interaction"]].astype(float),has_constant="add")
    try:
        fit=sm.GLM(use[outcome].astype(float),x,family=sm.families.Binomial()).fit()
        b=float(fit.params["interaction"]);se=float(fit.bse["interaction"])
        return {"interaction_log_or":b,"interaction_or":math.exp(b),"ci_low":math.exp(b-1.96*se),"ci_high":math.exp(b+1.96*se),"p_value":float(fit.pvalues["interaction"]),"converged":True,"n":len(use)}
    except Exception:
        return {"interaction_log_or":np.nan,"interaction_or":np.nan,"ci_low":np.nan,"ci_high":np.nan,"p_value":np.nan,"converged":False,"n":len(use)}


def prognostic_logistic(frame: pd.DataFrame,outcome: str,candidate: str):
    use=frame[[outcome,candidate]].dropna();x=sm.add_constant(use[[candidate]].astype(float),has_constant="add")
    try:
        fit=sm.GLM(use[outcome].astype(float),x,family=sm.families.Binomial()).fit();b=float(fit.params[candidate]);se=float(fit.bse[candidate])
        return {"prognostic_or":math.exp(b),"ci_low":math.exp(b-1.96*se),"ci_high":math.exp(b+1.96*se),"p_value":float(fit.pvalues[candidate]),"converged":True,"n":len(use)}
    except Exception:
        return {"prognostic_or":np.nan,"ci_low":np.nan,"ci_high":np.nan,"p_value":np.nan,"converged":False,"n":len(use)}
