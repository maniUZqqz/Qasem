"""Scheduled health check of the services that go through a proxy (so the settings page and the inbox cards stay fresh and a dead VPN is
noticed without anyone pressing a button). Safe to run twice and to run late; does nothing when every service is direct."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="egress.check_routed")
def check_routed() -> dict:
    from . import state

    return state.check_routed()
