"""منطقِ شخصیتِ دیداری: ساخت و ویرایش، قفل و نسخه، رندرِ کَش‌دار (پست/استوری، استیکر، برگه، SVG، PDF)، بسته‌یِ خروجی، بررسیِ ثبات.

موتورِ برداری و برگه‌ها در ``engine/`` خالص‌اند؛ این‌جا فقط همه‌چیزِ وابسته به Django و فایل است. رنگ و لوگوی برند همان «سبکِ برند» ِ تامنیل‌ساز است
(``apps.mascot.services``). هیچ‌جا هوش مصنوعی یا سرورِ پردازش لازم نیست؛ شخصیتِ کدکشیده هرگز منتظر نمی‌ماند.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import threading
import types
import zipfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from PIL import Image

from apps.mascot import services as MS
from apps.mascot.engine import brand as B
from apps.mascot.engine import compose, copy_guard, poses
from apps.photoedit import services as photo
from apps.photoedit.models import PhotoAsset

from . import persona as P
from .engine import doc as D
from .engine import render as R
from .engine import sheet as SH
from .models import BrandCharacter, BrandPersona, CharacterRender, CharacterVersion, UsageEvent

logger = logging.getLogger(__name__)

MAX_CHARACTERS = 8
MAX_RENDERS = 300
MAX_VERSIONS = 40
PREVIEW_SCALE = 0.42
_slots = threading.BoundedSemaphore(2)               # روی ۲ هستهٔ سرور هم‌زمان دو رندر


class CharError(Exception):
    """متنش برای کاربر است."""


ClaimsError = MS.ClaimsError


# ───────────────────────────── برند

brand_colours = MS.brand_colours
store_logo = MS.store_logo


def effective_brand(c: BrandCharacter) -> list[str]:
    return B.clean_colours(c.brand_colours)[:4] or brand_colours(c.store)


def persona_data(store) -> dict | None:
    row = BrandPersona.objects.filter(store=store).first()
    return P.normalize(row.data) if row is not None and row.data else None


# ───────────────────────────── سند و رکورد

def new_doc(role: str, colours: list[str], name: str, *, style: str = "flat", logo: bool = False, base: dict | None = None) -> dict:
    """سندِ تازه از نقش و رنگ‌های برند (ظاهرِ آدمک‌چوبیِ ماسکوت + لباس و رنگ‌های برداری)."""
    role = role if role in B.ROLES else B.DEFAULT_ROLE
    spec = B.spec_from_brand(role, colours, name, logo=logo)
    pal = B.brand_palette(colours)
    d = D.from_mascot_spec(spec, role=role, name=name)
    d.update(D.role_look(role))
    d.update({"style": style if style in D.STYLES else "flat", "top": pal["primary"], "top2": "#ffffff", "bottom": pal["limb"], "outline": pal["ink"], "shoes": "#f4f1ea",
              "skin": "#f1c9a5"})
    d.update({k: v for k, v in (base or {}).items() if k in D.DEFAULTS})
    return D.normalize(d, name=name)


def _clean_name(name, default: str) -> str:
    return " ".join(str(name or "").split())[:80] or default


def _snapshot(c: BrandCharacter, user, note: str = "") -> None:
    CharacterVersion.objects.update_or_create(character=c, version=c.version, defaults={"doc": c.doc, "note": note[:160], "created_by": user})
    old = list(CharacterVersion.objects.filter(character=c).order_by("-version").values_list("pk", flat=True)[MAX_VERSIONS:])
    if old:
        CharacterVersion.objects.filter(pk__in=old).delete()


@transaction.atomic
def create(store, user, *, role: str = B.DEFAULT_ROLE, name: str = "", style: str = "flat", use_logo: bool = True, brand: list | None = None,
           doc: dict | None = None, concept: dict | None = None) -> BrandCharacter:
    if BrandCharacter.objects.filter(store=store).count() >= MAX_CHARACTERS:
        raise CharError(f"هر فروشگاه حداکثر {MAX_CHARACTERS} شخصیتِ دیداری دارد؛ یکی را پاک کنید.")
    role = role if role in B.ROLES else B.DEFAULT_ROLE
    colours = B.clean_colours(brand) or brand_colours(store)
    name = _clean_name(name, f"{B.ROLES[role]['fa']} {store.name}"[:80])
    has_logo = bool(use_logo and store_logo(store) is not None)
    d = D.normalize(doc, name=name) if doc else new_doc(role, colours, name, style=style, logo=has_logo)
    if d["logo"] == "chest" and not has_logo:
        d["logo"] = "none"
    first = not BrandCharacter.objects.filter(store=store).exists()
    return BrandCharacter.objects.create(store=store, created_by=user, name=name, role=role, doc=d, brand_colours=B.clean_colours(brand)[:4], is_primary=first, concept=concept or {})


def from_mascot(store, user, mascot) -> BrandCharacter:
    """یک ماسکوتِ موجود را به شخصیتِ دیداری تبدیل می‌کند (ماسکوت دست نمی‌خورد)."""
    d = D.from_mascot_spec(mascot.spec, role=mascot.role, name=mascot.name)
    c = create(store, user, role=mascot.role, name=mascot.name, doc=d, brand=mascot.brand_colours, concept={"title": "از ماسکوتِ موجود", "source": "mascot", "mascot": mascot.pk})
    c.mascot = mascot
    c.save(update_fields=["mascot", "updated_at"])
    return c


def update(c: BrandCharacter, data: dict) -> BrandCharacter:
    """نام، رنگ‌های برند و (اگر قفل نیست) سند. ``doc`` ناقص ادغام می‌شود؛ ``reset_look`` ظاهر را از نو از روی نقش می‌سازد."""
    if c.locked:
        raise CharError("ظاهرِ این شخصیت تأیید و قفل شده است؛ برای تغییر، اول «بازکردنِ قفل» را بزنید.")
    fields = ["updated_at"]
    if "name" in data:
        c.name = _clean_name(data["name"], c.name)
        fields.append("name")
    if "brand_colours" in data:
        c.brand_colours = B.clean_colours(data["brand_colours"])[:4]
        fields.append("brand_colours")
    doc = dict(c.doc or {})
    if data.get("role") in B.ROLES and data["role"] != c.role:
        c.role = data["role"]
        fields.append("role")
        data = {**data, "reset_look": True}
    if data.get("reset_look") is True:
        doc = new_doc(c.role, effective_brand(c), c.name, style=doc.get("style", "flat"), logo=doc.get("logo") == "chest")
    if isinstance(data.get("doc"), dict):
        doc = {**doc, **data["doc"]}
    doc["name"] = c.name
    new = D.normalize(doc)
    if new["logo"] == "chest" and store_logo(c.store) is None:
        new["logo"] = "none"
    if new != c.doc:
        c.doc = new
        c.last_check = {}
        fields += ["doc", "last_check"]
    c.save(update_fields=list(dict.fromkeys(fields)))
    return c


def lock(c: BrandCharacter, user=None, note: str = "") -> BrandCharacter:
    if not c.locked:
        c.locked, c.locked_at = True, timezone.now()
        c.version += 1
        c.save(update_fields=["locked", "locked_at", "version", "updated_at"])
        _snapshot(c, user, note or "تأییدِ ظاهر")
    return c


def unlock(c: BrandCharacter) -> BrandCharacter:
    if c.locked:
        c.locked = False
        c.save(update_fields=["locked", "updated_at"])
    return c


def versions(c: BrandCharacter) -> list[dict]:
    return [{"version": v.version, "note": v.note, "created_at": v.created_at, "style": (v.doc or {}).get("style", "")} for v in c.versions.all()]


def restore(c: BrandCharacter, version: int) -> BrandCharacter:
    if c.locked:
        raise CharError("اول قفل را باز کنید.")
    v = c.versions.filter(version=version).first()
    if v is None:
        raise CharError("این نسخه پیدا نشد.")
    c.doc = D.normalize(v.doc, name=c.name)
    c.last_check = {}
    c.save(update_fields=["doc", "last_check", "updated_at"])
    return c


@transaction.atomic
def set_primary(c: BrandCharacter) -> BrandCharacter:
    BrandCharacter.objects.filter(store=c.store, is_primary=True).exclude(pk=c.pk).update(is_primary=False)
    c.is_primary = True
    c.save(update_fields=["is_primary", "updated_at"])
    return c


def primary(store) -> BrandCharacter | None:
    return BrandCharacter.objects.filter(store=store).order_by("-is_primary", "-updated_at").first()


@transaction.atomic
def delete(c: BrandCharacter) -> None:
    store, was_primary = c.store, c.is_primary
    c.delete()
    if was_primary:
        nxt = BrandCharacter.objects.filter(store=store).order_by("-updated_at").first()
        if nxt:
            nxt.is_primary = True
            nxt.save(update_fields=["is_primary"])


def publish_mascot(c: BrandCharacter) -> int:
    """همین شخصیت را (آدمک‌چوبی) به‌عنوانِ «ماسکوتِ برند» هم ثبت می‌کند تا صفحهٔ قدیمیِ ماسکوت و تامنیل‌ساز آن را ببینند. ⇒ شناسهٔ ماسکوت."""
    from apps.mascot.models import Mascot

    spec = D.to_mascot_spec(c.doc)
    if c.mascot_id and Mascot.objects.filter(pk=c.mascot_id, store=c.store).exists():
        m = Mascot.objects.get(pk=c.mascot_id)
        if not m.locked:
            m.spec, m.name, m.role = spec, c.name, c.role
            m.save(update_fields=["spec", "name", "role", "updated_at"])
        return m.pk
    m = Mascot.objects.create(store=c.store, created_by=c.created_by, name=c.name, role=c.role, spec=spec, brand_colours=c.brand_colours or [])
    c.mascot = m
    c.save(update_fields=["mascot", "updated_at"])
    return m.pk


# ───────────────────────────── گزینه‌های ساخت

def _opts_owner(c: BrandCharacter):
    return types.SimpleNamespace(role=c.role)


def clean_options(d: dict, c: BrandCharacter | None = None) -> dict:
    try:
        return MS.clean_options(d, _opts_owner(c) if c else None)
    except MS.MascotError as exc:
        raise CharError(str(exc)) from exc


def check_claims(opts: dict) -> None:
    MS.check_claims(opts)


# ───────────────────────────── پیش‌نمایش

def _work_doc(c: BrandCharacter, d: dict | None) -> dict:
    doc = dict(c.doc or {})
    if isinstance(d, dict) and isinstance(d.get("doc"), dict):
        doc = {**doc, **d["doc"]}
    work = D.normalize(doc, name=c.name)
    if work["logo"] == "chest" and store_logo(c.store) is None:
        work["logo"] = "none"
    return work


def preview(c: BrandCharacter, d: dict) -> dict:
    """پیش‌نمایشِ سریعِ ذخیره‌نشده (JPEG base64) + کلیدِ رنگ؛ ``d.doc`` (ویرایشِ ذخیره‌نشده) را هم می‌پذیرد."""
    opts = clean_options(d, c)
    doc = _work_doc(c, d)
    colours = effective_brand(c)
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    with _slots:
        img, info = R.still(doc, opts, colours, logo, scale=PREVIEW_SCALE)
    res = R.check_one(doc, pose=opts["pose"], expression=opts["expression"], logo=logo, flip=opts["flip"])
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=84)
    claims = [] if opts["allow_claims"] else [f for f in copy_guard.check_text(" ".join(str((opts.get(k) or {}).get("text") or "") for k in ("bubble", "caption"))) if f["code"] in copy_guard.BLOCKING]
    return {"image": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), "width": img.width, "height": img.height, "qa": R.qa_public(res), "claims": claims,
            "claims_message": copy_guard.message_fa(claims) if claims else "", "prop": info["props"][0], "options": MS._public_opts(opts)}


def figure_svg(c: BrandCharacter, d: dict) -> dict:
    """SVG زندهٔ شخصیت برای ادیتور: ``{svg، embedded، view، anchors، head}``. ژست و حالت اختیاری‌اند (پیش‌فرض ایستاده و شاد)."""
    d = d if isinstance(d, dict) else {}
    doc = _work_doc(c, d)
    pose = d.get("pose") if d.get("pose") in poses.POSES else "stand"
    expression = d.get("expression") if d.get("expression") in D.EXPRESSIONS else "happy"
    prop = d.get("prop") if d.get("prop") in (None, "auto") or d.get("prop") in D.PROPS else None
    prop = None if prop in (None, "auto") else prop
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    svg_text, info = R.svg(doc, pose=pose, expression=expression, prop=prop, flip=bool(d.get("flip")), logo=logo, background=d.get("background") if str(d.get("background") or "").startswith("#") else None,
                           view="canvas" if d.get("view") == "canvas" else "figure")
    out = {"svg": svg_text, **info}
    if doc["style"] in R.VECTOR_STYLES:
        out["anchors"] = R.preview_frames(doc, pose, expression)["anchors"]
    return out


# ───────────────────────────── رندر و ثبت

def _logo_key(logo: Image.Image | None) -> str:
    if logo is None:
        return ""
    return hashlib.sha1(logo.convert("RGBA").resize((16, 16)).tobytes()).hexdigest()[:10]


def _key(c: BrandCharacter, kind: str, payload: dict, colours: list[str], logo: Image.Image | None, doc: dict | None = None) -> str:
    d = doc or c.doc
    body = {"k": kind, "p": payload, "s": D.doc_hash(d), "v": c.version, "b": colours, "l": _logo_key(logo) if D.normalize(d)["logo"] == "chest" else "", "e": D.ENGINE_VERSION}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def _hit(c: BrandCharacter, key: str) -> CharacterRender | None:
    r = CharacterRender.objects.filter(character=c, key=key).select_related("asset").first()
    if r is None:
        return None
    if r.asset_id and r.asset and photo.abs_path(r.asset.original).is_file():
        return r
    if r.file and (Path(settings.MEDIA_ROOT) / r.file).is_file():
        return r
    r.delete()
    return None


def _write_file(c: BrandCharacter, key: str, ext: str, data: bytes) -> str:
    rel = f"brandchar/s{c.store_id}/c{c.pk}/{key}.{ext}"
    path = Path(settings.MEDIA_ROOT) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def _prune(c: BrandCharacter) -> None:
    old = list(CharacterRender.objects.filter(character=c).order_by("-pk").values_list("pk", flat=True)[MAX_RENDERS:])
    if old:
        CharacterRender.objects.filter(pk__in=old).delete()


def _register(c: BrandCharacter, user, kind: str, key: str, png: bytes | None, title: str, size: tuple[int, int], params: dict, qa_res: dict | None, *, doc: dict | None = None,
              file: tuple[str, bytes] | None = None) -> CharacterRender:
    asset = None
    if png is not None:
        ref = f"brandchar:{key}"[:60]
        asset = PhotoAsset.objects.filter(store=c.store, source_ref=ref).first()
        if asset is None or not photo.abs_path(asset.original).is_file():
            asset = photo._asset_from_bytes(c.store, user, png, title=title[:200], source_ref=ref, kind=PhotoAsset.Kind.GENERATED)
    rel = _write_file(c, key, file[0], file[1]) if file else ""
    row, _ = CharacterRender.objects.update_or_create(
        character=c, key=key, defaults={"store": c.store, "created_by": user, "kind": kind, "doc_hash": D.doc_hash(doc or c.doc), "version": c.version, "locked": c.locked, "params": params,
                                        "qa": R.qa_public(qa_res) if qa_res else {}, "width": size[0], "height": size[1], "asset": asset, "file": rel})
    _prune(c)
    return row


def render_shot(c: BrandCharacter, user, d: dict) -> tuple[CharacterRender, bool]:
    """پست/استوری با شخصیتِ ثابت. ⇒ (رندر، از کَش بود؟)."""
    opts = clean_options(d, c)
    check_claims(opts)
    doc = _work_doc(c, None)
    colours = effective_brand(c)
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    payload = MS._public_opts(opts)
    key = _key(c, "shot", payload, colours, logo)
    hit = _hit(c, key)
    if hit is not None:
        return hit, True
    with _slots:
        img, info = R.still(doc, opts, colours, logo)
    res = R.check_one(doc, pose=opts["pose"], expression=opts["expression"], logo=logo, flip=opts["flip"])
    size_fa = compose.SIZES[opts["size"]]["fa"]
    title = f"شخصیتِ برند «{c.name}» — {poses.label_fa(opts['pose'])} · {size_fa}"
    params = {**payload, "style": doc["style"], "claims_confirmed": bool(opts["allow_claims"] and copy_guard.check_text(" ".join(str((opts.get(k) or {}).get("text") or "") for k in ("bubble", "caption")))),
              "figure_bbox": info["figure_bbox"][0], "prop_drawn": info["props"][0]}
    return _register(c, user, "shot", key, _png(img), title, img.size, params, res), False


def sticker_payload(d: dict) -> dict:
    d = d if isinstance(d, dict) else {}
    pose = d.get("pose") or "thumbs_up"
    if pose not in poses.POSES:
        raise CharError("ژستِ ناشناخته است.")
    expression = d.get("expression") or "happy"
    if expression not in D.EXPRESSIONS:
        raise CharError("حالتِ چهره ناشناخته است.")
    prop = d.get("prop") or "auto"
    if prop != "auto" and prop not in D.PROPS:
        raise CharError("وسیلهٔ ناشناخته است.")
    return {"pose": pose, "expression": expression, "prop": prop, "flip": bool(d.get("flip")), "crop": "bust" if d.get("crop") == "bust" else "full"}


def render_sticker(c: BrandCharacter, user, d: dict) -> tuple[CharacterRender, bool]:
    """استیکرِ PNG شفاف (تمام‌قد یا نیم‌تنه)."""
    payload = sticker_payload(d)
    doc = _work_doc(c, None)
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    colours = effective_brand(c)
    key = _key(c, "sticker", payload, colours, logo)
    hit = _hit(c, key)
    if hit is not None:
        return hit, True
    with _slots:
        img, info = R.sticker(doc, pose=payload["pose"], expression=payload["expression"], prop=None if payload["prop"] == "auto" else payload["prop"], flip=payload["flip"], logo=logo, crop=payload["crop"])
    res = R.check_one(doc, pose=payload["pose"], expression=payload["expression"], logo=logo, flip=payload["flip"]) if payload["crop"] == "full" else None
    title = f"شخصیتِ برند «{c.name}» — استیکرِ شفاف · {poses.label_fa(payload['pose'])}" + (" (نیم‌تنه)" if payload["crop"] == "bust" else "")
    return _register(c, user, "sticker", key, _png(img), title, img.size, {**payload, "style": doc["style"], "prop_drawn": info["prop"]}, res), False


def render_sheet(c: BrandCharacter, user) -> tuple[CharacterRender, bool]:
    doc = _work_doc(c, None)
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    colours = effective_brand(c)
    pers = persona_data(c.store)
    key = _key(c, "sheet", {"title": c.name, "store": c.store.name, "p": hashlib.sha1(json.dumps(pers or {}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]}, colours, logo)
    hit = _hit(c, key)
    if hit is not None:
        return hit, True
    with _slots:
        img = SH.model_sheet(doc, title=c.name, store_name=c.store.name, version=c.version or None, logo=logo, persona=pers)
    return _register(c, user, "sheet", key, _png(img), f"برگهٔ مدلِ شخصیتِ برند «{c.name}»", img.size, {"title": c.name, "style": doc["style"]}, None), False


def render_pdf(c: BrandCharacter, user) -> tuple[CharacterRender, bool]:
    doc = _work_doc(c, None)
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    colours = effective_brand(c)
    pers = persona_data(c.store)
    key = _key(c, "pdf", {"title": c.name, "store": c.store.name, "p": hashlib.sha1(json.dumps(pers or {}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]}, colours, logo)
    hit = _hit(c, key)
    if hit is not None:
        return hit, True
    with _slots:
        data = SH.pdf_bytes(doc, title=c.name, store_name=c.store.name, version=c.version or None, logo=logo, persona=pers)
    return _register(c, user, "pdf", key, None, f"برگهٔ مدل (PDF) «{c.name}»", (2000, 1500), {"title": c.name, "style": doc["style"]}, None, file=("pdf", data)), False


def render_svg(c: BrandCharacter, user, d: dict) -> tuple[CharacterRender, bool]:
    d = d if isinstance(d, dict) else {}
    doc = _work_doc(c, None)
    pose = d.get("pose") if d.get("pose") in poses.POSES else "stand"
    expression = d.get("expression") if d.get("expression") in D.EXPRESSIONS else "happy"
    prop = d.get("prop") if d.get("prop") in D.PROPS else None
    bg = d.get("background") if str(d.get("background") or "").startswith("#") else None
    payload = {"pose": pose, "expression": expression, "prop": prop or "auto", "flip": bool(d.get("flip")), "bg": bg or ""}
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    colours = effective_brand(c)
    key = _key(c, "svg", payload, colours, logo)
    hit = _hit(c, key)
    if hit is not None:
        return hit, True
    with _slots:
        text, info = R.svg(doc, pose=pose, expression=expression, prop=prop, flip=payload["flip"], logo=logo, background=bg)
    return _register(c, user, "svg", key, None, f"SVG «{c.name}»", (int(info["view"][2]), int(info["view"][3])), {**payload, "embedded": info["embedded"], "style": doc["style"]}, None,
                     file=("svg", text.encode("utf-8"))), False


def read_file(r: CharacterRender) -> bytes | None:
    if not r.file:
        return None
    p = Path(settings.MEDIA_ROOT) / r.file
    return p.read_bytes() if p.is_file() else None


# ───────────────────────────── بسته‌یِ خروجی

EXPORT_POSES = poses.SHEET_POSES


def export_pack(c: BrandCharacter, user) -> bytes:
    """ZIP: برگهٔ مدل (PNG و PDF)، SVGِ هشت ژست، استیکرِ شفافِ هشت ژست، سند (JSON)، شخصیتِ گفتار (JSON) و راهنمای فارسی."""
    doc = _work_doc(c, None)
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    pers = persona_data(c.store)
    buf = io.BytesIO()
    with _slots, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        sheet = SH.model_sheet(doc, title=c.name, store_name=c.store.name, version=c.version or None, logo=logo, persona=pers)
        z.writestr("model-sheet.png", _png(sheet))
        z.writestr("model-sheet.pdf", SH.pdf_bytes(doc, title=c.name, store_name=c.store.name, version=c.version or None, logo=logo, persona=pers))
        for pz in EXPORT_POSES:
            text, _info = R.svg(doc, pose=pz, expression="happy", logo=logo)
            z.writestr(f"svg/{pz}.svg", text)
            img, _ = R.sticker(doc, pose=pz, expression="happy", logo=logo, height_px=1000)
            z.writestr(f"sticker-png/{pz}.png", _png(img))
        z.writestr("character.json", json.dumps({"name": c.name, "version": c.version, "locked": c.locked, "doc": doc}, ensure_ascii=False, indent=2))
        z.writestr("palette.json", json.dumps(D.palette(doc), ensure_ascii=False, indent=2))
        if pers:
            z.writestr("persona.json", json.dumps(pers, ensure_ascii=False, indent=2))
        z.writestr("README-fa.txt", "\n".join([
            f"شخصیتِ برند «{c.name}» — فروشگاهِ {c.store.name}", f"نسخه: {c.version}" + (" (تأییدشده)" if c.locked else " (هنوز قفل نشده)"), "",
            "model-sheet.png / .pdf  برگهٔ مدل: مرجعِ همهٔ تصویرها (کلیدِ رنگ، حالت‌ها، ژست‌ها، سبک‌ها)",
            "svg/                    هشت ژستِ برداری (سبکِ آدمک‌چوبی: تصویرِ جاسازی‌شده، نه برداری)",
            "sticker-png/            استیکرِ شفاف برای تامنیل، استوری و ویدیو", "character.json         سندِ کاملِ ظاهر (برای بازسازیِ همین شخصیت)",
            "palette.json            رنگ‌های امضا", "persona.json            لحنِ گفتارِ برند (اگر ثبت شده باشد)", "",
            "شخصیت یک کارتونِ کشیده‌شده با کد است، نه آدمِ واقعی. متنِ حباب‌ها را خودتان بنویسید یا از جمله‌های بی‌ادعا بردارید."]))
    log_use(c.store, c, "export", "zip", user=user)
    return buf.getvalue()


# ───────────────────────────── بررسیِ ثبات

def run_check(c: BrandCharacter, *, flip_too: bool = True) -> dict:
    """هر ژست × چهار اندازه (و نسخهٔ آینه‌ای) برای سبکِ همین شخصیت. نتیجه در ``last_check`` می‌ماند."""
    doc = _work_doc(c, None)
    logo = store_logo(c.store) if doc["logo"] == "chest" else None
    with _slots:
        res = R.grid(doc, logo=logo)
        res_flip = R.grid(doc, logo=logo, pose_list=["stand", "wave", "thumbs_up", "run_a", "think"], sizes=("ig_portrait",), flip=True) if flip_too else None
    failed = res["failed"] + ((res_flip or {}).get("failed") or [])
    out = {"at": timezone.now().isoformat(), "ok": not failed, "passed": res["passed"] + (res_flip or {}).get("passed", 0), "total": res["total"] + (res_flip or {}).get("total", 0),
           "seconds": round(res["seconds"] + (res_flip or {}).get("seconds", 0), 2), "version": c.version, "style": doc["style"], "poses": res["poses"], "sizes": res["sizes"], "failed": failed[:12]}
    c.last_check = out
    c.save(update_fields=["last_check", "updated_at"])
    return out


# ───────────────────────────── کاربرد

def log_use(store, character, surface: str, ref: str = "", meta: dict | None = None, user=None) -> None:
    try:
        UsageEvent.objects.create(store=store, character=character, surface=surface[:20], ref=str(ref)[:120], meta=meta or {}, created_by=user)
    except Exception:  # noqa: BLE001 — ثبتِ کاربرد هرگز کارِ اصلی را نمی‌شکند
        pass


# ───────────────────────────── نمایش

def asset_row(a: PhotoAsset | None) -> dict | None:
    return MS.asset_row(a)


def render_dict(r: CharacterRender, *, cached: bool | None = None) -> dict:
    a = r.asset
    base = f"/api/v1/stores/{r.store_id}/brand-character/characters/{r.character_id}/renders/{r.pk}/download/"
    out = {"id": r.pk, "character": r.character_id, "kind": r.kind, "kind_fa": r.get_kind_display(), "version": r.version, "locked": r.locked, "params": r.params, "qa": r.qa,
           "width": r.width, "height": r.height, "asset": asset_row(a), "created_at": r.created_at,
           "urls": {"png": photo.media_url(a.original) if a else None, "thumb": photo.media_url(a.thumb) if a else None, "download": base},
           "size_kb": round((a.size_bytes if a else 0) / 1024)}
    if cached is not None:
        out["cached"] = cached
    return out


def character_dict(c: BrandCharacter, *, with_cover: bool = True) -> dict:
    doc = D.normalize(c.doc, name=c.name)
    role = B.ROLES.get(c.role) or {}
    out = {"id": c.pk, "name": c.name, "role": c.role, "role_fa": role.get("fa", c.role), "doc": doc, "palette": D.palette(doc), "version": c.version, "locked": c.locked,
           "locked_at": c.locked_at, "is_primary": c.is_primary, "brand_colours": c.brand_colours or [], "check": c.last_check or {}, "concept": c.concept or {},
           "has_logo": doc["logo"] == "chest", "created_at": c.created_at, "updated_at": c.updated_at, "style": doc["style"], "style_fa": D.STYLE_LABELS_FA[doc["style"]],
           "shots": c.renders.filter(kind="shot").count(), "stickers": c.renders.filter(kind="sticker").count(), "mascot": c.mascot_id}
    if with_cover:
        row, kind = cover_row(c)
        out["cover"] = photo.media_url(row.asset.thumb) if row is not None and row.asset_id else None
        out["cover_kind"] = kind
    return out


#: نیم‌تنهٔ شفافِ ایستاده و خندان: «کارتِ» پایدارِ هر شخصیت (همان آواتارِ صندوقِ پیام). قالب‌ها و پست‌ها کارت را عوض نمی‌کنند.
COVER = {"pose": "stand", "expression": "happy", "prop": "none", "flip": False, "crop": "bust"}


def cover_row(c: BrandCharacter) -> tuple[CharacterRender | None, str]:
    """⇒ (رندر، «bust» اگر نیم‌تنهٔ تازهٔ همین نسخه باشد؛ «other» اگر فقط چیزِ دیگری هست؛ «» اگر هیچ)."""
    qs = c.renders.select_related("asset")
    h = D.doc_hash(c.doc)
    for r in qs.filter(kind="sticker")[:60]:
        p = r.params or {}
        if r.asset_id and p.get("crop") == "bust" and p.get("pose") == COVER["pose"] and p.get("expression") == COVER["expression"] and (p.get("prop") or "none") == "none" and not p.get("flip") \
                and r.doc_hash == h and r.version == c.version:
            return r, "bust"
    other = qs.filter(kind__in=("sticker", "sheet")).first() or qs.filter(kind__in=("shot", "template")).first()
    return (other, "other") if other is not None else (None, "")


def ensure_cover(c: BrandCharacter, user) -> CharacterRender | None:
    """کارتِ پایدار را (اگر نیست یا کهنه است) می‌سازد؛ شکست در آن هرگز کاری را خراب نمی‌کند."""
    row, kind = cover_row(c)
    if kind == "bust":
        return row
    try:
        return render_sticker(c, user, COVER)[0]
    except Exception:  # noqa: BLE001
        logger.warning("brandchar cover failed for %s", c.pk, exc_info=True)
        return None


def options_public() -> dict:
    base = MS.options_public()
    base["choices"] = {k: [{"key": o, "fa": D.CHOICE_LABELS_FA.get(k, {}).get(o, o)} for o in opts] for k, opts in D.CHOICES.items()}
    base["bools"] = [{"key": k, "fa": D.BOOL_LABELS_FA[k]} for k in D.BOOLS]
    base["skin_presets"] = [{"hex": h, "fa": fa} for h, fa in zip(D.SKIN_PRESETS, D.SKIN_PRESETS_FA)]
    base["colour_keys"] = [
        {"key": "skin", "fa": "پوست"}, {"key": "hair_colour", "fa": "مو"}, {"key": "top", "fa": "لباسِ اصلی"}, {"key": "top2", "fa": "رنگِ دومِ لباس"}, {"key": "bottom", "fa": "شلوار"},
        {"key": "shoes", "fa": "کفش"}, {"key": "hat_colour", "fa": "کلاه"}, {"key": "neck_colour", "fa": "شال/کراوات"}, {"key": "extra_colour", "fa": "وسیلهٔ اضافه"},
        {"key": "prop_colour", "fa": "وسیلهٔ دست"}, {"key": "outline", "fa": "خطِ دور"}, {"key": "limb_colour", "fa": "دست و پا (آدمک‌چوبی)"}, {"key": "head_fill", "fa": "سر (آدمک‌چوبی)"}]
    base["styles"] = [{"key": k, "fa": D.STYLE_LABELS_FA[k], "hint": D.STYLE_HINTS_FA[k], "vector": k != "stick"} for k in D.STYLES]
    base["anchors"] = [{"key": "world", "fa": "کلِ بوم"}, {"key": "head", "fa": "سر (با ژست حرکت می‌کند)"}, {"key": "body", "fa": "بدن"}, {"key": "hand", "fa": "دستِ راست"}]
    base["layer_shapes"] = [{"key": "rect", "fa": "مستطیل"}, {"key": "ellipse", "fa": "بیضی"}, {"key": "line", "fa": "خط"}, {"key": "path", "fa": "مسیر (قلم)"}]
    base["limits"] = {"max_layers": D.MAX_LAYERS, "max_points": D.MAX_POINTS}
    return base


def overview(store) -> dict:
    from . import persona_store, usage

    chars = [character_dict(c) for c in BrandCharacter.objects.filter(store=store)]
    pr = persona_store.public(persona_store.get(store))
    return {
        "store": {"id": store.pk, "name": store.name, "colors": brand_colours(store), "has_logo": store_logo(store) is not None},
        "roles": B.roles_public(), "options": options_public(), "lines": copy_guard.suggested_lines(store.name), "characters": chars, "persona": pr,
        "limits": {"max_characters": MAX_CHARACTERS, "max_text": MS.MAX_TEXT, "max_renders": MAX_RENDERS},
        "usage": usage.summary(store), "has_facts": P.facts_for(store.name) is not None,
        "notes": ["شخصیتِ برند یک کارتونِ کشیده‌شده با کد است، نه آدمِ واقعی؛ بدونِ هوش مصنوعی و کارتِ گرافیک هم کار می‌کند.",
                  "متنِ حباب و کپشن را خودتان بنویسید یا از جمله‌های بی‌ادعا بردارید؛ قیمت، آمار، وعدهٔ نتیجه، نظرِ مشتری و ادعای پزشکی ننویسید."],
    }
