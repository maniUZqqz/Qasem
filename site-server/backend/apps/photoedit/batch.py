"""«طراحیِ گروهی» (نوبت ۴): یک الگو/دستور + سبکِ برند روی چند عکس ⇒ برای هر عکس یک طراحی (۱ پیشنهاد، دقتِ «سریع») ⇒ مرور در جدول ⇒
ویرایشِ تکی در ویرایشگر ⇒ خروجیِ همه در یک zip.

اجرا در Celery، تک‌به‌تک (هرگز دو طراحیِ هم‌زمان از یک گروه). هوش مصنوعی فقط اگر کاربر بخواهد و فقط «برنامه‌ریز» (۱ فراخوانی برای هر عکس)؛ نقدِ
هوش مصنوعی در گروهی نیست. سقفِ تعداد: ۲۴ عکس (با هوش مصنوعی ۱۲ عکس).
"""
from __future__ import annotations

import io
import logging
import zipfile

from django.utils import timezone

from . import brand as brand_mod, services
from .designer import engine, recipes, render
from .models import PhotoAsset, PhotoDesign, PhotoDesignBatch

logger = logging.getLogger(__name__)

MAX_PHOTOS = 24
MAX_PHOTOS_AI = 12
MAX_ACTIVE = 1


class BatchError(Exception):
    """خطایی که متنش برای کاربر است."""


def create(store, user, data: dict) -> PhotoDesignBatch:
    inp = engine.clean_input({**data, "variants": 1})
    if not inp["prompt"] and not inp["recipe"]:
        raise BatchError("یا دستور بنویسید یا یکی از الگوها را انتخاب کنید.")
    raw = data.get("assets")
    ids: list[int] = []
    for x in raw if isinstance(raw, list) else []:
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v not in ids:
            ids.append(v)
    if not ids:
        raise BatchError("دست‌کم یک عکس انتخاب کنید.")
    assets = list(PhotoAsset.objects.filter(store=store, pk__in=ids).values_list("pk", flat=True))
    ids = [i for i in ids if i in assets]
    if not ids:
        raise BatchError("عکس‌های انتخاب‌شده پیدا نشد.")
    opts = inp["options"]
    opts.setdefault("use_ai", brand_mod.ai_default(store))
    cap = MAX_PHOTOS_AI if opts["use_ai"] else MAX_PHOTOS
    if len(ids) > cap:
        raise BatchError(f"در یک بار حداکثر {cap} عکس" + (" (با کمکِ هوش مصنوعی)" if opts["use_ai"] else "") + " می‌شود؛ بقیه را در بارِ بعد بدهید.")
    if PhotoDesignBatch.objects.filter(store=store, state__in=PhotoDesignBatch.ACTIVE).count() >= MAX_ACTIVE:
        raise BatchError("یک طراحیِ گروهیِ دیگر در حالِ انجام است؛ صبر کنید تا تمام شود.")
    fmt = inp["fmt"] or (recipes.RECIPES[inp["recipe"]]["format"] if inp["recipe"] else "square")
    title = str(data.get("title") or "").strip()[:120] or f"طراحیِ گروهی — {len(ids)} عکس"
    return PhotoDesignBatch.objects.create(store=store, created_by=user, title=title, recipe=inp["recipe"], prompt=inp["prompt"], fmt=fmt,
                                           mood=inp["mood"], copy=inp["copy"], options=opts, assets=ids, message="در صف")


def run(batch_id: int) -> None:
    """کارِ Celery. دوباره‌صدازدن بی‌خطر است (فقط QUEUED برداشته می‌شود)."""
    claimed = PhotoDesignBatch.objects.filter(pk=batch_id, state=PhotoDesignBatch.State.QUEUED).update(
        state=PhotoDesignBatch.State.RUNNING, message="شروع شد", updated_at=timezone.now())
    if not claimed:
        return
    b = PhotoDesignBatch.objects.select_related("store", "created_by").get(pk=batch_id)
    total = len(b.assets)
    failed = 0
    try:
        for i, aid in enumerate(b.assets):
            b.refresh_from_db(fields=["state"])
            if b.state == PhotoDesignBatch.State.CANCELLED:
                return
            asset = PhotoAsset.objects.filter(pk=aid, store=b.store).first()
            if asset is None:
                failed += 1
                continue
            PhotoDesignBatch.objects.filter(pk=b.pk).update(message=f"عکسِ {i + 1} از {total}…", progress=round(i / total, 3), updated_at=timezone.now())
            try:
                d = PhotoDesign.objects.create(store=b.store, asset=asset, created_by=b.created_by, prompt=b.prompt, recipe=b.recipe, fmt=b.fmt,
                                               mood=b.mood, quality="fast", copy=b.copy, options=dict(b.options, variants=1), batch=b,
                                               message="در صف")
                engine.run(d.pk)
                d.refresh_from_db(fields=["state"])
                if d.state != PhotoDesign.State.READY:
                    failed += 1
            except Exception:  # noqa: BLE001 — یک عکسِ خراب بقیه را نمی‌کشد
                logger.exception("photoedit.batch: item %s of batch %s failed", aid, batch_id)
                failed += 1
            PhotoDesignBatch.objects.filter(pk=b.pk).update(done=i + 1, progress=round((i + 1) / total, 3), updated_at=timezone.now())
        msg = f"{total - failed} طراحی آماده است" + (f"؛ {failed} عکس ناموفق بود" if failed else "")
        PhotoDesignBatch.objects.filter(pk=b.pk).update(state=PhotoDesignBatch.State.READY if failed < total else PhotoDesignBatch.State.FAILED,
                                                       progress=1.0, message=msg, updated_at=timezone.now())
    except Exception as exc:  # noqa: BLE001
        logger.exception("photoedit.batch: batch %s failed", batch_id)
        PhotoDesignBatch.objects.filter(pk=batch_id).update(state=PhotoDesignBatch.State.FAILED, error=str(exc)[:1500], message="ناموفق",
                                                           updated_at=timezone.now())


def cancel(b: PhotoDesignBatch) -> bool:
    if not b.active:
        return False
    PhotoDesignBatch.objects.filter(pk=b.pk, state__in=PhotoDesignBatch.ACTIVE).update(state=PhotoDesignBatch.State.CANCELLED, message="لغو شد",
                                                                                      updated_at=timezone.now())
    return True


def _item(b: PhotoDesignBatch, a: PhotoAsset | None, d: PhotoDesign | None, aid: int) -> dict:
    out = {"asset": {"id": aid, "title": a.title if a else "", "thumb": services.asset_dict(a)["thumb"] if a else ""}, "design": None}
    if d is not None:
        v = (d.variants or [None])[0] if d.variants else None
        out["design"] = {"id": d.pk, "state": d.state, "message": d.message, "error": d.error[:300],
                         "preview": (services.media_url(v["preview_rel"]) + f"?t={int(d.updated_at.timestamp())}") if v and v.get("preview_rel") else "",
                         "score": (v or {}).get("score"), "issues": ((v or {}).get("qa") or {}).get("issues", [])[:3],
                         "needs": bool(((v or {}).get("needs") or {}).get("manual"))}
    return out


def public(b: PhotoDesignBatch) -> dict:
    designs = {d.asset_id: d for d in b.designs.all().order_by("created_at")}
    assets = {a.pk: a for a in PhotoAsset.objects.filter(pk__in=b.assets)}
    return {"id": b.pk, "title": b.title, "state": b.state, "progress": b.progress, "done": b.done, "total": len(b.assets), "message": b.message,
            "error": b.error, "recipe": b.recipe, "prompt": b.prompt, "format": b.fmt, "options": b.options, "created": b.created_at.isoformat(),
            "items": [_item(b, assets.get(aid), designs.get(aid), aid) for aid in b.assets]}


def zip_bytes(b: PhotoDesignBatch, only: list[int] | None = None) -> tuple[bytes, int]:
    """خروجیِ نهاییِ هر طراحیِ آماده (قالب/کیفیتِ خودِ طراحی) در یک zip ⇒ (بایت‌ها، تعدادِ فایل)."""
    buf = io.BytesIO()
    n = 0
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for d in b.designs.filter(state=PhotoDesign.State.READY).select_related("asset", "asset__store", "store").order_by("created_at"):
            if only is not None and d.asset_id not in only:
                continue
            v = (d.variants or [None])[0]
            if not v:
                continue
            img, _frame, _notes = render.render_state(d.asset, v["state"])
            out = v["state"].get("out") or {}
            q = int(out.get("quality") or 92)
            data = render.to_jpeg(img, max(60, min(98, q)), max(img.size))        # اندازهٔ کاملِ قاب (بدونِ کوچک‌کردن)
            base = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (d.asset.title or f"photo{d.asset_id}"))[:40].strip("-") or f"photo{d.asset_id}"
            name = f"{n + 1:02d}-{base}.jpg"
            while name in used:
                name = f"{n + 1:02d}-{base}-{d.pk}.jpg"
            used.add(name)
            z.writestr(name, data)
            n += 1
    return buf.getvalue(), n
