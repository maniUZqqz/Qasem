"""The daily cap is counted from the attempts themselves: one ``SendAttempt`` row = one use of the day's allowance."""
from __future__ import annotations

from datetime import date

from ..models import SendAttempt


def attempts_on(day: date) -> int:
    """Send attempts made on ``day`` (Tehran date), over all campaigns. Registered with the compliance limits."""
    return SendAttempt.objects.filter(attempted_at__date=day).count()
