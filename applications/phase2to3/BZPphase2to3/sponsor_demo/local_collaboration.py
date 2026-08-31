from __future__ import annotations

from contextlib import closing
from email.utils import parseaddr
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
import warnings
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps, UnidentifiedImageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_DATA_ROOT = PROJECT_ROOT / "data"
MAX_ATTACHMENTS = 3
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LocalContentError(ValueError):
    """Raised when local changelog or feedback content cannot be accepted."""


def local_data_root() -> Path:
    configured = os.environ.get("SPONSOR_DEMO_LOCAL_DATA_ROOT", "").strip()
    if not configured:
        return DEFAULT_LOCAL_DATA_ROOT
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def changelog_path() -> Path:
    return local_data_root() / "changelog" / "entries.json"


def changelog_media_root() -> Path:
    return local_data_root() / "changelog" / "media"


def feedback_root() -> Path:
    return local_data_root() / "feedback"


def feedback_db_path() -> Path:
    return feedback_root() / "feedback.db"


def feedback_upload_root() -> Path:
    return feedback_root() / "uploads"


def _mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def ensure_local_storage() -> None:
    changelog_file = changelog_path()
    _mkdir_private(changelog_file.parent)
    _mkdir_private(changelog_media_root())
    if not changelog_file.exists():
        payload = {"schema_version": 1, "entries": []}
        try:
            with changelog_file.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except FileExistsError:
            pass

    _mkdir_private(feedback_root())
    _mkdir_private(feedback_upload_root())
    with closing(_connect_feedback_db()) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                feedback_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                category TEXT NOT NULL,
                impact TEXT NOT NULL,
                source_page TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reproduction_steps TEXT NOT NULL DEFAULT '',
                expected_behavior TEXT NOT NULL DEFAULT '',
                contact TEXT NOT NULL DEFAULT '',
                app_version TEXT NOT NULL,
                scenario_json TEXT NOT NULL DEFAULT '{}',
                attachments_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT '待处理'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS email_outbox (
                message_id TEXT PRIMARY KEY,
                feedback_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                body_text TEXT NOT NULL,
                reply_to TEXT NOT NULL DEFAULT '',
                attachments_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(feedback_id) REFERENCES feedback(feedback_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_email_outbox_delivery "
            "ON email_outbox(status, next_attempt_at)"
        )


def _connect_feedback_db() -> sqlite3.Connection:
    path = feedback_db_path()
    _mkdir_private(path.parent)
    connection = sqlite3.connect(path, timeout=30)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def load_changelog_entries() -> list[dict[str, Any]]:
    ensure_local_storage()
    path = changelog_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalContentError(f"更新日志文件无法读取：{exc}") from exc

    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise LocalContentError("更新日志文件格式不正确：entries必须为列表。")

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            raise LocalContentError(f"第{index + 1}条更新不是对象。")
        title = str(raw.get("title") or "").strip()
        published_at = str(raw.get("published_at") or "").strip()
        if not title or not published_at:
            raise LocalContentError(f"第{index + 1}条更新缺少title或published_at。")
        highlights = raw.get("highlights") or []
        if not isinstance(highlights, list):
            raise LocalContentError(f"第{index + 1}条更新的highlights必须为列表。")
        images = raw.get("images") or []
        if not isinstance(images, list):
            raise LocalContentError(f"第{index + 1}条更新的images必须为列表。")
        normalized_images: list[dict[str, str]] = []
        for image_index, image in enumerate(images):
            if not isinstance(image, dict):
                raise LocalContentError(
                    f"第{index + 1}条更新的第{image_index + 1}张图片格式不正确。"
                )
            relative_path = str(image.get("path") or "").strip()
            if not relative_path:
                continue
            candidate = (changelog_media_root() / relative_path).resolve()
            media_root = changelog_media_root().resolve()
            if candidate.parent != media_root or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                raise LocalContentError(
                    f"第{index + 1}条更新的第{image_index + 1}张图片路径不安全。"
                )
            normalized_images.append(
                {
                    "path": relative_path,
                    "caption": str(image.get("caption") or "").strip(),
                    "wide": bool(image.get("wide", False)),
                }
            )
        normalized.append(
            {
                "id": str(raw.get("id") or f"entry-{index + 1}"),
                "published_at": published_at,
                "version": str(raw.get("version") or "").strip(),
                "category": str(raw.get("category") or "功能更新").strip(),
                "title": title,
                "body": str(raw.get("body") or "").strip(),
                "highlights": [str(item).strip() for item in highlights if str(item).strip()],
                "images": normalized_images,
                "pinned": bool(raw.get("pinned", False)),
            }
        )
    return sorted(
        normalized,
        key=lambda item: (bool(item["pinned"]), str(item["published_at"])),
        reverse=True,
    )


def _clean_text(value: str, *, field_name: str, max_length: int, required: bool = False) -> str:
    cleaned = str(value or "").replace("\x00", "").strip()
    if required and not cleaned:
        raise LocalContentError(f"请填写{field_name}。")
    if len(cleaned) > max_length:
        raise LocalContentError(f"{field_name}不能超过{max_length}个字符。")
    return cleaned


def _valid_email(value: str) -> bool:
    _, address = parseaddr(value)
    return bool(address == value and len(address) <= 254 and EMAIL_PATTERN.fullmatch(address))


def email_delivery_configured() -> bool:
    if os.environ.get("SPONSOR_EMAIL_ENABLED", "").strip() != "1":
        return False
    sender = os.environ.get("SPONSOR_GMAIL_ADDRESS", "").strip()
    notify_to = os.environ.get("SPONSOR_FEEDBACK_NOTIFY_TO", "").strip()
    password_file = Path(
        os.environ.get("SPONSOR_GMAIL_APP_PASSWORD_FILE", "")
    ).expanduser()
    return bool(
        _valid_email(sender)
        and _valid_email(notify_to)
        and password_file.is_file()
        and password_file.stat().st_size > 0
    )


def _feedback_notification_body(
    *,
    feedback_id: str,
    created_at: str,
    cleaned: dict[str, str],
    scenario_payload: dict[str, Any],
    attachment_count: int,
) -> str:
    scenario_summary = (
        json.dumps(scenario_payload, ensure_ascii=False, indent=2)
        if scenario_payload
        else "未关联情景"
    )
    return f"""BlueBalloon BlueLab 收到新的试用反馈。

反馈编号：{feedback_id}
提交时间：{created_at}
问题页面：{cleaned["source_page"]}
问题类型：{cleaned["category"]}
影响程度：{cleaned["impact"]}
标题：{cleaned["title"]}

问题描述：
{cleaned["description"]}

复现步骤：
{cleaned["reproduction_steps"] or "未填写"}

期望结果：
{cleaned["expected_behavior"] or "未填写"}

联系邮箱：
{cleaned["contact"] or "未填写"}

应用版本：{cleaned["app_version"]}
截图数量：{attachment_count}

关联情景：
{scenario_summary}

此邮件由 BlueBalloon BlueLab 试用反馈系统自动发送。
"""


def _feedback_acknowledgement_body(*, feedback_id: str, created_at: str) -> str:
    return f"""您好：

我们已收到您提交的试用反馈。

反馈编号：{feedback_id}
提交时间：{created_at}

项目团队会根据影响程度进行核对。后续沟通时请保留反馈编号。请勿通过回复邮件发送患者级数据或任何个人可识别信息。

此邮件为自动回执，无需回复。

BlueBalloon BlueLab
"""


def _queue_feedback_emails(
    connection: sqlite3.Connection,
    *,
    feedback_id: str,
    created_at: str,
    cleaned: dict[str, str],
    scenario_payload: dict[str, Any],
    saved_attachments: list[dict[str, Any]],
) -> dict[str, bool]:
    queued = {"internal_notification": False, "acknowledgement": False}
    if not email_delivery_configured():
        return queued

    notify_to = os.environ.get("SPONSOR_FEEDBACK_NOTIFY_TO", "").strip()
    attachment_paths = [item["relative_path"] for item in saved_attachments]
    messages = [
        {
            "message_type": "internal",
            "recipient": notify_to,
            "subject": f"[试用反馈] {cleaned['impact']} · {cleaned['title']} · {feedback_id}",
            "body_text": _feedback_notification_body(
                feedback_id=feedback_id,
                created_at=created_at,
                cleaned=cleaned,
                scenario_payload=scenario_payload,
                attachment_count=len(saved_attachments),
            ),
            "reply_to": cleaned["contact"],
            "attachments": attachment_paths,
        }
    ]
    if cleaned["contact"]:
        messages.append(
            {
                "message_type": "acknowledgement",
                "recipient": cleaned["contact"],
                "subject": f"BlueBalloon BlueLab：我们已收到您的反馈（{feedback_id}）",
                "body_text": _feedback_acknowledgement_body(
                    feedback_id=feedback_id,
                    created_at=created_at,
                ),
                "reply_to": "",
                "attachments": [],
            }
        )

    for message in messages:
        connection.execute(
            """
            INSERT INTO email_outbox (
                message_id, feedback_id, message_type, recipient, subject,
                body_text, reply_to, attachments_json, status, attempts,
                next_attempt_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
            """,
            (
                f"MAIL-{uuid.uuid4().hex.upper()}",
                feedback_id,
                message["message_type"],
                message["recipient"],
                message["subject"],
                message["body_text"],
                message["reply_to"],
                json.dumps(message["attachments"], ensure_ascii=False),
                created_at,
                created_at,
            ),
        )
        if message["message_type"] == "internal":
            queued["internal_notification"] = True
        else:
            queued["acknowledgement"] = True
    return queued


def _safe_original_name(value: str) -> str:
    name = Path(str(value or "截图")).name.replace("\x00", "").strip()
    return name[:180] or "截图"


def _normalized_image(
    *,
    feedback_id: str,
    index: int,
    original_name: str,
    content: bytes,
    target_dir: Path,
) -> dict[str, Any]:
    if not content:
        raise LocalContentError(f"截图“{original_name}”为空文件。")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise LocalContentError(f"截图“{original_name}”超过5 MB限制。")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                image_format = str(probe.format or "").upper()
                width, height = probe.size
                probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning) as exc:
        raise LocalContentError(f"截图“{original_name}”不是有效的PNG或JPG图片。") from exc

    if image_format not in {"PNG", "JPEG"}:
        raise LocalContentError(f"截图“{original_name}”仅支持PNG或JPG格式。")
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise LocalContentError(f"截图“{original_name}”像素尺寸过大。")

    suffix = ".png" if image_format == "PNG" else ".jpg"
    stored_name = f"{feedback_id}_{index:02d}_{uuid.uuid4().hex[:8]}{suffix}"
    target = target_dir / stored_name
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    try:
        with Image.open(io.BytesIO(content)) as source:
            normalized = ImageOps.exif_transpose(source)
            if image_format == "PNG":
                normalized = normalized.convert("RGBA" if "A" in normalized.getbands() else "RGB")
                normalized.save(temporary, format="PNG", optimize=True)
            else:
                normalized = normalized.convert("RGB")
                normalized.save(temporary, format="JPEG", quality=90, optimize=True)
        os.replace(temporary, target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise LocalContentError(f"截图“{original_name}”无法保存。") from exc

    return {
        "original_name": _safe_original_name(original_name),
        "stored_name": stored_name,
        "relative_path": target.relative_to(feedback_root()).as_posix(),
        "size_bytes": target.stat().st_size,
        "width": width,
        "height": height,
        "format": image_format,
    }


def submit_feedback(
    *,
    category: str,
    impact: str,
    source_page: str,
    title: str,
    description: str,
    reproduction_steps: str = "",
    expected_behavior: str = "",
    contact: str = "",
    app_version: str,
    scenario_context: dict[str, Any] | None = None,
    attachments: Iterable[tuple[str, bytes]] = (),
) -> dict[str, Any]:
    ensure_local_storage()
    cleaned = {
        "category": _clean_text(category, field_name="问题类型", max_length=40, required=True),
        "impact": _clean_text(impact, field_name="影响程度", max_length=40, required=True),
        "source_page": _clean_text(source_page, field_name="问题发生页面", max_length=60, required=True),
        "title": _clean_text(title, field_name="问题标题", max_length=80, required=True),
        "description": _clean_text(description, field_name="问题描述", max_length=4000, required=True),
        "reproduction_steps": _clean_text(
            reproduction_steps, field_name="复现步骤", max_length=2000
        ),
        "expected_behavior": _clean_text(
            expected_behavior, field_name="期望结果", max_length=1200
        ),
        "contact": _clean_text(contact, field_name="联系邮箱", max_length=254),
        "app_version": _clean_text(
            app_version, field_name="应用版本", max_length=80, required=True
        ),
    }
    if cleaned["contact"] and not _valid_email(cleaned["contact"]):
        raise LocalContentError("联系邮箱格式不正确，请填写完整邮箱地址或留空。")

    attachment_items = list(attachments)
    if len(attachment_items) > MAX_ATTACHMENTS:
        raise LocalContentError(f"一次最多上传{MAX_ATTACHMENTS}张截图。")

    scenario_payload = scenario_context or {}
    try:
        scenario_json = json.dumps(scenario_payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise LocalContentError("当前情景摘要无法保存，请取消关联情景后重试。") from exc
    if len(scenario_json) > 50_000:
        raise LocalContentError("当前情景摘要过大，请取消关联情景后重试。")

    created_at = datetime.now(SHANGHAI_TZ)
    feedback_id = f"FB-{created_at:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    attachment_dir = feedback_upload_root() / f"{created_at:%Y}" / f"{created_at:%m}" / feedback_id
    saved_attachments: list[dict[str, Any]] = []
    if attachment_items:
        _mkdir_private(attachment_dir)
        try:
            for index, (original_name, content) in enumerate(attachment_items, start=1):
                saved_attachments.append(
                    _normalized_image(
                        feedback_id=feedback_id,
                        index=index,
                        original_name=original_name,
                        content=content,
                        target_dir=attachment_dir,
                    )
                )
        except Exception:
            shutil.rmtree(attachment_dir, ignore_errors=True)
            raise

    try:
        with closing(_connect_feedback_db()) as connection, connection:
            connection.execute(
                """
                INSERT INTO feedback (
                    feedback_id, created_at, category, impact, source_page, title,
                    description, reproduction_steps, expected_behavior, contact,
                    app_version, scenario_json, attachments_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    created_at.isoformat(timespec="seconds"),
                    cleaned["category"],
                    cleaned["impact"],
                    cleaned["source_page"],
                    cleaned["title"],
                    cleaned["description"],
                    cleaned["reproduction_steps"],
                    cleaned["expected_behavior"],
                    cleaned["contact"],
                    cleaned["app_version"],
                    scenario_json,
                    json.dumps(saved_attachments, ensure_ascii=False, separators=(",", ":")),
                    "待处理",
                ),
            )
            queued = _queue_feedback_emails(
                connection,
                feedback_id=feedback_id,
                created_at=created_at.isoformat(timespec="seconds"),
                cleaned=cleaned,
                scenario_payload=scenario_payload,
                saved_attachments=saved_attachments,
            )
    except sqlite3.Error as exc:
        if attachment_items:
            shutil.rmtree(attachment_dir, ignore_errors=True)
        raise LocalContentError("反馈暂时无法写入本地数据库，请稍后重试。") from exc

    return {
        "feedback_id": feedback_id,
        "created_at": created_at.isoformat(timespec="seconds"),
        "status": "待处理",
        "attachment_count": len(saved_attachments),
        "internal_notification_queued": queued["internal_notification"],
        "acknowledgement_queued": queued["acknowledgement"],
    }


def feedback_rows() -> list[dict[str, Any]]:
    ensure_local_storage()
    with closing(_connect_feedback_db()) as connection:
        rows = connection.execute(
            """
            SELECT feedback_id, created_at, category, impact, source_page, title,
                   description, reproduction_steps, expected_behavior, contact,
                   app_version, scenario_json, attachments_json, status
            FROM feedback
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]
