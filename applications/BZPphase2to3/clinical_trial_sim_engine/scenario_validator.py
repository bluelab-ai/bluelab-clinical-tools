"""Step19 sponsor-facing scenario validator."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from typing import Any
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "outputs/step18_full_preweb_package/step18a_specs/default_bzp2607_mvp.yaml"

MESSAGES = {
"custom": "自定义富集人群搜索目前不开放。当前未确认稳定获益富集亚组，反复筛选亚组可能导致数据驱动偏倚。",
"partial": "该人群仅使用当前II期数据中可重建的入排标准，不能代表完整BZP2607目标人群。",
"full": "部分III期入排标准无法在II期数据中可靠重建，当前结果为假设性场景。",
"borrow": "2022年II期目前仅可作为桥接一致性证据，剂量和mRS缺失/死亡规则尚不足以支持正式历史借用。",
"death": "Day90前死亡按mRS=6处理符合卒中mRS常见逻辑，但仍需最终SAP确认。",
"missing": "非死亡Day90 mRS缺失按未应答处理为保守假设，需结合最终SAP和敏感性分析解释。",
"supportive": "NIHSS作为支持性终点可增强证据一致性，但不提高主要终点正式成功概率。",
"hierarchy": "需预先设定检验顺序和多重性控制。",
"coprimary": "共同主要终点要求mRS和NIHSS均成功，通常会降低成功概率，仅建议作为严格敏感性分析。",
"adjusted": "协变量调整分析可能提高统计效率，但必须在III期揭盲前预先写入SAP。",
"center": "当前II期中心较稀疏，中心效应处理方式需由最终SAP预先规定。",
"bayesian": "贝叶斯成功阈值和先验设置尚未在方案/SAP中确认，当前仅用于探索性保证概率分析。",
"n": "样本量超出当前已验证情景范围，结果具有额外外推不确定性。",
"n_shrink_enrich": "无效应折减与富集同时启用具有很高假设负担，不建议作为正式设计依据。",
"mrs02": "Step16X中mRS 0–2治疗信号较弱，仅建议作为终点敏感性分析。",
"allocation": "Step16X基础模拟中2:1分配的探索性成功概率低于1:1，请结合入组和安全性需求解释。",
"dose": "200mg或600mg仅作为探索性剂量论证情景，不代表申办方推荐的III期剂量。",
"pooling": "不同活性剂量合并分析当前不开放。",
"unsupported": "所选参数组合缺少经审核的动态效应源，系统不会插值或生成结果。",
}

def load_default_config(path: str | Path | None = None) -> dict[str, Any]:
    with Path(path or DEFAULT_PATH).open(encoding="utf-8") as f:
        return yaml.safe_load(f)

def _merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    out=copy.deepcopy(base)
    for key,value in update.items():
        if isinstance(value,dict) and isinstance(out.get(key),dict): out[key]=_merge(out[key],value)
        else: out[key]=value
    return out

def validate_scenario(config: dict[str, Any] | None = None, *, sponsor_facing: bool = True, internal_override: bool = False, mode: str = "basic") -> dict[str, Any]:
    c=_merge(load_default_config(),config or {});errors=[];warnings=[];infos=[];flags=[]
    def add(target,code,message): target.append({"code":code,"message_zh":message});flags.append(code)
    t,e,m,s=c["trial"],c["effect"],c["missing_death"],c["simulation"]
    ep,sc=c["endpoint"],c["success_criterion"]
    if sponsor_facing and t.get("custom_subgroup_search"): add(errors,"V001",MESSAGES["custom"])
    if t.get("population")=="partial_bzp2607_like": add(warnings,"V002",MESSAGES["partial"])
    if t.get("population")=="analyst_assumed_full_bzp2607_like": add(warnings if mode=="advanced" else errors,"V003",MESSAGES["full"])
    if float(e.get("borrowing_weight_2022",0))>0 and not internal_override: add(errors,"V004",MESSAGES["borrow"])
    if m.get("death_before_day90_rule")=="mrs6_nonresponder" and not m.get("death_rule_sap_confirmed"): add(warnings,"V005",MESSAGES["death"])
    if m.get("unresolved_mrs_missing_rule")=="nonresponder" and not m.get("missing_rule_sap_confirmed"): add(warnings,"V006",MESSAGES["missing"])
    if ep.get("endpoint_hierarchy")=="mrs_primary_nihss_supportive": add(infos,"V007",MESSAGES["supportive"])
    if ep.get("endpoint_hierarchy")=="hierarchical_key_secondary":
        target=warnings if sc.get("multiplicity_strategy") not in [None,"","unspecified"] else errors;add(target,"V008",MESSAGES["hierarchy"])
    if ep.get("endpoint_hierarchy")=="co_primary": add(warnings,"V009",MESSAGES["coprimary"])
    if sc.get("analysis_method") in ["nihss_stratified_rd_cmh_like","covariate_adjusted_logistic","covariate_adjusted_marginal_rd"]: add(warnings,"V010",MESSAGES["adjusted"])
    if sc.get("center_adjustment") not in [None,"excluded_sparse"]: add(warnings,"V011",MESSAGES["center"])
    if s.get("method_type") in ["bayesian_assurance","both"]: add(warnings,"V012",MESSAGES["bayesian"])
    if not 1200 <= int(t.get("total_n",0)) <= 2000: add(warnings,"V013",MESSAGES["n"])
    if float(e.get("shrinkage",0))==0 and t.get("eligibility_enrichment"): add(warnings,"V014",MESSAGES["n_shrink_enrich"])
    if ep.get("primary_endpoint")=="day90_mrs02": add(warnings,"V015",MESSAGES["mrs02"])
    if t.get("allocation")=="2:1": add(warnings,"V016",MESSAGES["allocation"])
    if t.get("dose") in ["BZP 200mg BID","BZP 600mg BID"]: add(warnings,"V017",MESSAGES["dose"])
    if t.get("active_pooling"): add(errors,"V018",MESSAGES["pooling"])
    if ep.get("primary_endpoint") not in ["day90_mrs01","day90_mrs02","day90_mrs_ordinal","day14_nihss_change","day14_nihss_response"]: add(errors,"V019",MESSAGES["unsupported"])
    if t.get("dose") not in ["BZP 200mg BID","BZP 400mg BID","BZP 600mg BID"]: add(errors,"V020",MESSAGES["unsupported"])
    return {"valid":not errors,"status":"blocked" if errors else "valid_with_warnings" if warnings else "valid","errors":errors,"warnings":warnings,"infos":infos,"locked_or_invalid_flags":sorted(set(flags)),"normalized_config":c,"formal_primary_endpoint":ep.get("formal_success_endpoint","day90_mrs01")}
