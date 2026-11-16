"""Site-chat widget: nothing to deliver.

The visitor's browser polls `/widget/<key>/messages/`, so the stored message row
*is* the delivery. The adapter exists so `send` has one shape on every channel
and so a switched-off widget refuses replies like any other channel does.
"""
from __future__ import annotations

from .base import Adapter, Health, SendResult


class WebchatAdapter(Adapter):
    key = "WEBCHAT"
    slug = "webchat"
    title = "چت سایت"
    needs_token = False
    can_receive_webhook = False
    can_poll = False
    max_chars = 4000

    def send(self, to: str, text: str) -> SendResult:
        problem = self.too_long(text)
        return SendResult(False, problem) if problem else SendResult(True, "")

    def health(self) -> Health:
        return Health(True, "ویجت آماده است.")
