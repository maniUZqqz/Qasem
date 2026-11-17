# -*- coding: utf-8 -*-
"""«باز کردن در طراحیِ UI»: درختِ اجزای یک تبدیل ⇒ یک **سندِ طراحیِ UI/UX** در «استودیوی طراحی» (فریمِ دسکتاپ + گوشی) که همان‌جا ویرایش، با نمونهٔ کلیک‌پذیر دیده و
در پایان با «ساختِ سایت از این طرح» به پیش‌نویسِ سایت‌ساز تبدیل می‌شود.

* همان بلوک‌های سایت‌ساز (سربرگ، بخش‌ها، ستون‌ها، تیتر، متن، دکمه، فرم…) که ``mapping.map_tree`` می‌سازد در فریم می‌نشینند؛ پس طرح و پیش‌نویسِ سایت‌ساز یک ساختار دارند.
* **تصویرها جای‌تصویرند**: استودیوی طراحی فقط عکس‌های خودِ فروشگاه (محصول، کتابخانهٔ ادیتورِ عکس، لوگو) را می‌شناسد و «هرگز تصویرِ ساختگی نمی‌گذارد»؛
  تکه‌های بریده‌شده از اسکرین‌شات فقط در پیش‌نویسِ سایت‌ساز (رسانهٔ پروژه) می‌آیند. متن‌ها و رنگ‌ها واقعی‌اند.
* هیچ‌چیز منتشر نمی‌شود؛ سند در تاریخچهٔ طراحیِ فروشگاه می‌ماند و با حذفِ تبدیل پاک نمی‌شود (دستِ خودِ کاربر است).
* فقط وقتی کار می‌کند که ``apps.design_studio`` نصب باشد و ``settings.IMG2CODE_UI_DESIGN`` خاموش نشده باشد.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.utils import timezone

from . import mapping
from .models import Conversion
from .services import Img2CodeError

log = logging.getLogger(__name__)

MAX_NODES = 300          # ui_doc.MAX_NODES (سقفِ گره‌های یک سند؛ همهٔ فریم‌ها با هم)


def enabled() -> bool:
    return bool(getattr(settings, "IMG2CODE_UI_DESIGN", False)) and "apps.design_studio" in settings.INSTALLED_APPS


def path_for(store_id: int, doc_id: int) -> str:
    return "/stores/%d/design/ui/%d" % (store_id, doc_id)


def _count(blocks) -> int:
    n = 0
    for b in blocks or []:
        n += 1 + _count(b.get("children"))
    return n


def _blank_crops(blocks) -> None:
    """مرجعِ «crop:…» (تکه‌ای از اسکرین‌شات) در استودیو معنا ندارد ⇒ جای‌تصویر."""
    for b in blocks or []:
        props = b.get("props") or {}
        for k, v in list(props.items()):
            if isinstance(v, str) and v.startswith("crop:"):
                props[k] = ""
        _blank_crops(b.get("children"))


def _is_dark(hex_color: str) -> bool:
    try:
        return mapping._lum(mapping._hex_to_rgb(hex_color)) < 0.3
    except Exception:  # noqa: BLE001
        return False


def existing_doc(conv: Conversion):
    if not conv.ui_doc_id:
        return None
    from apps.design_studio.models import DesignDoc
    return DesignDoc.objects.filter(pk=conv.ui_doc_id, store=conv.store, kind="ui").first()


def create_doc(conv: Conversion, user, force_new: bool = False) -> dict:
    """⇒ {doc_id, url, created, warnings, stats}. اگر برای همین تبدیل قبلاً سندی ساخته شده و هنوز هست، همان را برمی‌گرداند (``force_new``: سندِ تازه)."""
    if not enabled():
        raise Img2CodeError("بخشِ «طراحی UI/UX» در این سایت روشن نیست.", "no_design_studio", 404)
    if conv.state != Conversion.State.READY:
        raise Img2CodeError("هنوز تبدیل تمام نشده است.", "not_ready", 409)
    from apps.design_studio import services as ds, ui_doc
    from apps.design_studio.models import DesignDoc

    if not force_new:
        doc = existing_doc(conv)
        if doc is not None:
            return {"doc_id": doc.pk, "url": path_for(conv.store_id, doc.pk), "created": False, "warnings": [], "stats": {}}
    if DesignDoc.objects.filter(store=conv.store).count() >= ds.MAX_DOCS:
        raise Img2CodeError("تعدادِ سندهای طراحیِ این فروشگاه به سقف رسید؛ چند سندِ قدیمی را پاک کنید.", "too_many_docs", 409)
    tree_path = conv.out_dir / "tree.json"
    if not tree_path.is_file():
        raise Img2CodeError("درختِ اجزای این تبدیل پیدا نشد.", "no_tree", 409)
    from .sitedraft import _load_image
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    _im, arr = _load_image(conv)
    result = mapping.map_tree(tree, arr, chrome=True)
    warnings = [w for w in result["warnings"] if "OCR" not in w or conv.source_kind != "url"]
    for key in ("header", "page", "footer"):
        if result.get(key):
            _blank_crops(result[key]["blocks"])
    try:
        docs = mapping.clean_docs(result)
    except Exception as exc:  # noqa: BLE001 — DocError از سایت‌ساز
        raise Img2CodeError("ساختارِ ساخته‌شده را سایت‌ساز نپذیرفت: %s" % exc, "bad_doc", 422) from None
    blocks: list = []
    for key in ("header", "page", "footer"):
        blocks.extend((docs.get(key) or {}).get("blocks") or [])
    n = _count(blocks)
    devices = ("desktop", "phone")
    if 2 * n > MAX_NODES:
        devices = ("desktop",)                    # سقفِ گره‌های سند (همهٔ فریم‌ها با هم)
    while blocks and _count(blocks) > MAX_NODES and len(blocks) > 1:
        blocks.pop()
        if not any("آخرِ صفحه" in w for w in warnings):
            warnings.append("صفحه بیش از سقفِ گره‌های سندِ طراحی بلوک داشت؛ بخش‌های آخرِ آن در طرح نیامد.")
    colors = (result.get("theme") or {}).get("colors") or {}
    s = {"mode": "dark" if _is_dark(result.get("page_bg") or "#ffffff") else "light", "brand_color": colors.get("primary") or "", "use_brand": True,
         "font_head": "vazirmatn", "font_body": "vazirmatn", "digits": "fa", "menu": [m["label"] for m in (result.get("menu") or [])][:6]}
    info = ds.store_info(conv.store, s)
    title = (conv.title or "طرح از تصویر #%d" % conv.pk)[:160]
    data = ui_doc.new_doc(info, template="blank", settings=s, devices=devices, blocks=blocks, name=(conv.title or "صفحهٔ اصلی")[:60])
    doc = DesignDoc.objects.create(store=conv.store, created_by=user, kind="ui", title=title, data=data, source=DesignDoc.Source.MANUAL,
                                   meta={"img2code": {"conversion": conv.pk, "note": "تصویرها جای‌تصویرند؛ تکه‌های واقعی در پیش‌نویسِ سایت‌ساز می‌آیند."}})
    conv.ui_doc_id = doc.pk
    conv.ui_doc_at = timezone.now()
    conv.save(update_fields=["ui_doc_id", "ui_doc_at", "updated_at"])
    warnings.append("در طرحِ UI تصویرها جای‌تصویرند (استودیو فقط عکس‌های خودِ فروشگاه را می‌شناسد)؛ تکه‌های واقعی در «ساختِ صفحه در سایت‌ساز» می‌آیند.")
    return {"doc_id": doc.pk, "url": path_for(conv.store_id, doc.pk), "created": True, "warnings": warnings,
            "stats": {"blocks": _count(blocks), "frames": len(data["frames"]), **{k: v for k, v in result["stats"].items() if k in ("images", "columns", "heading", "text", "button")}}}
