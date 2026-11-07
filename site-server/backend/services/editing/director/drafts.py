"""«کارگردان»: lightweight drafts, and the editor settings that go with them.

A «بساز» used to create up to three full `VideoProject` rows. Now each variant is a `DirectorDraft`: the project JSON (media are
referenced by `ref`, never copied), the plan and the critique — a few tens of kilobytes — plus ONE shared low-resolution preview
file per run. A draft turns into a real project only when the owner opens it in the manual editor; an unopened draft expires.

Rules that keep this safe:
  * a real `VideoProject` is never deleted here (opened, edited and saved projects are not this module's business);
  * only UNOPENED drafts expire, by age (`draft_days`, a per-store setting, 7 by default) or when a store has more than `MAX_DRAFTS`;
  * a preview folder is removed only when no draft of its run is left;
  * purging is done lazily (on listing, on each run, or by `manage.py director_drafts purge`) — no scheduler is needed.
"""
from __future__ import annotations

import logging
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

#: where the editor settings live on the store profile (`StoreProfile.ai_preferences[KEY]`)
KEY = "video_editor"
DEFAULTS = {"ai_default": True, "draft_days": 7}
MIN_DAYS, MAX_DAYS = 1, 30
#: unopened drafts per store; the oldest beyond this expire early
MAX_DRAFTS = 60
#: a promoted draft only stays as a pointer (so a double click opens the same project), then it is removed
PROMOTED_KEEP = timedelta(days=1)

COST_NOTE = (
    "هر «بساز» با کمکِ هوش مصنوعی چند درخواستِ کوچک به مدل می‌فرستد (فهمیدنِ دستور، نقدِ تصویر، پیشنهادِ مرحله؛ معمولاً یک تا شش درخواست) "
    "و از اعتبارِ سرویسِ هوش مصنوعی کم می‌شود. خاموش که باشد فقط قالب‌های آماده کار می‌کنند و هزینه‌ای ندارد."
)


def _profile(store, create: bool = False):
    from apps.stores.models import StoreProfile

    try:
        return store.profile
    except Exception:  # noqa: BLE001 — no profile row yet
        return StoreProfile.objects.get_or_create(store=store)[0] if create else None


def get_settings(store) -> dict:
    """The editor settings of a store, over the defaults."""
    out = dict(DEFAULTS)
    p = _profile(store)
    saved = (p.ai_preferences or {}).get(KEY) if p is not None else None
    if isinstance(saved, dict):
        if isinstance(saved.get("ai_default"), bool):
            out["ai_default"] = saved["ai_default"]
        out["draft_days"] = _days(saved.get("draft_days"))
    return out


def _days(value) -> int:
    try:
        return max(MIN_DAYS, min(MAX_DAYS, int(value)))
    except (TypeError, ValueError):
        return DEFAULTS["draft_days"]


def save_settings(store, *, ai_default=None, draft_days=None) -> dict:
    """Change one or both settings; every other AI preference of the store is kept."""
    cur = get_settings(store)
    if isinstance(ai_default, bool):
        cur["ai_default"] = ai_default
    if draft_days is not None:
        cur["draft_days"] = _days(draft_days)
    p = _profile(store, create=True)
    prefs = dict(p.ai_preferences or {})
    prefs[KEY] = {"ai_default": cur["ai_default"], "draft_days": cur["draft_days"]}
    p.ai_preferences = prefs
    p.save(update_fields=["ai_preferences"])
    return cur


def public_settings(store) -> dict:
    s = get_settings(store)
    return {**s, "min_days": MIN_DAYS, "max_days": MAX_DAYS, "max_drafts": MAX_DRAFTS, "cost_note": COST_NOTE}


# ───────────────────────────── drafts


def editing_root() -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "editing"


def preview_dir(job_id) -> Path | None:
    return editing_root() / f"director_{int(job_id)}" if job_id else None


def create(store, *, run: str, job_id, key: str, title: str, data: dict, score: int, length: float):
    from apps.content.models import DirectorDraft

    return DirectorDraft.objects.create(
        store=store, run=run, job_id=job_id, key=key, title=title[:200], data=data, score=int(score), length=float(length),
        expires_at=timezone.now() + timedelta(days=get_settings(store)["draft_days"]))


def replace(draft, *, title: str, data: dict, score: int, length: float):
    """A re-run of an unopened draft's plan replaces its data (and gives it a fresh window)."""
    draft.title, draft.data, draft.score, draft.length = title[:200], data, int(score), float(length)
    draft.expires_at = timezone.now() + timedelta(days=get_settings(draft.store)["draft_days"])
    draft.save()
    return draft


def row(draft) -> dict:
    now = timezone.now()
    left = (draft.expires_at - now).total_seconds() / 86400 if draft.project_id is None else None
    d = draft.data or {}
    return {
        "id": draft.pk, "key": draft.key, "title": draft.title, "score": draft.score, "length": round(draft.length, 1), "run": draft.run,
        "created_at": draft.created_at.isoformat(), "expires_at": draft.expires_at.isoformat(),
        "days_left": None if left is None else max(0, int(left + 0.999)),
        "project_id": draft.project_id, "prompt": ((d.get("director") or {}).get("prompt") or "")[:120],
    }


def promote(draft):
    """Make the real project from a draft (idempotent: a second call returns the same project)."""
    from apps.content.models import VideoProject

    if draft.project_id and VideoProject.objects.filter(pk=draft.project_id).exists():
        return draft.project
    project = VideoProject.objects.create(store=draft.store, title=draft.title, data=draft.data)
    draft.project = project
    draft.promoted_at = timezone.now()
    draft.save(update_fields=["project", "promoted_at", "updated_at"])
    return project


def _drop_previews(entries: list[tuple[str, int | None, int]]) -> int:
    """Remove the preview folder of every (run, job, store) that has no draft left."""
    from apps.content.models import DirectorDraft

    freed = 0
    for run, job_id, store_id in entries:
        if not job_id or DirectorDraft.objects.filter(store_id=store_id, run=run).exists():
            continue
        folder = preview_dir(job_id)
        if folder is not None and folder.is_dir():
            freed += sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
            shutil.rmtree(folder, ignore_errors=True)
    return freed


def purge(store=None, *, now=None) -> dict:
    """Delete expired UNOPENED drafts (and the oldest ones beyond the cap), old promoted pointers, and orphaned preview folders.

    Returns {"expired": n, "over_cap": n, "pointers": n, "bytes": freed}. Never touches a `VideoProject`.
    """
    from apps.content.models import DirectorDraft

    now = now or timezone.now()
    scope = DirectorDraft.objects.all() if store is None else DirectorDraft.objects.filter(store=store)
    gone: list[tuple[str, int | None, int]] = []
    out = {"expired": 0, "over_cap": 0, "pointers": 0, "bytes": 0}

    old = scope.filter(project__isnull=True, promoted_at__isnull=True, expires_at__lte=now)
    gone += [(d.run, d.job_id, d.store_id) for d in old]
    out["expired"] = old.count()
    old.delete()

    # promoted drafts are only pointers (a double click opens the same project); a project that was deleted afterwards leaves a dead pointer
    ptr = scope.filter(promoted_at__isnull=False).filter(promoted_at__lte=now - PROMOTED_KEEP) | scope.filter(promoted_at__isnull=False, project__isnull=True)
    gone += [(d.run, d.job_id, d.store_id) for d in ptr]
    out["pointers"] = ptr.count()
    ptr.delete()

    stores = [store.pk] if store is not None else list(scope.values_list("store_id", flat=True).distinct())
    for sid in stores:
        extra = list(DirectorDraft.objects.filter(store_id=sid, promoted_at__isnull=True).order_by("-created_at").values_list("pk", flat=True)[MAX_DRAFTS:])
        if extra:
            rows = DirectorDraft.objects.filter(pk__in=extra)
            gone += [(d.run, d.job_id, d.store_id) for d in rows]
            out["over_cap"] += len(extra)
            rows.delete()
    out["bytes"] = _drop_previews(gone)
    if any(out[k] for k in ("expired", "over_cap", "pointers")):
        logger.info("director drafts purged: %s", out)
    return out


def drafts_of(store) -> list[dict]:
    """Unopened drafts of a store, newest first (after purging the expired ones)."""
    from apps.content.models import DirectorDraft

    purge(store)
    return [row(d) for d in DirectorDraft.objects.filter(store=store, promoted_at__isnull=True)]
