#!/usr/bin/env python3
"""
Build an interactive QC report viewer HTML page for Protocol-Table QC.

Input:
  - QC一致性质控报告.md (single comprehensive markdown report)

Output:
  A single self-contained HTML file with:
    - Cover page (unified template)
    - Top bar with stats capsules (🔴🟡🟢 counts)
    - Left sidebar: floating TOC of 9 sections, click to jump, scroll-spy
    - Right panel: full rendered markdown report
    - Back-to-top button

Usage:
    python3 build_report_viewer.py \\
        --md QC一致性质控报告.md \\
        --output QC可视化报告.html
"""

import argparse
import html as html_mod
import json
import re
from pathlib import Path

import markdown

try:
    from PIL import Image
    import base64 as b64_mod
    import io
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

SCRIPT_DIR = Path(__file__).resolve().parent

# ── CSS ──────────────────────────────────────────────────────────────────────
CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif; }
body { display: flex; flex-direction: column; overflow: hidden; background: #f8fafc; color: #0f172a; }

/* Header */
.top-bar {
  display: flex; align-items: center; gap: 16px;
  padding: 16px 24px; background: #fff;
  border-bottom: 1px solid rgba(226,232,240,0.7); flex-shrink: 0;
}
.top-bar h1 { font-size: 16px; font-weight: 700; color: #0f172a; }
.top-bar .subtitle { font-size: 12px; color: #64748b; margin-left: 12px; }
.top-bar .stats { display: flex; gap: 10px; margin-left: auto; font-size: 12px; flex-wrap: wrap; }
.top-bar .stats span { padding: 4px 12px; border-radius: 9999px; font-weight: 600; white-space: nowrap; }
.stat-total   { background: #e0e7ff; color: #3730a3; }
.stat-critical{ background: #fee2e2; color: #991b1b; }
.stat-major   { background: #ffedd5; color: #9a3412; }
.stat-minor   { background: #dcfce7; color: #166534; }
.stat-none    { background: #f1f5f9; color: #64748b; }

/* Main layout */
.main { display: flex; flex: 1; overflow: hidden; }

/* Left sidebar — floating TOC */
.sidebar {
  width: 340px; min-width: 280px; flex-shrink: 0;
  display: flex; flex-direction: column;
  border-right: 1px solid #e2e8f0; background: #fff;
}
.sidebar .toc-header {
  padding: 16px 20px 10px; font-size: 13px; font-weight: 700; color: #64748b;
  text-transform: uppercase; letter-spacing: 0.06em;
}
.toc-list { flex: 1; overflow-y: auto; padding: 4px 12px 16px; }
.toc-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; margin: 2px 0;
  cursor: pointer; border-radius: 10px;
  transition: all 0.15s;
  border: 1px solid transparent;
  font-size: 13px; color: #334155; line-height: 1.4;
}
.toc-item:hover { background: #eff6ff; }
.toc-item.active { background: #dbeafe; border-color: #93c5fd; }
.toc-item .toc-num {
  font-size: 11px; color: #94a3b8; font-weight: 700;
  min-width: 24px; text-align: center; flex-shrink: 0;
}
.toc-item .toc-text { flex: 1; }

/* Right panel */
.content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.content-header {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 24px; background: #fff;
  border-bottom: 1px solid #e2e8f0; flex-shrink: 0;
}
.content-header .title { font-size: 14px; font-weight: 700; color: #1e293b; flex: 1; }

.content-body { flex: 1; overflow-y: auto; padding: 24px; max-width: 960px; }

/* Report content styling */
.report-content h1 { font-size: 22px; margin: 16px 0 12px; color: #0f172a; font-weight: 800; }
.report-content h2 {
  font-size: 18px; margin: 32px 0 12px; padding-bottom: 8px; color: #1e293b;
  border-bottom: 1px solid #e2e8f0; font-weight: 700; scroll-margin-top: 20px;
}
.report-content h3 { font-size: 15px; margin: 20px 0 8px; color: #334155; font-weight: 700; }
.report-content h4 { font-size: 14px; margin: 16px 0 6px; color: #475569; font-weight: 600; }
.report-content p { margin: 8px 0; line-height: 1.8; font-size: 14px; color: #334155; }
.report-content ul, .report-content ol { margin: 10px 0; padding-left: 28px; }
.report-content li { line-height: 1.8; font-size: 14px; color: #334155; }
.report-content blockquote {
  border-left: 3px solid #2563eb; padding: 10px 16px;
  margin: 14px 0; background: #eff6ff;
  font-size: 13px; border-radius: 0 8px 8px 0; color: #1e3a8a;
}
.report-content code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 13px; color: #0f172a; }
.report-content pre { background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 10px; overflow-x: auto; font-size: 13px; margin: 14px 0; }
.report-content hr { border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }
.report-content a { color: #2563eb; text-decoration: none; }
.report-content a:hover { text-decoration: underline; }

.report-content table {
  border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 13px;
  background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.report-content th, .report-content td {
  border: 1px solid #e2e8f0; padding: 8px 12px;
  text-align: left; vertical-align: top;
}
.report-content th { background: #f8fafc; font-weight: 600; color: #475569; }
.report-content tr:nth-child(even) td { background: #fafafa; }

/* Back to top button */
.back-to-top {
  position: fixed; bottom: 32px; right: 32px; z-index: 50;
  width: 44px; height: 44px; border-radius: 14px;
  background: #2563eb; color: #fff; border: none;
  cursor: pointer; font-size: 20px;
  box-shadow: 0 4px 20px rgba(37,99,235,0.30);
  transition: all 0.2s; opacity: 0; visibility: hidden;
  display: flex; align-items: center; justify-content: center;
}
.back-to-top.visible { opacity: 1; visibility: visible; }
.back-to-top:hover { background: #1d4ed8; transform: translateY(-2px); }

/* Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

/* ═══════════════════════════════════════════════════════════════════════════
   Cover Page
   ═══════════════════════════════════════════════════════════════════════════ */
.cover-overlay {
  position: fixed; inset: 0; z-index: 9999;
  display: flex; align-items: center; justify-content: center;
  background: #fff;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  transition: opacity 0.5s, visibility 0.5s;
}
.cover-overlay.dismissed { opacity: 0; visibility: hidden; pointer-events: none; }

.cover-overlay::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 320px;
  background: linear-gradient(180deg, #eff6ff 0%, rgba(239,246,255,0.3) 70%, transparent 100%);
  pointer-events: none;
}

.cover-card {
  position: relative; z-index: 1;
  text-align: center; max-width: 720px;
  padding: 48px 64px 60px;
}
.cover-logo {
  margin-bottom: 56px;
  display: inline-block;
}
.cover-logo img {
  height: 140px; width: auto;
  filter: drop-shadow(0 6px 16px rgba(37,99,235,0.08));
}
.cover-label {
  font-size: 13px; font-weight: 600; color: #2563eb;
  letter-spacing: 0.22em; text-transform: uppercase; margin-bottom: 24px;
}
.cover-h1 {
  font-size: 38px; font-weight: 800; color: #0f172a;
  line-height: 1.3; margin-bottom: 12px;
  letter-spacing: -0.015em;
}
.cover-h2 {
  font-size: 15px; color: #64748b; font-weight: 400; margin-bottom: 56px;
}

.cover-enter-btn {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 16px 56px;
  background: #2563eb; color: #fff;
  border: none; border-radius: 14px;
  font-size: 16px; font-weight: 700; cursor: pointer;
  letter-spacing: 0.02em;
  transition: all 0.2s;
  box-shadow: 0 4px 20px rgba(37,99,235,0.30);
  font-family: inherit;
}
.cover-enter-btn:hover {
  background: #1d4ed8; transform: translateY(-1px);
  box-shadow: 0 8px 32px rgba(37,99,235,0.40);
}
.cover-enter-btn:active { transform: translateY(0); }

.cover-footer {
  margin-top: 48px; font-size: 12px; color: #94a3b8;
}
.cover-footer span { color: #64748b; font-weight: 500; }

/* ── Usage Tip ── */
.usage-tip {
  background: #eff6ff; padding: 12px 16px; border-radius: 12px;
  margin-bottom: 16px; font-size: 13px; color: #1e40af;
}
.usage-tip kbd {
  background: #dbeafe; padding: 1px 6px; border-radius: 3px;
}
"""

# ── Section parsing ──────────────────────────────────────────────────────────
# The 9 expected sections in the protocol QC report
_SECTION_NAMES = [
    "总体概要",
    "预设指标覆盖",
    "统计方法一致性",
    "表题/脚注审查",
    "人群标签与组别检查",
    "数值验证",
    "问题汇总",
    "总结与建议",
]


def parse_report_sections(md_text: str) -> tuple[str, list[dict], dict[str, int], str, int]:
    """Parse the QC report markdown into overview + sections.

    Returns: (overview_html, sections_list, severity_counts)
      overview_html: content before the first section heading
      sections_list: [{id, title, content_html}]
      severity_counts: {critical, major, minor}
    """
    # Extract severity + date + table count from the META block at the top of the report.
    # The LLM is forced to write this in a fixed format, so it's deterministic to parse.
    critical_count = 0
    major_count = 0
    minor_count = 0
    report_date = ""
    table_count = 0

    meta_m = re.search(r'<!-- META\s*\n(.*?)\nEND_META\s*-->', md_text, re.DOTALL)
    if meta_m:
        meta_text = meta_m.group(1)
        for line in meta_text.strip().split("\n"):
            line = line.strip()
            if line.startswith("报告日期:"):
                report_date = line.split(":", 1)[1].strip()
            elif line.startswith("表格总数:"):
                m = re.search(r'(\d+)', line)
                if m:
                    table_count = int(m.group(1))
            elif line.startswith("严重:"):
                m = re.search(r'(\d+)', line)
                if m:
                    critical_count = int(m.group(1))
            elif line.startswith("中等:"):
                m = re.search(r'(\d+)', line)
                if m:
                    major_count = int(m.group(1))
            elif line.startswith("轻微:"):
                m = re.search(r'(\d+)', line)
                if m:
                    minor_count = int(m.group(1))

    severity_counts = {
        "critical": critical_count,
        "major": major_count,
        "minor": minor_count,
    }

    # Split by H2 headings into sections
    # Match: ## 数字、中文标题 (the section headers from the template)
    section_pattern = re.compile(
        r"^##\s+(?:[一二三四五六七八九十]+、)?\s*(.+?)$",
        re.MULTILINE,
    )

    sections: list[dict] = []
    overview_md = md_text

    # Find all H2 positions
    h2_matches = list(re.finditer(r"^##\s+(.+)$", md_text, re.MULTILINE))
    if not h2_matches:
        # No H2 headings found, treat entire doc as one section
        overview_html = markdown.markdown(
            md_text, extensions=["tables", "fenced_code", "sane_lists"]
        )
        return overview_html, [], severity_counts, report_date, table_count

    # Overview: everything before first H2
    overview_md = md_text[: h2_matches[0].start()].strip()
    overview_html = markdown.markdown(
        overview_md, extensions=["tables", "fenced_code", "sane_lists"]
    )

    # Extract each section
    for i, m in enumerate(h2_matches):
        title = m.group(1).strip()
        start = m.end()
        end = h2_matches[i + 1].start() if i + 1 < len(h2_matches) else len(md_text)
        content_md = md_text[start:end].strip()
        content_html = markdown.markdown(
            content_md, extensions=["tables", "fenced_code", "sane_lists"]
        )

        section_id = f"section-{i + 1}"

        sections.append({
            "id": section_id,
            "num": i + 1,
            "title": title,
            "content_html": content_html,
        })

    return overview_html, sections, severity_counts, report_date, table_count


# ── HTML builder ─────────────────────────────────────────────────────────────


def build_html(
    overview_html: str,
    sections: list[dict],
    severity_counts: dict[str, int],
    project_name: str,
    report_date: str = "",
    table_count: int = 0,
) -> str:
    """Generate the full self-contained HTML page."""

    # ── Logo base64 ──
    logo_b64 = ""
    if _HAS_PIL:
        try:
            logo_path = SCRIPT_DIR.parent.parent.parent.parent / "frontend" / "public" / "logo.png"
            if logo_path.exists():
                logo = Image.open(str(logo_path))
                h = 120
                w = int(logo.width * h / logo.height)
                logo_small = logo.resize((w, h), Image.LANCZOS)
                buf = io.BytesIO()
                logo_small.save(buf, format="PNG", optimize=True)
                logo_b64 = "data:image/png;base64," + b64_mod.b64encode(buf.getvalue()).decode()
        except Exception:
            pass

    # ── Stats capsules ──
    total = severity_counts["critical"] + severity_counts["major"] + severity_counts["minor"]
    stat_parts = []
    if total > 0:
        stat_parts.append(f'<span class="stat-total">总计: {total} 项</span>')
    if severity_counts["critical"]:
        stat_parts.append(f'<span class="stat-critical">🔴 严重: {severity_counts["critical"]}</span>')
    if severity_counts["major"]:
        stat_parts.append(f'<span class="stat-major">🟡 中等: {severity_counts["major"]}</span>')
    if severity_counts["minor"]:
        stat_parts.append(f'<span class="stat-minor">🟢 轻微: {severity_counts["minor"]}</span>')
    if not stat_parts:
        stat_parts.append('<span class="stat-none">暂无数据</span>')
    stats_html = "\n    ".join(stat_parts)

    # ── TOC list items ──
    toc_items = []
    for sec in sections:
        toc_items.append(
            f'<div class="toc-item" data-section="{sec["id"]}">'
            f'<span class="toc-num">{sec["num"]:02d}</span>'
            f'<span class="toc-text">{html_mod.escape(sec["title"])}</span>'
            f"</div>"
        )
    toc_html = "\n    ".join(toc_items) if toc_items else (
        '<div style="padding:20px;text-align:center;color:#94a3b8;">未检测到章节</div>'
    )

    # ── Content sections ──
    content_sections = []
    for sec in sections:
        content_sections.append(
            f'<h2 id="{sec["id"]}">{html_mod.escape(sec["title"])}</h2>\n'
            f'{sec["content_html"]}'
        )
    content_html = "\n\n".join(content_sections)

    sections_json = json.dumps(
        [{"id": s["id"], "title": s["title"], "num": s["num"]} for s in sections],
        ensure_ascii=False,
    )

    # ── Build page ──
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_mod.escape(project_name)} — 方案表格一致性质控报告</title>
<style>{CSS}</style>
</head>
<body>

<!-- ═══════════════════════════════════════════════════════════════════════════
     Cover Page
     ═══════════════════════════════════════════════════════════════════════════ -->
<div class="cover-overlay" id="coverOverlay">
  <div class="cover-card">
    <div class="cover-logo">
      {f'<img src="{logo_b64}" alt="Logo" />' if logo_b64 else '''
      <svg width="88" height="88" viewBox="0 0 88 88" fill="none">
        <rect x="14" y="8" width="60" height="72" rx="10" fill="#eff6ff" stroke="#2563eb" stroke-width="2.5"/>
        <path d="M40 26v20m0 0l-8-8m8 8l8-8" stroke="#2563eb" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="44" cy="58" r="12" fill="#2563eb" opacity="0.12" stroke="#2563eb" stroke-width="2"/>
        <path d="M39 58l3 3 7-7" stroke="#16a34a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>'''}
    </div>

    <div class="cover-label">Clinical Trial Quality Control Report</div>

    <div class="cover-h1">方案表格一致性质控</div>
    <div class="cover-h2">Protocol-Table Consistency Quality Control Report</div>
    {'<div style="margin-top:16px;font-size:13px;color:#64748b;">' + html_mod.escape(report_date) + ' &nbsp;|&nbsp; 核查表格 ' + str(table_count) + ' 张</div>' if report_date or table_count else ''}

    <button class="cover-enter-btn" onclick="dismissCover()">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 18 15 12 9 6"/>
      </svg>
      查看报告
    </button>

    <div class="cover-footer">
      由 <span>Protocol QC Platform</span> 自动生成
    </div>
  </div>
</div>

<script>
function dismissCover() {{
  document.getElementById('coverOverlay').classList.add('dismissed');
}}
</script>

<!-- Header -->
<header class="top-bar">
  {f'<img src="{logo_b64}" alt="Logo" style="height:28px;width:auto;" />' if logo_b64 else '''
  <svg viewBox="0 0 80 80" fill="none" width="28" height="28">
    <circle cx="40" cy="40" r="36" fill="#2563eb" opacity="0.12"/>
    <path d="M28 22h16l10 10v20a4 4 0 0 1-4 4H28a4 4 0 0 1-4-4V26a4 4 0 0 1 4-4z" fill="none" stroke="#2563eb" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M44 22v10h10" fill="none" stroke="#2563eb" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="48" cy="52" r="10" fill="#2563eb" opacity="0.15" stroke="#2563eb" stroke-width="2"/>
    <path d="M44 52l3 2.5 5-5" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>'''}
  <h1>方案表格一致性质控报告</h1>
  <span class="subtitle">{html_mod.escape(project_name)}{' &nbsp;|&nbsp; ' + html_mod.escape(report_date) if report_date else ''}{' &nbsp;|&nbsp; ' + str(table_count) + ' 张表' if table_count else ''}</span>
  <div class="stats">
    {stats_html}
  </div>
</header>

<!-- Main Container -->
<div class="main">

  <!-- Left Panel — TOC -->
  <aside class="sidebar">
    <div class="toc-header">报告目录</div>
    <div class="toc-list" id="tocList">
      {toc_html}
    </div>
  </aside>

  <!-- Right Panel — Content -->
  <section class="content">
    <div class="content-header">
      <div class="title" id="contentTitle">方案表格一致性质控报告</div>
    </div>
    <div class="content-body report-content" id="contentBody">
      <div class="usage-tip">
        💡 <strong>使用提示：</strong>点击左侧目录快速跳转到对应章节，右侧滚动浏览完整报告。
        按 <kbd>Esc</kbd> 切换回封面页。
      </div>
      {overview_html}
      {content_html}
    </div>
  </section>

</div>

<!-- Back to Top -->
<button class="back-to-top" id="backToTop" title="回到顶部" onclick="window.scrollTo({{top:0,behavior:'smooth'}});">↑</button>

<script>
const SECTIONS = {sections_json};

const tocList = document.getElementById('tocList');
const contentBody = document.getElementById('contentBody');
const contentTitle = document.getElementById('contentTitle');
const backToTopBtn = document.getElementById('backToTop');

// ── TOC click → scroll to section ──
tocList.addEventListener('click', function(e) {{
  const item = e.target.closest('.toc-item');
  if (!item) return;
  const sectionId = item.dataset.section;
  const target = document.getElementById(sectionId);
  if (target) {{
    target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    setActiveToc(sectionId);
  }}
}});

function setActiveToc(sectionId) {{
  document.querySelectorAll('.toc-item').forEach(function(el) {{
    el.classList.toggle('active', el.dataset.section === sectionId);
  }});
  const sec = SECTIONS.find(function(s) {{ return s.id === sectionId; }});
  if (sec) {{
    contentTitle.textContent = sec.title;
  }}
}}

// ── Scroll-spy: highlight active section in TOC ──
let spyTimeout;
contentBody.addEventListener('scroll', function() {{
  clearTimeout(spyTimeout);
  spyTimeout = setTimeout(function() {{
    const headings = contentBody.querySelectorAll('h2[id]');
    let currentId = null;
    headings.forEach(function(h) {{
      const rect = h.getBoundingClientRect();
      if (rect.top <= 120) currentId = h.id;
    }});
    if (currentId) setActiveToc(currentId);

    // Show/hide back-to-top
    if (contentBody.scrollTop > 400) {{
      backToTopBtn.classList.add('visible');
    }} else {{
      backToTopBtn.classList.remove('visible');
    }}
  }}, 50);
}});

// ── Keyboard ──
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') {{
    document.getElementById('coverOverlay').classList.remove('dismissed');
  }}
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {{
    e.preventDefault();
    const items = Array.from(document.querySelectorAll('.toc-item'));
    if (items.length === 0) return;
    const currentIdx = items.findIndex(function(el) {{ return el.classList.contains('active'); }});
    let nextIdx;
    if (e.key === 'ArrowDown') nextIdx = currentIdx < 0 ? 0 : Math.min(currentIdx + 1, items.length - 1);
    else nextIdx = currentIdx < 0 ? items.length - 1 : Math.max(currentIdx - 1, 0);
    const nextItem = items[nextIdx];
    const sectionId = nextItem.dataset.section;
    const target = document.getElementById(sectionId);
    if (target) {{
      target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      setActiveToc(sectionId);
    }}
    nextItem.scrollIntoView({{ block: 'nearest' }});
  }}
}});

// Initial scroll-spy
contentBody.dispatchEvent(new Event('scroll'));
</script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="将方案表格一致性质控 Markdown 报告转换为交互式 HTML 查看器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--md", required=True, help="QC一致性质控报告.md 路径")
    ap.add_argument("--output", default=None, help="输出 HTML 路径（默认与 .md 同目录下的 QC可视化报告.html）")
    ap.add_argument("--project-name", default=None, help="项目名称（默认取 .md 所在目录名）")
    args = ap.parse_args()

    md_path = Path(args.md).expanduser().resolve()
    if not md_path.exists():
        ap.error(f"Markdown 文件不存在: {md_path}")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else md_path.parent / "QC可视化报告.html"
    )
    project_name = args.project_name or md_path.parent.name

    print(f"📝 读取报告: {md_path}")
    md_text = md_path.read_text(encoding="utf-8")

    print("🔍 解析章节...")
    overview_html, sections, severity_counts, report_date, table_count = parse_report_sections(md_text)
    print(f"   → {len(sections)} 个章节")
    print(f"   → 严重(🔴): {severity_counts['critical']}, 中等(🟡): {severity_counts['major']}, 轻微(🟢): {severity_counts['minor']}")
    if report_date:
        print(f"   → 报告日期: {report_date}")
    if table_count:
        print(f"   → 表格总数: {table_count}")

    print(f"🔨 生成 HTML...")
    html = build_html(overview_html, sections, severity_counts, project_name, report_date, table_count)

    output_path.write_text(html, encoding="utf-8")
    size_kb = output_path.stat().st_size / 1024
    print(f"✅ 完成: {output_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
