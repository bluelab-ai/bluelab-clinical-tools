"""Fill the two-group MMRM model-statistics shell."""

from __future__ import annotations

import copy

from scripts.phase2.mmrm_utils import expand_indicator_rows


def fill_template(semantic: dict, projects: list[dict]) -> dict:
    result = copy.deepcopy(semantic)
    result["rows"] = expand_indicator_rows(semantic, projects)
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result
