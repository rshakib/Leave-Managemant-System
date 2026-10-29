"""Email backends behind one tiny interface (DECISIONS D-19).

`console`  — prints recipients, subject and body to the log (development)
`file`     — writes one .eml per message into EMAIL_FILE_DIR (development/tests)
`smtp`     — real SMTP via smtplib in a thread (never used in this phase)
"""

import logging
import smtplib
import ssl
import threading
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings
from app.services.email_rules import sanitize_header

logger = logging.getLogger(__name__)


class MailerError(RuntimeError):
    """Raised when a message could not be sent."""


@dataclass(frozen=True)
class Message:
    to: list[str]
    cc: list[str] = field(default_factory=list)
    subject: str = ""
    text: str = ""
    html: str = ""


def validate_config() -> None:
    """Called by the worker at startup."""
    backend = settings.email_backend.lower()
    if backend not in ("console", "file", "smtp"):
        raise MailerError(
            f"Unknown EMAIL_BACKEND '{settings.email_backend}' "
            "(use console, file or smtp)."
        )
    if backend == "smtp" and not settings.smtp_host:
        raise MailerError("EMAIL_BACKEND=smtp but SMTP_HOST is empty.")


def _build(message: Message) -> EmailMessage:
    email = EmailMessage()
    # Every header goes through sanitize_header: user text must never be able to
    # inject a new header (e.g. a name containing "\r\nBcc: ...").
    email["Subject"] = sanitize_header(message.subject)
    email["From"] = sanitize_header(settings.email_from)
    email["To"] = ", ".join(sanitize_header(address) for address in message.to)
    if message.cc:
        email["Cc"] = ", ".join(sanitize_header(address) for address in message.cc)
    email.set_content(message.text)
    email.add_alternative(message.html, subtype="html")
    return email


def _send_console(email: EmailMessage) -> None:
    logger.info(
        "EMAIL (console) to=%s cc=%s subject=%s",
        email.get("To"),
        email.get("Cc") or "-",
        email.get("Subject"),
    )
    body = email.get_body(preferencelist=("plain",))
    if body is not None:
        logger.info("EMAIL body:\n%s", body.get_content())


def _send_file(email: EmailMessage) -> None:
    directory = settings.email_outbox_dir
    directory.mkdir(parents=True, exist_ok=True)
    # The filename is random and never built from user input.
    path = directory / f"{uuid.uuid4().hex}.eml"
    path.write_bytes(bytes(email))


def _smtp_target() -> tuple[str, int]:
    return settings.smtp_host, settings.smtp_port


def _send_smtp(email: EmailMessage) -> None:
    host, port = _smtp_target()
    if not host:
        raise MailerError("EMAIL_BACKEND=smtp but SMTP_HOST is empty.")

    failures: list[BaseException] = []

    def deliver() -> None:
        try:
            if settings.smtp_ssl:
                client = smtplib.SMTP_SSL(host, port, timeout=15,
                                       context=ssl.create_default_context())
            else:
                client = smtplib.SMTP(host, port, timeout=15)
            with client:
                if settings.smtp_starttls and not settings.smtp_ssl:
                    client.starttls(context=ssl.create_default_context())
                if settings.smtp_user:
                    client.login(settings.smtp_user, settings.smtp_password)
                client.send_message(email)
        except BaseException as exc:  # noqa: BLE001 - reported to the caller
            failures.append(exc)

    thread = threading.Thread(target=deliver, daemon=True)
    thread.start()
    thread.join(timeout=20)
    if thread.is_alive():
        raise MailerError("SMTP send timed out after 20 seconds.")
    if failures:
        raise failures[0]


def send(message: Message) -> str:
    """Send one message; returns the backend name used."""
    validate_config()
    backend = settings.email_backend.lower()
    email = _build(message)

    if backend == "console":
        _send_console(email)
    elif backend == "file":
        _send_file(email)
    else:
        _send_smtp(email)
    return backend
