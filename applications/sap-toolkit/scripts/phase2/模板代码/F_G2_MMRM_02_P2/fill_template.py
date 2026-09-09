"""Fill the two-group repeated-measures MMRM least-squares-mean shell."""

from __future__ import annotations

import copy

from scripts.phase2.mmrm_utils import expand_visit_rows


REQUIRES_EXPLICIT_VISITS = True


def fill_template(semantic: dict, projects: list[dict], visits: list[str]) -> dict:
    result = copy.deepcopy(semantic)
    result["rows"] = expand_visit_rows(semantic, visits)
    result.pop("sections", None)
    result.pop("repeat_pattern", None)
    return result
