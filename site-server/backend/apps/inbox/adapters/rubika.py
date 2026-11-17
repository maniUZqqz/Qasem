"""Rubika bot API (`botapi.rubika.ir/v3/<token>/<method>`).

Not Telegram-shaped: every call is a JSON POST that answers
`{"status": "OK", "data": {...}}`, updates carry `type: "NewMessage"` with the
message nested in `new_message`, and ids are opaque strings (`b0...` for chats,
`u0...` for users). Two ways in, both supported:

* **webhook** - `updateBotEndpoints` with `type: "ReceiveUpdate"`; Rubika then
  POSTs `{"update": {...}}` (or `{"inline_message": {...}}`) to our URL.
* **polling** - `getUpdates` with an `offset_id` cursor; used when the store
  cannot or does not want to expose a webhook.
"""
from __future__ import annotations

import requests

from . import base
from .base import Adapter, AdapterError, Health, Incoming, PollResult, SendResult, TIMEOUT, scrub


class RubikaAdapter(Adapter):
    key = "RUBIKA"
    slug = "rubika"
    title = "روبیکا"
    host = "https://botapi.rubika.ir/v3"
    can_receive_webhook = True
    can_poll = True
    max_chars = 4096

    def _call(self, method: str, payload: dict | None = None, timeout: int = TIMEOUT, *, _probe: bool = False) -> dict:
        if not self.token:
            raise AdapterError("توکن ربات روبیکا وارد نشده است.")
        root = base.api_base_override(self.key) or self.host
        try:
            response = requests.post(
                f"{root}/{self.token}/{method}", json=payload or {}, timeout=timeout,
            )
        except requests.RequestException:
            raise AdapterError("روبیکا در دسترس نبود؛ کمی بعد دوباره امتحان کنید.") from None
        try:
            data = response.json()
        except ValueError:
            data = {}
        status = str(data.get("status", ""))
        # A wrong token comes back as HTTP 200 {"status": "INVALID_INPUT"} on
        # getMe (checked against the live service), INVALID_ACCESS elsewhere.
        if status in ("INVALID_ACCESS", "INVALID_TOKEN") or response.status_code in (401, 403) or (
            status == "INVALID_INPUT" and method == "getMe"
        ):
            raise AdapterError("توکن ربات روبیکا پذیرفته نشد.")
        if status == "INVALID_INPUT" and not _probe:
            # On every other method Rubika uses INVALID_INPUT for «the token is wrong» *and* for
            # «this chat id / text is wrong» alike. Ask getMe which one it is, so the owner is told
            # about the token only when it really is the token.
            self._call("getMe", timeout=10, _probe=True)  # raises «توکن … پذیرفته نشد» for a bad token
            raise AdapterError("روبیکا پیام را نپذیرفت: شناسهٔ گفتگو یا متن پیام نامعتبر است.")
        if response.status_code >= 400 or status != "OK":
            detail = scrub(str(data.get("dev_message") or data.get("message") or status))[:120]
            raise AdapterError(f"روبیکا درخواست را نپذیرفت ({response.status_code}): {detail}")
        return data.get("data") or {}

    def send(self, to: str, text: str) -> SendResult:
        problem = self.too_long(text)
        if problem:
            return SendResult(False, problem)
        try:
            data = self._call("sendMessage", {"chat_id": to, "text": text})
        except AdapterError as exc:
            return SendResult(False, str(exc))
        return SendResult(True, "", str(data.get("message_id", "")))

    def health(self) -> Health:
        try:
            data = self._call("getMe", timeout=10)
        except AdapterError as exc:
            return Health(False, str(exc))
        bot = data.get("bot") or data
        handle = bot.get("username") or bot.get("bot_title") or ""
        return Health(True, "ربات پاسخ می‌دهد.", f"@{handle}" if bot.get("username") else handle)

    def register_webhook(self, url: str) -> SendResult:
        try:
            self._call("updateBotEndpoints", {"url": url, "type": "ReceiveUpdate"})
        except AdapterError as exc:
            return SendResult(False, str(exc))
        return SendResult(True, "")

    def poll(self, cursor: str = "") -> PollResult:
        payload: dict = {"limit": 100}
        if cursor:
            payload["offset_id"] = cursor
        data = self._call("getUpdates", payload, timeout=20)
        messages: list[Incoming] = []
        for update in data.get("updates") or []:
            messages.extend(self.parse({"update": update}))
        return PollResult(messages, str(data.get("next_offset_id") or cursor or ""))

    def file_url(self, descriptor: dict) -> tuple[str, dict] | None:
        try:
            data = self._call("getFile", {"file_id": descriptor.get("file_id", "")}, timeout=10)
        except AdapterError:
            return None
        url = data.get("download_url")
        return (url, {}) if url else None

    def parse(self, payload: dict) -> list[Incoming]:
        update = payload.get("update")
        if update is None and payload.get("inline_message"):
            # Button callbacks are not customer messages.
            return []
        if update is None and payload.get("type"):
            update = payload  # a bare update
        update = update or {}
        if update.get("type") != "NewMessage":
            return []
        message = update.get("new_message") or {}
        if message.get("sender_type") and message["sender_type"] != "User":
            return []
        text = (message.get("text") or "").strip()
        chat_id = update.get("chat_id") or ""
        file = message.get("file") or {}
        image = None
        if file.get("file_id"):
            kind = str(file.get("type", "") or file.get("file_name", "")).lower()
            if "image" in kind or kind.endswith((".jpg", ".jpeg", ".png", ".webp")):
                image = {"kind": "rubika_file", "file_id": file["file_id"]}
        if (not text and not image) or not chat_id:
            return []
        sender = message.get("sender_id") or chat_id
        return [Incoming(
            external_id=str(message.get("message_id", "")),
            thread_id=str(chat_id),
            sender_id=str(sender),
            name="",
            text=text,
            image=image,
        )]
