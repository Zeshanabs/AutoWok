"""Outgoing email over SMTP (standard library only).

Email is optional. With ``SMTP_HOST`` empty nothing is sent and callers are
told so, which lets them fall back to showing a link the user can pass on.
Error messages never contain the SMTP password.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailError(RuntimeError):
    """The message could not be handed to the mail server."""


def email_configured() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host.strip() and settings.smtp_from.strip())


def _clean_header(value: str) -> str:
    # A line break in a header would let a caller inject extra headers.
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def send_email(*, to: str, subject: str, text: str, html: str | None = None) -> None:
    """Send one message. Raises ``EmailError`` when email is off or sending fails."""
    settings = get_settings()
    if not email_configured():
        raise EmailError("Email is not configured. Set SMTP_HOST and SMTP_FROM.")
    recipient = parseaddr(_clean_header(to))[1]
    if not recipient or "@" not in recipient:
        raise EmailError("The recipient address is not valid.")
    sender_name, sender_address = parseaddr(_clean_header(settings.smtp_from))
    if not sender_address:
        raise EmailError("SMTP_FROM is not a valid address.")

    message = EmailMessage()
    message["From"] = formataddr((sender_name or "Autowok", sender_address))
    message["To"] = recipient
    message["Subject"] = _clean_header(subject)[:200]
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")

    host = settings.smtp_host.strip()
    timeout = settings.smtp_timeout_seconds
    try:
        if settings.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, settings.smtp_port, timeout=timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, settings.smtp_port, timeout=timeout)
        with server:
            if settings.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if settings.smtp_username.strip():
                server.login(settings.smtp_username.strip(), settings.smtp_password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        logger.warning("smtp authentication failed", extra={"smtp_host": host})
        raise EmailError("The mail server rejected the SMTP username or password.") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise EmailError("The mail server refused the recipient address.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("smtp send failed", extra={"smtp_host": host, "error_type": type(exc).__name__})
        raise EmailError("The mail server could not be reached or refused the message.") from exc
