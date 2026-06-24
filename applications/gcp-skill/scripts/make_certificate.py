#!/usr/bin/env python3
"""Generate GCP 2026 training certificate from a per-user record file.

Usage: python3 scripts/make_certificate.py {姓名} {角色}

Reads .training-records/{姓名}-{角色}.json, populates the HTML template,
and writes .training-records/completion-{姓名}-{角色}-{YYYYMMDD}.html
"""

import json
import random
import string
import sys
from datetime import date, datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_ROOT / "assets" / "completion-cert.html"
OUTPUT_DIR = SKILL_ROOT / ".training-records"

GRADE_LABELS = {
    "excellent": "优秀",
    "good": "良好",
    "pass": "合格",
    "fail": "不合格",
}

TRACK_LABELS = {
    "novice": "完整学习",
    "experienced": "差异速通",
}

CHAPTER_KEYS = ["第一章", "第二章", "第三章", "第四章", "第五章", "第六章"]
CHAPTER_PLACEHOLDERS = ["ch1_rate", "ch2_rate", "ch3_rate", "ch4_rate", "ch5_rate", "ch6_rate"]


def _generate_cert_id():
    """Generate unique certificate ID: GCP26-YYYYMMDD-HHMMSSXXX"""
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"GCP26-{timestamp}{random_suffix}"


def generate_certificate(name, role):
    """Generate certificate HTML from {name}-{role}.json"""
    record_path = OUTPUT_DIR / f"{name}-{role}.json"

    if not record_path.exists():
        print(f"Error: No record found for {name} ({role}). Complete training first.")
        return None

    with open(record_path) as f:
        record = json.load(f)

    if not TEMPLATE_PATH.exists():
        print(f"Error: {TEMPLATE_PATH} not found.")
        return None

    with open(TEMPLATE_PATH) as f:
        template = f.read()

    learner_name = record.get("learner_name", name)
    track = record.get("learner_track", "novice")
    grade_key = record.get("final_grade", "")
    grade = GRADE_LABELS.get(grade_key, grade_key)
    score_rate = round(record.get("final_score", 0) * 100)
    certificate_id = record.get("certificate_id", _generate_cert_id())
    issue_date = date.today().strftime("%Y年%m月%d日")
    track_label = TRACK_LABELS.get(track, track)
    learner_role = record.get("learner_role", role)

    chapter_scores = record.get("chapter_scores", {})
    ch_rates = {}
    for ch, placeholder in zip(CHAPTER_KEYS, CHAPTER_PLACEHOLDERS):
        score = chapter_scores.get(ch)
        if score is not None and isinstance(score, (int, float)):
            ch_rates[placeholder] = str(round(score * 100)) + "%"
        else:
            ch_rates[placeholder] = "—"

    html = template
    html = html.replace("{{learner_name}}", learner_name)
    html = html.replace("{{track_label}}", track_label)
    html = html.replace("{{grade}}", grade)
    html = html.replace("{{score_rate}}", str(score_rate))
    html = html.replace("{{certificate_id}}", certificate_id)
    html = html.replace("{{issue_date}}", issue_date)
    for placeholder, val in ch_rates.items():
        html = html.replace(f"{{{{{placeholder}}}}}", val)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"completion-{learner_name}-{learner_role}-{date.today().strftime('%Y%m%d')}.html"
    output_path = OUTPUT_DIR / filename
    with open(output_path, "w") as f:
        f.write(html)

    # Update record with cert info
    record["certificate_issued"] = True
    record["certificate_id"] = certificate_id
    with open(record_path, "w") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    print(f"Certificate saved to: {output_path}")
    print(f"Certificate ID: {certificate_id}")
    return str(output_path)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        generate_certificate(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python3 scripts/make_certificate.py {姓名} {角色}")
        sys.exit(1)
