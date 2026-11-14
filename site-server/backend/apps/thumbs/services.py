"""منطقِ تامنیل‌ساز: ورودی‌ها از فروشگاه ⇒ ساخت (پیش‌نمایش/کامل/نسخه‌های A-B) ⇒ ذخیره، تاریخچه، دانلود، ادیتور عکس.

رندر (``render.py``) خالص است؛ این‌جا همه‌چیزِ وابسته به Django و فایل است: خواندنِ عکس‌ها (کتابخانهٔ ادیتورِ عکس)، رنگ و لوگوی برند،
برشِ سوژه (``cutout``)، پس‌زمینهٔ هوش مصنوعی (``aibg``) و فایل‌های خروجی زیرِ ``MEDIA_ROOT/thumbs/``.
"""
from __future__ import annotations

import base64
import copy
import io
import logging
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from django.utils import timezone
from PIL import Image

from apps.photoedit import brand as photo_brand
from apps.photoedit import ops
from apps.photoedit import services as photo
from apps.photoedit.models import PhotoAsset

from . import aibg, cutout, hooks, palette
from . import primitives as P
from . import formats as F
from . import render as R
from . import typo
from .models import IdeaSet, Thumbnail
from .styles import STYLES

logger = logging.getLogger(__name__)

MAX_VARIANTS = 6
PREVIEW_WIDTH = 720
THUMB_SIDE = 480
KEEP_IDEA_SETS = 30
MAX_ITEMS_PER_STORE = 120
_render_slots = threading.BoundedSemaphore(2)

STATE_FA = {"READY": "آماده", "WAITING_BG": "منتظرِ پس‌زمینهٔ هوش مصنوعی", "FAILED": "ناموفق"}


class ThumbError(Exception):
    """متنش برای کاربر است."""


# ───────────────────────────── برند و ورودی‌ها

def brand_kit(store) -> dict:
    kit = photo_brand.effective(store, None) or {}
    colors = palette.brand_colors_of(store.colors, kit.get("colors"))
    return {"colors": colors, "heading_font": kit.get("heading_font") or "", "tone": kit.get("tone") or "", "kit": kit,
            "has_logo": _logo_path(store, kit) is not None}


def _logo_path(store, kit=None) -> Path | None:
    logo = photo_brand.logo_asset(store, kit)
    if logo is not None:
        p = photo.abs_path(logo.original)
        if p.is_file():
            return p
    if (kit or {}).get("logo", {}).get("mode") == "none":
        return None
    return photo._store_logo(store)


def _asset(store, asset_id) -> PhotoAsset | None:
    if not asset_id:
        return None
    return PhotoAsset.objects.filter(store=store, pk=asset_id).first()


def prepare_inputs(store, spec: dict, *, allow_matting: bool = True) -> tuple[R.Inputs, list[str]]:
    """عکس‌های spec را از کتابخانه می‌خواند و سوژه را (اگر لازم) می‌برد. ⇒ (Inputs، یادداشت‌های فارسی)."""
    notes: list[str] = []
    kit = brand_kit(store)
    inp = R.Inputs(brand_colors=kit["colors"], store_name=store.name, heading_font=kit["heading_font"])
    sd = spec["subject"]
    for which, aid in ((1, sd.get("asset")), (2, spec["subject2"].get("asset"))):
        if not aid:
            continue
        asset = _asset(store, aid)
        if asset is None:
            notes.append("یکی از عکس‌های انتخاب‌شده در کتابخانه پیدا نشد.")
            continue
        mode = sd["mode"] if which == 1 else "auto"
        if mode == "photo":
            img, is_cut, note = cutout.load_asset(asset), False, ""
            if img is not None and P.is_blank(img):
                img, note = None, cutout.BLANK_NOTE
        else:
            img, is_cut, note = cutout.ensure(store, asset, allow_site=allow_matting)
        if img is None:
            notes.append(note or "فایلِ عکس پیدا نشد.")
            continue
        if note and which == 1 and mode == "cutout":
            notes.append(note)
        if which == 1:
            inp.subject, inp.subject_is_cutout = img, is_cut
        else:
            inp.subject2, inp.subject2_is_cutout = img, is_cut
    bg = spec["background"]
    if bg.get("asset"):
        a = _asset(store, bg["asset"])
        img = cutout.load_asset(a) if a is not None else None
        if img is not None:
            inp.background = img.convert("RGB")
        else:
            notes.append("عکسِ پس‌زمینه در کتابخانه پیدا نشد؛ پس‌زمینهٔ خودکار گذاشته شد.")
    for aid in spec.get("extra_assets") or []:
        a = _asset(store, aid)
        img = cutout.load_asset(a) if a is not None else None
        if img is not None:
            inp.extra.append(img)
    lp = _logo_path(store, kit["kit"])
    if lp is not None:
        try:
            inp.logo = ops.load(lp)
        except Exception:  # noqa: BLE001
            notes.append("لوگوی فروشگاه خوانده نشد.")
    return inp, notes


def render_spec(store, spec: dict, *, scale: float = 1.0, keep_layers: bool = False, allow_matting: bool = True, guides: bool | None = None
                ) -> tuple[R.RenderResult, list[str]]:
    inp, notes = prepare_inputs(store, spec, allow_matting=allow_matting)
    eff = spec
    if spec["background"]["kind"] in ("photo", "ai") and inp.background is None:
        eff = copy.deepcopy(spec)
        eff["background"]["kind"] = "auto"                       # عکس/تصویرِ هوش مصنوعی هنوز نیست ⇒ موقتاً خودکار
    res = R.render(eff, inp, scale=scale, keep_layers=keep_layers, guides=guides)
    return res, notes + res.warnings


def clean(raw) -> dict:
    try:
        return R.clean_spec(raw, STYLES)
    except R.SpecError as exc:
        raise ThumbError(str(exc)) from exc


# ───────────────────────────── پیش‌نمایش

def preview(store, raw_spec) -> dict:
    spec = clean(raw_spec)
    fmt = F.get(spec["format"])
    scale = min(1.0, PREVIEW_WIDTH / fmt.w)
    if not _render_slots.acquire(timeout=25):
        raise ThumbError("سرور هم‌اکنون سرگرمِ ساختنِ چند تامنیل است؛ چند ثانیه بعد دوباره امتحان کنید.")
    try:
        res, warnings = render_spec(store, spec, scale=scale)
    finally:
        _render_slots.release()
    data = R.to_jpeg_bytes(res.image, 82)
    return {"image": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii"), "width": res.size[0], "height": res.size[1],
            "layers": res.layers, "warnings": warnings, "palette": res.palette, "texts": res.texts, "spec": spec}


# ───────────────────────────── نسخه‌های A/B

FONT_ROTATION = ("lalezar", "estedad", "sahel", "vazirmatn")
MOOD_ROTATION = ("vivid", "dark", "warm", "cool", "neon", "light")
#: برای هر حال‌وهوای پایه، سه حال‌وهوای «کاملاً متفاوت». «پرانرژی/گرم/سرد» با رنگِ برند یک پالت می‌سازند و «سینمایی» به «تیره» می‌ماند،
#: پس جایگزین‌ها از شاخه‌های واقعاً جدا (تیره، روشن، نئونی، پرانرژی، لوکس) انتخاب می‌شوند تا نسخه‌های A/B/D/F با چشم هم فرق داشته باشند.
MOOD_ALTS = {
    "vivid": ("dark", "light", "neon"), "warm": ("dark", "light", "neon"), "cool": ("dark", "light", "neon"),
    "dark": ("vivid", "light", "luxury"), "cinema": ("vivid", "light", "neon"), "light": ("dark", "vivid", "neon"),
    "neon": ("vivid", "light", "dark"), "luxury": ("vivid", "light", "neon"),
}


def _font_fa(key: str) -> str:
    return typo.FONT_CHOICES[key][0].split(" — ")[0]


def variation_plan(spec: dict, n: int) -> list[tuple[dict, str]]:
    """نسخهٔ A = همان؛ B = حال‌وهوای دیگر + رنگِ اصلی/دوم جابه‌جا + سوژه آن‌طرف؛ C/E = سبکِ دیگرِ مناسبِ همین قالب؛
    D = فونتِ دیگر + حال‌وهوای سوم؛ F = حال‌وهوای چهارم + فونتِ دیگر.

    هر نسخه دست‌کم یک تغییرِ «درشت» دارد (پالتِ رنگیِ کاملاً دیگر یا سبکِ دیگر)، نه فقط جابه‌جاییِ دو رنگِ نزدیک یا فونتی که شبیهِ قبلی است
    (در چیدمانِ‌های با سوژهٔ وسطی همین‌ها نسخه‌ها را یکی می‌کرد)."""
    n = max(1, min(MAX_VARIANTS, int(n or 1)))
    has2 = bool(spec["subject2"].get("asset"))
    alts = [s for s in hooks.preferred_styles(spec["format"]) if s != spec["style"] and s in STYLES and (not STYLES[s].needs_second or has2)]
    plans: list[tuple[dict, str]] = [(copy.deepcopy(spec), "نسخهٔ اصلی")]

    def derive(**changes):
        sp = copy.deepcopy(spec)
        for path, val in changes.items():
            node = sp
            keys = path.split("__")
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = val
        return sp

    base_var = int(spec["colors"].get("variation") or 0)
    seed = int(spec.get("seed", 1))
    base_mood = spec["colors"].get("mood") or STYLES[spec["style"]].mood
    moods = MOOD_ALTS.get(base_mood, ("dark", "light", "neon"))
    cur = spec["font"] if spec["font"] != typo.AUTO_FONT else STYLES[spec["style"]].font

    def font_after(k: int) -> str:
        i = FONT_ROTATION.index(cur) if cur in FONT_ROTATION else -1
        return FONT_ROTATION[(i + k) % len(FONT_ROTATION)]

    for i in range(1, n):
        if i == 1:
            m = moods[0]
            plans.append((derive(colors__mood=m, colors__variation=base_var + 1, seed=seed + 7),
                          f"حال‌وهوای «{palette.MOOD_FA.get(m, m)}»؛ رنگ‌ها جابه‌جا شد و سوژه آن‌طرف رفت"))
        elif i in (2, 4) and alts:
            alt = alts[(0 if i == 2 else 1) % len(alts)]
            plans.append((derive(style=alt, colors__variation=(0 if i == 2 else 1) + base_var, seed=seed + i), f"سبکِ «{STYLES[alt].title}»"))
        elif i == 3:
            nxt, m = font_after(1), moods[1]
            plans.append((derive(font=nxt, colors__mood=m, colors__variation=base_var + 2, seed=seed + 13),
                          f"فونتِ «{_font_fa(nxt)}» با حال‌وهوای «{palette.MOOD_FA.get(m, m)}»"))
        else:
            nxt, m = font_after(2), moods[2]
            plans.append((derive(font=nxt, colors__mood=m, seed=seed + 19 + i, colors__variation=base_var + i),
                          f"حال‌وهوای «{palette.MOOD_FA.get(m, m)}» با فونتِ «{_font_fa(nxt)}»"))
    return plans


# ───────────────────────────── ساخت و ذخیره

def default_title(spec: dict) -> str:
    t = typo.plain(spec["content"].get("title", ""))
    return (t or STYLES[spec["style"]].title)[:80]


def _write_files(t: Thumbnail, img: Image.Image) -> None:
    fmt = F.get(t.format)
    d = photo.abs_path(t.dir_rel)
    d.mkdir(parents=True, exist_ok=True)
    for old in list(d.glob("final-*")) + list(d.glob("thumb-*")):
        old.unlink(missing_ok=True)
    rev = int(time.time() * 1000)
    png = io.BytesIO()
    img.save(png, "PNG", compress_level=4)
    jpg = R.to_jpeg_bytes(img, 92, fmt.max_kb)
    th = img.copy()
    th.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    tb = R.to_jpeg_bytes(th, 82)
    names = {"png": f"final-{rev}.png", "jpg": f"final-{rev}.jpg", "thumb": f"thumb-{rev}.jpg"}
    ops.save_bytes(d / names["png"], png.getvalue())
    ops.save_bytes(d / names["jpg"], jpg)
    ops.save_bytes(d / names["thumb"], tb)
    t.files = {k: f"{t.dir_rel}/{v}" for k, v in names.items()}
    t.width, t.height = img.size
    t.size_bytes = len(jpg)


def _apply_result(t: Thumbnail, res: R.RenderResult, warnings: list[str], *, extra_notes: dict | None = None) -> None:
    notes = dict(t.notes or {})
    notes.update({"warnings": warnings, "layers": res.layers, "texts": res.texts, "palette": res.palette})
    notes.update(extra_notes or {})
    t.notes = notes


def render_thumbnail(t: Thumbnail, *, user=None) -> Thumbnail:
    """spec ِ ذخیره‌شده ⇒ فایل‌ها. اگر پس‌زمینهٔ هوش مصنوعی خواسته شده و هنوز نیست، کارِ GPU ثبت می‌شود و تامنیل با پس‌زمینهٔ موقت می‌ماند."""
    spec = clean(t.spec)
    bg = spec["background"]
    extra: dict = {}
    wait = False
    if bg["kind"] == "ai" and not bg["asset"]:
        if not bg.get("job"):
            try:
                prompt, info = aibg.resolve_prompt(t.store, text=(t.notes or {}).get("ai_text", ""), preset=(t.notes or {}).get("ai_preset", ""),
                                                   style=spec["style"], colors=brand_kit(t.store)["colors"], prompt_en=(t.notes or {}).get("ai_prompt", ""))
                req = aibg.request(t.store, user or t.created_by, prompt_en=prompt, fmt=spec["format"], seed=spec["seed"] * 7919 + 13,
                                   meta={"thumb": t.pk})
                bg["job"] = req["job"]
                extra["ai"] = {"prompt": prompt, "engine": req.get("engine", ""), "note": info.get("note", "")}
            except aibg.BgError as exc:
                bg["kind"] = "auto"
                extra["ai"] = {"error": str(exc)}
        wait = bool(bg.get("job"))
    t.spec = spec
    t.bg_job = bg.get("job", "") if wait else ""
    res, warnings = render_spec(t.store, spec, scale=1.0)
    if extra.get("ai", {}).get("error"):
        warnings.append(f"پس‌زمینهٔ هوش مصنوعی ممکن نشد: {extra['ai']['error']} (پس‌زمینهٔ خودکار گذاشته شد)")
    _write_files(t, res.image)
    _apply_result(t, res, warnings, extra_notes=extra)
    t.state = Thumbnail.State.WAITING_BG if wait else Thumbnail.State.READY
    t.message = "پس‌زمینهٔ هوش مصنوعی در صفِ سرورِ پردازش است؛ وقتی آماده شد این تامنیل خودکار کامل می‌شود." if wait else ""
    t.asset = None
    t.save()
    if wait:
        kick_poll(t)
        refresh(t)                       # کارِ هم‌ارزِ قبلاً‌تمام‌شده (کَشِ صف) همین حالا کامل می‌شود
        t.refresh_from_db()
    return t


def create(store, user, raw_spec, *, variants: int = 1, title: str = "", ai: dict | None = None) -> list[Thumbnail]:
    """``variants`` نسخهٔ A/B/C… می‌سازد. ``ai`` = {text, preset, prompt_en}: دستورِ پس‌زمینهٔ هوش مصنوعی (فقط وقتی background.kind = ai)."""
    spec = clean(raw_spec)
    if Thumbnail.objects.filter(store=store).count() >= MAX_ITEMS_PER_STORE:
        raise ThumbError(f"تاریخچهٔ تامنیل‌ها پر است ({hooks.fa_digits(MAX_ITEMS_PER_STORE)} مورد)؛ چند مورد را پاک کنید.")
    plans = variation_plan(spec, variants)
    batch = uuid.uuid4().hex[:12]
    made: list[Thumbnail] = []
    if not _render_slots.acquire(timeout=60):
        raise ThumbError("سرور هم‌اکنون سرگرمِ ساختنِ چند تامنیل است؛ چند ثانیه بعد دوباره امتحان کنید.")
    try:
        for i, (sp, note) in enumerate(plans):
            if sp["background"]["kind"] == "ai":
                sp["background"]["job"] = ""
            t = Thumbnail.objects.create(store=store, created_by=user, title=(title or default_title(sp))[:200], format=sp["format"], style=sp["style"],
                                         batch=batch, variant=chr(65 + i), variant_note=note, spec=sp,
                                         notes={"ai_text": (ai or {}).get("text", ""), "ai_preset": (ai or {}).get("preset", ""),
                                                "ai_prompt": (ai or {}).get("prompt_en", "")})
            try:
                render_thumbnail(t, user=user)
            except Exception as exc:  # noqa: BLE001 — یک نسخه نباید بقیه را بخواباند
                logger.exception("thumbs: render of %s failed", t.pk)
                t.state, t.message = Thumbnail.State.FAILED, f"ساخته نشد: {exc}"[:300]
                t.save()
            made.append(t)
    finally:
        _render_slots.release()
    return made


def rerender(t: Thumbnail, patch: dict | None = None, user=None) -> Thumbnail:
    """ویرایشِ یک تامنیل: spec ِ ذخیره‌شده با تغییرهای تازه دوباره ساخته می‌شود (همان رکورد)."""
    spec = copy.deepcopy(t.spec)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(spec.get(k), dict):
            spec[k].update(v)
        else:
            spec[k] = v
    spec = clean(spec)
    t.spec, t.format, t.style = spec, spec["format"], spec["style"]
    if spec["background"]["kind"] != "ai" or spec["background"].get("asset"):
        spec["background"]["job"] = ""
    if not _render_slots.acquire(timeout=60):
        raise ThumbError("سرور هم‌اکنون سرگرمِ ساختنِ چند تامنیل است؛ چند ثانیه بعد دوباره امتحان کنید.")
    try:
        return render_thumbnail(t, user=user)
    finally:
        _render_slots.release()


def delete(t: Thumbnail) -> None:
    shutil.rmtree(photo.abs_path(t.dir_rel), ignore_errors=True)
    t.delete()


# ───────────────────────────── پس‌زمینهٔ هوش مصنوعیِ منتظر

POLL_ONLINE, POLL_OFFLINE, POLL_HOURS = 8, 40, 24


def kick_poll(t: Thumbnail, countdown: int | None = None, started: str | None = None) -> None:
    from django.conf import settings

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return
    from . import tasks

    online = aibg.availability()["online"]
    try:
        tasks.poll_thumb_task.apply_async((t.pk, started or timezone.now().isoformat()), countdown=countdown if countdown is not None else (POLL_ONLINE if online else POLL_OFFLINE))
    except Exception:  # noqa: BLE001 — بروکر نیست: پنل هر بار که باز شود دوباره وارسی می‌کند (refresh)
        logger.warning("thumbs: celery unavailable, thumbnail %s waits for the next panel poll", t.pk)


def refresh(t: Thumbnail) -> bool:
    """تامنیلِ منتظرِ پس‌زمینه را یک گام جلو می‌برد. ⇒ True اگر تمام شد (کامل یا با پیامِ شکست)."""
    if t.state != Thumbnail.State.WAITING_BG or not t.bg_job:
        return t.state != Thumbnail.State.WAITING_BG
    st = aibg.status(t.store, t.bg_job)
    if st is None:
        return _bg_failed(t, "کارِ پس‌زمینه پیدا نشد (شاید از صف پاک شده).")
    if st["state"] == "READY":
        claimed = Thumbnail.objects.filter(pk=t.pk, state=Thumbnail.State.WAITING_BG).update(message="در حالِ ساختِ نسخهٔ نهایی…")
        if not claimed:
            return False
        t.refresh_from_db()
        spec = copy.deepcopy(t.spec)
        spec["background"].update(kind="ai", asset=st["asset"]["id"], job="")
        t.spec = spec
        try:
            render_thumbnail(t)
        except Exception as exc:  # noqa: BLE001
            logger.exception("thumbs: final render after background failed")
            t.state, t.message = Thumbnail.State.FAILED, f"ساخته نشد: {exc}"[:300]
            t.save()
        return True
    if st["state"] in ("FAILED", "CANCELLED"):
        return _bg_failed(t, st.get("error") or st.get("message") or "پس‌زمینه ساخته نشد.")
    msg = st.get("message") or ""
    if msg != t.message:
        Thumbnail.objects.filter(pk=t.pk).update(message=msg[:300])
        t.message = msg[:300]
    return False


def _bg_failed(t: Thumbnail, reason: str) -> bool:
    spec = copy.deepcopy(t.spec)
    spec["background"].update(kind="auto", job="")
    notes = dict(t.notes or {})
    notes["warnings"] = list(notes.get("warnings") or []) + [f"{reason} پس‌زمینهٔ خودکار ماند؛ می‌توانید دوباره «پس‌زمینهٔ هوش مصنوعی» را بزنید."]
    t.spec, t.notes, t.bg_job, t.state, t.message = spec, notes, "", Thumbnail.State.READY, ""
    t.save()
    return True


def nudge_waiting(store) -> None:
    """هر بار که پنل فهرست را می‌خواند: منتظرها را یک گام جلو ببر و زنجیرهٔ poll ِ مرده را دوباره راه بینداز."""
    for t in Thumbnail.objects.filter(store=store, state=Thumbnail.State.WAITING_BG)[:12]:
        try:
            if not refresh(t) and (timezone.now() - t.updated_at).total_seconds() > 120:
                kick_poll(t, countdown=2)
        except Exception:  # noqa: BLE001
            logger.exception("thumbs: nudge of %s failed", t.pk)


# ───────────────────────────── خروجی‌ها

def thumb_dict(t: Thumbnail, *, full: bool = False) -> dict:
    fmt = F.FORMATS.get(t.format)
    files = t.files or {}
    out = {
        "id": t.pk, "title": t.title, "format": t.format, "format_title": fmt.title if fmt else t.format, "style": t.style,
        "style_title": STYLES[t.style].title if t.style in STYLES else t.style, "batch": t.batch, "variant": t.variant, "variant_note": t.variant_note,
        "state": t.state, "state_fa": STATE_FA.get(t.state, t.state), "message": t.message, "width": t.width, "height": t.height,
        "size_kb": round(t.size_bytes / 1024), "created_at": t.created_at, "asset": t.asset_id,
        "urls": {k: photo.media_url(v) for k, v in files.items()}, "warnings": (t.notes or {}).get("warnings", []),
        "bg_job": t.bg_job, "waiting_bg": t.state == Thumbnail.State.WAITING_BG,
    }
    if full:
        out["spec"] = t.spec
        out["layers"] = (t.notes or {}).get("layers", [])
        out["texts"] = (t.notes or {}).get("texts", [])
        out["palette"] = (t.notes or {}).get("palette", {})
        out["ai"] = (t.notes or {}).get("ai", {})
    return out


def history(store, limit: int = 40, before: int | None = None) -> list[Thumbnail]:
    qs = Thumbnail.objects.filter(store=store)
    if before:
        qs = qs.filter(pk__lt=before)
    return list(qs.order_by("-pk")[: max(1, min(100, int(limit)))])


def open_in_editor(t: Thumbnail, user=None) -> PhotoAsset:
    """خروجیِ نهایی ⇒ عکسِ کتابخانهٔ ادیتورِ عکس (برای ریزتنظیم). هر نسخهٔ تازهٔ تامنیل، عکسِ تازه می‌سازد."""
    if t.state == Thumbnail.State.FAILED or not t.files.get("png"):
        raise ThumbError("این تامنیل فایلی ندارد.")
    ref = f"thumb:{t.pk}:{Path(t.files['png']).stem}"
    existing = PhotoAsset.objects.filter(store=t.store, source_ref=ref[:60]).first()
    if existing is not None and photo.abs_path(existing.original).is_file():
        if t.asset_id != existing.pk:
            t.asset = existing
            t.save(update_fields=["asset", "updated_at"])
        return existing
    data = photo.abs_path(t.files["png"]).read_bytes()
    asset = photo._asset_from_bytes(t.store, user or t.created_by, data, title=f"تامنیل — {t.title}"[:200], source_ref=ref[:60])
    t.asset = asset
    t.save(update_fields=["asset", "updated_at"])
    return asset


def layered_file(t: Thumbnail) -> tuple[bytes, list[str]]:
    """«فایل لایه‌دار»: هر لایهٔ طرح (پس‌زمینه، سوژه، متن، تزئین، لوگو…) جدا. ⇒ (بایت‌ها، یادداشت‌ها)."""
    from apps.photoedit import psd

    spec = clean(t.spec)
    notes: list[str] = []
    scale = 1.0
    fmt = F.get(spec["format"])
    if fmt.w * fmt.h > 1_400_000:
        scale = 0.75
        notes.append("برای کم‌ماندنِ حجمِ فایل لایه‌دار با ۷۵٪ اندازه ساخته شد.")
    res, _w = render_spec(t.store, spec, scale=scale, keep_layers=True)
    layers = []
    for k in res.kept:
        img = k["img"]
        bb = img.getchannel("A").getbbox()
        if bb is None:
            continue
        crop = img.crop(bb)
        blend = k["blend"] if k["blend"] in psd.BLEND_KEYS else ("screen" if k["blend"] == "add" else "normal")
        layers.append(psd.PsdLayer(name=k["name"], img=crop, x=k["xy"][0] + bb[0], y=k["xy"][1] + bb[1], opacity=float(k["opacity"]), blend=blend))
    layers = [lay for lay in layers if lay.x + lay.img.width > 0 and lay.y + lay.img.height > 0]
    return psd.write_psd(res.image.size, res.image, layers), notes


def zip_batch(store, batch: str) -> bytes | None:
    items = [t for t in Thumbnail.objects.filter(store=store, batch=batch).order_by("variant") if t.files.get("png")]
    if not items:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for t in items:
            base = f"{t.variant or t.pk}-{t.style}-{t.format}"
            for kind, ext in (("png", "png"), ("jpg", "jpg")):
                p = photo.abs_path(t.files[kind])
                if p.is_file():
                    z.write(p, f"{base}.{ext}")
    return buf.getvalue()


def safe_name(title: str, ext: str) -> str:
    base = re.sub(r"[^\w؀-ۿ\-]+", "-", title or "thumbnail", flags=re.UNICODE).strip("-")[:60] or "thumbnail"
    return f"{base}.{ext}"


# ───────────────────────────── کتابخانهٔ عکس‌ها (همان ادیتورِ عکس)

def library_row(a: PhotoAsset) -> dict:
    return {"id": a.pk, "title": a.title, "thumb": photo.media_url(a.thumb), "url": photo.media_url(a.original), "width": a.width,
            "height": a.height, "has_alpha": a.has_alpha, "source_kind": a.source_kind, "product": a.product_id}


def library(store, limit: int = 80) -> list[dict]:
    return [library_row(a) for a in PhotoAsset.objects.filter(store=store).order_by("-pk")[:limit]]


def products_for_picker(store, limit: int = 60) -> list[dict]:
    from apps.products.models import Product

    out = []
    for p in Product.objects.filter(store=store).prefetch_related("images").order_by("-created_at")[:limit]:
        imgs = [i for i in p.images.all() if photo._field_path(i.image)]
        main = next((i for i in imgs if i.is_main), imgs[0] if imgs else None)
        out.append({"id": p.pk, "name": p.name, "image_ref": f"product_image:{main.pk}" if main else "", "has_price": bool(p.price),
                    "price_text": _price(p)})
    return out


def _price(p) -> str:
    from . import ideation

    return ideation.price_text(p)


# ───────────────────────────── ایده‌ها (تاریخچه)

def save_idea_set(store, user, product, result: dict) -> IdeaSet:
    row = IdeaSet.objects.create(store=store, created_by=user, product=product, topic=result["topic"][:300], format=result["format"], via=result["via"], result=result)
    old = list(IdeaSet.objects.filter(store=store).order_by("-pk").values_list("pk", flat=True)[KEEP_IDEA_SETS:])
    if old:
        IdeaSet.objects.filter(pk__in=old).delete()
    return row


# ───────────────────────────── نمونهٔ سبک‌ها (برای مودبرد و انتخابِ سبک)

SAMPLE_CONTENT = {
    "face_text": {"title": "*۵* اشتباهِ رایج", "subtitle": "قبل از شروع ببینید", "kicker": "نمونه", "badge": "ویژه"},
    "split_ba": {"title": "تفاوت را ببینید", "subtitle": "با یک تغییرِ ساده", "label_a": "بعد", "label_b": "قبل"},
    "number_list": {"number": "۷", "title": "نکته برای *شروع*", "subtitle": "کوتاه و کاربردی", "kicker": "فهرست"},
    "question_hook": {"title": "واقعاً *جواب* می‌دهد؟", "subtitle": "پاسخ را ببینید", "kicker": "پرسش"},
    "minimal_luxury": {"title": "طرحِ *ساده* و باوقار", "subtitle": "کم، ولی درست", "kicker": "ویژه"},
    "cinema_poster": {"title": "عنوانِ *پوستر*", "tagline": "داستانی که باید دید", "subtitle": "به‌زودی", "credits": "کارگردان: نام نمونه | تهیه‌کننده: نام نمونه"},
    "pinterest_collage": {"title": "ایده‌هایی برای *ذخیره‌کردن*", "subtitle": "مجموعهٔ ایده", "kicker": "ایده", "badge": "نو"},
    "product_hero": {"title": "محصولِ *تازه* را ببینید", "subtitle": "کیفیتِ بالا", "kicker": "تازه", "cta": "دیدن و سفارش", "badge": "ویژه"},
    "sticker_outline": {"title": "*شاد* و پُرانرژی", "subtitle": "همین حالا", "kicker": "جدید", "badge": "نو"},
    "neon": {"title": "*شبِ* نئونی", "subtitle": "حالِ‌وهوای تازه", "kicker": "ویژه"},
    "news_bold": {"title": "خبرِ *مهم* امروز", "subtitle": "جزئیات را ببینید", "kicker": "ویژه"},
    "versus": {"title": "کدام *بهتر* است؟", "subtitle": "رویارویی", "label_a": "گزینهٔ الف", "label_b": "گزینهٔ ب"},
    "magazine_cover": {"title": "*ویژه*نامه", "kicker": "شمارهٔ نمونه", "subtitle": "گفت‌وگویی که باید خواند", "tagline": "و چند نکتهٔ کاربردی"},
    "retro_poster": {"title": "جشنِ *بزرگ* بهار", "kicker": "نمونه", "subtitle": "یک شبِ به‌یادماندنی", "tagline": "ورودِ آزاد"},
    "quote_card": {"title": "هر روز یک قدمِ *کوچک*، آخرش یک راهِ بزرگ", "subtitle": "نامِ گوینده", "kicker": "جمله"},
}


def sample_inputs(style: str, brand_colors: list[str] | None = None) -> R.Inputs:
    from . import fixtures

    inp = R.Inputs(brand_colors=list(brand_colors or []), store_name="نمونه")
    sd = STYLES[style]
    if style in ("product_hero", "minimal_luxury"):
        inp.subject, inp.subject_is_cutout = fixtures.product(), True
    elif sd.subject != "none":
        inp.subject, inp.subject_is_cutout = fixtures.person(), True
    if sd.needs_second:
        inp.subject2, inp.subject2_is_cutout = fixtures.person(skin="#d9a577", shirt="#dc2626", mood="sad"), True
    if style == "pinterest_collage":
        inp.extra = [fixtures.scene(seed=5, size=(700, 600)), fixtures.scene(seed=8, size=(700, 600), palette=("#7c3aed", "#fbcfe8", "#facc15"))]
    return inp


def sample_image(style: str, fmt: str, brand_colors: list[str] | None = None, width: int = 560) -> bytes:
    spec = R.clean_spec({"format": fmt, "style": style, "content": SAMPLE_CONTENT.get(style, {"title": "عنوانِ نمونه"}),
                         "colors": {"use_brand": bool(brand_colors)}}, STYLES)
    fm = F.get(fmt)
    res = R.render(spec, sample_inputs(style, brand_colors), scale=min(1.0, width / fm.w))
    return R.to_jpeg_bytes(res.image, 84)
