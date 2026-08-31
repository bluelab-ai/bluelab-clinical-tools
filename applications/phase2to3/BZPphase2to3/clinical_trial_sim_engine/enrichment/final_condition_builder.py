from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class LevelDefinition:
    code: str
    label_zh: str
    predicate: Callable[[pd.DataFrame], pd.Series] | None
    provenance_zh: str


@dataclass(frozen=True)
class FeatureDefinition:
    code: str
    label_zh: str
    levels: tuple[LevelDefinition, ...]
    availability_zh: str
    exhaustive_level_codes: frozenset[str] | None = None


U = LevelDefinition("unrestricted", "无限制", None, "不筛选且交互贡献为0")
AGE_SOURCE_MIN = 40
AGE_SOURCE_MAX = 80
AGE_RANGE_PATTERN = re.compile(r"^range_(\d{1,3})_(\d{1,3})$")


def age_range_code(age_min: int, age_max: int) -> str:
    lower = int(age_min)
    upper = int(age_max)
    if not AGE_SOURCE_MIN <= lower <= AGE_SOURCE_MAX:
        raise ValueError(f"年龄下限必须在{AGE_SOURCE_MIN}至{AGE_SOURCE_MAX}岁之间。")
    if not AGE_SOURCE_MIN <= upper <= AGE_SOURCE_MAX:
        raise ValueError(f"年龄上限必须在{AGE_SOURCE_MIN}至{AGE_SOURCE_MAX}岁之间。")
    if lower > upper:
        raise ValueError("年龄下限不能高于年龄上限。")
    return f"range_{lower}_{upper}"


def parse_age_range_code(level_code: str) -> tuple[int, int] | None:
    match = AGE_RANGE_PATTERN.fullmatch(str(level_code))
    if not match:
        return None
    lower, upper = (int(value) for value in match.groups())
    age_range_code(lower, upper)
    return lower, upper


FEATURES: dict[str, FeatureDefinition] = {
    "age": FeatureDefinition("age", "年龄", (U,
        LevelDefinition("lt65", "<65岁", lambda d: d.age.lt(65), "预设临床分层"),
        LevelDefinition("ge65", "≥65岁", lambda d: d.age.ge(65), "甲方建议年龄阈值；Phase II FAS 214例"),
        LevelDefinition("ge70", "≥70岁", lambda d: d.age.ge(70), "甲方建议5岁递增阈值；Phase II FAS 133例"),
        LevelDefinition("ge75", "≥75岁", lambda d: d.age.ge(75), "甲方建议5岁递增阈值；Phase II FAS 48例，数据有限"),
        LevelDefinition("ge80", "≥80岁", lambda d: d.age.ge(80), "甲方建议5岁递增阈值；Phase II FAS 2例，仅人群洞察")), "数据有限", frozenset({"lt65", "ge65"})),
    "sex": FeatureDefinition("sex", "性别", (U,
        LevelDefinition("male", "男性", lambda d: d.sex_male.eq(1), "结构化性别字段"),
        LevelDefinition("female", "女性", lambda d: d.sex_male.eq(0), "结构化性别字段")), "可模拟", frozenset({"male", "female"})),
    "onset": FeatureDefinition("onset", "发病至首次给药时间", (U,
        LevelDefinition("le24", "≤24小时", lambda d: d.onset_within_24h.eq(1), "结构化时间差/直接二分类"),
        LevelDefinition("gt24", ">24小时", lambda d: d.onset_within_24h.eq(0), "结构化时间差/直接二分类；不推断缺失")), "可模拟", frozenset({"le24", "gt24"})),
    "nihss": FeatureDefinition("nihss", "基线NIHSS", (U,
        LevelDefinition("6_10", "6–10分", lambda d: d.baseline_nihss.between(6, 10), "拟议Ⅲ期随机分层"),
        LevelDefinition("11_20", "11–20分（Ⅱ期实际观察11–20分）", lambda d: d.baseline_nihss.between(11, 20), "拟议Ⅲ期随机分层；披露实际范围")), "数据有限"),
    "ocsp": FeatureDefinition("ocsp", "OCSP分型", (U,
        LevelDefinition("taci", "TACI", lambda d: d.ocsp_taci.eq(1), "结构化XPT字段"),
        LevelDefinition("paci", "PACI", lambda d: d.ocsp_paci.eq(1), "结构化XPT字段"),
        LevelDefinition("laci", "LACI", lambda d: d.ocsp_laci.eq(1), "结构化XPT字段；仅2例"),
        LevelDefinition("poci", "POCI", lambda d: d.ocsp_poci.eq(1), "结构化XPT字段；Ⅱ期0例")), "数据有限", frozenset({"taci", "paci", "laci", "poci"})),
    "previous_stroke": FeatureDefinition("previous_stroke", "既往卒中", (U,
        LevelDefinition("no", "无既往卒中", lambda d: d.previous_stroke_corrected.eq(0), "Step21R结构化语义校正"),
        LevelDefinition("yes", "有既往卒中", lambda d: d.previous_stroke_corrected.eq(1), "Step21R结构化语义校正")), "可模拟", frozenset({"no", "yes"})),
    "prestroke_mrs": FeatureDefinition("prestroke_mrs", "发病前功能状态（卒前mRS）", (U,
        LevelDefinition("recorded_0", "有记录且mRS=0", lambda d: d.previous_stroke_corrected.eq(1) & d.prestroke_mrs_corrected.eq(0), "仅既往卒中者适用"),
        LevelDefinition("recorded_1", "有记录且mRS=1", lambda d: d.previous_stroke_corrected.eq(1) & d.prestroke_mrs_corrected.eq(1), "仅既往卒中者适用"),
        LevelDefinition("recorded_le1", "有记录且mRS≤1", lambda d: d.previous_stroke_corrected.eq(1) & d.prestroke_mrs_corrected.le(1), "仅既往卒中者适用"),
        LevelDefinition("recorded_ge2", "有记录且mRS≥2", lambda d: d.previous_stroke_corrected.eq(1) & d.prestroke_mrs_corrected.ge(2), "仅既往卒中者适用；Ⅱ期无数据"),
        LevelDefinition("previous_missing", "有既往卒中但卒前mRS缺失", lambda d: d.previous_stroke_corrected.eq(1) & d.prestroke_mrs_corrected.isna(), "缺失与不适用分开")), "数据有限"),
    "screening_mrs": FeatureDefinition("screening_mrs", "本次卒中筛选期mRS", (U,
        LevelDefinition("raw_2", "原始分值2分", lambda d: d.baseline_mrs.eq(2), "结构化筛选期原始分值"),
        LevelDefinition("raw_3", "原始分值3分", lambda d: d.baseline_mrs.eq(3), "结构化筛选期原始分值"),
        LevelDefinition("raw_4", "原始分值4分", lambda d: d.baseline_mrs.eq(4), "结构化筛选期原始分值"),
        LevelDefinition("raw_5", "原始分值5分", lambda d: d.baseline_mrs.eq(5), "结构化筛选期原始分值"),
        LevelDefinition("0_2", "0–2分", lambda d: d.baseline_mrs.between(0, 2), "分析者预设衍生分组；技术审计显示Ⅱ期来源实际仅2分"),
        LevelDefinition("3_5", "3–5分（临床功能依赖分组）", lambda d: d.baseline_mrs.between(3, 5), "分析者预设衍生分组"),
        LevelDefinition("0_3", "2–3分", lambda d: d.baseline_mrs.between(0, 3), "原内部派生定义为mRS 0–3；Phase2_2026实际观察范围为2–5，因此该来源子集实际对应2–3分。"),
        LevelDefinition("4_5", "4–5分（中重度功能障碍分组）", lambda d: d.baseline_mrs.between(4, 5), "分析者预设衍生分组")), "数据有限"),
    "motor": FeatureDefinition("motor", "基线肢体运动缺损", (U,
        LevelDefinition("low", "较轻（四项合计<4分）", lambda d: d.limb_motor_sum.lt(4), "NIHSS双侧上下肢运动四项合计"),
        LevelDefinition("high", "较重（四项合计≥4分）", lambda d: d.limb_motor_sum.ge(4), "NIHSS双侧上下肢运动四项合计"),
        LevelDefinition("le4", "四项合计≤4分", lambda d: d.limb_motor_sum.le(4), "甲方建议敏感性阈值；包含恰好4分患者"),
        LevelDefinition("gt4", "四项合计>4分", lambda d: d.limb_motor_sum.gt(4), "甲方建议敏感性阈值的补集")), "可模拟", frozenset({"low", "high"})),
    "bmi": FeatureDefinition("bmi", "BMI", (U,
        LevelDefinition("in_range", "18.5–27.9 kg/m²", lambda d: d.bmi.between(18.5, 27.9), "预设临床范围"),
        LevelDefinition("outside", "范围外", lambda d: ~d.bmi.between(18.5, 27.9) & d.bmi.notna(), "预设临床范围补集")), "数据有限", frozenset({"in_range", "outside"})),
}

REMOVED_LEVEL_WARNING = "原场景包含已移除的NIHSS 12–15分选项，系统已将该特征重置为无限制。"
REMOVED_NIHSS_LEVELS = frozenset({"12_15", "nihss_12_15"})


def migrate_removed_conditions(conditions: list[dict] | None) -> tuple[list[dict], list[str]]:
    migrated = []
    removed = False
    for item in conditions or []:
        feature = str(item.get("feature", ""))
        if feature == "nihss_12_15":
            removed = True
            continue
        copied = dict(item)
        raw = copied.get("levels", copied.get("level", []))
        levels = [raw] if isinstance(raw, str) else list(raw or [])
        if feature == "nihss":
            kept = [level for level in levels if str(level) not in REMOVED_NIHSS_LEVELS]
            removed = removed or len(kept) != len(levels)
            if not kept:
                continue
            copied["levels"] = kept
            copied.pop("level", None)
        migrated.append(copied)
    return migrated, [REMOVED_LEVEL_WARNING] if removed else []


def level_definition(feature_code: str, level_code: str) -> LevelDefinition:
    if feature_code == "age":
        bounds = parse_age_range_code(level_code)
        if bounds is not None:
            lower, upper = bounds
            return LevelDefinition(
                level_code,
                f"{lower}–{upper}岁（含边界）",
                lambda d, lo=lower, hi=upper: d.age.between(lo, hi, inclusive="both"),
                f"Phase II FAS实际观察年龄闭区间；来源范围{AGE_SOURCE_MIN}–{AGE_SOURCE_MAX}岁",
            )
    try:
        return next(level for level in FEATURES[feature_code].levels if level.code == level_code)
    except (KeyError, StopIteration) as exc:
        raise ValueError(f"不支持的富集条件：{feature_code}/{level_code}") from exc


def normalize_conditions(conditions: list[dict] | None) -> list[dict[str, object]]:
    merged: dict[str, set[str]] = {}
    for item in conditions or []:
        feature = str(item.get("feature", ""))
        if feature not in FEATURES:
            raise ValueError(f"不支持的富集特征：{feature}")
        raw = item.get("levels", item.get("level", []))
        levels = [raw] if isinstance(raw, str) else list(raw or [])
        valid = {level.code for level in FEATURES[feature].levels}
        unknown = {
            level
            for level in set(levels) - valid
            if not (feature == "age" and parse_age_range_code(str(level)) is not None)
        }
        if unknown:
            raise ValueError(f"{FEATURES[feature].label_zh}包含不支持水平：{sorted(unknown)}")
        selected = {str(x) for x in levels if x != "unrestricted"}
        if selected:
            merged.setdefault(feature, set()).update(selected)
    normalized = []
    for feature in sorted(merged):
        selected = merged[feature]
        exhaustive = FEATURES[feature].exhaustive_level_codes
        if exhaustive and selected == exhaustive:
            continue
        normalized.append({"feature": feature, "levels": sorted(selected)})
    return normalized


def condition_mask(frame: pd.DataFrame, conditions: list[dict] | None) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for item in normalize_conditions(conditions):
        within = pd.Series(False, index=frame.index)
        for level_code in item["levels"]:
            predicate = level_definition(str(item["feature"]), str(level_code)).predicate
            if predicate is not None:
                within |= predicate(frame).fillna(False)
        mask &= within
    return mask


def condition_summary_zh(conditions: list[dict] | None) -> str:
    chunks = []
    for item in normalize_conditions(conditions):
        feature = FEATURES[str(item["feature"])]
        levels = " 或 ".join(level_definition(feature.code, str(code)).label_zh for code in item["levels"])
        chunks.append(f"{feature.label_zh}={levels}")
    return " 且 ".join(chunks) if chunks else "无限制（全人群）"


def condition_hash(conditions: list[dict] | None) -> str:
    payload = json.dumps(normalize_conditions(conditions), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def schema() -> dict:
    return {
        "logic_between_features": "AND",
        "logic_within_feature": "OR",
        "dynamic_age_range": {
            "supported": True,
            "inclusive": True,
            "minimum": AGE_SOURCE_MIN,
            "maximum": AGE_SOURCE_MAX,
            "code_pattern": "range_{minimum}_{maximum}",
        },
        "features": [
            {
                "code": feature.code,
                "label_zh": feature.label_zh,
                "availability_zh": feature.availability_zh,
                "levels": [
                    {
                        "code": level.code,
                        "label_zh": level.label_zh,
                        "provenance_zh": level.provenance_zh,
                    }
                    for level in feature.levels
                ],
            }
            for feature in FEATURES.values()
        ],
    }
