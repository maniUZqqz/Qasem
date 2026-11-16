"""SMS through the owner's paired phones (`apps.mobile`).

Sending queues a message on the phone gateway; a phone claims it and sends from
its SIM, so "delivered" here means *queued*, and the connect page says so. The
gateway already enforces opt-out lists, quiet hours and per-phone caps - this
adapter adds nothing on top and removes nothing from it.
"""
from __future__ import annotations

from .base import Adapter, Health, SendResult


class SmsAdapter(Adapter):
    key = "SMS"
    slug = "sms"
    title = "پیامک"
    needs_token = False
    can_receive_webhook = False
    can_poll = False  # inbound is pulled from the phone gateway's table, not over HTTP
    max_chars = 480

    def send(self, to: str, text: str) -> SendResult:
        problem = self.too_long(text)
        if problem:
            return SendResult(False, problem)
        from apps.mobile import sms
        from apps.mobile.base import MobileError
        from apps.mobile.models import SmsMessage

        try:
            message, _ = sms.enqueue(to, text, kind=SmsMessage.Kind.TRANSACTIONAL)
        except MobileError as exc:
            return SendResult(False, exc.message)
        return SendResult(True, "", str(message.uid))

    def health(self) -> Health:
        from apps.inbox import sms_gateway

        store = getattr(self.connection, "store", None)
        info = sms_gateway.status(store) if store is not None else {"online": 0}
        if info["paused"]:
            return Health(False, "صفِ پیامک از بخش موبایل متوقف شده است.")
        if not info["online"]:
            return Health(False, "هیچ گوشی پیامکی آنلاین نیست.")
        return Health(True, f"{info['online']} گوشی آنلاین است.")
