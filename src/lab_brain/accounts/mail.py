"""Sending account mail: verification and password-reset links, and approval notices.

FAILS CLOSED. With no mailer configured, nothing that needs a message can happen: registration and
password reset are refused, with a message saying an administrator must configure mail. Nothing is
silently dropped and no link is shown in the browser in its place.

    SmtpMailer      an SMTP server named by the deployment (`LAB_BRAIN_SMTP_*`), over TLS --
                    STARTTLS, or implicit TLS on port 465; credentials from a file, never the
                    environment's value itself
    OutboxMailer    writes each message to a directory as an .eml file: for a deployment that has
                    no mail server yet and an operator who forwards links by hand, and for local
                    testing; it must be named explicitly (`--mail-outbox`)
    MemoryMailer    the tests'
"""

from __future__ import annotations

import os
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Protocol


class MailUnavailable(Exception):
    """No mailer is configured, or the configured one could not send. Nothing was sent."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, message: Message) -> None: ...


def _email(sender: str, message: Message) -> EmailMessage:
    out = EmailMessage()
    out["From"] = sender
    out["To"] = message.to
    out["Subject"] = message.subject
    out["Date"] = formatdate(localtime=False)
    out["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1] if "@" in sender else None)
    out.set_content(message.body)
    return out


@dataclass(frozen=True)
class SmtpMailer:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = None
    #: STARTTLS on a plain port (587), or implicit TLS (465). A mailer without TLS is refused.
    implicit_tls: bool = False
    timeout: float = 15.0

    def send(self, message: Message) -> None:
        context = ssl.create_default_context()
        try:
            if self.implicit_tls:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout, context=context
                )
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with client:
                if not self.implicit_tls:
                    client.starttls(context=context)
                if self.username:
                    client.login(self.username, self.password or "")
                client.send_message(_email(self.sender, message))
        except (OSError, smtplib.SMTPException) as failed:
            raise MailUnavailable(f"the mail server did not accept the message: {failed}") from None


@dataclass
class OutboxMailer:
    directory: Path
    sender: str = "lab-brain@localhost"

    def send(self, message: Message) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        mail = _email(self.sender, message)
        name = str(mail["Message-ID"]).strip("<>").replace("@", "_").replace("/", "_")
        path = self.directory / f"{name}.eml"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(mail.as_bytes())


@dataclass
class MemoryMailer:
    sent: list[Message] = field(default_factory=list)

    def send(self, message: Message) -> None:
        self.sent.append(message)


def mailer_from(env: Mapping[str, str], *, outbox: Path | None = None) -> Mailer | None:
    """The deployment's mailer, or None (mail fails closed).

    `LAB_BRAIN_SMTP_HOST`, `_PORT` (587; 465 means implicit TLS), `_FROM`, `_USERNAME` and
    `_PASSWORD_FILE`. An explicit outbox directory is used only when no SMTP host is named.
    """
    host = env.get("LAB_BRAIN_SMTP_HOST", "").strip()
    if host:
        sender = env.get("LAB_BRAIN_SMTP_FROM", "").strip()
        if "@" not in sender:
            raise ValueError("LAB_BRAIN_SMTP_FROM must name the sending address")
        port = int(env.get("LAB_BRAIN_SMTP_PORT", "587") or "587")
        password = None
        secret = env.get("LAB_BRAIN_SMTP_PASSWORD_FILE", "").strip()
        if secret:
            password = Path(secret).read_text(encoding="utf-8").strip()
        return SmtpMailer(
            host=host,
            port=port,
            sender=sender,
            username=env.get("LAB_BRAIN_SMTP_USERNAME", "").strip() or None,
            password=password,
            implicit_tls=port == 465,
        )
    if outbox is not None:
        return OutboxMailer(outbox)
    return None
