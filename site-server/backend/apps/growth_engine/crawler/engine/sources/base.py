"""The shared vocabulary of the sources: a task to do, the context a task runs in, the ways it can end."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..candidates import Found
from ..fetch import WebClient


@dataclass
class TaskSpec:
    """A task as a source describes it; the runner turns it into a ``CrawlTask`` row (unique per run by ``key``)."""

    source: str
    kind: str
    key: str
    label: str = ""
    params: dict = field(default_factory=dict)
    stage: str = "discover"  # discover | enrich | ig
    priority: int = 100
    depth: int = 0


class RetryLater(Exception):
    """A busy public service: the task goes back to the queue after ``delay_s`` (it is tried ``MAX_ATTEMPTS`` times in all)."""

    def __init__(self, message: str, delay_s: int = 300):
        super().__init__(message)
        self.message = message
        self.delay_s = delay_s


class TaskFailed(Exception):
    """This task cannot succeed (a bad address, a refused page). It is recorded and the run goes on."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class WaitForNode(Exception):
    """The work is handed to the processing node; the task waits (durable queue) and is finished by ``node.sync``."""

    def __init__(self, job_uid: str, message: str = ""):
        super().__init__(message or "منتظرِ سرورِ پردازش")
        self.job_uid = job_uid
        self.message = message or "منتظرِ سرورِ پردازش"


@dataclass
class SourceContext:
    run: object  # CrawlRun
    spec: dict
    web: WebClient
    emit: Callable[[Found], object]  # puts a found business into the run (dedupes), returns (candidate, created)
    add_tasks: Callable[[list[TaskSpec]], int]  # schedules follow-up tasks; returns how many were new
    log: Callable[[str, str], None]  # (level, message)
    secrets: dict = field(default_factory=dict)  # provider keys (Neshan ...), never logged
    node_available: bool = False
    stop: Callable[[], bool] = lambda: False

    # convenience
    def types(self) -> list[str]:
        return [t for t in (self.spec.get("business_types") or []) if t]

    def cities(self) -> list[str]:
        return [c for c in (self.spec.get("cities") or []) if c]

    def budget(self, name: str, default: int) -> int:
        try:
            return int((self.spec.get("budget") or {}).get(name) or default)
        except (TypeError, ValueError):
            return default
