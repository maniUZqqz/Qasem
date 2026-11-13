"""Asking the processing node to read Instagram (job kind `ig.scrape`) and taking its answer into the database.

* `request_scan` puts one durable job in the compute queue: it waits there if the node is off and runs when the node is on.
* `sync_run` / `sync_runs` look at the compute job of a run and, once it has ended, ingest the batch it wrote (idempotent).
* `auto_scan_all` is what the periodic task calls: for every store that wants it, one small scan when the node is READY.

A stop of the node (challenge, «wait a few minutes», budget, not signed in ...) is an answer, not an error: the run ends as
«stopped» with the reason, whatever it read before stopping is kept.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import timedelta

from django.utils import timezone

from apps.compute import services as SV
from apps.compute.models import ComputeJob

from . import ingest, normalize, seeds, status
from .explain import fa
from .models import IgScanRun, IgStoreConfig

logger = logging.getLogger(__name__)

KIND = "ig.scrape"
PACE_S = [45, 110]
MAX_WAIT_S = 24 * 3600
STOP_FA = {
    "challenge": "اینستاگرام «تأییدِ انسان بودن» خواست؛ روی سرورِ پردازش آباگرام را باز کنید و در پنجره تأیید کنید.",
    "limit": "اینستاگرام گفت چند دقیقه صبر کن؛ آباگرام مکث کرد.",
    "budget": "سقفِ ساعتی/روزانهٔ صفحه‌های آباگرام پر شد؛ بعداً ادامه می‌دهد.",
    "not_signed_in": "آباگرام روی سرورِ پردازش وارد اینستاگرام نیست؛ دوباره وارد شوید (Open-Abagram.bat).",
    "unreachable": "اینستاگرام در دسترس نبود (VPN/پراکسی را بررسی کنید).",
    "service_down": "آباگرام روی سرورِ پردازش جواب نداد.",
    "installing": "آباگرام هنوز در حالِ نصبِ خودکار است.",
    "install_error": "نصبِ آباگرام خطا دارد.",
    "starting": "آباگرام در حالِ روشن‌شدن بود.",
    "busy": "آباگرام با کارِ دیگری مشغول بود.",
    "cancelled": "خواندن لغو شد.",
    "no_accounts": "نامِ صفحهٔ معتبری داده نشده بود.",
}


class ScanRefused(Exception):
    """A scan cannot be started now; the message (Persian) says why and what to do."""

    def __init__(self, message, code="refused"):
        super().__init__(message)
        self.code = code


def active_run(store) -> IgScanRun | None:
    return IgScanRun.objects.filter(store=store, source=IgScanRun.Source.NODE, state__in=[IgScanRun.State.QUEUED, IgScanRun.State.RUNNING]).first()


def request_scan(store, *, auto: bool = False, accounts: list[str] | None = None, max_accounts: int | None = None, force: bool = False,
                 rng: random.Random | None = None) -> IgScanRun:
    """Queue one scan. Raises ScanRefused with the reason."""
    cfg, _ = IgStoreConfig.objects.get_or_create(store=store)
    seeds.apply_defaults(store)
    st = status.node_status()
    if not st["can_queue"]:
        raise ScanRefused(st["message"] or "سرورِ پردازش آماده نیست.", st["problem"] or "not_ready")
    if auto and not st["ready"]:
        raise ScanRefused(st["message"], st["problem"] or "not_ready")
    if st["problem"] not in (None, "node_offline"):
        raise ScanRefused(st["message"], st["problem"])
    running = active_run(store)
    if running:
        raise ScanRefused("یک خواندن هم‌اکنون %s است." % ("در صف" if running.state == IgScanRun.State.QUEUED else "در جریان"), "busy")
    limit = max(1, min(int(max_accounts or cfg.max_accounts), 12))
    names = [n for n in (accounts or []) if n] or seeds.due_accounts(store, limit=limit, force=force)
    names = names[:limit]
    if not names:
        raise ScanRefused("صفحه‌ای برای خواندن نیست: یا هیچ صفحه‌ای اضافه نشده، یا همه تازه (کمتر از %s ساعت پیش) خوانده شده‌اند." % fa(cfg.min_reread_h), "nothing_due")
    rng = rng or random.Random()
    run = IgScanRun.objects.create(store=store, source=IgScanRun.Source.NODE, accounts=names, message="در صفِ سرورِ پردازش")
    payload = {"accounts": names, "max_accounts": len(names), "pace_s": PACE_S, "fresh": True, "posts_per_account": 24,
               "store_id": store.pk, "run_id": run.pk, "seed": rng.randrange(1, 10 ** 9)}
    timeout = len(names) * (300 + PACE_S[1]) + 600
    try:
        job = SV.enqueue_durable(KIND, payload, store=store, origin="igtrends", priority=60, timeout_s=timeout, dedupe=False,
                                 max_attempts=1, max_wait_s=MAX_WAIT_S)
    except SV.ComputeUnavailable as exc:
        run.state, run.message, run.finished_at = IgScanRun.State.FAILED, str(exc)[:300], timezone.now()
        run.save()
        raise ScanRefused(status.instruction("node_old", None), "node_old") from exc
    run.job_uid = str(job.uid)
    run.save(update_fields=["job_uid", "updated_at"])
    if auto:
        cfg.last_auto_at = timezone.now()
        cfg.save(update_fields=["last_auto_at", "updated_at"])
    return run


def _result_batch(job: ComputeJob) -> dict | None:
    try:
        path = SV.output_path(job, "ig_batch.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def sync_run(run: IgScanRun) -> IgScanRun:
    """Bring one run up to date with its compute job; ingest the result once. Never raises for a bad batch (the run says why)."""
    if not run.job_uid or run.ingested_at or run.state in (IgScanRun.State.OK, IgScanRun.State.STOPPED, IgScanRun.State.FAILED):
        return run
    job = ComputeJob.objects.filter(uid=run.job_uid).first()
    if job is None:
        run.state, run.message, run.finished_at = IgScanRun.State.FAILED, "کارِ پردازشی پیدا نشد (از صف پاک شده).", timezone.now()
        run.save()
        return run
    S = ComputeJob.State
    if job.state == S.QUEUED:
        run.state, run.message = IgScanRun.State.QUEUED, (job.message or "در صفِ سرورِ پردازش")[:300]
    elif job.state in (S.CLAIMED, S.RUNNING):
        run.state, run.message = IgScanRun.State.RUNNING, (job.message or "در حالِ خواندن")[:300]
    elif job.state == S.COMPLETED:
        return _ingest_finished(run, job)
    else:
        run.state = IgScanRun.State.FAILED
        run.message = ("لغو شد" if job.state == S.CANCELLED else (job.error or "ناموفق"))[:300]
        run.finished_at = job.finished_at or timezone.now()
    run.save()
    return run


def _ingest_finished(run: IgScanRun, job: ComputeJob) -> IgScanRun:
    batch = _result_batch(job)
    now = timezone.now()
    meta = (job.result or {}).get("meta") or {}
    if batch is None:
        run.state, run.message, run.finished_at = IgScanRun.State.FAILED, "سرورِ پردازش فایلِ نتیجه را نفرستاد.", now
        run.save()
        return run
    try:
        out = ingest.apply_batch(run.store, batch, run)
    except normalize.BatchError as exc:
        run.state, run.message, run.finished_at, run.ingested_at = IgScanRun.State.FAILED, "نتیجه خوانده نشد: %s" % exc, now, now
        run.save()
        return run
    stop = out.get("stopped")
    run.accounts_read, run.posts_new, run.posts_updated = out["accounts"], out["new"], out["updated"]
    run.summary = {"posts": out["posts"], "per_account": batch.get("per_account") or {}, "not_read": out.get("not_read"), "node": batch.get("node"),
                   "report": meta.get("report")}
    run.finished_at, run.ingested_at = job.finished_at or now, now
    if stop:
        run.state, run.stop_code = IgScanRun.State.STOPPED, (stop.get("code") or "")[:20]
        run.message = STOP_FA.get(run.stop_code, stop.get("message") or "زودتر متوقف شد")[:300]
    else:
        run.state = IgScanRun.State.OK
        run.message = ("%s صفحه خوانده شد، %s پستِ تازه." % (fa(out["accounts"]), fa(out["new"])))[:300]
    run.save()
    return run


def sync_runs(store=None) -> int:
    """All unfinished node runs (of one store, or all). Returns how many were looked at."""
    qs = IgScanRun.objects.filter(source=IgScanRun.Source.NODE, state__in=[IgScanRun.State.QUEUED, IgScanRun.State.RUNNING])
    if store is not None:
        qs = qs.filter(store=store)
    n = 0
    for run in qs.select_related("store"):
        try:
            sync_run(run)
        except Exception:  # noqa: BLE001 - one bad run must not stop the others
            logger.exception("igtrends: could not sync run %s", run.pk)
        n += 1
    return n


def on_job_finished(job: ComputeJob) -> None:
    """Called by apps.compute.api.finish for every ended job: ingest at once instead of waiting for the next sync."""
    if job.kind != KIND:
        return
    run = IgScanRun.objects.filter(job_uid=str(job.uid)).select_related("store").first()
    if run is not None:
        sync_run(run)


def seed_new_stores(limit: int = 200) -> list[int]:
    """Fitness / coaching shops (Chagher ...) that nobody has opened the trends tab for yet get their starter pack here, so the first
    automatic scan needs no click from the owner. Idempotent: a store with a config row is left alone."""
    from apps.stores.models import Store
    done = []
    for store in Store.objects.filter(ig_config__isnull=True).order_by("pk")[:limit]:
        if seeds.looks_like_fitness(store):
            seeds.apply_defaults(store)
            done.append(store.pk)
    return done


def auto_scan_all(now=None) -> dict:
    """One small scan per store that wants it, when the node is ready. Safe to call every half hour."""
    now = now or timezone.now()
    out = {"started": [], "skipped": {}, "seeded": []}
    try:
        out["seeded"] = seed_new_stores()
    except Exception:  # noqa: BLE001 - seeding is a convenience; the scan of the others must still happen
        logger.exception("igtrends: could not seed the starter pack")
    sync_runs()
    st = status.node_status()
    if not st["ready"]:
        out["skipped"]["_node"] = st["problem"]
        return out
    for cfg in IgStoreConfig.objects.filter(auto_scan=True).select_related("store"):
        store = cfg.store
        if getattr(store, "is_active", True) is False:
            continue
        last = IgScanRun.objects.filter(store=store, source=IgScanRun.Source.NODE).order_by("-created_at").first()
        if last and now - last.created_at < timedelta(hours=cfg.interval_h):
            out["skipped"][store.pk] = "interval"
            continue
        if not store.ig_seeds.filter(kind="account", enabled=True, scrape=True).exists():
            out["skipped"][store.pk] = "no_seeds"
            continue
        try:
            run = request_scan(store, auto=True)
            out["started"].append(run.pk)
        except ScanRefused as exc:
            out["skipped"][store.pk] = exc.code
    return out
