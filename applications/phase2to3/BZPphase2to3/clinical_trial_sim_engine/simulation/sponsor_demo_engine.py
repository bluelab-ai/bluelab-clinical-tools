from __future__ import annotations

import copy
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit,logit
from scipy.stats import norm

from ..config_loader import normalize_config
from ..enrichment.population_filter import FILTERS,apply_filters,validate_filters
from ..models.outcome_models import effective_effect,get_effect_source
from ..models.step23_interactions import coefficient_row,calibrated_interaction_component


ROOT=Path(__file__).resolve().parents[2];ASSET=ROOT/"clinical_trial_sim_engine/assets/private/step22_phase2_2026_population.parquet";CENTER_REGISTRY=ROOT/"outputs/step23_sponsor_demo/center_mapping/center_id_name_mapping.csv"
OUTCOME={"death6_locf_like":"mrs01_locf","death6_multiple_imputation":"mrs01_mi_probability","death6_conservative_nonresponder":"mrs01_nonresponder","observed_available_case":"mrs01_observed"}
SHORT_WARNING="本结果用于候选Ⅲ期入组人群的探索性比较，PoS取决于Ⅱ期数据、交互效应及所选择的Ⅲ期效应假设。"


@lru_cache(maxsize=1)
def population_asset():return pd.read_parquet(ASSET)


def normalize_demo_config(config: dict[str,Any]|None=None)->dict[str,Any]:
    base=normalize_config(config or {});base["trial"]["population"]="phase2_2026_allcomers";base["trial"]["analysis_population"]=(config or {}).get("trial",{}).get("analysis_population","FAS")
    base["effect"]["shrinkage"]=.5;base["effect"]["borrowing_weight_2022"]=0
    demo={"phase3_effect_multiplier":1.0,"interaction_retention_ratio":.25,"enrichment_mode":"interaction","filters":[],"center_mode":"all","selected_center_ids":[]};demo.update((config or {}).get("demo",{}));base["demo"]=demo
    return base


def demo_config_hash(config):return hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:16]


def _validate(config):
    d=config["demo"];errors=[];warnings=[]
    if not .5<=float(d["phase3_effect_multiplier"])<=1.5:errors.append("Ⅲ期相对Ⅱ期效应假设系数必须在50%至150%之间。")
    if not 0<=float(d["interaction_retention_ratio"])<=1:errors.append("亚组交互效应保留比例必须在0%至100%之间。")
    if d["enrichment_mode"] not in {"interaction","composition_only"}:errors.append("未知患者富集模式。")
    try:validate_filters(d.get("filters",[]),"phase2_2026_like")
    except ValueError as exc:errors.append(str(exc))
    centers=[str(x).zfill(2) for x in d.get("selected_center_ids",[])]
    known=set(population_asset().site_id.astype(str).str.zfill(2))
    if any(x not in known for x in centers):errors.append("所选中心不在结构化中心注册表中。")
    if d["center_mode"]=="all" and centers:warnings.append("全中心模式忽略已传入的中心编号。")
    if d["center_mode"] in {"single","multiple"} and not centers:errors.append("中心情景已启用但未选择中心。")
    if d["center_mode"]=="single" and len(centers)!=1:errors.append("单中心模式必须且只能选择一个中心。")
    if d["center_mode"]=="multiple" and len(centers)<2:errors.append("多中心模式至少选择两个中心。")
    return errors,warnings


def _center_frame(config):
    frame=population_asset();d=config["demo"];centers=[] if d["center_mode"]=="all" else [str(x).zfill(2) for x in d.get("selected_center_ids",[])]
    selected=frame if not centers else frame[frame.site_id.astype(str).str.zfill(2).isin(centers)]
    if selected.empty:raise ValueError("所选中心没有FAS来源受试者。")
    counts=selected.groupby("dose").size();dose=config["trial"]["dose"].replace("BZP ","").replace(" BID","");warnings=[]
    if len(selected)<10:warnings.append("所选中心合计FAS少于10例，结果波动较大。")
    active_n=int(counts.get(dose,0));placebo_n=int(counts.get("placebo",0))
    if active_n<3 or placebo_n<3:warnings.append("所选剂量或安慰剂来源样本少于3例，中心情景为强警示。")
    elif active_n<5 or placebo_n<5:warnings.append("所选剂量或安慰剂来源样本少于5例，中心情景为中度警示。")
    return selected,centers,warnings


def _population_summary(config,center_frame,filters):
    selected,_=apply_filters(center_frame,filters);prevalence=len(selected)/len(center_frame);outcome=OUTCOME[config["missing_death"]["sensitivity_rule"]];dose=config["trial"]["dose"].replace("BZP ","").replace(" BID","")
    pc=selected.loc[selected.dose.eq("placebo"),outcome].mean();pt=selected.loc[selected.dose.eq(dose),outcome].mean();warnings=[]
    if len(selected)<40:warnings.append("富集后II期来源样本少于40例。")
    if prevalence<.1:warnings.append("符合富集条件的II期受试者比例低于10%。")
    return {"source_n":len(selected),"center_source_n":len(center_frame),"eligible_proportion":prevalence,"screen_failure_rate":1-prevalence,"observed_control_rate":float(pc) if pd.notna(pc) else None,"observed_active_rate":float(pt) if pd.notna(pt) else None,"warnings":warnings}


def _arm_sizes(total_n,allocation):n1=int(round(total_n*2/3)) if allocation=="2:1" else total_n//2;return n1,total_n-n1
def _simulate(seed,nsim,total_n,allocation,pc,pt):
    rng=np.random.default_rng(seed);n1,n0=_arm_sizes(total_n,allocation);a=rng.binomial(n1,pt,nsim);c=rng.binomial(n0,pc,nsim);rd=a/n1-c/n0;se=np.sqrt(np.maximum((a/n1)*(1-a/n1)/n1+(c/n0)*(1-c/n0)/n0,1e-12));success=rd/se>norm.ppf(.975);pos=float(success.mean());mcse=float(math.sqrt(pos*(1-pos)/nsim));return pos,mcse,[max(0,pos-1.96*mcse),min(1,pos+1.96*mcse)],float(rd.mean())
def _assurance(seed,nsim,total_n,allocation,pc,log_or,uncertainty):
    rng=np.random.default_rng(seed+7919);n1,n0=_arm_sizes(total_n,allocation);true=rng.normal(log_or,max(uncertainty,.05),nsim);pt=expit(logit(pc)+true);se=np.sqrt(pt*(1-pt)/n1+pc*(1-pc)/n0);observed=(pt-pc)+rng.normal(0,se);success=observed/se>norm.ppf(.975);value=float(success.mean());return value,float(math.sqrt(value*(1-value)/nsim))


def _rates_and_effect(config,frame,filters,base_pc,base_log_or):
    summary=_population_summary(config,frame,filters);observed_pc=summary["observed_control_rate"]
    pc=base_pc if not filters and len(frame)==len(population_asset()) else float(np.clip(.5*base_pc+.5*(observed_pc if observed_pc is not None else base_pc),.001,.999))
    multiplier=float(config["demo"]["phase3_effect_multiplier"]);log_or=base_log_or*multiplier;components=[]
    if config["demo"]["enrichment_mode"]=="interaction":
        dose=config["trial"]["dose"].replace("BZP ","").replace(" BID","");missing=config["missing_death"]["sensitivity_rule"]
        for code in filters:
            row=coefficient_row(dose,missing,code);component=calibrated_interaction_component(row,float(config["demo"]["interaction_retention_ratio"]));log_or+=component;components.append({"filter_code":code,"selected_level":float(row.selected_level),"prevalence":float(row.feature_prevalence),"raw_beta_t":float(row.raw_treatment_coefficient),"raw_beta_tx":float(row.raw_interaction_coefficient),"retained_centered_component":component,"converged":bool(row.model_converged),"warning":str(row.warning_status)})
    pt=float(expit(logit(pc)+log_or));return summary,pc,pt,log_or,components


def _direction_label(delta,eligible,warnings,components):
    severe=any("少于3" in x or "低于10%" in x for x in warnings) or any(x["warning"]!="none" for x in components)
    if severe:return "结果波动较大"
    if abs(delta)<.03:return "PoS变化较小"
    if delta>=.10 and eligible>=.10:return "优先探索"
    if delta>=.03:return "可考虑"
    return "结果波动较大"


def run_demo_scenario(scenario_config:dict[str,Any])->dict[str,Any]:
    config=normalize_demo_config(scenario_config);key=demo_config_hash(config);errors,warnings=_validate(config)
    if errors:return {"scenario_id":f"BZP23-{key[:10].upper()}","config_hash":key,"status":"blocked","errors_zh":errors,"warnings_zh":warnings,"exploratory":True}
    center_frame,centers,center_warnings=_center_frame(config);warnings+=center_warnings;source_cfg=copy.deepcopy(config);source_cfg.pop("demo",None);source=get_effect_source(source_cfg);base_pc=float(source["control_outcome"]);base_rd=effective_effect(source,.5);base_pt=float(np.clip(base_pc+base_rd,.001,.999));base_log_or=float(logit(base_pt)-logit(base_pc))
    full_summary,full_pc,full_pt,full_log_or,_=_rates_and_effect(config,center_frame,[],base_pc,base_log_or);filters=config["demo"]["filters"];enriched_summary,pc,pt,log_or,components=_rates_and_effect(config,center_frame,filters,base_pc,base_log_or);warnings+=enriched_summary["warnings"]
    nsim=int(config["simulation"]["n_simulations"]);seed=int(config["simulation"]["random_seed"]);total=int(config["trial"]["total_n"]);allocation=config["trial"]["allocation"]
    full_mc,full_mcse,full_ci,_=_simulate(seed,nsim,total,allocation,full_pc,full_pt);enr_mc,enr_mcse,enr_ci,mean_rd=_simulate(seed,nsim,total,allocation,pc,pt);full_bayes,full_bse=_assurance(seed,nsim,total,allocation,full_pc,full_log_or,float(source.get("uncertainty_estimate") or .07));enr_bayes,enr_bse=_assurance(seed,nsim,total,allocation,pc,log_or,float(source.get("uncertainty_estimate") or .07))
    method=config["simulation"]["method_type"];full_display=full_bayes if method=="bayesian_assurance" else full_mc;enr_display=enr_bayes if method=="bayesian_assurance" else enr_mc;delta=enr_display-full_display;label=_direction_label(delta,enriched_summary["eligible_proportion"],warnings,components)
    center_names=[]
    if centers and CENTER_REGISTRY.exists():
        cr=pd.read_csv(CENTER_REGISTRY,dtype={"SITEID":str});center_names=cr[cr.SITEID.astype(str).str.zfill(2).isin(centers)].display_name.tolist()
    return {"scenario_id":f"BZP23-{key[:10].upper()}","config_hash":key,"status":"pass_with_warnings" if warnings else "pass","full_population_pos":full_display,"enriched_population_pos":enr_display,"delta_pos":delta,"eligible_proportion":enriched_summary["eligible_proportion"],"screen_failure_rate":enriched_summary["screen_failure_rate"],"monte_carlo_pos":enr_mc,"full_monte_carlo_pos":full_mc,"mc_standard_error":enr_mcse,"mc_confidence_interval":enr_ci,"bayesian_assurance":enr_bayes,"full_bayesian_assurance":full_bayes,"assurance_mc_standard_error":enr_bse,"control_probability":pc,"treatment_probability":pt,"risk_difference":pt-pc,"odds_ratio":math.exp(log_or),"base_treatment_log_or":base_log_or,"final_subgroup_log_or":log_or,"phase3_effect_multiplier":float(config["demo"]["phase3_effect_multiplier"]),"interaction_retention_ratio":float(config["demo"]["interaction_retention_ratio"]),"interaction_components":components,"enrichment_mode":config["demo"]["enrichment_mode"],"filters":filters,"filter_labels_zh":[FILTERS[x].label_zh for x in filters],"center_mode":config["demo"]["center_mode"],"selected_center_ids":centers,"selected_center_names":center_names,"center_source_n":len(center_frame),"center_scenario_method":"所选中心协变量/基础风险构成 + 剂量特异合并交互","candidate_direction_label":label,"warnings_zh":warnings,"short_warning_zh":SHORT_WARNING,"borrowing_weight_2022":0,"death_as_mrs6":True,"model_source":source["source_file"],"model_version":"step23-sponsor-demo-v1.0","normalized_config":config,"exploratory":True}
