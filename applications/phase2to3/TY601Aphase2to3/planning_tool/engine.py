"""Tapgrel multi-endpoint exploratory Phase III planning engine.

Observed Phase II evidence, modeled transport and simulated planning outputs are kept
separate. No result is a prediction or guarantee of Phase III success.
"""
from __future__ import annotations
import copy,hashlib,json,math
from functools import lru_cache
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
ENGINE_VERSION="tapgrel-multi-endpoint-dynamic-4.0"
DATA_VERSION="TY601A-P2_multi_endpoint_web_2026-08-21"
CONTRACT_PATH=DATA/"phase3_dynamic_parameter_contract.json"
CONTROL_ARM="氯吡格雷组"

SOURCE_COLUMNS={
 "nominal_v8_missing_nonresponder":"mrs01_main_nonresponder",
 "available_case":"mrs01_observed",
 "strict_d85_d95_missing_nonresponder":"mrs01_strict_window_nonresponder",
 "locf_like_through_d95":"mrs01_locf_like",
}

PRIMARY_ENDPOINTS={
 "cec_ischemic_stroke_d90":{
  "label":"D1–D90 CEC裁定缺血性卒中","short_label":"CEC缺血性卒中","kind":"binary",
  "direction":"lower","evidence_tag":"Phase II正式主要终点",
  "description":"D1至D90经CEC裁定的缺血性卒中累积发生；数值越低越有利。",
 },
 "mrs_ordinal_day90":{
  "label":"D90完整有序mRS（0–6）","short_label":"有序mRS","kind":"ordinal",
  "direction":"lower","evidence_tag":"Phase II SAP预设shift分析",
  "description":"D90 mRS 0–6全等级位移；共同优势比>1表示更偏向较低、较好的mRS等级。",
 },
 "mrs01_day90":{
  "label":"D90 mRS≤1","short_label":"mRS≤1","kind":"binary",
  "direction":"higher","evidence_tag":"探索性二分类规划终点",
  "description":"D90优秀功能结局；应答比例越高越有利。",
 },
 "mrs02_day90":{
  "label":"D90 mRS≤2","short_label":"mRS≤2","kind":"binary",
  "direction":"higher","evidence_tag":"探索性二分类规划终点",
  "description":"D90功能独立结局；应答比例越高越有利。",
 },
}

def endpoint_metadata(endpoint:str)->dict[str,Any]:
 if endpoint not in PRIMARY_ENDPOINTS:raise ValueError("主要终点不受支持。")
 return copy.deepcopy(PRIMARY_ENDPOINTS[endpoint])

@lru_cache(maxsize=1)
def assets():
 return {
  "population":pd.read_csv(DATA/"phase2_mrs01_web_dataset.csv"),
  "effects":pd.read_csv(DATA/"phase2_mrs01_unadjusted_effects.csv"),
  "adjusted":pd.read_csv(DATA/"phase2_mrs01_adjusted_effects.csv"),
  "contract":json.loads(CONTRACT_PATH.read_text()),
 }

def options()->dict[str,list[Any]]:
 c=assets()["contract"];a=c["advanced_parameters"];d=assets()["population"]
 return {
 "active_arms":c["basic_parameters"]["active_arm"]["values"],
  "primary_endpoints":list(PRIMARY_ENDPOINTS),
  "source_scenarios":a["source_scenario"]["values"],
  "analysis_priors":a["analysis_prior"]["values"],
  "simulation_sizes":a["n_simulations"]["values"],
  "sex_values":sorted(d.sex.dropna().astype(int).unique().tolist()),
  "baseline_mrs_values":sorted(d.baseline_mrs.dropna().astype(int).unique().tolist()),
  "indication_values":sorted(d.indication.dropna().astype(str).unique().tolist()),
  "sbp_values":sorted(d.baseline_sbp_gt140_sap.dropna().astype(int).unique().tolist()),
  "presentation_values":sorted(d.presentation_group.dropna().astype(str).unique().tolist()),
  "history_values":[0,1],
  "cyp2c19_values":sorted(d.cyp2c19_group.dropna().astype(str).unique().tolist()),
  "prior_stroke_tia_proxy_values":[0,1],
  "sbp_operators":["all","lt","le","ge","gt"],
 }

def dose_tooltip()->str:
 c=assets()["contract"]["dose_regimens"]
 return "\n".join(f'{v["display"]}：{v["tooltip"]}' for v in c.values())

def _population_defaults()->dict[str,Any]:
 d=assets()["population"]
 return {
  "nihss_range":[int(d.baseline_nihss.min()),int(d.baseline_nihss.max())],
  "age_range":[int(d.age.min()),int(d.age.max())],
  "sex":sorted(d.sex.dropna().astype(int).unique().tolist()),
  "baseline_mrs":sorted(d.baseline_mrs.dropna().astype(int).unique().tolist()),
  "indication":sorted(d.indication.dropna().astype(str).unique().tolist()),
  "sbp":sorted(d.baseline_sbp_gt140_sap.dropna().astype(int).unique().tolist()),
  "sbp_operator":"all","sbp_threshold":140,
  "presentation_group":sorted(d.presentation_group.dropna().astype(str).unique().tolist()),
  "history_hypertension":[0,1],"history_diabetes":[0,1],"history_dyslipidemia":[0,1],
  "cyp2c19_group":sorted(d.cyp2c19_group.dropna().astype(str).unique().tolist()),
  "prior_stroke_tia_proxy":[0,1],
  "site_mitt_n_min":0,
 }

def normalize_population_filters(raw:dict[str,Any]|None)->dict[str,Any]:
 default=_population_defaults();raw=raw or {}
 def pair(name):
  value=raw.get(name,default[name])
  if not isinstance(value,(list,tuple)) or len(value)!=2:return default[name]
  return [int(value[0]),int(value[1])]
 def values(name,cast):
  value=raw.get(name,default[name])
  if not isinstance(value,(list,tuple)) or not value:return default[name]
  return sorted({cast(x) for x in value})
 legacy_sbp=values("sbp",int)
 sbp_operator=str(raw.get("sbp_operator","all"))
 if "sbp_operator" not in raw and legacy_sbp!=default["sbp"]:
  sbp_operator="le" if legacy_sbp==[0] else ("gt" if legacy_sbp==[1] else "all")
 return {
  "nihss_range":pair("nihss_range"),
  "age_range":pair("age_range"),
  "sex":values("sex",int),
  "baseline_mrs":values("baseline_mrs",int),
  "indication":values("indication",str),
  "sbp":default["sbp"],"sbp_operator":sbp_operator,
  "sbp_threshold":int(raw.get("sbp_threshold",default["sbp_threshold"])),
  "presentation_group":values("presentation_group",str),
  "history_hypertension":values("history_hypertension",int),
  "history_diabetes":values("history_diabetes",int),
  "history_dyslipidemia":values("history_dyslipidemia",int),
  "cyp2c19_group":values("cyp2c19_group",str),
  "prior_stroke_tia_proxy":values("prior_stroke_tia_proxy",int),
  "site_mitt_n_min":int(raw.get("site_mitt_n_min",0) or 0),
 }

def population_filters_active(filters:dict[str,Any])->bool:
 return filters!=_population_defaults()

def patient_filters_active(filters:dict[str,Any])->bool:
 x=dict(filters);x["site_mitt_n_min"]=0
 return x!=_population_defaults()

def _apply_filters(d:pd.DataFrame,filters:dict[str,Any],*,include_site:bool=True)->pd.DataFrame:
 q=d.copy();default=_population_defaults()
 if filters["nihss_range"]!=default["nihss_range"]:q=q[q.baseline_nihss.between(*filters["nihss_range"])]
 if filters["age_range"]!=default["age_range"]:q=q[q.age.between(*filters["age_range"])]
 if filters["sex"]!=default["sex"]:q=q[q.sex.isin(filters["sex"])]
 if filters["baseline_mrs"]!=default["baseline_mrs"]:q=q[q.baseline_mrs.isin(filters["baseline_mrs"])]
 if filters["indication"]!=default["indication"]:q=q[q.indication.astype(str).isin(filters["indication"])]
 op=filters["sbp_operator"];cut=filters["sbp_threshold"]
 if op=="lt":q=q[q.baseline_sbp<cut]
 elif op=="le":q=q[q.baseline_sbp<=cut]
 elif op=="ge":q=q[q.baseline_sbp>=cut]
 elif op=="gt":q=q[q.baseline_sbp>cut]
 if filters["presentation_group"]!=default["presentation_group"]:q=q[q.presentation_group.isin(filters["presentation_group"])]
 for field in ["history_hypertension","history_diabetes","history_dyslipidemia","prior_stroke_tia_proxy"]:
  if filters[field]!=default[field]:q=q[q[field].isin(filters[field])]
 if filters["cyp2c19_group"]!=default["cyp2c19_group"]:q=q[q.cyp2c19_group.isin(filters["cyp2c19_group"])]
 if include_site and filters["site_mitt_n_min"]>0:q=q[q.site_mitt_n>=filters["site_mitt_n_min"]]
 return q

def population_filter_counts(filters:dict[str,Any])->dict[str,Any]:
 d=assets()["population"];d=d[d.mitt_flag==1].copy();patient=_apply_filters(d,filters,include_site=False)
 eligible=_apply_filters(d,filters,include_site=True)
 return {
  "source_n":len(d),"patient_eligible_n":len(patient),"eligible_n":len(eligible),
  "patient_retention":len(patient)/len(d),"source_retention":len(eligible)/len(d),
  "center_sensitivity_active":filters["site_mitt_n_min"]>0,
 }

def _wilson(x,n,z):
 p=x/n;den=1+z*z/n;center=(p+z*z/(2*n))/den
 half=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
 return center-half,center+half

def newcombe(x1,n1,x0,n0):
 z=norm.ppf(.975);p1=x1/n1;p0=x0/n0
 l1,u1=_wilson(x1,n1,z);l0,u0=_wilson(x0,n0,z);rd=p1-p0
 lo=rd-np.sqrt((p1-l1)**2+(u0-p0)**2)
 hi=rd+np.sqrt((u1-p1)**2+(p0-l0)**2)
 return rd,lo,hi

def _endpoint_values(d:pd.DataFrame,endpoint:str,source_scenario:str)->pd.Series:
 """Return the endpoint under the selected transparent missing-data planning rule."""
 if endpoint=="cec_ischemic_stroke_d90":return pd.to_numeric(d["cec_ischemic_stroke_d90"],errors="coerce")
 if source_scenario not in SOURCE_COLUMNS:raise ValueError("Phase II证据口径不受支持。")
 score=pd.to_numeric(d["mrs_day90_analysis_score"],errors="coerce")
 raw=pd.to_numeric(d["v8_mrs_raw"],errors="coerce")
 latest=pd.to_numeric(d["latest_postbaseline_mrs_le95"],errors="coerce")
 death=pd.to_numeric(d["death_before_day90_flag"],errors="coerce").fillna(0).eq(1)
 strict=pd.to_numeric(d["v8_strict_window_flag"],errors="coerce").fillna(0).eq(1)
 if source_scenario=="nominal_v8_missing_nonresponder":v=score
 elif source_scenario=="available_case":v=score
 elif source_scenario=="strict_d85_d95_missing_nonresponder":v=raw.where(strict)
 else:v=latest
 v=v.mask(death,6)
 if source_scenario!="available_case":v=v.fillna(6)
 if endpoint=="mrs_ordinal_day90":return v.clip(0,6)
 threshold=1 if endpoint=="mrs01_day90" else 2
 return v.le(threshold).astype(float).where(v.notna())

def _ordinal_common_effect(active:np.ndarray,control:np.ndarray)->tuple[float,float,list[float]]:
 """Approximate proportional-odds effect using fixed-covariance GLS across six cutpoints."""
 pa=np.bincount(active.astype(int),minlength=7).astype(float);pa/=pa.sum()
 pc=np.bincount(control.astype(int),minlength=7).astype(float);pc/=pc.sum()
 fa=np.clip(np.cumsum(pa)[:-1],1e-4,1-1e-4);fc=np.clip(np.cumsum(pc)[:-1],1e-4,1-1e-4)
 log_or=np.log(fa/(1-fa))-np.log(fc/(1-fc))
 def cov(f,n):
  out=np.empty((6,6))
  for j in range(6):
   for k in range(6):
    raw=f[min(j,k)]-f[j]*f[k]
    out[j,k]=raw/(n*f[j]*(1-f[j])*f[k]*(1-f[k]))
  return out
 sigma=cov(fa,len(active))+cov(fc,len(control));inv=np.linalg.pinv(sigma)
 one=np.ones(6);den=float(one@inv@one);weights=(inv@one)/den
 beta=float(weights@log_or);se=math.sqrt(1/den)
 return beta,se,[float(x) for x in np.exp(log_or)]

def _evidence_from_data(active_arm:str,source_scenario:str,filters:dict[str,Any],endpoint:str)->dict[str,Any]:
 meta=endpoint_metadata(endpoint)
 d=assets()["population"];d=d[d.mitt_flag==1].copy();d=_apply_filters(d,filters)
 d=d[d.treatment_arm_label.isin([active_arm,CONTROL_ARM])].copy();rows={}
 for arm in (active_arm,CONTROL_ARM):
  q=d[d.treatment_arm_label==arm];v=_endpoint_values(q,endpoint,source_scenario).dropna().astype(float)
  row={"source_n":len(q),"n":len(v),"missing":int(len(q)-len(v))}
  if meta["kind"]=="binary":row.update({"responders":int(v.sum()),"rate":None if len(v)==0 else float(v.mean())})
  else:
   counts=np.bincount(v.astype(int),minlength=7).astype(int)
   row.update({"distribution":counts.tolist(),"mean_score":None if len(v)==0 else float(v.mean())})
  rows[arm]=row
 a=rows[active_arm];c=rows[CONTROL_ARM]
 if min(a["n"],c["n"])==0:raise ValueError("所选人群在试验组或对照组没有可评价的Phase II终点记录。")
 common={"endpoint":endpoint,"endpoint_kind":meta["kind"],"active_n":a["n"],"active_source_n":a["source_n"],"active_missing":a["missing"],
  "control_n":c["n"],"control_source_n":c["source_n"],"control_missing":c["missing"]}
 if meta["kind"]=="binary":
  rd,lo,hi=newcombe(a["responders"],a["n"],c["responders"],c["n"])
  benefit=rd if meta["direction"]=="higher" else -rd
  return {**common,"active_responders":a["responders"],"active_rate":a["rate"],
   "control_responders":c["responders"],"control_rate":c["rate"],"observed_rd":float(rd),
   "observed_benefit":float(benefit),"rd_ci_low":float(lo),"rd_ci_high":float(hi)}
 av=_endpoint_values(d[d.treatment_arm_label==active_arm],endpoint,source_scenario).dropna().to_numpy()
 cv=_endpoint_values(d[d.treatment_arm_label==CONTROL_ARM],endpoint,source_scenario).dropna().to_numpy()
 beta,se,threshold_ors=_ordinal_common_effect(av,cv)
 return {**common,"active_distribution":a["distribution"],"control_distribution":c["distribution"],
  "active_mean_score":a["mean_score"],"control_mean_score":c["mean_score"],
  "observed_log_common_or":beta,"observed_common_or":float(math.exp(beta)),"observed_log_or_se":se,
  "threshold_odds_ratios":threshold_ors}

def phase2_evidence(active_arm:str,source_scenario:str,population_filters:dict[str,Any]|None=None,primary_endpoint:str="mrs01_day90")->dict[str,Any]:
 filters=normalize_population_filters(population_filters)
 return _evidence_from_data(active_arm,source_scenario,filters,primary_endpoint)

def default_control_rate(active_arm:str,source_scenario:str,primary_endpoint:str="mrs01_day90")->float|None:
 e=phase2_evidence(active_arm,source_scenario,None,primary_endpoint)
 return e.get("control_rate")

def normalize_scenario(s:dict[str,Any])->dict[str,Any]:
 o=options();c=assets()["contract"]
 endpoint=s.get("primary_endpoint","mrs01_day90")
 source=s.get("source_scenario",o["source_scenarios"][0])
 if endpoint=="cec_ischemic_stroke_d90":source="cec_adjudicated_d1_d90"
 out={
  "primary_endpoint":endpoint,
  "active_arm":s.get("active_arm",o["active_arms"][0]),"control_arm":CONTROL_ARM,
  "source_scenario":source,
  "total_n":int(s.get("total_n",c["basic_parameters"]["total_n"]["default"])),
  "active_allocation":float(s.get("active_allocation",.5)),
  "effect_multiplier":float(s.get("effect_multiplier",1.0)),
  "analysis_prior":s.get("analysis_prior","weak_beta11"),
  "n_simulations":int(s.get("n_simulations",5000)),
  "random_seed":int(s.get("random_seed",20260810)),
  "population_filters":normalize_population_filters(s.get("population_filters")),
 }
 default_rate=default_control_rate(out["active_arm"],out["source_scenario"],endpoint)
 raw_rate=s.get("control_response_rate",default_rate)
 out["control_response_rate"]=None if default_rate is None else float(default_rate if raw_rate is None else raw_rate)
 return out

def validate_scenario(s:dict[str,Any])->list[str]:
 c=assets()["contract"];b=c["basic_parameters"];a=c["advanced_parameters"];d=_population_defaults();err=[]
 if s["primary_endpoint"] not in PRIMARY_ENDPOINTS:err.append("主要终点不受支持。")
 if s["active_arm"] not in b["active_arm"]["values"]:err.append("剂量方案不受支持。")
 if s["primary_endpoint"]=="cec_ischemic_stroke_d90":
  if s["source_scenario"]!="cec_adjudicated_d1_d90":err.append("CEC终点仅支持D1–D90裁定事件口径。")
 elif s["source_scenario"] not in a["source_scenario"]["values"]:err.append("Phase II证据口径不受支持。")
 if not b["total_n"]["minimum"]<=s["total_n"]<=b["total_n"]["maximum"]:err.append("总样本量超出已验证范围200–5000。")
 if PRIMARY_ENDPOINTS.get(s["primary_endpoint"],{}).get("kind")=="binary":
  low,high=(.01,.50) if s["primary_endpoint"]=="cec_ischemic_stroke_d90" else (.20,.95)
  if s["control_response_rate"] is None or not low<=s["control_response_rate"]<=high:err.append(f"规划对照率须在{low:.0%}–{high:.0%}之间。")
 if not b["effect_multiplier"]["minimum"]<=s["effect_multiplier"]<=b["effect_multiplier"]["maximum"]:err.append("效应系数须在50%–150%之间。")
 if not a["active_allocation"]["minimum"]<=s["active_allocation"]<=a["active_allocation"]["maximum"]:err.append("试验组分配比例须在30%–70%之间。")
 if s["analysis_prior"] not in a["analysis_prior"]["values"]:err.append("Bayesian先验不受支持。")
 if s["n_simulations"] not in a["n_simulations"]["values"]:err.append("模拟次数不受支持。")
 if not a["random_seed"]["minimum"]<=s["random_seed"]<=a["random_seed"]["maximum"]:err.append("随机种子超出范围。")
 f=s["population_filters"]
 if f["nihss_range"][0]>f["nihss_range"][1] or f["nihss_range"][0]<d["nihss_range"][0] or f["nihss_range"][1]>d["nihss_range"][1]:err.append(f'基线NIHSS范围须在{d["nihss_range"][0]}–{d["nihss_range"][1]}内。')
 if f["age_range"][0]>f["age_range"][1] or f["age_range"][0]<d["age_range"][0] or f["age_range"][1]>d["age_range"][1]:err.append(f'年龄范围须在{d["age_range"][0]}–{d["age_range"][1]}岁内。')
 if not set(f["sex"]).issubset(d["sex"]) or not f["sex"]:err.append("性别条件包含不支持的取值。")
 if not set(f["baseline_mrs"]).issubset(d["baseline_mrs"]) or not f["baseline_mrs"]:err.append("基线mRS条件包含不支持的取值。")
 if not set(f["indication"]).issubset(d["indication"]) or not f["indication"]:err.append("适应证条件包含不支持的取值。")
 if f["sbp_operator"] not in {"all","lt","le","ge","gt"}:err.append("基线SBP比较符号不受支持。")
 if not int(assets()["population"].baseline_sbp.min())<=f["sbp_threshold"]<=int(assets()["population"].baseline_sbp.max()):err.append("基线SBP阈值超出Phase II观察范围。")
 for field in ["presentation_group","history_hypertension","history_diabetes","history_dyslipidemia","cyp2c19_group","prior_stroke_tia_proxy"]:
  if not set(f[field]).issubset(d[field]) or not f[field]:err.append(f"{field}条件包含不支持的取值。")
 if not 0<=f["site_mitt_n_min"]<=int(assets()["population"].site_mitt_n.max()):err.append("来源中心人数下限超出Phase II观察范围。")
 return err

def _warning(level,title,text):
 return {"level":level,"title":title,"text":text}

def _warning_set(s:dict[str,Any],e:dict[str,Any],full:dict[str,Any],counts:dict[str,Any],assumed_value:float)->list[dict[str,str]]:
 meta=endpoint_metadata(s["primary_endpoint"])
 w=[_warning("ordinary","探索性规划边界","结果依赖当前数据和假设，不代表或保证Phase III最终成功。")]
 if s["effect_multiplier"]>1.25:w.append(_warning("strong","高效应外推",f'效应系数{s["effect_multiplier"]:.0%}明显高于Phase II观察效应，仅适合乐观压力测试。'))
 elif s["effect_multiplier"]>1:w.append(_warning("caution","乐观效应外推",f'效应系数{s["effect_multiplier"]:.0%}高于Phase II观察效应，尚无直接证据支持放大。'))
 elif s["effect_multiplier"]<1:w.append(_warning("ordinary","效应折减",f'效应系数{s["effect_multiplier"]:.0%}表示对Phase II观察风险差进行折减。'))
 control_gap=0.
 if meta["kind"]=="binary":
  control_gap=abs(s["control_response_rate"]-full["control_rate"])
  if control_gap>=.10:w.append(_warning("strong","对照率重度外推","规划对照率与所选Phase II对照率相差至少10个百分点。"))
  elif control_gap>=.05:w.append(_warning("caution","对照率外推","规划对照率与所选Phase II对照率相差至少5个百分点。"))
 if s["source_scenario"] not in {"nominal_v8_missing_nonresponder","cec_adjudicated_d1_d90"}:
  level="strong" if s["source_scenario"] in {"available_case","locf_like_through_d95"} and s["effect_multiplier"]>1 else "caution"
  w.append(_warning(level,"敏感性终点口径","当前使用非主规划的D90窗口/缺失敏感性口径。"))
 if patient_filters_active(s["population_filters"]):
  level="strong" if counts["source_retention"]<.20 else ("caution" if counts["source_retention"]<.50 else "ordinary")
  w.append(_warning(level,"探索性人群传递",f'当前基线条件保留{counts["eligible_n"]}/{counts["source_n"]}例（{counts["source_retention"]:.1%}）；所选剂量/对照终点评价为{e["active_n"]}/{e["control_n"]}例。亚组观察差异不证明治疗效应修饰。'))
 f=s["population_filters"];default=_population_defaults()
 if f["prior_stroke_tia_proxy"]!=default["prior_stroke_tia_proxy"]:
  w.append(_warning("strong","未经官方验证的病史代理",f'该条件由MH关键词临时派生。当前所选剂量/对照来源为{e["active_source_n"]}/{e["control_source_n"]}例，终点评价为{e["active_n"]}/{e["control_n"]}例；全mITT代理分组111/102/108与SAR的112/103/108不一致，且可能混入本次指数事件。'))
 if f["sex"]!=default["sex"]:
  selected="、".join("男" if x==1 else "女" for x in f["sex"])
  w.append(_warning("caution","性别亚组仅作描述性探索",f'当前选择{selected}；所选剂量/对照终点评价为{e["active_n"]}/{e["control_n"]}例。性别未列入SAR主要终点森林图，当前差异不证明性别治疗效应修饰。'))
 if f["cyp2c19_group"]!=default["cyp2c19_group"]:
  w.append(_warning("caution","CYP2C19高级探索","部分代谢型样本稀疏；若用于未来入组，还需确认随机前检测可实施性。"))
 if f["presentation_group"]!=default["presentation_group"] and "高危TIA" in f["presentation_group"]:
  w.append(_warning("strong","高危TIA样本极少","Phase II仅8例高危TIA；该层只能展示分布，不能单独支持核心模拟。"))
 if f["baseline_mrs"]!=default["baseline_mrs"] and 2 in f["baseline_mrs"]:
  w.append(_warning("caution","发病前mRS=2样本有限","Phase II中发病前mRS=2仅8例，包含该层的组合应重点查看来源人数。"))
 if counts["center_sensitivity_active"]:w.append(_warning("caution","来源中心敏感性","中心人数条件仅筛选Phase II来源中心，不是患者入组条件，也不计入预计筛查人数。"))
 min_arm=min(e["active_n"],e["control_n"])
 if min_arm<20:w.append(_warning("strong","来源组别极稀疏",f'所选剂量/对照终点评价为{e["active_n"]}/{e["control_n"]}例（来源为{e["active_source_n"]}/{e["control_source_n"]}例）；较少组仅{min_arm}例，核心结果不予计算。'))
 elif min_arm<40:w.append(_warning("strong","来源组别稀疏",f'所选剂量/对照终点评价为{e["active_n"]}/{e["control_n"]}例（来源为{e["active_source_n"]}/{e["control_source_n"]}例）；效应与assurance非常不稳定。'))
 elif min_arm<60:w.append(_warning("caution","来源组别有限",f'所选剂量/对照终点评价为{e["active_n"]}/{e["control_n"]}例（来源为{e["active_source_n"]}/{e["control_source_n"]}例）；应重点查看不确定性和全人群参照。'))
 if s["analysis_prior"]!="weak_beta11":
  level="strong" if min_arm<40 else "caution"
  w.append(_warning(level,"未批准Bayesian先验","所选先验仅用于敏感性，尚未获申办方正式批准。"))
 if s["n_simulations"]==1000:w.append(_warning("ordinary","快速模拟精度","1,000次适合交互探索；重要情景建议用20,000次复核。"))
 if s["active_allocation"]<=.35 or s["active_allocation"]>=.65:
  level="strong" if s["total_n"]<400 else "caution"
  w.append(_warning(level,"不均衡分配",f'试验组分配{s["active_allocation"]:.0%}会减少另一组信息量。'))
 if meta["kind"]=="ordinal":
  ors=e.get("threshold_odds_ratios",[])
  if ors and max(ors)/max(min(ors),.01)>2:
   w.append(_warning("caution","比例优势假设需核查","Phase II各mRS切点优势比差异较大；共同优势比模拟仅作近似规划，正式设计需做比例优势诊断与敏感性分析。"))
  w.append(_warning("ordinary","有序模型近似","当前以Phase II对照组0–6分布和共同优势比进行比例优势Monte Carlo；尚未替代正式SAP样本量程序。"))
 elif assumed_value>.95 and meta["direction"]=="higher":w.append(_warning("strong","应答率接近上界",f'传递后试验组应答率为{assumed_value:.1%}，结果对小幅参数变化敏感。'))
 if meta["kind"]=="binary" and s["effect_multiplier"]>1 and control_gap>=.05:w.append(_warning("strong","叠加外推","当前同时放大治疗效应并改变对照率，外推假设相互叠加。"))
 return w

def _ordinal_transport(control_distribution:list[int],log_common_or:float)->list[float]:
 p=np.asarray(control_distribution,dtype=float);p/=p.sum()
 f=np.clip(np.cumsum(p)[:-1],1e-6,1-1e-6)
 shifted=1/(1+np.exp(-(np.log(f/(1-f))+log_common_or)))
 out=np.diff(np.r_[0,shifted,1]);return [float(x) for x in np.clip(out,0,1)/np.clip(out,0,1).sum()]

def preview_scenario(scenario:dict[str,Any])->dict[str,Any]:
 try:s=normalize_scenario(scenario)
 except Exception as exc:return {"status":"unsupported","errors":[f"参数无法解析：{exc}"],"warnings_ui":[]}
 errors=validate_scenario(s)
 if errors:return {"status":"unsupported","errors":errors,"warnings_ui":[],"normalized_scenario":s}
 try:
  e=phase2_evidence(s["active_arm"],s["source_scenario"],s["population_filters"],s["primary_endpoint"])
  full=phase2_evidence(s["active_arm"],s["source_scenario"],None,s["primary_endpoint"])
 except Exception as exc:return {"status":"unsupported","errors":[str(exc)],"warnings_ui":[],"normalized_scenario":s}
 counts=population_filter_counts(s["population_filters"]);meta=endpoint_metadata(s["primary_endpoint"]);extra={}
 if meta["kind"]=="binary":
  sign=1 if meta["direction"]=="higher" else -1
  p1=s["control_response_rate"]+sign*s["effect_multiplier"]*e["observed_benefit"]
  full_p1=s["control_response_rate"]+sign*s["effect_multiplier"]*full["observed_benefit"]
  if not 0<p1<1:errors.append(f"传递后的当前人群试验组发生率为{p1:.1%}，超出0%–100%。")
  if not 0<full_p1<1:errors.append(f"同设计全人群参照的试验组发生率为{full_p1:.1%}，超出0%–100%。")
  extra={"assumed_active_rate":p1,"assumed_control_rate":s["control_response_rate"],"full_assumed_active_rate":full_p1,
   "assumed_benefit":s["effect_multiplier"]*e["observed_benefit"],"full_assumed_benefit":s["effect_multiplier"]*full["observed_benefit"]}
  assumed_value=p1
 else:
  beta=s["effect_multiplier"]*e["observed_log_common_or"];full_beta=s["effect_multiplier"]*full["observed_log_common_or"]
  extra={"assumed_log_common_or":beta,"assumed_common_or":float(math.exp(beta)),
   "full_assumed_log_common_or":full_beta,"full_assumed_common_or":float(math.exp(full_beta)),
   "assumed_control_distribution":[x/sum(e["control_distribution"]) for x in e["control_distribution"]],
   "assumed_active_distribution":_ordinal_transport(e["control_distribution"],beta),
   "full_assumed_control_distribution":[x/sum(full["control_distribution"]) for x in full["control_distribution"]],
   "full_assumed_active_distribution":_ordinal_transport(full["control_distribution"],full_beta)}
  assumed_value=extra["assumed_common_or"]
 n1=int(round(s["total_n"]*s["active_allocation"]));n0=s["total_n"]-n1
 if min(n1,n0)<30:errors.append("至少一个Phase III治疗组少于30例。")
 if min(e["active_n"],e["control_n"])<20:errors.append("所选人群至少一个Phase II来源组少于20个终点评价，核心概率结果不可支持。")
 warnings=_warning_set(s,e,full,counts,assumed_value)
 return {"status":"unsupported" if errors else "supported","errors":errors,"warnings_ui":warnings,
  "normalized_scenario":s,"endpoint":meta,"evidence":e,"full_evidence":full,"population":counts,
  "active_n":n1,"control_n":n0,**extra}

def conditional_operating_characteristics(*,p1:float,p0:float,n1:int,n0:int,n_simulations:int,seed:int,direction:str="higher")->dict[str,float]:
 rng=np.random.default_rng(seed);x1=rng.binomial(n1,p1,n_simulations);x0=rng.binomial(n0,p0,n_simulations)
 rd,lo,hi=newcombe(x1,n1,x0,n0);ok=lo>0 if direction=="higher" else hi<0;pos=float(ok.mean())
 return {"success_frequency":pos,"mcse":math.sqrt(pos*(1-pos)/n_simulations),
  "mean_observed_rd":float(rd.mean()),"mean_ci_low":float(lo.mean()),"mean_ci_high":float(hi.mean())}

def analytic_power_normal(*,p1:float,p0:float,n1:int,n0:int,direction:str="higher")->float:
 se=math.sqrt(p1*(1-p1)/n1+p0*(1-p0)/n0)
 effect=(p1-p0) if direction=="higher" else (p0-p1)
 return float(norm.cdf(effect/se-norm.ppf(.975))) if se>0 else 0.

def _beta_moments(a,b):
 m=a/(a+b);v=a*b/((a+b)**2*(a+b+1));return m,v

def bayesian_assurance(*,scenario:dict[str,Any],evidence:dict[str,Any],n1:int,n0:int,seed_offset:int=1000003,direction:str="higher")->dict[str,float]:
 ns=scenario["n_simulations"];rng=np.random.default_rng(scenario["random_seed"]+seed_offset)
 p0_src=rng.beta(evidence["control_responders"]+1,evidence["control_n"]-evidence["control_responders"]+1,ns)
 p1_src=rng.beta(evidence["active_responders"]+1,evidence["active_n"]-evidence["active_responders"]+1,ns)
 sign=1 if direction=="higher" else -1
 benefit=sign*(p1_src-p0_src);delta=sign*scenario["effect_multiplier"]*benefit
 ess=max(evidence["control_n"],20)
 p0=rng.beta(scenario["control_response_rate"]*ess,(1-scenario["control_response_rate"])*ess,ns)
 raw_p1=p0+delta;clip=(raw_p1<=.001)|(raw_p1>=.999);p1=np.clip(raw_p1,.001,.999)
 x1=rng.binomial(n1,p1);x0=rng.binomial(n0,p0);prior=scenario["analysis_prior"]
 if prior=="weak_beta11":aa0=ba0=ac0=bc0=1.
 elif prior=="skeptical_equal_ess20":
  m=scenario["control_response_rate"];aa0=ac0=m*20;ba0=bc0=(1-m)*20
 elif prior=="discounted_phase2_10pct":
  aa0=1+.1*evidence["active_responders"];ba0=1+.1*(evidence["active_n"]-evidence["active_responders"])
  ac0=1+.1*evidence["control_responders"];bc0=1+.1*(evidence["control_n"]-evidence["control_responders"])
 else:raise ValueError(prior)
 ma,va=_beta_moments(aa0+x1,ba0+n1-x1);mc,vc=_beta_moments(ac0+x0,bc0+n0-x0)
 z=(ma-mc)/np.sqrt(va+vc);pp=norm.cdf(z) if direction=="higher" else norm.cdf(-z);ok=pp>.975;ass=float(ok.mean())
 return {"assurance":ass,"mcse":math.sqrt(ass*(1-ass)/ns),"mean_posterior_probability":float(pp.mean()),
  "mean_true_active_rate":float(p1.mean()),"mean_true_control_rate":float(p0.mean()),
  "mean_true_rd":float((p1-p0).mean()),"clipped_design_draw_fraction":float(clip.mean())}

def _ordinal_covariance(probabilities:list[float],n:int)->np.ndarray:
 p=np.asarray(probabilities,dtype=float);f=np.clip(np.cumsum(p)[:-1],1e-5,1-1e-5);out=np.empty((6,6))
 for j in range(6):
  for k in range(6):
   out[j,k]=(f[min(j,k)]-f[j]*f[k])/(n*f[j]*(1-f[j])*f[k]*(1-f[k]))
 return out

def ordinal_operating_characteristics(*,active_distribution:list[float],control_distribution:list[float],n1:int,n0:int,n_simulations:int,seed:int)->dict[str,float]:
 pa=np.asarray(active_distribution,dtype=float);pc=np.asarray(control_distribution,dtype=float)
 sigma=_ordinal_covariance(pa,n1)+_ordinal_covariance(pc,n0);inv=np.linalg.pinv(sigma);one=np.ones(6)
 den=float(one@inv@one);weights=(inv@one)/den;se=math.sqrt(1/den)
 rng=np.random.default_rng(seed);ca=rng.multinomial(n1,pa,size=n_simulations);cc=rng.multinomial(n0,pc,size=n_simulations)
 fa=np.clip((np.cumsum(ca,axis=1)[:,:-1]+.5)/(n1+1),1e-6,1-1e-6)
 fc=np.clip((np.cumsum(cc,axis=1)[:,:-1]+.5)/(n0+1),1e-6,1-1e-6)
 threshold_log_or=np.log(fa/(1-fa))-np.log(fc/(1-fc));beta=threshold_log_or@weights
 ok=beta-norm.ppf(.975)*se>0;pos=float(ok.mean())
 return {"success_frequency":pos,"mcse":math.sqrt(pos*(1-pos)/n_simulations),
  "mean_log_common_or":float(beta.mean()),"mean_common_or":float(np.exp(beta).mean()),"planning_se":se}

def ordinal_bayesian_assurance(*,scenario:dict[str,Any],evidence:dict[str,Any],n1:int,n0:int,seed_offset:int=1000003)->dict[str,float]:
 ns=scenario["n_simulations"];rng=np.random.default_rng(scenario["random_seed"]+seed_offset)
 source_beta=rng.normal(evidence["observed_log_common_or"],evidence["observed_log_or_se"],ns)
 true_beta=scenario["effect_multiplier"]*source_beta
 pc=np.asarray(evidence["control_distribution"],dtype=float);pc/=pc.sum()
 # Design variance is evaluated at the transported point estimate; source uncertainty is integrated above.
 point_beta=scenario["effect_multiplier"]*evidence["observed_log_common_or"]
 pa=np.asarray(_ordinal_transport(evidence["control_distribution"],point_beta))
 future_var=float(1/(np.ones(6)@np.linalg.pinv(_ordinal_covariance(pa,n1)+_ordinal_covariance(pc,n0))@np.ones(6)))
 observed=rng.normal(true_beta,math.sqrt(future_var),ns);prior_var=100.
 post_var=1/(1/future_var+1/prior_var);post_mean=post_var*observed/future_var
 pp=norm.cdf(post_mean/math.sqrt(post_var));ok=pp>.975;ass=float(ok.mean())
 return {"assurance":ass,"mcse":math.sqrt(ass*(1-ass)/ns),"mean_posterior_probability":float(pp.mean()),
  "mean_true_log_common_or":float(true_beta.mean()),"mean_true_common_or":float(np.exp(true_beta).mean()),
  "clipped_design_draw_fraction":0.}

def scenario_hash(s:dict[str,Any])->str:
 return hashlib.sha256(json.dumps(s,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]

@lru_cache(maxsize=256)
def _evaluate_cached(payload:str)->dict[str,Any]:
 s=json.loads(payload);preview=preview_scenario(s)
 if preview["status"]!="supported":
  return {"status":"unsupported","reason":"；".join(preview["errors"]),"errors":preview["errors"],
   "warnings_ui":preview.get("warnings_ui",[]),"planning_stage":True,"normalized_scenario":s}
 e=preview["evidence"];full=preview["full_evidence"];n1=preview["active_n"];n0=preview["control_n"]
 meta=endpoint_metadata(s["primary_endpoint"]);specific={}
 if meta["kind"]=="binary":
  p0=s["control_response_rate"];p1=preview["assumed_active_rate"];full_p1=preview["full_assumed_active_rate"]
  mc=conditional_operating_characteristics(p1=p1,p0=p0,n1=n1,n0=n0,n_simulations=s["n_simulations"],seed=s["random_seed"],direction=meta["direction"])
  ba=bayesian_assurance(scenario=s,evidence=e,n1=n1,n0=n0,direction=meta["direction"])
  if population_filters_active(s["population_filters"]):
   full_mc=conditional_operating_characteristics(p1=full_p1,p0=p0,n1=n1,n0=n0,n_simulations=s["n_simulations"],seed=s["random_seed"]+7919,direction=meta["direction"])
   full_ba=bayesian_assurance(scenario=s,evidence=full,n1=n1,n0=n0,seed_offset=1007922,direction=meta["direction"])
  else:full_mc=mc.copy();full_ba=ba.copy()
  specific={"assumed_active_rate":p1,"assumed_control_rate":p0,"assumed_risk_difference":p1-p0,
   "assumed_benefit":preview["assumed_benefit"],"full_assumed_active_rate":full_p1,
   "full_assumed_risk_difference":full_p1-p0,"phase2_active_rate":e["active_rate"],
   "phase2_control_rate":e["control_rate"],"phase2_observed_rd":e["observed_rd"],
   "phase2_observed_benefit":e["observed_benefit"],"phase2_rd_ci_low":e["rd_ci_low"],"phase2_rd_ci_high":e["rd_ci_high"],
   "full_phase2_observed_rd":full["observed_rd"],"bayesian_mean_true_rd":ba["mean_true_rd"],
   "analytic_power_benchmark":analytic_power_normal(p1=p1,p0=p0,n1=n1,n0=n0,direction=meta["direction"]),
   "success_rule":"RD双侧95% Newcombe/Wilson区间下限>0" if meta["direction"]=="higher" else "RD双侧95% Newcombe/Wilson区间上限<0"}
 else:
  mc=ordinal_operating_characteristics(active_distribution=preview["assumed_active_distribution"],control_distribution=preview["assumed_control_distribution"],n1=n1,n0=n0,n_simulations=s["n_simulations"],seed=s["random_seed"])
  ba=ordinal_bayesian_assurance(scenario=s,evidence=e,n1=n1,n0=n0)
  if population_filters_active(s["population_filters"]):
   full_mc=ordinal_operating_characteristics(active_distribution=preview["full_assumed_active_distribution"],control_distribution=preview["full_assumed_control_distribution"],n1=n1,n0=n0,n_simulations=s["n_simulations"],seed=s["random_seed"]+7919)
   full_ba=ordinal_bayesian_assurance(scenario=s,evidence=full,n1=n1,n0=n0,seed_offset=1007922)
  else:full_mc=mc.copy();full_ba=ba.copy()
  specific={"assumed_common_or":preview["assumed_common_or"],"assumed_log_common_or":preview["assumed_log_common_or"],
   "assumed_active_distribution":preview["assumed_active_distribution"],"assumed_control_distribution":preview["assumed_control_distribution"],
   "full_assumed_common_or":preview["full_assumed_common_or"],"phase2_observed_common_or":e["observed_common_or"],
   "phase2_observed_log_common_or":e["observed_log_common_or"],"phase2_threshold_odds_ratios":e["threshold_odds_ratios"],
   "phase2_active_distribution":e["active_distribution"],"phase2_control_distribution":e["control_distribution"],
   "phase2_active_mean_score":e["active_mean_score"],"phase2_control_mean_score":e["control_mean_score"],
   "full_phase2_observed_common_or":full["observed_common_or"],"bayesian_mean_true_common_or":ba["mean_true_common_or"],
   "analytic_power_benchmark":float(norm.cdf(preview["assumed_log_common_or"]/mc["planning_se"]-norm.ppf(.975))),
   "success_rule":"比例优势模型共同OR双侧95% Wald区间下限>1"}
 counts=preview["population"];min_arm=min(e["active_n"],e["control_n"])
 support="supported" if min_arm>=60 and counts["source_retention"]>=.30 else "limited"
 screening=None if counts["patient_retention"]<=0 else int(math.ceil(s["total_n"]/counts["patient_retention"]))
 warnings_ui=list(preview["warnings_ui"])
 if ba.get("clipped_design_draw_fraction",0)>.01:warnings_ui.append(_warning("strong","Bayesian概率边界","超过1%的设计分布抽样触及概率边界，assurance外推负担较高。"))
 return {
  "status":"supported","evidence_support":support,"engine_version":ENGINE_VERSION,"data_version":DATA_VERSION,
  "primary_endpoint":s["primary_endpoint"],"endpoint_label":meta["label"],"endpoint_kind":meta["kind"],"endpoint_direction":meta["direction"],"endpoint_evidence_tag":meta["evidence_tag"],
  "scenario_hash":scenario_hash(s),"planning_stage":True,"not_a_prediction":True,"normalized_scenario":s,
  "active_n":n1,"control_n":n0,
  "monte_carlo_pos":mc["success_frequency"],"monte_carlo_standard_error":mc["mcse"],
  "bayesian_assurance":ba["assurance"],"bayesian_standard_error":ba["mcse"],
  "full_population_pos":full_mc["success_frequency"],"full_population_standard_error":full_mc["mcse"],
  "full_population_assurance":full_ba["assurance"],"delta_pos_vs_full":mc["success_frequency"]-full_mc["success_frequency"],
  "source_n_active":e["active_n"],"source_n_control":e["control_n"],
  "source_missing_active":e["active_missing"],"source_missing_control":e["control_missing"],
  "full_source_n_active":full["active_n"],"full_source_n_control":full["control_n"],
  "phase2_source_n":counts["source_n"],"phase2_eligible_n":counts["eligible_n"],
  "phase2_patient_eligible_n":counts["patient_eligible_n"],"phase2_source_retention":counts["source_retention"],
  "phase2_patient_retention":counts["patient_retention"],"estimated_screened_n":screening,
  "source_sensitivity_active":counts["center_sensitivity_active"],
  "bayesian_clipped_draw_fraction":ba.get("clipped_design_draw_fraction",0),"posterior_threshold":.975,
  "warnings_ui":warnings_ui,"warnings":[x["text"] for x in warnings_ui],**specific,
 }

def evaluate_scenario(scenario:dict[str,Any],config:dict[str,Any]|None=None)->dict[str,Any]:
 try:s=normalize_scenario(scenario)
 except Exception as exc:return {"status":"unsupported","reason":f"参数无法解析：{exc}","planning_stage":True}
 payload=json.dumps(s,sort_keys=True,ensure_ascii=False,separators=(",",":"))
 return copy.deepcopy(_evaluate_cached(payload))

def _distribution_rows(full:pd.DataFrame,eligible:pd.DataFrame,series_name:str,levels:list[tuple[Any,str]])->list[dict[str,Any]]:
 rows=[];fs=full[series_name];es=eligible[series_name]
 fden=int(fs.notna().sum());eden=int(es.notna().sum())
 for value,label in levels:
  if callable(value):fn=int(value(fs).sum());en=int(value(es).sum())
  else:fn=int((fs==value).sum());en=int((es==value).sum())
  rows.append({"level":label,"full_n":fn,"full_denominator":fden,"full_pct":0 if fden==0 else fn/fden,
   "eligible_n":en,"eligible_denominator":eden,"eligible_pct":0 if eden==0 else en/eden})
 return rows

def population_insights(scenario:dict[str,Any])->dict[str,Any]:
 s=normalize_scenario(scenario);f=s["population_filters"];d=assets()["population"];full=d[d.mitt_flag==1].copy()
 patient=_apply_filters(full,f,include_site=False);eligible=_apply_filters(full,f,include_site=True)
 counts=population_filter_counts(f);active=s["active_arm"];source=s["source_scenario"];endpoint=s["primary_endpoint"];meta=endpoint_metadata(endpoint)
 def outcome_row(arm,g):
  v=_endpoint_values(g,endpoint,source).dropna().astype(float)
  base={"arm":arm,"n":len(g),"available_n":len(v),"missing_n":len(g)-len(v)}
  if meta["kind"]=="binary":return {**base,"responders":int(v.sum()),"response_rate":None if len(v)==0 else float(v.mean()),"summary_value":None if len(v)==0 else float(v.mean())}
  dist=np.bincount(v.astype(int),minlength=7).astype(int).tolist()
  return {**base,"responders":None,"response_rate":None,"mean_score":None if len(v)==0 else float(v.mean()),"distribution":dist,"summary_value":None if len(v)==0 else float(v.mean())}
 arms=[]
 for arm,g in eligible.groupby("treatment_arm_label",sort=True):
  arms.append(outcome_row(arm,g))
 full_outcome=[]
 for arm in (active,CONTROL_ARM):
  g=full[full.treatment_arm_label==arm];full_outcome.append(outcome_row(arm,g))
 empty={"arm":"","n":0,"available_n":0,"missing_n":0,"responders":0 if meta["kind"]=="binary" else None,"response_rate":None,"summary_value":None}
 outcome=[next((x for x in arms if x["arm"]==arm),{**empty,"arm":arm}) for arm in (active,CONTROL_ARM)]
 age_levels=[(lambda x:x<55,"<55岁"),(lambda x:(x>=55)&(x<65),"55–64岁"),(lambda x:(x>=65)&(x<75),"65–74岁"),(lambda x:x>=75,"≥75岁")]
 site_levels=[(lambda x:x<8,"<8例"),(lambda x:(x>=8)&(x<20),"8–19例"),(lambda x:x>=20,"≥20例")]
 distributions={
  "基线NIHSS分布":_distribution_rows(full,eligible,"baseline_nihss",[(x,str(x)) for x in range(int(full.baseline_nihss.min()),int(full.baseline_nihss.max())+1)]),
  "年龄分布":_distribution_rows(full,eligible,"age",age_levels),
  "发病前mRS分布":_distribution_rows(full,eligible,"baseline_mrs",[(x,f"mRS {x}") for x in sorted(full.baseline_mrs.dropna().astype(int).unique())]),
  "性别分布":_distribution_rows(full,eligible,"sex",[(1,"男"),(2,"女")]),
  "入组时疾病类型":_distribution_rows(full,eligible,"indication",[(x,str(x)) for x in sorted(full.indication.dropna().unique())]),
  "入组时疾病/影像类型":_distribution_rows(full,eligible,"presentation_group",[(x,str(x)) for x in sorted(full.presentation_group.dropna().unique())]),
  "高血压病史":_distribution_rows(full,eligible,"history_hypertension",[(1,"有"),(0,"无")]),
  "糖尿病病史":_distribution_rows(full,eligible,"history_diabetes",[(1,"有"),(0,"无")]),
  "血脂异常病史":_distribution_rows(full,eligible,"history_dyslipidemia",[(1,"有"),(0,"无")]),
  "CYP2C19代谢型":_distribution_rows(full,eligible,"cyp2c19_group",[(x,str(x)) for x in sorted(full.cyp2c19_group.dropna().unique())]),
  "既往卒中/TIA病史":_distribution_rows(full,eligible,"prior_stroke_tia_proxy",[(1,"有"),(0,"无")]),
  "基线SBP分层":_distribution_rows(full,eligible,"baseline_sbp_gt140_sap",[(1,"SBP>140"),(0,"SBP≤140")]),
  "Phase II来源中心规模":_distribution_rows(full,eligible,"site_mitt_n",site_levels),
 }
 min_pair=min(x["available_n"] for x in outcome)
 support="数据支持相对充分" if min_pair>=60 else ("仅作探索性假设，数据有限" if min_pair>=20 else "当前不支持核心概率")
 flow=[{"stage":"Phase II mITT来源","n":len(full)},{"stage":"应用患者基线条件","n":len(patient)}]
 if f["site_mitt_n_min"]>0:flow.append({"stage":"应用来源中心敏感性","n":len(eligible)})
 flow.append({"stage":"所选剂量+对照来源","n":sum(x["n"] for x in outcome)})
 return {
  "status":"supported","scenario":s,"source_n":len(full),"patient_eligible_n":len(patient),"eligible_n":len(eligible),
  "patient_retention":counts["patient_retention"],"source_retention":counts["source_retention"],
  "center_sensitivity_active":counts["center_sensitivity_active"],"flow":flow,"arm_distribution":arms,
  "distributions":distributions,"outcome":outcome,"full_outcome":full_outcome,"support_status":support,
  "endpoint":meta,"primary_endpoint":endpoint,
  "warning":f'描述性Phase II mITT来源结果：当前保留{len(eligible)}/{len(full)}例；所选剂量/对照来源为{outcome[0]["n"]}/{outcome[1]["n"]}例，终点评价为{outcome[0]["available_n"]}/{outcome[1]["available_n"]}例。不证明治疗效应异质性，也不构成入组建议。',
 }

def population_summary(filters:dict[str,Any],config:dict[str,Any]|None=None)->dict[str,Any]:
 s={"population_filters":filters};ins=population_insights(s)
 return {"status":"supported","source_n":ins["source_n"],"retained_n":ins["eligible_n"],
  "retention":ins["source_retention"],"screening_burden":None if ins["patient_retention"]==0 else 1/ins["patient_retention"],
  "arm_summary":[{"treatment_arm":x["arm"],"n":x["n"],"responders":x["responders"],
   "response_rate":x["response_rate"],"observed_or_death":x["available_n"],"nondeath_missing":x["missing_n"]} for x in ins["arm_distribution"]],
  "filters":normalize_population_filters(filters),"warning":ins["warning"]}

def comparison_frame(saved:list[dict[str,Any]])->pd.DataFrame:
 rows=[]
 for item in saved:
  s=item["scenario"];r=item["result"]
  rows.append({"情景":item["name"],"主要终点":r.get("endpoint_label",PRIMARY_ENDPOINTS["mrs01_day90"]["label"]),"候选剂量":s["active_arm"],"二期口径":s["source_scenario"],
   "效应系数":s["effect_multiplier"],"对照发生/应答率":s.get("control_response_rate"),"试验组分配":s["active_allocation"],
   "总样本量":s["total_n"],"来源保留":r.get("phase2_source_retention"),"探索性成功频率":r.get("monte_carlo_pos"),
   "全人群参照":r.get("full_population_pos"),"Bayesian assurance":r.get("bayesian_assurance"),
   "假设RD":r.get("assumed_risk_difference"),"假设共同OR":r.get("assumed_common_or"),"证据状态":r.get("evidence_support")})
 return pd.DataFrame(rows)
