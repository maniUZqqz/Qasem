"""نمای «صفِ پردازش»: فهرستِ کارها با وضعیتِ فارسی، جایگاه در صف، چرایِ انتظار، لغو و تلاشِ دوباره.

سمتِ پنل (فقط کارکنان): `GET /api/v1/compute/queue/`، `.../queue/summary/`، `POST .../queue/<uid>/cancel|retry/`.
منطقِ صف خودش در services.py است؛ این‌جا فقط خواندن و ترجمه به زبانِ آدم است.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from . import services as SV
from .models import ComputeJob, ComputeNode, capability_for
from .park import PARK_KIND

S = ComputeJob.State

#: گروه‌های نمایشی ⇐ وضعیت‌های ComputeJob
GROUPS = {
    "waiting": [S.QUEUED],
    "running": [S.CLAIMED, S.RUNNING],
    "done": [S.COMPLETED],
    "failed": [S.FAILED],
    "cancelled": [S.CANCELLED],
}
GROUP_OF = {s: g for g, states in GROUPS.items() for s in states}

KIND_LABELS = {
    "photo.edit": "ویرایشِ عکس", "photo.analyze": "تحلیلِ عکس", "video.edit": "تدوینِ ویدیو",
    "edit.render": "رندرِ نهاییِ ویدیو", "edit.track": "ردیابی در ویدیو", "edit.matte": "حذفِ پس‌زمینهٔ ویدیو",
    "voice.tts": "ساختِ گفتار", "voice.asr": "تبدیلِ گفتار به متن (زیرنویس)", "voice.clone": "ساختِ صدای کلون‌شده",
    "voice.sfx": "صدای محیط و افکت", "voice.music": "موسیقیِ زمینه", "voice.http": "فرمانِ سرویسِ صدا",
    "comfy.graph": "تولیدِ تصویر یا ویدیو (ComfyUI)", "comfy.profile": "تولیدِ تصویر یا ویدیو (پروفایل)",
    "ollama.chat": "گفتگوی هوشمند", "ollama.generate": "نوشتنِ متنِ هوشمند", "ollama.vision": "تحلیلِ تصویرِ هوشمند",
    "ollama.pull": "دانلودِ مدلِ هوش مصنوعی", "node.models": "دانلودِ مدل‌های صدا و ویدیو",
    "node.update": "به‌روزرسانیِ نرم‌افزارِ سرورِ پردازش", "node.bench": "آزمونِ مدلِ صدا", "echo": "آزمونِ اتصال",
    PARK_KIND: "کارِ منتظرِ سرورِ پردازش",
}
KIND_LABEL_PREFIX = {
    "comfy": "تولیدِ تصویر یا ویدیو", "photo": "ویرایشِ عکس", "video": "تدوینِ ویدیو", "voice": "کارِ صدا",
    "ollama": "هوشِ مصنوعی (متن)", "edit": "ویرایشگرِ ویدیو", "node": "کارِ سرورِ پردازش", "up3d": "ویدیوی سه‌بعدی",
}

#: کارهایی که تلاشِ دوبارهٔ آن‌ها از پنل بی‌خطر است (خروجی‌شان را فقط همین صف می‌بیند)
RETRYABLE_PREFIXES = ("node.", "ollama.pull", "echo")


def kind_label(kind: str) -> str:
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    return KIND_LABEL_PREFIX.get((kind or "").split(".", 1)[0], kind or "—")


_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n) -> str:
    return str(n).translate(_FA)


def _clock(dt) -> str:
    """«امروز ۰۲:۰۰» / «فردا ۰۲:۰۰» به وقتِ تهران."""
    t = SV.tehran_now(dt)
    today = SV.tehran_now(timezone.now()).date()
    day = (t.date() - today).days
    hhmm = fa(f"{t.hour:02d}:{t.minute:02d}")
    if day <= 0:
        return f"امروز {hhmm}"
    if day == 1:
        return f"فردا {hhmm}"
    return f"{fa(day)} روزِ دیگر، {hhmm}"


def human_duration(seconds) -> str:
    if seconds is None:
        return ""
    s = int(max(0, seconds))
    if s < 60:
        return f"{fa(s)} ثانیه"
    m = s // 60
    if m < 60:
        return f"{fa(m)} دقیقه"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{fa(h)} ساعت" + (f" و {fa(m)} دقیقه" if m else "")
    return f"{fa(h // 24)} روز"


def capability_of(job: ComputeJob) -> str:
    if job.kind == PARK_KIND:
        return (job.payload or {}).get("capability") or "any"
    return capability_for(job.kind)


def node_takes(node: ComputeNode, kind: str) -> bool:
    """همان قاعدهٔ `_kinds_q` برای یک نوع کار (بدون پرس‌وجو)."""
    if kind.startswith("echo") or kind.startswith("node."):
        return True
    if kind == "ollama.pull" and (node.capabilities or {}).get("ollama_pull"):
        return True
    for prefix, capability in SV.CAPABILITY_PREFIXES.items():
        if kind.startswith(prefix):
            return node.has(capability)
    return False


def _positions(queued) -> dict:
    """جایگاهِ هر کارِ منتظر در صفِ همان توانایی (کارِ عکس پشتِ کارِ صدا نمی‌ماند)."""
    by_cap: dict[str, list] = {}
    for j in queued:
        by_cap.setdefault(capability_of(j), []).append(j)
    pos = {}
    for jobs in by_cap.values():
        jobs.sort(key=lambda j: (j.priority, j.created_at))
        for i, j in enumerate(jobs, start=1):
            pos[j.pk] = i
    return pos


def _wait_reason(j: ComputeJob, now, nodes: list, pos: int) -> tuple[str, str]:
    """(کلیدِ دلیل، متنِ فارسی) برای کارِ منتظر."""
    if j.not_before and j.not_before > now:
        return "scheduled", f"زمان‌بندی‌شده — شروع {_clock(j.not_before)} (وقتِ تهران)"
    if j.window and not SV.in_window(j.window, now):
        return "window", f"منتظرِ بازهٔ دانلود ({fa(j.window)}، وقتِ تهران) — باز می‌شود {_clock(SV.next_window_start(j.window, now))}"
    wanted = j.node_wanted
    if wanted and wanted != "__hold__" and not wanted.startswith("~") and j.kind != PARK_KIND:
        pinned = next((n for n in nodes if n.name == wanted), None)
        if pinned is None or not pinned.enabled:
            return "pinned_gone", f"منتظرِ سرورِ «{wanted}» که غیرفعال یا حذف شده؛ لغو کنید یا سرور را فعال کنید"
        if not pinned.online:
            return "pinned_offline", f"در صف — منتظرِ روشن شدنِ سرورِ «{wanted}»"
        if not node_takes(pinned, j.kind):
            return "no_node", SV.NO_NODE_QUEUED_TEXT
    elif wanted == "__hold__" or wanted.startswith("~"):
        return "hold", "در صف — منتظرِ آماده شدنِ ورودی‌ها (مثلاً ترجمهٔ متن)"
    cap = capability_of(j)

    def can_serve(n):
        if not (n.enabled and n.online):
            return False
        if j.kind == PARK_KIND:
            return cap == "any" or n.has(cap)
        return node_takes(n, j.kind)

    pool = [n for n in nodes if can_serve(n)]
    if not pool:
        return "no_node", SV.NO_NODE_QUEUED_TEXT
    if j.kind != PARK_KIND and all(SV.audio_blocked(n, j) for n in pool):
        return "model", "در صف — منتظرِ آماده شدنِ مدل روی سرورِ پردازش"
    if pos <= 1:
        return "busy", "در صف — نوبتِ بعدی"
    return "busy", f"در صف — نفرِ {fa(pos)}ام"


def status_text(j: ComputeJob, reason_text: str) -> str:
    if j.state == S.QUEUED:
        return reason_text
    if j.state in (S.CLAIMED, S.RUNNING):
        who = j.node.name if j.node else "سرورِ پردازش"
        pct = f" — {fa(int(round(j.progress * 100)))}٪" if j.progress else ""
        return f"در حال پردازش روی «{who}»{pct}"
    if j.state == S.COMPLETED:
        return "تمام شد"
    if j.state == S.CANCELLED:
        return "لغو شد"
    return "ناموفق" + (f" — {(j.error or '').strip().splitlines()[-1][:140]}" if (j.error or "").strip() else "")


def title_of(j: ComputeJob) -> str:
    p = j.payload or {}
    if j.kind == PARK_KIND:
        return p.get("title") or kind_label(j.kind)
    if j.kind == "ollama.pull":
        return f"دانلودِ مدلِ {p.get('model') or p.get('tag') or ''}".strip()
    if j.kind == "node.models":
        pk = p.get("packages")
        return "دانلودِ مدل‌ها" + (f": {'، '.join(map(str, pk))}" if pk else "")
    return kind_label(j.kind)


def can_cancel(j: ComputeJob) -> bool:
    return not j.final and not (j.state in (S.CLAIMED, S.RUNNING) and j.cancel_requested)


def can_retry(j: ComputeJob) -> bool:
    if j.state not in (S.FAILED, S.CANCELLED) or j.kind == PARK_KIND:
        return False
    return j.kind.startswith(RETRYABLE_PREFIXES) or j.origin in ("panel", "ai_models", "voice_models", "downloads")


def job_row(j: ComputeJob, now, nodes: list, positions: dict) -> dict:
    pos = positions.get(j.pk, 0)
    reason, text = ("", "")
    waiting_s = None
    if j.state == S.QUEUED:
        reason, text = _wait_reason(j, now, nodes, pos)
        waiting_s = int((now - (j.queued_at or j.created_at)).total_seconds())
    p = j.payload or {}
    return {
        "uid": str(j.uid), "kind": j.kind, "kind_label": kind_label(j.kind), "title": title_of(j),
        "state": j.state, "state_label": j.get_state_display(), "group": GROUP_OF.get(j.state, "waiting"),
        "status_text": status_text(j, text), "wait_reason": reason,
        "position": pos if j.state == S.QUEUED else 0, "ahead": max(0, pos - 1) if j.state == S.QUEUED else 0,
        "waiting_s": waiting_s, "waiting_text": human_duration(waiting_s) if waiting_s is not None else "",
        "waited_s": j.waited_s, "run_s": j.run_s,
        "created": j.created_at, "queued_at": j.queued_at, "claimed": j.claimed_at, "finished": j.finished_at,
        "node": j.node.name if j.node else None, "node_wanted": j.node_wanted if not j.node_wanted.startswith(("~", "__")) else "",
        "attempts": j.attempts, "max_attempts": j.max_attempts, "lost_count": j.lost_count,
        "progress": round(j.progress, 3), "message": j.message, "error": (j.error or "")[-600:],
        "origin": j.origin, "store": j.store.name if j.store_id and getattr(j, "store", None) else None,
        "can_cancel": can_cancel(j), "can_retry": can_retry(j),
        "scheduled_for": j.not_before, "window": j.window, "category": j.category,
        "capability": capability_of(j), "parked": j.kind == PARK_KIND,
        "model": p.get("model") or p.get("tag") or "",
    }


def _nodes():
    return list(ComputeNode.objects.all())


def counts() -> dict:
    rows = dict(ComputeJob.objects.values_list("state").annotate(n=Count("id")))
    out = {g: sum(rows.get(s, 0) for s in states) for g, states in GROUPS.items()}
    out["all"] = sum(out.values())
    return out


def listing(state: str = "all", kind: str = "", q: str = "", limit: int = 100, offset: int = 0, category: str = "",
            since=None, until=None) -> dict:
    now = timezone.now()
    base = ComputeJob.objects.select_related("node", "store")
    if kind:
        base = base.filter(kind__startswith=kind)
    if category:
        base = base.filter(category=category)
    if q:
        base = base.filter(Q(kind__icontains=q) | Q(message__icontains=q) | Q(error__icontains=q) | Q(origin__icontains=q)
                           | Q(node__name__icontains=q))
    if since:
        base = base.filter(created_at__gte=since)
    if until:
        base = base.filter(created_at__lte=until)
    nodes = _nodes()
    queued_all = list(ComputeJob.objects.filter(state=S.QUEUED).only("id", "priority", "created_at", "kind", "payload"))
    positions = _positions(queued_all)
    if state in GROUPS:
        qs = base.filter(state__in=GROUPS[state])
        order = ("priority", "created_at") if state == "waiting" else (
            ("-claimed_at",) if state == "running" else ("-finished_at", "-created_at"))
        total = qs.count()
        rows = list(qs.order_by(*order)[offset:offset + limit])
    else:                                    # all: منتظرها (به ترتیبِ صف)، بعد در حالِ اجرا، بعد تازه‌ترین پایان‌یافته‌ها
        waiting = list(base.filter(state=S.QUEUED).order_by("priority", "created_at"))
        running = list(base.filter(state__in=GROUPS["running"]).order_by("-claimed_at"))
        done_qs = base.filter(state__in=S.values).exclude(state__in=[S.QUEUED, S.CLAIMED, S.RUNNING]).order_by("-finished_at", "-created_at")
        total = len(waiting) + len(running) + done_qs.count()
        head = waiting + running
        rows = (head + list(done_qs[:max(0, offset + limit - len(head))]))[offset:offset + limit]
    return {
        "counts": counts(), "total": total, "offset": offset, "limit": limit,
        "nodes": [{"id": n.pk, "name": n.name, "online": n.online, "enabled": n.enabled, "last_seen": n.last_seen,
                   "agent": (n.capabilities or {}).get("agent")} for n in nodes],
        "jobs": [job_row(j, now, nodes, positions) for j in rows],
    }


def one(job: ComputeJob) -> dict:
    now = timezone.now()
    nodes = _nodes()
    queued_all = list(ComputeJob.objects.filter(state=S.QUEUED).only("id", "priority", "created_at", "kind", "payload"))
    return job_row(job, now, nodes, _positions(queued_all))


def summary() -> dict:
    now = timezone.now()
    nodes = _nodes()
    enabled = [n for n in nodes if n.enabled]
    online = [n for n in enabled if n.online]
    queued = ComputeJob.objects.filter(state=S.QUEUED)
    waiting = queued.count()
    oldest = queued.order_by("queued_at", "created_at").first()
    since = (now - (oldest.queued_at or oldest.created_at)).total_seconds() if oldest else None
    failed_24h = ComputeJob.objects.filter(state=S.FAILED, finished_at__gte=now - timedelta(hours=24)).count()
    return {
        "waiting": waiting, "parked": queued.filter(kind=PARK_KIND).count(),
        "running": ComputeJob.objects.filter(state__in=GROUPS["running"]).count(),
        "scheduled": queued.filter(Q(not_before__gt=now) | ~Q(window="")).count(),
        "failed_24h": failed_24h,
        "nodes_total": len(enabled), "nodes_online": len(online),
        "oldest_wait_s": int(since) if since is not None else None,
        "oldest_wait_text": human_duration(since) if since is not None else "",
        "text": (f"{fa(waiting)} کار منتظرِ سرورِ پردازش" if waiting and not online else
                 f"{fa(waiting)} کار در صف" if waiting else "صف خالی است"),
    }


def retry(job: ComputeJob) -> ComputeJob:
    """همان کارِ ناموفق/لغوشده دوباره به صف برمی‌گردد (ورودی‌هایش هنوز هست)؛ فقط برای کارهایی که can_retry دارند."""
    if not can_retry(job):
        raise ValueError("این کار از این‌جا دوباره اجرا نمی‌شود؛ از همان صفحه‌ای که ساختید دوباره بزنید.")
    now = timezone.now()
    ComputeJob.objects.filter(pk=job.pk).update(
        state=S.QUEUED, attempts=0, lost_count=0, error="", progress=0.0, node=None, claimed_at=None, finished_at=None,
        cancel_requested=False, queued_at=now, waited_s=None, run_s=None, result={},
        message=SV.NO_NODE_QUEUED_TEXT if not SV.online_nodes(capability_of(job)) else "")
    job.refresh_from_db()
    return job
