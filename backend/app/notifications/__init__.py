"""Email (primary) and Telegram (optional) notifications. Idempotent via (channel, dedupe_key)."""
import logging
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import utcnow
from app.models import Notification

log = logging.getLogger(__name__)


def email_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_user and s.smtp_password and s.notify_email_to)


def telegram_configured() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def send_email(subject: str, text: str, html: str | None = None, to: str | None = None) -> None:
    s = get_settings()
    if not (s.smtp_host and s.smtp_user and s.smtp_password):
        raise RuntimeError("SMTP is not configured")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s.smtp_from or s.smtp_user, to or s.notify_email_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(s.smtp_user, s.smtp_password.get_secret_value())
        smtp.send_message(msg)


def send_telegram(text: str) -> None:
    s = get_settings()
    r = httpx.post(f"https://api.telegram.org/bot{s.telegram_bot_token.get_secret_value()}/sendMessage",
                   json={"chat_id": s.telegram_chat_id, "text": text, "parse_mode": "HTML",
                         "disable_web_page_preview": True}, timeout=20)
    r.raise_for_status()


def notify(db: Session, *, kind: str, title: str, text: str, dedupe_key: str, html: str | None = None,
           telegram_text: str | None = None, user_id: int | None = None) -> list[Notification]:
    """Send on every configured channel at most once per dedupe_key."""
    channels = [c for c, ok in (("email", email_configured()), ("telegram", telegram_configured())) if ok]
    sent = []
    for channel in channels:
        if db.scalar(select(Notification.id).where(Notification.channel == channel,
                                                   Notification.dedupe_key == dedupe_key)):
            continue
        n = Notification(channel=channel, kind=kind, title=title[:300], body=text, dedupe_key=dedupe_key,
                         user_id=user_id)
        db.add(n)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            continue
        try:
            if channel == "email":
                send_email(title, text, html)
            else:
                send_telegram(telegram_text or f"<b>{title}</b>\n{text}")
            n.status, n.sent_at = "sent", utcnow()
        except Exception as e:  # noqa: BLE001 - notification failure must not break the pipeline
            n.status, n.error = "failed", repr(e)[:500]
            log.warning("notification failed", extra={"ctx": {"channel": channel, "error": repr(e)}})
        sent.append(n)
    db.commit()
    return sent
