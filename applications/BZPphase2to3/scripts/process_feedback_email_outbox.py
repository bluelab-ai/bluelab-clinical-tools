#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
import json
import mimetypes
import os
from pathlib import Path
import smtplib
import sqlite3
import ssl
import sys
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sponsor_demo.local_collaboration import ensure_local_storage, feedback_db_path, feedback_root  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
MAX_ATTACHED_BYTES = 10 * 1024 * 1024
MAX_ATTEMPTS = 4
RETRY_MINUTES = (1, 5, 30, 120)


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def settings() -> dict[str, object]:
    password_path = Path(os.environ.get("SPONSOR_GMAIL_APP_PASSWORD_FILE", "")).expanduser()
    if os.environ.get("SPONSOR_EMAIL_ENABLED", "").strip() != "1":
        raise RuntimeError("邮件发送未启用。")
    if not password_path.is_file():
        raise RuntimeError(f"Gmail应用密码文件不存在：{password_path}")
    password = "".join(password_path.read_text(encoding="utf-8").split())
    if not password:
        raise RuntimeError("Gmail应用密码为空。")
    return {
        "host": os.environ.get("SPONSOR_SMTP_HOST", "smtp.gmail.com").strip(),
        "port": int(os.environ.get("SPONSOR_SMTP_PORT", "465")),
        "sender": os.environ.get("SPONSOR_GMAIL_ADDRESS", "").strip(),
        "from_name": os.environ.get("SPONSOR_EMAIL_FROM_NAME", "BlueBalloon BlueLab").strip(),
        "password": password,
    }


def build_message(row: sqlite3.Row, config: dict[str, object]) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((str(config["from_name"]), str(config["sender"])))
    message["To"] = row["recipient"]
    message["Subject"] = row["subject"]
    message["X-Feedback-ID"] = row["feedback_id"]
    if row["reply_to"]:
        message["Reply-To"] = row["reply_to"]
    message.set_content(row["body_text"])

    attachment_root = feedback_root().resolve()
    attached_bytes = 0
    for relative_path in json.loads(row["attachments_json"] or "[]"):
        candidate = (attachment_root / str(relative_path)).resolve()
        if not candidate.is_relative_to(attachment_root) or not candidate.is_file():
            continue
        payload = candidate.read_bytes()
        if attached_bytes + len(payload) > MAX_ATTACHED_BYTES:
            continue
        mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        maintype, subtype = mime_type.split("/", 1)
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=candidate.name)
        attached_bytes += len(payload)
    return message


def deliver(message: EmailMessage, config: dict[str, object]) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(str(config["host"]), int(config["port"]), context=context, timeout=30) as smtp:
        smtp.login(str(config["sender"]), str(config["password"]))
        smtp.send_message(message)


def send_test(recipient: str, config: dict[str, object]) -> None:
    message = EmailMessage()
    message["From"] = formataddr((str(config["from_name"]), str(config["sender"])))
    message["To"] = recipient
    message["Subject"] = "BlueBalloon BlueLab 反馈邮件配置测试"
    message.set_content(
        "Gmail反馈提醒与自动回执通道已连接成功。\n\n"
        f"测试时间：{now_iso()}\n\nBlueBalloon BlueLab\n"
    )
    deliver(message, config)
    print(f"TEST_SENT recipient={recipient}")


def process(limit: int, config: dict[str, object]) -> int:
    ensure_local_storage()
    connection = sqlite3.connect(feedback_db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    sent = failed = retried = 0
    with closing(connection), connection:
        rows = connection.execute(
            """
            SELECT * FROM email_outbox
            WHERE status IN ('pending', 'retry') AND next_attempt_at <= ?
            ORDER BY created_at, message_id
            LIMIT ?
            """,
            (now_iso(), limit),
        ).fetchall()
        for row in rows:
            try:
                deliver(build_message(row, config), config)
            except Exception as exc:
                attempts = int(row["attempts"]) + 1
                if attempts >= MAX_ATTEMPTS:
                    status = "failed"
                    next_attempt = now_iso()
                    failed += 1
                else:
                    status = "retry"
                    delay = RETRY_MINUTES[min(attempts - 1, len(RETRY_MINUTES) - 1)]
                    next_attempt = (datetime.now(TZ) + timedelta(minutes=delay)).isoformat(timespec="seconds")
                    retried += 1
                connection.execute(
                    "UPDATE email_outbox SET status=?, attempts=?, next_attempt_at=?, last_error=? WHERE message_id=?",
                    (status, attempts, next_attempt, str(exc)[:1000], row["message_id"]),
                )
                print(
                    f"DELIVERY_{status.upper()} message_id={row['message_id']} "
                    f"feedback_id={row['feedback_id']} attempts={attempts} error={type(exc).__name__}"
                )
            else:
                connection.execute(
                    "UPDATE email_outbox SET status='sent', attempts=attempts+1, sent_at=?, last_error='' WHERE message_id=?",
                    (now_iso(), row["message_id"]),
                )
                sent += 1
                print(
                    f"DELIVERY_SENT message_id={row['message_id']} "
                    f"feedback_id={row['feedback_id']} type={row['message_type']}"
                )
    print(f"OUTBOX_SUMMARY selected={len(rows)} sent={sent} retry={retried} failed={failed}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Send queued sponsor feedback emails through Gmail SMTP.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--send-test-to", default="")
    args = parser.parse_args()
    config = settings()
    if args.send_test_to:
        send_test(args.send_test_to, config)
        return 0
    return process(max(1, min(args.limit, 100)), config)


if __name__ == "__main__":
    raise SystemExit(main())
