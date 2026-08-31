from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import logit

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs/step19_dynamic_chinese_mvp/model_assets/effect_source_registry.csv"
DOSES = ("200mg", "400mg", "600mg")
MISSING = ("death6_multiple_imputation", "death6_locf_like", "death6_conservative_nonresponder", "observed_available_case")
MISSING_SHORT = {"death6_multiple_imputation":"MI", "death6_locf_like":"LOCF", "death6_conservative_nonresponder":"NR", "observed_available_case":"AC"}
RETAINED_EFFECT_FRACTION = 0.50
VERSION = "step24ar-anchor-v1.0"


def _hash(row: dict[str, Any]) -> str:
    payload=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@lru_cache(maxsize=1)
def canonical_phase2_registry() -> pd.DataFrame:
    source=pd.read_csv(SOURCE)
    selected=source[(source.endpoint.eq("day90_mrs01")) & (source.population.eq("phase2_2026_allcomers")) & source.dose.isin([f"BZP {x} BID" for x in DOSES]) & source.missing_rule.isin(MISSING)].copy()
    rows=[]
    for _, item in selected.iterrows():
        dose=str(item.dose).replace("BZP ","").replace(" BID","")
        pc=float(item.control_outcome)
        raw_rd=float(item.treatment_effect)
        raw_pt=float(np.clip(pc+raw_rd,1e-6,1-1e-6))
        raw_rd_se=float(item.uncertainty_estimate)
        raw_log_or=float(logit(raw_pt)-logit(pc))
        raw_log_or_se=float(raw_rd_se/(raw_pt*(1-raw_pt)))
        rd=raw_rd*RETAINED_EFFECT_FRACTION
        pt=float(np.clip(pc+rd,1e-6,1-1e-6))
        log_or=float(logit(pt)-logit(pc))
        rd_se=float(item.uncertainty_estimate)*RETAINED_EFFECT_FRACTION
        log_or_se=float(rd_se/(pt*(1-pt)))
        base={
            "anchor_id":f"P2C-{dose.replace('mg','')}-{MISSING_SHORT[item.missing_rule]}-V1",
            "anchor_type":"phase2_canonical",
            "dose":dose,
            "endpoint":"Day90 mRS 0–1",
            "missing_method":item.missing_rule,
            "control_event_probability":pc,
            "active_event_probability":pt,
            "risk_difference":rd,
            "odds_ratio":float(np.exp(log_or)),
            "log_odds_ratio":log_or,
            "log_odds_ratio_se":log_or_se,
            "raw_active_event_probability":raw_pt,
            "raw_risk_difference":raw_rd,
            "raw_risk_difference_se":raw_rd_se,
            "raw_log_odds_ratio":raw_log_or,
            "raw_log_odds_ratio_se":raw_log_or_se,
            "shrinkage_regularization":"Step22预设效应保留50%（shrinkage=0.5）",
            "raw_or_model_shrunk":"model-shrunk",
            "source_step":"Step22/Step23已验证全人群效应源",
            "source_file":str(item.source_file),
            "analysis_method":"双侧α=0.05风险差成功规则",
            "version":VERSION,
        }
        base["anchor_hash"]=_hash(base)
        rows.append(base)
    table=pd.DataFrame(rows).sort_values(["dose","missing_method"]).reset_index(drop=True)
    expected={(dose,missing) for dose in DOSES for missing in MISSING}
    found=set(zip(table.dose,table.missing_method))
    if found != expected or table.duplicated(["dose","missing_method"]).any():
        raise ValueError(f"规范Phase II锚点不唯一或不完整：{found ^ expected}")
    return table


def registry_for_export() -> pd.DataFrame:
    base=canonical_phase2_registry().copy()
    custom=base.copy()
    custom["anchor_id"]="CUSTOM-RULE-"+custom.anchor_id
    custom["anchor_type"]="custom_multiplier_rule"
    custom["shrinkage_regularization"]="Phase II原始观察风险差乘一次用户系数；NIHSS偏差仅乘交互保留比例"
    custom["raw_or_model_shrunk"]="rule"
    custom["anchor_hash"]=[_hash(row) for row in custom.drop(columns=["anchor_hash"]).to_dict("records")]
    pc,pt=.514,.621
    log_or=float(logit(pt)-logit(pc))
    v03={
        "anchor_id":"V03-400-DESIGN-V1", "anchor_type":"v03_design_assumption", "dose":"400mg",
        "endpoint":"Day90 mRS 0–1", "missing_method":"all_supported", "control_event_probability":pc,
        "active_event_probability":pt, "risk_difference":pt-pc, "odds_ratio":float(np.exp(log_or)),
        "log_odds_ratio":log_or, "log_odds_ratio_se":0.0, "raw_risk_difference":pt-pc,
        "shrinkage_regularization":"无；条件性书面设计假设", "raw_or_model_shrunk":"design-assumption",
        "source_step":"BZP2607 V0.3书面设计假设", "source_file":"方案设计率62.1%对51.4%",
        "analysis_method":"双侧α=0.05风险差成功规则", "version":VERSION,
    }
    v03["anchor_hash"]=_hash(v03)
    return pd.concat([base,custom,pd.DataFrame([v03])],ignore_index=True)


def resolve_anchor(dose: str, missing_method: str, effect_source: str, multiplier: float=1.0) -> dict[str, Any]:
    if effect_source == "v03_design":
        if dose != "400mg": raise ValueError("V0.3方案设计假设仅适用于400 mg BID。")
        row=registry_for_export().query("anchor_type=='v03_design_assumption'").iloc[0].to_dict()
        row.update({"applied_multiplier":1.0,"base_anchor_id":row["anchor_id"],"effect_source":"v03_design"})
    else:
        matches=canonical_phase2_registry().query("dose==@dose and missing_method==@missing_method")
        if len(matches)!=1: raise ValueError("规范Phase II锚点不唯一。")
        row=matches.iloc[0].to_dict()
        row["base_anchor_id"]=row["anchor_id"]
        if effect_source == "custom_multiplier":
            applied=float(multiplier)
            pc=float(row["control_event_probability"])
            row["risk_difference"]=float(row["raw_risk_difference"])*applied
            row["active_event_probability"]=float(np.clip(pc+row["risk_difference"],1e-6,1-1e-6))
            row["log_odds_ratio"]=float(logit(row["active_event_probability"])-logit(pc))
            custom_rd_se=float(row["raw_risk_difference_se"])*abs(applied)
            row["log_odds_ratio_se"]=float(custom_rd_se/(row["active_event_probability"]*(1-row["active_event_probability"])))
            row["odds_ratio"]=float(np.exp(row["log_odds_ratio"]))
            row["anchor_id"]=f"CUSTOM-{int(round(multiplier*100))}-{row['base_anchor_id']}"
            row["applied_multiplier"]=applied
            row["effect_reference"]="phase2_raw_risk_difference"
            row["effect_source"]="custom_multiplier"
        else:
            row["applied_multiplier"]=1.0
            row["effect_source"]="phase2_model"
    hash_fields={key:row[key] for key in ["anchor_id","base_anchor_id","dose","missing_method","control_event_probability","active_event_probability","log_odds_ratio","log_odds_ratio_se","applied_multiplier","effect_source"]}
    row["applied_anchor_hash"]=_hash(hash_fields)
    return row
