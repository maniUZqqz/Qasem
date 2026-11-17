"""Telegram-shaped bot APIs: Telegram itself and Bale.

Bale deliberately copied Telegram's Bot API (same method names, same update
JSON, only the host differs: `tapi.bale.ai`), so one class serves both and a
platform is a three-line subclass. Eitaa and Rubika are *not* in here: their
bot APIs have their own shapes (see `eitaa.py`, `rubika.py`).

The parser is the same one `apps.customers.webhooks` uses for Telegram, on
purpose: a thread that arrives through the polling path and one that arrives
through the webhook must be indistinguishable, or the same customer would be
two people depending on how the message got here.
"""
from __future__ import annotations

import requests

from . import base
from .base import Adapter, AdapterError, Health, Incoming, PollResult, SendResult, TIMEOUT, scrub


class TelegramCompat(Adapter):
    """`https://<host>/bot<token>/<method>` JSON bot API."""

    key = "TELEGRAM"
    slug = "telegram"
    title = "تلگرام"
    host = "https://api.telegram.org"
    can_receive_webhook = True
    can_poll = True
    max_chars = 4096
    #: Telegram echoes a secret header on each webhook call; Bale does not.
    secret_header = "X-Telegram-Bot-Api-Secret-Token"
    #: Names the platform in an image descriptor, so the receipt flow asks the
    #: right platform for the file (a Bale file id sent to Telegram is nonsense).
    file_kind = "telegram_file"

    def _root(self) -> str:
        return base.api_base_override(self.key) or self.host

    def _url(self, method: str) -> str:
        return f"{self._root()}/bot{self.token}/{method}"

    def _call(self, method: str, payload: dict | None = None, timeout: int = TIMEOUT) -> dict:
        if not self.token:
            raise AdapterError(f"توکن ربات {self.title} وارد نشده است.")
        try:
            response = requests.post(self._url(method), json=payload or {}, timeout=timeout)
        except requests.RequestException:
            raise AdapterError(f"{self.title} در دسترس نبود؛ کمی بعد دوباره امتحان کنید.{self.unreachable_hint}") from None
        try:
            data = response.json()
        except ValueError:
            data = {}
        # Bale answers a bad token with HTTP 401; Eitaa Yar answers HTTP 200 with
        # the same error *inside* the body. Both mean "this token is not valid".
        error_code = data.get("error_code") if isinstance(data, dict) else None
        if response.status_code == 401 or error_code == 401 or (response.status_code == 404 and not data):
            raise AdapterError(f"توکن ربات {self.title} پذیرفته نشد.")
        if response.status_code >= 400 or not data.get("ok", False):
            detail = scrub(str(data.get("description", "") or ""))[:120]
            raise AdapterError(
                f"{self.title} درخواست را نپذیرفت ({error_code or response.status_code})"
                + (f": {detail}" if detail else "")
            )
        return data

    # -- verbs ----------------------------------------------------------
    def send(self, to: str, text: str) -> SendResult:
        problem = self.too_long(text)
        if problem:
            return SendResult(False, problem)
        try:
            data = self._call("sendMessage", {"chat_id": to, "text": text})
        except AdapterError as exc:
            return SendResult(False, str(exc))
        mid = ((data.get("result") or {}).get("message_id")) or ""
        return SendResult(True, "", str(mid))

    def health(self) -> Health:
        try:
            data = self._call("getMe", timeout=10)
        except AdapterError as exc:
            return Health(False, str(exc))
        me = data.get("result") or {}
        handle = me.get("username") or me.get("first_name") or ""
        return Health(True, "ربات پاسخ می‌دهد.", f"@{handle}" if me.get("username") else handle)

    def register_webhook(self, url: str) -> SendResult:
        payload = {"url": url}
        if self.secret_header and self.connection is not None and getattr(self.connection, "secret", ""):
            payload["secret_token"] = self.connection.secret
        try:
            self._call("setWebhook", payload)
        except AdapterError as exc:
            return SendResult(False, str(exc))
        return SendResult(True, "")

    def clear_webhook(self) -> SendResult:
        try:
            self._call("deleteWebhook")
        except AdapterError as exc:
            return SendResult(False, str(exc))
        return SendResult(True, "")

    def verify(self, body: bytes, headers) -> bool:
        import hmac

        if not self.secret_header:
            return True
        expected = getattr(self.connection, "secret", "") or ""
        got = headers.get(self.secret_header, "")
        # A Telegram webhook registered by *us* always carries the header. One
        # registered by hand without it cannot be told from a forgery, so it is
        # refused: the URL secret alone is not enough for the platform that
        # offers a second factor.
        return bool(got) and hmac.compare_digest(got, expected)

    def poll(self, cursor: str = "") -> PollResult:
        payload = {"timeout": 0, "limit": 100, "allowed_updates": ["message", "edited_message"]}
        if cursor:
            try:
                payload["offset"] = int(cursor)
            except ValueError:
                pass
        data = self._call("getUpdates", payload, timeout=20)
        updates = data.get("result") or []
        out: list[Incoming] = []
        next_offset = cursor
        for update in updates:
            out.extend(self.parse(update))
            try:
                next_offset = str(max(int(next_offset or 0), int(update["update_id"]) + 1))
            except (KeyError, TypeError, ValueError):
                pass
        return PollResult(out, next_offset)

    # -- parsing --------------------------------------------------------
    def parse(self, payload: dict) -> list[Incoming]:
        message = payload.get("message") or payload.get("edited_message") or {}
        text = (message.get("text") or message.get("caption") or "").strip()
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        image = self._image(message)
        contact = message.get("contact") or {}
        if (not text and not image and not contact) or not chat.get("id"):
            return []
        # Groups and channels are not customers: a bot added to a group would
        # otherwise turn every member's chatter into an "unanswered customer".
        if chat.get("type") and chat["type"] != "private":
            return []
        if sender.get("is_bot"):
            return []
        name = " ".join(p for p in (sender.get("first_name"), sender.get("last_name")) if p)
        # A phone number arrives only when the customer shares a contact card.
        phone = contact.get("phone_number", "") if contact else ""
        if not text and contact:
            text = "[مخاطب]"
        return [Incoming(
            external_id=str(message.get("message_id", "")),
            thread_id=str(chat["id"]),
            sender_id=str(sender.get("id") or chat["id"]),
            name=name or sender.get("username", ""),
            username=sender.get("username", "") or "",
            phone=phone,
            text=text,
            image=image,
        )]

    def _image(self, message: dict) -> dict | None:
        photos = message.get("photo") or []
        if photos and photos[-1].get("file_id"):
            return {"kind": self.file_kind, "file_id": photos[-1]["file_id"]}
        document = message.get("document") or {}
        if document.get("file_id") and str(document.get("mime_type", "")).startswith("image/"):
            return {"kind": self.file_kind, "file_id": document["file_id"]}
        return None

    def file_url(self, descriptor: dict) -> tuple[str, dict] | None:
        try:
            data = self._call("getFile", {"file_id": descriptor.get("file_id", "")}, timeout=10)
        except AdapterError:
            return None
        path = (data.get("result") or {}).get("file_path")
        if not path:
            return None
        return f"{self._root()}/file/bot{self.token}/{path}", {}


class TelegramAdapter(TelegramCompat):
    key = "TELEGRAM"
    slug = "telegram"
    title = "تلگرام"
    host = "https://api.telegram.org"
    blocked_from_iran = True
    unreachable_hint = (
        " اگر این سرور در ایران است، تلگرام معمولاً از آن در دسترس نیست (نه وب‌هوک کار می‌کند نه پرسش دوره‌ای)؛"
        " بله، ایتا یا روبیکا را وصل کنید."
    )


class BaleAdapter(TelegramCompat):
    """Bale's Bot API (`tapi.bale.ai`) — Telegram's JSON, a different host."""

    key = "BALE"
    slug = "bale"
    title = "بله"
    host = "https://tapi.bale.ai"
    file_kind = "bale_file"
    max_chars = 4096
    # Bale does not echo a secret header; the per-connection secret in the URL
    # is the only check available, and it is 24 random bytes.
    secret_header = ""
