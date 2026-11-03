"""Outgoing mail. Development uses a local SMTP catcher (Mailpit); tests replace the sender with a capture list."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from meridian.api.settings import get_api_settings

log = logging.getLogger("meridian.mail")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def send(self, to: str, subject: str, body: str) -> None:
        settings = get_api_settings()
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = settings.mail_from, to, subject
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
                smtp.send_message(message)
        except OSError as exc:
            log.warning("mail delivery failed: %s", type(exc).__name__)


class CaptureMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


def get_mailer() -> Mailer:
    return SmtpMailer()
