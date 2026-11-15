"""منطقِ ماسکوت: ساخت و ویرایشِ شخصیت، قفل، رندرِ کَش‌دار (پست/استوری، استیکر، برگهٔ مدل)، ثبت در کتابخانهٔ ادیتورِ عکس، بررسیِ ثبات.

موتور (``engine/``) خالص است و دیتابیس نمی‌شناسد؛ این‌جا همهٔ چیزِ وابسته به Django و فایل است: رنگ و لوگوی برندِ فروشگاه (همان «سبکِ برند» ِ
تامنیل‌ساز)، رکوردها، کَش با کلیدِ هش و ثبتِ هر خروجی به‌عنوانِ ``PhotoAsset``. هیچ‌جا هوش مصنوعی یا سرورِ پردازش لازم نیست.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import threading

from django.utils import timezone
from PIL import Image

from apps.photoedit import services as photo
from apps.photoedit.models import PhotoAsset

from . import selftest
from .engine import brand as B
from .engine import compose, copy_guard, poses, qa, scenes
from .engine import spec as S
from .models import Mascot, MascotRender

logger = logging.getLogger(__name__)

MAX_MASCOTS = 8
MAX_RENDERS = 150
PREVIEW_SCALE = 0.42
MAX_TEXT = 140
_slots = threading.BoundedSemaphore(2)           # روی ۲ هستهٔ سرور هم‌زمان دو رندر


class MascotError(Exception):
    """متنش برای کاربر است."""


class ClaimsError(MascotError):
    def __init__(self, found: list[dict]):
        super().__init__(copy_guard.message_fa(found))
        self.found = found


# ───────────────────────────── برند

def brand_colours(store) -> list[str]:
    """رنگ‌های برندِ فروشگاه: «سبکِ برند» ِ ادیتورِ عکس، بعد رنگ‌هایی که در خودِ فروشگاه ثبت شده."""
    got: list = []
    try:
        from apps.thumbs import services as thumbs

        got = list(thumbs.brand_kit(store)["colors"])
    except Exception:  # noqa: BLE001 — رنگِ برند نبود هم ماسکوت کار می‌کند
        logger.warning("mascot: brand kit unavailable for store %s", getattr(store, "pk", "?"))
    if not got and isinstance(store.colors, dict):
        got = [v for v in store.colors.values() if isinstance(v, str)]
    return B.clean_colours(got)[:4]


def store_logo(store) -> Image.Image | None:
    """لوگوی فروشگاه (RGBA، کوچک‌شده) یا None."""
    try:
        from apps.photoedit import ops
        from apps.thumbs import services as thumbs

        path = thumbs._logo_path(store, thumbs.brand_kit(store)["kit"])
        if path is None:
            return None
        img = ops.load(path)
        img.thumbnail((512, 512), Image.Resampling.LANCZOS)
        return img.convert("RGBA")
    except Exception:  # noqa: BLE001
        logger.warning("mascot: logo of store %s could not be read", getattr(store, "pk", "?"))
        return None


def effective_brand(m: Mascot) -> list[str]:
    return B.clean_colours(m.brand_colours)[:4] or brand_colours(m.store)


# ───────────────────────────── رکوردها

def _clean_name(name, default: str) -> str:
    n = " ".join(str(name or "").split())[:80]
    return n or default


def create(store, user, *, role: str = B.DEFAULT_ROLE, name: str = "", use_logo: bool = True, brand: list | None = None) -> Mascot:
    if Mascot.objects.filter(store=store).count() >= MAX_MASCOTS:
        raise MascotError(f"هر فروشگاه حداکثر {MAX_MASCOTS} ماسکوت دارد؛ یکی را پاک کنید.")
    role = role if role in B.ROLES else B.DEFAULT_ROLE
    colours = B.clean_colours(brand) or brand_colours(store)
    name = _clean_name(name, f"{B.ROLES[role]['fa']} {store.name}"[:80])
    has_logo = bool(use_logo and store_logo(store) is not None)
    spec = B.spec_from_brand(role, colours, name, logo=has_logo)
    return Mascot.objects.create(store=store, created_by=user, name=name, role=role, spec=spec, brand_colours=B.clean_colours(brand)[:4])


def update(m: Mascot, data: dict) -> Mascot:
    """نام، نقش، رنگِ برند و (اگر قفل نیست) ظاهر. «بازتنظیم از روی نقش» ظاهر را دوباره از رنگ‌های برند می‌سازد."""
    if m.locked:
        raise MascotError("ظاهرِ این ماسکوت تأیید و قفل شده است؛ برای تغییر، اول «بازکردنِ قفل» را بزنید.")
    fields = ["updated_at"]
    if "name" in data:
        m.name = _clean_name(data["name"], m.name)
        fields.append("name")
    if "brand_colours" in data:
        m.brand_colours = B.clean_colours(data["brand_colours"])[:4]
        fields.append("brand_colours")
    spec = dict(m.spec or {})
    if data.get("role") in B.ROLES and data.get("reset_look", True) and data["role"] != m.role:
        m.role = data["role"]
        fields.append("role")
        spec = B.spec_from_brand(m.role, effective_brand(m), m.name, logo=spec.get("logo") == "chest")
    if data.get("reset_look") is True:
        spec = B.spec_from_brand(m.role, effective_brand(m), m.name, logo=spec.get("logo") == "chest")
    if isinstance(data.get("spec"), dict):
        spec = {**spec, **data["spec"]}
    spec["name"] = m.name
    new = S.normalize(spec)
    if new.get("logo") == "chest" and store_logo(m.store) is None:
        new["logo"] = "none"                                  # لوگویی نیست که روی سینه بنشیند
    if new != m.spec:
        m.spec = new
        fields.append("spec")
        m.last_check = {}
        fields.append("last_check")
    m.save(update_fields=list(dict.fromkeys(fields)))
    return m


def lock(m: Mascot) -> Mascot:
    """تأییدِ ظاهر: نسخه بالا می‌رود و spec قفل می‌شود."""
    if not m.locked:
        m.locked, m.locked_at = True, timezone.now()
        m.version += 1
        m.save(update_fields=["locked", "locked_at", "version", "updated_at"])
    return m


def unlock(m: Mascot) -> Mascot:
    if m.locked:
        m.locked = False
        m.save(update_fields=["locked", "updated_at"])
    return m


# ───────────────────────────── گزینه‌های ساخت

def _hex_or_none(v) -> str | None:
    c = B.clean_colours([v])
    return c[0] if c else None


def clean_options(d: dict, m: Mascot | None = None) -> dict:
    d = d if isinstance(d, dict) else {}
    role = B.ROLES.get(m.role if m else B.DEFAULT_ROLE) or B.ROLES[B.DEFAULT_ROLE]
    size = d.get("size") or compose.DEFAULT_SIZE
    if size not in compose.SIZES:
        raise MascotError("اندازهٔ ناشناخته است.")
    pose = d.get("pose") or "stand"
    if pose not in poses.POSES:
        raise MascotError("ژستِ ناشناخته است.")
    expression = d.get("expression") or "happy"
    if expression not in S.EXPRESSIONS:
        raise MascotError("حالتِ چهره ناشناخته است.")
    bg = d.get("background") or role["background"]
    if bg not in scenes.BACKGROUNDS:
        bg = _hex_or_none(bg)
        if bg is None:
            raise MascotError("پس‌زمینهٔ ناشناخته است.")
    prop = d.get("prop") or "auto"
    if prop != "auto" and prop not in S.PROPS:
        raise MascotError("وسیلهٔ ناشناخته است.")
    position = d.get("position") if d.get("position") in compose.POSITIONS else "center"
    out: dict = {"size": size, "pose": pose, "expression": expression, "background": bg, "position": position, "flip": bool(d.get("flip")), "prop": prop,
                 "bubble": None, "caption": None}
    b = d.get("bubble")
    if isinstance(b, dict) and str(b.get("text") or "").strip():
        kind = b.get("kind") if b.get("kind") in compose.BUBBLE_KINDS else "say"
        try:
            font = max(30, min(96, int(b.get("font") or 52)))
        except (TypeError, ValueError):
            font = 52
        out["bubble"] = {"text": " ".join(str(b["text"]).split())[:MAX_TEXT], "kind": kind, "font": font}
    c = d.get("caption")
    if isinstance(c, dict) and str(c.get("text") or "").strip():
        out["caption"] = {"text": " ".join(str(c["text"]).split())[:MAX_TEXT], "position": "bottom" if c.get("position") == "bottom" else "top"}
    out["allow_claims"] = bool(d.get("allow_claims"))
    return out


def check_claims(opts: dict) -> None:
    """قیمت، آمار، وعدهٔ نتیجه، نظرِ مشتری و ادعای پزشکی در متنِ حباب یا کپشن ⇒ بدونِ تأییدِ صریحِ کاربر ساخته نمی‌شود."""
    if opts.get("allow_claims"):
        return
    texts = " ".join(str((opts.get(k) or {}).get("text") or "") for k in ("bubble", "caption"))
    found = [f for f in copy_guard.check_text(texts) if f["code"] in copy_guard.BLOCKING]
    if found:
        raise ClaimsError(found)


def _scene(m: Mascot, opts: dict, colours: list[str], *, scale: float = 1.0) -> dict:
    w0, h0 = compose.size_of(opts["size"])
    scene: dict = {"size": opts["size"], "brand": colours, "position": opts["position"],
                   "background": {"color": opts["background"]} if str(opts["background"]).startswith("#") else opts["background"],
                   "actors": [{"spec": m.spec, "pose": opts["pose"], "expression": opts["expression"], "flip": opts["flip"],
                               "prop": None if opts["prop"] == "auto" else opts["prop"]}]}
    if scale != 1.0:
        scene["width"], scene["height"] = max(120, round(w0 * scale)), max(120, round(h0 * scale))
    if opts["bubble"]:
        scene["bubbles"] = [{"actor": 0, **opts["bubble"]}]
    if opts["caption"]:
        scene["caption"] = dict(opts["caption"])
    return scene


# ───────────────────────────── پیش‌نمایش

def preview(m: Mascot, d: dict) -> dict:
    """پیش‌نمایشِ سریعِ بدونِ ذخیره؛ ``d["spec"]`` (ویرایشِ ذخیره‌نشده) را هم می‌پذیرد."""
    opts = clean_options(d, m)
    work = m
    if isinstance(d.get("spec"), dict):
        work = Mascot(store=m.store, name=m.name, role=m.role, spec=S.normalize({**(m.spec or {}), **d["spec"]}), brand_colours=m.brand_colours)
        if work.spec.get("logo") == "chest" and store_logo(m.store) is None:
            work.spec["logo"] = "none"
    colours = effective_brand(m)
    logo = store_logo(m.store) if work.spec.get("logo") == "chest" else None
    with _slots:
        img, info = compose.compose_still(_scene(work, opts, colours, scale=PREVIEW_SCALE), logo=logo)
    res = qa.check_figure(compose.qa_layer(_scene(work, opts, colours)["actors"][0], logo=logo).layer, S.palette(work.spec))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=84)
    claims = [] if opts["allow_claims"] else [f for f in copy_guard.check_text(" ".join(str((opts.get(k) or {}).get("text") or "") for k in ("bubble", "caption"))) if f["code"] in copy_guard.BLOCKING]
    return {"image": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), "width": img.width, "height": img.height,
            "qa": qa_public(res), "claims": claims, "claims_message": copy_guard.message_fa(claims) if claims else "", "prop": info["props"][0], "options": _public_opts(opts)}


# ───────────────────────────── رندر و ثبت

def _logo_key(logo: Image.Image | None) -> str:
    if logo is None:
        return ""
    return hashlib.sha1(logo.convert("RGBA").resize((16, 16)).tobytes()).hexdigest()[:10]


def _key(m: Mascot, kind: str, payload: dict, colours: list[str], logo: Image.Image | None) -> str:
    body = {"k": kind, "p": payload, "s": S.spec_hash(m.spec), "v": m.version, "b": colours, "l": _logo_key(logo) if (m.spec or {}).get("logo") == "chest" else "", "e": S.ENGINE_VERSION}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def _public_opts(opts: dict) -> dict:
    return {k: v for k, v in opts.items() if k != "allow_claims"}


def qa_public(res: dict) -> dict:
    return {"ok": res["ok"], "score": res["palette_score"], "colours": [{k: c[k] for k in ("role", "hex", "name", "found", "share")} for c in res["colours"]],
            "notes": [qa.note_fa(n) for n in res["notes"]], "scope": res.get("scope", "figure")}


def _hit(m: Mascot, key: str) -> MascotRender | None:
    r = MascotRender.objects.filter(mascot=m, key=key).select_related("asset").first()
    if r is not None and r.asset_id and r.asset and photo.abs_path(r.asset.original).is_file():
        return r
    if r is not None:
        r.delete()                                           # عکسش از کتابخانه پاک شده؛ دوباره ساخته شود
    return None


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def _register(m: Mascot, user, kind: str, key: str, png: bytes, title: str, size: tuple[int, int], params: dict, qa_res: dict | None) -> MascotRender:
    ref = f"mascot:{key}"[:60]
    asset = PhotoAsset.objects.filter(store=m.store, source_ref=ref).first()
    if asset is None or not photo.abs_path(asset.original).is_file():
        asset = photo._asset_from_bytes(m.store, user, png, title=title[:200], source_ref=ref, kind=PhotoAsset.Kind.GENERATED)
    row, _ = MascotRender.objects.update_or_create(
        mascot=m, key=key, defaults={"store": m.store, "created_by": user, "kind": kind, "spec_hash": S.spec_hash(m.spec), "version": m.version, "locked": m.locked,
                                      "params": params, "qa": qa_public(qa_res) if qa_res else {}, "width": size[0], "height": size[1], "asset": asset})
    old = list(MascotRender.objects.filter(mascot=m).order_by("-pk").values_list("pk", flat=True)[MAX_RENDERS:])
    if old:
        MascotRender.objects.filter(pk__in=old).delete()
    return row


def render_shot(m: Mascot, user, d: dict) -> tuple[MascotRender, bool]:
    """پست/استوری با شخصیتِ ثابت. ⇒ (رندر، از کَش بود؟)."""
    opts = clean_options(d, m)
    check_claims(opts)
    colours = effective_brand(m)
    logo = store_logo(m.store) if m.spec.get("logo") == "chest" else None
    payload = _public_opts(opts)
    key = _key(m, "shot", payload, colours, logo)
    hit = _hit(m, key)
    if hit is not None:
        return hit, True
    with _slots:
        img, info = compose.compose_still(_scene(m, opts, colours), logo=logo)
    res = qa.check_figure(compose.qa_layer(_scene(m, opts, colours)["actors"][0], logo=logo).layer, S.palette(m.spec))
    size_fa = compose.SIZES[opts["size"]]["fa"]
    title = f"ماسکوت «{m.name}» — {poses.label_fa(opts['pose'])} · {size_fa}"
    params = {**payload, "claims_confirmed": bool(opts["allow_claims"] and copy_guard.check_text(" ".join(str((opts.get(k) or {}).get("text") or "") for k in ("bubble", "caption")))),
              "figure_bbox": info["figure_bbox"][0], "prop_drawn": info["props"][0]}
    return _register(m, user, "shot", key, _png(img), title, img.size, params, res), False


def render_sticker(m: Mascot, user, d: dict) -> tuple[MascotRender, bool]:
    """استیکرِ PNG شفاف (تمام‌قد یا نیم‌تنه). تامنیل‌ساز آن را بدونِ هیچ «حذفِ پس‌زمینه»ای به‌عنوانِ سوژه می‌گیرد."""
    d = d if isinstance(d, dict) else {}
    pose = d.get("pose") or "thumbs_up"
    if pose not in poses.POSES:
        raise MascotError("ژستِ ناشناخته است.")
    expression = d.get("expression") or "happy"
    if expression not in S.EXPRESSIONS:
        raise MascotError("حالتِ چهره ناشناخته است.")
    prop = d.get("prop") or "auto"
    if prop != "auto" and prop not in S.PROPS:
        raise MascotError("وسیلهٔ ناشناخته است.")
    crop = "bust" if d.get("crop") == "bust" else "full"
    payload = {"pose": pose, "expression": expression, "prop": prop, "flip": bool(d.get("flip")), "crop": crop}
    logo = store_logo(m.store) if m.spec.get("logo") == "chest" else None
    colours = effective_brand(m)
    key = _key(m, "sticker", payload, colours, logo)
    hit = _hit(m, key)
    if hit is not None:
        return hit, True
    with _slots:
        img, info = compose.sticker(m.spec, pose=pose, expression=expression, prop=None if prop == "auto" else prop, flip=payload["flip"], logo=logo, crop=crop)
    res = qa.check_figure(img, S.palette(m.spec))
    title = f"ماسکوت «{m.name}» — استیکرِ شفاف · {poses.label_fa(pose)}" + (" (نیم‌تنه)" if crop == "bust" else "")
    return _register(m, user, "sticker", key, _png(img), title, img.size, {**payload, **{"prop_drawn": info["prop"]}}, res if crop == "full" else None), False


def render_sheet(m: Mascot, user) -> tuple[MascotRender, bool]:
    logo = store_logo(m.store) if m.spec.get("logo") == "chest" else None
    colours = effective_brand(m)
    key = _key(m, "sheet", {"title": m.name, "store": m.store.name}, colours, logo)
    hit = _hit(m, key)
    if hit is not None:
        return hit, True
    with _slots:
        img = compose.model_sheet(m.spec, title=m.name, store_name=m.store.name, version=m.version or None, logo=logo)
    return _register(m, user, "sheet", key, _png(img), f"برگهٔ مدلِ ماسکوت «{m.name}»", img.size, {"title": m.name}, None), False


# ───────────────────────────── بررسیِ ثبات

def run_check(m: Mascot) -> dict:
    """هر ژست × چهار اندازه: شخصیت خالی نیست و همهٔ رنگ‌های امضا دیده می‌شوند. نتیجه در ``Mascot.check`` می‌ماند."""
    logo = store_logo(m.store) if m.spec.get("logo") == "chest" else None
    with _slots:
        res = selftest.grid(m.spec, logo=logo)
    out = {"at": timezone.now().isoformat(), "ok": res["ok"], "passed": res["passed"], "total": res["total"], "seconds": res["seconds"], "version": m.version,
           "poses": res["poses"], "sizes": res["sizes"], "failed": res["failed"][:12]}
    m.last_check = out
    m.save(update_fields=["last_check", "updated_at"])
    return out


# ───────────────────────────── نمایش

def asset_row(a: PhotoAsset | None) -> dict | None:
    if a is None:
        return None
    return {"id": a.pk, "title": a.title, "thumb": photo.media_url(a.thumb), "url": photo.media_url(a.original), "width": a.width, "height": a.height,
            "has_alpha": a.has_alpha, "source_kind": a.source_kind, "product": a.product_id}


def render_dict(r: MascotRender, *, cached: bool | None = None) -> dict:
    a = r.asset
    out = {"id": r.pk, "mascot": r.mascot_id, "kind": r.kind, "kind_fa": r.get_kind_display(), "version": r.version, "locked": r.locked, "params": r.params, "qa": r.qa,
           "width": r.width, "height": r.height, "asset": asset_row(a), "created_at": r.created_at,
           "urls": {"png": photo.media_url(a.original) if a else None, "thumb": photo.media_url(a.thumb) if a else None,
                    "download": f"/api/v1/stores/{r.store_id}/mascot/{r.mascot_id}/shots/{r.pk}/download/"},
           "size_kb": round((a.size_bytes if a else 0) / 1024)}
    if cached is not None:
        out["cached"] = cached
    return out


def mascot_dict(m: Mascot, *, with_cover: bool = True) -> dict:
    spec = S.normalize(m.spec)
    role = B.ROLES.get(m.role) or {}
    out = {"id": m.pk, "name": m.name, "role": m.role, "role_fa": role.get("fa", m.role), "spec": spec, "palette": S.palette(spec), "anchor": S.anchor_text(spec),
           "version": m.version, "locked": m.locked, "locked_at": m.locked_at, "brand_colours": m.brand_colours or [], "check": m.last_check or {},
           "has_logo": spec.get("logo") == "chest", "created_at": m.created_at, "updated_at": m.updated_at,
           "shots": m.renders.filter(kind="shot").count(), "stickers": m.renders.filter(kind="sticker").count()}
    if with_cover:
        last = m.renders.filter(kind="shot").select_related("asset").first()
        out["cover"] = photo.media_url(last.asset.thumb) if last is not None and last.asset_id else None
    return out


def options_public() -> dict:
    return {
        "poses": [{"key": k, "fa": poses.POSE_LABELS[k][0], "en": poses.POSE_LABELS[k][1], "tags": poses.tags_of(k), "original": k in poses.ORIGINAL_24} for k in poses.POSES],
        "pose_tags": [{"key": k, "fa": v["fa"], "poses": list(v["poses"])} for k, v in poses.MARKETING_TAGS.items()],
        "expressions": [{"key": k, "fa": S.EXPRESSION_LABELS_FA[k]} for k in S.EXPRESSIONS],
        "backgrounds": [{"key": k, "fa": v["fa"], "en": v["en"], "group": v["group"]} for k, v in scenes.BACKGROUNDS.items()],
        "sizes": [{"key": k, "fa": v["fa"], "w": v["w"], "h": v["h"], "aspect": v["aspect"], "safe": list(v["safe"])} for k, v in compose.SIZES.items()],
        "choices": {k: [{"key": o, "fa": S.CHOICE_LABELS_FA.get(k, {}).get(o, o)} for o in opts] for k, opts in S.CHOICES.items()},
        "bubble_kinds": [{"key": k, "fa": v} for k, v in compose.BUBBLE_KINDS.items()],
        "positions": [{"key": "center", "fa": "وسط"}, {"key": "left", "fa": "چپ"}, {"key": "right", "fa": "راست"}],
        "crops": [{"key": "full", "fa": "تمام‌قد"}, {"key": "bust", "fa": "نیم‌تنه (برای چهرهٔ بزرگِ تامنیل)"}],
        "colour_keys": list(S.COLOUR_KEYS),
    }


def overview(store) -> dict:
    kit_colours = brand_colours(store)
    return {
        "store": {"id": store.pk, "name": store.name, "colors": kit_colours, "has_logo": store_logo(store) is not None},
        "roles": B.roles_public(), "options": options_public(), "lines": copy_guard.suggested_lines(store.name),
        "mascots": [mascot_dict(m) for m in Mascot.objects.filter(store=store)],
        "limits": {"max_mascots": MAX_MASCOTS, "max_text": MAX_TEXT, "max_renders": MAX_RENDERS},
        "notes": ["ماسکوت یک شخصیتِ کارتونیِ کشیده‌شده با کد است، نه آدمِ واقعی؛ هیچ مدلِ هوش مصنوعی یا کارتِ گرافیکی لازم نیست.",
                  "متنِ حباب و کپشن را خودتان بنویسید یا از جمله‌های بی‌ادعای پیشنهادی بردارید؛ قیمت، آمار، وعدهٔ نتیجه، نظرِ مشتری و ادعای پزشکی ننویسید."],
    }
