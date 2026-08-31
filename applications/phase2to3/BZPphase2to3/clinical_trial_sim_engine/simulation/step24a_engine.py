from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from scipy.stats import norm

from ..config_loader import deep_merge, load_default_config
from ..enrichment.final_condition_builder import (
    FEATURES,
    condition_mask,
    condition_summary_zh,
    normalize_conditions,
    parse_age_range_code,
)
from ..models.canonical_effect_anchor import resolve_anchor
from ..models.final_level_interactions import condition_model, population
from ..models.nihss_continuous_trend import DOSES, OUTCOMES, model_curve

DISCLAIMER="本Demo基于Phase2_2026中可用的结构化基线变量生成探索性虚拟人群，不代表完整复刻尚未最终确定的Ⅲ期入排标准。"
WARNING="所有结果均为探索性、规划阶段，不构成确证性富集推荐或Ⅲ期成功概率预测。"
EFFECT_SOURCES={"phase2_model":"默认保守效应（原始效应的50%）","v03_design":"方案设计假设对照","custom_multiplier":"自定义：相对Phase II原始效应"}
MISSING_LABELS={code:label for code,(_,label) in OUTCOMES.items()}
SAFE_COLUMNS=["dose","age","sex_male","baseline_nihss","baseline_mrs","onset_within_24h","previous_stroke_corrected","prestroke_mrs_corrected","limb_motor_sum","bmi","mrs01_locf","mrs01_mi_probability","mrs01_nonresponder","mrs01_observed"]
BASELINE_CACHE:dict[str,dict[str,Any]]={}
MACHINE_EPS=1e-6
ENGINE_VERSION="step24ar-calibrated-v2.0"


def normalize_step24a_config(config:dict[str,Any]|None=None)->dict[str,Any]:
    raw=config or {}; base=deep_merge(load_default_config(),raw)
    base["trial"].update({"population":"phase2_2026_allcomers","analysis_population":"FAS"})
    step={"nihss_min":6,"nihss_max":20,"conditions":[],"effect_assumption":"phase2_model","effect_multiplier":1.0,"interaction_retention":.25,"analysis_method":"two_sided_risk_difference_z","information_retention":1.0,"protocol_version":"BZP2607-V0.3-planning"}
    step.update(raw.get("step24a",{})); warnings=list(step.get("normalization_warnings_zh",[])); retained=[]
    for item in normalize_conditions(step.get("conditions",[])):
        if item["feature"] in {"nihss","ocsp"}: warnings.append("NIHSS固定水平或OCSP已从当前活动富集条件中移除，相关旧条件已重置。")
        else: retained.append(item)
    step["conditions"]=retained; step["nihss_min"]=int(step["nihss_min"]); step["nihss_max"]=int(step["nihss_max"])
    step["effect_multiplier"]=float(step["effect_multiplier"]); step["interaction_retention"]=float(step["interaction_retention"]); step["information_retention"]=float(step["information_retention"])
    step["normalization_warnings_zh"]=list(dict.fromkeys(warnings)); base["step24a"]=step; base.pop("final_demo",None)
    return base


def default_step24a_config()->dict[str,Any]:
    return normalize_step24a_config({"trial":{"dose":"BZP 400mg BID","total_n":1122,"allocation":"1:1"},"missing_death":{"sensitivity_rule":"death6_multiple_imputation"},"simulation":{"method_type":"both","n_simulations":1000,"random_seed":20260717},"step24a":{"nihss_min":6,"nihss_max":20,"conditions":[],"effect_assumption":"phase2_model","effect_multiplier":1.0,"interaction_retention":.25}})


def _dose(config): return config["trial"]["dose"].replace("BZP ","").replace(" BID","")


def _age_condition_lower_bound(conditions):
    lower_bounds = []
    thresholds = {"ge65": 65, "ge70": 70, "ge75": 75, "ge80": 80}
    for item in conditions:
        if item["feature"] != "age":
            continue
        for level in item["levels"]:
            if level in thresholds:
                lower_bounds.append(thresholds[level])
                continue
            bounds = parse_age_range_code(str(level))
            if bounds is not None:
                lower_bounds.append(bounds[0])
    return min(lower_bounds) if lower_bounds else None


def validate_step24a_config(config):
    cfg=normalize_step24a_config(config); step=cfg["step24a"]; errors=[]; dose=_dose(cfg); n=int(cfg["trial"]["total_n"])
    if dose not in DOSES: errors.append("剂量必须为200、400或600 mg BID。")
    if not 200<=n<=3000: errors.append("目标随机入组样本量N必须在200至3000之间。")
    if cfg["trial"]["allocation"]=="1:1" and n%2: errors.append("1:1随机分配要求总样本量N为偶数，请修正后运行。")
    if not 6<=step["nihss_min"]<=20 or not 6<=step["nihss_max"]<=20: errors.append("基线NIHSS最低分和最高分必须在6至20之间。")
    if step["nihss_min"]>step["nihss_max"]: errors.append("基线NIHSS最低分不能高于最高分。")
    if cfg["missing_death"]["sensitivity_rule"] not in OUTCOMES: errors.append("缺失处理方法不在当前工具支持列表中。")
    if step["effect_assumption"] not in EFFECT_SOURCES: errors.append("治疗效应假设来源无效。")
    if step["effect_assumption"]=="v03_design" and dose!="400mg": errors.append("V0.3方案设计假设仅适用于400 mg BID。")
    if not .5<=step["effect_multiplier"]<=1.5: errors.append("相对Phase II原始观察效应系数必须在50%至150%之间。")
    if not 0<=step["interaction_retention"]<=1: errors.append("NIHSS交互保留比例必须在0%至100%之间。")
    if any(x["feature"] in {"nihss","ocsp"} for x in step["conditions"]): errors.append("NIHSS固定水平和OCSP不能作为当前活动富集条件。")
    if _age_condition_lower_bound(step["conditions"]) == 80: errors.append("≥80岁或80–80岁区间在Phase II FAS中仅2例且所选剂量组无来源，仅可在人群洞察页查看，不能运行模拟。")
    return errors


def config_hash(config):
    payload=json.dumps(normalize_step24a_config(config),ensure_ascii=False,sort_keys=True,separators=(",",":")); return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _eligible_source(config):
    data=population(); step=config["step24a"]; mask=data.baseline_nihss.between(step["nihss_min"],step["nihss_max"])
    if step["conditions"]: mask &= condition_mask(data,step["conditions"])
    return data,data.loc[mask].copy()


def _support(config,eligible):
    dose=_dose(config); outcome=OUTCOMES[config["missing_death"]["sensitivity_rule"]][0]; active=eligible[eligible.dose.eq(dose)]; placebo=eligible[eligible.dose.eq("placebo")]
    prevalence=len(eligible)/len(population()); ae=float(active[outcome].sum(skipna=True)); pe=float(placebo[outcome].sum(skipna=True))
    separation=bool(len(active) and len(placebo) and any(v<=1e-12 for v in (ae,len(active)-ae,pe,len(placebo)-pe)))
    if len(eligible)==0: status,warning,extra="不可估计","所选NIHSS范围及其他条件在Phase2_2026 FAS中无来源病例。",True
    elif len(eligible)<20 or len(active)<5 or len(placebo)<5: status,warning,extra="模型外推敏感性","来源样本明显稀疏；仅显示模型外推敏感性，不形成数据支持的富集PoS或推荐。",True
    elif len(eligible)<40 or len(active)<10 or len(placebo)<10: status,warning,extra="数据有限","来源样本有限；保留强警示。",False
    elif separation: status,warning,extra="数据有限","来源子集存在零应答单元格；惩罚趋势结果需谨慎解释。",False
    else: status,warning,extra="数据支持较充分","",False
    age_lower = _age_condition_lower_bound(config["step24a"]["conditions"])
    if age_lower is not None and age_lower >= 75 and status == "数据支持较充分":
        status, warning = "数据有限", "年龄条件从75岁及以上起始，Phase II来源有限；结果仅作区间敏感性探索。"
    return {"eligible_n":len(eligible),"selected_dose_n":len(active),"placebo_n":len(placebo),"eligible_proportion":prevalence,"treatment_responders":ae,"treatment_nonresponders":len(active)-ae,"placebo_responders":pe,"placebo_nonresponders":len(placebo)-pe,"missing_endpoint_n":int(eligible[outcome].isna().sum()),"severe_separation":separation,"support_status":status,"extrapolation_flag":extra,"support_warning_zh":warning}


def preview_source_support(config):
    cfg=normalize_step24a_config(config); errors=validate_step24a_config(cfg)
    if errors:return {"status":"blocked","errors_zh":errors}
    _,eligible=_eligible_source(cfg); support=_support(cfg,eligible); n=int(cfg["trial"]["total_n"])
    support.update({"status":"pass_with_warnings" if support["support_warning_zh"] else "pass","target_randomized_n":n,"estimated_screened_n":math.ceil(n/support["eligible_proportion"]) if support["eligible_proportion"] else None,"nihss_interval_zh":f"{cfg['step24a']['nihss_min']}–{cfg['step24a']['nihss_max']}分","condition_summary_zh":condition_summary_zh(cfg["step24a"]["conditions"])})
    return support


def generate_target_population(config,seed=None):
    cfg=normalize_step24a_config(config); _,eligible=_eligible_source(cfg); n=int(cfg["trial"]["total_n"])
    if eligible.empty:return pd.DataFrame(columns=SAFE_COLUMNS+["randomized_arm"])
    rng=np.random.default_rng(int(seed if seed is not None else cfg["simulation"]["random_seed"])); eligible=eligible.sort_values(["baseline_nihss","age","baseline_mrs"]).reset_index(drop=True)
    quotient,remainder=divmod(n,len(eligible)); indices=np.tile(np.arange(len(eligible)),quotient)
    if remainder: indices=np.concatenate([indices,np.sort(rng.choice(len(eligible),size=remainder,replace=False))])
    sampled=eligible.iloc[indices][SAFE_COLUMNS].reset_index(drop=True).copy(); order=np.argsort(sampled.baseline_nihss.to_numpy()+rng.uniform(-.01,.01,len(sampled)))
    n_active=n//2 if cfg["trial"]["allocation"]=="1:1" else int(round(n*2/3)); arms=np.empty(n,dtype=object)
    if cfg["trial"]["allocation"]=="1:1": arms[order[::2]]="试验组"; arms[order[1::2]]="安慰剂组"
    else: arms[order[:n_active]]="试验组"; arms[order[n_active:]]="安慰剂组"
    sampled["randomized_arm"]=arms; return sampled.iloc[rng.permutation(n)].reset_index(drop=True)


def _weighted_offset(probabilities,target,weights):
    logits=logit(np.clip(probabilities,MACHINE_EPS,1-MACHINE_EPS)); weights=np.asarray(weights,float); weights/=weights.sum(); low,high=-8.,8.
    for _ in range(80):
        mid=(low+high)/2
        if np.average(expit(logits+mid),weights=weights)<target: low=mid
        else: high=mid
    return (low+high)/2


def centered_trend(dose,missing_method):
    curve,draws,model=model_curve(dose,missing_method); weights=population().baseline_nihss.value_counts().reindex(range(6,21),fill_value=0).to_numpy(float); weights/=weights.sum()
    raw=curve.log_odds_ratio.to_numpy(float); mean=float(np.average(raw,weights=weights)); centered=raw-mean
    draw_raw=draws[:,:,4]; draw_means=np.average(draw_raw,axis=1,weights=weights); centered_draws=draw_raw-draw_means[:,None]
    return curve,draws,model,centered,centered_draws,{"uncentered_weighted_mean":mean,"centered_weighted_mean":float(np.average(centered,weights=weights)),"weights":weights}


def _curve_probabilities(config,curve,centered,anchor,additional_log_or=0.):
    weights=population().baseline_nihss.value_counts().reindex(range(6,21),fill_value=0).to_numpy(float); raw_p0=curve.placebo_probability.to_numpy(float); offset=_weighted_offset(raw_p0,float(anchor["control_event_probability"]),weights)
    p0=expit(logit(np.clip(raw_p0,MACHINE_EPS,1-MACHINE_EPS))+offset); contribution=centered*float(config["step24a"]["interaction_retention"])
    p1=expit(logit(np.clip(p0,MACHINE_EPS,1-MACHINE_EPS))+float(anchor["log_odds_ratio"])+contribution+additional_log_or)
    return p0,p1,contribution


def _patient_probabilities(config,generated,curve,centered,anchor,additional_log_or=0.):
    p0_curve,p1_curve,contribution=_curve_probabilities(config,curve,centered,anchor,additional_log_or); idx=generated.baseline_nihss.astype(int).to_numpy()-6
    return p0_curve[idx],p1_curve[idx],contribution[idx]


def _simulate(seed,nsim,total_n,allocation,pc,pt):
    rng=np.random.default_rng(seed); n1=total_n//2 if allocation=="1:1" else int(round(total_n*2/3)); n0=total_n-n1; successes=0
    for start in range(0,nsim,1000):
        size=min(1000,nsim-start); a=rng.binomial(n1,pt,size); c=rng.binomial(n0,pc,size); pa=a/n1; pctrl=c/n0; se=np.sqrt(np.maximum(pa*(1-pa)/n1+pctrl*(1-pctrl)/n0,1e-12)); successes+=int(np.sum((pa-pctrl)/se>norm.ppf(.975)))
    pos=successes/nsim; return float(pos),float(math.sqrt(pos*(1-pos)/nsim))


def _bayesian(config,generated,draws,centered_draws,anchor,additional_log_or):
    nsim=int(config["simulation"]["n_simulations"]); seed=int(config["simulation"]["random_seed"]); rng=np.random.default_rng(seed+7919); active=generated.randomized_arm.eq("试验组").to_numpy(); control=~active; ai=generated.loc[active,"baseline_nihss"].astype(int).to_numpy()-6; ci=generated.loc[control,"baseline_nihss"].astype(int).to_numpy()-6
    selected=rng.integers(0,len(draws),nsim); base_draw=rng.normal(float(anchor["log_odds_ratio"]),float(anchor["log_odds_ratio_se"]),nsim); score_weights=population().baseline_nihss.value_counts().reindex(range(6,21),fill_value=0).to_numpy(float); pa=np.empty(nsim); pc=np.empty(nsim); retention=float(config["step24a"]["interaction_retention"])
    for draw_id in np.unique(selected):
        mask=selected==draw_id; raw_p0=draws[draw_id,:,0]; offset=_weighted_offset(raw_p0,float(anchor["control_event_probability"]),score_weights); p0_curve=expit(logit(np.clip(raw_p0,MACHINE_EPS,1-MACHINE_EPS))+offset); pc[mask]=p0_curve[ci].mean(); dev=centered_draws[draw_id]*retention; p1_matrix=expit(logit(np.clip(p0_curve[ai],MACHINE_EPS,1-MACHINE_EPS))[None,:]+base_draw[mask,None]+dev[ai][None,:]+additional_log_or); pa[mask]=p1_matrix.mean(axis=1)
    n1=active.sum(); n0=control.sum(); a=rng.binomial(n1,pa); c=rng.binomial(n0,pc); oa=a/n1; oc=c/n0; se=np.sqrt(np.maximum(oa*(1-oa)/n1+oc*(1-oc)/n0,1e-12)); success=(oa-oc)/se>norm.ppf(.975); value=float(success.mean()); return value,float(math.sqrt(value*(1-value)/nsim))


def _other_feature_contribution(config):
    dose=_dose(config); missing=config["missing_death"]["sensitivity_rule"]; retention=float(config["step24a"]["interaction_retention"]); total=0.; rows=[]; warnings=[]; usable=True
    for condition in config["step24a"]["conditions"]:
        model=condition_model(condition["feature"],condition["levels"],dose,missing); raw=float(model["coefficient_used"]) if pd.notna(model["coefficient_used"]) else None; contribution=raw*retention*(1-float(model["feature_prevalence"])) if raw is not None and bool(model["usable_interaction"]) else None
        item={"feature":condition["feature"],"feature_label_zh":FEATURES[condition["feature"]].label_zh,"levels":condition["levels"],"raw_interaction":raw,"retained_centered_contribution":contribution,"data_support_status":model["data_support_status"],"warning_zh":"" if pd.isna(model["warning_zh"]) else str(model["warning_zh"])}; rows.append(item)
        if contribution is None: usable=False
        else: total+=contribution
        if item["warning_zh"]: warnings.append(f"{item['feature_label_zh']}：{item['warning_zh']}")
    active_features={x["feature"] for x in config["step24a"]["conditions"]}
    if active_features.intersection({"motor","screening_mrs"}): warnings.append("NIHSS与肢体运动缺损或本次卒中筛选期mRS可能共同反映卒中严重程度，组合结果可能存在信息重叠。")
    return total,rows,warnings,usable


def _population_hash(frame):
    cols=["dose","age","sex_male","baseline_nihss","baseline_mrs","randomized_arm"]; return hashlib.sha256(pd.util.hash_pandas_object(frame[cols],index=False).to_numpy().tobytes()).hexdigest()[:16]


def _baseline_key(config,anchor):
    fields={"dose":_dose(config),"N":config["trial"]["total_n"],"allocation":config["trial"]["allocation"],"endpoint":config["endpoint"]["primary_endpoint"],"missing_method":config["missing_death"]["sensitivity_rule"],"effect_source":config["step24a"]["effect_assumption"],"custom_multiplier":config["step24a"]["effect_multiplier"],"analysis_method":config["step24a"]["analysis_method"],"seed":config["simulation"]["random_seed"],"n_simulations":config["simulation"]["n_simulations"],"information_retention":config["step24a"]["information_retention"],"protocol_version":config["step24a"]["protocol_version"],"anchor_hash":anchor["applied_anchor_hash"]}
    return hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:20]


def shared_all_population_baseline(config):
    anchor=resolve_anchor(_dose(config),config["missing_death"]["sensitivity_rule"],config["step24a"]["effect_assumption"],config["step24a"]["effect_multiplier"]); key=_baseline_key(config,anchor)
    if key in BASELINE_CACHE:return copy.deepcopy(BASELINE_CACHE[key])
    base=copy.deepcopy(config); base["step24a"].update({"nihss_min":6,"nihss_max":20,"conditions":[]}); generated=generate_target_population(base); curve,draws,model,centered,centered_draws,centering=centered_trend(_dose(base),base["missing_death"]["sensitivity_rule"]); p0,p1,_=_patient_probabilities(base,generated,curve,centered,anchor); active=generated.randomized_arm.eq("试验组").to_numpy(); control=~active; pt=float(p1[active].mean()); pc=float(p0[control].mean()); nsim=int(base["simulation"]["n_simulations"]); mc,mcse=_simulate(int(base["simulation"]["random_seed"]),nsim,len(generated),base["trial"]["allocation"],pc,pt); assurance,ase=_bayesian(base,generated,draws,centered_draws,anchor,0.)
    result={"cache_key":key,"monte_carlo_pos":mc,"bayesian_assurance":assurance,"mc_standard_error":mcse,"assurance_standard_error":ase,"control_probability":pc,"treatment_probability":pt,"analysis_method":base["step24a"]["analysis_method"],"n_simulations":nsim,"generated_n":len(generated),"target_population_hash":_population_hash(generated),"effect_anchor_id":anchor["anchor_id"],"effect_anchor_hash":anchor["applied_anchor_hash"],"base_control_rate":anchor["control_event_probability"],"base_active_rate":anchor["active_event_probability"],"base_log_odds_ratio":anchor["log_odds_ratio"],"trend_model":model["model_form"],"centered_weighted_mean":centering["centered_weighted_mean"]}
    BASELINE_CACHE[key]=copy.deepcopy(result); return result


def _recommendation(support,delta,mcse,sign_stability,screening_ratio):
    if support["eligible_n"]==0:return "不可估计"
    if support["extrapolation_flag"]:return "模型外推敏感性"
    if support["eligible_n"]<40 or support["selected_dose_n"]<10 or support["placebo_n"]<10:return "数据有限，暂不形成推荐"
    if sign_stability<.70 or delta is None or delta<=max(.01,2*mcse):return "可作为敏感性探索" if delta is not None and delta>0 else "数据有限，暂不形成推荐"
    if screening_ratio>10:return "可作为敏感性探索"
    return "可优先探索"


def run_step24a_scenario(scenario_config):
    config=normalize_step24a_config(scenario_config); key=config_hash(config); errors=validate_step24a_config(config)
    if errors:return {"scenario_id":f"BZP24AR-{key[:10].upper()}","config_hash":key,"status":"blocked","errors_zh":errors,"exploratory":True}
    _,eligible=_eligible_source(config); support=_support(config,eligible); anchor=resolve_anchor(_dose(config),config["missing_death"]["sensitivity_rule"],config["step24a"]["effect_assumption"],config["step24a"]["effect_multiplier"]); baseline=shared_all_population_baseline(config); warnings=list(config["step24a"].get("normalization_warnings_zh",[])); n=int(config["trial"]["total_n"])
    if support["support_warning_zh"]:warnings.append(support["support_warning_zh"])
    common={"scenario_id":f"BZP24AR-{key[:10].upper()}","config_hash":key,"target_randomized_n":n,"all_population_pos":baseline["monte_carlo_pos"],"all_population_bayesian_assurance":baseline["bayesian_assurance"],"all_population_source_n":len(population()),"all_population_eligible_proportion":1.0,"all_population_estimated_screened_n":n,"eligible_n":support["eligible_n"],"selected_dose_n":support["selected_dose_n"],"placebo_n":support["placebo_n"],"eligible_proportion":support["eligible_proportion"],"estimated_screened_n":math.ceil(n/support["eligible_proportion"]) if support["eligible_proportion"] else None,"evidence_support_status":support["support_status"],"extrapolation_flag":support["extrapolation_flag"],"nihss_interval_zh":f"{config['step24a']['nihss_min']}–{config['step24a']['nihss_max']}分","condition_summary_zh":condition_summary_zh(config["step24a"]["conditions"]),"source_support":support,"shared_baseline":baseline,"effect_anchor_id":anchor["anchor_id"],"effect_anchor_hash":anchor["applied_anchor_hash"],"base_control_rate":anchor["control_event_probability"],"base_active_rate":anchor["active_event_probability"],"base_log_odds_ratio":anchor["log_odds_ratio"],"required_warning_zh":WARNING,"phase3_alignment_disclaimer_zh":DISCLAIMER,"normalized_config":config,"exploratory":True,"death_as_mrs6":True,"borrowing_weight_2022":0,"model_version":ENGINE_VERSION}
    if support["eligible_n"]==0:return common|{"status":"pass_with_warnings","generated_randomized_n":0,"enriched_population_pos":None,"monte_carlo_pos":None,"bayesian_assurance":None,"delta_pos":None,"treatment_probability":None,"control_probability":None,"risk_difference":None,"odds_ratio":None,"candidate_direction_label":"不可估计","target_population_hash":None,"sensitivity_extrapolated_pos":None,"warnings_zh":list(dict.fromkeys(warnings+["零数据范围返回NA，未生成虚拟患者。"])) ,"interaction_components":[],"boundary_status":"无科学性截断"}
    generated=generate_target_population(config); curve,draws,model,centered,centered_draws,centering=centered_trend(_dose(config),config["missing_death"]["sensitivity_rule"]); other,components,component_warnings,usable=_other_feature_contribution(config); warnings+=component_warnings
    if not usable:return common|{"status":"pass_with_warnings","generated_randomized_n":len(generated),"enriched_population_pos":None,"monte_carlo_pos":None,"bayesian_assurance":None,"delta_pos":None,"candidate_direction_label":"不可估计","target_population_hash":_population_hash(generated),"warnings_zh":list(dict.fromkeys(warnings+["其他活动特征交互不可估计；未回退到合并效应。"])) ,"interaction_components":components,"boundary_status":"无科学性截断"}
    p0,p1,patient_contribution=_patient_probabilities(config,generated,curve,centered,anchor,other); active=generated.randomized_arm.eq("试验组").to_numpy(); control=~active; pt=float(p1[active].mean()); pc=float(p0[control].mean()); mc,mcse=_simulate(int(config["simulation"]["random_seed"]),int(config["simulation"]["n_simulations"]),n,config["trial"]["allocation"],pc,pt); assurance,ase=_bayesian(config,generated,draws,centered_draws,anchor,other); primary=None if support["extrapolation_flag"] else mc; primary_assurance=None if support["extrapolation_flag"] else assurance; delta=None if primary is None else primary-baseline["monte_carlo_pos"]
    selected_scores=np.arange(config["step24a"]["nihss_min"],config["step24a"]["nihss_max"]+1)-6; selected_draw=centered_draws[:,selected_scores]; point_sign=np.sign(float(np.mean(centered[selected_scores]))+float(anchor["log_odds_ratio"])); draw_sign=np.sign(np.mean(selected_draw,axis=1)*float(config["step24a"]["interaction_retention"])+float(anchor["log_odds_ratio"])); sign_stability=float(np.mean(draw_sign==point_sign)); recommendation=_recommendation(support,delta,mcse,sign_stability,(1/support["eligible_proportion"]) if support["eligible_proportion"] else math.inf)
    if model["model_form"] == "no_interaction" and recommendation == "可优先探索":
        recommendation = "可作为敏感性探索"
        warnings.append("未检出满足稳定性标准的NIHSS治疗效应修饰；范围差异仅作为预后构成与设计敏感性，不升级为优先富集建议。")
    if support["extrapolation_flag"]:warnings.append("显示值仅为原始惩罚趋势的模型外推敏感性，不纳入推荐排序。")
    pop_hash=_population_hash(generated); machine_trigger=bool(np.any((curve.unconstrained_placebo_probability<MACHINE_EPS)|(curve.unconstrained_placebo_probability>1-MACHINE_EPS)|(curve.unconstrained_treatment_probability<MACHINE_EPS)|(curve.unconstrained_treatment_probability>1-MACHINE_EPS)))
    return common|{"status":"pass_with_warnings" if warnings else "pass","generated_randomized_n":len(generated),"enriched_population_pos":primary,"monte_carlo_pos":primary,"sensitivity_extrapolated_pos":mc if support["extrapolation_flag"] else None,"delta_pos":delta,"mc_standard_error":mcse,"bayesian_assurance":primary_assurance,"sensitivity_extrapolated_assurance":assurance if support["extrapolation_flag"] else None,"assurance_standard_error":ase,"treatment_probability":pt,"control_probability":pc,"risk_difference":pt-pc,"odds_ratio":float(np.exp(logit(pt)-logit(pc))),"candidate_direction_label":recommendation,"trend_model":model["model_form"],"trend_model_reason_zh":model["selection_reason_zh"],"trend_uncertainty_propagated":True,"base_effect_uncertainty_propagated":True,"interaction_sign_stability":sign_stability,"nihss_centered_weighted_mean":centering["centered_weighted_mean"],"selected_range_mean_centered_contribution":float(patient_contribution.mean()),"target_population_hash":pop_hash,"monte_carlo_population_hash":pop_hash,"bayesian_population_hash":pop_hash,"monte_carlo_effect_anchor_hash":anchor["applied_anchor_hash"],"bayesian_effect_anchor_hash":anchor["applied_anchor_hash"],"interaction_components":components,"other_feature_log_or_contribution":other,"multifeature_approximation":bool(config["step24a"]["conditions"]),"all_generated_conditions_satisfied":bool(generated.baseline_nihss.between(config["step24a"]["nihss_min"],config["step24a"]["nihss_max"]).all() and (not config["step24a"]["conditions"] or condition_mask(generated,config["step24a"]["conditions"]).all())),"boundary_status":"仅1e-6机器数值稳定；无0.01概率或固定OR科学边界","machine_stability_triggered":machine_trigger,"warnings_zh":list(dict.fromkeys(warnings))}
