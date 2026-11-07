"""منطقِ ادیتورِ عکس: کتابخانه، نسخه‌ها، صفِ سرورِ پردازش و کارهای سرورِ سایت."""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from PIL import Image, ImageDraw

from . import catalog, develop_np, ops
from . import frames
from . import layers as layers_mod
from . import textlayer
from .models import PhotoAsset, PhotoEdit, PhotoPreset, PhotoProject

logger = logging.getLogger(__name__)

MAX_UPLOAD_MB = 40
ALLOWED_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")
THUMB_SIDE = 480
PREVIEW_SIDE = 1600
MAX_BATCH = 40
#: نسخه‌های ناموفق/لغوشده بیش از این فایل نگه نمی‌دارند (دیسکِ سرور کوچک است)
NODE_TIMEOUT_S = 1800


class PhotoError(Exception):
    """خطایی که متنش برای کاربر است."""


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def abs_path(rel: str) -> Path:
    return media_root() / rel


def media_url(rel: str | None) -> str | None:
    if not rel:
        return None
    return settings.MEDIA_URL.rstrip("/") + "/" + rel.lstrip("/")


def _field_path(field) -> Path | None:
    try:
        if field and field.name:
            p = Path(field.path)
            return p if p.is_file() else None
    except (ValueError, NotImplementedError):
        return None
    return None


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)          # همان دیسک ⇐ جای اضافه نمی‌گیرد
    except OSError:
        shutil.copyfile(src, dst)


# ───────────────────────────── گره‌ها

def node_status() -> dict:
    from apps.compute import services as compute

    nodes = compute.online_nodes("photo")
    return {"online": bool(nodes), "nodes": [n.name for n in nodes]}


# ───────────────────────────── کتابخانه

def _finish_asset(asset: PhotoAsset, src: Path) -> PhotoAsset:
    """کپیِ ثابت + اندازه‌ها + بندانگشتی + اندازه‌گیری."""
    img = ops.load(src)
    d = abs_path(asset.dir_rel)
    d.mkdir(parents=True, exist_ok=True)
    suffix = {".jpeg": ".jpg"}.get(src.suffix.lower(), src.suffix.lower())
    if suffix in (".jpg", ".png", ".webp") and ops.orientation(src) == 1:
        original = d / f"source{suffix}"
        _link_or_copy(src, original)
    else:
        # BMP/TIFF/GIF، یا عکسِ موبایل با چرخشِ EXIF ⇐ یک بار صاف و ذخیره، تا کیت و مرورگر یک عکس ببینند
        fmt = "png" if img.mode == "RGBA" or suffix in (".png", ".bmp", ".tif", ".tiff", ".gif") else "jpeg"
        data, fmt = ops.encode(img, fmt, 95)
        original = d / ("source." + {"jpeg": "jpg"}.get(fmt, fmt))
        ops.save_bytes(original, data)
    ops.save_bytes(d / "thumb.jpg", ops.jpeg_bytes(img, THUMB_SIDE))
    ops.save_bytes(d / "preview.jpg", ops.jpeg_bytes(img, PREVIEW_SIDE, 88))   # «قبل» در مقایسه
    facts = ops.measure(img)
    asset.original = f"{asset.dir_rel}/{original.name}"
    asset.thumb = f"{asset.dir_rel}/thumb.jpg"
    asset.width, asset.height = img.size
    asset.size_bytes = original.stat().st_size
    asset.has_alpha = img.mode == "RGBA"
    asset.facts = facts
    asset.findings = ops.findings(facts)
    asset.save()
    return asset


def add_upload(store, user, upload, title: str = "") -> PhotoAsset:
    name = os.path.basename(getattr(upload, "name", "") or "photo.jpg")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise PhotoError(f"«{name}» عکس نیست (JPEG، PNG، WebP، TIFF یا BMP).")
    if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise PhotoError(f"«{name}» بیشتر از {MAX_UPLOAD_MB} مگابایت است.")
    asset = PhotoAsset.objects.create(store=store, created_by=user, title=(title or Path(name).stem)[:200],
                                      source_kind=PhotoAsset.Kind.UPLOAD, original="-")
    tmp = abs_path(asset.dir_rel) / f"upload{suffix}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "wb") as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    try:
        _finish_asset(asset, tmp)
    except ops.OpError as exc:
        shutil.rmtree(abs_path(asset.dir_rel), ignore_errors=True)
        asset.delete()
        raise PhotoError(f"«{name}»: {exc}") from exc
    tmp.unlink(missing_ok=True)      # اصل hardlink یا کپیِ خودش را دارد
    return asset


def resolve_ref(store, ref: str):
    """product_image:<id> | generated:<id> | edit:<id> ⇐ (نوع، فایل، عنوان، محصول)."""
    from apps.content.models import GeneratedImage
    from apps.products.models import ProductImage

    from services.imaging.text_overlay import to_persian_digits as fa

    kind, _, raw = (ref or "").partition(":")
    try:
        pk = int(raw)
    except ValueError:
        raise PhotoError("منبعِ عکس نامعتبر است.") from None
    if kind == "product_image":
        pi = ProductImage.objects.filter(pk=pk, product__store=store).select_related("product").first()
        if pi is None or not _field_path(pi.image):
            raise PhotoError("عکسِ محصول پیدا نشد.")
        return PhotoAsset.Kind.PRODUCT, _field_path(pi.image), f"{pi.product.name} — عکسِ {fa(str(pi.pk))}", pi.product
    if kind == "generated":
        gi = GeneratedImage.objects.filter(pk=pk, store=store).select_related("product").first()
        if gi is None or not _field_path(gi.image):
            raise PhotoError("تصویرِ ساخته‌شده پیدا نشد.")
        return PhotoAsset.Kind.GENERATED, _field_path(gi.image), f"{gi.product.name} — {gi.get_kind_display()}", gi.product
    if kind == "edit":
        ed = PhotoEdit.objects.filter(pk=pk, asset__store=store, state=PhotoEdit.State.READY).select_related(
            "asset", "asset__product").first()
        if ed is None or not ed.files.get("result") or not abs_path(ed.files["result"]).is_file():
            raise PhotoError("نسخهٔ ویرایش‌شده پیدا نشد.")
        return (PhotoAsset.Kind.EDIT, abs_path(ed.files["result"]), f"{ed.asset.title} — نسخهٔ {fa(str(ed.number))}",
                ed.asset.product)
    raise PhotoError("منبعِ عکس نامعتبر است.")


def add_ref(store, user, ref: str) -> tuple[PhotoAsset, bool]:
    """عکسی که از قبل در فروشگاه هست (محصول، تصویرِ ساخته‌شده، نسخهٔ ویرایش) ⇐ کتابخانه؛ دوباره‌آوردن همان را برمی‌گرداند."""
    existing = PhotoAsset.objects.filter(store=store, source_ref=ref).first()
    if existing and existing.original and abs_path(existing.original).is_file():
        return existing, False
    kind, path, title, product = resolve_ref(store, ref)
    asset = existing or PhotoAsset(store=store, created_by=user, source_kind=kind, source_ref=ref, original="-")
    asset.title, asset.product = title[:200], product
    asset.save()
    try:
        _finish_asset(asset, path)
    except ops.OpError as exc:
        asset.delete()
        raise PhotoError(str(exc)) from exc
    return asset, True


def delete_asset(asset: PhotoAsset) -> None:
    for e in asset.edits.filter(state__in=PhotoEdit.ACTIVE):
        cancel(e)
    shutil.rmtree(abs_path(asset.dir_rel), ignore_errors=True)
    asset.delete()


def list_sources(store, limit: int = 60) -> dict:
    """عکس‌هایی که می‌شود به کتابخانه آورد: عکس‌های محصول‌ها و تصویرهای ساخته‌شده."""
    from apps.content.models import GeneratedImage
    from apps.products.models import Product

    imported = set(PhotoAsset.objects.filter(store=store).exclude(source_ref="").values_list("source_ref", flat=True))

    def usable(field) -> bool:     # فایل‌های خراب/خالیِ قدیمی (۱ بایتی) در انتخابگر نیایند
        p = _field_path(field)
        return bool(p and p.stat().st_size > 100)

    products = []
    for p in Product.objects.filter(store=store).prefetch_related("images").order_by("-created_at")[:80]:
        imgs = [{"ref": f"product_image:{i.pk}", "id": i.pk, "url": i.image.url, "is_main": i.is_main,
                 "imported": f"product_image:{i.pk}" in imported} for i in p.images.all() if usable(i.image)]
        products.append({"id": p.pk, "name": p.name, "images": imgs})
    generated = [{"ref": f"generated:{g.pk}", "id": g.pk, "url": g.image.url, "product_id": g.product_id,
                  "product_name": g.product.name, "kind": g.kind, "kind_label": g.get_kind_display(),
                  "imported": f"generated:{g.pk}" in imported}
                 for g in GeneratedImage.objects.filter(store=store).select_related("product").order_by("-created_at")[:limit]
                 if usable(g.image)]
    return {"products": products, "generated": generated}


# ───────────────────────────── نسخه‌ها

def plan(asset: PhotoAsset, recipe_key: str) -> dict:
    """کارهای یک دستور برای همین عکس (با دلیل و تیکِ پیش‌فرض)."""
    node = node_status()
    if recipe_key == "suggest":
        operations = catalog.suggest(asset.facts or {}, asset.findings or [], node_online=node["online"])
    else:
        recipe = catalog.RECIPE_BY_KEY.get(recipe_key)
        if recipe is None:
            raise PhotoError("دستورِ ناشناخته.")
        operations = []
        for o in recipe["operations"]:
            where = catalog.tools()[o["tool"]]["where"]
            on = o["on"]
            # کارِ اختیاریِ سرورِ پردازش وقتی گره خاموش است تیک نمی‌خورد؛ جایگزینِ سبکش (اگر هست) تیک می‌خورد
            if o["optional"] and where == "node" and not node["online"]:
                on = False
            if o["optional"] and where == "server" and not o["on"] and not node["online"] and \
                    any(x["tool"] == "kit_auto" and x["optional"] for x in recipe["operations"]):
                on = True
            operations.append({"tool": o["tool"], "params": catalog.normalize_params(o["tool"], o["params"], strict=False),
                               "reason": catalog.tools()[o["tool"]]["help"], "optional": o["optional"], "on": on})
    for o in operations:
        o["where"] = catalog.tools()[o["tool"]]["where"]
        o["title"] = catalog.tools()[o["tool"]]["title"]
    out = {"recipe": recipe_key, "operations": operations, "node": node, "findings": asset.findings or []}
    if any(o["tool"] == "kit_smart" for o in operations):
        # «ویرایش با دستور»: کجا انجام می‌شود، راست و درست (سرورِ پردازش یا هوشِ مصنوعیِ سایت)
        from . import smart

        decision = smart.decide_path(asset.store)
        for o in operations:
            if o["tool"] == "kit_smart":
                o["where"] = "node" if decision["path"] == "node" else "server"
                o["reason"] = smart.path_help(decision)
        out["smart"] = decision
    return out


def _next_number(asset: PhotoAsset) -> int:
    return (asset.edits.aggregate(m=Max("number"))["m"] or 0) + 1


def create_edits(store, user, asset_ids, recipe_key: str, operations, order: int = catalog.ORDER_CURRENT) -> list[PhotoEdit]:
    """یک نسخه برای هر عکس. ``order``: نسخهٔ ترتیبِ کارها (۲ = قاب‌اول، برای کارِ تازه؛ ۱ = ترتیبِ قدیمی، برای ساختِ دوبارهٔ
    نسخه‌های قدیمی)؛ روی ``PhotoEdit.stats["order"]`` نشان می‌خورد تا «تلاشِ دوباره» عیناً همان را بسازد."""
    order = 1 if int(order or 1) < 2 else catalog.ORDER_CURRENT
    ids = []
    for x in asset_ids or []:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise PhotoError("اول یک یا چند عکس انتخاب کنید.")
    if len(ids) > MAX_BATCH:
        raise PhotoError(f"در هر بار حداکثر {MAX_BATCH} عکس.")
    assets = {a.pk: a for a in PhotoAsset.objects.filter(store=store, pk__in=ids)}
    if len(assets) != len(ids):
        raise PhotoError("بعضی عکس‌ها پیدا نشدند.")
    per_asset = {}
    if operations is None:
        if recipe_key == "suggest":
            for pk, a in assets.items():
                per_asset[pk] = catalog.normalize_operations(plan(a, "suggest")["operations"], order)
        else:
            recipe = catalog.RECIPE_BY_KEY.get(recipe_key)
            if recipe is None:
                raise PhotoError("دستورِ ناشناخته.")
            ops_ = catalog.normalize_operations(plan(next(iter(assets.values())), recipe_key)["operations"], order)
            per_asset = {pk: ops_ for pk in assets}
    else:
        try:
            ops_ = catalog.normalize_operations(operations, order)
            for o in ops_:      # عکسِ لایه‌های تصویری باید مالِ همین فروشگاه باشد
                if o["tool"] == "compose":
                    layers_mod.normalize_layers(o["params"]["layers"], store=store, base="one")
        except catalog.CatalogError as exc:
            raise PhotoError(str(exc)) from exc
        per_asset = {pk: ops_ for pk in assets}
    for pk, ops_ in per_asset.items():
        if not ops_:
            raise PhotoError("هیچ کاری انتخاب نشده.")
        if any(catalog.tools()[o["tool"]].get("single") for o in ops_) and len(ids) > 1:
            raise PhotoError("«ترمیمِ لکه» جای لکه‌های یک عکس را دارد؛ فقط یک عکس انتخاب کنید.")
    batch = uuid.uuid4().hex
    out = []
    with transaction.atomic():
        for pk in ids:
            asset = PhotoAsset.objects.select_for_update().get(pk=pk)
            out.append(PhotoEdit.objects.create(asset=asset, number=_next_number(asset), batch=batch, created_by=user,
                                                recipe=recipe_key if recipe_key in catalog.RECIPE_BY_KEY else "",
                                                operations=per_asset[pk], message="در صف", stats={"order": order}))
    return out


def _set(edit: PhotoEdit, **fields) -> None:
    for k, v in fields.items():
        setattr(edit, k, v)
    edit.save(update_fields=list(fields) + ["updated_at"])


def fail(edit: PhotoEdit, message: str) -> None:
    _set(edit, state=PhotoEdit.State.FAILED, error=message[:4000], message="ناموفق")


def _prepare_smart(edit: PhotoEdit) -> bool:
    """«ویرایش با دستور» (kit_smart) پیش از صف. ⇐ True = ادامه بده (کارها شاید بازنویسی شدند)، False = با این نسخه کاری نمانده.

    * node: اولویتِ بینایی «اول لوکال» و یک سرورِ پردازشِ photo آنلاین ⇒ همان صفِ سرورِ پردازش (کیت)؛ فقط تصمیم ثبت می‌شود.
    * site: هوشِ مصنوعی از خودِ سایت (لوکال ⇄ متیس، ترتیبِ تنظیماتِ هوش مصنوعی) ⇒ kit_smart ⇐ develop + ابزارهای سبکِ سایت؛
      اصلِ کارها در stats["original_operations"] می‌ماند؛ کارهای کیتِ بی‌همتا (پس‌زمینه، قابِ مربع، بزرگ‌نمایی) در صف می‌روند.
    """
    import time

    from . import smart

    asset = edit.asset
    ops_in = list(edit.operations or [])
    base_stats = dict(edit.stats or {})
    goal = next((o["params"].get("goal", "") for o in ops_in if o["tool"] == "kit_smart"), "")
    decision = smart.decide_path(asset.store)
    if decision["path"] == "node":
        _set(edit, stats=base_stats | {"smart": {"path": "node", "pending": True, "goal": goal, "via": "", "model": "",
                                                 "label": "", "fell_back": False, "reason": "", "adjust": {}, "notes": "",
                                                 "fallback": False}})
        return True
    began = time.monotonic()
    _set(edit, message="هوشِ مصنوعی عکس را می‌بیند…", progress=0.1,
         stats=base_stats | {"smart_running": True, "smart_started": timezone.now().isoformat()})
    try:
        result = smart.run_site_smart(asset, goal, asset.store, base=smart.base_of(ops_in))
    except Exception as exc:  # noqa: BLE001 — خطای برنامه (نه شکستِ هوش مصنوعی) هم نباید نسخه را بکشد
        logger.exception("photoedit: smart edit %s: AI step crashed", edit.pk)
        result = smart.fallback_result(asset, f"خطای داخلی: {exc}", goal)
    try:
        new_ops, result = smart.apply_site(asset, ops_in, result, order=int(base_stats.get("order") or 1))
    except Exception as exc:  # noqa: BLE001
        logger.exception("photoedit: smart edit %s: could not build operations", edit.pk)
        fail(edit, f"ویرایشِ هوشمند ساخته نشد: {exc}")
        return False
    meta = result.get("meta") or {}
    stats = base_stats | {"original_operations": ops_in, "smart": smart.stats_record(result, goal, time.monotonic() - began)}
    msg = ("هوشِ مصنوعی جواب نداد؛ نور و رنگِ خودکارِ سبک اعمال می‌شود" if meta.get("fallback")
           else f"{meta.get('label') or 'هوشِ مصنوعی'} تنظیم کرد")
    # در این فاصله کاربر ممکن است لغوش کرده باشد؛ فقط نسخهٔ هنوز QUEUED بازنویسی می‌شود
    won = PhotoEdit.objects.filter(pk=edit.pk, state=PhotoEdit.State.QUEUED).update(
        operations=new_ops, stats=stats, message=msg[:300], progress=0.3, updated_at=timezone.now())
    edit.refresh_from_db()
    return bool(won)


def start(edit: PhotoEdit) -> PhotoEdit:
    """کارهای کیت ⇐ یک کارِ photo.edit در صف (حتی وقتی هیچ گره‌ای آنلاین نیست)؛ بی کارِ کیت ⇐ همین حالا روی سرورِ سایت."""
    from apps.compute import services as compute

    if edit.state != PhotoEdit.State.QUEUED:
        return edit
    node_ops, server_ops = catalog.split(edit.operations)
    if any(o["tool"] == "kit_smart" for o in node_ops):
        # «ویرایش با دستور»: مسیر (سرورِ پردازش یا سایت) را اولویتِ هوشِ مصنوعی و وضعِ گره می‌گوید
        if not _prepare_smart(edit):
            return edit
        node_ops, server_ops = catalog.split(edit.operations)
    if not node_ops:
        return run_server_stage(edit)
    asset = edit.asset
    src = abs_path(asset.original)
    if not src.is_file():
        fail(edit, "فایلِ اصلِ عکس پیدا نشد.")
        return edit
    export = next((o["params"] for o in server_ops if o["tool"] == "export"), None)
    payload = catalog.kit_payload(node_ops, has_server_after=any(o["tool"] != "export" for o in server_ops),
                                  final_format=(export or {}).get("format"))
    name = f"photo-a{asset.pk}{src.suffix.lower()}"
    payload["image"] = name
    try:
        job = compute.enqueue("photo.edit", payload, {name: str(src)}, store=asset.store, origin="photoedit",
                              timeout_s=NODE_TIMEOUT_S, require_online=False, priority=95)
    except Exception as exc:  # noqa: BLE001
        logger.exception("photoedit: enqueue of edit %s failed", edit.pk)
        fail(edit, f"ثبت در صفِ سرورِ پردازش نشد: {exc}")
        return edit
    online = node_status()["online"]
    _set(edit, state=PhotoEdit.State.NODE, compute_job=str(job.uid), progress=0.05,
         message="در صفِ سرورِ پردازش" if online else "منتظرِ سرورِ پردازش — الان هیچ سرورِ پردازشی با ویرایشگرِ عکس آنلاین نیست",
         stats=dict(edit.stats or {}) | {"kit_payload": payload, "enqueued_at": timezone.now().isoformat(),
                                         "reused": job.state == job.State.COMPLETED})
    return edit


def refresh(edit: PhotoEdit) -> bool:
    """وضعیتِ کارِ گره ⇐ نسخه. True = خروجی رسید و نوبتِ مرحلهٔ سرورِ سایت است (و همین فراخوان آن را گرفت)."""
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    if edit.state != PhotoEdit.State.NODE or not edit.compute_job:
        return False
    job = ComputeJob.objects.filter(uid=edit.compute_job).select_related("node").first()
    if job is None:
        fail(edit, "کارِ سرورِ پردازش پیدا نشد.")
        return False
    if job.state == ComputeJob.State.COMPLETED:
        outs = job.outputs()
        primary = (job.result or {}).get("meta", {}).get("primary")
        img = next((o for o in outs if o["name"] == primary), None) or next(
            (o for o in outs if o.get("media") == "image"), None)
        if img is None:
            fail(edit, "سرورِ پردازش عکسی پس نفرستاد.")
            return False
        won = PhotoEdit.objects.filter(pk=edit.pk, state=PhotoEdit.State.NODE).update(
            state=PhotoEdit.State.SERVER, progress=0.8, message="مرحلهٔ آخر روی سرورِ سایت", updated_at=timezone.now())
        if not won:
            return False
        edit.refresh_from_db()
        src = compute.output_path(job, img["name"])
        dst = abs_path(edit.dir_rel) / ("node" + src.suffix.lower())
        _link_or_copy(src, dst)
        kit = {}
        side = next((o for o in outs if o["name"] == "photo-edit.json"), None)
        if side:
            try:
                kit = json.loads(compute.output_path(job, side["name"]).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                kit = {}
        took = (job.finished_at - job.claimed_at).total_seconds() if (job.finished_at and job.claimed_at) else None
        edit.files = dict(edit.files) | {"node": f"{edit.dir_rel}/{dst.name}"}
        edit.stats = dict(edit.stats) | {"node": job.node.name if job.node else "", "node_seconds": took,
                                         "kit": {k: kit.get(k) for k in ("recipe", "notes", "usedAi", "error", "steps", "model")
                                                 if k in kit}}
        if any(o["tool"] == "kit_smart" for o in edit.operations):    # «ویرایش با دستور» روی سرورِ پردازش: چه کسی جواب داد
            from . import smart

            edit.stats = dict(edit.stats) | {"smart": smart.node_record(kit, (edit.stats or {}).get("smart"))}
        edit.save(update_fields=["files", "stats", "updated_at"])
        return True
    if job.state in (ComputeJob.State.FAILED, ComputeJob.State.CANCELLED):
        fail(edit, "ویرایش روی سرورِ پردازش ناموفق بود: " + (job.error or job.get_state_display())[:1500])
        return False
    online = bool(compute.online_nodes("photo"))
    if job.state == ComputeJob.State.QUEUED:
        msg = "در صفِ سرورِ پردازش" if online else \
            "منتظرِ سرورِ پردازش — الان هیچ سرورِ پردازشی با ویرایشگرِ عکس آنلاین نیست"
        prog = 0.05
    else:
        msg = f"روی {job.node.name if job.node else 'سرورِ پردازش'}: {job.message or 'در حالِ ویرایش'}"
        prog = 0.1 + 0.65 * float(job.progress or 0)
    if msg != edit.message or abs(prog - edit.progress) > 0.005:
        _set(edit, message=msg[:300], progress=round(prog, 3))
    return False


def _store_logo(store) -> Path | None:
    return _field_path(getattr(store, "logo", None))


def server_ctx(store) -> dict:
    """زمینهٔ کارهای سرورِ سایت: لوگو / عکسِ کتابخانه (logo_path) و ماسکِ پروژه (mask_path)؛ scale را فراخواننده می‌گذارد."""

    def logo_path(p):
        if p.get("source") == "asset" and p.get("asset"):
            a = PhotoAsset.objects.filter(store=store, pk=int(p["asset"])).first()
            return abs_path(a.original) if a and abs_path(a.original).is_file() else None
        return _store_logo(store)

    def mask_path(project_id, mid):
        try:
            pr = PhotoProject.objects.filter(pk=int(project_id), store=store).select_related("asset").first()
        except (TypeError, ValueError):
            return None
        if pr is None or not layers_mod.MASK_ID_RE.match(str(mid)):
            return None
        p = abs_path(pr.dir_rel) / f"mask-{mid}.png"
        return p if p.is_file() else None

    def paint_path(project_id, pid):
        try:
            pr = PhotoProject.objects.filter(pk=int(project_id), store=store).select_related("asset").first()
        except (TypeError, ValueError):
            return None
        if pr is None or not layers_mod.MASK_ID_RE.match(str(pid)):
            return None
        p = abs_path(pr.dir_rel) / f"paint-{pid}.png"
        return p if p.is_file() else None

    def liquify_path(project_id):
        try:
            pr = PhotoProject.objects.filter(pk=int(project_id), store=store).first()
        except (TypeError, ValueError):
            return None
        if pr is None:
            return None
        p = abs_path(pr.dir_rel) / "liquify.bin"
        return p if p.is_file() else None

    return {"notes": [], "store_name": store.name, "logo_path": logo_path, "mask_path": mask_path,
            "paint_path": paint_path, "liquify_path": liquify_path, "scale": 1.0}


def run_server_stage(edit: PhotoEdit) -> PhotoEdit:
    """کارهای سرورِ سایت روی اصل (یا خروجیِ سرورِ پردازش) ⇐ نتیجه، پیش‌نمایش، بندانگشتی، اندازه‌گیری ⇐ READY."""
    if edit.state not in (PhotoEdit.State.QUEUED, PhotoEdit.State.SERVER):
        return edit
    _set(edit, state=PhotoEdit.State.SERVER, progress=max(edit.progress, 0.8), message="ساخت روی سرورِ سایت")
    asset = edit.asset
    store = asset.store
    _node_ops, server_ops = catalog.split(edit.operations)
    src = abs_path(edit.files["node"]) if edit.files.get("node") else abs_path(asset.original)
    vdir = abs_path(edit.dir_rel)

    ctx = server_ctx(store)
    try:
        img = ops.load(src)
        ctx["scale"] = (img.width / asset.width) if asset.width else 1.0
        out, export = ops.run(img, server_ops, ctx)
        fmt = export.get("format") or ops.default_format(out, src.suffix)
        if fmt == "jpeg" and out.mode == "RGBA" and not export:
            fmt = "png"
        if out.mode == "RGBA" and fmt == "jpeg":
            ctx["notes"].append("قالبِ JPEG شفافیت ندارد ⇐ روی زمینهٔ سفید")
        untouched = not [o for o in server_ops if o["tool"] != "export"] and not export and edit.files.get("node")
        vdir.mkdir(parents=True, exist_ok=True)
        if untouched:   # فقط کارِ کیت ⇐ همان فایلِ سرورِ پردازش، بی فشرده‌سازیِ دوباره
            result = vdir / ("result" + src.suffix.lower())
            _link_or_copy(src, result)
        else:
            data, fmt = ops.encode(out, fmt, int(export.get("quality") or 92), int(export.get("max_kb") or 0))
            result = vdir / ("result." + {"jpeg": "jpg"}.get(fmt, fmt))
            ops.save_bytes(result, data)
            if export.get("max_kb") and len(data) > export["max_kb"] * 1024:
                ctx["notes"].append(f"حجم با کمترین کیفیتِ مجاز هم {len(data) // 1024} کیلوبایت شد")
        ops.save_bytes(vdir / "preview.jpg", ops.jpeg_bytes(out, PREVIEW_SIDE, 88))
        ops.save_bytes(vdir / "thumb.jpg", ops.jpeg_bytes(out, THUMB_SIDE))
        after = ops.measure(out)
    except (ops.OpError, OSError) as exc:
        fail(edit, str(exc))
        return edit
    except Exception as exc:  # noqa: BLE001
        logger.exception("photoedit: server stage of edit %s failed", edit.pk)
        fail(edit, f"خطای داخلی: {exc}")
        return edit
    files = dict(edit.files) | {"result": f"{edit.dir_rel}/{result.name}", "preview": f"{edit.dir_rel}/preview.jpg",
                                "thumb": f"{edit.dir_rel}/thumb.jpg"}
    stats = dict(edit.stats or {}) | {"after": after, "server_notes": ctx["notes"], "bytes": result.stat().st_size,
                                      "format": result.suffix.lstrip(".")}
    _set(edit, state=PhotoEdit.State.READY, progress=1.0, message="آماده", files=files, stats=stats)
    return edit


def cancel(edit: PhotoEdit) -> PhotoEdit:
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    if not edit.active:
        return edit
    job = ComputeJob.objects.filter(uid=edit.compute_job).first() if edit.compute_job else None
    if job is not None and not job.final:
        compute.cancel(job)
    _set(edit, state=PhotoEdit.State.CANCELLED, message="لغو شد")
    return edit


def delete_edit(edit: PhotoEdit) -> None:
    cancel(edit)
    shutil.rmtree(abs_path(edit.dir_rel), ignore_errors=True)
    edit.delete()


def recover_stale(edit: PhotoEdit) -> bool:
    """مرحلهٔ سرورِ سایت که Celery ِ آن وسطِ کار رفت (ری‌استارت) ⇐ دوباره؛ True = باید دوباره فرستاده شود."""
    now = timezone.now()
    if edit.state == PhotoEdit.State.SERVER and edit.updated_at < now - timedelta(minutes=10):
        tries = int((edit.stats or {}).get("server_retries") or 0)
        if tries >= 2:
            fail(edit, "مرحلهٔ سرورِ سایت چند بار نیمه‌کاره ماند.")
            return False
        _set(edit, stats=dict(edit.stats) | {"server_retries": tries + 1})
        return True
    # ویرایشِ هوشمندِ سایت تا چند دقیقه منتظرِ هوشِ مصنوعی می‌ماند؛ در آن مدت دوباره فرستاده نشود
    wait = 12 if (edit.stats or {}).get("smart_running") else 5
    if edit.state == PhotoEdit.State.QUEUED and edit.updated_at < now - timedelta(minutes=wait):
        return True
    return False


# ───────────────────────────── تحلیلِ کیت (سرورِ پردازش)

def request_analysis(asset: PhotoAsset) -> PhotoAsset:
    from apps.compute import services as compute

    src = abs_path(asset.original)
    name = f"photo-a{asset.pk}{src.suffix.lower()}"
    job = compute.enqueue("photo.analyze", {"image": name}, {name: str(src)}, store=asset.store, origin="photoedit",
                          timeout_s=600, require_online=False, priority=110)
    asset.analysis_job = str(job.uid)
    asset.kit_analysis = {"state": "QUEUED"}
    asset.save(update_fields=["analysis_job", "kit_analysis", "updated_at"])
    refresh_analysis(asset)
    return asset


def refresh_analysis(asset: PhotoAsset) -> None:
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    if not asset.analysis_job or (asset.kit_analysis or {}).get("state") in ("READY", "FAILED"):
        return
    job = ComputeJob.objects.filter(uid=asset.analysis_job).first()
    if job is None:
        asset.kit_analysis = {"state": "FAILED", "error": "کار پیدا نشد."}
    elif job.state == ComputeJob.State.COMPLETED:
        out = next((o for o in job.outputs() if o["name"].endswith(".json")), None)
        try:
            data = json.loads(compute.output_path(job, out["name"]).read_text(encoding="utf-8")) if out else {}
        except (OSError, ValueError):
            data = {}
        auto = data.get("auto") or {}
        asset.kit_analysis = {"state": "READY", "text": data.get("text") or "", "notes": auto.get("notes") or [],
                              "auto_recipe": auto.get("recipe") or {}, "stats": data.get("stats") or {}}
    elif job.state in (ComputeJob.State.FAILED, ComputeJob.State.CANCELLED):
        asset.kit_analysis = {"state": "FAILED", "error": (job.error or "ناموفق")[:500]}
    else:
        online = bool(compute.online_nodes("photo"))
        asset.kit_analysis = {"state": job.state, "message": "در حالِ تحلیل" if job.state == ComputeJob.State.RUNNING
                              else ("در صفِ سرورِ پردازش" if online else "منتظرِ سرورِ پردازش")}
    asset.save(update_fields=["kit_analysis", "updated_at"])


# ───────────────────────────── پیش‌نمایشِ دقیقِ کارهای سبک

PREVIEW_SIDE_LIVE = 1280


def preview_source(asset: PhotoAsset):
    """تصویرِ ورودیِ پیش‌نمایش: عکسِ شفاف از خودِ اصل، عکسِ بزرگ از نسخهٔ ۱۶۰۰ پیکسلی (حافظهٔ سرور کم است)."""
    src = abs_path(asset.original)
    big = (asset.width or 0) * (asset.height or 0) > 6_000_000
    pv = abs_path(f"{asset.dir_rel}/preview.jpg")
    if big and not asset.has_alpha and pv.is_file():
        src = pv
    if not src.is_file():
        raise PhotoError("فایلِ اصلِ عکس پیدا نشد.")
    return ops.load(src)


def preview(asset: PhotoAsset, operations, order: int = catalog.ORDER_CURRENT) -> tuple[bytes, dict]:
    """کارهای سرورِ سایت (Pillow) روی نسخهٔ کوچکِ عکس، همین حالا و دقیق — برای متن، لوگو، واترمارک، برش، چرخش، رنگِ ساده.

    ترتیبِ کارها همان ترتیبِ قراردادیِ ساختِ نهایی است (``catalog.normalize_operations`` با ``order``)، پس پیش‌نمایش و
    خروجی یک ترتیب دارند.

    کارهای سرورِ پردازش (کیت) این‌جا اجرا نمی‌شوند: فهرستشان در ``skipped`` برمی‌گردد تا پنل بداند پیش‌نمایش کاملِ
    آن‌ها فقط با «ساخت» ِ نهایی روی سرورِ پردازش است.
    """
    try:
        clean = catalog.normalize_operations(operations if operations is not None else [], order)
    except catalog.CatalogError as exc:
        raise PhotoError(str(exc)) from exc
    node_ops, server_ops = catalog.split(clean)
    server_ops = [o for o in server_ops if o["tool"] != "export"]
    img = preview_source(asset)
    img.thumbnail((PREVIEW_SIDE_LIVE, PREVIEW_SIDE_LIVE), Image.Resampling.LANCZOS)
    ctx = server_ctx(asset.store)
    ctx["scale"] = (img.width / asset.width) if asset.width else 1.0
    try:
        out, _export = ops.run(img, server_ops, ctx)
    except ops.OpError as exc:
        raise PhotoError(str(exc)) from exc
    data = ops.jpeg_bytes(out, PREVIEW_SIDE_LIVE, 88)
    return data, {"size": list(out.size), "notes": ctx["notes"], "skipped": catalog.titles(node_ops)}


# ───────────────────────────── ذخیره و استفاده

def _result(edit: PhotoEdit) -> Path:
    if edit.state != PhotoEdit.State.READY or not edit.files.get("result"):
        raise PhotoError("این نسخه هنوز آماده نیست.")
    p = abs_path(edit.files["result"])
    if not p.is_file():
        raise PhotoError("فایلِ نتیجه پیدا نشد.")
    return p


def _product(store, product_id):
    from apps.products.models import Product

    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        raise PhotoError("محصول را انتخاب کنید.") from None
    product = Product.objects.filter(pk=pid, store=store).first()
    if product is None:
        raise PhotoError("محصول پیدا نشد.")
    return product


def save_to_product(edit: PhotoEdit, product_id, *, main: bool = False):
    path = _result(edit)
    product = _product(edit.asset.store, product_id or edit.asset.product_id)
    with open(path, "rb") as fh:
        image = product.images.create(image=File(fh, name=f"edit_{edit.asset_id}_{edit.number}{path.suffix}"),
                                      is_main=main, alt_text=edit.asset.title[:200],
                                      order=(product.images.aggregate(m=Max("order"))["m"] or 0) + 1)
    if main:
        product.images.exclude(pk=image.pk).update(is_main=False)
    saved = dict(edit.saved or {})
    saved["product_images"] = (saved.get("product_images") or []) + [{"id": image.pk, "product": product.pk}]
    _set(edit, saved=saved)
    return image


def use_in_content(edit: PhotoEdit, product_id):
    """نتیجه ⇐ «تصویرِ ساخته‌شده» (GeneratedImage، نوعِ بهبودِ عکس) ⇐ در استودیو تصویر، کپشن و کمپین‌ها انتخاب‌شدنی."""
    from apps.content.models import GeneratedImage

    path = _result(edit)
    asset = edit.asset
    product = _product(asset.store, product_id or asset.product_id)
    with open(path, "rb") as fh:
        gi = GeneratedImage.objects.create(
            store=asset.store, product=product, kind=GeneratedImage.Kind.ENHANCED,
            concept=f"ادیتور عکس: {asset.title} — نسخهٔ {edit.number}"[:500],
            instructions="، ".join(catalog.titles(edit.operations)), workflow_version="photo-editor",
            image=File(fh, name=f"photoedit_{asset.pk}_{edit.number}{path.suffix}"),
            metadata={"source": "photo_editor", "edit_id": edit.pk, "asset_id": asset.pk,
                      "operations": catalog.titles(edit.operations)})
    saved = dict(edit.saved or {})
    saved["generated_images"] = (saved.get("generated_images") or []) + [{"id": gi.pk, "product": product.pk}]
    _set(edit, saved=saved)
    return gi


def save_to_library(edit: PhotoEdit, user) -> PhotoAsset:
    _result(edit)
    asset, _new = add_ref(edit.asset.store, user, f"edit:{edit.pk}")
    saved = dict(edit.saved or {})
    if asset.pk not in (saved.get("assets") or []):
        saved["assets"] = (saved.get("assets") or []) + [asset.pk]
        _set(edit, saved=saved)
    return asset


# ───────────────────────────── برای پنل

def _needs_node(e: PhotoEdit, node_ops: list[dict]) -> bool:
    """بی «ویرایش با دستور»: bool(node_ops). با آن، تا مسیر معلوم نشده (QUEUED) فقط وقتی سرورِ پردازش لازم است که
    تصمیم «سرورِ پردازش» باشد یا کارِ کیتِ بی‌همتایی مانده باشد."""
    if not node_ops or e.state != PhotoEdit.State.QUEUED or not any(o["tool"] == "kit_smart" for o in node_ops):
        return bool(node_ops)
    from . import smart

    return bool(smart.residual_node_ops(e.operations or [])) or smart.decide_path(e.asset.store)["path"] == "node"


def edit_dict(e: PhotoEdit) -> dict:
    f = e.files or {}
    st = e.stats or {}
    node_ops, server_ops = catalog.split(e.operations or [])
    return {
        "id": e.id, "asset": e.asset_id, "number": e.number, "batch": e.batch, "recipe": e.recipe,
        "recipe_title": catalog.RECIPE_BY_KEY.get(e.recipe, {}).get("title", "دستی") if e.recipe else "دستی",
        "operations": [{"tool": o["tool"], "params": o["params"], "title": catalog.tools().get(o["tool"], {}).get("title", o["tool"]),
                        "where": catalog.tools().get(o["tool"], {}).get("where", "server"), "reason": o.get("reason", "")}
                       for o in e.operations or []],
        #: آنچه کیت/هوشِ مصنوعی واقعاً انتخاب کرد، به‌صورتِ کارهای جدا و قابل‌ویرایش (خالی = کیتی نبود یا هنوز برنگشته)
        "chosen": catalog.steps_from_kit_recipe((st.get("kit") or {}).get("recipe")) if e.state == PhotoEdit.State.READY else [],
        "needs_node": _needs_node(e, node_ops),
        #: «ویرایش با دستور»: path (node/site)، via، model، label، fell_back، reason، adjust، notes، fallback
        "smart": st.get("smart") or None,
        "state": e.state, "state_label": e.get_state_display(), "active": e.active,
        "progress": round(e.progress, 3), "message": e.message, "error": e.error,
        "urls": {k: media_url(f.get(k)) for k in ("result", "preview", "thumb", "node")},
        "size": [st["after"]["width"], st["after"]["height"]] if st.get("after") else None,
        "after": st.get("after"), "kit": st.get("kit") or {}, "server_notes": st.get("server_notes") or [],
        "node": st.get("node"), "node_seconds": st.get("node_seconds"), "bytes": st.get("bytes"),
        "order": int(st.get("order") or 1),
        "format": st.get("format"), "saved": e.saved or {}, "created_at": e.created_at, "updated_at": e.updated_at,
    }


def asset_dict(a: PhotoAsset, *, edits: bool = False) -> dict:
    out = {
        "id": a.id, "title": a.title, "source_kind": a.source_kind, "source_label": a.get_source_kind_display(),
        "source_ref": a.source_ref, "product": a.product_id, "product_name": a.product.name if a.product_id else None,
        "url": media_url(a.original), "thumb": media_url(a.thumb),
        "preview": media_url(f"{a.dir_rel}/preview.jpg") if abs_path(f"{a.dir_rel}/preview.jpg").is_file()
        else media_url(a.original),
        "width": a.width, "height": a.height,
        "size_bytes": a.size_bytes, "has_alpha": a.has_alpha, "facts": a.facts or {}, "findings": a.findings or [],
        "kit_analysis": a.kit_analysis or {}, "created_at": a.created_at,
    }
    qs = a.edits.all().order_by("-number")
    if edits:
        out["edits"] = [edit_dict(e) for e in qs]
    else:
        last = qs.first()
        out["last_edit"] = edit_dict(last) if last else None
        out["edits_count"] = qs.count()
    return out


# ═════════════════════════════ ادیتورِ حرفه‌ای: پروژه‌ها، ماسک‌ها، پیش‌نمایشِ دقیق، پیش‌تنظیم‌ها

MAX_PROJECT_BYTES = 2 * 1024 * 1024
MAX_PRESET_BYTES = 512 * 1024
MASK_MAX_SIDE = 2048
MASK_GC_AGE_S = 600
EXACT_KEEP = 8
#: کارهای کیت که در «پیش‌نمایشِ دقیق» با یک کپیِ کوچک اجرا می‌شوند (هندسه‌تغییردهنده‌ها و هوشِ مصنوعی نه)
EXACT_TOOLS = {"kit_auto", "kit_preset", "kit_adjust", "kit_denoise", "kit_sharpen", "kit_heal"}
PRESET_TOOLS = ("look", "auto_tone", "color", "crop_format", "kit_preset", "kit_denoise", "kit_sharpen",
                "kit_background", "kit_square", "kit_upscale")


class ProjectConflict(PhotoError):
    """ذخیره با شمارهٔ نسخهٔ کهنه — پروژه از جای دیگری عوض شده."""


def project_dir(project: PhotoProject) -> Path:
    return abs_path(project.dir_rel)


def mask_file(project: PhotoProject, mid: str) -> Path:
    if not layers_mod.MASK_ID_RE.match(str(mid or "")):
        raise PhotoError("شناسهٔ ماسک نامعتبر است.")
    return project_dir(project) / f"mask-{mid}.png"


def paint_file(project: PhotoProject, pid: str) -> Path:
    if not layers_mod.MASK_ID_RE.match(str(pid or "")):
        raise PhotoError("شناسهٔ لایهٔ نقاشی نامعتبر است.")
    return project_dir(project) / f"paint-{pid}.png"


def liquify_file(project: PhotoProject) -> Path:
    return project_dir(project) / "liquify.bin"


def liquify_info(project: PhotoProject) -> dict | None:
    """نقشهٔ مایع‌سازیِ پروژه ⇒ {rev, gw, gh, url} یا None (فایل نیست/خراب است). rev = int(mtime)."""
    from . import liquify as lq

    path = liquify_file(project)
    try:
        gw, gh = lq.peek(path)
        rev = int(path.stat().st_mtime)
    except (OSError, lq.LiquifyError):
        return None
    return {"rev": rev, "gw": gw, "gh": gh, "url": f"{media_url(project.dir_rel + '/liquify.bin')}?v={rev}"}


def save_liquify(project: PhotoProject, raw: bytes) -> dict:
    """بایت‌های LQF1 ⇒ هدر و اندازه وارسی ⇒ liquify.bin (اتمیک) ⇒ {rev, gw, gh}. rev همیشه از قبلی بزرگ‌تر است."""
    from . import liquify as lq

    if not raw:
        raise PhotoError("فایلِ مایع‌سازی خالی است.")
    try:
        gw, gh = lq.parse_header(raw)
    except lq.LiquifyError as exc:
        raise PhotoError(str(exc)) from exc
    path = liquify_file(project)
    try:
        prev = int(path.stat().st_mtime)
    except OSError:
        prev = 0
    ops.save_bytes(path, raw)
    rev = int(path.stat().st_mtime)
    if rev <= prev:                        # دو ذخیره در یک ثانیه ⇒ rev تکراری نشود (کلیدِ کشِ مرورگر)
        rev = prev + 1
        os.utime(path, (rev, rev))
    return {"rev": rev, "gw": gw, "gh": gh}


def delete_liquify(project: PhotoProject) -> bool:
    path = liquify_file(project)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    return existed


def ensure_frame_v2(project: PhotoProject) -> tuple[PhotoProject, dict | None]:
    """پروژهٔ fv=1 را یک بار به مدلِ «قاب‌اول» (fv=2) کوچ می‌دهد: داده ذخیره می‌شود، ``rev``+۱ و JSON ِ اصل در
    ``PhotoProject.legacy`` می‌ماند (ماسک‌های رنگ‌آمیزیِ اصل هم ``v1-mask-<id>.png``). ⇐ ``(پروژه، گزارش)``؛ گزارش
    ``None`` یعنی از قبل fv=2 بود. کوچِ ناموفق چیزی ذخیره نمی‌کند (گزارش ``stamped=False`` و ``error`` دارد)."""
    cur = project.data if isinstance(project.data, dict) else {}
    if frames._fv(cur) >= frames.FV:
        return project, None
    with transaction.atomic():
        locked = PhotoProject.objects.select_for_update().select_related("asset", "store").get(pk=project.pk)
        before = locked.data if isinstance(locked.data, dict) else {}
        if frames._fv(before) >= frames.FV:
            return locked, None
        asset = locked.asset
        pdir = project_dir(locked)
        new, rep = frames.migrate_v1_to_v2(before, asset.width, asset.height, pdir,
                                           asset_path=abs_path(asset.original) if asset.original else None)
        if not rep["stamped"]:
            return locked, rep
        try:
            cleaned = _clean_project_data(new, locked.store)
            locked.legacy = locked.legacy or json.loads(json.dumps(before))
            locked.data = cleaned
            locked.rev += 1
            locked.save(update_fields=["data", "legacy", "rev"])   # updated_at دست نمی‌خورد (ترتیبِ فهرست)
        except Exception as exc:  # noqa: BLE001 — ماسک‌های بازنویسی‌شده برگردند، داده همان fv=1 بماند
            frames.restore_v1_masks(pdir, rep["mask_ids"])
            if not isinstance(exc, PhotoError):
                raise
            rep.update(stamped=False, changed=False, error=str(exc),
                       notes=list(rep["notes"]) + [f"کوچِ قاب‌اول انجام نشد: {exc}"])
            return locked, rep
    return locked, rep


def project_dict(p: PhotoProject, *, full: bool = True, migrate: bool = True) -> dict:
    """پروژه برای پنل. ``full`` + ``migrate``: پروژهٔ fv=1 همین‌جا یک بار به fv=2 کوچ داده می‌شود (``ensure_frame_v2``) و
    کلیدِ ``migration`` (فقط همان بار) گزارش را دارد. پاسخِ ساخت/ذخیره/تعارض ``migrate=False`` می‌گیرند تا ``rev`` عوض نشود."""
    report = None
    if full and migrate:
        p, report = ensure_frame_v2(p)
    out = {"id": p.pk, "asset": p.asset_id, "title": p.title, "rev": p.rev, "updated_at": p.updated_at,
           "thumb": media_url(p.asset.thumb)}
    if report is not None:
        out["migration"] = {"migrated": bool(report["stamped"]), "trivial": bool(report["trivial"]), "notes": report["notes"],
                            "error": report["error"]}
    if full:
        masks = {}
        d = project_dir(p)
        if d.is_dir():
            for f in sorted(d.glob("mask-*.png")):
                masks[f.stem[5:]] = f"{media_url(p.dir_rel + '/' + f.name)}?v={int(f.stat().st_mtime)}"
        paints = {}
        if d.is_dir():
            for f in sorted(d.glob("paint-*.png")):
                paints[f.stem[6:]] = f"{media_url(p.dir_rel + '/' + f.name)}?v={int(f.stat().st_mtime)}"
        out["data"] = p.data or {}
        out["masks"] = masks
        out["paints"] = paints
        out["liquify"] = liquify_info(p)          # {rev, gw, gh, url} یا None
    return out


def _clean_project_data(data, store) -> dict:
    if not isinstance(data, dict):
        raise PhotoError("دادهٔ پروژه باید یک شیء باشد.")
    data = dict(data)
    if isinstance(data.get("layers"), list):
        try:
            data["layers"] = layers_mod.normalize_layers(data["layers"], store=store, base="at_most_one")
        except catalog.CatalogError as exc:
            raise PhotoError(str(exc)) from exc
    elif "layers" in data:
        raise PhotoError("layers باید فهرست باشد.")
    if "liquify" in data:      # نشانِ نقشهٔ مایع‌سازیِ پروژه: null یا {"rev": int}
        lq = data["liquify"]
        try:
            data["liquify"] = {"rev": int(lq["rev"])} if isinstance(lq, dict) and lq.get("rev") is not None else None
        except (TypeError, ValueError):
            data["liquify"] = None
    if len(json.dumps(data, ensure_ascii=False)) > MAX_PROJECT_BYTES:
        raise PhotoError("پروژه بزرگ‌تر از ۲ مگابایت است.")
    return data


def create_project(store, asset: PhotoAsset, title: str = "", data=None) -> PhotoProject:
    cleaned = _clean_project_data(data if data is not None else {}, store)
    return PhotoProject.objects.create(store=store, asset=asset, title=(title or asset.title or "")[:200], data=cleaned)


def save_project(project: PhotoProject, *, data=None, title=None, rev=None) -> PhotoProject:
    with transaction.atomic():
        locked = PhotoProject.objects.select_for_update().select_related("asset", "store").get(pk=project.pk)
        if rev is not None and int(rev) != locked.rev:
            raise ProjectConflict("پروژه در جای دیگری عوض شده است؛ نسخهٔ تازه را باز کنید.")
        if data is not None:
            locked.data = _clean_project_data(data, locked.store)
        if title is not None:
            locked.title = str(title)[:200]
        locked.rev += 1
        locked.save()
    gc_masks(locked)
    return locked


def gc_masks(project: PhotoProject, *, min_age_s: int = MASK_GC_AGE_S) -> int:
    """ماسک‌های بی‌ارجاع (و قدیمی‌تر از min_age_s؛ ماسکِ تازه‌بارگذاری‌شده هنوز در JSON نیامده ممکن است) پاک می‌شوند."""
    d = project_dir(project)
    if not d.is_dir():
        return 0
    used = layers_mod.mask_ids((project.data or {}).get("layers"))
    now = timezone.now().timestamp()
    n = 0
    for f in d.glob("mask-*.png"):
        if f.stem[5:] not in used and now - f.stat().st_mtime >= min_age_s:
            f.unlink(missing_ok=True)
            n += 1
    used_paint = layers_mod.paint_ids((project.data or {}).get("layers"))
    for f in d.glob("paint-*.png"):
        if f.stem[6:] not in used_paint and now - f.stat().st_mtime >= min_age_s:
            f.unlink(missing_ok=True)
            n += 1
    return n


def delete_project(project: PhotoProject) -> None:
    shutil.rmtree(project_dir(project), ignore_errors=True)
    project.delete()


def save_mask(project: PhotoProject, mid: str, raw: bytes) -> tuple[Path, int, int]:
    """PNG/JPEG ِ ماسک ⇐ خاکستری، حداکثر ۲۰۴۸ پیکسل ⇐ mask-<id>.png."""
    path = mask_file(project, mid)
    if not raw:
        raise PhotoError("فایلِ ماسک خالی است.")
    if len(raw) > 30 * 1024 * 1024:
        raise PhotoError("فایلِ ماسک خیلی بزرگ است.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            if im.mode in ("RGBA", "LA") and im.convert("L").getextrema() == (0, 0):
                g = im.getchannel("A")          # ماسک فقط در آلفا (قلمِ سفید روی شفاف نبود)
            else:
                g = im.convert("L")
    except Exception as exc:  # noqa: BLE001
        raise PhotoError("ماسک عکسِ معتبری نیست.") from exc
    g.thumbnail((MASK_MAX_SIDE, MASK_MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    g.save(buf, "PNG", optimize=True)
    ops.save_bytes(path, buf.getvalue())
    return path, g.width, g.height


def save_paint(project: PhotoProject, pid: str, raw: bytes) -> tuple[Path, int, int]:
    """PNG ِ RGBA ِ لایهٔ نقاشی ⇐ حداکثر ۲۰۴۸ پیکسل ⇐ paint-<id>.png (آلفا حفظ می‌شود)."""
    path = paint_file(project, pid)
    if not raw:
        raise PhotoError("فایلِ لایهٔ نقاشی خالی است.")
    if len(raw) > 40 * 1024 * 1024:
        raise PhotoError("فایلِ لایهٔ نقاشی خیلی بزرگ است.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            g = im.convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise PhotoError("لایهٔ نقاشی عکسِ معتبری نیست.") from exc
    g.thumbnail((MASK_MAX_SIDE, MASK_MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    g.save(buf, "PNG", compress_level=4)
    ops.save_bytes(path, buf.getvalue())
    return path, g.width, g.height


# ───────────────────────────── پیش‌نمایشِ دقیق (کیت روی کپیِ کوچک)

def _prune_dir(d: Path, keep: int) -> None:
    files = sorted((f for f in d.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[keep:]:
        f.unlink(missing_ok=True)


def _small_copy(asset: PhotoAsset, side: int, subdir: str, stem: str) -> tuple[Path, Image.Image]:
    img = preview_source(asset)
    img.thumbnail((side, side), Image.Resampling.LANCZOS)
    d = abs_path(asset.dir_rel) / subdir
    d.mkdir(parents=True, exist_ok=True)
    fmt = "png" if img.mode == "RGBA" else "jpeg"
    data, fmt = ops.encode(img, fmt, 92)
    path = d / f"{stem}-{side}.{'png' if fmt == 'png' else 'jpg'}"
    ops.save_bytes(path, data)
    _prune_dir(d, EXACT_KEEP * 3)
    return path, img


def _job_state(job) -> str:
    from apps.compute.models import ComputeJob

    return {ComputeJob.State.QUEUED: "QUEUED", ComputeJob.State.CLAIMED: "RUNNING", ComputeJob.State.RUNNING: "RUNNING",
            ComputeJob.State.COMPLETED: "COMPLETED", ComputeJob.State.FAILED: "FAILED",
            ComputeJob.State.CANCELLED: "CANCELLED"}.get(job.state, job.state)


def exact_request(asset: PhotoAsset, operations, side: int = 1280) -> dict:
    """کارهای کیتِ لغزنده‌ها روی کپیِ کوچکِ عکس، روی سرورِ پردازش (فقط وقتی آنلاین است)."""
    from apps.compute import services as compute

    node = node_status()
    if not node["online"]:
        return {"online": False, "state": "OFFLINE", "nodes": []}
    try:
        clean = catalog.normalize_operations(operations if operations is not None else [])
    except catalog.CatalogError as exc:
        raise PhotoError(str(exc)) from exc
    node_ops, _server = catalog.split(clean)
    use = [o for o in node_ops if o["tool"] in EXACT_TOOLS]
    ignored = catalog.titles([o for o in node_ops if o["tool"] not in EXACT_TOOLS])
    if not use:
        return {"online": True, "state": "NOOP", "ignored": ignored, "nodes": node["nodes"]}
    try:
        side = int(max(320, min(2000, int(side))))
    except (TypeError, ValueError):
        side = 1280
    path, img = _small_copy(asset, side, "exact", f"photo-x{asset.pk}")
    payload = catalog.kit_payload(use, has_server_after=False, final_format="jpeg")
    recipe = payload["recipe"]
    adj = recipe.get("adjust") or {}
    if "sharpenRadius" in adj and asset.width:
        # شعاعِ شارپ به پیکسلِ اندازهٔ اصل است؛ روی کپیِ کوچک متناسب می‌شود (حداقلِ کیت ۰٫۵)
        adj["sharpenRadius"] = round(max(0.5, min(3.0, adj["sharpenRadius"] * img.width / asset.width)), 3)
    recipe.setdefault("output", {}).update({"format": "jpeg", "quality": 90})
    payload["image"] = path.name
    payload["x_asset"] = asset.pk
    try:
        job = compute.enqueue("photo.edit", payload, {path.name: str(path)}, store=asset.store, origin="photoexact",
                              timeout_s=180, require_online=True, priority=30)
    except compute.ComputeUnavailable:
        return {"online": False, "state": "OFFLINE", "nodes": []}
    return {"online": True, "job": str(job.uid), "state": _job_state(job), "ignored": ignored, "nodes": node["nodes"],
            "size": list(img.size)}


def _image_output(job):
    from apps.compute import services as compute

    outs = job.outputs()
    primary = (job.result or {}).get("meta", {}).get("primary")
    out = next((o for o in outs if o["name"] == primary), None) or next((o for o in outs if o.get("media") == "image"), None)
    return (out, compute.output_path(job, out["name"])) if out else (None, None)


def _job_for(store, uid, origin: str):
    from apps.compute.models import ComputeJob

    try:
        return ComputeJob.objects.filter(uid=uid, origin=origin, store=store).first()
    except Exception:  # noqa: BLE001 — شناسهٔ خراب
        return None


def exact_status(store, uid) -> dict | None:
    job = _job_for(store, uid, "photoexact")
    if job is None:
        return None
    out = {"job": str(job.uid), "state": _job_state(job), "message": job.message, "progress": round(job.progress or 0, 3),
           "node": job.node.name if job.node_id else None, "url": None, "size": None,
           "online": bool(node_status()["online"])}
    if job.state == job.State.FAILED:
        out["error"] = (job.error or "")[:500]
    if job.state == job.State.COMPLETED:
        meta, src = _image_output(job)
        asset = PhotoAsset.objects.filter(store=store, pk=(job.payload or {}).get("x_asset") or 0).first()
        if meta is None or src is None or not src.is_file() or asset is None:
            out.update(state="FAILED", error="سرورِ پردازش عکسی پس نفرستاد.")
            return out
        d = abs_path(asset.dir_rel) / "exact"
        d.mkdir(parents=True, exist_ok=True)
        dst = d / f"out-{str(job.uid)[:12]}{src.suffix.lower() or '.jpg'}"
        if not dst.is_file():
            _link_or_copy(src, dst)
            _prune_dir(d, EXACT_KEEP * 3)
        try:
            with Image.open(dst) as im:
                out["size"] = list(im.size)
        except Exception:  # noqa: BLE001
            pass
        rel = str(dst.relative_to(media_root())).replace(os.sep, "/")
        out["url"] = f"{media_url(rel)}?v={int(dst.stat().st_mtime)}"
    return out


def exact_cancel(store, uid, origin: str = "photoexact") -> bool:
    from apps.compute import services as compute

    job = _job_for(store, uid, origin)
    if job is None:
        return False
    if not job.final:
        compute.cancel(job)
    return True


def exact_finish_for_test(job, node=None, *, factor: float = 1.2):
    """آزمون/توسعه: نقشِ گرهٔ پردازش را بازی می‌کند — همین کار را به نامِ گره برمی‌دارد (کارِ دیگری را نه)، عکسِ ورودی را
    به اندازهٔ ``factor`` روشن می‌کند (کارِ «انتخابِ سوژه»: خروجیِ PNG ِ شفاف با بیضیِ وسط) و با همان قراردادِ agent
    (خروجی ``<نام>-edited.<jpg|png>`` + ``meta.primary``) تمامش می‌کند. ⇐ کارِ تمام‌شده.

    مثال روی سرور: ``manage.py photoedit_fake_node online`` ⇐ (درخواستِ exact از مرورگر) ⇐ ``manage.py photoedit_fake_node finish``.
    """
    from PIL import ImageEnhance

    from apps.compute import services as compute
    from apps.compute.models import ComputeNode

    node = node or ComputeNode.objects.filter(enabled=True).first() or ComputeNode.objects.create(
        name="gpu-fake", last_seen=timezone.now(), capabilities={"photo": True})
    if job.state != job.State.QUEUED:
        raise PhotoError("این کار دیگر در صف نیست.")
    job.node, job.state, job.attempts = node, job.State.RUNNING, job.attempts + 1
    job.claimed_at = job.heartbeat_at = timezone.now()
    job.save()
    root = compute.job_root(job)
    src = root / "inputs" / (job.payload or {}).get("image", "")
    stem = Path(src.name).stem
    if job.origin == "photosubject":
        im = Image.open(src).convert("RGBA")
        alpha = Image.new("L", im.size, 0)
        ImageDraw.Draw(alpha).ellipse([im.width * 0.2, im.height * 0.2, im.width * 0.8, im.height * 0.8], fill=255)
        im.putalpha(alpha)
        name = stem + "-edited.png"
        im.save(compute.output_path(job, name), "PNG")
    else:
        img = ImageEnhance.Brightness(Image.open(src).convert("RGB")).enhance(factor)
        name = stem + "-edited.jpg"
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        compute.output_path(job, name).write_bytes(buf.getvalue())
    return compute.finish(job, node, True, meta={"primary": name, "engine": "photo"})


# ───────────────────────────── «انتخابِ سوژه»

def _mask_png(mask_u8, asset: PhotoAsset, token: str) -> tuple[str, int, int]:
    d = abs_path(asset.dir_rel) / "subject"
    d.mkdir(parents=True, exist_ok=True)
    g = Image.fromarray(mask_u8, "L")
    buf = io.BytesIO()
    g.save(buf, "PNG", optimize=True)
    path = d / f"{token}.png"
    ops.save_bytes(path, buf.getvalue())
    _prune_dir(d, 10)
    rel = str(path.relative_to(media_root())).replace(os.sep, "/")
    return f"{media_url(rel)}?v={int(path.stat().st_mtime)}", g.width, g.height


def subject_grabcut(asset: PhotoAsset, rect=None) -> dict:
    """جایگزینِ سبکِ سرور وقتی سرورِ پردازش خاموش است: cv2.grabCut روی کپیِ ۵۱۲ پیکسلی (یا آلفای خودِ عکسِ شفاف)."""
    import cv2
    import numpy as np

    img = preview_source(asset)
    img.thumbnail((512, 512), Image.Resampling.LANCZOS)
    if img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 250:
        mask = np.asarray(img.getchannel("A"), dtype=np.uint8).copy()
        url, w, h = _mask_png(mask, asset, "alpha")
        return {"state": "READY", "method": "alpha", "url": url, "w": w, "h": h}
    arr = np.asarray(ops.flatten(img))[..., ::-1].copy()
    h, w = arr.shape[:2]
    try:
        x, y, rw, rh = (float(v) for v in rect)
    except (TypeError, ValueError):
        x, y, rw, rh = 0.05, 0.05, 0.9, 0.9
    x0, y0 = int(max(0, min(w - 2, round(x * w)))), int(max(0, min(h - 2, round(y * h))))
    box = (x0, y0, int(max(2, min(w - x0, round(rw * w)))), int(max(2, min(h - y0, round(rh * h)))))
    gc = np.zeros((h, w), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(arr, gc, box, bgd, fgd, 4, cv2.GC_INIT_WITH_RECT)
    fg = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fg = cv2.GaussianBlur(fg, (0, 0), 1.2)
    url, mw, mh = _mask_png(fg, asset, "grabcut")
    return {"state": "READY", "method": "grabcut", "url": url, "w": mw, "h": mh}


def subject_request(asset: PhotoAsset, rect=None) -> dict:
    from apps.compute import services as compute

    node = node_status()
    if not node["online"]:
        return subject_grabcut(asset, rect)
    path, _img = _small_copy(asset, 1024, "subject", f"photo-s{asset.pk}")
    op = {"tool": "kit_background", "params": catalog.normalize_params(
        "kit_background", {"method": "auto", "bg": "transparent", "shadow": 0, "cleanup": -1})}
    payload = catalog.kit_payload([op], has_server_after=False, final_format="png")
    payload["image"] = path.name
    payload["x_asset"] = asset.pk
    try:
        job = compute.enqueue("photo.edit", payload, {path.name: str(path)}, store=asset.store, origin="photosubject",
                              timeout_s=300, require_online=True, priority=30)
    except compute.ComputeUnavailable:
        return subject_grabcut(asset, rect)
    return {"state": _job_state(job), "method": "kit", "job": str(job.uid)}


def subject_status(store, uid) -> dict | None:
    import numpy as np

    job = _job_for(store, uid, "photosubject")
    if job is None:
        return None
    out = {"job": str(job.uid), "state": _job_state(job), "method": "kit", "message": job.message}
    if job.state == job.State.FAILED:
        out["error"] = (job.error or "")[:500]
    if job.state == job.State.COMPLETED:
        meta, src = _image_output(job)
        asset = PhotoAsset.objects.filter(store=store, pk=(job.payload or {}).get("x_asset") or 0).first()
        if meta is None or src is None or not src.is_file() or asset is None:
            out.update(state="FAILED", error="سرورِ پردازش عکسی پس نفرستاد.")
            return out
        with Image.open(src) as im:
            alpha = np.asarray(im.convert("RGBA").getchannel("A"), dtype=np.uint8).copy()
        url, w, h = _mask_png(alpha, asset, f"kit-{str(job.uid)[:12]}")
        out.update(url=url, w=w, h=h)
        out["state"] = "READY"
    return out


# ───────────────────────────── فونت‌ها

def fonts_list() -> list[dict]:
    from . import fontreg

    files = textlayer.font_files()
    if not files:
        return []
    out = [{"key": "vazirmatn", "title": "وزیرمتن", "family": "Vazirmatn", "weights": sorted(files), "rtl": True}]
    out += [fontreg.info(k) for k in fontreg.available()]
    return out


# ───────────────────────────── پیش‌تنظیم‌ها (ذخیره، اعمال روی چند عکس)

def normalize_preset_data(data) -> dict:
    if not isinstance(data, dict):
        raise PhotoError("دادهٔ پیش‌تنظیم باید یک شیء باشد.")
    try:
        tools = {}
        for key, params in (data.get("tools") if isinstance(data.get("tools"), dict) else {}).items():
            if key in PRESET_TOOLS:
                tools[key] = catalog.normalize_params(key, params, strict=False)
        out_in = data.get("output") if isinstance(data.get("output"), dict) else {}
        fmt = out_in.get("format") if out_in.get("format") in ("jpeg", "png", "webp") else "jpeg"
        le = out_in.get("long_edge")
        out = {
            "adjust": develop_np.normalize_adjust(data.get("adjust") if isinstance(data.get("adjust"), dict) else {}),
            "curve": catalog.normalize_curve(data.get("curve")),
            "kit_auto": bool(data.get("kit_auto")),
            "tools": tools,
            "layers": layers_mod.preset_layers(data.get("layers")),
            "output": {"format": fmt, "quality": int(catalog._clamp(out_in.get("quality"), 40, 100, 92)),
                       "max_kb": int(catalog._clamp(out_in.get("max_kb"), 0, 20000, 0)),
                       "long_edge": 0 if not le else int(catalog._clamp(le, 64, 8000, 0))},
        }
    except catalog.CatalogError as exc:
        raise PhotoError(str(exc)) from exc
    if len(json.dumps(out, ensure_ascii=False)) > MAX_PRESET_BYTES:
        raise PhotoError("پیش‌تنظیم خیلی بزرگ است.")
    return out


def preset_dict(p: PhotoPreset) -> dict:
    return {"id": p.pk, "name": p.name, "kind": p.kind, "data": p.data or {}, "created_at": p.created_at,
            "updated_at": p.updated_at}


def preset_operations(data, node_online: bool) -> list[dict]:
    """داده‌ی پیش‌تنظیم ⇐ فهرستِ کارها برای ``create_edits``، با ترتیبِ قراردادیِ v2 (قاب‌اول):
    کارهای کیت (آنلاین) یا develop (خاموش) ⇐ crop_format ⇐ auto_tone ⇐ look ⇐ color ⇐ compose (روکش‌ها روی بومِ نهایی)
    ⇐ resize ⇐ export."""
    d = normalize_preset_data(data)
    adjust, curve, tools = dict(d["adjust"]), dict(d["curve"]), d["tools"]
    ops_: list[dict] = []

    def add(tool, params):
        ops_.append({"tool": tool, "params": catalog.normalize_params(tool, params, strict=False)})

    if node_online:
        if d["kit_auto"]:
            add("kit_auto", {})
        for key in ("kit_preset", "kit_denoise", "kit_sharpen", "kit_background", "kit_square", "kit_upscale"):
            if key in tools:
                add(key, tools[key])
        if adjust or curve:
            add("kit_adjust", {"adjust": adjust, "curve": curve})
    else:
        merged: dict = {}
        mcurve: dict = {}
        preset = tools.get("kit_preset")
        if preset:   # فیلترِ کیت ⇐ لغزنده‌هایش، زیرِ لغزنده‌های خودِ کاربر
            rec = catalog.kit_presets().get(preset["preset"], {}).get("recipe") or {}
            merged.update(rec.get("adjust") or {})
            mcurve.update(catalog.normalize_curve(rec.get("curve")))
        if "kit_denoise" in tools:
            merged.update({"noiseLuma": tools["kit_denoise"]["luma"], "noiseColor": tools["kit_denoise"]["color"]})
        if "kit_sharpen" in tools:
            sp = tools["kit_sharpen"]
            merged.update({"sharpen": sp["amount"], "sharpenRadius": sp["radius"], "sharpenMasking": sp["masking"]})
        merged.update(adjust)
        mcurve.update(curve)
        if merged or mcurve:
            add("develop", {"adjust": merged, "curve": mcurve, "spots": []})
    for key in ("crop_format", "auto_tone", "look", "color"):    # قاب و رنگ پیش از روکش‌ها (مثلِ catalog.SERVER_ORDER_V2)
        if key in tools:
            add(key, tools[key])
    if d["layers"]:
        base = {"id": "base", "type": "base", "name": "عکس"}
        add("compose", {"project": 0, "layers": [base] + d["layers"]})
    out = d["output"]
    if out["long_edge"]:
        add("resize", {"long_edge": out["long_edge"]})
    add("export", {"format": out["format"], "quality": out["quality"], "max_kb": out["max_kb"]})
    return ops_


# ═════════════════════════════ «پرکردنِ هوشمند» (FLUX inpaint روی سرورِ پردازش)

GENFILL_ORIGIN = "photogenfill"
GENFILL_PRIORITY = 105          # پایین‌تر از ویرایش‌های معمولی (۹۵) و تحلیل (۱۱۰)
GENFILL_TIMEOUT_S = 1200
GENFILL_MAX_ACTIVE = 4          # هم‌زمان در صف/اجرا برای هر فروشگاه
GENFILL_TITLE = "پرکردن هوشمند"
GENFILL_WAIT_MESSAGE = "سرورِ پردازش خاموش است؛ کار در صف می‌ماند و وقتی روشن شد انجام می‌شود"
#: ``node_wanted`` ِ کاری که منتظرِ ترجمهٔ توضیحِ فارسی به انگلیسی است. ``compute.claim`` فقط کارهایی با node_wanted خالی یا
#: نامِ همان گره می‌دهد ⇒ هیچ گره‌ای این کار را نمی‌گیرد تا ترجمه برسد (بی هیچ تغییری در apps.compute و عاملِ گره).
#: ترجمه که رسید، گراف عوض و node_wanted به مقدارِ اصلی برمی‌گردد (genfill_release).
GENFILL_HOLD = "~translating"
GENFILL_TR_RETRY_S = 30             # فاصلهٔ تلاش‌های دوبارهٔ ترجمه وقتی مترجمی نیست
GENFILL_TR_GIVE_UP_H = 72           # بعد از این‌همه ساعت بی‌مترجم، کار با پیامِ روشن ناموفق می‌شود
GENFILL_TR_STALE_S = 240            # اگر این‌قدر از آخرین تلاش گذشته، زنجیرهٔ تلاش مرده فرض می‌شود و پنل دوباره راهش می‌اندازد
GENFILL_TR_WAIT = ("توضیح فارسی است و پیش از ساختن باید به انگلیسی ترجمه شود، ولی الان هیچ مترجمی در دسترس نیست. کار گم نمی‌شود: "
                   "به‌محضِ روشن‌شدنِ سرورِ پردازش یا شارژِ متیس خودکار ترجمه و ساخته می‌شود. اگر نمی‌خواهید منتظر بمانید، "
                   "توضیح را همین‌جا انگلیسی بنویسید.")


def _tr_wait_message(reason: str = "") -> str:
    return GENFILL_TR_WAIT + (f" (علت: {reason})" if reason else "")


def _genfill_node() -> str:
    """گرهٔ انتخاب‌شده در پنل («سرورِ تصویر و ویدیو»)؛ خالی = هر گره‌ای که ComfyUI دارد."""
    try:
        from services.comfyui import remote

        return remote.node_name("agent://any")
    except Exception:  # noqa: BLE001
        return ""


def genfill_online() -> bool:
    try:
        from services.comfyui import remote

        return bool(remote.comfy_nodes_online("agent://any"))
    except Exception:  # noqa: BLE001
        return False


def _genfill_caps() -> dict:
    """توانایی‌های گرهٔ ComfyUI ِ مناسب (آنلاین‌ها اول)؛ گره‌ای که مدل‌هایش را گزارش نکرده ⇐ {} (ناشناخته)."""
    from apps.compute.models import ComputeNode

    wanted = _genfill_node()
    rows = [n for n in ComputeNode.objects.filter(enabled=True) if (not wanted or n.name == wanted) and n.has("comfyui")]
    rows.sort(key=lambda n: (not n.online, -(n.last_seen.timestamp() if n.last_seen else 0)))
    for n in rows:
        caps = n.capabilities or {}
        if isinstance(caps.get("comfy_models"), dict) and caps["comfy_models"]:
            return caps
    return {}


def genfill_fake_caps() -> dict:
    """آزمون/توسعه: توانایی‌های یک گرهٔ ComfyUI ِ ساختگی که فقط چک‌پوینتِ FLUX dev ِ مالک را دارد."""
    from . import inpaint_graph

    choice = inpaint_graph.choose({"comfy_models": {"checkpoints": [inpaint_graph.DEFAULT_DEV_CKPT], "unet": []}})
    return {"comfyui": True, "comfy_nodes": sorted(set(choice["required_nodes"]) | {"KSamplerAdvanced", "ImageScale"}),
            "comfy_models": {"checkpoints": [inpaint_graph.DEFAULT_DEV_CKPT], "unet": []}}


def _genfill_seed(seed) -> int:
    import secrets

    if seed in (None, ""):
        return secrets.randbelow(2 ** 31)
    try:
        return abs(int(seed)) % (2 ** 32)
    except (TypeError, ValueError):
        raise PhotoError("seed باید یک عدد باشد.") from None


def _tr_public(tr) -> dict:
    """بخشی از وضعیتِ ترجمه که به پنل می‌رود."""
    tr = tr if isinstance(tr, dict) else {}
    return {k: tr.get(k, d) for k, d in (("state", "none"), ("source", ""), ("fa", ""), ("en", ""), ("label", ""),
                                         ("message", ""), ("attempts", 0))}


def _genfill_prompt_plan(store, prompt: str, prompt_en) -> tuple[str, dict, bool]:
    """توضیحِ کاربر ⇒ (متنی که در گراف می‌نشیند، وضعیتِ ترجمه، آیا باید کار منتظرِ ترجمه بماند).

    بی حرفِ فارسی (انگلیسی یا خالی) ⇒ دست‌نخورده. فارسی + انگلیسیِ نوشته/ویرایش‌شدهٔ کاربر ⇒ همان (و برای دفعهٔ بعد کَش می‌شود).
    فارسی بی انگلیسی ⇒ کَش؛ نبود ⇒ کار «منتظرِ ترجمه» ثبت می‌شود (مترجمِ لوکال/متیس بعداً صدا زده می‌شود)."""
    from . import inpaint, translate

    fa = translate.normalize(prompt)
    if not translate.needs_translation(fa):
        return fa, {"state": "none", "fa": fa, "en": fa, "source": "none"}, False
    en_user = " ".join(str(prompt_en or "").split())
    hit = translate.cache_get(store, fa)
    if en_user:
        if not translate.valid_english(en_user, max_len=inpaint.MAX_PROMPT):
            raise PhotoError("متنِ انگلیسی باید حرفِ لاتین داشته باشد، بدونِ حرفِ فارسی، و کوتاه باشد.")
        if hit is not None and hit.en == en_user:
            return en_user, {"state": "ok", **hit.as_dict()}, False
        translate.remember_user(store, fa, en_user)
        return en_user, {"state": "ok", "fa": fa, "en": en_user, "source": "user", "label": "نوشتهٔ شما"}, False
    if hit is not None:
        return hit.en, {"state": "ok", **hit.as_dict()}, False
    return fa, {"state": "waiting", "fa": fa, "en": "", "source": "", "label": "", "attempts": 0, "since": timezone.now().isoformat(),
                "last_try": None, "message": GENFILL_TR_WAIT}, True


def genfill_request(store, user, asset: PhotoAsset, image_bytes: bytes, mask_bytes: bytes, prompt: str = "",
                    seed=None, prompt_en=None) -> dict:
    """بومِ فعلی + ماسک ⇐ کارِ comfy.graph (FLUX inpaint) در صف — حتی وقتی گره خاموش است. ⇐ {job, state, online, message, …}.

    ``prompt`` فارسی باشد ⇒ پیش از ساختن به انگلیسیِ تحت‌اللفظی ترجمه می‌شود (``translate``): ``prompt_en`` (متنی که پنل نشان داد و
    کاربر شاید ویرایش کرد) یا کَشِ ترجمه ⇒ همان‌جا؛ وگرنه کار با ``node_wanted=GENFILL_HOLD`` در صف می‌نشیند (هیچ گره‌ای
    برنمی‌دارد) و یک کارِ celery تا پیدا شدنِ مترجم ترجمه را امتحان می‌کند، بعد گراف را عوض و کار را آزاد می‌کند."""
    import hashlib
    import tempfile

    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    from . import inpaint, inpaint_graph

    active = ComputeJob.objects.filter(origin=GENFILL_ORIGIN, store=store, state__in=(
        ComputeJob.State.QUEUED, ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING)).count()
    if active >= GENFILL_MAX_ACTIVE:
        from services.imaging.text_overlay import to_persian_digits as fa

        raise PhotoError(f"هم‌اکنون {fa(str(GENFILL_MAX_ACTIVE))} «پرکردنِ هوشمند» در صف یا در حالِ ساخت است؛ "
                         "صبر کنید تمام شوند یا یکی را لغو کنید.")
    effective, tr, hold = _genfill_prompt_plan(store, prompt, prompt_en)
    try:
        prep = inpaint.prepare(image_bytes, mask_bytes, effective)
    except inpaint.InpaintError as exc:
        raise PhotoError(str(exc)) from exc
    caps = _genfill_caps()
    try:
        choice = inpaint_graph.choose(caps)
    except inpaint_graph.GraphError as exc:
        raise PhotoError(str(exc)) from exc
    seed = _genfill_seed(seed)
    key = hashlib.sha256(prep.image_png + prep.mask_png).hexdigest()[:12]
    names = {"image": f"nmgf_{key}_image.png", "mask": f"nmgf_{key}_mask.png", "full": f"nmgf_{key}_full.png"}
    graph = inpaint_graph.build(choice, names["image"], names["mask"], prep.prompt, seed, prep.size)
    missing = inpaint_graph.check_nodes(graph, caps.get("comfy_nodes"))
    if missing:
        raise PhotoError("روی سرورِ پردازش این نودهای ComfyUI نصب نیست و «پرکردنِ هوشمند» بدونشان کار نمی‌کند: "
                         + "، ".join(missing))
    meta = prep.meta() | {"asset": asset.pk, "user": getattr(user, "pk", None), "seed": seed, "full_mask": names["full"],
                          "engine": {k: choice.get(k) for k in ("kind", "loader", "label", "assumed")},
                          "prompt_fa": tr.get("fa", ""), "tr": tr, "node_wanted": _genfill_node()}
    payload = {"graph": graph, "uploads": [names["image"], names["mask"]], "x_genfill": meta}
    with tempfile.TemporaryDirectory(prefix="nmgf-") as tmp:
        files = {}
        for what, data in (("image", prep.image_png), ("mask", prep.mask_png), ("full", prep.full_mask_png)):
            p = Path(tmp) / names[what]
            p.write_bytes(data)
            files[names[what]] = str(p)
        try:
            # payload شناسهٔ عکس را دارد ⇒ درخواستِ یکسانِ فروشگاهِ دیگر هرگز هم‌اثر نمی‌شود (dedupe فقط برای خودِ ما)
            # منتظرِ ترجمه: از همان لحظهٔ ثبت node_wanted=HOLD (نه بعداً) تا گرهٔ آنلاین در فاصلهٔ ثبت و نگه‌داشتن آن را نگیرد
            job = compute.enqueue("comfy.graph", payload, files, store=store, origin=GENFILL_ORIGIN,
                                  priority=GENFILL_PRIORITY, timeout_s=GENFILL_TIMEOUT_S,
                                  node=GENFILL_HOLD if hold else _genfill_node(), require_online=False)
        except Exception as exc:  # noqa: BLE001
            logger.exception("photoedit: genfill enqueue failed")
            raise PhotoError(f"ثبت در صفِ سرورِ پردازش نشد: {exc}") from exc
    online = genfill_online()
    state = _job_state(job)
    holding = state == "QUEUED" and job.node_wanted == GENFILL_HOLD
    if holding:
        _genfill_kick(job.uid)         # زیرِ آزمون (celery eager) همین‌جا اجرا می‌شود و شاید کار را آزاد کند
        job.refresh_from_db()
        state = _job_state(job)
        holding = state == "QUEUED" and job.node_wanted == GENFILL_HOLD
    final_tr = ((job.payload or {}).get("x_genfill") or {}).get("tr") or tr
    if holding:
        message = final_tr.get("message") or GENFILL_TR_WAIT
    else:
        message = "آماده" if state == "COMPLETED" else ("در صفِ سرورِ پردازش" if online else GENFILL_WAIT_MESSAGE)
    return {"job": str(job.uid), "state": state, "online": online, "message": message,
            "engine": choice["label"], "notes": choice["notes"], "translation": _tr_public(final_tr)}


def _genfill_kick(uid) -> None:
    """کارِ celery ِ «ترجمه ⇐ آزادکردن» را راه می‌اندازد (بی‌بروکر: لاگ؛ تلاشِ بعدیِ پنل دوباره راهش می‌اندازد)."""
    from . import tasks

    try:
        tasks.genfill_translate_job_task.delay(str(uid))
    except Exception:  # noqa: BLE001
        logger.warning("photoedit: celery unavailable, genfill translation of %s waits for the next panel poll", uid)


def _genfill_meta_of(job) -> dict:
    return ((job.payload or {}).get("x_genfill")) or {}


def _genfill_patch(job, *, tr_update: dict | None = None, graph_text: str | None = None, prompt: str | None = None,
                   release: bool = False, fail: str = "") -> bool:
    """کارِ منتظرِ ترجمه را اتمی تغییر می‌دهد (فقط اگر هنوز QUEUED و HOLD باشد). ⇒ اعمال شد؟

    ``release``: node_wanted به گرهٔ اصلی برمی‌گردد (از این لحظه گره می‌تواند بگیرد)؛ ``fail``: کار با این پیام ناموفق می‌شود."""
    import copy

    from apps.compute.models import ComputeJob

    fresh = ComputeJob.objects.filter(pk=job.pk, state=ComputeJob.State.QUEUED, node_wanted=GENFILL_HOLD).first()
    if fresh is None:
        return False
    payload = copy.deepcopy(fresh.payload or {})
    meta = payload.setdefault("x_genfill", {})
    if tr_update:
        meta["tr"] = {**(meta.get("tr") or {}), **tr_update}
    if prompt is not None:
        meta["prompt"] = prompt
    if graph_text is not None:
        try:
            payload["graph"]["20"]["inputs"]["text"] = graph_text
        except (KeyError, TypeError):
            return False
    fields: dict = {"payload": payload}
    if release:
        fields["node_wanted"] = meta.get("node_wanted") or ""
        fields["message"] = ""
    elif fail:
        fields.update(state=ComputeJob.State.FAILED, error=fail[:4000], message="ناموفق", finished_at=timezone.now(),
                      node_wanted=meta.get("node_wanted") or "")
    return ComputeJob.objects.filter(pk=job.pk, state=ComputeJob.State.QUEUED, node_wanted=GENFILL_HOLD).update(**fields) == 1


def genfill_release(job, tr) -> bool:
    """ترجمه (یا انگلیسیِ نوشتهٔ کاربر) رسید ⇒ گراف به‌روز و کار برای گره آزاد می‌شود. ⇒ آزاد شد؟ (کسِ دیگری زودتر آزاد/لغو کرده ⇒ False)"""
    from . import inpaint_graph

    en = " ".join(str(tr.en).split())
    done = {"state": "ok", "en": en, "source": tr.source, "via": tr.via, "model": tr.model, "label": tr.label or "نوشتهٔ شما",
            "message": "", "fa": tr.fa}
    return _genfill_patch(job, tr_update=done, graph_text=inpaint_graph.effective_prompt(en), prompt=en, release=True)


def genfill_translate_step(uid) -> str:
    """یک گامِ ترجمهٔ کارِ منتظر (از celery). ⇒ "done" | "waiting" | "failed" | "busy" | "gone".

    waiting = مترجمی نیست (دوباره امتحان می‌شود)؛ failed = مترجم دو بار خروجیِ بی‌مصرف داد یا ۷۲ ساعت گذشت (کار ناموفق شد)."""
    from datetime import datetime

    from apps.compute.models import ComputeJob

    from . import translate

    job = ComputeJob.objects.filter(uid=uid, origin=GENFILL_ORIGIN).select_related("store").first()
    if job is None or job.state != ComputeJob.State.QUEUED or job.node_wanted != GENFILL_HOLD:
        return "gone"
    meta = _genfill_meta_of(job)
    tr = meta.get("tr") or {}
    fa = meta.get("prompt_fa") or tr.get("fa") or ""
    lock = _genfill_dir(job.store, meta.get("asset")) / f"{str(job.uid)[:12]}.tr.lock"
    if not _take_lock(lock, stale_s=600):
        return "busy"
    try:
        now = timezone.now()
        try:
            since = datetime.fromisoformat(tr.get("since") or "")
        except ValueError:
            since = now
        if since.tzinfo is None:
            since = timezone.make_aware(since)
        if now - since > timedelta(hours=GENFILL_TR_GIVE_UP_H):
            msg = ("ترجمه: در ۷۲ ساعت هیچ مترجمی در دسترس نشد و این «پرکردنِ هوشمند» لغو شد؛ دوباره اجرا کنید "
                   "(یا توضیح را انگلیسی بنویسید).")
            _genfill_patch(job, tr_update={"state": "failed", "message": msg}, fail=msg)
            return "failed"
        _genfill_patch(job, tr_update={"last_try": now.isoformat(), "attempts": int(tr.get("attempts") or 0) + 1})
        try:
            res = translate.translate(fa, store=job.store)
        except translate.Unavailable as exc:
            _genfill_patch(job, tr_update={"state": "waiting", "message": _tr_wait_message(exc.reason)})
            return "waiting"
        except translate.Failed as exc:
            msg = f"ترجمه: {exc}"
            _genfill_patch(job, tr_update={"state": "failed", "message": msg}, fail=msg)
            return "failed"
        except Exception as exc:  # noqa: BLE001 — خطای پیش‌بینی‌نشده نباید کار را بکشد؛ بعداً دوباره
            logger.exception("photoedit: genfill translation step of %s crashed", job.uid)
            _genfill_patch(job, tr_update={"state": "waiting", "message": _tr_wait_message(translate.explain(exc))})
            return "waiting"
        return "done" if genfill_release(job, res) else "gone"
    finally:
        lock.unlink(missing_ok=True)


def genfill_set_english(store, uid, text) -> dict | None:
    """کاربر برای کارِ منتظرِ ترجمه خودش انگلیسی نوشت ⇒ همان‌جا آزاد می‌شود. ⇒ وضعیت یا None (کار نیست)."""
    from . import translate

    job = _job_for(store, uid, GENFILL_ORIGIN)
    if job is None:
        return None
    en = " ".join(str(text or "").split())
    from . import inpaint

    if not translate.valid_english(en, max_len=inpaint.MAX_PROMPT):
        raise PhotoError("متنِ انگلیسی باید حرفِ لاتین داشته باشد، بدونِ حرفِ فارسی، و کوتاه باشد.")
    meta = _genfill_meta_of(job)
    fa = meta.get("prompt_fa") or ""
    if not genfill_release(job, translate.Translation(fa=fa, en=en, source="user", label="نوشتهٔ شما")):
        raise PhotoError("این کار دیگر منتظرِ ترجمه نیست (شاید ترجمه شد، لغو شد یا تمام شده است).")
    if fa:
        translate.remember_user(store, fa, en)
    return genfill_status(store, uid)


def _genfill_error_text(raw: str) -> str:
    raw = (raw or "").strip()
    low = raw.lower()
    if raw.startswith("ترجمه"):          # شکستِ مرحلهٔ ترجمه (genfill_translate_step): پیامش خودش کامل است
        return raw
    if "not in list" in low:
        why = "نامِ مدل یا فایلِ لازم (چک‌پوینت/CLIP/VAE) روی سرورِ پردازش پیدا نشد."
    elif "out of memory" in low or "oom" in low.split():
        why = "حافظهٔ کارتِ گرافیک کم آمد؛ ناحیهٔ کوچک‌تری انتخاب کنید و دوباره امتحان کنید."
    elif "missing_node_type" in low or "node_errors" in low and "does not exist" in low:
        why = "یکی از نودهای لازمِ ComfyUI روی سرورِ پردازش نصب نیست."
    elif "unavailable" in low or "refused" in low or "10061" in low:
        why = "ComfyUI روی سرورِ پردازش پاسخ نداد."
    else:
        why = "ساختنِ تصویر روی سرورِ پردازش ناموفق بود."
    return f"پرکردنِ هوشمند انجام نشد: {why}" + (f" (جزئیات: {raw[:300]})" if raw else "")


def _genfill_dir(store, asset_id) -> Path:
    a = PhotoAsset.objects.filter(store=store, pk=asset_id).first() if asset_id else None
    d = abs_path(a.dir_rel if a else f"photoedit/s{store.pk}") / "genfill"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _take_lock(path: Path, stale_s: int = 120) -> bool:
    import time

    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        try:
            if time.time() - path.stat().st_mtime > stale_s:       # قفلِ جامانده از ری‌استارت
                path.unlink(missing_ok=True)
                return _take_lock(path, stale_s)
        except OSError:
            pass
        return False


def _asset_from_bytes(store, user, data: bytes, *, title: str, source_ref: str = "", product=None,
                      kind=None) -> PhotoAsset:
    """مثلِ add_upload ولی از بایت‌ها (نتیجه‌های ساخته‌شده روی سرور)."""
    asset = PhotoAsset.objects.create(store=store, created_by=user, product=product, title=title[:200],
                                      source_kind=kind or PhotoAsset.Kind.GENERATED, source_ref=source_ref[:60],
                                      original="-")
    tmp = abs_path(asset.dir_rel) / "upload.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    try:
        _finish_asset(asset, tmp)
    except ops.OpError as exc:
        shutil.rmtree(abs_path(asset.dir_rel), ignore_errors=True)
        asset.delete()
        raise PhotoError(str(exc)) from exc
    tmp.unlink(missing_ok=True)
    return asset


def _genfill_finalize(store, job):
    """خروجیِ گره ⇐ patch ِ RGBA ⇐ عکسِ کتابخانه. تکرارپذیر: بارِ دوم همان عکس را برمی‌گرداند. None = هم‌زمان کسِ دیگری می‌سازد."""
    import time

    from django.contrib.auth import get_user_model

    from apps.compute import services as compute

    from . import inpaint

    meta = (job.payload or {}).get("x_genfill") or {}
    uid12 = str(job.uid)[:12]
    ref = f"genfill:{job.uid}"
    folder = _genfill_dir(store, meta.get("asset"))
    info = folder / f"{uid12}.json"

    def existing():
        a = PhotoAsset.objects.filter(store=store, source_ref=ref).first()
        if a is not None and info.is_file():
            try:
                data = json.loads(info.read_text(encoding="utf-8"))
                return a, data["layer"], data.get("size")
            except (OSError, ValueError, KeyError):
                return None
        return None

    hit = existing()
    if hit:
        return hit
    lock = folder / f"{uid12}.lock"
    if not _take_lock(lock):
        for _ in range(40):          # کسِ دیگری (درخواستِ هم‌زمان) در حالِ ساختن است
            time.sleep(0.25)
            hit = existing()
            if hit:
                return hit
        return None
    try:
        hit = existing()
        if hit:
            return hit
        out_meta, src = _image_output(job)
        if out_meta is None or src is None or not src.is_file():
            raise PhotoError("سرورِ پردازش عکسی پس نفرستاد.")
        mask_path = compute.job_root(job) / "inputs" / os.path.basename(str(meta.get("full_mask") or "-"))
        if not mask_path.is_file():
            raise PhotoError("ماسکِ این کار پیدا نشد؛ دوباره اجرا کنید.")
        try:
            rect, canvas = meta["rect"], meta["canvas"]
            with Image.open(src) as res_im, Image.open(mask_path) as mk:
                res_im.load()
                mk.load()
                pasted = inpaint.paste_back((rect[2] - rect[0], rect[3] - rect[1]), res_im, mk, meta.get("feather"),
                                            origin=(rect[0], rect[1]), canvas=(canvas[0], canvas[1]),
                                            grow=int(meta.get("grow_full") or 0))
        except (inpaint.InpaintError, OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise PhotoError(f"چسباندنِ نتیجه انجام نشد: {exc}") from exc
        buf = io.BytesIO()
        pasted.patch.save(buf, "PNG", compress_level=4)
        info.write_text(json.dumps({"layer": pasted.placement, "size": list(pasted.patch.size),
                                    "bbox": list(pasted.bbox)}), encoding="utf-8")
        user = get_user_model().objects.filter(pk=meta["user"]).first() if meta.get("user") else None
        origin = PhotoAsset.objects.filter(store=store, pk=meta.get("asset") or 0).select_related("product").first()
        asset = _asset_from_bytes(store, user, buf.getvalue(), title=GENFILL_TITLE, source_ref=ref,
                                  product=origin.product if origin else None)
        return asset, pasted.placement, list(pasted.patch.size)
    finally:
        lock.unlink(missing_ok=True)


def genfill_status(store, uid) -> dict | None:
    """وضعیتِ یک «پرکردنِ هوشمند»؛ وقتی گره تمام کرد ⇐ همین‌جا چسباندن و ساختنِ عکسِ کتابخانه (فقط یک بار)."""
    job = _job_for(store, uid, GENFILL_ORIGIN)
    if job is None:
        return None
    state = _job_state(job)
    online = genfill_online()
    node = job.node.name if job.node_id else None
    tr = _genfill_meta_of(job).get("tr")
    out = {"job": str(job.uid), "state": state, "message": "", "progress": round(float(job.progress or 0), 3),
           "node": node, "online": online, "translation": _tr_public(tr)}
    if state == "QUEUED" and job.node_wanted == GENFILL_HOLD:
        _genfill_nudge(job, tr)
        out.update(message=(tr or {}).get("message") or GENFILL_TR_WAIT, progress=max(out["progress"], 0.02))
    elif state == "QUEUED":
        out.update(message="در صفِ سرورِ پردازش" if online else GENFILL_WAIT_MESSAGE, progress=max(out["progress"], 0.02))
    elif state == "RUNNING":
        out["message"] = f"روی «{node or 'سرورِ پردازش'}» در حالِ ساختن…"
    elif state == "FAILED":
        out.update(message="ناموفق", error=_genfill_error_text(job.error))
    elif state == "CANCELLED":
        out["message"] = "لغو شد"
    elif state == "COMPLETED":
        try:
            built = _genfill_finalize(store, job)
        except PhotoError as exc:
            out.update(state="FAILED", message="ناموفق", error=str(exc))
            return out
        except Exception as exc:  # noqa: BLE001
            logger.exception("photoedit: genfill finalize of %s failed", job.uid)
            out.update(state="FAILED", message="ناموفق", error=f"خطای داخلی: {exc}")
            return out
        if built is None:
            out.update(state="RUNNING", message="در حالِ ساختنِ لایه…")
            return out
        asset, layer, size = built
        took = (job.finished_at - job.claimed_at).total_seconds() if (job.finished_at and job.claimed_at) else None
        out.update(state="READY", message="آماده", progress=1.0, asset=asset_dict(asset), layer=layer, size=size,
                   seconds=round(took, 1) if took is not None else None)
    return out


def _genfill_nudge(job, tr) -> None:
    """هر بار که پنل می‌پرسد: اگر زنجیرهٔ تلاشِ ترجمه مرده باشد (ری‌استارتِ celery، پاک‌شدنِ صف) دوباره راهش می‌اندازد."""
    from datetime import datetime

    tr = tr if isinstance(tr, dict) else {}
    ref = tr.get("last_try") or tr.get("since")
    try:
        last = datetime.fromisoformat(ref) if ref else None
    except ValueError:
        last = None
    if last is not None and last.tzinfo is None:
        last = timezone.make_aware(last)
    if last is None or (timezone.now() - last).total_seconds() > GENFILL_TR_STALE_S:
        _genfill_kick(job.uid)


def genfill_cancel(store, uid) -> bool:
    return exact_cancel(store, uid, GENFILL_ORIGIN)


def genfill_finish_for_test(job, node=None, *, result_scale: float = 1.0, error: str = ""):
    """آزمون/توسعه: نقشِ گرهٔ ComfyUI را بازی می‌کند — کارِ photogenfill را برمی‌دارد، ناحیهٔ ماسک را با cv2.inpaint پر
    می‌کند (``genfill_00001_.png``، با ``result_scale`` می‌شود اندازهٔ خروجی را عوض کرد) و مثلِ agent تمامش می‌کند.
    ``error`` ⇐ کار ناموفق تمام می‌شود."""
    import cv2
    import numpy as np

    from apps.compute import services as compute
    from apps.compute.models import ComputeNode

    node = node or ComputeNode.objects.filter(enabled=True).first() or ComputeNode.objects.create(
        name="gpu-fake", last_seen=timezone.now(), capabilities=genfill_fake_caps())
    if job.state != job.State.QUEUED:
        raise PhotoError("این کار دیگر در صف نیست.")
    job.node, job.state, job.attempts = node, job.State.RUNNING, job.attempts + 1
    job.claimed_at = job.heartbeat_at = timezone.now()
    job.save()
    if error:
        return compute.finish(job, node, False, error=error, meta={"retryable": False})
    root = compute.job_root(job)
    up = (job.payload or {}).get("uploads") or []
    img = np.asarray(Image.open(root / "inputs" / up[0]).convert("RGB"))
    mask = np.asarray(Image.open(root / "inputs" / up[1]).convert("L")) >= 128
    mask = cv2.dilate(mask.astype(np.uint8) * 255, np.ones((5, 5), np.uint8))
    filled = cv2.inpaint(np.ascontiguousarray(img[..., ::-1]), mask, 5, cv2.INPAINT_TELEA)[..., ::-1]
    out = Image.fromarray(np.ascontiguousarray(filled))
    if result_scale != 1.0:
        out = out.resize((max(1, round(out.width * result_scale)), max(1, round(out.height * result_scale))))
    name = "genfill_00001_.png"
    out.save(compute.output_path(job, name), "PNG")
    return compute.finish(job, node, True, meta={"primary": name, "engine": "comfyui"})


# ─── پایانِ «پرکردنِ هوشمند» ───
