from __future__ import annotations

from typing import Any


RULE_LABELS = {
    "observed_available_case": "观察病例分析",
    "death6_conservative_nonresponder": "死亡按mRS=6，其余缺失按未应答",
    "death6_locf_like": "死亡按mRS=6，类LOCF敏感性分析",
    "death6_multiple_imputation": "死亡按mRS=6，多重插补敏感性分析",
    "tipping_point_worst_case": "倾覆点/最不利情景敏感性分析",
}


def summarize_missing_death(config: dict[str, Any]) -> dict[str, Any]:
    rule = config["missing_death"].get("sensitivity_rule", "death6_conservative_nonresponder")
    return {
        "rule": rule,
        "rule_zh": RULE_LABELS.get(rule, rule),
        "death_as_mrs6": rule != "observed_available_case",
        "sap_confirmation_needed": True,
        "patient_level_exported": False,
    }
