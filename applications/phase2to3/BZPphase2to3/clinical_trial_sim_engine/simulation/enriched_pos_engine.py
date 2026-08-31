from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from scipy.stats import norm

from ..config_loader import normalize_config
from ..engine import run_scenario as run_step19_scenario
from ..enrichment.enriched_population_generator import load_population, summarize_enriched_population
from ..enrichment.population_filter import FILTERS, validate_filters
from ..models.outcome_models import effective_effect, get_effect_source


ROOT=Path(__file__).resolve().parents[2]
STEP21=ROOT/"outputs/step21_cross_study_enrichment_foundation"
DISCLAIMER="所有结果均为探索性和规划阶段。成功概率升高不等同于已确认富集人群。"


def normalize_step22_config(config: dict[str, Any] | None=None) -> dict[str, Any]:
    base=normalize_config(config or {})
    enrichment={"mode":"fixed_effect","filters":[],"source_mode":"phase2_2026_like","interaction_shrinkage":.75}
    enrichment.update((config or {}).get("enrichment",{}));base["enrichment"]=enrichment
    borrowing={"method":"none","historical_weight":0.0};borrowing.update((config or {}).get("borrowing",{}));base["borrowing"]=borrowing
    base["trial"]["population"]="phase2_2026_allcomers";base["trial"]["analysis_population"]=(config or {}).get("trial",{}).get("analysis_population","FAS")
    return base


def step22_config_hash(config: dict[str,Any]) -> str:
    return hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:16]


def _validate(config):
    errors=[];warnings=[]
    try: validate_filters(config["enrichment"]["filters"],config["enrichment"]["source_mode"])
    except ValueError as exc: errors.append(str(exc))
    if config["trial"].get("analysis_population") not in {"FAS","PPS"}:errors.append("主要分析人群仅支持FAS；PPS仅作支持性。")
    if config["trial"].get("analysis_population")=="PPS":warnings.append("PPS仅为支持性敏感性，不替代FAS主要分析。")
    if config["enrichment"]["mode"] not in {"fixed_effect","interaction_adjusted"}:errors.append("未知富集模拟模式。")
    if config["borrowing"]["method"]=="dynamic" and config["trial"]["dose"]!="BZP 200mg BID":errors.append("动态借用仅支持200mg探索性敏感性。")
    if config["borrowing"]["method"]=="dynamic":warnings.append("2022动态借用仅作探索性敏感性，默认仍为0%。")
    if config["enrichment"]["mode"]=="interaction_adjusted":warnings.append("交互调整结果假设负担高，不作为默认正式PoS。")
    return errors,warnings


def _interaction(config,pop):
    filters=config["enrichment"]["filters"]
    if not filters:return {"raw_log_or":0.0,"adjusted_log_or":0.0,"se":0.0,"stability_rate":1.0,"unstable":False,"sources":[]}
    dose=config["trial"]["dose"].replace("BZP ","").replace(" BID","")
    table=pd.read_csv(STEP21/"enrichment_screening/treatment_interaction_results.csv")
    total=0.0;variance=0.0;sources=[];stable=[]
    for code in filters:
        definition=FILTERS[code];rows=table[(table.study.eq("Phase2_2026"))&(table.active_dose.eq(dose))&(table.candidate.eq(definition.variable))]
        if rows.empty or not bool(rows.iloc[0].get("converged",False)):
            sources.append(f"{code}:不可估计");stable.append(0.0);continue
        r=rows.iloc[0];beta=float(r.interaction_log_or);lo=float(r.ci_low);hi=float(r.ci_high);se=(math.log(hi)-math.log(lo))/(2*1.96) if lo>0 and hi>0 else 1.0
        level=float(definition.level) if isinstance(definition.level,(int,float)) else 1.0
        prevalence=float(load_population()[definition.variable].mean())
        contrast=level-prevalence
        total+=beta*contrast;variance+=(se*max(abs(contrast),.25))**2
        direction_prob=float(max(norm.cdf(beta/se),1-norm.cdf(beta/se))) if se>0 else 1.0
        stable.append(direction_prob);sources.append(f"{code}:{beta:.3f}")
    retained=1-float(config["enrichment"].get("interaction_shrinkage",.75));adjusted=total*retained;se=math.sqrt(variance)*retained
    stability=float(np.mean(stable)) if stable else 0.0
    return {"raw_log_or":total,"adjusted_log_or":adjusted,"se":se,"stability_rate":stability,"unstable":stability<.80 or se>abs(adjusted)*2,"sources":sources}


def _borrowing(config,log_or,se):
    if config["borrowing"]["method"]!="dynamic":return {"method":"none","compatibility_metric":None,"historical_nominal_n":221,"effective_historical_n":0.0,"borrowing_weight":0.0,"posterior_log_or":log_or,"posterior_se":se,"conflict_warning":False}
    row=pd.read_csv(STEP21/"borrowing_200mg/dynamic_borrowing_results.csv").iloc[0]
    return {"method":"robust_dynamic_sensitivity","compatibility_metric":float(row.compatibility_metric),"historical_nominal_n":int(row.historical_nominal_n),"effective_historical_n":float(row.effective_historical_n),"borrowing_weight":float(row.borrowing_weight),"posterior_log_or":float(row.posterior_effect),"posterior_se":float(row.posterior_se),"conflict_warning":bool(row.conflict_warning)}


def _simulate(rng,nsim,total_n,allocation,pc,pt):
    n1=int(round(total_n*(2/3))) if allocation=="2:1" else total_n//2;n0=total_n-n1
    a=rng.binomial(n1,pt,size=nsim);c=rng.binomial(n0,pc,size=nsim);rd=a/n1-c/n0
    se=np.sqrt(np.maximum((a/n1)*(1-a/n1)/n1+(c/n0)*(1-c/n0)/n0,1e-12));z=rd/se;success=z>norm.ppf(.975)
    pos=float(success.mean());mcse=float(math.sqrt(pos*(1-pos)/nsim));return pos,mcse,[max(0,pos-1.96*mcse),min(1,pos+1.96*mcse)],float(rd.mean()),n1,n0


def _assurance(rng,nsim,total_n,allocation,pc,log_or,uncertainty):
    n1=int(round(total_n*(2/3))) if allocation=="2:1" else total_n//2;n0=total_n-n1
    true=rng.normal(log_or,max(uncertainty,.05),nsim);pt=expit(logit(pc)+true)
    se=np.sqrt(pt*(1-pt)/n1+pc*(1-pc)/n0);observed=(pt-pc)+rng.normal(0,se);success=observed/se>norm.ppf(.975)
    value=float(success.mean());return value,float(math.sqrt(value*(1-value)/nsim))


def run_enriched_scenario(scenario_config: dict[str,Any], *, reproduce_step19: bool=True) -> dict[str,Any]:
    config=normalize_step22_config(scenario_config);errors,warnings=_validate(config);key=step22_config_hash(config)
    if errors:return {"scenario_id":f"BZP22-{key[:10].upper()}","config_hash":key,"status":"blocked","errors_zh":errors,"warnings_zh":warnings,"formal_pos":None,"exploratory":True}
    pop=summarize_enriched_population(config);warnings.extend(pop["warnings_zh"])
    source_cfg=copy.deepcopy(config);source_cfg.pop("enrichment",None);source_cfg.pop("borrowing",None);source=get_effect_source(source_cfg)
    base_pc=float(source["control_outcome"]);base_rd=effective_effect(source,float(config["effect"]["shrinkage"]));base_pt=float(np.clip(base_pc+base_rd,.001,.999));base_log_or=float(logit(base_pt)-logit(base_pc))
    filters=config["enrichment"]["filters"]
    observed_pc=pop["control_response_probability_observed"]
    pc=base_pc if not filters or not np.isfinite(observed_pc) else float(np.clip(.5*base_pc+.5*observed_pc,.01,.99))
    interaction=_interaction(config,pop);used_log_or=base_log_or
    if config["enrichment"]["mode"]=="interaction_adjusted":used_log_or+=interaction["adjusted_log_or"]
    borrow=_borrowing(config,used_log_or,float(source.get("uncertainty_estimate") or .07))
    if borrow["method"]!="none":used_log_or=borrow["posterior_log_or"]
    pt=float(expit(logit(pc)+used_log_or));nsim=int(config["simulation"]["n_simulations"]);seed=int(config["simulation"]["random_seed"]);rng=np.random.default_rng(seed)
    if reproduce_step19 and not filters and config["enrichment"]["mode"]=="fixed_effect" and borrow["method"]=="none":
        old=run_step19_scenario(source_cfg,use_cache=False);pos=old.get("formal_pos");mcse=old.get("mc_standard_error");ci=old.get("mc_confidence_interval");pc=old.get("control_outcome");pt=old.get("treatment_outcome");rd=float(pt-pc);n1=old["endpoint_statistics"]["n_active"];n0=old["endpoint_statistics"]["n_control"];assurance=old.get("bayesian_assurance");assurance_se=old.get("assurance_mc_standard_error")
    else:
        pos,mcse,ci,rd,n1,n0=_simulate(rng,nsim,int(config["trial"]["total_n"]),config["trial"]["allocation"],pc,pt)
        assurance,assurance_se=_assurance(np.random.default_rng(seed+7919),nsim,int(config["trial"]["total_n"]),config["trial"]["allocation"],pc,used_log_or,float(source.get("uncertainty_estimate") or .07)) if config["simulation"]["method_type"] in {"both","bayesian_assurance"} else (None,None)
    base_rng=np.random.default_rng(seed);base_pos,_,_,_,_,_=_simulate(base_rng,nsim,int(config["trial"]["total_n"]),config["trial"]["allocation"],base_pc,base_pt)
    delta=float(pos-base_pos);control_change=float(pc-base_pc);effect_change=float((pt-pc)-base_rd)
    if not filters:reason="无富集基线"
    elif config["enrichment"]["mode"]=="fixed_effect":reason="主要为基础预后与样本构成变化"
    elif interaction["unstable"]:reason="交互信号不稳定或小亚组"
    else:reason="可能的治疗效应修饰"
    if borrow["method"]!="none":reason+="；含动态借用变化"
    if not filters:category="no clear advantage"
    elif pop["small_cell_warning"] or interaction["unstable"] and config["enrichment"]["mode"]=="interaction_adjusted":category="unstable exploratory signal"
    elif config["enrichment"]["mode"]=="fixed_effect":category="prognostic population optimization"
    elif interaction["adjusted_log_or"]>0 and interaction["stability_rate"]>=.8:category="potential predictive enrichment"
    else:category="high-assumption scenario"
    if interaction["unstable"] and config["enrichment"]["mode"]=="interaction_adjusted":warnings.append("交互估计稳定性不足，不能称为已确认富集人群。")
    return {"scenario_id":f"BZP22-{key[:10].upper()}","config_hash":key,"status":"pass_with_warnings" if warnings else "pass","formal_pos":pos,"mc_standard_error":mcse,"mc_confidence_interval":ci,"bayesian_assurance":assurance,"assurance_mc_standard_error":assurance_se,"control_outcome":pc,"treatment_outcome":pt,"risk_difference":rd,"odds_ratio":float(math.exp(used_log_or)),"treatment_effect_used":used_log_or,"effect_scale":"对数优势比","success_rule_result":"双侧p<0.05且方向有利","n_active":n1,"n_control":n0,"population_summary":pop,"enriched_population_prevalence":pop["eligible_proportion"],"projected_screen_failure_rate":pop["projected_screen_failure_rate"],"effective_sample_size":pop["effective_source_sample_size"],"interaction":interaction,"borrowing":borrow,"delta_pos":delta,"control_rate_change":control_change,"treatment_effect_change":effect_change,"reason_decomposition":reason,"recommendation_category":category,"cross_study_consistency":"200mg方向冲突" if config["trial"]["dose"]=="BZP 200mg BID" else "仅2026证据","assumption_burden":"高" if config["enrichment"]["mode"]=="interaction_adjusted" or borrow["method"]!="none" else "中" if filters else "低","warning_level":"高" if warnings else "低","warnings_zh":warnings,"model_source":source["source_file"],"model_version":"step22-enrichment-v1.0","normalized_config":config,"disclaimer_zh":DISCLAIMER,"exploratory":True}
