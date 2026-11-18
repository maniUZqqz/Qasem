"""A changed proxy or route must take effect now: drop the cached table, and forget the inbox's «can this server reach Telegram?»
answer (it is cached for minutes and was measured with the OLD route)."""
from __future__ import annotations

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from services import egress

from .models import EgressProxy, EgressRoute, EgressSwitch

logger = logging.getLogger(__name__)


def _forget_reachability() -> None:
    try:
        from apps.inbox import adapters, shared

        for kind in ("TELEGRAM",):
            cls = adapters.adapter_class(kind)
            if cls is not None:
                shared.set_flag(f"reach:{cls.key}", "", 1)
    except Exception:  # noqa: BLE001 - a nicety; the cached answer expires by itself
        logger.debug("egress: could not reset the inbox reachability flags", exc_info=True)


@receiver([post_save, post_delete], sender=EgressProxy)
@receiver([post_save, post_delete], sender=EgressRoute)
@receiver([post_save, post_delete], sender=EgressSwitch)
def _changed(sender, **kwargs):
    egress.invalidate()
    # health writes (the «test» button) are not a routing change
    fields = kwargs.get("update_fields")
    if fields and set(fields) <= {"health", "checked_at", "last_test", "last_test_at"}:
        return
    _forget_reachability()
