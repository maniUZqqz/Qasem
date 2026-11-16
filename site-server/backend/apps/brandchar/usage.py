"""«همه‌جا به کار ببر»: دکمه‌های واقعی که شخصیتِ برند را به بخش‌های دیگرِ پنل می‌رسانند.

هر کدام یک تابعِ کوچک است که از شخصیتِ «اصلی» (یا شخصیتِ انتخاب‌شده) استیکر/تصویر می‌سازد و دادهٔ لازمِ همان بخش را برمی‌گرداند؛ هر استفاده در ``UsageEvent`` ثبت می‌شود
تا صفحهٔ «گالری و کاربرد» بگوید شخصیت کجاها به کار رفته:

* ``motion``       — قطعهٔ «شخصیتِ برند» در استودیوی موشن (وارد می‌شود، دست تکان می‌دهد، اشاره می‌کند، حباب؛ هم‌زمان با کلماتِ گوینده).
* ``thumbnail``    — سوژهٔ تامنیل (استیکرِ شفافِ نیم‌تنه؛ بدونِ کارِ «حذفِ پس‌زمینه»).
* ``post_template``— قالب‌های پست و استوری در استودیوی تصویر.
* ``inbox``        — آواتار و سلامِ ایجنتِ فروش در صندوقِ پیام و چتِ آزمایشی.
* ``site_hero``    — بلوکِ «سربرگِ شخصیتِ برند» در سایت‌ساز.
* ``director``     — ابزارِ «شخصیتِ برند» در کارگردانِ ویدیو (استیکرِ ورودی/اشاره/تأیید روی ویدیو).
"""
from __future__ import annotations

from django.db.models import Count

from apps.mascot.engine import poses
from apps.photoedit import services as photo

from . import inject, persona as P
from .models import BrandCharacter, SiteBinding, UsageEvent

SURFACES: dict[str, dict] = {
    "motion": {"fa": "استودیوی موشن", "about": "قطعهٔ «شخصیتِ برند»: وارد می‌شود، دست تکان می‌دهد، اشاره می‌کند و حبابِ گفتار را هم‌زمان با کلماتِ گوینده نشان می‌دهد.", "page": "/stores/{id}/motion"},
    "thumbnail": {"fa": "تامنیل‌ساز", "about": "سوژهٔ تامنیل: استیکرِ شفافِ نیم‌تنه (بدونِ «حذفِ پس‌زمینه»).", "page": "/stores/{id}/thumbnails"},
    "post_template": {"fa": "قالبِ پست و استوری", "about": "۱۰ قالبِ آماده با متنِ حباب از لحنِ برند.", "page": "/stores/{id}/brand-character/scenes"},
    "inbox": {"fa": "صندوق پیام و ایجنتِ فروش", "about": "آواتار و سلامِ ایجنتِ فروش با لحنِ برند.", "page": "/stores/{id}/inbox"},
    "site_hero": {"fa": "سایت‌ساز", "about": "بلوکِ «سربرگِ شخصیتِ برند» با تصویرِ شخصیت و حباب.", "page": "/tools/studio"},
    "director": {"fa": "کارگردانِ ویدیو", "about": "استیکرِ شخصیت روی ویدیو (ورود، اشاره، تأیید) در ویرایشگرِ ویدیو.", "page": "/stores/{id}/editor"},
    "ai_render": {"fa": "تصویرِ هوش مصنوعی", "about": "نسخهٔ تصویرسازی‌شده/سه‌بعدی‌نما با ComfyUI.", "page": "/stores/{id}/brand-character/studio"},
    "export": {"fa": "بستهٔ خروجی", "about": "SVG، PNG شفاف و برگهٔ مدل (PDF).", "page": "/stores/{id}/brand-character/export"},
}

#: ژست‌های قطعهٔ موشن برای هر «کار»
MOTION_ACTIONS = {
    "wave": ("stand", "wave"), "point": ("stand", "point_right"), "thumbs": ("stand", "thumbs_up"), "explain": ("stand", "point_up"), "think": ("stand", "think"),
}


def summary(store) -> dict:
    counts = {r["surface"]: r["n"] for r in UsageEvent.objects.filter(store=store).values("surface").annotate(n=Count("id"))}
    rows = [{"key": k, "fa": v["fa"], "about": v["about"], "page": v["page"].replace("{id}", str(store.pk)), "count": counts.get(k, 0)} for k, v in SURFACES.items()]
    persona_on = inject.persona_row(store) is not None
    return {"surfaces": rows, "total": sum(counts.values()), "persona_active": persona_on,
            "injection": [{"key": k, "fa": v[0], "kind": v[2], "active": persona_on} for k, v in inject.INJECTION_POINTS.items()]}


def recent(store, limit: int = 30) -> list[dict]:
    return [{"id": e.pk, "surface": e.surface, "surface_fa": SURFACES.get(e.surface, {}).get("fa", e.surface), "ref": e.ref, "meta": e.meta, "created_at": e.created_at,
             "character": e.character_id} for e in UsageEvent.objects.filter(store=store).order_by("-id")[:limit]]


def _sticker(c: BrandCharacter, user, pose: str, *, crop: str = "full", expression: str = "happy", prop: str = "none"):
    from . import services as S

    row, _cached = S.render_sticker(c, user, {"pose": pose, "expression": expression, "crop": crop, "prop": prop})
    return row


def _ref(row) -> str:
    return f"photo:{row.asset_id}"


def motion_scene(c: BrandCharacter, user, *, action: str = "wave", text: str = "", enter: str = "left", side: str = "right", duration: float = 6.0) -> dict:
    """صحنه/قطعهٔ ``brand_character`` برای استودیوی موشن، با تصویرِ ژست‌ها (``photo:<id>``). ``text`` همان متنِ گویندهٔ همین صحنه است تا حباب هم‌زمان با کلمات بیاید."""
    from . import services as S

    action = action if action in MOTION_ACTIONS else "wave"
    a, b = MOTION_ACTIONS[action]
    ra = _sticker(c, user, a)
    rb = _sticker(c, user, b)
    persona = S.persona_data(c.store)
    line = " ".join(str(text or "").split())[:160]
    if not line and persona:
        line = (persona.get("greeting") or (persona.get("catchphrases") or [""])[0] or "")[:160]
    S.log_use(c.store, c, "motion", f"{action}", {"action": action}, user=user)
    return {"type": "brand_character", "duration": max(3.0, min(14.0, float(duration))), "text": line, "name": (persona or {}).get("name") or c.name, "image_a": _ref(ra), "image_b": _ref(rb),
            "action": action, "arrive": enter if enter in ("left", "right", "bottom") else "left", "side": side if side in ("left", "right") else "right", "bubble": bool(line)}


def thumbnail_subject(c: BrandCharacter, user, pose: str = "thumbs_up", expression: str = "happy") -> dict:
    from . import services as S

    if pose not in poses.POSES:
        pose = "thumbs_up"
    row = _sticker(c, user, pose, crop="bust", expression=expression)
    S.log_use(c.store, c, "thumbnail", str(row.asset_id), {"pose": pose}, user=user)
    persona = S.persona_data(c.store)
    title = ""
    if persona and persona.get("catchphrases"):
        title = persona["catchphrases"][0]
    return {"asset": row.asset_id, "url": photo.media_url(row.asset.original), "thumb": photo.media_url(row.asset.thumb), "title": title,
            "open": f"/stores/{c.store_id}/thumbnails?subject={row.asset_id}" + (f"&title={title}" if title else "")}


def inbox_card(store, user=None) -> dict:
    """آواتار و سلامِ ایجنتِ فروش (برای صندوقِ پیام و چتِ آزمایشی). بدونِ شخصیت: ``enabled = False``."""
    from . import services as S

    c = S.primary(store)
    row = inject.persona_row(store)
    data = P.normalize(row.data) if row is not None else None
    if c is None and not data:
        return {"enabled": False}
    out = {"enabled": True, "name": (data or {}).get("name") or (c.name if c else ""), "greeting": (data or {}).get("greeting", ""), "signoff": (data or {}).get("signoff", ""),
           "avatar": None, "character": c.pk if c else None}
    if c is not None:
        try:
            r = _sticker(c, user, "stand", crop="bust")
            out["avatar"] = photo.media_url(r.asset.thumb)
            out["avatar_full"] = photo.media_url(r.asset.original)
        except Exception:  # noqa: BLE001 — آواتار نشد ⇒ فقط سلام
            out["avatar"] = None
    return out


def site_hero(c: BrandCharacter, user, project_slug: str = "", pose: str = "wave") -> dict:
    """ویژگی‌های بلوکِ ``brand_hero`` در سایت‌ساز. سایت‌ساز ابزارِ کارکنان است؛ پس فقط برای کاربرِ کارمند: پروژه به این فروشگاه بسته می‌شود (تا متنِ هوش مصنوعیِ سایت
    هم با لحنِ برند نوشته شود) و تصویر در رسانهٔ خودِ پروژه می‌نشیند (``m:<id>``؛ در سایتِ منتشرشده هم می‌ماند). برای بقیه فقط نشانیِ تصویر برمی‌گردد."""
    from . import services as S

    if pose not in poses.POSES:
        pose = "wave"
    row = _sticker(c, user, pose)
    persona = S.persona_data(c.store)
    image = photo.media_url(row.asset.original)
    alt = f"شخصیتِ برند {c.name}"
    bound = False
    if project_slug and getattr(user, "is_staff", False):
        SiteBinding.objects.update_or_create(project_slug=project_slug[:120], defaults={"store": c.store})
        bound = True
        try:
            from django.core.files.uploadedfile import SimpleUploadedFile

            from apps.projects.builder import media as builder_media
            from apps.projects.models import Project

            project = Project.objects.filter(slug=project_slug).first()
            if project is not None:
                data = photo.abs_path(row.asset.original).read_bytes()
                asset = builder_media.save_upload(project, SimpleUploadedFile("brand-character.png", data, content_type="image/png"), alt=alt)
                image = f"m:{asset.pk}"
        except Exception:  # noqa: BLE001 — رسانهٔ پروژه نشد ⇒ همان نشانیِ مطلق
            pass
    S.log_use(c.store, c, "site_hero", project_slug or "-", {"pose": pose, "bound": bound}, user=user)
    tag = (persona or {}).get("tagline") or ((persona or {}).get("catchphrases") or [""])[0]
    return {"image": image, "image_alt": alt, "title": tag or c.store.name, "subtitle": (persona or {}).get("summary", "")[:240], "bubble": (persona or {}).get("greeting", "")[:120],
            "name": (persona or {}).get("name") or c.name, "project_slug": project_slug, "bound": bound}


def director_overlay(c: BrandCharacter, user) -> dict:
    """بستهٔ استیکرها برای ابزارِ «شخصیتِ برند» در کارگردانِ ویدیو: ورود (دست تکان‌دادن)، اشاره، تأیید، پایان؛ هر کدام PNGِ شفاف."""
    from . import services as S

    items = []
    for key, pose, fa in (("intro", "wave", "ورود و سلام"), ("point", "point_right", "اشاره"), ("explain", "point_up", "توضیح"), ("ok", "thumbs_up", "تأیید"), ("outro", "wave", "خداحافظی")):
        r = _sticker(c, user, pose)
        items.append({"key": key, "fa": fa, "pose": pose, "asset": r.asset_id, "url": photo.media_url(r.asset.original), "thumb": photo.media_url(r.asset.thumb)})
    persona = S.persona_data(c.store)
    S.log_use(c.store, c, "director", "overlay", {}, user=user)
    return {"items": items, "name": (persona or {}).get("name") or c.name, "greeting": (persona or {}).get("greeting", ""), "signoff": (persona or {}).get("signoff", ""),
            "catchphrase": ((persona or {}).get("catchphrases") or [""])[0]}


DIRECTOR_POSES = {"intro": "wave", "point": "point_right", "explain": "point_up", "ok": "thumbs_up", "outro": "wave"}


def director_ref(store, action: str = "intro", user=None) -> str | None:
    """ابزارِ «شخصیتِ برند» در کارگردانِ ویدیو (``services.editing.director.tools``): استیکرِ شفافِ شخصیتِ اصلی برای یک کار ⇒ ``photo:<id>`` (همان منبعی که ویرایشگر می‌شناسد)؛
    شخصیتی نباشد ⇒ None."""
    from . import services as S

    c = S.primary(store)
    if c is None:
        return None
    pose = DIRECTOR_POSES.get(action, "wave")
    row = _sticker(c, user or c.created_by, pose)
    S.log_use(store, c, "director", f"tool:{action}", {"pose": pose}, user=user)
    return _ref(row)
