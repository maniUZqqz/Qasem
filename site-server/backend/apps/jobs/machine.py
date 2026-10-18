"""The states a generation job may be in, and the moves between them.

Until now a Job was QUEUED → RUNNING → COMPLETED. That is enough for a caption
and useless for a video: the whole point of incremental generation (§9.1) is
that the job **stops** after the first five seconds and waits for a person, and
"RUNNING" cannot express the difference between "the GPU is busy" and "the GPU
is idle because we are waiting for you".

So the states carry that distinction, and the machine enforces it:

    QUEUED → PROCESSING → PREVIEW → WAITING_APPROVAL → APPROVED
           → RENDERING → QC → COMPLETED

Every state also reaches FAILED and CANCELLED, and nothing leaves those two.

Why a table rather than `if` statements scattered across the tasks: an illegal
move is not a display bug. A job that goes from WAITING_APPROVAL straight to
COMPLETED has charged a customer for something nobody approved, and a job that
re-enters RENDERING has spent GPU minutes twice. `advance()` refuses, loudly.

The legacy states (RUNNING) stay in the enum. Old rows exist, and rewriting
history to make a state diagram prettier is how you lose the ability to explain
an invoice from last month.
"""
from __future__ import annotations

QUEUED = "QUEUED"
PROCESSING = "PROCESSING"
PREVIEW = "PREVIEW"
WAITING_APPROVAL = "WAITING_APPROVAL"
APPROVED = "APPROVED"
RENDERING = "RENDERING"
QC = "QC"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

#: Kept because rows in the database use it. New jobs do not enter it.
RUNNING = "RUNNING"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})

#: States where our own hardware is occupied. The scheduler counts these, so
#: WAITING_APPROVAL must not be among them — a job parked for a human is not
#: holding a GPU, and treating it as if it were would idle the card for hours.
BUSY = frozenset({PROCESSING, RENDERING, QC, RUNNING})

#: States a person is expected to act on. A job here will sit forever unless
#: someone answers, so staleness reaping must leave it alone.
AWAITING_HUMAN = frozenset({PREVIEW, WAITING_APPROVAL})

#: Still in flight from the panel's point of view.
ACTIVE = frozenset({QUEUED, PROCESSING, PREVIEW, WAITING_APPROVAL, APPROVED, RENDERING, QC, RUNNING})

_MOVES: dict[str, frozenset[str]] = {
    QUEUED: frozenset({PROCESSING, RUNNING}),
    PROCESSING: frozenset({PREVIEW, RENDERING, QC, COMPLETED}),
    # A preview that nobody has to approve (Auto mode above threshold) goes
    # straight back to work; one that does becomes WAITING_APPROVAL.
    PREVIEW: frozenset({WAITING_APPROVAL, PROCESSING, RENDERING, APPROVED}),
    WAITING_APPROVAL: frozenset({APPROVED, PROCESSING}),
    APPROVED: frozenset({PROCESSING, RENDERING, PREVIEW}),
    RENDERING: frozenset({QC, PREVIEW, COMPLETED}),
    QC: frozenset({COMPLETED, PROCESSING, RENDERING}),
    # legacy
    RUNNING: frozenset({COMPLETED, PROCESSING, PREVIEW, RENDERING, QC}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
}

_LABEL = {
    QUEUED: "در صف",
    PROCESSING: "در حال پردازش",
    PREVIEW: "پیش‌نمایش آماده است",
    WAITING_APPROVAL: "منتظر تأیید شما",
    APPROVED: "تأیید شد",
    RENDERING: "در حال رندر نهایی",
    QC: "در حال بررسی کیفیت",
    COMPLETED: "تمام شد",
    FAILED: "شکست خورد",
    CANCELLED: "لغو شد",
    RUNNING: "در حال اجرا",
}


class IllegalTransition(Exception):
    """A move the machine does not allow.

    Raised rather than logged: the moves this blocks are the ones that charge
    for unapproved work or spend GPU minutes twice.
    """


def label(state: str) -> str:
    return _LABEL.get(state, state)


def allowed(state: str) -> frozenset[str]:
    """Where a job in this state may go next."""
    return _MOVES.get(state, frozenset())


def can(current: str, target: str) -> bool:
    """Is this move legal? FAILED and CANCELLED are reachable from anywhere
    that is not already terminal — a job can always break or be abandoned."""
    if current in TERMINAL:
        return False
    if target in (FAILED, CANCELLED):
        return True
    return target in allowed(current)


def check(current: str, target: str) -> None:
    """Raise unless the move is legal."""
    if not can(current, target):
        raise IllegalTransition(
            f"«{label(current)}» نمی‌تواند به «{label(target)}» برود."
        )
