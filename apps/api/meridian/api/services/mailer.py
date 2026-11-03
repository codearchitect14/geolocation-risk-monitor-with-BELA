"""Outgoing mail. Development uses a local SMTP catcher (Mailpit); tests replace the sender with a capture list."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from meridian.api.settings import get_api_settings

log = logging.getLogger("meridian.mail")


Attachment = tuple[str, bytes, str]  # filename, content, media type


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str, attachments: list[Attachment] | None = None) -> None: ...


class SmtpMailer:
    def send(self, to: str, subject: str, body: str, attachments: list[Attachment] | None = None) -> None:
        settings = get_api_settings()
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = settings.mail_from, to, subject
        message.set_content(body)
        for filename, content, media_type in attachments or []:
            main, _, sub = media_type.partition("/")
            message.add_attachment(content, maintype=main, subtype=sub or "octet-stream", filename=filename)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
                smtp.send_message(message)
        except OSError as exc:
            log.warning("mail delivery failed: %s", type(exc).__name__)


class CaptureMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.attachments: list[list[Attachment]] = []

    def send(self, to: str, subject: str, body: str, attachments: list[Attachment] | None = None) -> None:
        self.sent.append((to, subject, body))
        self.attachments.append(attachments or [])


def get_mailer() -> Mailer:
    return SmtpMailer()
