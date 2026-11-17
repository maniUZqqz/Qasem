"""Running a crawl: plan -> discover -> dedupe -> enrich -> finalize, with pause / resume / cancel, retries, budgets and a diary.

The state lives in the database (``CrawlRun`` / ``CrawlTask`` / ``CrawlCandidate``), never in the worker's memory, so a run survives a worker
restart: calling ``run_crawl(run_id)`` again continues with the tasks that are not done. One task = one request-sized unit; after every task the run's counters,
heartbeat and budget usage are saved, and the pause / cancel flags and the time budget are looked at.

Ways a run ends: ``completed`` (also when a budget stopped it early - the diary says which), ``cancelled`` (by a person), ``failed`` (only for a
bug or a database problem; a busy website or a blocked search engine is never a failure of the run). Work that needs the processing node
(JavaScript sites, Instagram pages, big batches) does NOT hold the run back: those tasks wait in the durable queue and ``sync_node`` finishes them whenever the node comes online.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.core.dbretry import retry_locked

from .. import presets
from ..models import CrawlCandidate, CrawlLog, CrawlMission, CrawlRun, CrawlTask
from . import candidates as cand_mod
from . import finalize, nodebridge, scoring
from . import fetch as fetchmod
from .sources import directory, instagram, neshan, osm, search, website
from .sources.base import RetryLater, SourceContext, TaskFailed, TaskSpec, WaitForNode

logger = logging.getLogger(__name__)

SOURCES = {"osm": osm, "search": search, "directory": directory, "website": website, "neshan": neshan}
MAX_LOG_ROWS = 700
MAX_ATTEMPTS = 3
MAX_TASKS = 1500
STAGE_ORDER = ["plan", "discover", "dedupe", "enrich", "finalize", "done"]
NODE_BATCH_SITES = 25
IDLE_SLEEP_MAX = 90


class Interrupted(Exception):
    """The run was cancelled or paused by a person (checked between tasks)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind  # cancel | pause


# --------------------------------------------------------------------------- the run's diary and counters


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_./=:@#%+-])\d+(?:[.,]\d+)?(?![A-Za-z0-9_])")


def fa_numbers(text: str) -> str:
    """The diary is read by a Persian speaker: «12 مورد» -> «۱۲ مورد». Numbers inside addresses, ids and handles (``id=12``, ``/page/2``, ``abc123``) stay as they are."""
    return _NUMBER.sub(lambda m: m.group(0).translate(_FA_DIGITS), text)


def log(run_id: int, level: str, message: str) -> None:
    def write() -> None:
        if CrawlLog.objects.filter(run_id=run_id).count() >= MAX_LOG_ROWS:
            return
        CrawlLog.objects.create(run_id=run_id, level=level, message=fa_numbers(message)[:500])

    try:
        retry_locked(write)
    except Exception:  # noqa: BLE001 - the diary must never stop a run
        logger.warning("crawler: could not write the log of run %s", run_id)


def refresh_counters(run: CrawlRun) -> None:
    rows = dict(CrawlTask.objects.filter(run=run).values_list("status").annotate(n=Count("id")))
    total = sum(rows.values())
    done = rows.get("done", 0) + rows.get("skipped", 0)
    CrawlRun.objects.filter(pk=run.pk).update(
        tasks_total=total, tasks_done=done, tasks_failed=rows.get("failed", 0), tasks_waiting=rows.get("waiting_node", 0),
        unique_count=CrawlCandidate.objects.filter(run=run).count(), total_items=total, processed_items=done + rows.get("failed", 0) + rows.get("waiting_node", 0),
        heartbeat_at=timezone.now(),
    )


def set_state(run_id: int, **fields) -> None:
    CrawlRun.objects.filter(pk=run_id).update(**fields)


# --------------------------------------------------------------------------- planning


def plan_discovery(spec: dict) -> list[TaskSpec]:
    sources = spec.get("sources") or {}
    specs: list[TaskSpec] = []
    if sources.get("osm", True):
        specs += osm.plan(spec)
    if sources.get("neshan"):
        specs += neshan.plan(spec)
    if sources.get("directory", True) or spec.get("directory_urls"):
        specs += directory.plan(spec)
    if sources.get("search", True):
        specs += search.plan(spec)
    return specs


def add_task_specs(run: CrawlRun, specs: list[TaskSpec]) -> int:
    """Create tasks that do not exist yet (unique by key). Returns how many were new."""
    if not specs:
        return 0
    existing = CrawlTask.objects.filter(run=run).count()
    room = max(0, MAX_TASKS - existing)
    rows = [
        CrawlTask(run=run, stage=s.stage, source=s.source, kind=s.kind, key=s.key[:400], label=s.label[:300], params=s.params, priority=s.priority, depth=s.depth)
        for s in specs[:room]
    ]
    before = CrawlTask.objects.filter(run=run).count()
    CrawlTask.objects.bulk_create(rows, ignore_conflicts=True)
    return CrawlTask.objects.filter(run=run).count() - before


# --------------------------------------------------------------------------- the engine


class Engine:
    def __init__(self, run: CrawlRun, *, web_factory=None):
        self.run = run
        self.spec = dict(run.spec or {})
        self.mission: CrawlMission = run.mission
        budget_spec = self.spec.get("budget") or {}
        usage = (run.usage or {}).get("budget") or {}
        self.budget = fetchmod.Budget.from_spec(budget_spec, used=usage)
        factory = web_factory or fetchmod.make_fetcher
        self.fetcher = factory(read_timeout=110.0, domain_delay=float(budget_spec.get("domain_delay") or 2.0))
        self._flags_at = 0.0
        self._flags = (False, False)
        self.out_of_area = int((run.usage or {}).get("out_of_area") or 0)  # found, but in another city than the mission asked for (not kept)
        self.web = fetchmod.WebClient(self.fetcher, self.budget, stop=self.should_stop, log=lambda lv, m: log(run.pk, lv, m), heartbeat=lambda: CrawlRun.objects.filter(pk=run.pk).update(heartbeat_at=timezone.now()))
        self.node_known = nodebridge.capable("crawl.run")

    # -- flags
    def _read_flags(self) -> tuple[bool, bool]:
        now = time.monotonic()
        if now - self._flags_at > 1.5:
            row = CrawlRun.objects.filter(pk=self.run.pk).values_list("cancel_requested", "pause_requested").first() or (False, False)
            self._flags, self._flags_at = (bool(row[0]), bool(row[1])), now
        return self._flags

    def should_stop(self) -> bool:
        cancel, pause = self._read_flags()
        return cancel or pause

    def check_interrupt(self) -> None:
        cancel, pause = self._read_flags()
        if cancel:
            raise Interrupted("cancel")
        if pause:
            raise Interrupted("pause")

    # -- context handed to a source
    def context(self) -> SourceContext:
        def emit(found):
            cand, created = cand_mod.add_found(self.run, found)
            if cand is None:  # its own address / position / landline area code says another city
                self.out_of_area += 1
                return None, False
            CrawlRun.objects.filter(pk=self.run.pk).update(found_count=F("found_count") + 1)
            return cand, created

        def add_tasks(specs):
            return add_task_specs(self.run, specs)

        return SourceContext(
            run=self.run, spec=self.spec, web=self.web, emit=emit, add_tasks=add_tasks, log=lambda lv, m: log(self.run.pk, lv, m),
            node_available=self.node_known, stop=self.should_stop,
        )

    # -- executing one task
    def execute(self, task: CrawlTask, ctx: SourceContext) -> None:
        module = SOURCES.get(task.source)
        task.status, task.started_at, task.attempts = CrawlTask.Status.RUNNING, timezone.now(), task.attempts + 1
        task.save(update_fields=["status", "started_at", "attempts"])
        set_state(self.run.pk, message=task.label[:300] or f"{task.source}:{task.kind}")
        try:
            if module is None:
                raise TaskFailed("منبعِ این کار شناخته نشد.")
            result = module.execute(task, ctx) or {}
            task.status, task.result, task.error = CrawlTask.Status.DONE, result, ""
            task.finished_at = timezone.now()
        except RetryLater as busy:
            if task.attempts >= MAX_ATTEMPTS:
                task.status, task.error = CrawlTask.Status.FAILED, busy.message[:500]
                task.finished_at = timezone.now()
                log(self.run.pk, "warn", f"{task.label or task.key[:60]}: {busy.message} (بعد از {MAX_ATTEMPTS} بار تلاش رها شد)")
            else:
                task.status, task.error = CrawlTask.Status.PENDING, busy.message[:500]
                task.not_before = timezone.now() + timedelta(seconds=busy.delay_s)
                log(self.run.pk, "warn", f"{task.label or task.key[:60]}: {busy.message} (بعداً دوباره امتحان می‌شود)")
        except TaskFailed as bad:
            task.status, task.error, task.finished_at = CrawlTask.Status.FAILED, bad.message[:500], timezone.now()
            log(self.run.pk, "warn", f"{task.label or task.key[:60]}: {bad.message}")
        except WaitForNode as wait:
            task.status, task.node_job_uid = CrawlTask.Status.WAITING_NODE, wait.job_uid
        except fetchmod.BudgetExceeded:
            task.status = CrawlTask.Status.PENDING
            task.save()
            raise
        except Exception as exc:  # noqa: BLE001 - one task never stops the run
            logger.exception("crawler: task %s of run %s crashed", task.pk, self.run.pk)
            task.status, task.error, task.finished_at = CrawlTask.Status.FAILED, f"خطای داخلی ({type(exc).__name__})", timezone.now()
            log(self.run.pk, "error", f"{task.label or task.key[:60]}: خطای داخلی ({type(exc).__name__})")
        task.save()

    def pick(self, stage: str) -> CrawlTask | None:
        now = timezone.now()
        return (CrawlTask.objects.filter(run=self.run, stage=stage, status=CrawlTask.Status.PENDING)
                .filter(models_q_ready(now)).order_by("priority", "id").first())

    def pending_delayed(self, stage: str) -> CrawlTask | None:
        return CrawlTask.objects.filter(run=self.run, stage=stage, status=CrawlTask.Status.PENDING, not_before__gt=timezone.now()).order_by("not_before").first()

    def drain(self, stage: str) -> str:
        """Run the pending tasks of one stage. Returns ``done`` | ``parked`` (only delayed tasks remain, far away)."""
        ctx = self.context()
        while True:
            self.check_interrupt()
            task = self.pick(stage)
            if task is None:
                waiting = self.pending_delayed(stage)
                if waiting is None:
                    return "done"
                delay = (waiting.not_before - timezone.now()).total_seconds()
                if delay > IDLE_SLEEP_MAX:
                    return "parked"
                time.sleep(max(1.0, delay))
                continue
            self.execute(task, ctx)
            self.save_usage()

    def save_usage(self) -> None:
        refresh_counters(self.run)
        CrawlRun.objects.filter(pk=self.run.pk).update(
            usage={**(self.run.usage or {}), "budget": self.budget.snapshot(), "out_of_area": self.out_of_area}, pages_fetched=self.budget.requests, bytes_fetched=self.budget.bytes, cache_hits=self.budget.cache_hits,
        )

    def close(self) -> None:
        try:
            self.web.close()
        except Exception:  # noqa: BLE001
            pass


def models_q_ready(now):
    from django.db.models import Q

    return Q(not_before__isnull=True) | Q(not_before__lte=now)


# --------------------------------------------------------------------------- the enrichment plan


def plan_enrichment(engine: Engine) -> dict:
    """Decide, per candidate, who reads its site: the server, or the processing node (when there is one and the job is big or needs a browser)."""
    spec, run = engine.spec, engine.run
    budget = spec.get("budget") or {}
    max_sites = int(budget.get("max_sites") or 60)
    server_cap = int(budget.get("server_sites") or 40)
    execution = spec.get("execution", "auto")
    sources = spec.get("sources") or {}
    node_known = engine.node_known
    todo = [c for c in CrawlCandidate.objects.filter(run=run, enriched=False).exclude(website="").order_by("id")]
    # businesses that already have a phone AND an e-mail need the site least
    todo.sort(key=lambda c: (bool(c.phones) + bool(c.emails), c.id))
    specs: list[TaskSpec] = []
    to_node = 0
    for i, c in enumerate(todo[:max_sites]):
        if node_known and (execution == "node" or (execution == "auto" and i >= server_cap)):
            specs.append(TaskSpec(source="website", kind="node_site", key=f"node_site:{c.pk}", stage="node", priority=60, label=f"سایت (روی سرورِ پردازش): {c.website[:60]}",
                                  params={"candidate_id": c.pk, "url": c.website, "render": "auto"}))
            to_node += 1
        else:
            specs.append(website.task_for(c))
    if execution == "node" and not node_known:
        log(run.pk, "warn", "اجرای روی سرورِ پردازش خواسته شده ولی هیچ سرورِ پردازشی با این توانایی ثبت نشده؛ سایت‌ها روی همین سرور خوانده می‌شوند.")
    ig_n = 0
    if sources.get("instagram"):
        for c in CrawlCandidate.objects.filter(run=run).exclude(instagram="").order_by("id")[: int(budget.get("max_ig_accounts") or 40)]:
            if instagram.handle_of(c):
                specs.append(instagram.task_for(c))
                ig_n += 1
    new = add_task_specs(run, specs)
    log(run.pk, "info", f"برنامهٔ تکمیل: {len(todo)} سایت ({min(len(todo), max_sites)} خوانده می‌شود، {to_node} روی سرورِ پردازش)، {ig_n} پیجِ اینستاگرام.")
    return {"sites": min(len(todo), max_sites), "node_sites": to_node, "ig": ig_n, "new_tasks": new}


# --------------------------------------------------------------------------- node work (durable, never blocks the run)


def _members(run: CrawlRun, kinds: tuple[str, ...]) -> list[CrawlTask]:
    return list(CrawlTask.objects.filter(run=run, kind__in=kinds, status=CrawlTask.Status.PENDING).order_by("id"))


def queue_node_work(run: CrawlRun, spec: dict) -> dict:
    """Group the waiting node tasks into jobs and put them in the durable queue; with no capable node yet they just wait (and ``sync_node`` retries)."""
    out = {"jobs": 0, "waiting": 0}
    for kind_pair in (("node_site",), ("ig_profile",)):
        tasks = _members(run, kind_pair)
        waiting = list(CrawlTask.objects.filter(run=run, kind__in=kind_pair, status=CrawlTask.Status.WAITING_NODE, node_job_uid=""))
        tasks += waiting
        if not tasks:
            continue
        for t in tasks:
            if t.status != CrawlTask.Status.WAITING_NODE:
                t.status = CrawlTask.Status.WAITING_NODE
                t.save(update_fields=["status"])
        out["waiting"] += len(tasks)
        out["jobs"] += _submit_groups(run, spec, tasks)
    return out


def _submit_groups(run: CrawlRun, spec: dict, tasks: list[CrawlTask]) -> int:
    jobs = 0
    kind = tasks[0].kind
    if kind == "ig_profile":
        size, node_kind = instagram.MAX_PER_JOB, instagram.KIND
        groups = [tasks[i:i + size] for i in range(0, len(tasks), size)]
    else:
        size, node_kind = NODE_BATCH_SITES, "crawl.run"
        groups = []
        for render in ("auto", "always"):
            sel = [t for t in tasks if (t.params.get("render") or "auto") == render]
            groups += [sel[i:i + size] for i in range(0, len(sel), size)]
    for group in groups:
        if not group:
            continue
        if kind == "ig_profile":
            handles = list(dict.fromkeys(t.params["handle"] for t in group))
            payload, timeout = instagram.build_payload(handles, run.pk), instagram.timeout_for(len(handles))
            job_kind = instagram.KIND
        else:
            render = group[0].params.get("render") or "auto"
            budget = (spec.get("budget") or {})
            payload = {
                "sites": [{"id": t.params["candidate_id"], "url": t.params["url"]} for t in group], "max_pages_per_site": int(budget.get("max_pages_per_site") or 5),
                "render": render, "domain_delay": float(budget.get("domain_delay") or 2.0), "run_id": run.pk, "purpose": "growth_crawler",
                "max_html_bytes": 150_000, "total_bytes": 40_000_000,
            }
            timeout = 120 + len(group) * 90
            job_kind = "crawl.render" if render == "always" else "crawl.run"
        try:
            uid = nodebridge.submit(job_kind, payload, timeout_s=timeout)
        except nodebridge.NodeUnavailable:
            log(run.pk, "info", f"{len(group)} کار منتظرِ سرورِ پردازش است (هنوز سروری با این توانایی گزارش نداده؛ بعد از به‌روزرسانیِ سرورِ پردازش خودکار صف می‌شود).")
            continue
        CrawlTask.objects.filter(pk__in=[t.pk for t in group]).update(node_job_uid=uid, status=CrawlTask.Status.WAITING_NODE)
        jobs += 1
        log(run.pk, "info", f"{len(group)} کار به سرورِ پردازش سپرده شد (در صفِ ماندگار؛ تا روشن‌شدنش می‌ماند).")
    return jobs


def sync_node(run: CrawlRun) -> dict:
    """Bring the node-bound tasks of one run up to date: queue the ones that could not be queued yet, ingest finished jobs. Never raises."""
    spec = dict(run.spec or {})
    out = {"queued": 0, "ingested": 0, "failed": 0, "waiting": 0}
    try:
        if CrawlTask.objects.filter(run=run, status=CrawlTask.Status.WAITING_NODE, node_job_uid="").exists():
            out["queued"] = queue_node_work(run, spec)["jobs"]
        uids = list(CrawlTask.objects.filter(run=run, status=CrawlTask.Status.WAITING_NODE).exclude(node_job_uid="").values_list("node_job_uid", flat=True).distinct())
        for uid in uids:
            members = list(CrawlTask.objects.filter(run=run, node_job_uid=uid, status=CrawlTask.Status.WAITING_NODE))
            state = nodebridge.poll(uid)
            if state.state in ("waiting", "running"):
                CrawlTask.objects.filter(pk__in=[t.pk for t in members]).update(result={"node": state.state, "message": state.message})
                out["waiting"] += len(members)
                continue
            if state.state == "done" and state.job is not None:
                n_ok, n_bad = _ingest(run, spec, state.job, members)
                out["ingested"] += n_ok
                out["failed"] += n_bad
            else:
                CrawlTask.objects.filter(pk__in=[t.pk for t in members]).update(
                    status=CrawlTask.Status.FAILED, error=(state.message or "کارِ سرورِ پردازش ناموفق بود")[:500], finished_at=timezone.now())
                out["failed"] += len(members)
                log(run.pk, "warn", f"کارِ سرورِ پردازش پایان نیافت: {state.message}")
        refresh_counters(run)
        waiting = CrawlTask.objects.filter(run=run, status=CrawlTask.Status.WAITING_NODE).count()
        if waiting == 0 and out["ingested"]:
            log(run.pk, "info", "کارهای سرورِ پردازش تمام شد و لیدها تکمیل شدند.")
    except Exception:  # noqa: BLE001 - the periodic sync must never crash the beat
        logger.exception("crawler: node sync of run %s failed", run.pk)
    return out


def _ingest(run: CrawlRun, spec: dict, job, members: list[CrawlTask]) -> tuple[int, int]:
    ok = bad = 0
    by_cand = {t.params.get("candidate_id"): t for t in members if t.kind == "node_site"}
    by_handle = {t.params.get("handle"): t for t in members if t.kind == "ig_profile"}
    now = timezone.now()
    if by_cand:
        sites = {s.get("id"): s for s in nodebridge.read_sites(job)}
        for cid, task in by_cand.items():
            site = sites.get(cid)
            cand = CrawlCandidate.objects.filter(pk=cid, run=run).first()
            if site is None or cand is None:
                task.status, task.error, task.finished_at = CrawlTask.Status.FAILED, "سرورِ پردازش پاسخی برای این سایت نفرستاد.", now
                task.save()
                bad += 1
                continue
            pages = [website.PageData(url=p.get("url", ""), kind=p.get("kind", "home"), html=p.get("html", ""), status=int(p.get("status") or 0), outcome=p.get("outcome", "ok"),
                                      note=p.get("note", ""), rendered=bool(p.get("rendered"))) for p in site.get("pages", [])]
            type_words, fit = website.words_for(list(cand.types or []), spec)
            info = website.analyze_site(pages, home_url=cand.website, type_words=type_words, fit_words=fit, robots=site.get("robots", ""))
            if info.ok:
                website.apply_to_candidate(cand, info)
                finalize.refresh_lead_from_candidate(cand, spec)
                task.status, task.result = CrawlTask.Status.DONE, {"ok": True, "pages": len(pages), "rendered": any(p.rendered for p in pages)}
                ok += 1
            else:
                cand.enriched = True
                cand.signals = {**(cand.signals or {}), "site": {"reason": info.reason or site.get("reason", ""), "pages": 0}}
                cand.save(update_fields=["enriched", "signals"])
                task.status, task.error = CrawlTask.Status.FAILED, f"سایت خوانده نشد ({info.reason or site.get('reason', '')})"
                bad += 1
            task.finished_at = now
            task.save()
    if by_handle:
        batch = nodebridge.read_json(job, "ig_batch.json") or {}
        accounts = {str(a.get("username", "")).lower(): a for a in batch.get("accounts", []) if isinstance(a, dict)}
        per = batch.get("per_account") or {}
        for handle, task in by_handle.items():
            cand = CrawlCandidate.objects.filter(pk=task.params.get("candidate_id"), run=run).first()
            acc = accounts.get(str(handle).lower())
            if acc and cand is not None:
                instagram.apply_account(cand, acc)
                finalize.refresh_lead_from_candidate(cand, spec)
                task.status, task.result = CrawlTask.Status.DONE, {"followers": acc.get("followers"), "status": per.get(handle, {}).get("status", "ok")}
                ok += 1
            else:
                why = (per.get(handle) or {}).get("status") or (batch.get("stopped") or {}).get("message") or "خوانده نشد"
                task.status, task.error = CrawlTask.Status.FAILED, f"پیج خوانده نشد ({why})"[:500]
                bad += 1
            task.finished_at = now
            task.save()
    return ok, bad


# --------------------------------------------------------------------------- the run


def mark_started(run: CrawlRun) -> bool:
    """Take the run for this worker. False when another worker has it (alive) or it is already over."""
    now = timezone.now()
    stale = now - timedelta(seconds=180)
    with transaction.atomic():
        row = CrawlRun.objects.select_for_update().filter(pk=run.pk).first() if connection_supports_for_update() else CrawlRun.objects.filter(pk=run.pk).first()
        if row is None or row.is_finished:
            return False
        if row.status == CrawlRun.Status.RUNNING and row.heartbeat_at and row.heartbeat_at > stale:
            return False
        CrawlRun.objects.filter(pk=run.pk).update(
            status=CrawlRun.Status.RUNNING, started_at=row.started_at or now, heartbeat_at=now, attempts=F("attempts") + 1, paused=False, pause_requested=False, error="",
        )
    return True


def connection_supports_for_update() -> bool:
    from django.db import connection

    return connection.features.has_select_for_update


def run_crawl(run_id: int, *, web_factory=None) -> str:
    """Execute or resume a run. Returns the status string (``completed`` | ``cancelled`` | ``failed`` | ``paused`` | ``parked`` | ``busy`` | ``missing``)."""
    run = CrawlRun.objects.select_related("mission").filter(pk=run_id).first()
    if run is None:
        return "missing"
    if run.is_finished:
        return run.status
    if run.cancel_requested and run.status == CrawlRun.Status.QUEUED:
        run.mark_finished(CrawlRun.Status.CANCELLED, "پیش از شروع لغو شد.")
        return run.status
    if not mark_started(run):
        return "busy"
    run.refresh_from_db()
    engine = Engine(run, web_factory=web_factory)
    try:
        return _drive(run, engine)
    except Interrupted as stop:
        return _on_interrupt(run, stop.kind)
    except fetchmod.BudgetExceeded as exc:
        if exc.reason == "stopped":
            cancel, pause = engine._read_flags()
            return _on_interrupt(run, "cancel" if cancel else "pause")
        log(run.pk, "warn", exc.message + " اجرا با آنچه تا اینجا پیدا شده ادامه می‌یابد.")
        return _finish_after_budget(run, engine)
    except Exception as exc:  # noqa: BLE001
        logger.exception("crawler: run %s failed", run_id)
        engine.save_usage()
        run.refresh_from_db()
        run.mark_finished(CrawlRun.Status.FAILED, f"خطای داخلی ({type(exc).__name__}). با «ادامه» دوباره اجرا می‌شود.")
        log(run.pk, "error", f"اجرا با خطای داخلی متوقف شد ({type(exc).__name__}).")
        return run.status
    finally:
        engine.close()


def _on_interrupt(run: CrawlRun, kind: str) -> str:
    run.refresh_from_db()
    refresh_counters(run)
    if kind == "cancel":
        for uid in CrawlTask.objects.filter(run=run, status=CrawlTask.Status.WAITING_NODE).exclude(node_job_uid="").values_list("node_job_uid", flat=True).distinct():
            nodebridge.cancel(uid)
        CrawlTask.objects.filter(run=run, status__in=[CrawlTask.Status.PENDING, CrawlTask.Status.WAITING_NODE, CrawlTask.Status.RUNNING]).update(status=CrawlTask.Status.SKIPPED, error="اجرا لغو شد")
        run.mark_finished(CrawlRun.Status.CANCELLED, "به درخواستِ کاربر متوقف شد؛ آنچه پیدا شده بود می‌ماند.")
        log(run.pk, "info", "اجرا لغو شد.")
        return run.status
    CrawlTask.objects.filter(run=run, status=CrawlTask.Status.RUNNING).update(status=CrawlTask.Status.PENDING)
    CrawlRun.objects.filter(pk=run.pk).update(status=CrawlRun.Status.QUEUED, paused=True, pause_requested=False, message="متوقفِ موقت؛ با «ادامه» از همین‌جا ادامه می‌یابد.")
    log(run.pk, "info", "اجرا متوقفِ موقت شد.")
    return "paused"


def _finish_after_budget(run: CrawlRun, engine: Engine) -> str:
    """A budget ran out: stop discovering / enriching, but still turn what was found into leads."""
    CrawlTask.objects.filter(run=run, status=CrawlTask.Status.PENDING).exclude(stage__in=["node", "ig"]).update(status=CrawlTask.Status.SKIPPED, error="سقفِ بودجه")
    return _finalize_and_finish(run, engine)


def _drive(run: CrawlRun, engine: Engine) -> str:
    spec = engine.spec
    stage = run.stage if run.stage in STAGE_ORDER else "plan"
    # ---- plan
    if stage == "plan":
        specs = plan_discovery(spec)
        n = add_task_specs(run, specs)
        set_state(run.pk, stage="discover")
        log(run.pk, "info", f"برنامه ساخته شد: {n} کارِ پیدا کردن ({', '.join(sorted({s.source for s in specs})) or 'هیچ'}).")
        if n == 0 and not spec.get("directory_urls"):
            log(run.pk, "warn", "هیچ کاری برای پیدا کردن برنامه‌ریزی نشد؛ نوعِ کسب‌وکار، شهر و منبع‌ها را بررسی کنید.")
        stage = "discover"
    # ---- discover
    if stage == "discover":
        res = engine.drain("discover")
        if res == "parked":
            return _park(run, engine)
        set_state(run.pk, stage="dedupe")
        stage = "dedupe"
    # ---- dedupe + plan the enrichment
    if stage == "dedupe":
        engine.check_interrupt()
        refresh_counters(run)
        total = CrawlCandidate.objects.filter(run=run).count()
        log(run.pk, "info", f"پیدا کردن تمام شد: {CrawlRun.objects.get(pk=run.pk).found_count} مورد، پس از یکی‌کردنِ تکراری‌ها {total} کسب‌وکار.")
        if engine.out_of_area:
            log(run.pk, "info", f"{engine.out_of_area} مورد کنار گذاشته شد چون نشانی یا جایگاهشان شهرِ دیگری بود (نه شهرهای این مأموریت).")
        if (spec.get("sources") or {}).get("website", True) or (spec.get("sources") or {}).get("instagram"):
            plan_enrichment(engine)
        set_state(run.pk, stage="enrich")
        stage = "enrich"
    # ---- enrich
    if stage == "enrich":
        res = engine.drain("enrich")
        if res == "parked":
            return _park(run, engine)
        queued = queue_node_work(run, spec)
        if queued["waiting"]:
            log(run.pk, "info", f"{queued['waiting']} کار به سرورِ پردازش سپرده شد/می‌ماند؛ اجرا منتظرشان نمی‌ماند.")
        set_state(run.pk, stage="finalize")
        stage = "finalize"
    # ---- finalize
    return _finalize_and_finish(run, engine)


def _park(run: CrawlRun, engine: Engine) -> str:
    """Only delayed tasks are left (a busy public service): sleep without holding a worker and let the beat wake the run."""
    soon = CrawlTask.objects.filter(run=run, status=CrawlTask.Status.PENDING, not_before__isnull=False).order_by("not_before").first()
    until = soon.not_before if soon else timezone.now() + timedelta(minutes=10)
    engine.save_usage()
    CrawlRun.objects.filter(pk=run.pk).update(status=CrawlRun.Status.QUEUED, usage={**(run.usage or {}), "budget": engine.budget.snapshot(), "out_of_area": engine.out_of_area, "parked_until": until.isoformat()},
                                              message="منتظرِ سرویسِ شلوغِ بیرونی؛ خودکار ادامه می‌یابد.")
    log(run.pk, "info", f"سرویسِ بیرونی شلوغ است؛ اجرا تا {timezone.localtime(until).strftime('%H:%M')} می‌خوابد و خودش ادامه می‌دهد.")
    return "parked"


def _finalize_and_finish(run: CrawlRun, engine: Engine) -> str:
    run.refresh_from_db()
    set_state(run.pk, stage="finalize", message="ساختنِ لیدها")
    spec = engine.spec
    out = finalize.finalize_run(run, spec, stop=engine.should_stop, log=lambda lv, m: log(run.pk, lv, m))
    engine.check_interrupt()
    CrawlRun.objects.filter(pk=run.pk).update(created_count=out["created"], merged_count=out["merged"], skipped_count=out["skipped"])
    engine.save_usage()
    refresh_counters(run)
    run.refresh_from_db()
    # the leads exist now: a late node answer (a JavaScript site, an Instagram page) refreshes them through ``sync_node``
    CrawlRun.objects.filter(pk=run.pk).update(stage="done", finished_ok=True, message="تمام شد" + (f" (برای {run.tasks_waiting} کار منتظرِ سرورِ پردازش)" if run.tasks_waiting else ""))
    run.refresh_from_db()
    run.mark_finished(CrawlRun.Status.COMPLETED)
    _after_run(run)
    log(run.pk, "info", f"اجرا تمام شد: {out['created']} لیدِ تازه، {out['merged']} ادغام، {out['skipped']} ردشده.")
    return run.status


def _after_run(run: CrawlRun) -> None:
    mission = run.mission
    now = timezone.now()
    updates = {"last_run_at": now}
    if mission.schedule_days and mission.enabled:
        updates["next_run_at"] = now + timedelta(days=mission.schedule_days)
    CrawlMission.objects.filter(pk=mission.pk).update(**updates)
