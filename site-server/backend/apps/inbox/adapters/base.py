"""The small contract every messaging channel keeps.

One adapter per platform, and the rest of the inbox (assignment, SLA, bot,
broadcast) never learns what a platform is: it asks an adapter to `send`,
`parse` a webhook body, `poll` for updates, or report `health`.

Why plain classes and not a plugin framework: there are about eight channels,
each with a different wire format, and the only thing they share is the four
verbs below. A registry dict is the whole "framework".

**Tokens never leave this layer.** A `requests` error quotes the URL, and for
Telegram/Bale/Eitaa/Rubika the URL *is* the bot token. Every adapter therefore
catches transport errors and returns a sentence that names the platform and the
symptom, never the exception text (same rule `services.publishing.channels`
already follows for Telegram).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.conf import settings

#: Seconds a platform call may take. The inbox sends from a request thread, so
#: this must stay well under a gunicorn timeout.
TIMEOUT = 15


class AdapterError(Exception):
    """A platform call failed. The message is already safe to show."""


@dataclass
class Incoming:
    """One message from a customer, platform-neutral."""

    external_id: str
    thread_id: str
    sender_id: str
    name: str = ""
    username: str = ""
    phone: str = ""
    text: str = ""
    #: {"kind": "telegram_file"|"url"|"rubika_file", ...} — a descriptor, not
    #: bytes; fetching is a network call and the webhook has seconds to answer.
    image: dict | None = None


@dataclass
class SendResult:
    ok: bool
    reason: str = ""
    external_id: str = ""

    def as_dict(self) -> dict:
        return {"sent": self.ok, "reason": self.reason, "external_id": self.external_id}


@dataclass
class Health:
    """What the connect page shows next to a channel."""

    ok: bool
    detail: str = ""
    #: The bot's own display name / username, when the platform tells us.
    account: str = ""


@dataclass
class PollResult:
    messages: list[Incoming] = field(default_factory=list)
    cursor: str = ""


def api_base_override(key: str) -> str:
    """A test or on-premise override of a platform's API root.

    Read from settings, never from the connection row: a store owner who could
    point `api_base` anywhere would turn the poller into an SSRF probe against
    the server's own network.
    """
    table = getattr(settings, "INBOX_API_BASES", None) or {}
    return str(table.get(key, "") or "").rstrip("/")


_TOKEN_RE = re.compile(r"[A-Za-z0-9:_\-]{20,}")


def scrub(text: str) -> str:
    """Remove anything that looks like a bot token from a string."""
    return _TOKEN_RE.sub("***", text or "")


class Adapter:
    """Base class. Subclasses override what their platform supports."""

    #: Channel key stored on `Conversation.channel` — upper case.
    key = ""
    #: URL segment of the inbound webhook and key in the registry.
    slug = ""
    title = ""
    #: Can a store connect it by pasting a token?
    needs_token = True
    can_receive_webhook = False
    can_poll = False
    can_send = True
    max_chars: int | None = None
    #: The platform's API host as seen from an Iranian server, and whether that server can
    #: normally reach it at all. Telegram is filtered: neither its webhook nor polling can
    #: work from such a server, and the connect page must say so instead of «در دسترس نبود».
    host = ""
    blocked_from_iran = False
    #: Appended to «not reachable» errors - what the owner can do about it.
    unreachable_hint = ""
    #: The routing-table service of ``apps.egress`` that carries this platform's API calls: the owner can send exactly that service through
    #: a proxy / VPN (panel › ابزارها › پراکسی و VPN). "" = an Iranian / local service: always direct, never routable.
    egress_service = ""

    def __init__(self, connection=None):
        self.connection = connection

    # -- what a subclass fills in -------------------------------------------
    def send(self, to: str, text: str) -> SendResult:  # pragma: no cover
        raise NotImplementedError

    def parse(self, payload: dict) -> list[Incoming]:
        return []

    def poll(self, cursor: str = "") -> PollResult:
        return PollResult()

    def health(self) -> Health:  # pragma: no cover
        raise NotImplementedError

    def register_webhook(self, url: str) -> SendResult:
        return SendResult(False, "این کانال وب‌هوک ندارد.")

    def verify(self, body: bytes, headers) -> bool:
        """The platform's own signature check. Default: the URL secret is it."""
        return True

    def file_url(self, descriptor: dict) -> tuple[str, dict] | None:
        """Where to download an attachment this platform described: (url, headers).

        Resolved lazily - a webhook has seconds to answer, so `parse` only records
        *which* file; the receipt flow asks for the address afterwards. None means
        this platform cannot hand the file out (the owner is told to open the chat).
        """
        return None

    # -- helpers ------------------------------------------------------------
    @property
    def token(self) -> str:
        return (getattr(self.connection, "token", "") or "").strip()

    @property
    def config(self) -> dict:
        return getattr(self.connection, "config", None) or {}

    def too_long(self, text: str) -> str:
        if self.max_chars and len(text) > self.max_chars:
            return f"پیام از سقف {self.max_chars} کاراکترِ {self.title} بلندتر است."
        return ""
