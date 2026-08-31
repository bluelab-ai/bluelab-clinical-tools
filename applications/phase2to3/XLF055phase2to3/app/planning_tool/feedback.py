"""Private local feedback storage and resilient background email outbox."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
import io
import json
import os
from pathlib import Path
import re
import shutil
import smtplib
import sqlite3
import ssl
import uuid
import warnings
from typing import Iterable
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps, UnidentifiedImageError


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = APP_ROOT / "runtime"
TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_NOTIFY_TO = "feedback@example.com"
MAX_ATTACHMENTS = 3
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_DIMENSION = 12_000
MAX_ATTEMPTS = 4
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FeedbackError(ValueError):
    """Raised when feedback cannot be accepted safely."""


def runtime_root() -> Path:
    configured = os.getenv("XLF055_APP_LOCAL_DATA_ROOT", "").strip()
    if not configured:
        return DEFAULT_RUNTIME
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = APP_ROOT / candidate
    return candidate.resolve()


def feedback_root() -> Path:
    return runtime_root() / "feedback"


def database_path() -> Path:
    return feedback_root() / "feedback.db"


def upload_root() -> Path:
    return feedback_root() / "uploads"


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _harden_database_files() -> None:
    base = database_path()
    for candidate in (base, Path(str(base) + "-wal"), Path(str(base) + "-shm")):
        if candidate.exists() and candidate.is_file():
            candidate.chmod(0o600)


def _postcommit_hardening_status() -> bool:
    # Never turn a committed operation into a false failure report.
    try:
        _harden_database_files()
    except OSError:
        return False
    return True


def _connect() -> sqlite3.Connection:
    _private_directory(feedback_root())
    path = database_path()
    connection = sqlite3.connect(path, timeout=10)
    path.chmod(0o600)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=10000")
    _harden_database_files()
    return connection


def ensure_storage() -> None:
    _private_directory(feedback_root())
    _private_directory(upload_root())
    with closing(_connect()) as connection, connection:
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
                created_at TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT '',
                last_error_type TEXT NOT NULL DEFAULT '',
                next_attempt_at TEXT NOT NULL DEFAULT '',
                lease_until TEXT NOT NULL DEFAULT '',
                worker_id TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(feedback_id) REFERENCES feedback(feedback_id)
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(email_outbox)").fetchall()
        }
        migrations = {
            "next_attempt_at": "TEXT NOT NULL DEFAULT ''",
            "lease_until": "TEXT NOT NULL DEFAULT ''",
            "worker_id": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in migrations.items():
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE email_outbox ADD COLUMN {column} {definition}"
                )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_xlf055_outbox "
            "ON email_outbox(status, next_attempt_at, created_at)"
        )
    _harden_database_files()


def _clean(
    value: str, *, field: str, maximum: int, required: bool = False
) -> str:
    cleaned = str(value or "").replace("\x00", "").strip()
    if required and not cleaned:
        raise FeedbackError(f"请填写{field}。")
    if len(cleaned) > maximum:
        raise FeedbackError(f"{field}不能超过{maximum}个字符。")
    return cleaned


def _clean_header(
    value: str, *, field: str, maximum: int, required: bool = False
) -> str:
    cleaned = _clean(value, field=field, maximum=maximum, required=required)
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise FeedbackError(f"{field}不能包含换行符或控制字符。")
    return cleaned


def _valid_email(value: str) -> bool:
    _, parsed = parseaddr(value)
    return bool(
        parsed == value
        and len(parsed) <= 254
        and EMAIL_PATTERN.fullmatch(parsed)
    )


def _env(primary: str, legacy: str, default: str = "") -> str:
    return (
        os.getenv(primary, "").strip()
        or os.getenv(legacy, "").strip()
        or default
    )


def email_delivery_requested() -> bool:
    return (
        _env("XLF055_FEEDBACK_EMAIL_ENABLED", "SPONSOR_EMAIL_ENABLED", "0")
        == "1"
    )


def notification_recipient() -> str:
    configured = _env(
        "XLF055_FEEDBACK_NOTIFY_TO",
        "SPONSOR_FEEDBACK_NOTIFY_TO",
        DEFAULT_NOTIFY_TO,
    )
    return configured if _valid_email(configured) else DEFAULT_NOTIFY_TO


def smtp_settings() -> dict[str, object] | None:
    """Resolve worker-only SMTP settings; invalid configuration never raises."""
    if not email_delivery_requested():
        return None
    try:
        sender = _env(
            "XLF055_FEEDBACK_SMTP_USERNAME", "SPONSOR_GMAIL_ADDRESS"
        )
        if not _valid_email(sender):
            return None
        password_path_value = _env(
            "XLF055_FEEDBACK_SMTP_PASSWORD_FILE",
            "SPONSOR_GMAIL_APP_PASSWORD_FILE",
        )
        if not password_path_value:
            return None
        password_path = Path(password_path_value).expanduser()
        if not password_path.is_file():
            return None
        if password_path.stat().st_mode & 0o077:
            return None
        password = "".join(
            password_path.read_text(encoding="utf-8").split()
        )
        if not password:
            return None
        port = int(
            _env("XLF055_FEEDBACK_SMTP_PORT", "SPONSOR_SMTP_PORT", "465")
        )
        if port < 1 or port > 65535:
            return None
        from_name = _env(
            "XLF055_FEEDBACK_FROM_NAME",
            "SPONSOR_EMAIL_FROM_NAME",
            "XLF055规划工具",
        )
        if any(ord(character) < 32 or ord(character) == 127 for character in from_name):
            return None
        notify_to = notification_recipient()
        return {
            "host": _env(
                "XLF055_FEEDBACK_SMTP_HOST",
                "SPONSOR_SMTP_HOST",
                "smtp.gmail.com",
            ),
            "port": port,
            "sender": sender,
            "password": password,
            "notify_to": notify_to,
            "from_name": from_name[:80],
        }
    except (OSError, UnicodeError, ValueError):
        return None


def email_channel_status() -> dict[str, object]:
    """Return public queue intent without reading or exposing SMTP credentials."""
    requested = email_delivery_requested()
    return {
        "delivery_requested": requested,
        "notify_to": notification_recipient(),
        "automatic_receipt_mode": "queued_when_contact_email_is_provided",
        "credential_storage": "worker-only protected password file",
    }


def _safe_attachment(
    feedback_id: str,
    index: int,
    original_name: str,
    content: bytes,
) -> dict[str, object]:
    del original_name
    label = f"截图{index}"
    if not content:
        raise FeedbackError(f"{label}为空文件。")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise FeedbackError(f"{label}超过5 MB。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                image_format = str(probe.format or "").upper()
                width, height = probe.size
                probe.verify()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise FeedbackError("截图必须是有效的PNG或JPG图片。") from exc
    if image_format not in {"PNG", "JPEG"}:
        raise FeedbackError("截图仅支持PNG或JPG格式。")
    if (
        width <= 0
        or height <= 0
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise FeedbackError("截图像素尺寸过大。")
    suffix = ".png" if image_format == "PNG" else ".jpg"
    target_directory = upload_root() / feedback_id
    _private_directory(target_directory)
    name = f"{feedback_id}_{index:02d}_{uuid.uuid4().hex[:8]}{suffix}"
    target = target_directory / name
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    try:
        with Image.open(io.BytesIO(content)) as source:
            normalized = ImageOps.exif_transpose(source)
            if image_format == "PNG":
                normalized = normalized.convert(
                    "RGBA" if "A" in normalized.getbands() else "RGB"
                )
                normalized.save(temporary, format="PNG", optimize=True)
            else:
                normalized = normalized.convert("RGB")
                normalized.save(
                    temporary, format="JPEG", quality=90, optimize=True
                )
        if temporary.stat().st_size > MAX_ATTACHMENT_BYTES:
            raise FeedbackError(f"{label}重新编码后超过5 MB。")
        os.replace(temporary, target)
        target.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return {
        "display_name": label,
        "relative_path": target.relative_to(feedback_root()).as_posix(),
        "size_bytes": target.stat().st_size,
        "format": image_format,
    }


def _notification_body(
    feedback_id: str, created_at: str, values: dict[str, str]
) -> str:
    return f"""XLF055规划工具收到新的问题反馈。

反馈编号：{feedback_id}
提交时间：{created_at}
问题页面：{values["source_page"]}
问题类型：{values["category"]}
影响程度：{values["impact"]}
标题：{values["title"]}

问题描述：
{values["description"]}

复现步骤：
{values["reproduction_steps"] or "未填写"}

期望结果：
{values["expected_behavior"] or "未填写"}

联系邮箱：
{values["contact"] or "未填写"}

应用版本：{values["app_version"]}

反馈系统不会自动附带病例参数。请勿通过邮件发送患者级数据或直接标识符。
"""


def _receipt_body(feedback_id: str, created_at: str) -> str:
    return f"""您好：

我们已收到您提交的XLF055规划工具反馈。

反馈编号：{feedback_id}
提交时间：{created_at}

项目团队会进行核对。请保留反馈编号，并请勿通过回复邮件发送患者级数据或个人可识别信息。

此邮件为自动回执，无需回复。

XLF055规划工具
"""


def _queue_messages(
    connection: sqlite3.Connection,
    *,
    feedback_id: str,
    created_at: str,
    values: dict[str, str],
    attachments: list[dict[str, object]],
) -> int:
    messages = [
        {
            "type": "internal",
            "recipient": notification_recipient(),
            "subject": (
                f"[XLF055反馈] {values['impact']} · {values['title']} · "
                f"{feedback_id}"
            ),
            "body": _notification_body(feedback_id, created_at, values),
            "reply_to": values["contact"],
            "attachments": [
                str(item["relative_path"]) for item in attachments
            ],
        }
    ]
    if values["contact"]:
        messages.append(
            {
                "type": "acknowledgement",
                "recipient": values["contact"],
                "subject": f"我们已收到您的反馈（{feedback_id}）",
                "body": _receipt_body(feedback_id, created_at),
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
                created_at, next_attempt_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
            """,
            (
                f"MAIL-{uuid.uuid4().hex.upper()}",
                feedback_id,
                message["type"],
                message["recipient"],
                message["subject"],
                message["body"],
                message["reply_to"],
                json.dumps(message["attachments"], ensure_ascii=False),
                created_at,
                created_at,
            ),
        )
    return len(messages)


def _build_email(row: sqlite3.Row, settings: dict[str, object]) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr(
        (str(settings["from_name"]), str(settings["sender"]))
    )
    message["To"] = row["recipient"]
    message["Subject"] = row["subject"]
    message["Message-ID"] = f"<{row['message_id'].lower()}@xlf055.local>"
    message["X-Feedback-ID"] = row["feedback_id"]
    if row["reply_to"]:
        message["Reply-To"] = row["reply_to"]
    message.set_content(row["body_text"])
    attachment_base = feedback_root().resolve()
    total = 0
    for relative in json.loads(row["attachments_json"] or "[]"):
        candidate = (attachment_base / str(relative)).resolve()
        if (
            not candidate.is_relative_to(attachment_base)
            or not candidate.is_file()
        ):
            raise FileNotFoundError("queued attachment is unavailable")
        content = candidate.read_bytes()
        total += len(content)
        if total > MAX_TOTAL_ATTACHMENT_BYTES:
            raise ValueError("queued attachments exceed total limit")
        subtype = "png" if candidate.suffix.lower() == ".png" else "jpeg"
        message.add_attachment(
            content, maintype="image", subtype=subtype, filename=candidate.name
        )
    return message


def _status_counts() -> dict[str, int]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS n FROM email_outbox GROUP BY status"
        ).fetchall()
    counts = {str(row["status"]): int(row["n"]) for row in rows}
    return {
        "pending": counts.get("pending", 0),
        "retry": counts.get("retry", 0),
        "sending": counts.get("sending", 0),
        "sent": counts.get("sent", 0),
        "failed": counts.get("failed", 0),
    }


def _release_stale_claims(now: str) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            """
            UPDATE email_outbox
            SET status='retry', worker_id='', lease_until='',
                next_attempt_at=?, last_error_type='LeaseExpired'
            WHERE status='sending' AND lease_until!='' AND lease_until<=?
            """,
            (now, now),
        )


def _claim_next(worker_id: str, now: str) -> sqlite3.Row | None:
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT * FROM email_outbox
            WHERE status IN ('pending', 'retry')
              AND attempts < ?
              AND (next_attempt_at='' OR next_attempt_at<=?)
            ORDER BY created_at, message_id
            LIMIT 1
            """,
            (MAX_ATTEMPTS, now),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        lease_until = (
            datetime.now(TZ) + timedelta(minutes=2)
        ).isoformat(timespec="seconds")
        changed = connection.execute(
            """
            UPDATE email_outbox
            SET status='sending', worker_id=?, lease_until=?
            WHERE message_id=? AND status IN ('pending', 'retry')
            """,
            (worker_id, lease_until, row["message_id"]),
        ).rowcount
        connection.commit()
        if changed != 1:
            return None
        return connection.execute(
            "SELECT * FROM email_outbox WHERE message_id=?",
            (row["message_id"],),
        ).fetchone()


def process_email_outbox(limit: int = 10) -> dict[str, int | bool]:
    ensure_storage()
    requested = email_delivery_requested()
    settings = smtp_settings()
    before = _status_counts()
    if settings is None:
        return {
            "delivery_requested": requested,
            "configured": False,
            "config_error": requested,
            "selected": 0,
            "sent": 0,
            "retry_scheduled": 0,
            "permanent_failed": 0,
            "pending_email_count": (
                before["pending"] + before["retry"] + before["sending"]
            ),
            "terminal_failed_count": before["failed"],
        }

    now = datetime.now(TZ).isoformat(timespec="seconds")
    _release_stale_claims(now)
    selected = sent = retry_scheduled = permanent_failed = 0
    worker_id = f"WORKER-{uuid.uuid4().hex[:12]}"
    for _ in range(max(1, min(int(limit), 50))):
        row = _claim_next(
            worker_id, datetime.now(TZ).isoformat(timespec="seconds")
        )
        if row is None:
            break
        selected += 1
        try:
            message = _build_email(row, settings)
            with smtplib.SMTP_SSL(
                str(settings["host"]),
                int(settings["port"]),
                context=ssl.create_default_context(),
                timeout=20,
            ) as smtp:
                smtp.login(
                    str(settings["sender"]), str(settings["password"])
                )
                smtp.send_message(message)
        except Exception as exc:
            attempts = int(row["attempts"]) + 1
            terminal = attempts >= MAX_ATTEMPTS
            if terminal:
                permanent_failed += 1
                status = "failed"
                next_attempt_at = ""
            else:
                retry_scheduled += 1
                status = "retry"
                delay_seconds = min(15 * (2 ** (attempts - 1)), 3600)
                next_attempt_at = (
                    datetime.now(TZ) + timedelta(seconds=delay_seconds)
                ).isoformat(timespec="seconds")
            with closing(_connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE email_outbox
                    SET status=?, attempts=?, last_error_type=?,
                        next_attempt_at=?, worker_id='', lease_until=''
                    WHERE message_id=? AND worker_id=?
                    """,
                    (
                        status,
                        attempts,
                        type(exc).__name__,
                        next_attempt_at,
                        row["message_id"],
                        worker_id,
                    ),
                )
        else:
            sent += 1
            with closing(_connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE email_outbox
                    SET status='sent', attempts=attempts+1, sent_at=?,
                        last_error_type='', next_attempt_at='',
                        worker_id='', lease_until=''
                    WHERE message_id=? AND worker_id=?
                    """,
                    (
                        datetime.now(TZ).isoformat(timespec="seconds"),
                        row["message_id"],
                        worker_id,
                    ),
                )
    after = _status_counts()
    storage_hardening_verified = _postcommit_hardening_status()
    return {
        "delivery_requested": True,
        "configured": True,
        "config_error": False,
        "selected": selected,
        "sent": sent,
        "retry_scheduled": retry_scheduled,
        "permanent_failed": permanent_failed,
        "pending_email_count": (
            after["pending"] + after["retry"] + after["sending"]
        ),
        "terminal_failed_count": after["failed"],
        "storage_hardening_verified": storage_hardening_verified,
    }


def submit_feedback(
    *,
    category: str,
    impact: str,
    source_page: str,
    title: str,
    description: str,
    reproduction_steps: str,
    expected_behavior: str,
    contact: str,
    app_version: str,
    attachments: Iterable[tuple[str, bytes]] = (),
) -> dict[str, object]:
    ensure_storage()
    values = {
        "category": _clean_header(
            category, field="问题类型", maximum=40, required=True
        ),
        "impact": _clean_header(
            impact, field="影响程度", maximum=40, required=True
        ),
        "source_page": _clean_header(
            source_page, field="问题页面", maximum=60, required=True
        ),
        "title": _clean_header(
            title, field="问题标题", maximum=80, required=True
        ),
        "description": _clean(
            description, field="问题描述", maximum=4000, required=True
        ),
        "reproduction_steps": _clean(
            reproduction_steps, field="复现步骤", maximum=2000
        ),
        "expected_behavior": _clean(
            expected_behavior, field="期望结果", maximum=1200
        ),
        "contact": _clean_header(
            contact, field="联系邮箱", maximum=254
        ),
        "app_version": _clean_header(
            app_version, field="应用版本", maximum=80, required=True
        ),
    }
    if values["contact"] and not _valid_email(values["contact"]):
        raise FeedbackError("联系邮箱格式不正确。")
    attachment_items = list(attachments)
    if len(attachment_items) > MAX_ATTACHMENTS:
        raise FeedbackError("一次最多上传3张截图。")
    if sum(len(content) for _, content in attachment_items) > MAX_TOTAL_ATTACHMENT_BYTES:
        raise FeedbackError("截图总大小不能超过10 MB。")

    created_at = datetime.now(TZ).isoformat(timespec="seconds")
    feedback_id = (
        f"FB-{datetime.now(TZ):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    )
    feedback_directory = upload_root() / feedback_id
    saved: list[dict[str, object]] = []
    try:
        for index, (name, content) in enumerate(attachment_items, start=1):
            saved.append(
                _safe_attachment(feedback_id, index, name, content)
            )
        if sum(int(item["size_bytes"]) for item in saved) > MAX_TOTAL_ATTACHMENT_BYTES:
            raise FeedbackError("截图重新编码后的总大小超过10 MB。")
        with closing(_connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO feedback (
                    feedback_id, created_at, category, impact, source_page, title,
                    description, reproduction_steps, expected_behavior, contact,
                    app_version, attachments_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '待处理')
                """,
                (
                    feedback_id,
                    created_at,
                    values["category"],
                    values["impact"],
                    values["source_page"],
                    values["title"],
                    values["description"],
                    values["reproduction_steps"],
                    values["expected_behavior"],
                    values["contact"],
                    values["app_version"],
                    json.dumps(saved, ensure_ascii=False),
                ),
            )
            queued = _queue_messages(
                connection,
                feedback_id=feedback_id,
                created_at=created_at,
                values=values,
                attachments=saved,
            )
    except Exception:
        if feedback_directory.exists():
            shutil.rmtree(feedback_directory)
        raise
    storage_hardening_verified = _postcommit_hardening_status()
    requested = email_delivery_requested()
    return {
        "feedback_id": feedback_id,
        "created_at": created_at,
        "stored_locally": True,
        "queued_messages": queued,
        "email_delivery_requested": requested,
        "delivery_status": (
            "queued_for_background_delivery"
            if requested
            else "queued_email_channel_not_enabled"
        ),
        "automatic_receipt_requested": bool(values["contact"]),
        "storage_hardening_verified": storage_hardening_verified,
    }


def aggregate_status() -> dict[str, int]:
    ensure_storage()
    with closing(_connect()) as connection:
        feedback_n = int(
            connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        )
    counts = _status_counts()
    return {
        "feedback_count": feedback_n,
        "pending_email_count": (
            counts["pending"] + counts["retry"] + counts["sending"]
        ),
        "sent_email_count": counts["sent"],
        "failed_email_count": counts["failed"],
    }
