"""The e-mail channel: one message per approved item through the operator's own SMTP account.

* the account (host, port, security, user, from, reply-to) comes from the panel, falling back to the server's ``EMAIL_*``;
  the password is never returned or logged;
* every message carries the sender block and the opt-out line (added by the system, ``rendering.compose``), a ``Reply-To`` that
  is the operator's own address (replies reach a person) and a ``List-Unsubscribe`` header;
* a message is handed to the server ONCE: no retry, ever (a timed-out SMTP session may have delivered it);
* ``verify`` only opens a session and logs in: it sends nothing.

The mail backend class comes from ``GROWTH_ENGINE["EMAIL_BACKEND"]`` (default SMTP) so tests run on the in-memory backend and no test
ever reaches a real server.
"""
from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.utils import formataddr
from urllib.parse import quote

from django.core.mail import EmailMessage, get_connection

from apps.growth_engine.core import conf
from apps.growth_engine.core import normalization as nz

from ..models import Channel
from ..services import channel_config
from . import targets

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    ok: bool
    code: str = ""  # "" on success, else a stable code
    text: str = ""  # Persian explanation
    detail: str = ""  # what the server said on success (short)


def _connection(cfg: dict):
    return get_connection(
        backend=conf.get("EMAIL_BACKEND"), host=cfg["host"], port=cfg["port"], username=cfg["username"] or None, password=cfg["password"] or None,
        use_tls=cfg["security"] == "starttls", use_ssl=cfg["security"] == "ssl", timeout=cfg["timeout"], fail_silently=False,
    )


def prepare(item, growth) -> dict:
    """The dry run of an e-mail item: who, from where, and every reason it cannot be sent (nothing is contacted)."""
    problems: list[str] = []
    target = targets.resolve(item.lead, Channel.EMAIL)
    recipient = item.recipient or (target.recipient if target else "")
    if not recipient:
        problems.append(targets.no_target(Channel.EMAIL)[1])
    problems += channel_config.email_problems()
    if not (item.subject or "").strip():
        problems.append("موضوعِ ایمیل خالی است.")
    cfg = channel_config.smtp_settings()
    return {
        "channel": Channel.EMAIL, "ok": not problems, "problems": problems, "recipient": recipient,
        "from": cfg["from_email"], "reply_to": cfg["reply_to"],
        "material": {"from": cfg["from_email"], "reply_to": cfg["reply_to"]},
    }


def build_message(item, cfg: dict | None = None) -> EmailMessage:
    cfg = cfg or channel_config.smtp_settings()
    subject = nz.normalize_text(item.subject or "")
    reply_to = cfg["reply_to"]
    headers = {"X-Mailer": "NMarketing Growth Engine"}
    if reply_to:
        headers["List-Unsubscribe"] = f"<mailto:{reply_to}?subject={quote('لغو')}>"
    return EmailMessage(
        subject=subject, body=item.rendered_text, from_email=formataddr((cfg["from_name"], cfg["from_email"])) if cfg["from_name"] else cfg["from_email"],
        to=[item.recipient], reply_to=[reply_to] if reply_to else None, headers=headers,
    )


def send(item) -> SendResult:
    """Hand ``item``'s message to the mail server once. Never raises for a mail problem."""
    cfg = channel_config.smtp_settings()
    try:
        message = build_message(item, cfg)
        message.connection = _connection(cfg)
        sent = message.send(fail_silently=False)
    except smtplib.SMTPAuthenticationError:
        return SendResult(False, "auth_failed", "سرورِ ایمیل نامِ کاربری یا رمز را نپذیرفت.")
    except smtplib.SMTPRecipientsRefused:
        return SendResult(False, "recipient_refused", "سرورِ ایمیل نشانیِ گیرنده را نپذیرفت.")
    except smtplib.SMTPSenderRefused:
        return SendResult(False, "sender_refused", "سرورِ ایمیل نشانیِ فرستنده (From) را نپذیرفت؛ باید نشانیِ مجازِ همین حساب باشد.")
    except smtplib.SMTPDataError as exc:
        return SendResult(False, "data_refused", f"سرورِ ایمیل متن را نپذیرفت (کد {exc.smtp_code}).")
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError):
        return SendResult(False, "disconnected", "اتصال به سرورِ ایمیل قطع شد؛ معلوم نیست ایمیل رفته یا نه.")
    except (socket.timeout, TimeoutError):
        return SendResult(False, "timeout", "سرورِ ایمیل جواب نداد؛ معلوم نیست ایمیل رفته یا نه.")
    except ssl.SSLError:
        return SendResult(False, "tls_error", "رمزگذاریِ اتصال به سرورِ ایمیل برقرار نشد (نوعِ رمزگذاری یا پورت را بررسی کنید).")
    except smtplib.SMTPException as exc:
        return SendResult(False, "smtp_error", f"خطای سرورِ ایمیل ({type(exc).__name__}).")
    except OSError:
        return SendResult(False, "connect_error", "به سرورِ ایمیل وصل نشد (نشانی یا پورت را بررسی کنید).")
    if not sent:
        return SendResult(False, "not_sent", "سرورِ ایمیل پیام را نپذیرفت.")
    return SendResult(True, detail="سرورِ ایمیل پیام را پذیرفت.")


def verify() -> tuple[bool, str]:
    """Open a session and log in - nothing is sent. Returns (ok, Persian message)."""
    problems = channel_config.email_problems()
    if problems:
        return False, " ".join(problems)
    cfg = channel_config.smtp_settings()
    connection = _connection(cfg)
    try:
        connection.open()
    except smtplib.SMTPAuthenticationError:
        return False, "سرورِ ایمیل نامِ کاربری یا رمز را نپذیرفت."
    except ssl.SSLError:
        return False, "رمزگذاریِ اتصال برقرار نشد (نوعِ رمزگذاری یا پورت را بررسی کنید)."
    except (socket.timeout, TimeoutError):
        return False, "سرورِ ایمیل جواب نداد."
    except smtplib.SMTPException as exc:
        return False, f"خطای سرورِ ایمیل ({type(exc).__name__})."
    except OSError:
        return False, "به سرورِ ایمیل وصل نشد (نشانی یا پورت را بررسی کنید)."
    finally:
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - closing a half-open session must not hide the real answer
            pass
    return True, "اتصال و ورود به سرورِ ایمیل درست است (ایمیلی فرستاده نشد)."
