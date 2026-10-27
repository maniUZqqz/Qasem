"""منطقِ ادیتورِ عکس: کتابخانه، نسخه‌ها، صفِ سرورِ پردازش و کارهای سرورِ سایت."""
from __future__ import annotations

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

from . import catalog, ops
from .models import PhotoAsset, PhotoEdit

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
    return {"recipe": recipe_key, "operations": operations, "node": node, "findings": asset.findings or []}


def _next_number(asset: PhotoAsset) -> int:
    return (asset.edits.aggregate(m=Max("number"))["m"] or 0) + 1


def create_edits(store, user, asset_ids, recipe_key: str, operations) -> list[PhotoEdit]:
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
                per_asset[pk] = catalog.normalize_operations(plan(a, "suggest")["operations"])
        else:
            recipe = catalog.RECIPE_BY_KEY.get(recipe_key)
            if recipe is None:
                raise PhotoError("دستورِ ناشناخته.")
            ops_ = catalog.normalize_operations(plan(next(iter(assets.values())), recipe_key)["operations"])
            per_asset = {pk: ops_ for pk in assets}
    else:
        try:
            ops_ = catalog.normalize_operations(operations)
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
                                                operations=per_asset[pk], message="در صف"))
    return out


def _set(edit: PhotoEdit, **fields) -> None:
    for k, v in fields.items():
        setattr(edit, k, v)
    edit.save(update_fields=list(fields) + ["updated_at"])


def fail(edit: PhotoEdit, message: str) -> None:
    _set(edit, state=PhotoEdit.State.FAILED, error=message[:4000], message="ناموفق")


def start(edit: PhotoEdit) -> PhotoEdit:
    """کارهای کیت ⇐ یک کارِ photo.edit در صف (حتی وقتی هیچ گره‌ای آنلاین نیست)؛ بی کارِ کیت ⇐ همین حالا روی سرورِ سایت."""
    from apps.compute import services as compute

    if edit.state != PhotoEdit.State.QUEUED:
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
                                         "kit": {k: kit.get(k) for k in ("recipe", "notes", "usedAi", "error", "steps")
                                                 if k in kit}}
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

    def logo_path(p):
        if p.get("source") == "asset" and p.get("asset"):
            a = PhotoAsset.objects.filter(store=store, pk=int(p["asset"])).first()
            return abs_path(a.original) if a and abs_path(a.original).is_file() else None
        return _store_logo(store)

    ctx = {"notes": [], "store_name": store.name, "logo_path": logo_path}
    try:
        img = ops.load(src)
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
    if edit.state == PhotoEdit.State.QUEUED and edit.updated_at < now - timedelta(minutes=5):
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

def edit_dict(e: PhotoEdit) -> dict:
    f = e.files or {}
    st = e.stats or {}
    node_ops, server_ops = catalog.split(e.operations or [])
    return {
        "id": e.id, "asset": e.asset_id, "number": e.number, "batch": e.batch, "recipe": e.recipe,
        "recipe_title": catalog.RECIPE_BY_KEY.get(e.recipe, {}).get("title", "دستی") if e.recipe else "دستی",
        "operations": [{"tool": o["tool"], "params": o["params"], "title": catalog.tools().get(o["tool"], {}).get("title", o["tool"]),
                        "where": catalog.tools().get(o["tool"], {}).get("where", "server")} for o in e.operations or []],
        "needs_node": bool(node_ops),
        "state": e.state, "state_label": e.get_state_display(), "active": e.active,
        "progress": round(e.progress, 3), "message": e.message, "error": e.error,
        "urls": {k: media_url(f.get(k)) for k in ("result", "preview", "thumb", "node")},
        "size": [st["after"]["width"], st["after"]["height"]] if st.get("after") else None,
        "after": st.get("after"), "kit": st.get("kit") or {}, "server_notes": st.get("server_notes") or [],
        "node": st.get("node"), "node_seconds": st.get("node_seconds"), "bytes": st.get("bytes"),
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
