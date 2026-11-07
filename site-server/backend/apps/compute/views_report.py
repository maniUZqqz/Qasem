"""«گزارشِ سرورهای پردازش» (فقط کارکنان):

  GET /api/v1/compute/report/                 یک JSON برای کلِ صفحه (سرورها، نوبت‌های اتصال، منابع، آمارِ کارها، خطاها، دانلودها)
  GET /api/v1/compute/report/logs/            لاگِ سرورها با فیلتر و صفحه‌بندی
  GET /api/v1/compute/report/export.csv       خروجیِ CSV (jobs | sessions | samples | logs | errors | downloads)

بازه‌ها `from=YYYY-MM-DD&to=YYYY-MM-DD` به **وقتِ تهران** و شاملِ روزِ پایان‌اند؛ پیش‌فرض ۷ روزِ آخر و سقف ۹۰ روز.
کارهای «wait.node» (جایگزینِ داخلیِ کارهای Celeryِ منتظر) در هیچ آماری نمی‌آیند.
"""
from __future__ import annotations

import csv
import itertools
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import Coalesce
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import exceptions, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import queue as QV
from . import report as RP
from . import services as SV
from .models import ComputeJob, ComputeNode, ComputeNodeLog, ComputeSettings
from .models_report import ComputeNodeSample, ComputeNodeSession
from .park import PARK_KIND
from .updates import latest, update_state

S = ComputeJob.State
MAX_DAYS = 90
#: فقط ۵۰۰ خطِ آخرِ هر گره در پایگاه می‌ماند (api.node_log)؛ گزارش همان را نشان می‌دهد و می‌گوید
LOG_KEEP = 500
MAX_CSV_ROWS = 50_000
ERROR_LEVELS = ("ERROR", "CRITICAL", "FATAL")
DOWNLOAD_KINDS = ("ollama.pull", "node.models")
SERVICES = ("comfyui", "comfy_bridge", "photo", "video", "voice", "ollama", "blender")
MAX_SESSIONS = 200
MAX_SEGMENTS = 600
DAY = timedelta(days=1)

_DAY_RX = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


# ───────────────────────────── ورودی‌ها

def _parse_day(value, field: str) -> date:
    text = str(value or "").strip()
    try:
        if not _DAY_RX.fullmatch(text):
            raise ValueError(text)
        return date.fromisoformat(text)
    except ValueError:
        label = "شروع" if field == "from" else "پایان"
        raise exceptions.ValidationError({field: f"تاریخِ {label} درست نیست؛ مثل 2026-11-07 بنویسید."})


def _midnight(day: date) -> datetime:
    """نیمه‌شبِ تهرانِ آن روز به UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=dt_timezone.utc) - SV.TEHRAN_OFFSET


def parse_range(params, now=None, required: bool = True):
    """from/to (وقتِ تهران، شاملِ روزِ پایان) یا days=N (N روزِ آخر، با امروز) ⇒ {from_d, to_d, start, end, days}.
    نادرست ⇒ ValidationError (۴۰۰). `to` در آینده به امروز می‌رسد؛ بازهٔ بیش از ۹۰ روز رد می‌شود.
    required=False و بی‌تاریخ ⇒ None."""
    now = now or timezone.now()
    today = SV.tehran_now(now).date()
    raw_from, raw_to, raw_days = params.get("from"), params.get("to"), params.get("days")
    if not raw_from and not raw_to and not raw_days and not required:
        return None
    if raw_days and not raw_from and not raw_to:
        try:
            n = int(str(raw_days).strip())
        except ValueError:
            raise exceptions.ValidationError({"days": "تعدادِ روز باید عدد باشد."})
        if not 1 <= n <= MAX_DAYS:
            raise exceptions.ValidationError({"days": f"تعدادِ روز باید بین ۱ تا {MAX_DAYS} باشد."})
        raw_from, raw_to = (today - timedelta(days=n - 1)).isoformat(), today.isoformat()
    to_d = _parse_day(raw_to, "to") if raw_to else None
    from_d = _parse_day(raw_from, "from") if raw_from else None
    if to_d is None:
        to_d = today
    if to_d > today:
        to_d = today
    if from_d is None:
        from_d = to_d - timedelta(days=6)
    if from_d > today:
        raise exceptions.ValidationError({"from": "تاریخِ شروع در آینده است."})
    if from_d > to_d:
        raise exceptions.ValidationError({"from": "تاریخِ شروع باید پیش از تاریخِ پایان باشد."})
    days = (to_d - from_d).days + 1
    if days > MAX_DAYS:
        raise exceptions.ValidationError({"to": f"بازه نباید بیشتر از {MAX_DAYS} روز باشد."})
    start = _midnight(from_d)
    end = min(_midnight(to_d + DAY), now)
    return {"from_d": from_d, "to_d": to_d, "start": start, "end": max(end, start), "days": days}


def _node_id(params):
    raw = params.get("node")
    if raw in (None, "", "all"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise exceptions.ValidationError({"node": "شمارهٔ سرور درست نیست."})


def _int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _short(text: str, n: int = 220) -> str:
    for line in str(text or "").strip().splitlines():
        if line.strip():
            return line.strip()[:n]
    return ""


# ───────────────────────────── بخش‌های گزارش

def _resources(caps: dict) -> dict:
    v = RP.sample_values(caps)
    disk_used = (v["disk_total_gb"] - v["disk_free_gb"]) if v["disk_total_gb"] and v["disk_free_gb"] is not None else None
    return {**v,
            "ram_used_pct": RP.ram_used_pct(v["ram_free_mb"], v["ram_total_mb"]),
            "vram_used_pct": RP.used_pct(v["vram_used_mb"], v["vram_total_mb"]),
            "disk_used_pct": RP.used_pct(disk_used, v["disk_total_gb"])}


def _text_list(value, n: int, width: int) -> list[str]:
    return [str(x)[:width] for x in value if x][:n] if isinstance(value, list) else []


def _models(caps: dict) -> dict:
    """آنچه روی سرور نصب است، از گزارشِ خودِ سرور (فهرست‌ها کوتاه می‌شوند؛ هر نوعِ ورودی تحمل می‌شود)."""
    dm = caps.get("models") if isinstance(caps.get("models"), dict) else {}
    packages = []
    raw_pk = dm.get("packages")
    for key, row in (raw_pk.items() if isinstance(raw_pk, dict) else []):
        if isinstance(row, dict):
            packages.append({"key": str(key)[:60], "title": str(row.get("title") or key)[:80], "installed": bool(row.get("installed")),
                             "optional": bool(row.get("optional")), "missing_mb": RP.num(row.get("missing_mb"), 0, 1e9) or 0,
                             "total_mb": RP.num(row.get("total_mb"), 0, 1e9) or 0})
    packages = packages[:60]
    comfy = {}
    if isinstance(caps.get("comfy_models"), dict):
        for label, items in list(caps["comfy_models"].items())[:20]:
            if isinstance(items, list):
                comfy[str(label)[:40]] = _text_list(items, 60, 120)
    audio = {str(k)[:40]: bool(v) for k, v in list(caps["audio"].items())[:20]} if isinstance(caps.get("audio"), dict) else {}
    return {"ollama": _text_list(caps.get("ollama_models"), 100, 100),
            "ollama_stale": bool(caps.get("ollama_models_stale") or caps.get("ollama_models_source") == "disk"),
            "comfy": comfy, "comfy_count": sum(len(x) for x in comfy.values()), "audio": audio,
            "voice_clone": bool(caps.get("voice_clone")), "packages": packages,
            "download_running": bool(dm.get("running")), "download_error": str(dm.get("error") or "")[:300]}


def _job_groups(rng, node_id=None):
    """یک پرس‌وجو برای همهٔ آمارِ کارها: (kind، node، state) ⇐ شمار و جمعِ زمان‌ها. wait.node نمی‌آید."""
    qs = ComputeJob.objects.exclude(kind=PARK_KIND).filter(created_at__gte=rng["start"], created_at__lt=rng["end"])
    if node_id:
        qs = qs.filter(node_id=node_id)
    done = Q(state=S.COMPLETED, run_s__isnull=False)
    return list(qs.values("kind", "node_id", "state").annotate(
        n=Count("id"), run_sum=Sum("run_s", filter=done), run_n=Count("run_s", filter=done),
        wait_sum=Sum("waited_s"), wait_n=Count("waited_s")))


def _blank_stat():
    return {"count": 0, "success": 0, "failed": 0, "cancelled": 0, "running": 0, "waiting": 0,
            "_run_sum": 0.0, "_run_n": 0, "_wait_sum": 0.0, "_wait_n": 0}


def _add(stat, g):
    stat["count"] += g["n"]
    key = {S.COMPLETED: "success", S.FAILED: "failed", S.CANCELLED: "cancelled", S.QUEUED: "waiting",
           S.CLAIMED: "running", S.RUNNING: "running"}.get(g["state"])
    if key:
        stat[key] += g["n"]
    stat["_run_sum"] += g["run_sum"] or 0.0
    stat["_run_n"] += g["run_n"] or 0
    stat["_wait_sum"] += g["wait_sum"] or 0.0
    stat["_wait_n"] += g["wait_n"] or 0


def _finish(stat) -> dict:
    out = {k: v for k, v in stat.items() if not k.startswith("_")}
    out["avg_run_s"] = round(stat["_run_sum"] / stat["_run_n"], 1) if stat["_run_n"] else None
    out["avg_wait_s"] = round(stat["_wait_sum"] / stat["_wait_n"], 1) if stat["_wait_n"] else None
    decided = out["success"] + out["failed"]
    out["success_rate"] = round(100.0 * out["success"] / decided, 1) if decided else None
    return out


def _jobs_section(rng, node_id=None):
    groups = _job_groups(rng, node_id)
    per_kind: dict[str, dict] = defaultdict(_blank_stat)
    per_node: dict = defaultdict(_blank_stat)
    per_node_kind: dict = defaultdict(lambda: defaultdict(_blank_stat))
    total = _blank_stat()
    for g in groups:
        _add(per_kind[g["kind"]], g)
        _add(total, g)
        if g["node_id"] is not None:
            _add(per_node[g["node_id"]], g)
            _add(per_node_kind[g["node_id"]][g["kind"]], g)
    # p50 / p95 ِ زمانِ اجرا (فقط کارهای تمام‌شده): یک پرس‌وجوی سبک با سقف
    runs: dict[str, list] = defaultdict(list)
    qs = ComputeJob.objects.exclude(kind=PARK_KIND).filter(created_at__gte=rng["start"], created_at__lt=rng["end"],
                                                           state=S.COMPLETED, run_s__isnull=False)
    if node_id:
        qs = qs.filter(node_id=node_id)
    for kind, run_s in qs.values_list("kind", "run_s")[:50_000]:
        runs[kind].append(run_s)

    def rows_of(stats: dict, with_pct: bool) -> list[dict]:
        rows = []
        for kind, stat in stats.items():
            row = _finish(stat)
            row.update({"kind": kind, "kind_label": QV.kind_label(kind)})
            if with_pct:
                vals = sorted(runs.get(kind, []))
                row.update({"p50_run_s": round(RP.percentile(vals, 50), 1) if vals else None,
                            "p95_run_s": round(RP.percentile(vals, 95), 1) if vals else None})
            rows.append(row)
        rows.sort(key=lambda r: (-r["count"], r["kind"]))
        return rows

    return {"per_kind": rows_of(per_kind, True), "totals": _finish(total),
            "per_node": {nid: _finish(st) for nid, st in per_node.items()},
            "per_node_kind": {nid: rows_of(kinds, False) for nid, kinds in per_node_kind.items()}}


def _queue_now() -> dict:
    rows = (ComputeJob.objects.exclude(kind=PARK_KIND).filter(state__in=[S.QUEUED, S.CLAIMED, S.RUNNING])
            .values("state").annotate(n=Count("id"), oldest=Min(Coalesce("queued_at", "created_at"))))
    waiting = running = 0
    oldest = None
    for r in rows:
        if r["state"] == S.QUEUED:
            waiting += r["n"]
            oldest = r["oldest"]
        else:
            running += r["n"]
    wait_s = int((timezone.now() - oldest).total_seconds()) if oldest else None
    return {"waiting": waiting, "running": running, "oldest_wait_s": wait_s,
            "oldest_wait_text": QV.human_duration(wait_s) if wait_s is not None else ""}


def _error_items(rng, node_id=None, limit: int = 50) -> list[dict]:
    """ناموفق‌های اخیر (کار) + خطاهای لاگ، تازه‌ترین اول، هرکدام با توضیحِ ساده."""
    items = []
    jobs = ComputeJob.objects.exclude(kind=PARK_KIND).filter(state=S.FAILED, finished_at__gte=rng["start"],
                                                             finished_at__lt=rng["end"])
    if node_id:
        jobs = jobs.filter(node_id=node_id)
    for j in jobs.select_related("node").order_by("-finished_at")[:limit]:
        text = (j.error or j.message or "خطای نامشخص").strip()
        items.append({"source": "job", "at": j.finished_at, "node": j.node.name if j.node else None, "node_id": j.node_id,
                      "level": "ERROR", "kind": j.kind, "kind_label": QV.kind_label(j.kind), "uid": str(j.uid),
                      "short": _short(text), "text": text[:2000], "explain": RP.explain(text)})
    logs = ComputeNodeLog.objects.filter(level__in=ERROR_LEVELS, created_at__gte=rng["start"], created_at__lt=rng["end"])
    if node_id:
        logs = logs.filter(node_id=node_id)
    for r in logs.select_related("node").order_by("-created_at")[:limit]:
        items.append({"source": "log", "at": r.logged_at or r.created_at, "node": r.node.name, "node_id": r.node_id,
                      "level": r.level, "kind": None, "kind_label": "لاگِ سرور", "uid": None,
                      "short": _short(r.message), "text": r.message[:2000], "explain": RP.explain(r.message)})
    items.sort(key=lambda x: x["at"], reverse=True)
    return items


def _download_q() -> Q:
    return Q(category="download") | Q(kind__in=DOWNLOAD_KINDS)


def _progress_numbers(done, total, speed_bps):
    """(درصد، ثانیهٔ باقی‌مانده) از بایتِ گرفته‌شده/کل/سرعت — ورودی‌ها از گره می‌آیند و هر چیزی ممکن است باشند."""
    done, total, speed = RP.num(done, 0, 1e15), RP.num(total, 0, 1e15), RP.num(speed_bps, 0, 1e12)
    pct = round(min(100.0, 100.0 * done / total), 1) if done is not None and total else None
    eta = int((total - done) / speed) if speed and total and done is not None and total > done else None
    return done, total, speed, pct, eta


def _job_download_item(j: ComputeJob) -> dict:
    live = (j.result or {}).get("live")
    live = live if isinstance(live, dict) else {}
    mbs = RP.num(live.get("speed_mbs"), 0, 1e6)
    done, total, speed, pct, eta = _progress_numbers(live.get("done"), live.get("total"), mbs * 1_000_000 if mbs is not None else None)
    if pct is None and j.progress:
        pct = round(j.progress * 100, 1)
    return {"source": "job", "uid": str(j.uid), "title": QV.title_of(j), "kind": j.kind, "node": j.node.name if j.node else None,
            "state": j.state, "percent": pct, "bytes_done": done, "bytes_total": total, "speed_bps": speed, "eta_s": eta,
            "phase": str(live.get("phase") or "")[:30], "attempt": RP.num(live.get("attempt"), 0, 1e4),
            "max_attempts": RP.num(live.get("max_attempts"), 0, 1e4), "message": j.message, "started": j.claimed_at}


def _node_download_item(n: ComputeNode, dm: dict) -> dict:
    """دانلودِ پس‌زمینهٔ خودِ سرور (Download-Models) از گزارشِ heartbeat (caps["models"]["progress"])."""
    pr = dm.get("progress") if isinstance(dm.get("progress"), dict) else {}
    done, total, speed, pct, eta = _progress_numbers(pr.get("bytes_done"), pr.get("bytes_total"),
                                                     RP.num(pr.get("speed_bps"), 0, 1e12))
    cur = pr.get("current")
    if isinstance(cur, dict):        # شکلِ جزئی: {id, title, done, total}
        name, cur_done, cur_total = cur.get("title") or cur.get("id"), cur.get("done"), cur.get("total")
    else:                            # شکلی که عاملِ فعلی می‌فرستد: نامِ مورد + current_done/current_total
        name, cur_done, cur_total = cur, pr.get("current_done"), pr.get("current_total")
    pkgs = _text_list(pr.get("packages"), 8, 40)
    failed = []
    for f in (pr.get("failed") or [])[:5] if isinstance(pr.get("failed"), list) else []:
        if isinstance(f, dict):
            failed.append(f"{str(f.get('id') or '')[:60]}: {str(f.get('reason') or '')[:120]}")
    return {
        "source": "node", "uid": None, "node": n.name, "kind": "node.models",
        "title": "دانلودِ مدل‌های سرور" + (": " + "، ".join(pkgs) if pkgs else ""),
        "state": "RUNNING", "percent": pct, "bytes_done": done, "bytes_total": total, "speed_bps": speed, "eta_s": eta,
        "phase": "", "attempt": None, "max_attempts": None, "message": str(name or "")[:120],
        "current_done": RP.num(cur_done, 0, 1e15), "current_total": RP.num(cur_total, 0, 1e15), "failed": failed,
        "items_done": RP.num(pr.get("items_done"), 0, 1e6), "items_total": RP.num(pr.get("items_total"), 0, 1e6), "started": None}


def _downloads_section(rng, nodes: list, node_id=None, now=None) -> dict:
    now = now or timezone.now()
    base = ComputeJob.objects.filter(_download_q()).exclude(kind=PARK_KIND).select_related("node", "store")
    picked = [n for n in nodes if n.pk == node_id] if node_id else nodes
    if node_id:
        base = base.filter(Q(node_id=node_id) | Q(node_wanted=picked[0].name)) if picked else base.filter(node_id=node_id)
    active = [_job_download_item(j) for j in base.filter(state__in=[S.CLAIMED, S.RUNNING]).order_by("-claimed_at")[:50]]
    known = {(a["node"], a["kind"]) for a in active if a["percent"] is not None}
    for n in picked:
        dm = (n.capabilities or {}).get("models")
        if isinstance(dm, dict) and dm.get("running") and (n.name, "node.models") not in known:
            active.append(_node_download_item(n, dm))
    queued = list(base.filter(state=S.QUEUED).order_by("not_before", "priority", "created_at")[:50])
    waiting = []
    if queued:
        positions = QV._positions(list(ComputeJob.objects.filter(state=S.QUEUED).only("id", "priority", "created_at", "kind", "payload")))
        for j in queued:
            row = QV.job_row(j, now, nodes, positions)
            waiting.append({"uid": row["uid"], "title": row["title"], "kind": j.kind, "node_wanted": row["node_wanted"],
                            "scheduled_for": j.not_before, "window": j.window, "status_text": row["status_text"],
                            "wait_reason": row["wait_reason"], "waiting_s": row["waiting_s"], "created": j.created_at})
    # تاریخچه: ساخته‌شده یا پایان‌یافته در بازه + هرچه زمان‌بندی داشته (not_before / window) و در بازه ثبت شده
    hist_q = (Q(finished_at__gte=rng["start"], finished_at__lt=rng["end"], state__in=ComputeJob.FINAL)
              | Q(created_at__gte=rng["start"], created_at__lt=rng["end"], state__in=ComputeJob.FINAL))
    history = [_download_history_item(j) for j in base.filter(hist_q).order_by("-created_at")[:100]]
    return {"active": active, "waiting": waiting, "history": history}


def _download_history_item(j: ComputeJob) -> dict:
    result = j.result or {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    live = result.get("live") if isinstance(result.get("live"), dict) else {}
    size = RP.num(meta.get("bytes"), 0, 1e15) or RP.num(live.get("total"), 0, 1e15) or RP.num((j.payload or {}).get("expected_bytes"), 0, 1e15)
    speed = round(size / j.run_s) if size and j.run_s else None
    return {"uid": str(j.uid), "title": QV.title_of(j), "kind": j.kind, "node": j.node.name if j.node else None,
            "state": j.state, "state_label": j.get_state_display(), "started": j.claimed_at, "finished": j.finished_at,
            "created": j.created_at, "scheduled_for": j.not_before, "window": j.window,
            "run_s": j.run_s, "bytes": size, "speed_bps": speed, "error": _short(j.error) if j.state == S.FAILED else "",
            "explain": RP.explain(j.error)["what"] if j.state == S.FAILED and j.error else ""}


def _series_and_sessions(rng, nodes: list, now, retention_days: int):
    ids = [n.pk for n in nodes]
    lo, hi = rng["start"].timestamp(), rng["end"].timestamp()
    sess = defaultdict(list)
    rows = (ComputeNodeSession.objects.filter(node_id__in=ids, started_at__lte=rng["end"])
            .filter(Q(ended_at__gte=rng["start"]) | Q(ended_at__isnull=True, last_beat__gte=rng["start"]))
            .order_by("started_at").values_list("node_id", "started_at", "last_beat", "ended_at", "agent", "hostname", "gpu"))
    for node_id, started, last_beat, ended, agent, hostname, gpu in rows:
        sess[node_id].append((started, last_beat, ended, agent))
    pts: dict = defaultdict(lambda: {m: [] for m in RP.METRICS})
    for (node_id, at, ram_free, ram_total, vram_used, vram_total, disk_free, gpu_util, gpu_temp
         ) in (ComputeNodeSample.objects.filter(node_id__in=ids, at__gte=rng["start"], at__lte=rng["end"])
               .values_list("node_id", "at", "ram_free_mb", "ram_total_mb", "vram_used_mb", "vram_total_mb", "disk_free_gb",
                            "gpu_util_pct", "gpu_temp_c").iterator()):
        t = at.timestamp()
        d = pts[node_id]
        ram = RP.ram_used_pct(ram_free, ram_total)
        if ram is not None:
            d["ram_used_pct"].append((t, ram))
        vram = RP.used_pct(vram_used, vram_total)
        if vram is not None:
            d["vram_used_pct"].append((t, vram))
        if disk_free is not None:
            d["disk_free_gb"].append((t, disk_free))
        if gpu_util is not None:
            d["gpu_util_pct"].append((t, gpu_util))
        if gpu_temp is not None:
            d["gpu_temp_c"].append((t, gpu_temp))
    tracking = ComputeNodeSession.objects.aggregate(m=Min("started_at"))["m"]
    floor = (now - timedelta(days=retention_days)).timestamp()
    out = {}
    for n in nodes:
        mine = sess.get(n.pk, [])
        spans = RP.session_spans([(a, b, c) for a, b, c, _ in mine], now)
        merged = RP.merge_spans(spans)
        since = max(lo, floor, n.created_at.timestamp(), tracking.timestamp() if tracking else hi)
        uptime = RP.uptime_stats(RP.clip_spans(merged, since, hi), since, hi) if tracking else RP.uptime_stats([], hi, hi)
        uptime.update({"sessions": len(mine), "since": datetime.fromtimestamp(since, tz=dt_timezone.utc) if tracking else None,
                       "partial": bool(tracking and since > lo + 60)})
        segments = [[int(s), int(e)] for s, e in RP.clip_spans(merged, lo, hi)][-MAX_SEGMENTS:]
        listing = []
        for (started, last_beat, ended, agent), (s, e, ongoing) in reversed(list(zip(mine, spans))):
            listing.append({"started": started, "ended": None if ongoing else datetime.fromtimestamp(e, tz=dt_timezone.utc),
                            "minutes": round((e - s) / 60.0, 1), "ongoing": ongoing, "agent": agent})
        out[n.pk] = {"uptime": uptime, "segments": segments, "sessions": listing[:MAX_SESSIONS],
                     "sessions_truncated": len(listing) > MAX_SESSIONS,
                     "series": {m: RP.downsample(pts[n.pk][m], lo, hi) if n.pk in pts else [] for m in RP.METRICS}}
    return out, tracking


def build_report(rng, node_id=None, now=None) -> dict:
    now = now or timezone.now()
    all_nodes = list(ComputeNode.objects.all())
    picked = all_nodes
    if node_id is not None:
        picked = [n for n in all_nodes if n.pk == node_id]
        if not picked:
            raise exceptions.ValidationError({"node": "سروری با این شماره نیست."})
    cfg = ComputeSettings.get()
    last = latest()
    timeline, tracking = _series_and_sessions(rng, picked, now, cfg.retention_days)
    jobs = _jobs_section(rng, node_id)
    log_counts = dict(ComputeNodeLog.objects.filter(node_id__in=[n.pk for n in picked]).values_list("node_id")
                      .annotate(n=Count("id")))
    nodes = []
    for n in picked:
        caps = n.capabilities or {}
        state = update_state(caps, last)
        res = _resources(caps)
        nodes.append({
            "id": n.pk, "name": n.name, "enabled": n.enabled, "online": n.online, "last_seen": n.last_seen,
            "created": n.created_at, "agent": caps.get("agent"), "agent_latest": state["agent_latest"],
            "update_waiting": state["update_waiting"], "hostname": caps.get("hostname"), "gpu": caps.get("gpu"),
            "services": {k: bool(caps.get(k)) for k in SERVICES}, "models": _models(caps), "resources": res,
            "resources_known": {"ram": res["ram_used_pct"] is not None, "vram": res["vram_used_pct"] is not None,
                                "disk": res["disk_free_gb"] is not None, "gpu_util": res["gpu_util_pct"] is not None,
                                "gpu_temp": res["gpu_temp_c"] is not None},
            "jobs": jobs["per_node"].get(n.pk) or _finish(_blank_stat()),
            "jobs_by_kind": jobs["per_node_kind"].get(n.pk) or [],
            "logs": {"count": log_counts.get(n.pk, 0), "kept_max": LOG_KEEP, "truncated": log_counts.get(n.pk, 0) >= LOG_KEEP},
            **timeline[n.pk]})
    versions: dict = defaultdict(list)
    for n in all_nodes:
        versions[str((n.capabilities or {}).get("agent") or "")].append(n.name)
    errors = _error_items(rng, node_id, 50)
    groups = Counter(e["explain"]["code"] for e in errors)
    by_code = {e["explain"]["code"]: e["explain"] for e in errors}
    return {
        "generated_at": now,
        "range": {"from": rng["from_d"].isoformat(), "to": rng["to_d"].isoformat(), "start": rng["start"], "end": rng["end"],
                  "days": rng["days"], "retention_days": cfg.retention_days, "tracking_start": tracking, "max_days": MAX_DAYS},
        "agent_latest": last.get("version"),
        "site_version": str(getattr(settings, "NM_VERSION", "") or ""),
        "nodes": nodes,
        "jobs": {"per_kind": jobs["per_kind"], "totals": jobs["totals"]},
        "queue_now": _queue_now(),
        "errors": errors,
        "error_groups": [{"code": c, "count": k, "what": by_code[c]["what"]} for c, k in groups.most_common(5)],
        "downloads": _downloads_section(rng, all_nodes, node_id, now),
        "agent_versions": [{"version": v or "نامعلوم", "nodes": names, "latest": bool(v) and v == last.get("version")}
                           for v, names in sorted(versions.items())],
        "logs_note": {"kept_per_node": LOG_KEEP, "any_truncated": any(x["logs"]["truncated"] for x in nodes)},
    }


# ───────────────────────────── نماها

@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def report(request):
    rng = parse_range(request.query_params)
    return Response(build_report(rng, _node_id(request.query_params)))


def _level_q(level: str) -> Q | None:
    level = (level or "").strip().lower()
    if not level or level == "all":
        return None
    groups = {"error": ERROR_LEVELS, "warning": ("WARNING", "WARN"), "info": ("INFO",), "debug": ("DEBUG",)}
    return Q(level__in=groups.get(level, (level.upper()[:10],)))


def _log_qs(request, rng):
    """لاگ‌ها با فیلترِ سرور/سطح/متن و بازهٔ rng (None = همهٔ لاگ‌های نگه‌داشته‌شده)."""
    qp = request.query_params
    qs = ComputeNodeLog.objects.all()
    node_id = _node_id(qp)
    if node_id:
        qs = qs.filter(node_id=node_id)
    lq = _level_q(qp.get("level"))
    if lq is not None:
        qs = qs.filter(lq)
    q = (qp.get("q") or "").strip()[:100]
    if q:
        qs = qs.filter(message__icontains=q)
    if rng:
        qs = qs.filter(created_at__gte=rng["start"], created_at__lt=rng["end"])
    return qs, node_id


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def logs(request):
    qp = request.query_params
    qs, node_id = _log_qs(request, parse_range(qp, required=False))
    limit, offset = _int(qp.get("limit"), 200, 1, 500), _int(qp.get("offset"), 0, 0, 100_000)
    total = qs.count()
    rows = []
    for r in qs.select_related("node").order_by("-created_at", "-id")[offset:offset + limit]:
        rows.append({"id": r.pk, "node": r.node.name, "node_id": r.node_id, "level": r.level, "message": r.message[:4000],
                     "ts": r.logged_at or r.created_at, "received": r.created_at,
                     "explain": RP.explain(r.message) if r.level in ERROR_LEVELS else None})
    scope = ComputeNodeLog.objects.filter(node_id=node_id) if node_id else ComputeNodeLog.objects.all()
    per_node = dict(scope.values_list("node_id").annotate(n=Count("id")))
    oldest = scope.aggregate(m=Min("created_at"))["m"]
    return Response({"total": total, "limit": limit, "offset": offset, "lines": rows,
                     "kept_per_node": LOG_KEEP, "truncated": any(n >= LOG_KEEP for n in per_node.values()), "oldest": oldest})


# ───────────────────────────── CSV

class _Echo:
    def write(self, value):
        return value


def _cell(value):
    """سلولِ امن برای Excel: متنی که با = + - @ (یا tab/CR) شروع شود با ' قفل می‌شود (تزریقِ فرمول)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    if isinstance(value, datetime):
        return SV.tehran_now(value).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            value = round(value, 2)
            return int(value) if value == int(value) else value      # «4000.0» ⇒ «4000»
        return value
    text = str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def _stream(header, rows, filename: str) -> StreamingHttpResponse:
    writer = csv.writer(_Echo())
    cap = MAX_CSV_ROWS

    def gen():
        yield "﻿"                                     # BOM: Excel فارسی را درست می‌خواند
        yield writer.writerow(header)
        count = 0
        for row in itertools.islice(rows, cap + 1):      # یک ردیفِ اضافه فقط برای فهمیدنِ «بیشتر هم بود»
            if count == cap:
                yield writer.writerow([f"… فقط {cap} ردیفِ اول؛ بازه یا سرور را کوچک‌تر کنید."])
                break
            yield writer.writerow([_cell(c) for c in row])
            count += 1

    resp = StreamingHttpResponse(gen(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["Cache-Control"] = "no-store"
    return resp


def _rows_jobs(rng, node_id):
    qs = ComputeJob.objects.exclude(kind=PARK_KIND).filter(created_at__gte=rng["start"], created_at__lt=rng["end"])
    if node_id:
        qs = qs.filter(node_id=node_id)
    labels = dict(S.choices)
    for j in qs.select_related("node").order_by("created_at").iterator(chunk_size=2000):
        yield [str(j.uid), QV.kind_label(j.kind), j.kind, labels.get(j.state, j.state), j.node.name if j.node else "",
               j.created_at, j.claimed_at, j.finished_at, j.waited_s, j.run_s, j.attempts, j.lost_count, j.category,
               (j.error or "")[:500]]


def _rows_sessions(rng, node_id):
    qs = ComputeNodeSession.objects.filter(started_at__lte=rng["end"]).filter(
        Q(ended_at__gte=rng["start"]) | Q(ended_at__isnull=True, last_beat__gte=rng["start"]))
    if node_id:
        qs = qs.filter(node_id=node_id)
    now = timezone.now()
    for s in qs.select_related("node").order_by("node__name", "started_at").iterator(chunk_size=2000):
        (a, e, ongoing), = RP.session_spans([(s.started_at, s.last_beat, s.ended_at)], now)
        yield [s.node.name, s.started_at, None if ongoing else datetime.fromtimestamp(e, tz=dt_timezone.utc),
               round((e - a) / 60.0, 1), ongoing, s.agent, s.hostname, s.gpu]


def _rows_samples(rng, node_id):
    qs = ComputeNodeSample.objects.filter(at__gte=rng["start"], at__lte=rng["end"])
    if node_id:
        qs = qs.filter(node_id=node_id)
    for s in qs.select_related("node").order_by("node__name", "at").iterator(chunk_size=2000):
        yield [s.node.name, s.at, "میانگینِ ۱۵ دقیقه" if s.kind == ComputeNodeSample.M15 else "خام", s.ram_free_mb, s.ram_total_mb,
               s.vram_used_mb, s.vram_total_mb, s.disk_free_gb, s.disk_total_gb, s.gpu_util_pct, s.gpu_temp_c, s.running_jobs]


def _rows_logs(rng, node_id, request):
    qs, _ = _log_qs(request, rng)
    for r in qs.select_related("node").order_by("-created_at", "-id").iterator(chunk_size=2000):
        yield [r.node.name, r.level, r.logged_at or r.created_at, r.message]


def _rows_errors(rng, node_id):
    for e in _error_items(rng, node_id, MAX_CSV_ROWS // 2):
        yield [e["at"], "کار" if e["source"] == "job" else "لاگ", e["node"] or "", e["kind_label"], e["short"],
               e["explain"]["what"], e["explain"]["advice"], e["text"][:1000]]


def _rows_downloads(rng, node_id):
    base = ComputeJob.objects.filter(_download_q()).exclude(kind=PARK_KIND).filter(
        state__in=ComputeJob.FINAL, finished_at__gte=rng["start"], finished_at__lt=rng["end"])
    if node_id:
        base = base.filter(node_id=node_id)
    for j in base.select_related("node").order_by("-finished_at").iterator(chunk_size=2000):
        it = _download_history_item(j)
        yield [it["title"], it["node"] or "", it["state_label"], it["started"], it["finished"], it["run_s"], it["bytes"],
               it["speed_bps"], it["error"]]


CSV_SECTIONS = {
    "jobs": (["شناسه", "نوعِ کار", "کدِ نوع", "وضعیت", "سرور", "ساخته شد (وقتِ تهران)", "شروعِ اجرا (وقتِ تهران)",
              "پایان (وقتِ تهران)", "انتظار در صف (ثانیه)", "زمانِ اجرا (ثانیه)", "تلاش‌ها", "دفعاتِ قطعِ سرور", "دسته", "خطا"],
             _rows_jobs),
    "sessions": (["سرور", "شروعِ اتصال (وقتِ تهران)", "پایانِ اتصال (وقتِ تهران)", "مدت (دقیقه)", "هنوز وصل است",
                  "نسخهٔ نرم‌افزار", "نامِ کامپیوتر", "کارتِ گرافیک"], _rows_sessions),
    "samples": (["سرور", "زمان (وقتِ تهران)", "نوع", "RAMِ آزاد (MB)", "RAMِ کل (MB)", "VRAMِ مصرفی (MB)", "VRAMِ کل (MB)",
                 "دیسکِ آزاد (GB)", "دیسکِ کل (GB)", "استفادهٔ GPU (٪)", "دمای GPU (°C)", "کارهای در حالِ اجرا"], _rows_samples),
    "errors": (["زمان (وقتِ تهران)", "منبع", "سرور", "نوعِ کار", "خطا (خلاصه)", "توضیحِ ساده", "پیشنهاد", "متنِ کامل"], _rows_errors),
    "downloads": (["دانلود", "سرور", "وضعیت", "شروع (وقتِ تهران)", "پایان (وقتِ تهران)", "مدت (ثانیه)", "حجم (بایت)",
                   "سرعت (بایت بر ثانیه)", "خطا"], _rows_downloads),
}
LOGS_HEADER = ["سرور", "سطح", "زمان (وقتِ تهران)", "پیام"]


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def export_csv(request):
    qp = request.query_params
    section = (qp.get("section") or "").strip()
    if section != "logs" and section not in CSV_SECTIONS:
        raise exceptions.ValidationError({"section": "بخش را یکی از jobs، sessions، samples، logs، errors، downloads بدهید."})
    rng = parse_range(qp)
    node_id = _node_id(qp)
    name = f"compute-{section}-{rng['from_d'].isoformat()}-{rng['to_d'].isoformat()}.csv"
    if section == "logs":
        return _stream(LOGS_HEADER, _rows_logs(rng, node_id, request), name)
    header, rows = CSV_SECTIONS[section]
    return _stream(header, rows(rng, node_id), name)
