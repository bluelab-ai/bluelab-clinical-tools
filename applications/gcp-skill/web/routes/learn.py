"""Learn route: article rendering for novice and experienced tracks."""
import re

from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from web.article_parser import parse_article, get_articles_in_chapter, get_article_title
from web.record_manager import load_record, save_record, update_chapter_status
from web.config import CHAPTERS, CHAPTER_ARTICLES, CHAPTER_TITLES, SKILL_ROOT
from web.user_manager import load_account

router = APIRouter()


# ============================================================
# Intro content: extracted from diff-guide.md for novice overview
# ============================================================

def _intro_md_to_html(text: str) -> str:
    """Convert the diff-guide intro sections to simple HTML.
    Handles **bold**, - bullet lists, paragraphs, and markdown tables."""
    lines = text.split('\n')
    out = []
    in_table = False
    table_rows = []

    for line in lines:
        stripped = line.strip()

        # Bold conversion
        stripped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)

        # Table detection: lines starting and ending with |
        if stripped.startswith('|') and stripped.endswith('|'):
            cells = [c.strip() for c in stripped.strip('|').split('|')][:2]  # keep only first 2 columns
            if all(c.startswith('---') or c.startswith(':--') for c in cells if c):
                continue  # skip separator row
            table_rows.append(cells)
            in_table = True
            continue
        elif in_table:
            # End of table — flush it.  First row is <th>, rest are <td>.
            rows_html = ''
            for ri, row in enumerate(table_rows):
                tag = 'th' if ri == 0 else 'td'
                rows_html += '<tr>' + ''.join(
                    f'<{tag}>{c}</{tag}>' for c in row
                ) + '</tr>'
            out.append(f'<table class="intro-table">{rows_html}</table>')
            table_rows = []
            in_table = False

        # Bullet list
        if re.match(r'^-\s', stripped):
            out.append('<li>' + re.sub(r'^-\s*', '', stripped) + '</li>')
        # Numbered heading (一、二、三、四)
        elif re.match(r'^[一二三四五六七八九十]、', stripped):
            out.append('<h3>' + stripped + '</h3>')
        # Empty line
        elif stripped == '':
            out.append('<br>')
        # Regular paragraph
        else:
            out.append('<p>' + stripped + '</p>')

    # Flush any remaining table
    if in_table and table_rows:
        rows_html = ''
        for ri, row in enumerate(table_rows):
            tag = 'th' if ri == 0 else 'td'
            rows_html += '<tr>' + ''.join(
                f'<{tag}>{c}</{tag}>' for c in row
            ) + '</tr>'
        out.append(f'<table class="intro-table">{rows_html}</table>')

    # Wrap consecutive <li> in <ul>
    result = []
    i = 0
    while i < len(out):
        if out[i].startswith('<li>'):
            ul = ['<ul>']
            while i < len(out) and out[i].startswith('<li>'):
                ul.append(out[i])
                i += 1
            ul.append('</ul>')
            result.append('\n'.join(ul))
        else:
            result.append(out[i])
            i += 1

    return '\n'.join(result)


def _get_intro_sections() -> list[dict]:
    """Extract the four key overview sections from diff-guide.md."""
    guide_path = SKILL_ROOT / "content" / "diff-guide.md"
    if not guide_path.exists():
        return []

    with open(guide_path, encoding="utf-8") as f:
        content = f.read()

    # Extract "修订背景与立法逻辑" section
    m = re.search(r'## 修订背景与立法逻辑\n(.*?)(?=\n## )', content, re.DOTALL)
    if not m:
        return []

    section_text = m.group(1).strip()

    # Split by ### headings.  Because the section starts with ###, the first
    # element of the split contains the first heading+body glued together.
    # Subsequent elements alternate [heading, body, heading, body, ...].
    parts = re.split(r'\n### (.+?)\n', section_text)

    sections = []

    # Handle first section (heading+body in parts[0])
    if parts:
        first = parts[0].strip()
        if first.startswith("### "):
            first = first[4:]  # strip "### " prefix
        # Split at first blank line to separate title from body
        first_parts = first.split("\n\n", 1)
        first_title = first_parts[0].strip()
        first_body = first_parts[1].strip() if len(first_parts) > 1 else ""
        sections.append({"title": first_title, "body_html": _intro_md_to_html(first_body)})

    # Handle remaining sections (alternating heading/body pairs)
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        body_html = _intro_md_to_html(body)
        sections.append({"title": title, "body_html": body_html})

    return sections


# ============================================================
# Diff module definitions (used by diff routes below)
# ============================================================

def _get_diff_modules() -> list[dict]:
    """Return the hardcoded diff module sequence from diff-guide.md."""
    return [
        {"id": "opening", "title": "2026版 GCP 修订总览", "format": "💬",
         "description": "修订背景与立法逻辑：为什么从9章83条精简为6章54条，六章结构的功能逻辑，新增内容反映了哪些监管关切，术语变更的深层含义，与ICH E6(R3)的关系。",
         "articles": [], "duration": "~4 min"},
        {"id": "step1", "title": "术语变更概览", "format": "💬",
         "description": "关键术语更新：试验参与者、主要研究者(PI)、服务供应商、伦理审查委员会。术语变更不仅是措辞调整，更反映了对临床试验参与关系和法律定位的重新理解。",
         "articles": [], "duration": "~2 min"},
        {"id": "step2", "title": "核心理念升级", "format": "🔴",
         "description": "质量源于设计(QbD) + 风险相称的质量管理体系", "articles": [6, 40, 42], "duration": "~6 min"},
        {"id": "step3", "title": "责任体系重构", "format": "🔴",
         "description": "PI不可授权事项 + 申办者质量管理体系", "articles": [19, 20, 32, 33], "duration": "~7 min"},
        {"id": "step4", "title": "数据治理专章", "format": "🔴",
         "description": "电子源数据、元数据与稽查轨迹、计算机化系统验证、盲态数据管理", "articles": [51, 52, 53], "duration": "~9 min"},
        {"id": "step5", "title": "知情同意 + 伦理审查变化", "format": "🟡",
         "description": "知情同意新要求 + 伦理审查委员会监督职能强化", "articles": [27, 14], "duration": "~5 min"},
        {"id": "step6", "title": "新增专条", "format": "🔴",
         "description": "利益冲突回避 + 新技术新方法", "articles": [12, 13], "duration": "~5 min"},
        {"id": "closing", "title": "修订要点回顾与路径选择", "format": "💬",
         "description": "总结2026版关键变化 + A/B/C分支选择说明", "articles": [], "duration": "~3 min"},
    ]


# ============================================================
# Specific routes FIRST (before parameterized /{chapter}/{article})
# ============================================================

@router.get("/start", response_class=HTMLResponse)
async def learn_start(request: Request,
                      username: str = Cookie(None),
                      learner_role: str = Cookie(None)):
    """Redirect to the current chapter/article based on record."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    if not record:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    # Novice track: show intro/overview first if not yet viewed
    track = record.get("learner_track", "novice")
    if track == "novice" and not record.get("intro_viewed"):
        return RedirectResponse(url="/learn/intro", status_code=303)

    # If all 6 chapters passed, go straight to exam (don't loop back to articles)
    chapters = record.get("chapters", {})
    real_chapters = {ch: c for ch, c in chapters.items() if ch != "导论"}
    if len(real_chapters) == 6 and all(c.get("status") == "passed" for c in real_chapters.values()):
        return RedirectResponse(url="/exam/start", status_code=303)

    current_ch = record.get("current_chapter", "导论")
    last_article = record.get("last_article")

    articles = get_articles_in_chapter(current_ch)
    if not articles:
        # Introduction chapter or empty chapter - advance to first real chapter
        record["current_chapter"] = "第一章"
        save_record(username, learner_role, record)
        return RedirectResponse(url="/learn/第一章/1", status_code=303)

    next_article = articles[0]
    if last_article and int(last_article) in articles:
        idx = articles.index(int(last_article))
        if idx + 1 < len(articles):
            next_article = articles[idx + 1]

    return RedirectResponse(
        url=f"/learn/{current_ch}/{next_article}", status_code=303
    )


# ---- Intro route (novice overview) ----

@router.get("/intro", response_class=HTMLResponse)
async def learn_intro(request: Request,
                      username: str = Cookie(None),
                      learner_role: str = Cookie(None)):
    """Show the novice intro/overview page before starting articles."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    if not record:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    intro_sections = _get_intro_sections()

    return request.app.state.templates.TemplateResponse("learn.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "is_intro": True,
        "intro_sections": intro_sections,
    })


@router.post("/intro/start", response_class=HTMLResponse)
async def learn_intro_start(request: Request,
                            username: str = Cookie(None),
                            learner_role: str = Cookie(None)):
    """Mark intro as viewed and begin learning from 第一章."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    record["intro_viewed"] = True
    record["current_chapter"] = "第一章"
    save_record(username, learner_role, record)

    return RedirectResponse(url="/learn/第一章/1", status_code=303)


# ---- Diff routes ----

@router.get("/diff", response_class=HTMLResponse)
async def learn_diff_start(request: Request,
                           username: str = Cookie(None),
                           learner_role: str = Cookie(None)):
    """Start experienced track diff overview."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    if not record:
        return RedirectResponse(url="/", status_code=303)

    modules = _get_diff_modules()
    completed = record.get("diff_modules_completed", [])
    next_module_idx = len(completed)

    if next_module_idx >= len(modules):
        return RedirectResponse(url="/learn/branch", status_code=303)

    return RedirectResponse(
        url=f"/learn/diff/{next_module_idx}", status_code=303
    )


@router.get("/diff/{module_idx}", response_class=HTMLResponse)
async def learn_diff_module(request: Request,
                            module_idx: int,
                            username: str = Cookie(None),
                            learner_role: str = Cookie(None)):
    """Render a single diff module."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    modules = _get_diff_modules()
    if module_idx < 0 or module_idx >= len(modules):
        return RedirectResponse(url="/learn/branch", status_code=303)

    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    module = modules[module_idx].copy()
    module["index"] = module_idx
    module["total"] = len(modules)
    module["is_last"] = module_idx == len(modules) - 1

    articles_data = []
    for aid in module.get("articles", []):
        art = parse_article(aid, learner_role)
        if art:
            articles_data.append(art)

    # Build diff sidebar data — like novice chapters_data but for 8 diff modules
    diff_modules_data = []
    for i, mod in enumerate(modules):
        is_current = (i == module_idx)
        entry = {
            "title": mod["title"],
            "format": mod["format"],
            "is_current": is_current,
            "idx": i,
        }
        if is_current and mod.get("articles"):
            article_items = []
            for art_num in mod["articles"]:
                title = get_article_title(art_num)
                article_items.append({"num": art_num, "title": title})
            entry["article_items"] = article_items
        diff_modules_data.append(entry)

    return request.app.state.templates.TemplateResponse("learn.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "is_diff": True,
        "module": module,
        "articles_data": articles_data,
        "diff_modules_data": diff_modules_data,
    })


@router.post("/diff/complete", response_class=HTMLResponse)
async def learn_diff_complete(request: Request,
                              module_idx: int = Form(...),
                              username: str = Cookie(None),
                              learner_role: str = Cookie(None)):
    """Mark a diff module as complete and advance."""
    record = load_record(username, learner_role)
    completed = record.get("diff_modules_completed", [])
    if module_idx not in completed:
        completed.append(module_idx)
    record["diff_modules_completed"] = completed
    save_record(username, learner_role, record)

    modules = _get_diff_modules()
    if module_idx + 1 >= len(modules):
        return RedirectResponse(url="/learn/branch", status_code=303)
    return RedirectResponse(url=f"/learn/diff/{module_idx + 1}", status_code=303)


# ---- Branch routes ----

@router.get("/branch", response_class=HTMLResponse)
async def branch_select_page(request: Request,
                             username: str = Cookie(None),
                             learner_role: str = Cookie(None)):
    """Branch selection page for experienced track — or resume if already chosen."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    account = load_account(username)
    real_name = account.get("real_name", username) if account else username
    branch = record.get("experienced_branch")

    # Auto-resume based on existing branch
    if branch == "B":
        # Find next chapter without a passed quiz
        from web.config import CHAPTERS
        for ch in CHAPTERS:
            if ch == "导论":
                continue
            ch_status = (record.get("chapters") or {}).get(ch, {}).get("status")
            if ch_status != "passed":
                return RedirectResponse(url=f"/quiz/{ch}/start?change_only=1", status_code=303)
        # All passed — offer B→C upgrade
        return request.app.state.templates.TemplateResponse("branch_select.html", {
            "request": request, "learner_name": real_name,
            "learner_role": learner_role, "current_branch": "B",
            "offer_upgrade": True,
        })
    elif branch == "C":
        # Check for in-progress exam
        if record.get("final_exam_in_progress"):
            return RedirectResponse(url="/exam/start", status_code=303)
        return request.app.state.templates.TemplateResponse("branch_select.html", {
            "request": request, "learner_name": real_name,
            "learner_role": learner_role, "current_branch": "C",
            "offer_exam": True,
        })

    return request.app.state.templates.TemplateResponse("branch_select.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "current_branch": branch,
    })


@router.post("/branch/select", response_class=HTMLResponse)
async def branch_select(request: Request,
                        branch: str = Form(...),
                        username: str = Cookie(None),
                        learner_role: str = Cookie(None)):
    """Handle branch selection."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)
    record = load_record(username, learner_role)
    record["experienced_branch"] = branch
    save_record(username, learner_role, record)

    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    if branch == "A":
        return request.app.state.templates.TemplateResponse("branch_select.html", {
            "request": request, "learner_name": real_name,
            "learner_role": learner_role, "branch": "A", "done": True,
        })
    elif branch == "B":
        return RedirectResponse(url="/quiz/第一章/start?change_only=1", status_code=303)
    elif branch == "C":
        return RedirectResponse(url="/exam/start", status_code=303)
    return RedirectResponse(url="/learn/branch", status_code=303)


@router.post("/branch/upgrade", response_class=HTMLResponse)
async def branch_upgrade(request: Request,
                         from_branch: str = Form(...),
                         to_branch: str = Form(...),
                         username: str = Cookie(None),
                         learner_role: str = Cookie(None)):
    """Handle branch upgrade (A→B, B→C, C fail→B)."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)
    record = load_record(username, learner_role)
    record["experienced_branch"] = to_branch
    save_record(username, learner_role, record)

    if to_branch == "B":
        return RedirectResponse(url="/quiz/第一章/start?change_only=1", status_code=303)
    elif to_branch == "C":
        return RedirectResponse(url="/exam/start", status_code=303)
    return RedirectResponse(url="/learn/branch", status_code=303)


# ============================================================
# Parameterized article route — MUST be LAST to not catch /diff/0 etc.
# ============================================================

@router.get("/{chapter}/{article_num}", response_class=HTMLResponse)
async def learn_article(request: Request,
                        chapter: str,
                        article_num: int,
                        username: str = Cookie(None),
                        learner_role: str = Cookie(None)):
    """Render a single article page."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    # B/C branch users should never be in the novice article flow
    branch = record.get("experienced_branch") if record else None
    if branch in ("B", "C"):
        return RedirectResponse(url="/learn/branch", status_code=303)

    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    article = parse_article(article_num, learner_role)
    if not article:
        return HTMLResponse(f"Article {article_num} not found", status_code=404)

    record = load_record(username, learner_role)

    articles_in_ch = get_articles_in_chapter(chapter)
    # If article doesn't belong to this chapter, redirect to chapter's first article
    if article_num not in articles_in_ch:
        if articles_in_ch:
            return RedirectResponse(url=f"/learn/{chapter}/{articles_in_ch[0]}", status_code=303)
        else:
            return RedirectResponse(url="/learn/第一章/1", status_code=303)
    current_idx = articles_in_ch.index(article_num)
    has_prev = current_idx > 0
    has_next = current_idx < len(articles_in_ch) - 1
    prev_article = articles_in_ch[current_idx - 1] if has_prev else None
    next_article = articles_in_ch[current_idx + 1] if has_next else None

    record["last_article"] = str(article_num)
    record["current_chapter"] = chapter
    update_chapter_status(record, chapter, "active")
    save_record(username, learner_role, record)

    total_articles = 54
    current_overall = article_num

    # ---- Build sidebar data ----
    chapters_data = []
    for ch_name in CHAPTERS:
        if ch_name == "导论":
            continue
        articles_in_ch = CHAPTER_ARTICLES.get(ch_name, [])
        ch_record = record.get("chapters", {}).get(ch_name, {})
        ch_status = ch_record.get("status", "idle")
        is_current = (ch_name == chapter)

        # Only show article list for the current chapter
        article_items = []
        if is_current:
            for art_num in articles_in_ch:
                if art_num < article_num:
                    state = "past"
                elif art_num == article_num:
                    state = "current"
                else:
                    state = "future"
                title = get_article_title(art_num)
                article_items.append({"num": art_num, "state": state, "title": title})

        # Quiz state: passed, available (current chapter + all articles read), or locked
        if ch_status == "passed":
            quiz_state = "passed"
        elif is_current and articles_in_ch and article_num >= articles_in_ch[-1]:
            quiz_state = "available"
        else:
            quiz_state = "future"

        chapters_data.append({
            "name": ch_name,
            "title": CHAPTER_TITLES.get(ch_name, ch_name),
            "article_items": article_items,
            "quiz_state": quiz_state,
            "quiz_score": ch_record.get("quiz_score"),
            "is_current": is_current,
            "is_expanded": is_current,
        })

    return request.app.state.templates.TemplateResponse("learn.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "chapter": chapter,
        "chapter_title": article.get("chapter", chapter),
        "article": article,
        "article_num": article_num,
        "has_prev": has_prev,
        "has_next": has_next,
        "prev_article": prev_article,
        "next_article": next_article,
        "current_idx": current_idx,
        "total_in_chapter": len(articles_in_ch),
        "total_articles": total_articles,
        "current_overall": current_overall,
        "change_level": article.get("change_level", ""),
        "chapters_data": chapters_data,
    })
