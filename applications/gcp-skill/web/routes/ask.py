"""AI Q&A route: 3 scenarios with strict prompt constraints. Uses DeepSeek via Anthropic-compatible API."""
import json
import re
import httpx
from fastapi import APIRouter, Request, Cookie
from fastapi.responses import JSONResponse
from anthropic import Anthropic

from web.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, BANK_PATH
from web.article_parser import parse_article
from web.record_manager import load_record

router = APIRouter()

SYSTEM_PROMPT_ARTICLE = """你是 GCP 2026 培训 AI 助教。你正在帮助一位学员理解《药物临床试验质量管理规范（2026年修订）》中的一条具体条文。

**回答规则（必须严格遵守）：**
1. 仅基于下面提供的「当前条文」原文和白话解读来回答。
2. 条文有明确答案 → 引用原文，标注条文号。
3. 条文没有直接覆盖 → 说清一般原则，强调"具体以机构 SOP 为准"。不得编造不存在的条文。
4. 问题与当前条文完全无关 → 只回复："你问的问题和这一段无关。关于 GCP 其他条文的问题，可以在学到对应章节时再问。"
5. **严格控制字数：不超过 150 字。** 直击要点，禁止铺垫、客套、总结升华。
6. 语气友好，用中文。禁止提供合规法律意见。"""

SYSTEM_PROMPT_CHAPTER = """你是 GCP 2026 培训 AI 助教。学员正在学习某一章，有一个跨条文的问题。

**回答规则：**
1. 可引用下面提供的「本章已学条文」中的任何条文来回答。
2. 有明确答案 → 引用原文，标注条文号。
3. 不确定 → 说"建议对照官方文本确认"。
4. 本章未涉及此内容 → 回复："本章未涉及此内容，建议学完后续章节再问。"
5. **严格控制字数：不超过 200 字。** 直击要点，禁止铺垫、客套、总结升华。
6. 语气友好，用中文。禁止提供合规法律意见。"""

SYSTEM_PROMPT_QUIZ = """你是 GCP 2026 培训 AI 助教。学员刚做了一道测验题，看了预写解析后仍然不理解，需要你进一步讲解。

**回答规则：**
1. 结合下面提供的「题目」「正确答案」「预写解析」和「关联条文」来讲解。
2. 在预写解析的基础上深入展开：解释为什么对、为什么错、背后的法规逻辑。
3. 如果预写解析已经足够清晰，简要补充即可，不要重复。
4. 不得编造条文或给出与 2026 版 GCP 不一致的信息。
5. **严格控制字数：不超过 200 字。** 直击要点，禁止铺垫、客套、总结升华。
6. 语气耐心、友好。禁止提供合规法律意见。"""

SYSTEM_PROMPT_FULL = """你是 GCP 2026 培训 AI 助教。学员正在学习《药物临床试验质量管理规范（2026年修订）》，需要你基于全部54条法规回答一个综合性问题。

**回答规则（必须严格遵守）：**
1. 下面提供的是全部54条法规的条文原文（按章节排列）。请基于这些条文来回答。
2. 引用条文时标注条文号（如"根据第6条…"），方便学员查阅。
3. 条文中没有直接覆盖的内容 → 说清一般原则，强调"具体以机构 SOP 为准"。不得编造不存在的条文。
4. 不确定的地方 → 说"建议对照官方文本确认"。
5. **严格控制字数：不超过 300 字。** 直击要点，禁止铺垫、客套、总结升华。避免堆砌术语。
6. 语气友好，用中文。禁止提供合规法律意见。"""


def _build_full_context() -> str:
    """Build compact context of all 54 articles + diff-guide background."""
    from web.article_parser import get_article_compact
    from web.config import CHAPTERS, CHAPTER_ARTICLES, SKILL_ROOT

    lines = []

    # 1. Diff-guide: revision background & legislative logic
    diff_guide = SKILL_ROOT / "content" / "diff-guide.md"
    if diff_guide.exists():
        with open(diff_guide, encoding="utf-8") as f:
            dg = f.read()
        # Extract "修订背景与立法逻辑" section (between its heading and next ##)
        import re
        m = re.search(r'## 修订背景与立法逻辑\n(.*?)(?=\n## )', dg, re.DOTALL)
        if m:
            bg_text = m.group(1).strip()
            lines.append("## GCP 2026 修订背景与立法逻辑（来自diff-guide）")
            lines.append(bg_text)
            lines.append("")

    # 2. All 54 articles (title + original text)
    for ch in CHAPTERS:
        if ch == "导论":
            continue
        articles = CHAPTER_ARTICLES.get(ch, [])
        if not articles:
            continue
        lines.append(f"\n## {ch}")
        for num in articles:
            art = get_article_compact(num)
            if art:
                lines.append(f"第{num}条·{art.get('title','')}：{art.get('original_text','')}")
    return "\n".join(lines)


@router.post("/article")
async def ask_article(request: Request,
                      username: str = Cookie(None),
                      learner_role: str = Cookie("student")):
    """Scenario A: Article-level question. AI only uses current article."""
    if not username or not learner_role:
        return JSONResponse({"reply": "请先登录后再提问。"})
    body = await request.json()
    article_num = body.get("article_num")
    question = body.get("question", "")

    article = parse_article(article_num, learner_role)
    if not article:
        return JSONResponse({"reply": "无法找到该条文。"})

    context = f"""**学员角色：**{learner_role}

**当前条文：**
【第{article_num}条 · {article.get('title', '')}】
原文：{article.get('original_text', '')}
白话解读：{article.get('plain_explanation', '')}"""

    return _call_ai(SYSTEM_PROMPT_ARTICLE, context, question, max_tokens=400)


@router.post("/chapter")
async def ask_chapter(request: Request,
                      username: str = Cookie(None),
                      learner_role: str = Cookie("student")):
    """Scenario B: Chapter-level question. AI uses all learned articles in chapter,
    or specific articles if provided (for diff modules)."""
    if not username or not learner_role:
        return JSONResponse({"reply": "请先登录后再提问。"})
    body = await request.json()
    chapter = body.get("chapter", "")
    question = body.get("question", "")
    article_ids = body.get("articles")  # optional: list of article numbers for diff modules

    if article_ids:
        # Use specific articles (from diff module)
        article_nums = [int(a) for a in article_ids]
    else:
        # Use all articles in the chapter
        from web.article_parser import get_articles_in_chapter
        article_nums = get_articles_in_chapter(chapter)

    articles_text = ""
    for num in article_nums:
        art = parse_article(num)
        if art:
            articles_text += f"\n【第{num}条 · {art.get('title', '')}】\n原文：{art.get('original_text', '')}\n"

    context = f"""**学员角色：**{learner_role}

**相关条文：**
{articles_text if articles_text else '（无特定条文，请根据GCP常识简要回答）'}"""

    return _call_ai(SYSTEM_PROMPT_CHAPTER, context, question, max_tokens=500)


@router.post("/quiz")
async def ask_quiz(request: Request,
                   username: str = Cookie(None),
                   learner_role: str = Cookie("student")):
    """Scenario C: Quiz follow-up. AI builds on pre-written explanation."""
    if not username or not learner_role:
        return JSONResponse({"reply": "请先登录后再提问。"})
    body = await request.json()
    question_id = body.get("question_id", "")
    question = body.get("question", "我还是不太理解，能再讲讲吗？")

    with open(BANK_PATH, encoding="utf-8") as f:
        bank = json.load(f)

    q = next((q for q in bank["questions"] if q["id"] == question_id), None)
    if not q:
        return JSONResponse({"reply": "无法找到该题目。"})

    article_num = int(q.get("article", 1))
    article = parse_article(article_num, learner_role)

    context = f"""**学员角色：**{learner_role}

**题目信息：**
题目：{q.get('question', '')}
选项：{q.get('options', [])}
正确答案：{q.get('answer', '')}
预写解析：{q.get('explanation', '')}

**关联条文：**
【第{article_num}条 · {article.get('title', '') if article else ''}】
原文：{article.get('original_text', '') if article else ''}
白话解读：{article.get('plain_explanation', '') if article else ''}"""

    return _call_ai(SYSTEM_PROMPT_QUIZ, context, question, max_tokens=500)


@router.post("/full")
async def ask_full(request: Request,
                    username: str = Cookie(None),
                    learner_role: str = Cookie("student")):
    """Scenario D: Full-regulation question. AI uses all 54 articles."""
    if not username or not learner_role:
        return JSONResponse({"reply": "请先登录后再提问。"})
    body = await request.json()
    question = body.get("question", "")

    context = f"**学员角色：**{learner_role}\n\n**GCP 2026 全部条文（共54条）：**\n{_build_full_context()}"
    return _call_ai(SYSTEM_PROMPT_FULL, context, question, max_tokens=800)


def _md_to_html(text: str) -> str:
    """Convert basic Markdown to HTML for AI reply display.
    Handles: **bold**, - list, 1. numbered list, \\n line breaks.

    Safety: HTML-escapes input first so any raw HTML/script tags from the AI
    are rendered as text, never executed. Only <strong>, <br>, &nbsp; are
    intentionally emitted by this function.
    """
    import html as _html

    # 0. Escape any HTML that the AI model may have returned (XSS prevention).
    #    This turns <script> into &lt;script&gt; etc. Our markdown patterns
    #    (**bold**, - list, 1. list) don't use HTML special chars, so they
    #    survive escaping unchanged.
    text = _html.escape(text)

    # 1. Convert **bold** -> <strong>bold</strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    # 2. Convert numbered lists (1. text) — wrap in <ol> if consecutive
    #    Simpler: just style the line, don't wrap
    # 3. Convert - list markers to bullet • and indent
    lines = text.split('\n')
    out = []
    for line in lines:
        stripped = line.strip()
        # Numbered list: "1. text" or "1) text" — keep the number
        if re.match(r'^\d+[.)]\s', stripped):
            out.append('&nbsp;&nbsp;' + stripped)
        # Bullet list: "- text" or "* text"
        elif re.match(r'^[-*]\s', stripped):
            out.append('&nbsp;&nbsp;• ' + re.sub(r'^[-*]\s*', '', stripped))
        else:
            out.append(stripped)
    text = '<br>'.join(out)
    return text


def _call_ai(system_prompt: str, context: str, user_question: str,
             max_tokens: int = 600) -> JSONResponse:
    """Call DeepSeek via Anthropic-compatible API endpoint."""
    if not ANTHROPIC_API_KEY:
        return JSONResponse({"reply": "AI 服务未配置。请联系管理员设置 API Key。"})

    try:
        http_client = httpx.Client(proxy=None)
        client = Anthropic(
            api_key=ANTHROPIC_API_KEY,
            base_url=ANTHROPIC_BASE_URL,
            http_client=http_client,
        )
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"{context}\n\nUSER QUESTION:\n{user_question}"}
            ],
        )

        # Extract text blocks only (deepseek-chat returns clean text)
        reply = ""
        content = message.content
        if isinstance(content, str):
            reply = content.strip()
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if getattr(block, "type", None) == "text":
                    t = (getattr(block, "text", None) or "").strip()
                    if t:
                        text_parts.append(t)
            reply = "\n\n".join(text_parts)

        if not reply:
            print(f"[AI empty reply] content={str(content)[:300]}", flush=True)
            reply = "AI 返回了空回复，请稍后重试。"

        reply = _md_to_html(reply)
        return JSONResponse({"reply": reply})
    except Exception as e:
        print(f"[AI error] {e}", flush=True)
        return JSONResponse({"reply": f"AI 暂时无法响应（{str(e)[:100]}）。请稍后重试或查看条文原文。"})
