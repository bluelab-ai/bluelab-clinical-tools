"""Read and write per-user training records under web/users/{username}/records/."""
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from web.config import USERS_DIR


def _get_records_dir(username: str) -> Path:
    """Get the records directory for a given username."""
    d = USERS_DIR / username / "records"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_records(username: str) -> list[dict]:
    """Find all training records for a given username.

    Returns list of dicts with keys: filename, role, data (parsed JSON)
    """
    results = []
    records_dir = _get_records_dir(username)
    for f in sorted(records_dir.glob("*.json")):
        role = f.stem
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        results.append({
            "filename": str(f),
            "role": role,
            "learner_name": data.get("learner_name", username),
            "learner_role": data.get("learner_role", role),
            "learner_track": data.get("learner_track", "novice"),
            "current_chapter": data.get("current_chapter", "导论"),
            "last_article": data.get("last_article"),
            "chapters": data.get("chapters", {}),
            "experienced_branch": data.get("experienced_branch"),
            "has_old_gcp_basis": data.get("has_old_gcp_basis", False),
            "certificate_issued": data.get("certificate_issued", False),
            "final_score": data.get("final_score"),
            "final_grade": data.get("final_grade"),
            "data": data,
        })
    return results


def create_record(username: str, learner_name: str, role: str, role_label: str,
                  has_old_basis: bool = False) -> dict:
    """Create a new training record under the user's records directory."""
    template_path = Path(__file__).resolve().parent.parent / "assets" / "learning-record.json"
    with open(template_path, encoding="utf-8") as f:
        record = json.load(f)

    now = datetime.now().isoformat()
    record["learner_name"] = learner_name
    record["learner_role"] = role
    record["has_old_gcp_basis"] = has_old_basis
    record["learner_track"] = "experienced" if has_old_basis else "novice"
    record["first_session"] = now
    record["last_session"] = now
    record["current_chapter"] = "导论"

    records_dir = _get_records_dir(username)
    filepath = records_dir / f"{role}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return record


def load_record(username: str, role: str) -> Optional[dict]:
    """Load an existing training record."""
    records_dir = _get_records_dir(username)
    filepath = records_dir / f"{role}.json"
    if not filepath.exists():
        return None
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def save_record(username: str, role: str, record: dict):
    """Save a training record to disk."""
    records_dir = _get_records_dir(username)
    filepath = records_dir / f"{role}.json"
    record["last_session"] = datetime.now().isoformat()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def update_chapter_status(record: dict, chapter: str, status: str):
    """Update a chapter's status in the record."""
    if "chapters" not in record:
        record["chapters"] = {}
    if chapter not in record["chapters"]:
        record["chapters"][chapter] = {"title": chapter, "status": "idle"}
    record["chapters"][chapter]["status"] = status


def set_quiz_score(record: dict, chapter: str, score: float):
    """Record a chapter quiz score."""
    if "chapters" not in record:
        record["chapters"] = {}
    if chapter not in record["chapters"]:
        record["chapters"][chapter] = {"title": chapter, "status": "idle"}
    record["chapters"][chapter]["quiz_score"] = score


def get_progress_summary(record: dict) -> str:
    """Generate a human-readable progress description."""
    track = record.get("learner_track", "novice")
    branch = record.get("experienced_branch")

    if track == "experienced":
        if branch == "A":
            return "差异速览已完成（A 分支）"
        elif branch == "B":
            ch = record.get("current_chapter", "")
            return f"B 分支 — 章节测验进行中（{ch}）"
        elif branch == "C":
            if record.get("final_exam_in_progress"):
                return "C 分支 — 结业考试进行中"
            return "C 分支 — 待参加结业考试"
        else:
            # Still in diff overview, haven't picked a branch yet
            diff_done = len(record.get("diff_modules_completed") or [])
            return f"老手轨 — 差异速览进行中（{diff_done}/8 模块）"

    chapters = record.get("chapters") or {}
    real_chapters = {ch: c for ch, c in chapters.items() if ch != "导论"}
    passed = sum(1 for c in real_chapters.values() if c.get("status") == "passed")
    total = len(real_chapters)  # 6

    if passed >= total:
        if record.get("final_exam_in_progress"):
            return "新手轨 — 全部章节已通过 — 结业考试进行中"
        if record.get("final_score") is not None:
            grade_map = {"excellent": "优秀", "good": "良好", "pass": "合格", "fail": "不合格"}
            grade = grade_map.get(record.get("final_grade", ""), "")
            grade_str = f" — {grade}" if grade else ""
            return f"新手轨 — 全部章节已通过 — 考试已完成{grade_str}"
        return "新手轨 — 全部章节已通过 — 待参加结业考试"

    ch = record.get("current_chapter", "导论")
    # Only count chapters that come before current_chapter in sequence.
    # If the student rolled back (e.g., current_chapter=第一章), chapters
    # after it don't count as passed in the display — they'll be re-earned.
    ordered_chapters = ["第一章", "第二章", "第三章", "第四章", "第五章", "第六章"]
    current_idx = None
    for i, c_name in enumerate(ordered_chapters):
        if c_name == ch:
            current_idx = i
            break
    if current_idx is not None:
        passed = sum(
            1 for c_name in ordered_chapters[:current_idx]
            if real_chapters.get(c_name, {}).get("status") == "passed"
        )
    else:
        passed = 0
    return f"新手轨 — 已通过 {passed}/{total} 章 — 当前：{ch}"
