"""WhatsApp Business Cloud API (Meta) - OFF by default.

WhatsApp has no free bot API: it needs an official Business account with a
verified number, a Meta app, and a permanent access token. None of that can be
created by us, so this adapter ships switched off (`enabled=False` on the
connection) and the connect page says exactly what the owner has to bring.

Wire format (Cloud API):
  inbound  POST  {"entry":[{"changes":[{"value":{"contacts":[{"profile":{"name"},"wa_id"}],
                  "messages":[{"from","id","type":"text","text":{"body"}}]}}]}]}
  outbound POST  https://graph.facebook.com/<ver>/<phone_number_id>/messages
                  {"messaging_product":"whatsapp","to":<wa_id>,"type":"text","text":{"body"}}
  handshake GET  hub.mode=subscribe&hub.verify_token&hub.challenge
  signature header  X-Hub-Signature-256: sha256=<hmac(app_secret, body)>

Note: this is *not* the `entry[].messaging[]` envelope Instagram uses, which is
why `apps.customers.webhooks._meta` cannot parse it.
"""
from __future__ import annotations

import hashlib
import hmac

import requests

from services import egress

from . import base
from .base import Adapter, AdapterError, Health, Incoming, SendResult, TIMEOUT, scrub

GRAPH_VERSION = "v20.0"


class WhatsAppAdapter(Adapter):
    key = "WHATSAPP"
    slug = "whatsapp"
    title = "واتساپ"
    host = "https://graph.facebook.com"
    #: the routing-table service of apps.egress (graph.facebook.com is filtered from Iran: the owner may route it through a proxy)
    egress_service = "whatsapp"
    can_receive_webhook = True
    can_poll = False
    max_chars = 4096

    @property
    def phone_id(self) -> str:
        return str(self.config.get("phone_number_id", "") or "").strip()

    @property
    def app_secret(self) -> str:
        return str(self.config.get("app_secret", "") or "").strip()

    def _root(self) -> str:
        return base.api_base_override(self.key) or self.host

    def send(self, to: str, text: str) -> SendResult:
        problem = self.too_long(text)
        if problem:
            return SendResult(False, problem)
        if not (self.token and self.phone_id):
            return SendResult(False, "واتساپ تنظیم نشده: توکن و شناسهٔ شمارهٔ واتساپ بیزینس لازم است.")
        try:
            response = egress.post(
                self.egress_service, f"{self._root()}/{GRAPH_VERSION}/{self.phone_id}/messages",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "messaging_product": "whatsapp", "to": to,
                    "type": "text", "text": {"body": text},
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            return SendResult(False, egress.reason(exc) or "واتساپ در دسترس نبود؛ کمی بعد دوباره امتحان کنید.")
        if response.status_code >= 400:
            try:
                detail = scrub(str((response.json().get("error") or {}).get("message", "")))[:120]
            except ValueError:
                detail = ""
            return SendResult(False, f"واتساپ پیام را نپذیرفت ({response.status_code}) {detail}".strip())
        try:
            mid = ((response.json().get("messages") or [{}])[0]).get("id", "")
        except ValueError:
            mid = ""
        return SendResult(True, "", str(mid))

    def health(self) -> Health:
        if not (self.token and self.phone_id):
            return Health(False, "توکن یا شناسهٔ شمارهٔ واتساپ بیزینس وارد نشده است.")
        try:
            response = egress.get(
                self.egress_service, f"{self._root()}/{GRAPH_VERSION}/{self.phone_id}",
                headers={"Authorization": f"Bearer {self.token}"},
                params={"fields": "display_phone_number,verified_name"},
                timeout=10,
            )
        except requests.RequestException as exc:
            return Health(False, egress.reason(exc) or "واتساپ در دسترس نبود.")
        if response.status_code >= 400:
            return Health(False, f"توکن یا شناسهٔ شماره پذیرفته نشد ({response.status_code}).")
        data = response.json()
        return Health(True, "حساب واتساپ بیزینس پاسخ می‌دهد.", data.get("display_phone_number", ""))

    def verify(self, body: bytes, headers) -> bool:
        if not self.app_secret:
            return False  # unsigned payloads on an unconfigured channel are probes
        header = headers.get("X-Hub-Signature-256", "")
        if not header.startswith("sha256="):
            return False
        digest = hmac.new(self.app_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(header[7:], digest)

    def file_url(self, descriptor: dict) -> tuple[str, dict] | None:
        media_id = descriptor.get("id")
        if not (media_id and self.token):
            return None
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = egress.get(self.egress_service, f"{self._root()}/{GRAPH_VERSION}/{media_id}", headers=headers, timeout=10)
            url = response.json().get("url") if response.status_code < 400 else None
        except (requests.RequestException, ValueError):
            return None
        return (url, headers) if url else None

    def handshake(self, query) -> str | None:
        """The challenge to echo for Meta's subscription GET, or None to refuse."""
        expected = str(self.config.get("verify_token", "") or "")
        if query.get("hub.mode") == "subscribe" and expected and hmac.compare_digest(
            str(query.get("hub.verify_token", "")), expected
        ):
            return str(query.get("hub.challenge", ""))
        return None

    def parse(self, payload: dict) -> list[Incoming]:
        out: list[Incoming] = []
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                names = {
                    c.get("wa_id"): (c.get("profile") or {}).get("name", "")
                    for c in value.get("contacts") or []
                }
                for msg in value.get("messages") or []:
                    sender = str(msg.get("from", ""))
                    if not sender:
                        continue
                    kind = msg.get("type")
                    text = ""
                    image = None
                    if kind == "text":
                        text = ((msg.get("text") or {}).get("body") or "").strip()
                    elif kind == "image":
                        image = {"kind": "whatsapp_media", "id": (msg.get("image") or {}).get("id", "")}
                        text = ((msg.get("image") or {}).get("caption") or "").strip()
                    elif kind == "button":
                        text = ((msg.get("button") or {}).get("text") or "").strip()
                    if not text and not image:
                        continue
                    out.append(Incoming(
                        external_id=str(msg.get("id", "")),
                        thread_id=sender,
                        sender_id=sender,
                        name=names.get(sender, ""),
                        phone=sender,
                        text=text,
                        image=image,
                    ))
        return out
