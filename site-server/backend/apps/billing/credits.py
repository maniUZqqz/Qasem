"""Quality-gated credit: a store pays for output it can use, not for output.

ROADMAP §9.9 draws it as:

    Generation → QC → PASS: consume credit · FAIL: refund credit

`services.reserve/commit/release` already covers the crash case: a render that
dies releases its reservation. This module covers the harder one — the render
*succeeded*, the credit was spent, and the result is unusable anyway. Without
this, a store that regenerates a poster four times pays four times for one
poster, and concludes the product is expensive rather than that the model had
a bad day.

Two things are deliberately separated:

* **refund** — one specific output was rejected; its credit goes back.
* **guarantee** — after `QUALITY_MAX_ATTEMPTS` tries at the same thing, we stop
  charging for it at all and say so. That is a promise, so it is enforced in
  code rather than offered in marketing copy.

The `source` field exists because the automatic judge (Vision QC, phase 21) is
not built yet. Today every verdict comes from the shop owner pressing "not
good"; when QC arrives it writes `AUTO` into the same ledger and nothing else
has to change.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

from .models import Usage

logger = logging.getLogger(__name__)

CUSTOMER = "CUSTOMER"
AUTO = "AUTO"


class NotRefundable(Exception):
    """This usage row cannot be refunded, and the reason is worth showing."""


def max_attempts() -> int:
    """How many goes at one thing before the credit stops being charged.

    Three is the default: one miss is luck, two is a coincidence, three means
    the model cannot do this job today and charging further is taking money
    for a problem we have not solved.
    """
    return int(settings.UPMARKET_AI.get("QUALITY_MAX_ATTEMPTS", 3))


def attempt_chain(row: Usage) -> list[Usage]:
    """Every attempt at the same thing, oldest first, including this one."""
    chain = [row]
    seen = {row.pk}
    current = row
    while current.retry_of_id and current.retry_of_id not in seen:
        current = current.retry_of
        seen.add(current.pk)
        chain.insert(0, current)
    return chain


@transaction.atomic
def refund(
    row: Usage | None,
    *,
    reason: str = "",
    source: str = CUSTOMER,
    actor=None,
) -> Usage | None:
    """Give a spent credit back because the output was not usable.

    Idempotent: refunding twice is a double credit, and the second call is
    usually a double-clicked button rather than a second complaint.
    """
    if row is None:
        return None

    row = Usage.objects.select_for_update().get(pk=row.pk)

    if row.state == Usage.State.REFUNDED:
        return row  # already given back
    if row.state == Usage.State.RELEASED:
        # Nothing was ever charged: the job failed before producing anything.
        # Refunding here would hand back a credit that was never taken.
        raise NotRefundable("این مورد اصلاً مصرف نشده بود — چیزی برای برگشت نیست.")
    if row.state != Usage.State.COMMITTED:
        raise NotRefundable("این مورد هنوز تمام نشده است.")

    row.state = Usage.State.REFUNDED
    row.quality_reason = (reason or "کیفیت خروجی مناسب نبود")[:200]
    row.quality_source = source
    row.save(update_fields=["state", "quality_reason", "quality_source", "updated_at"])

    _log(row, reason=row.quality_reason, source=source, actor=actor)
    logger.info(
        "credit refund store=%s %s x%s attempt=%s (%s)",
        row.store_id, row.metric, row.quantity, row.attempt, source,
    )
    return row


def _log(row: Usage, *, reason: str, source: str, actor) -> None:
    """Append the decision to the billing history.

    The ledger row says the credit came back; this says who decided and why.
    A refund with no stated reason is indistinguishable from a bug.
    """
    from .payment_models import BillingEvent

    BillingEvent.objects.create(
        store_id=row.store_id,
        kind=BillingEvent.Kind.CREDIT_REFUNDED,
        summary=f"{row.get_metric_display()} ×{row.quantity} برگشت خورد — {reason}"[:300],
        actor=actor,
        context={
            "usage_id": row.pk,
            "metric": row.metric,
            "quantity": row.quantity,
            "attempt": row.attempt,
            "source": source,
            "job_id": row.job_id,
        },
    )


def guarantee_status(row: Usage) -> dict:
    """Where this attempt chain stands against the quality guarantee."""
    chain = attempt_chain(row)
    limit = max_attempts()
    used = len(chain)
    return {
        "attempt": row.attempt,
        "attempts_used": used,
        "max_attempts": limit,
        "attempts_left": max(0, limit - used),
        "exhausted": used >= limit,
    }


@transaction.atomic
def reserve_retry(row: Usage, *, job=None, detail: str = "") -> tuple[Usage | None, dict]:
    """Reserve credit for another go — unless the guarantee says it is free.

    Returns `(reservation, status)`. A `None` reservation with
    `status["free"] is True` means the guarantee kicked in: the work still
    runs, it just is not charged for. That is the whole point of promising it.
    """
    from . import services

    status = guarantee_status(row)

    if status["exhausted"]:
        # ROADMAP §9.9 row C: "Generation Failed — Credit Returned".
        #
        # The **whole chain** comes back, not just the last attempt. A store
        # that tried three times and got nothing usable paid three times for
        # one thing; handing back only the final credit would leave them
        # charged twice over for a result they never received, which is not a
        # guarantee — it is a discount on failure.
        why = f"بعد از {status['attempts_used']} تلاش به کیفیت لازم نرسید"
        given_back = 0
        for attempt in attempt_chain(row):
            if attempt.state == Usage.State.COMMITTED:
                refund(attempt, reason=why, source=AUTO)
                given_back += attempt.quantity

        status["free"] = True
        status["refunded"] = given_back
        status["message"] = (
            f"بعد از {status['attempts_used']} تلاش، این تولید رایگان شد و "
            "اعتبار همه‌ی تلاش‌ها برگشت خورد."
        )
        return None, status

    reservation = services.reserve(
        row.store, row.metric, row.quantity, job=job, detail=detail or row.detail,
        external=row.external,
    )
    if reservation is not None:
        reservation.attempt = row.attempt + 1
        reservation.retry_of = row
        reservation.save(update_fields=["attempt", "retry_of", "updated_at"])
    status["free"] = False
    status["attempt"] = row.attempt + 1
    status["message"] = ""
    return reservation, status
