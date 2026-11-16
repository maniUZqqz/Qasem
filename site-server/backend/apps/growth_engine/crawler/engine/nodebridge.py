"""The processing node (the GPU computer) as a helper of the crawler.

Three kinds of work can be handed to it, all through the compute queue's *durable* mode (a job waits there while the node is off and
runs when it is on; nothing is lost and nobody has to click):

``crawl.run``      read many business sites (the same page selection as the server, optional headless-browser rendering) and return the pages;
``crawl.render``   the same but ALWAYS in a headless browser - for sites that are only a JavaScript shell;
``ig.scrape``      Abagram (the owner's Instagram reader, existing kind) reads the public profile of a few business pages.

If the node has not yet been updated (an older agent does not advertise the capability) the work is NOT enqueued - the compute queue
refuses a kind nobody can run - and the task simply stays «منتظرِ سرورِ پردازش». ``sync`` (every few minutes, from Celery beat, and when
the panel is opened) tries again; the first time a node reports the capability the work is queued by itself.
"""
from __future__ import annotations

import gzip
import json
import logging
from dataclasses import dataclass

from django.utils import timezone

from apps.compute import services as SV
from apps.compute.models import ComputeJob, capability_for

logger = logging.getLogger(__name__)

ORIGIN = "growth_crawler"
MAX_WAIT_S = 14 * 24 * 3600
KINDS = ("crawl.run", "crawl.render", "ig.scrape")


class NodeUnavailable(Exception):
    """No registered node can run this kind (yet)."""


@dataclass
class Poll:
    state: str  # waiting | running | done | failed | cancelled | missing
    message: str = ""
    job: ComputeJob | None = None


def capable(kind: str) -> bool:
    """A node that reported the capability exists (online or not)."""
    try:
        return bool(SV.known_nodes(capability_for(kind)))
    except Exception:  # noqa: BLE001 - never let the compute app's trouble stop a crawl
        logger.exception("crawler: known_nodes failed")
        return False


def online(kind: str) -> bool:
    try:
        return bool(SV.online_nodes(capability_for(kind)))
    except Exception:  # noqa: BLE001
        return False


def submit(kind: str, payload: dict, *, timeout_s: int, priority: int = 70) -> str:
    """Queue one durable job. Returns its uid; ``NodeUnavailable`` when no node can ever run it (nothing was queued)."""
    try:
        job = SV.enqueue_durable(kind, payload, origin=ORIGIN, priority=priority, timeout_s=timeout_s, dedupe=False, max_attempts=2, max_wait_s=MAX_WAIT_S)
    except SV.ComputeUnavailable as exc:
        raise NodeUnavailable(str(exc)) from exc
    return str(job.uid)


def poll(uid: str) -> Poll:
    job = ComputeJob.objects.filter(uid=uid).first()
    if job is None:
        return Poll("missing", "کارِ پردازشی از صف پاک شده بود.")
    S = ComputeJob.State
    if job.state == S.COMPLETED:
        return Poll("done", job.message or "", job)
    if job.state == S.FAILED:
        return Poll("failed", (job.error or "ناموفق")[:300], job)
    if job.state == S.CANCELLED:
        return Poll("cancelled", (job.error or "لغو شد")[:300], job)
    if job.state in (S.CLAIMED, S.RUNNING):
        return Poll("running", (job.message or "در حال اجرا روی سرورِ پردازش")[:200], job)
    return Poll("waiting", (job.message or "در صفِ سرورِ پردازش")[:200], job)


def cancel(uid: str) -> None:
    job = ComputeJob.objects.filter(uid=uid).first()
    if job is not None and not job.final:
        try:
            SV.cancel(job, "اجرای مشتری‌یاب لغو شد")
        except Exception:  # noqa: BLE001
            logger.exception("crawler: could not cancel node job %s", uid)


def read_json(job: ComputeJob, name: str):
    try:
        with open(SV.output_path(job, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def read_sites(job: ComputeJob, name: str = "pages.jsonl.gz") -> list[dict]:
    """The node's answer of ``crawl.run`` / ``crawl.render``: one JSON object per site (see processing/crawl_jobs.py)."""
    path = SV.output_path(job, name)
    out: list[dict] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except (OSError, EOFError):
        return []
    return out


def stamp() -> str:
    return timezone.now().isoformat(timespec="seconds")
