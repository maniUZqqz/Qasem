"""A test key that costs nothing. §9.16's «محیط تست».

A developer wiring our API into their shop's software writes the request wrong
the first five times. Making them spend five videos' worth of GPU on that is a
tax on integrating with us, and a shop whose month's allowance went on a
misplaced field will not try again.

So a key can be marked `is_test`. Its calls go through **exactly the same
authentication, scope check, validation and error paths** as a live one, and
stop at the last possible moment — where the work would be queued — returning a
shaped example instead.

Two things that make this honest rather than a toy:

**The responses are generated from the caller's own data.** A canned blob of
lorem ipsum teaches nothing about the shape you actually get back; a caption
about their real product, with their real product id in it, is a response they
can write code against.

**Every sandbox response says it is one.** `"sandbox": true` at the top level,
and the job ids are prefixed. A developer who ships to production still holding
a test key finds out from the first response, not from a customer asking where
their videos went.
"""
from __future__ import annotations

from django.utils import timezone

#: Prefixed so a sandbox job id cannot be mistaken for a real one — and so
#: polling it hits the sandbox status path rather than 404ing confusingly.
JOB_PREFIX = "sandbox-"

NOTE = (
    "این پاسخ از محیط تست است. شکل داده دقیقاً مثل محیط واقعی است ولی هیچ "
    "پردازشی انجام نشده و از سهمیه‌ی شما چیزی کم نشده."
)


def _job_id(endpoint: str) -> str:
    return f"{JOB_PREFIX}{endpoint}-{int(timezone.now().timestamp())}"


def _wrap(payload: dict) -> dict:
    # At the top level, not buried: a developer who ships with a test key finds
    # out from the first response rather than from a customer.
    return {"sandbox": True, "note": NOTE, **payload}


def queued(endpoint: str, product) -> dict:
    """What an asynchronous endpoint would have answered."""
    job = _job_id(endpoint)
    return _wrap({
        "job_id": job,
        "status_url": f"/api/v1/public/jobs/{job}/",
    })


def sales_agent(store, product, message: str) -> dict:
    """A reply shaped like the real one, from the shop's own data.

    Uses their actual product and price rather than an invented one, because a
    caller needs to see where the real numbers land in the structure.
    """
    if product is not None:
        reply = (
            f"سلام! «{product.name}» موجود است و قیمتش "
            f"{int(product.price):,} تومان است. برایتان ثبت کنم؟"
        )
        products = [product.pk]
    else:
        reply = "سلام! بفرمایید، در خدمتم."
        products = []

    return _wrap({
        "reply": reply,
        "intent": "PRICE" if product is not None else "GREETING",
        "action": "ANSWER",
        "needs_human": False,
        "products": products,
        "order": None,
        "conversation_id": 0,
    })


def job_status(job_id: str) -> dict:
    """A finished sandbox job, so polling code can be tested end to end.

    Always COMPLETED. A sandbox that stayed QUEUED would make the caller write
    a retry loop that never exits, which is worse than no sandbox.
    """
    return _wrap({
        "id": job_id,
        "state": "COMPLETED",
        "state_label": "انجام شد",
        "progress": {"step": 1, "total": 1, "label": ""},
        "awaiting_human": False,
        "result": {"example": True},
        "error": "",
    })


def is_sandbox_job(job_id) -> bool:
    return str(job_id).startswith(JOB_PREFIX)
