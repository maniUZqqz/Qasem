"""The global daily cap. Outreach registers a counter that says how many send attempts happened on a day;
compliance itself never imports outreach."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

from django.utils import timezone

from ..models import GrowthSettings

_COUNTERS: list[Callable[[date], int]] = []


def register_counter(fn: Callable[[date], int]) -> None:
    """``fn(day) -> number of send attempts made on that (Tehran) day``. Registering the same function twice is a no-op."""
    if fn not in _COUNTERS:
        _COUNTERS.append(fn)


def sent_on(day: date) -> int:
    return sum(int(fn(day)) for fn in _COUNTERS)


def sent_today() -> int:
    return sent_on(timezone.localdate())


def cap_remaining(settings_obj: GrowthSettings | None = None) -> int:
    settings_obj = settings_obj or GrowthSettings.load()
    return max(0, settings_obj.daily_cap - sent_today())
