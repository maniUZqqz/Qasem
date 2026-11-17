"""لایهٔ سرویسِ استودیوی طراحی: ساخت و ذخیرهٔ سند، ویرایش‌ها (ops)، پیش‌نمایش، خروجی‌ها و نظرها."""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
from collections import OrderedDict
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from . import brand, catalog_doc, catalog_pages as cp, deck_doc, deck_slides as ds, exports, fonts, images, products as prod, scene, typeset, ui_doc, ui_frames as uf
from .models import DesignComment, DesignDoc, DesignExport

logger = logging.getLogger(__name__)

MAX_DOCS = 200
MAX_DATA_BYTES = 2_500_000
KEEP_EXPORTS = 24
CACHE_DAYS = 3


class DesignError(ValueError):
    """خطایی که متنش برای کاربر است."""


class Conflict(DesignError):
    pass


# ───────────────────────────── ابزار

def store_info(store, settings: dict | None = None) -> catalog_doc.StoreInfo:
    return catalog_doc.StoreInfo.from_store(store, settings)


def image_source(store) -> images.ImageSource:
    return images.ImageSource(store)


def _title_default(kind: str, store) -> str:
    return {"catalog": f"کاتالوگ {store.name}", "deck": f"ارائهٔ {store.name}", "ui": f"طراحیِ سایت {store.name}"}.get(kind, store.name)


def _clip(v, n=200) -> str:
    return typeset.clean_text(v, n)


# ───────────────────────────── ساخت

def _catalog_settings(opts: dict) -> dict:
    s = {}
    src = opts.get("settings") if isinstance(opts.get("settings"), dict) else {}
    for k in cp.DEFAULTS:
        if k in src:
            s[k] = src[k]
    return clean_catalog_settings(s)


def clean_catalog_settings(s: dict) -> dict:
    out = {}
    for k, v in s.items():
        if k == "page_size":
            if v in scene.PAGE_SIZES:
                out[k] = v
        elif k == "orientation":
            if v in ("portrait", "landscape"):
                out[k] = v
        elif k == "bleed":
            out[k] = max(0.0, min(10.0, float(v or 0)))
        elif k == "margin":
            out[k] = max(0.0, min(40.0, float(v or 0)))
        elif k in ("heading_font", "body_font"):
            out[k] = v if (v == "" or fonts.known(v)) else ""
        elif k == "look":
            out[k] = v if (v == "" or brand.look_theme(v)) else ""
        elif k == "digits":
            if v in ("fa", "en", "keep"):
                out[k] = v
        elif k in ("show_prices", "show_sku", "show_logo", "page_numbers"):
            out[k] = bool(v)
        elif k in ("title", "subtitle", "tagline", "date_text", "zero_price_label"):
            out[k] = _clip(v, 120)
        elif k == "colors":
            out[k] = [c for c in v if isinstance(c, str)][:5] if isinstance(v, list) else (v if isinstance(v, dict) else None)
        elif k in ("grid_cols", "grid_rows"):
            out[k] = max(1, min(4 if k == "grid_cols" else 5, int(v or 2)))
    return out


def _deck_settings(opts: dict) -> dict:
    src = opts.get("settings") if isinstance(opts.get("settings"), dict) else {}
    out = {}
    for k, v in src.items():
        if k == "template" and v in ds.TEMPLATES:
            out[k] = v
        elif k in ("heading_font", "body_font"):
            out[k] = v if (v == "" or fonts.known(v)) else ""
        elif k == "look":
            out[k] = v if (v == "" or brand.look_theme(v)) else ""
        elif k == "digits" and v in ("fa", "en", "keep"):
            out[k] = v
        elif k in ("show_prices", "slide_numbers", "show_logo"):
            out[k] = bool(v)
        elif k in ("title", "footer_text", "zero_price_label"):
            out[k] = _clip(v, 120)
        elif k == "colors":
            out[k] = [c for c in v if isinstance(c, str)][:5] if isinstance(v, list) else None
    return out


def _ui_settings(opts: dict) -> dict:
    src = opts.get("settings") if isinstance(opts.get("settings"), dict) else {}
    table = uf.style_table()
    out = {}
    for k, v in src.items():
        if k == "style" and (v == "" or v in table):
            out[k] = v
        elif k == "mode" and v in ("light", "dark"):
            out[k] = v
        elif k in ("font_head", "font_body") and fonts.known(v):
            out[k] = v
        elif k == "brand_color" and (v == "" or (isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v))):
            out[k] = v
        elif k == "use_brand":
            out[k] = bool(v)
        elif k == "digits" and v in ("fa", "en", "keep"):
            out[k] = v
        elif k == "radius" and v not in (None, ""):
            out[k] = max(0.0, min(60.0, float(v)))
        elif k == "menu" and isinstance(v, list):
            out[k] = [_clip(x, 30) for x in v[:6] if _clip(x, 30)]
    return out


def create_doc(store, user, kind: str, *, title: str = "", options: dict | None = None, ask=None) -> DesignDoc:
    if kind not in ("catalog", "deck", "ui"):
        raise DesignError("نوعِ سند نامعتبر است.")
    if DesignDoc.objects.filter(store=store).count() >= MAX_DOCS:
        raise DesignError("تعدادِ سندها به سقف رسید؛ چند سندِ قدیمی را پاک کنید.")
    opts = options or {}
    src = image_source(store)
    meta: dict = {}
    source = DesignDoc.Source.RULES
    if kind == "catalog":
        s = _catalog_settings(opts)
        info = store_info(store, s)
        ids = [int(i) for i in (opts.get("products") or []) if str(i).isdigit()] or None
        items = prod.snapshot(store, ids, only_available=not bool(ids))
        if not items:
            raise DesignError("این فروشگاه هنوز محصولی ندارد؛ اول محصول اضافه کنید.")
        data = catalog_doc.new_doc(info, items, s, {k: opts[k] for k in ("featured", "layout", "toc", "with_about", "lookbook", "dividers", "extra_pages", "pre_pages", "about", "back_text", "back_contacts", "cover_image")
                                                    if k in opts}, src)
    elif kind == "deck":
        s = _deck_settings(opts)
        info = store_info(store, s)
        ids = [int(i) for i in (opts.get("products") or []) if str(i).isdigit()] or None
        items = prod.snapshot(store, ids, only_available=not bool(ids))
        facts_in = [f for f in (opts.get("facts") or []) if isinstance(f, dict)]
        facts = [f for f in facts_in if str(f.get("value") or "").strip() and str(f.get("label") or "").strip() and str(f.get("source") or "").strip()]
        # ردیفِ نیمه‌کاره (مثلاً عدد بدونِ منبع) بی‌صدا دور ریخته نمی‌شود: شمارش و برچسبش در سند می‌ماند و بازبینی هشدار می‌دهد.
        dropped = [f for f in facts_in if f not in facts and any(str(f.get(k) or "").strip() for k in ("value", "label", "source"))]
        data, ai = deck_doc.new_deck(info, items, s, {k: opts[k] for k in ("featured", "products_count", "steps", "steps_title", "team", "cta", "subtitle", "kicker", "cover_image", "date") if k in opts},
                                     brief=_clip(opts.get("brief"), 1200), use_ai=bool(opts.get("use_ai")), facts=facts or None, store=store, ask=ask)
        meta["ai"] = ai
        if dropped:
            data.setdefault("meta", {})["facts_dropped"] = len(dropped)
            data["meta"]["facts_dropped_labels"] = [_clip(f.get("label") or f.get("value"), 60) for f in dropped[:8]]
        source = DesignDoc.Source.AI if ai.get("used") else DesignDoc.Source.RULES
    else:
        s = _ui_settings(opts)
        info = store_info(store, s)
        devices = tuple(d for d in (opts.get("devices") or ("desktop", "phone")) if d in ("desktop", "tablet", "phone")) or ("desktop", "phone")
        data = ui_doc.new_doc(info, template=opts.get("template") if opts.get("template") in ("landing", "blank") else "landing", settings=s, devices=devices)
        source = DesignDoc.Source.MANUAL
    if opts.get("sample"):
        source = DesignDoc.Source.SAMPLE
    doc = DesignDoc.objects.create(store=store, created_by=user, kind=kind, title=_clip(title, 160) or _title_default(kind, store), data=data, source=source, meta=meta)
    return doc


# ───────────────────────────── نمایش

def doc_summary(doc: DesignDoc) -> dict:
    d = doc.data or {}
    n = len(d.get("pages") or d.get("slides") or d.get("frames") or [])
    return {"id": doc.pk, "kind": doc.kind, "kind_fa": doc.get_kind_display(), "title": doc.title, "rev": doc.rev, "source": doc.source, "count": n,
            "updated_at": doc.updated_at.isoformat(), "created_at": doc.created_at.isoformat(), "site": site_public((doc.meta or {}).get("site")), "ai": (doc.meta or {}).get("ai")}


def doc_public(doc: DesignDoc) -> dict:
    out = doc_summary(doc)
    out["data"] = doc.data
    out["meta"] = {**(doc.meta or {}), "site": out["site"]} if out.get("site") else doc.meta
    return out


def site_public(site: dict | None) -> dict | None:
    """«ساختِ سایت از این طرح» ⇒ نشانیِ درستِ سایت‌ساز. ویرایشگرِ سایت‌ساز شناسهٔ صفحه می‌خواهد (p/<slug>/builder/page/<id>)؛
    سندهای قدیمی‌تر شناسهٔ صفحه را نداشتند، پس از روی پروژه پیدا می‌شود. اگر پروژه پاک شده باشد ``exists=False``."""
    if not isinstance(site, dict) or not site.get("slug"):
        return site if isinstance(site, dict) else None
    out = {**site, "pages": [dict(p) for p in (site.get("pages") or []) if isinstance(p, dict)]}
    proj = None
    try:
        from apps.projects.models import Page, Project

        proj = Project.objects.filter(pk=site.get("project_id")).only("pk", "slug").first()
        if proj is not None:
            by_slug = {p["slug"]: p["pk"] for p in Page.objects.filter(project=proj).order_by("order", "pk").values("pk", "slug")}
            for pg in out["pages"]:
                pg["page_id"] = pg.get("page_id") or by_slug.get(pg.get("slug", ""))
            out["slug"] = proj.slug
    except Exception:  # noqa: BLE001 — نشانی فقط یک کمک است؛ هرگز نمایشِ سند را نمی‌شکند
        logger.exception("design site link lookup failed")
    out["exists"] = proj is not None
    out["url"] = f"/panel/tools/studio/p/{out['slug']}"
    first = next((p.get("page_id") for p in out["pages"] if p.get("page_id")), None)
    out["builder_url"] = f"/panel/tools/studio/p/{out['slug']}/builder/page/{first}" if first and proj is not None else out["url"]
    return out


# ───────────────────────────── بسته و کَش

_LOCK = threading.Lock()
_BUNDLES: OrderedDict = OrderedDict()


def bundle_for(doc: DesignDoc, *, with_checks: bool = True, mode: str | None = None) -> exports.Bundle:
    key = (doc.pk, doc.kind, doc.rev, doc.updated_at.timestamp() if doc.updated_at else 0, with_checks, mode)
    with _LOCK:
        hit = _BUNDLES.get(key)
        if hit is not None:
            _BUNDLES.move_to_end(key)
            return hit
    settings = doc.data.get("settings") or {}
    info = store_info(doc.store, settings)
    src = image_source(doc.store)
    if doc.kind == "ui" and mode:
        sc = uf.build_scene(doc.data, info, mode_override=mode, with_styleguide=True)
        b = exports.Bundle("ui", doc.data, sc, info, src, doc.title, doc.pk, ui_doc.review(doc.data, sc) if with_checks else [])
    else:
        b = exports.make_bundle(doc.kind, doc.data, info, src, doc.title, doc.pk, with_checks)
    with _LOCK:
        _BUNDLES[key] = b
        while len(_BUNDLES) > 3:
            _BUNDLES.popitem(last=False)
    return b


def scene_public(doc: DesignDoc, *, mode: str | None = None) -> dict:
    b = bundle_for(doc, mode=mode)
    pages = [scene.public_page(p) for p in b.pages]
    out = {"kind": doc.kind, "unit": b.unit, "rev": doc.rev, "pages": pages, "checks": b.checks, "settings": b.sc.get("settings"), "palette": b.sc.get("palette"), "fonts": b.sc.get("fonts")}
    if doc.kind == "ui":
        out["tokens"] = b.sc["tokens"]
        out["links"] = ui_doc.links(doc.data)
        sg = b.sc.get("styleguide")
        out["styleguide"] = {"w": sg["w"], "h": sg["h"]} if sg else None
    if doc.kind == "catalog":
        out["toc"] = b.sc.get("toc")
    return out


def preview_bytes(doc: DesignDoc, page_id: str, width: int = 900, mode: str | None = None) -> bytes:
    width = max(120, min(2400, int(width)))
    d = exports.data_root() / f"s{doc.store_id}" / f"d{doc.pk}" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", page_id)
    f = d / f"r{doc.rev}-{safe}-{width}-{mode or 'x'}.png"
    if f.is_file():
        return f.read_bytes()
    b = bundle_for(doc, with_checks=False, mode=mode)
    if page_id == "styleguide":
        data = exports.preview_png(b, 0, width, styleguide=True)
    else:
        idx = next((i for i, p in enumerate(b.pages) if p["id"] == page_id), None)
        if idx is None:
            raise DesignError("صفحه پیدا نشد.")
        data = exports.preview_png(b, idx, width)
    try:
        f.write_bytes(data)
        _prune_cache(d)
    except OSError:
        pass
    return data


def _prune_cache(d: Path) -> None:
    now = time.time()
    try:
        files = sorted(d.glob("r*.png"), key=lambda p: p.stat().st_mtime)
        for p in files[:-60]:
            p.unlink(missing_ok=True)
        for p in files:
            if now - p.stat().st_mtime > CACHE_DAYS * 86400:
                p.unlink(missing_ok=True)
    except OSError:
        pass


# ───────────────────────────── ذخیره و ویرایش

def _check_size(data: dict) -> None:
    if len(json.dumps(data, ensure_ascii=False)) > MAX_DATA_BYTES:
        raise DesignError("سند بیش از اندازه بزرگ شد.")


def _str_list(v, n=40, each=300) -> list[str]:
    return [_clip(x, each) for x in (v if isinstance(v, list) else [])[:n] if _clip(x, each)]


def _obj_list(v, keys: dict, n=12) -> list[dict]:
    out = []
    for it in (v if isinstance(v, list) else [])[:n]:
        if isinstance(it, dict):
            o = {k: (_clip(it.get(k), lim) if isinstance(lim, int) else it.get(k)) for k, lim in keys.items() if k in it}
            if o:
                out.append(o)
    return out


CATALOG_FIELDS = {
    "title": lambda v: _clip(v, 120), "subtitle": lambda v: _clip(v, 120), "kicker": lambda v: _clip(v, 80), "tagline": lambda v: _clip(v, 200), "date_text": lambda v: _clip(v, 60),
    "image": lambda v: _clip(v, 80), "text": lambda v: _clip(v, 1500), "note": lambda v: _clip(v, 300), "notes": lambda v: _clip(v, 1000), "cols": lambda v: max(1, min(4, int(v or 2))),
    "rows": lambda v: max(1, min(5, int(v or 3))), "products": lambda v: [int(x) for x in (v if isinstance(v, list) else [])[:40] if str(x).isdigit()], "product": lambda v: int(v) if str(v).isdigit() else None,
    "paragraphs": lambda v: _str_list(v, 8, 1200), "points": lambda v: _str_list(v, 8, 80), "images": lambda v: _str_list(v, 5, 80), "captions": lambda v: _str_list(v, 5, 80),
    "steps": lambda v: _obj_list(v, {"title": 60, "text": 240}, 7), "contacts": lambda v: _obj_list(v, {"label": 30, "value": 120, "kind": 20}, 8),
}
CATALOG_TYPE_FIELDS = {
    "cover": {"title", "subtitle", "tagline", "date_text", "image", "notes"}, "toc": {"title", "notes"}, "text": {"title", "kicker", "paragraphs", "image", "notes"},
    "grid": {"title", "kicker", "cols", "rows", "products", "notes"}, "hero": {"product", "title", "text", "points", "notes"}, "price_list": {"title", "kicker", "products", "note", "notes"},
    "lookbook": {"title", "kicker", "images", "captions", "notes"}, "steps": {"title", "kicker", "steps", "notes"}, "divider": {"title", "subtitle", "notes"},
    "back": {"title", "text", "contacts", "notes"},
}
DECK_FIELDS = {
    "title": lambda v: _clip(v, 120), "subtitle": lambda v: _clip(v, 200), "kicker": lambda v: _clip(v, 80), "date": lambda v: _clip(v, 60), "image": lambda v: _clip(v, 80),
    "text": lambda v: _clip(v, 600), "notes": lambda v: _clip(v, 1500), "caption": lambda v: _clip(v, 160), "button": lambda v: _clip(v, 60), "note": lambda v: _clip(v, 200),
    "link": lambda v: v if isinstance(v, str) and re.match(r"^https?://", v) else "", "product": lambda v: int(v) if str(v).isdigit() else None,
    "items": lambda v: v, "bullets": lambda v: _str_list(v, 8, 240), "points": lambda v: _str_list(v, 6, 80), "steps": lambda v: _obj_list(v, {"title": 50, "text": 200}, 6),
    "members": lambda v: _obj_list(v, {"name": 60, "role": 80, "photo": 80}, 6),
}
DECK_TYPE_FIELDS = {
    "title": {"title", "subtitle", "kicker", "date", "image", "notes"}, "agenda": {"title", "items", "notes"}, "text": {"title", "bullets", "text", "image", "notes"},
    "product": {"product", "title", "text", "points", "notes"}, "comparison": {"title", "items", "notes"}, "stats": {"title", "items", "notes"}, "timeline": {"title", "steps", "notes"},
    "team": {"title", "members", "notes"}, "cta": {"title", "text", "button", "link", "note", "notes"}, "section": {"title", "subtitle", "notes"}, "image": {"image", "caption", "notes"},
}


def _clean_deck_items(typ: str, v) -> list:
    if typ == "agenda":
        return _str_list(v, 8, 60)
    if typ == "stats":
        return _obj_list(v, {"value": 30, "label": 80, "source": 120}, 4)
    if typ == "comparison":
        out = []
        for it in (v if isinstance(v, list) else [])[:3]:
            if isinstance(it, dict):
                o = {"points": _str_list(it.get("points"), 6, 100)}
                if str(it.get("product", "")).isdigit():
                    o["product"] = int(it["product"])
                for k, n in (("name", 80), ("price", 40)):
                    if it.get(k):
                        o[k] = _clip(it[k], n)
                if it.get("highlight"):
                    o["highlight"] = True
                out.append(o)
        return out
    return []


def clean_spec(kind: str, typ: str, spec: dict) -> dict:
    fields = CATALOG_FIELDS if kind == "catalog" else DECK_FIELDS
    allowed = (CATALOG_TYPE_FIELDS if kind == "catalog" else DECK_TYPE_FIELDS).get(typ, set())
    out = {}
    for k, v in (spec or {}).items():
        if k in allowed and k in fields:
            try:
                out[k] = fields[k](v) if not (kind == "deck" and k == "items") else _clean_deck_items(typ, v)
            except (TypeError, ValueError):
                continue
    return out


def _next_id(lst: list, prefix: str) -> str:
    used = {x.get("id") for x in lst}
    n = len(lst) + 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def _apply_pages_ops(doc: DesignDoc, ops: list[dict]) -> dict:
    data = doc.data
    kind = doc.kind
    key, prefix = ("pages", "p") if kind == "catalog" else ("slides", "s")
    types = cp.PAGE_TYPES if kind == "catalog" else ds.SLIDE_TYPES
    lst = data.setdefault(key, [])
    max_n = catalog_doc.MAX_PAGES if kind == "catalog" else deck_doc.MAX_SLIDES

    def find(pid):
        sp = next((x for x in lst if x.get("id") == pid), None)
        if sp is None:
            raise DesignError("صفحه پیدا نشد.")
        return sp

    for op in (ops or [])[:60]:
        k = op.get("op")
        if k == "set_settings":
            patch = op.get("set") or {}
            cleaned = clean_catalog_settings(patch) if kind == "catalog" else _deck_settings({"settings": patch})
            data["settings"].update(cleaned)
        elif k in ("add_page", "add_slide"):
            typ = op.get("type")
            if typ not in types:
                raise DesignError("نوعِ صفحه نامعتبر است.")
            if len(lst) >= max_n:
                raise DesignError("تعدادِ صفحه‌ها به سقف رسید.")
            sp = {"id": _next_id(lst, prefix), "type": typ, **clean_spec(kind, typ, op.get("spec") or {})}
            idx = op.get("index")
            if kind == "catalog" and typ == "back":
                idx = len(lst)
            if isinstance(idx, int) and 0 <= idx <= len(lst):
                lst.insert(idx, sp)
            else:
                backs = [i for i, x in enumerate(lst) if x.get("type") == ("back" if kind == "catalog" else "cta")]
                if backs and kind == "catalog":
                    lst.insert(backs[-1], sp)
                else:
                    lst.append(sp)
        elif k in ("update_page", "update_slide"):
            sp = find(op.get("page") or op.get("slide"))
            sp.update(clean_spec(kind, sp["type"], op.get("set") or {}))
            for f in op.get("unset") or []:
                sp.pop(f, None)
        elif k in ("delete_page", "delete_slide"):
            if len(lst) <= 1:
                raise DesignError("دست‌کم یک صفحه باید بماند.")
            lst[:] = [x for x in lst if x.get("id") != (op.get("page") or op.get("slide"))]
        elif k in ("move_page", "move_slide"):
            sp = find(op.get("page") or op.get("slide"))
            lst.remove(sp)
            lst.insert(max(0, min(len(lst), int(op.get("to", 0)))), sp)
        elif k in ("duplicate_page", "duplicate_slide"):
            sp = find(op.get("page") or op.get("slide"))
            if len(lst) >= max_n:
                raise DesignError("تعدادِ صفحه‌ها به سقف رسید.")
            cp_ = json.loads(json.dumps(sp, ensure_ascii=False))
            cp_["id"] = _next_id(lst, prefix)
            lst.insert(lst.index(sp) + 1, cp_)
        elif k == "override":
            sp = find(op.get("page") or op.get("slide"))
            patch = {kk: v for kk, v in (op.get("set") or {}).items() if kk in scene.OVERRIDE_KEYS}
            cleaned = scene.clean_element({"id": "tmp", "type": "text" if "text" in patch else "rect", **patch}) or {}
            ov = sp.setdefault("overrides", {})
            cur = ov.setdefault(str(op.get("el")), {})
            for kk, v in patch.items():
                cur[kk] = cleaned.get(kk, v) if kk in ("x", "y", "w", "h", "size", "color", "weight", "text", "font", "align", "opacity", "rot", "lh") else v
            if len(ov) > 400:
                raise DesignError("ویرایش‌های این صفحه بیش از اندازه شد.")
        elif k == "clear_override":
            sp = find(op.get("page") or op.get("slide"))
            (sp.get("overrides") or {}).pop(str(op.get("el")), None)
        elif k == "add_element":
            sp = find(op.get("page") or op.get("slide"))
            extra = sp.setdefault("extra", [])
            if len(extra) >= 100:
                raise DesignError("عنصرهای افزوده بیش از اندازه شد.")
            el = dict(op.get("element") or {})
            el["id"] = _next_id(extra, "x")
            c = scene.clean_element(el)
            if c is None:
                raise DesignError("عنصرِ نامعتبر.")
            extra.append(c)
        elif k == "remove_element":
            sp = find(op.get("page") or op.get("slide"))
            eid = str(op.get("el"))
            sp["extra"] = [e for e in sp.get("extra", []) if e.get("id") != eid]
            if eid not in {e.get("id") for e in sp.get("extra", [])}:
                sp.setdefault("overrides", {}).setdefault(eid, {})["hidden"] = True
        elif k == "sync_products" and kind in ("catalog", "deck"):
            keep = [p["id"] for p in data.get("products", [])]
            if op.get("add_all"):
                snap = prod.snapshot(doc.store)
            else:
                snap = prod.snapshot(doc.store, keep or None, only_available=False)
            data["products"] = snap
            valid = {p["id"] for p in snap}
            for sp in lst:
                if isinstance(sp.get("products"), list):
                    sp["products"] = [i for i in sp["products"] if i in valid]
                if sp.get("product") and sp["product"] not in valid:
                    sp["product"] = None
        elif k == "pad4" and kind == "catalog":
            while len(lst) % 4 != 0 and len(lst) < max_n:
                idx = max(0, len(lst) - 1) if lst and lst[-1].get("type") == "back" else len(lst)
                lst.insert(idx, {"id": _next_id(lst, prefix), "type": "text", "title": "یادداشت", "paragraphs": []})
        elif k == "set_facts" and kind == "deck":
            data["facts"] = _obj_list(op.get("facts"), {"value": 30, "label": 80, "source": 120}, 12)
        else:
            raise DesignError(f"عملِ «{k}» را نمی‌شناسم.")
    return data


def apply_ops(doc: DesignDoc, ops: list[dict], rev: int | None = None) -> DesignDoc:
    """ops را روی سند می‌نشاند و ذخیره می‌کند. rev ناهمخوان ⇒ Conflict (ذخیرهٔ هم‌زمان از دو تب)."""
    with transaction.atomic():
        d = DesignDoc.objects.select_for_update().get(pk=doc.pk)
        if rev is not None and int(rev) != d.rev:
            raise Conflict("این سند در جای دیگری عوض شده؛ صفحه را تازه کنید.")
        try:
            if d.kind == "ui":
                ui_doc.apply_ops(d.data, ops)
            else:
                _apply_pages_ops(d, ops)
        except (ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, DesignError):
                raise
            raise DesignError(str(exc) if isinstance(exc, ValueError) else "ویرایشِ نامعتبر.") from exc
        _check_size(d.data)
        d.rev += 1
        d.save(update_fields=["data", "rev", "updated_at"])
    return d


def rename(doc: DesignDoc, title: str) -> DesignDoc:
    doc.title = _clip(title, 160) or doc.title
    doc.save(update_fields=["title", "updated_at"])
    return doc


# ───────────────────────────── پاک‌کردنِ سند

def doc_dir(store_id: int, doc_id: int) -> Path:
    return exports.data_root() / f"s{int(store_id)}" / f"d{int(doc_id)}"


def remove_doc_files(store_id: int, doc_id: int) -> bool:
    """پوشهٔ خروجی‌ها و کَشِ پیش‌نمایشِ یک سند را پاک می‌کند (چند مگابایت برای هر سند؛ سرور جای کمی دارد). فقط داخلِ ``design/s<store>/d<doc>``."""
    d = doc_dir(store_id, doc_id)
    root = exports.data_root().resolve()
    try:
        r = d.resolve()
        if r.parent.parent != root or not d.exists():
            return False
        shutil.rmtree(r, ignore_errors=True)
        s = r.parent
        if s.is_dir() and not any(s.iterdir()):
            s.rmdir()                                            # پوشهٔ فروشگاهِ خالی هم نماند
        return True
    except OSError:
        logger.exception("design doc files cleanup failed (doc %s)", doc_id)
        return False


def delete_doc(doc: DesignDoc) -> None:
    """سند + فایل‌های خروجی‌اش. (پاک‌شدنِ زنجیره‌ای، مثلاً با پاک‌شدنِ فروشگاه، با سیگنالِ post_delete پوشه را پاک می‌کند.)"""
    store_id, doc_id = doc.store_id, doc.pk
    doc.delete()
    remove_doc_files(store_id, doc_id)


# ───────────────────────────── خروجی‌ها

def export_dict(e: DesignExport) -> dict:
    label = "ویدیوی MP4 (ساخته‌شده روی سرورِ پردازش)" if e.kind == "mp4" else exports.KINDS.get(e.kind, (e.kind,))[0]
    return {"id": e.pk, "kind": e.kind, "label": label, "state": e.state, "progress": round(e.progress, 3), "message": e.message, "error": e.error, "filename": e.filename,
            "size_bytes": e.size_bytes, "info": e.info, "doc_rev": e.doc_rev, "created_at": e.created_at.isoformat(), "params": e.params,
            "download": f"/design/exports/{e.pk}/download/" if e.state == DesignExport.State.READY else ""}


def start_export(doc: DesignDoc, kind: str, params: dict | None, user) -> DesignExport:
    if kind not in exports.KINDS:
        raise DesignError("نوعِ خروجی ناشناخته است.")
    if doc.kind not in exports.KINDS[kind][3]:
        raise DesignError(f"«{exports.KINDS[kind][0]}» برای این نوع سند نیست.")
    if DesignExport.objects.filter(doc__store=doc.store, state__in=DesignExport.ACTIVE).count() >= 4:
        raise DesignError("چند خروجی در حالِ ساخت است؛ چند لحظه صبر کنید.")
    clean_params = {}
    for k, v in (params or {}).items():
        if k in ("dpi", "scale", "quality") and isinstance(v, (int, float)):
            clean_params[k] = v
        elif k in ("bleed", "marks") and isinstance(v, bool):
            clean_params[k] = v
        elif k == "text_mode" and v in ("outline", "text"):
            clean_params[k] = v
    e = DesignExport.objects.create(doc=doc, created_by=user, kind=kind, params=clean_params, doc_rev=doc.rev, message="در صف")
    _prune_exports(doc)
    from . import tasks

    tasks.dispatch_export(e.pk)
    e.refresh_from_db()
    return e


def _prune_exports(doc: DesignDoc) -> None:
    old = list(doc.exports.order_by("-created_at")[KEEP_EXPORTS:])
    for e in old:
        if e.file:
            try:
                (exports.data_root() / e.file).unlink(missing_ok=True)
            except OSError:
                pass
        e.delete()


def run_export(export_id: int) -> None:
    e = DesignExport.objects.select_related("doc", "doc__store").filter(pk=export_id).first()
    if e is None or e.state not in (DesignExport.State.QUEUED, DesignExport.State.RUNNING):
        return
    e.state, e.message, e.progress = DesignExport.State.RUNNING, "آماده‌سازی", 0.02
    e.save(update_fields=["state", "message", "progress", "updated_at"])

    def progress(frac, msg):
        DesignExport.objects.filter(pk=e.pk).update(progress=max(0.02, min(0.98, frac)), message=msg[:300])

    try:
        doc = e.doc
        b = bundle_for(doc)
        try:
            data, filename, info = exports.build(e.kind, b, e.params, progress)
        finally:
            b.src.clear()                                          # عکس‌های درشتِ این خروجی را از حافظه برگردان
        rel = f"s{doc.store_id}/d{doc.pk}/exports/{e.pk}-{filename}"
        path = exports.data_root() / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        e.file, e.filename, e.size_bytes = rel, filename, len(data)
        e.info = json.loads(json.dumps(info, ensure_ascii=False, default=str))
        e.state, e.progress, e.message, e.error = DesignExport.State.READY, 1.0, "آماده", ""
    except (exports.ExportError, DesignError) as exc:
        e.state, e.error, e.message = DesignExport.State.FAILED, str(exc), "ناموفق"
    except Exception as exc:  # noqa: BLE001
        logger.exception("design export %s failed", export_id)
        e.state, e.error, e.message = DesignExport.State.FAILED, f"{exc.__class__.__name__}: {exc}"[:600], "ناموفق"
    e.save()


def export_file(e: DesignExport) -> Path | None:
    if e.state != DesignExport.State.READY or not e.file:
        return None
    p = (exports.data_root() / e.file).resolve()
    root = exports.data_root().resolve()
    return p if root in p.parents and p.is_file() else None


# ───────────────────────────── نظرها

def comment_dict(c: DesignComment) -> dict:
    return {"id": c.pk, "frame": c.frame_id, "node": c.node_id, "x": c.x, "y": c.y, "text": c.text, "resolved": c.resolved, "author": c.author_name or "", "parent": c.parent_id,
            "created_at": c.created_at.isoformat()}


def add_comment(doc: DesignDoc, user, body: dict) -> DesignComment:
    if doc.kind != "ui":
        raise DesignError("نظر فقط روی طراحیِ UI/UX است.")
    frame = str(body.get("frame") or "")
    if not any(f.get("id") == frame for f in doc.data.get("frames", [])):
        raise DesignError("فریم پیدا نشد.")
    text = _clip(body.get("text"), 1200)
    if not text:
        raise DesignError("متنِ نظر خالی است.")
    if doc.comments.count() >= 500:
        raise DesignError("تعدادِ نظرها به سقف رسید.")
    parent = None
    if body.get("parent"):
        parent = doc.comments.filter(pk=body["parent"]).first()
    name = getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "") or ""
    return DesignComment.objects.create(doc=doc, author=user, author_name=name[:80], frame_id=frame, node_id=str(body.get("node") or "")[:40],
                                        x=max(0.0, min(1.0, float(body.get("x") or 0))), y=max(0.0, min(1.0, float(body.get("y") or 0))), text=text, parent=parent)


# ───────────────────────────── نمونهٔ آماده

def create_sample(store, user, send_to_site: bool = False) -> dict:
    """«نمونهٔ آماده»: برای چغر سه پیش‌نویسِ واقعی؛ برای هر فروشگاهِ دیگر کاتالوگ، ارائه و طرحِ UI از دادهٔ خودش."""
    from . import chagher

    if chagher.is_chagher(store):
        return chagher.ensure_drafts(store, user, send_to_site=send_to_site)
    out = {"created": {}}
    for kind in ("catalog", "deck", "ui"):
        existing = DesignDoc.objects.filter(store=store, source=DesignDoc.Source.SAMPLE, kind=kind).first()
        if existing:
            out[kind] = existing.pk
            out["created"][kind] = False
            continue
        try:
            doc = create_doc(store, user, kind, options={"sample": True, "use_ai": False})
        except DesignError as exc:
            out.setdefault("errors", {})[kind] = str(exc)
            continue
        out[kind] = doc.pk
        out["created"][kind] = True
    return out
