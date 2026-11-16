"""Working hours - one definition shared by the bot, the SLA clock and the UI.

Stored as `{"days": [5, 6, 0, 1, 2], "start": "09:00", "end": "18:00"}` with
Python weekday numbers (Monday = 0) in Tehran time. An empty value means "always
open", which is the honest default for a shop that never filled it in: assuming
office hours it did not state would mute the bot at 7 pm for no reason.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

#: Saturday to Wednesday, 9 to 18 - the common Iranian office week, offered as
#: the one-click default in the settings page.
DEFAULT_HOURS = {"days": [5, 6, 0, 1, 2], "start": "09:00", "end": "18:00"}


def _hm(text: str, fallback: str) -> tuple[int, int]:
    try:
        h, m = (text or fallback).split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        h, m = fallback.split(":")
        return int(h), int(m)


def configured(hours: dict | None) -> bool:
    return bool(hours and hours.get("days"))


def is_open(hours: dict | None, now: datetime | None = None) -> bool:
    if not configured(hours):
        return True
    local = (now or datetime.now(TEHRAN)).astimezone(TEHRAN)
    if local.weekday() not in set(hours["days"]):
        return False
    sh, sm = _hm(hours.get("start"), "09:00")
    eh, em = _hm(hours.get("end"), "18:00")
    start = local.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = local.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= local < end


def next_open(hours: dict | None, now: datetime | None = None) -> datetime:
    """The next moment the shop is open (now, when it already is)."""
    now = (now or datetime.now(TEHRAN)).astimezone(TEHRAN)
    if is_open(hours, now):
        return now
    sh, sm = _hm(hours.get("start"), "09:00")
    for offset in range(0, 9):
        day = now + timedelta(days=offset)
        if day.weekday() not in set(hours["days"]):
            continue
        candidate = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
        if candidate > now:
            return candidate
    return now
