"""Durable feedback notification outbox for the Tapgrel planning tool."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
import json
import mimetypes
import os
from pathlib import Path
import smtplib
import sqlite3
import ssl
import uuid


APP_ROOT = Path(__file__).resolve().parent
RUNTIME = APP_ROOT / "runtime"
FEEDBACK_ROOT = RUNTIME / "feedback"
DATABASE = FEEDBACK_ROOT / "email_outbox.db"
DEFAULT_NOTIFY_TO = "feedback@example.com"
MAX_ATTEMPTS = 6


def _valid_email(value: str) -> bool:
    _, parsed = parseaddr(value)
    return bool(parsed == value and "@" in parsed and len(parsed) <= 254)


def _connect() -> sqlite3.Connection:
    FEEDBACK_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    FEEDBACK_ROOT.chmod(0o700)
    connection = sqlite3.connect(DATABASE, timeout=10)
    DATABASE.chmod(0o600)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def ensure_storage() -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS email_outbox (
                message_id TEXT PRIMARY KEY,
                feedback_id TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                body_text TEXT NOT NULL,
                reply_to TEXT NOT NULL DEFAULT '',
                attachment_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT '',
                next_attempt_at TEXT NOT NULL DEFAULT '',
                last_error_type TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tapgrel_outbox "
            "ON email_outbox(status, next_attempt_at, created_at)"
        )


def _notify_to() -> str:
    configured = (
        os.getenv("TAPGREL_FEEDBACK_NOTIFY_TO", "").strip()
        or os.getenv("SPONSOR_FEEDBACK_NOTIFY_TO", "").strip()
        or DEFAULT_NOTIFY_TO
    )
    return configured if _valid_email(configured) else DEFAULT_NOTIFY_TO


def queue_feedback_email(record: dict[str, object], attachment: Path | None = None) -> str:
    """Queue one owner notification after the local feedback record is committed."""
    ensure_storage()
    feedback_id = str(record.get("feedback_id", "")).strip()
    if not feedback_id:
        raise ValueError("feedback_id is required")
    title = str(record.get("title", "")).replace("\r", " ").replace("\n", " ").strip()[:80]
    subject = f"[泰普格雷反馈][{record.get('impact', '未分级')}] {title}"[:180]
    contact = str(record.get("contact", "")).strip()
    reply_to = contact if _valid_email(contact) else ""
    body = "\n".join(
        [
            "泰普格雷 Phase III 规划探索工具收到一条新反馈。",
            "",
            f"反馈编号：{feedback_id}",
            f"提交时间：{record.get('submitted_at_utc', '')}",
            f"问题类型：{record.get('category', '')}",
            f"影响程度：{record.get('impact', '')}",
            f"发生页面：{record.get('source_page', '')}",
            f"问题标题：{title}",
            "",
            "问题描述：",
            str(record.get("description", ""))[:4000],
            "",
            "复现步骤：",
            str(record.get("steps", ""))[:2000] or "未填写",
            "",
            f"联系邮箱：{contact or '未填写'}",
            f"关联当前情景：{'是' if record.get('scenario') else '否'}",
        ]
    )
    attachment_value = ""
    if attachment:
        resolved = attachment.resolve()
        root = FEEDBACK_ROOT.resolve()
        if resolved.is_file() and resolved.is_relative_to(root):
            attachment_value = str(resolved.relative_to(root))
    message_id = f"MSG-{uuid.uuid4().hex.upper()}"
    with closing(_connect()) as connection, connection:
        connection.execute(
            """
            INSERT INTO email_outbox (
                message_id, feedback_id, recipient, subject, body_text,
                reply_to, attachment_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                feedback_id,
                _notify_to(),
                subject,
                body,
                reply_to,
                attachment_value,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
    return message_id


def _smtp_settings() -> dict[str, object]:
    if os.getenv("SPONSOR_EMAIL_ENABLED", "").strip() != "1":
        raise RuntimeError("SMTP delivery is disabled")
    sender = os.getenv("SPONSOR_GMAIL_ADDRESS", "").strip()
    password_path = Path(
        os.getenv("SPONSOR_GMAIL_APP_PASSWORD_FILE", "")
    ).expanduser()
    if not _valid_email(sender) or not password_path.is_file():
        raise RuntimeError("SMTP credentials are incomplete")
    if password_path.stat().st_mode & 0o077:
        raise RuntimeError("SMTP password file permissions are too broad")
    password = "".join(password_path.read_text(encoding="utf-8").split())
    if not password:
        raise RuntimeError("SMTP password is empty")
    return {
        "host": os.getenv("SPONSOR_SMTP_HOST", "smtp.gmail.com").strip(),
        "port": int(os.getenv("SPONSOR_SMTP_PORT", "465")),
        "sender": sender,
        "password": password,
        "from_name": "泰普格雷规划工具",
    }


def _build_message(row: sqlite3.Row, settings: dict[str, object]) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((str(settings["from_name"]), str(settings["sender"])))
    message["To"] = row["recipient"]
    message["Subject"] = row["subject"]
    message["Message-ID"] = f"<{row['message_id'].lower()}@tapgrel.local>"
    message["X-Feedback-ID"] = row["feedback_id"]
    if row["reply_to"]:
        message["Reply-To"] = row["reply_to"]
    message.set_content(row["body_text"])
    if row["attachment_path"]:
        candidate = (FEEDBACK_ROOT / row["attachment_path"]).resolve()
        root = FEEDBACK_ROOT.resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise FileNotFoundError("queued attachment is unavailable")
        mime, _ = mimetypes.guess_type(candidate.name)
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        message.add_attachment(
            candidate.read_bytes(), maintype=maintype, subtype=subtype, filename=candidate.name
        )
    return message


def process_outbox(limit: int = 10) -> dict[str, int]:
    ensure_storage()
    settings = _smtp_settings()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT * FROM email_outbox
            WHERE status IN ('pending', 'retry') AND attempts < ?
              AND (next_attempt_at='' OR next_attempt_at<=?)
            ORDER BY created_at, message_id LIMIT ?
            """,
            (MAX_ATTEMPTS, now, max(1, min(limit, 50))),
        ).fetchall()
    sent = retried = failed = 0
    for row in rows:
        try:
            message = _build_message(row, settings)
            with smtplib.SMTP_SSL(
                str(settings["host"]),
                int(settings["port"]),
                context=ssl.create_default_context(),
                timeout=25,
            ) as smtp:
                smtp.login(str(settings["sender"]), str(settings["password"]))
                smtp.send_message(message)
        except Exception as exc:
            attempts = int(row["attempts"]) + 1
            terminal = attempts >= MAX_ATTEMPTS
            next_attempt = "" if terminal else (
                datetime.now(timezone.utc) + timedelta(seconds=min(30 * 2 ** (attempts - 1), 3600))
            ).isoformat(timespec="seconds")
            with closing(_connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE email_outbox SET status=?, attempts=?, next_attempt_at=?,
                        last_error_type=? WHERE message_id=?
                    """,
                    (
                        "failed" if terminal else "retry",
                        attempts,
                        next_attempt,
                        type(exc).__name__,
                        row["message_id"],
                    ),
                )
            failed += int(terminal)
            retried += int(not terminal)
        else:
            with closing(_connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE email_outbox SET status='sent', attempts=attempts+1,
                        sent_at=?, next_attempt_at='', last_error_type=''
                    WHERE message_id=?
                    """,
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), row["message_id"]),
                )
            sent += 1
    return {"selected": len(rows), "sent": sent, "retry": retried, "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    result = process_outbox(limit=args.limit)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if result["retry"] or result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
