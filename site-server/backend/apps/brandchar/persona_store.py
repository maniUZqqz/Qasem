"""ذخیره و نسخه‌بندیِ شخصیتِ گفتار: ساختن، ذخیره، قفل (تأیید)، بازگرداندن، پیش‌نویسِ خودکار و پیش‌نمایشِ بلوکِ تزریق."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from . import inject, persona
from .models import BrandPersona, PersonaVersion

MAX_VERSIONS = 40


class PersonaError(Exception):
    """متنش برای کاربر است."""


def get(store) -> BrandPersona | None:
    return BrandPersona.objects.filter(store=store).first()


def public(row: BrandPersona | None, store=None) -> dict:
    data = persona.normalize(row.data) if row is not None else persona.empty()
    a = persona.ARCHETYPES.get(data["archetype"], {})
    return {
        "exists": row is not None and bool(row.data), "data": data, "version": row.version if row else 0, "locked": bool(row and row.locked),
        "locked_at": row.locked_at if row else None, "active": bool(row.active) if row else True, "source": row.source if row else "",
        "score": persona.filled_score(data), "archetype_fa": a.get("fa", ""), "archetype_about": a.get("about", ""),
        "tone_words": persona.tone_words(data["tone"]), "updated_at": row.updated_at if row else None,
    }


def _snapshot(row: BrandPersona, user, note: str = "") -> None:
    PersonaVersion.objects.update_or_create(persona=row, version=row.version, defaults={"data": row.data, "source": row.source, "note": note[:160], "created_by": user})
    old = list(PersonaVersion.objects.filter(persona=row).order_by("-version").values_list("pk", flat=True)[MAX_VERSIONS:])
    if old:
        PersonaVersion.objects.filter(pk__in=old).delete()


@transaction.atomic
def save(store, user, data: dict, *, source: str = "manual", active: bool | None = None, note: str = "") -> BrandPersona:
    row = get(store) or BrandPersona(store=store)
    if row.pk and row.locked:
        raise PersonaError("شخصیتِ گفتار تأیید و قفل شده است؛ برای تغییر، اول «بازکردنِ قفل» را بزنید.")
    row.data = persona.normalize(data)
    row.source = source if source in ("manual", "rule", "facts", "ai") else "manual"
    row.updated_by = user
    if active is not None:
        row.active = bool(active)
    row.save()
    return row


@transaction.atomic
def lock(store, user, note: str = "") -> BrandPersona:
    row = get(store)
    if row is None or not row.data:
        raise PersonaError("هنوز شخصیتی ذخیره نشده است.")
    if not row.locked:
        row.locked, row.locked_at = True, timezone.now()
        row.version += 1
        row.updated_by = user
        row.save()
        _snapshot(row, user, note or "تأییدِ شخصیتِ گفتار")
    return row


def unlock(store) -> BrandPersona:
    row = get(store)
    if row is not None and row.locked:
        row.locked = False
        row.save(update_fields=["locked", "updated_at"])
    return row


def set_active(store, active: bool) -> BrandPersona:
    row = get(store)
    if row is None:
        raise PersonaError("هنوز شخصیتی ذخیره نشده است.")
    row.active = bool(active)
    row.save(update_fields=["active", "updated_at"])
    return row


def versions(store) -> list[dict]:
    row = get(store)
    if row is None:
        return []
    return [{"version": v.version, "source": v.source, "note": v.note, "created_at": v.created_at, "name": (v.data or {}).get("name", "")} for v in row.versions.all()]


@transaction.atomic
def restore(store, user, version: int) -> BrandPersona:
    row = get(store)
    v = row.versions.filter(version=version).first() if row else None
    if v is None:
        raise PersonaError("این نسخه پیدا نشد.")
    if row.locked:
        raise PersonaError("اول قفل را باز کنید.")
    row.data = persona.normalize(v.data)
    row.updated_by = user
    row.save()
    return row


def prompt_preview(store, kind: str = "caption") -> dict:
    row = get(store)
    text = inject.block_from_data(row.data, kind) if row is not None and row.data else ""
    return {"kind": kind, "text": text, "chars": len(text), "limit": inject.MAX_CHARS, "active": bool(row and row.active)}
