"""Certificate route: generate and serve completion certificates."""
import random
import string
from datetime import date, datetime
from pathlib import Path
from fastapi import APIRouter, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from web.config import SKILL_ROOT
from web.record_manager import load_record, save_record
from web.user_manager import load_account

router = APIRouter()

TEMPLATE_PATH = SKILL_ROOT / "assets" / "completion-cert.html"
CERTS_DIR = SKILL_ROOT / "web" / "certs"

GRADE_LABELS = {
    "excellent": "优秀",
    "good": "良好",
    "pass": "合格",
    "fail": "不合格",
}

TRACK_LABELS = {
    "novice": "系统培训",
    "experienced": "差异速览",
}

CHAPTER_KEYS = ["第一章", "第二章", "第三章", "第四章", "第五章", "第六章"]
CHAPTER_PLACEHOLDERS = ["ch1_rate", "ch2_rate", "ch3_rate", "ch4_rate", "ch5_rate", "ch6_rate"]


def _generate_cert_id():
    """Generate unique certificate ID: GCP26-YYYYMMDD-HHMMSSXXX"""
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"GCP26-{timestamp}{random_suffix}"


def _build_cert_html(record: dict, cert_id: str) -> str:
    """Fill the certificate template with record data."""
    if not TEMPLATE_PATH.exists():
        return None
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()

    learner_name = record.get("learner_name", "")
    track = record.get("learner_track", "novice")
    grade_key = record.get("final_grade", "")
    grade = GRADE_LABELS.get(grade_key, grade_key)
    score_rate = round((record.get("final_score") or 0) * 100)
    issue_date = date.today().strftime("%Y年%m月%d日")
    track_label = TRACK_LABELS.get(track, track)

    chapter_scores = record.get("chapter_scores", {})
    ch_rates = {}
    for ch, placeholder in zip(CHAPTER_KEYS, CHAPTER_PLACEHOLDERS):
        score = chapter_scores.get(ch)
        if score is not None and isinstance(score, (int, float)):
            ch_rates[placeholder] = str(int(score)) + "%"
        else:
            ch_rates[placeholder] = "—"

    html = template
    html = html.replace("{{learner_name}}", learner_name)
    html = html.replace("{{track_label}}", track_label)
    html = html.replace("{{grade}}", grade)
    html = html.replace("{{score_rate}}", str(score_rate))
    html = html.replace("{{certificate_id}}", cert_id)
    html = html.replace("{{issue_date}}", issue_date)
    for placeholder, val in ch_rates.items():
        html = html.replace(f"{{{{{placeholder}}}}}", val)

    return html


@router.get("/generate", response_class=HTMLResponse)
async def cert_generate(request: Request,
                        username: str = Cookie(None),
                        learner_role: str = Cookie(None)):
    """Generate certificate and show it."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    if not record:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    # Check eligibility
    track = record.get("learner_track", "novice")
    branch = record.get("experienced_branch")
    if track == "experienced" and branch not in ("C",):
        return HTMLResponse(
            "<h2>A 和 B 分支不发证</h2><p>需通过 C 分支结业考试（≥60%）才可获证。</p>"
            "<a href='/'>返回首页</a>",
            status_code=403
        )

    final_score = record.get("final_score")
    if final_score is None:
        return HTMLResponse(
            "<h2>请先完成结业考试</h2><p>完成全部六章并通过结业考试后可获证。</p>"
            "<a href='/exam/start'>去考试</a>",
            status_code=403
        )

    # Check pass (>=60%)
    if (final_score or 0) < 0.6:
        return HTMLResponse(
            f"<h2>结业考试未通过</h2><p>正确率 {round(final_score * 100)}%，需 ≥60%。</p>"
            "<a href='/exam/start'>重新考试</a>",
            status_code=403
        )

    # Generate or reuse certificate ID
    cert_id = record.get("certificate_id") or _generate_cert_id()

    # Build certificate HTML
    cert_html = _build_cert_html(record, cert_id)
    if not cert_html:
        return HTMLResponse("证书模板未找到。", status_code=500)

    # Save certificate to disk
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = real_name or username
    filename = f"completion-{safe_name}-{learner_role}-{date.today().strftime('%Y%m%d')}.html"
    cert_path = CERTS_DIR / filename
    with open(cert_path, "w", encoding="utf-8") as f:
        f.write(cert_html)

    # Update record
    record["certificate_issued"] = True
    record["certificate_id"] = cert_id
    save_record(username, learner_role, record)

    # Inject a control bar + body padding into the cert HTML and return it directly
    control_bar = """<div id="cert-control-bar" style="position:fixed;top:0;left:0;right:0;background:#1a3a5c;color:white;
        padding:12px 24px;display:flex;justify-content:space-between;align-items:center;z-index:9999;
        font-family:'PingFang SC','Microsoft YaHei',sans-serif;box-shadow:0 2px 8px rgba(0,0,0,0.2);">
        <span style="font-weight:700;">GCP 2026 培训证书</span>
        <div style="display:flex;gap:12px;">
            <button onclick="window.print()" style="color:white;background:#c9a962;padding:8px 18px;
                border-radius:4px;border:none;cursor:pointer;font-weight:600;font-size:14px;">📥 保存为 PDF / 打印</button>
            <a href="/" style="color:#ccc;padding:8px 12px;text-decoration:none;">退出 ↩</a>
        </div>
    </div>
    <style>
    body { padding-top: 64px !important; }
    @media print {
      body { padding-top: 0 !important; }
      #cert-control-bar { display: none !important; }
    }
    </style>
    """
    cert_html_with_bar = cert_html.replace("<body>", "<body>" + control_bar)
    return HTMLResponse(cert_html_with_bar)


@router.get("/download")
async def cert_download(request: Request,
                        username: str = Cookie(None),
                        learner_role: str = Cookie(None)):
    """Download the certificate HTML file."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)
    real_name = account.get("real_name", username) if account else username
    filename = f"completion-{real_name}-{learner_role}-{date.today().strftime('%Y%m%d')}.html"
    filepath = CERTS_DIR / filename
    if filepath.exists():
        return FileResponse(str(filepath), filename=filename,
                           media_type="text/html")
    return HTMLResponse("Certificate file not found.", status_code=404)
