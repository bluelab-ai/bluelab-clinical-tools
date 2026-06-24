"""Parse article-XX.md files into structured dicts with role filtering."""
from __future__ import annotations

import re
from pathlib import Path
from web.config import ARTICLES_DIR, ROLE_EMOJI_MAP


# Module-level cache — article titles don't change at runtime
_article_title_cache: dict[int, str] = {}


def get_article_title(article_num: int | str) -> str:
    """Read just the title from an article's frontmatter. Results are cached."""
    num = int(article_num)
    if num in _article_title_cache:
        return _article_title_cache[num]

    filename = f"article-{num:02d}.md"
    filepath = ARTICLES_DIR / filename
    if not filepath.exists():
        title = f"第{num}条"
    else:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        fm = _parse_frontmatter(content)
        title = fm.get("title", f"第{num}条")

    _article_title_cache[num] = title
    return title


def get_article_compact(article_num: int | str) -> dict | None:
    """Fast‑path: read only title + original_text, skipping section parsing and
    HTML conversion.  Used by _build_full_context() for the 54‑article context."""
    num = int(article_num)
    filename = f"article-{num:02d}.md"
    filepath = ARTICLES_DIR / filename
    if not filepath.exists():
        return None

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    fm = _parse_frontmatter(content)
    title = fm.get("title", f"第{num}条")

    # Extract just the 条文原文 section (skip all other sections + HTML conversion)
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)
    m = re.search(r"###\s*📜\s*条文原文\s*\n(.*?)(?=\n###\s)", body, re.DOTALL)
    original_text = m.group(1).strip() if m else ""

    return {"title": title, "original_text": original_text}


def parse_article(article_num: int | str, learner_role: str = None) -> dict:
    """Parse a single article markdown file into a structured dict.

    Args:
        article_num: Article number (1-54), e.g. 6 or "06"
        learner_role: If provided, filter the roles section to only this role

    Returns:
        dict with keys: id, chapter, title, change_level, tags, roles,
                        scenario, original_text, plain_explanation,
                        change_note, role_tip, pitfalls, related_articles
    """
    filename = f"article-{int(article_num):02d}.md"
    filepath = ARTICLES_DIR / filename

    if not filepath.exists():
        return None

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    result = _parse_frontmatter(content)
    result.update(_parse_sections(content, learner_role))
    return result


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter fields."""
    result = {}
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        for line in fm_text.strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key == "change_level":
                    result["change_level"] = value
                elif key == "title":
                    result["title"] = value
                elif key == "chapter":
                    result["chapter"] = value
                elif key == "id":
                    result["id"] = value
                elif key == "tags":
                    result["tags"] = [t.strip().strip('"').strip("'") for t in value.strip("[]").split(",")]
                elif key == "roles":
                    result["roles"] = [r.strip().strip('"').strip("'") for r in value.strip("[]").split(",")]
    return result


def _parse_sections(content: str, learner_role: str = None) -> dict:
    """Parse the 6 content sections from article body."""
    result = {}

    # Remove frontmatter
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)

    sections = {
        "scenario": (r"###\s*💡\s*先想一个场景\s*\n(.*?)(?=\n###\s)", "scenario"),
        "original_text": (r"###\s*📜\s*条文原文\s*\n(.*?)(?=\n###\s)", "original_text"),
        "plain_explanation": (r"###\s*🔑\s*这条在说什么\s*\n(.*?)(?=\n###\s)", "plain_explanation"),
        "change_note": (r"###\s*🔄\s*和旧版.*?\s*\n(.*?)(?=\n###\s)", "change_note"),
        "roles_block": (r"###\s*👤\s*对你的影响\s*\n(.*?)(?=\n###\s)", "roles_block"),
        "pitfalls": (r"###\s*⚠️\s*容易踩的坑\s*\n(.*?)(?=\n###\s|$)", "pitfalls"),
    }

    for key, (pattern, _) in sections.items():
        m = re.search(pattern, body, re.DOTALL)
        if m:
            text = m.group(1).strip()
            if key == "roles_block" and learner_role:
                text = _filter_role_line(text, learner_role)
            result[key] = text
        else:
            result[key] = ""

    # Related articles
    related_m = re.search(r"###\s*🔗\s*关联条文\s*\n(.*?)$", body, re.DOTALL)
    result["related_articles"] = related_m.group(1).strip() if related_m else ""

    # Short scenario for 🟡 diff modules (truncate raw before MD conversion)
    raw_scenario = result.get("scenario", "")
    result["scenario_short"] = raw_scenario[:120] + ("…" if len(raw_scenario) > 120 else "")

    # Convert all text fields from Markdown to HTML
    for key in result:
        if result[key]:
            result[key] = _md_to_html(result[key])

    return result


def _filter_role_line(roles_text: str, learner_role: str) -> str:
    """Extract only the role line matching learner_role by emoji."""
    emoji_map_reverse = {
        "PI": "🏥",
        "CRA": "📋",
        "CRC": "📝",
        "student": "🎓",
    }
    target_emoji = emoji_map_reverse.get(learner_role, "")
    if not target_emoji:
        return roles_text

    for line in roles_text.split("\n"):
        if target_emoji in line:
            return line.strip()
    return roles_text


def _md_to_html(text: str) -> str:
    """Convert inline Markdown to HTML. Templates provide outer wrapper tags.
    Only handles: **bold**, > prefix, - list marker, \\n line breaks."""
    # 1. Convert **bold** -> <strong>bold</strong> (before stripping *)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    # 2. Strip leading > and optional space from each line
    #    (templates already wrap content in <blockquote>)
    lines = [re.sub(r'^>\s?', '', line) for line in text.split('\n')]

    # 3. Strip - list markers at line start
    lines = [re.sub(r'^-\s+', '', line) for line in lines]

    # 4. Split role label from description: "Role: desc" → "Role<br>desc"
    #    (role lines look like: 🏥 <strong>PI</strong>: description text)
    text = '<br>'.join(lines)
    # Strip role emojis (🏥📋📝🎓) and the colon after role name
    text = re.sub(r'[🏥📋📝🎓]\s*', '', text)
    text = re.sub(r'(<strong>[^<]+</strong>)[:：]\s*', r'\1 ', text)

    return text


def strip_display_emojis(text: str) -> str:
    """Remove decorative section emojis from display text, keeping 💡 and ⚠️."""
    emoji_to_strip = ["📜", "🔑", "🔄", "👤"]
    for emoji in emoji_to_strip:
        text = text.replace(emoji, "")
    return text


def get_articles_in_chapter(chapter: str) -> list[int]:
    """Return list of article numbers in a given chapter."""
    from web.config import CHAPTER_ARTICLES
    return CHAPTER_ARTICLES.get(chapter, [])
