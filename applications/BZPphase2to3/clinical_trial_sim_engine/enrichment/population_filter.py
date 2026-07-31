from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class FilterDefinition:
    code: str
    label_zh: str
    variable: str
    level: float | str
    availability: str
    tier: str
    rule_zh: str
    predicate: Callable[[pd.DataFrame], pd.Series]


FILTERS = {
    "onset_le24": FilterDefinition("onset_le24", "发病至首次给药不超过24小时", "onset_within_24h", 1, "cross_study_ready", "basic", "<=24小时", lambda d: d.onset_within_24h.eq(1)),
    "nihss_6_10": FilterDefinition("nihss_6_10", "基线NIHSS 6-10分", "baseline_nihss_stratum", 0, "cross_study_ready", "basic", "6-10分", lambda d: d.baseline_nihss.between(6, 10)),
    "age_lt65": FilterDefinition("age_lt65", "年龄小于65岁", "age_ge65", 0, "cross_study_ready", "basic", "<65岁", lambda d: d.age.lt(65)),
    "ocsp_taci": FilterDefinition("ocsp_taci", "OCSP为TACI", "ocsp_taci", 1, "2026_only", "basic", "TACI", lambda d: d.ocsp_taci.eq(1)),
    "no_previous_stroke": FilterDefinition("no_previous_stroke", "无既往卒中", "previous_stroke", 0, "cross_study_ready", "basic", "无既往卒中", lambda d: d.previous_stroke.eq(0)),
    "baseline_mrs_lt3": FilterDefinition("baseline_mrs_lt3", "基线mRS低于3分", "baseline_mrs_ge3", 0, "2026_only", "basic", "<3分", lambda d: d.baseline_mrs.lt(3)),
    "motor_low": FilterDefinition("motor_low", "基线肢体运动缺损较轻", "limb_motor_high", 0, "cross_study_ready", "advanced", "四项合计<4", lambda d: d.limb_motor_sum.lt(4)),
    "female": FilterDefinition("female", "女性", "sex_male", 0, "cross_study_ready", "advanced", "女性", lambda d: d.sex_male.eq(0)),
    "bmi_18_5_27_9": FilterDefinition("bmi_18_5_27_9", "BMI 18.5-27.9 kg/m²", "bmi", "18.5-27.9", "2026_only", "advanced", "18.5-27.9 kg/m²", lambda d: d.bmi.between(18.5, 27.9)),
}

APPROVED_TWO_VARIABLE_COMBINATIONS = {
    frozenset({"onset_le24", "nihss_6_10"}),
    frozenset({"onset_le24", "age_lt65"}),
    frozenset({"nihss_6_10", "age_lt65"}),
    frozenset({"onset_le24", "no_previous_stroke"}),
}

LOCKED_CODES = {"site", "center", "atrial_fibrillation", "early_reperfusion", "custom_threshold", "automatic_cutpoint_search"}


def validate_filters(filter_codes: list[str], source_mode: str = "phase2_2026_like") -> list[str]:
    codes = list(dict.fromkeys(filter_codes or []))
    if any(code in LOCKED_CODES for code in codes):
        raise ValueError("研究中心及其他锁定参数不能作为富集条件。")
    unknown = [code for code in codes if code not in FILTERS]
    if unknown:
        raise ValueError(f"不支持的预设富集条件：{unknown}")
    if len(codes) > 2:
        raise ValueError("仅支持无富集、单变量富集或经批准的双变量组合。")
    if len(codes) == 2 and frozenset(codes) not in APPROVED_TWO_VARIABLE_COMBINATIONS:
        raise ValueError("该双变量组合未预先批准。")
    if source_mode != "phase2_2026_like" and any(FILTERS[x].availability == "2026_only" for x in codes):
        raise ValueError("所选变量仅支持Phase2_2026来源场景。")
    return codes


def apply_filters(frame: pd.DataFrame, filter_codes: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    codes = validate_filters(filter_codes)
    mask = pd.Series(True, index=frame.index)
    for code in codes:
        mask &= FILTERS[code].predicate(frame).fillna(False)
    return frame.loc[mask].copy(), mask


def supported_combination_rows() -> list[dict[str, object]]:
    rows = [{"combination_id":"none","filter_codes":"","variable_count":0,"supported":True,"mode":"无富集"}]
    rows += [{"combination_id":code,"filter_codes":code,"variable_count":1,"supported":True,"mode":"单变量"} for code in FILTERS]
    for combo in sorted(APPROVED_TWO_VARIABLE_COMBINATIONS, key=lambda x: sorted(x)):
        codes = sorted(combo); rows.append({"combination_id":"+".join(codes),"filter_codes":"|".join(codes),"variable_count":2,"supported":True,"mode":"预设双变量"})
    return rows
