"""Eitaa bot API (Eitaa Yar - `eitaayar.ir/api/<token>/<method>`).

What was checked against the live service (a wrong token, no account needed):
the envelope is Telegram's - `{"ok": false, "error_code": 401, "description":
"Unauthorized"}` - but it comes back with HTTP 200, and there is no `bot`
prefix in the path. Everything else follows Eitaa Yar's public documentation:

* `getMe`, `sendMessage` (needs `chat_id`, `text`, and a `title` that Eitaa
  shows above the message), `sendFile`;
* receiving is Eitaa Yar's own `setWebhook` / `getUpdates`, which not every bot
  plan enables.

Because the receive half is plan-dependent, the connect page does not promise
it: `health()` reports sending separately from receiving
(`config["receive_ok"]`), and a bot that can only send is shown as "فقط ارسال"
with the reason, instead of a green tick that never delivers a customer.
"""
from __future__ import annotations

from . import base
from .base import AdapterError, Health, SendResult
from .tgcompat import TelegramCompat


class EitaaAdapter(TelegramCompat):
    key = "EITAA"
    slug = "eitaa"
    title = "ایتا"
    host = "https://eitaayar.ir/api"
    max_chars = 4096
    secret_header = ""
    file_kind = "eitaa_file"

    def file_url(self, descriptor: dict):
        # Eitaa Yar documents no way to download what a user sent; say so instead of guessing.
        return None

    def _url(self, method: str) -> str:
        return f"{self._root()}/{self.token}/{method}"

    def send(self, to: str, text: str) -> SendResult:
        problem = self.too_long(text)
        if problem:
            return SendResult(False, problem)
        title = str(self.config.get("message_title", "") or "پاسخ پشتیبانی")[:60]
        try:
            data = self._call("sendMessage", {"chat_id": to, "title": title, "text": text})
        except AdapterError as exc:
            return SendResult(False, str(exc))
        result = data.get("result") or {}
        return SendResult(True, "", str(result.get("message_id", "")))

    def health(self) -> Health:
        base_health = super().health()
        if not base_health.ok:
            return base_health
        # Probe the receive half once; a bot without it is still a fine sender.
        try:
            self._call("getUpdates", {"limit": 1, "timeout": 0}, timeout=10)
        except AdapterError as exc:
            return Health(
                True,
                "ارسال پیام فعال است؛ دریافت پیام برای این ربات فعال نیست "
                "(در ایتایار، دریافت پیام را برای ربات روشن کنید). " + str(exc)[:80],
                base_health.account,
            )
        return Health(True, "ارسال و دریافت فعال است.", base_health.account)


def probe_receive(adapter: EitaaAdapter) -> bool:
    try:
        adapter._call("getUpdates", {"limit": 1, "timeout": 0}, timeout=10)
        return True
    except AdapterError:
        return False


__all__ = ["EitaaAdapter", "probe_receive", "base"]
