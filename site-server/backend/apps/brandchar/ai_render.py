"""تصویرِ هوش مصنوعی از روی همین شخصیت (سه‌بعدی‌نما / تصویرسازی / یکی از ۱۱۶ سبک) روی ComfyUI ِ سرورِ پردازش.

همیشه همان راهِ امن: شخصیتِ کدکشیده (استیکرِ ژستِ انتخابی) **مرجع** است؛ گره آن را با FLUX «ویرایشِ تصویر» (img2img) به سبکِ خواسته می‌برد، پس رنگ‌ها و ساختار حفظ می‌شود
(قفلِ هویت). اگر IP-Adapter/PuLID روی گره نصب باشد، گره گزارش می‌دهد (``caps.comfy_nodes``) و صفحه می‌گوید؛ مسیرِ پایه هیچ‌کدام را لازم ندارد.

* کار ``brandchar.render`` در **صفِ ماندگار** می‌رود: گره خاموش باشد، کار می‌ماند و با روشن‌شدنِ گره خودکار انجام می‌شود (بدونِ هیچ کاری از شما).
* شخصیتِ کدکشیده هرگز منتظرِ این نمی‌ماند.
* نتیجه که رسید: پس‌زمینه با «حذفِ رنگِ زمینه» شفاف می‌شود (کارِ CPU روی سایت، بدونِ کارِ دومِ گره)، در کتابخانهٔ ادیتورِ عکس ثبت می‌شود و با برگهٔ قفل‌شده سنجیده می‌شود
  («سنجشِ ثبات»: رنگ‌های امضا و سیلوئت).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging

import numpy as np
from django.utils import timezone
from PIL import Image

from apps.compute import services as C
from apps.compute.models import ComputeJob
from apps.looks import compose as looks_compose
from apps.photoedit import services as photo
from apps.photoedit.models import PhotoAsset

from .engine import doc as D
from .engine import qa as QA
from .models import BrandCharacter, CharacterAIJob

logger = logging.getLogger(__name__)

KIND = "brandchar.render"
MODES = {
    "illustrated": {"fa": "تصویرسازیِ دیجیتال", "positive": "polished 2D digital illustration of a friendly cartoon brand mascot character, clean shapes, consistent design, full body, centered, plain light grey background",
                    "denoise": 0.55},
    "3d": {"fa": "سه‌بعدی‌نما (خمیری/پیکسارگونه)", "positive": "cute stylised 3D rendered cartoon mascot character, soft studio lighting, smooth materials, full body, centered, plain light grey background",
           "denoise": 0.62},
    "look": {"fa": "یکی از سبک‌های کتابخانه", "positive": "cartoon brand mascot character, full body, centered, plain light grey background", "denoise": 0.6},
}
#: نامِ دیگری که برای حالت‌ها می‌نویسند ⇒ کلیدِ درست (نه بی‌صدا «تصویرسازی»)؛ هر چیزِ دیگر خطای ۴۰۰ با فهرستِ کلیدهای مجاز است
MODE_ALIASES = {"three_d": "3d", "threed": "3d", "3-d": "3d", "3d_look": "3d", "illustration": "illustrated", "illustrate": "illustrated", "style": "look", "looks": "look"}


def normalize_mode(mode: str) -> str:
    key = str(mode or "illustrated").strip().lower().replace(" ", "_") or "illustrated"
    key = MODE_ALIASES.get(key, key)
    if key not in MODES:
        raise AIRenderError(f"حالتِ «{str(mode)[:30]}» ناشناخته است؛ حالت‌های مجاز: " + "، ".join(f"{k} ({v['fa']})" for k, v in MODES.items()) + ".")
    return key


def modes_public() -> list[dict]:
    return [{"key": k, "fa": v["fa"], "needs_look": k == "look"} for k, v in MODES.items()]


# نامِ انگلیسیِ لباس و ... برای مدلِ تصویرساز (کلیدِ سند مثلِ «track» به‌تنهایی معنا ندارد: «a teal track» یعنی چه؟)
OUTFIT_EN = {"tshirt": "t-shirt", "tank": "tank top", "hoodie": "hoodie", "jersey": "sports jersey", "suit": "suit jacket over a white shirt", "track": "zip-up track jacket"}
BOTTOMS_EN = {"pants": "trousers", "shorts": "shorts", "joggers": "jogger pants", "skirt": "skirt"}
SHOES_EN = {"sneakers": "sneakers", "boots": "boots", "bare": "bare feet"}
HAIR_EN = {"tuft": "a small tuft of {c} hair", "spikes": "spiky {c} hair", "bob": "{c} bob-cut hair", "ponytail": "{c} hair in a ponytail", "buzz": "buzz-cut {c} hair",
           "short": "short {c} hair", "bun": "{c} hair in a bun", "curly": "curly {c} hair", "long": "long {c} hair"}
HAT_EN = {"cap": "baseball cap", "beanie": "knit beanie", "headband": "headband", "tophat": "top hat", "hood": "hood", "chef": "chef hat"}
EXTRA_EN = {"glasses": "round glasses", "backpack": "backpack", "mask": "face mask", "apron": "apron"}
PROP_EN = {"torch": "torch", "phone": "smartphone", "key": "key", "bat": "bat", "sign": "sign board", "map": "map", "dumbbell": "dumbbell", "barbell": "barbell", "clipboard": "clipboard",
           "bag": "shopping bag", "pan": "frying pan", "box": "parcel box", "tablet": "tablet", "megaphone": "megaphone"}
BASE_NEGATIVE = "text, letters, watermark, logo, signature, extra limbs, deformed hands, blurry, low quality, realistic human face, photo of a real person"
REF_SIZE = 1024
BG = (236, 238, 242)


class AIRenderError(Exception):
    """متنش برای کاربر است."""


def anchor_en(doc: dict) -> str:
    """توصیفِ انگلیسیِ هویتِ شخصیت برای مدلِ تصویرساز (رنگ‌ها از سند)."""
    from apps.mascot.engine import spec as MS

    d = D.normalize(doc)
    cn = MS.colour_name
    hair = HAIR_EN.get(d["hair"], "short {c} hair").format(c=cn(d["hair_colour"])) if d["hair"] != "none" else "no hair"
    bits = [f"a friendly cartoon character with {cn(d['skin'])}-toned skin, {hair}",
            f"wearing a {cn(d['top'])} {OUTFIT_EN.get(d['outfit'], d['outfit'])} and {cn(d['bottom'])} {BOTTOMS_EN.get(d['bottoms'], d['bottoms'])}, "
            + ("barefoot" if d["shoes_type"] == "bare" else SHOES_EN.get(d["shoes_type"], d["shoes_type"]))]
    if d["hat"] != "none":
        bits.append(f"a {cn(d['hat_colour'])} {HAT_EN.get(d['hat'], d['hat'])}")
    if d["extra"] != "none":
        bits.append(EXTRA_EN.get(d["extra"], d["extra"]))
    if d["prop"] != "none":
        bits.append(f"holding a {PROP_EN.get(d['prop'], d['prop'])}")
    return ", ".join(bits)


def build_prompt(doc: dict, mode: str, *, look: str = "", extra: str = "", store=None) -> dict:
    mode = mode if mode in MODES else "illustrated"
    m = MODES[mode]
    positive = m["positive"]
    negative = BASE_NEGATIVE
    hints: dict = {}
    look_fa = ""
    if mode == "look" or look:
        try:
            c = looks_compose.compose(look, "NEW_IMAGE", store, notes="")
        except looks_compose.LookError as exc:
            raise AIRenderError(exc.message_fa) from exc
        positive = f"{c['positive']}, cartoon brand mascot character, full body, centered, plain light grey background"
        negative = f"{c['negative']}, {BASE_NEGATIVE}"
        hints = c["hints"]
        look_fa = c["name_fa"]
    prompt = f"{anchor_en(doc)}. {positive}" + (f", {extra.strip()[:200]}" if extra.strip() else "")
    return {"positive": prompt[:1500], "negative": negative[:800], "hints": hints, "look_fa": look_fa, "denoise": m["denoise"]}


def reference_png(doc: dict, pose: str, expression: str, logo: Image.Image | None) -> bytes:
    """مرجعِ ورودیِ گره: شخصیتِ کدکشیده روی زمینهٔ ساده، مربعِ ۱۰۲۴ (همان زمینه‌ای که در prompt گفته شده)."""
    from . import services as S

    img, _info = S.R.sticker(doc, pose=pose, expression=expression, logo=logo, height_px=REF_SIZE)
    canvas = Image.new("RGB", (REF_SIZE, REF_SIZE), BG)
    img.thumbnail((int(REF_SIZE * 0.9), int(REF_SIZE * 0.92)), Image.LANCZOS)
    canvas.paste(img, ((REF_SIZE - img.width) // 2, (REF_SIZE - img.height) // 2 + 20), img)
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue()


def start(c: BrandCharacter, user, *, mode: str = "illustrated", look: str = "", extra: str = "", pose: str = "stand", expression: str = "happy", seed: int | None = None) -> CharacterAIJob:
    """کار را در صفِ ماندگارِ سرورِ پردازش می‌گذارد. گره خاموش ⇒ همان‌جا می‌ماند (پیامِ «در صف» دارد)."""
    from . import services as S
    from apps.mascot.engine import poses

    if pose not in poses.POSES:
        raise AIRenderError("ژستِ ناشناخته است.")
    if expression not in D.EXPRESSIONS:
        raise AIRenderError("حالتِ چهره ناشناخته است.")
    mode = normalize_mode(mode)
    if mode == "look" and not look:
        raise AIRenderError("برای حالتِ «سبک» یکی از سبک‌ها را انتخاب کنید.")
    p = build_prompt(c.doc, mode, look=look, extra=extra, store=c.store)
    doc = D.normalize(c.doc, name=c.name)
    logo = S.store_logo(c.store) if doc["logo"] == "chest" else None
    ref = reference_png(doc, pose, expression, logo)
    seed = int(seed) if seed is not None else int(hashlib.sha256((str(c.pk) + str(timezone.now().timestamp())).encode()).hexdigest()[:8], 16)
    hints = p["hints"] or {}
    payload = {"prompt": p["positive"], "negative_prompt": p["negative"], "mode": mode, "reference": "reference.png", "identity": "auto", "width": 1024, "height": 1024,
               "steps": int(hints.get("steps") or 22), "guidance": float(hints.get("guidance") or 3.5), "denoise": p["denoise"], "seed": seed,
               "palette": [r["hex"] for r in D.palette(doc)]}
    import os
    import tempfile

    fd, tmp = tempfile.mkstemp(prefix="bc-ref-", suffix=".png")                 # صف فایلِ ورودی را از روی مسیر کپی می‌کند
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(ref)
        job = C.enqueue_durable(KIND, payload, {"reference.png": tmp}, store=c.store, origin="brandchar", priority=90, timeout_s=2400, category="brandchar")
    except C.ComputeUnavailable as exc:
        raise AIRenderError(str(exc)) from exc
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    online = bool(C.online_nodes(C.capability_for(KIND)))
    row = CharacterAIJob.objects.create(character=c, store=c.store, created_by=user, compute_uid=str(job.uid), mode=mode, look=look, prompt=p["positive"], pose=pose,
                                        state=CharacterAIJob.State.QUEUED, character_version=c.version, params={"expression": expression, "extra": extra[:200], "seed": seed, "look_fa": p["look_fa"]},
                                        message="در صفِ سرورِ پردازش" + ("" if online else " — سرورِ پردازش الان خاموش است؛ با روشن‌شدنش خودکار ساخته می‌شود"))
    return row


# ───────────────────────────── پایانِ کار

def _job_of(row: CharacterAIJob) -> ComputeJob | None:
    return ComputeJob.objects.filter(uid=row.compute_uid).first() if row.compute_uid else None


def key_background(img: Image.Image, tol: float = 26.0) -> Image.Image:
    """زمینهٔ تقریباً یک‌رنگِ لبه‌ها را شفاف می‌کند (پرکردنِ سیل از چهار لبه با تلورانس)؛ سایه‌ها و رنگِ مشابهِ داخلِ بدن دست نمی‌خورد."""
    rgb = img.convert("RGB")
    arr = np.asarray(rgb).astype(np.int16)
    h, w, _ = arr.shape
    edge = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    bg = np.median(edge, axis=0)
    close = (np.abs(arr - bg).sum(axis=2) <= tol * 3)
    seen = np.zeros((h, w), bool)
    stack = [(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)] + [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)]
    from collections import deque

    dq = deque((y, x) for y, x in stack if close[y, x])
    for y, x in dq:
        seen[y, x] = True
    while dq:
        y, x = dq.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and close[ny, nx]:
                seen[ny, nx] = True
                dq.append((ny, nx))
    alpha = np.where(seen, 0, 255).astype(np.uint8)
    out = rgb.convert("RGBA")
    a = Image.fromarray(alpha).filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(1.2))
    out.putalpha(a)
    return out


def consistency(doc: dict, ai_img: Image.Image, ref_sticker: Image.Image | None = None) -> dict:
    """سنجشِ ثبات در برابرِ برگهٔ قفل‌شده: (۱) رنگ‌های امضا در تصویرِ هوش مصنوعی (کلیدِ رنگ، با تلورانسِ بیشتر برای تصویرِ نقاشی‌شده)، (۲) هم‌پوشانیِ سیلوئت با شخصیتِ کدکشیده."""
    pal = D.palette(doc)
    layer = ai_img.convert("RGBA")
    rows, total, _fig = QA.colour_shares_loose(layer, pal)
    sig = QA.signature_colours(pal)
    found = [r for r in rows if r["hex"] in {s["hex"] for s in sig} and r["found"]]
    score = round(len(found) / len(sig), 3) if sig else None
    sil = None
    if ref_sticker is not None:
        sil = QA.silhouette_iou(layer, ref_sticker)
    notes = []
    for r in rows:
        if r["hex"] in {s["hex"] for s in sig} and not r["found"]:
            notes.append(f"رنگِ «{r['name'] or r['hex']}» ({r['role']}) در تصویر کم‌رنگ است.")
    if sil is not None and sil < QA.SILHOUETTE_MIN:
        notes.append("شکلِ کلیِ شخصیت با نسخهٔ کدکشیده فرق دارد.")
    ok = (score is None or score >= QA.AI_PALETTE_OK) and (sil is None or sil >= QA.SILHOUETTE_MIN)
    return {"ok": bool(ok), "palette_score": score, "silhouette": sil, "notes": notes, "colours": [{k: r.get(k) for k in ("role", "hex", "name", "found", "share")} for r in rows]}


def refresh(row: CharacterAIJob, user=None) -> CharacterAIJob:
    """وضعیتِ کارِ پردازش را می‌خواند و اگر تمام شده تصویر را ثبت و بررسی می‌کند. هر بار صدا زدنِ آن امن و تکراری‌پذیر است."""
    if row.state in (CharacterAIJob.State.DONE, CharacterAIJob.State.FAILED):
        return row
    job = _job_of(row)
    if job is None:
        row.state, row.error, row.message = CharacterAIJob.State.FAILED, "کارِ پردازش پیدا نشد.", "ناموفق"
        row.save(update_fields=["state", "error", "message", "updated_at"])
        return row
    if job.state == ComputeJob.State.COMPLETED:
        try:
            return _finalize(row, job)
        except Exception as exc:  # noqa: BLE001
            logger.exception("brandchar ai finalize failed")
            row.state, row.error, row.message = CharacterAIJob.State.FAILED, str(exc)[:500], "ثبتِ نتیجه ناموفق بود"
            row.save(update_fields=["state", "error", "message", "updated_at"])
            return row
    if job.state in (ComputeJob.State.FAILED, ComputeJob.State.CANCELLED):
        row.state, row.error, row.message = CharacterAIJob.State.FAILED, (job.error or "لغو شد")[:500], "ناموفق"
        row.save(update_fields=["state", "error", "message", "updated_at"])
        return row
    new_state = CharacterAIJob.State.RUNNING if job.state in (ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING) else CharacterAIJob.State.QUEUED
    msg = job.message or ("در حالِ ساخت روی سرورِ پردازش" if new_state == CharacterAIJob.State.RUNNING else row.message)
    if new_state == CharacterAIJob.State.QUEUED and not C.online_nodes(C.capability_for(KIND)):
        msg = "در صفِ سرورِ پردازش — سرورِ پردازش الان خاموش است؛ با روشن‌شدنش خودکار ساخته می‌شود"
    if (row.state, row.message) != (new_state, msg[:240]):
        row.state, row.message = new_state, msg[:240]
        row.params = {**row.params, "progress": job.progress}
        row.save(update_fields=["state", "message", "params", "updated_at"])
    return row


def _finalize(row: CharacterAIJob, job: ComputeJob) -> CharacterAIJob:
    from . import services as S

    outs = [o for o in (job.result or {}).get("outputs", []) if str(o.get("name", "")).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    if not outs:
        raise AIRenderError("سرورِ پردازش تصویری برنگرداند.")
    path = C.output_path(job, outs[0]["name"])
    img = Image.open(path)
    img.load()
    img = img.convert("RGB")
    c = row.character
    doc = D.normalize(c.doc, name=c.name)
    logo = S.store_logo(c.store) if doc["logo"] == "chest" else None
    ref, _ = S.R.sticker(doc, pose=row.pose or "stand", expression=(row.params or {}).get("expression", "happy"), logo=logo, height_px=700)
    cut = key_background(img)
    check = consistency(doc, cut, ref)
    key = hashlib.sha256((row.compute_uid + "ai").encode()).hexdigest()[:24]
    buf = io.BytesIO()
    img.save(buf, "PNG")
    asset = photo._asset_from_bytes(c.store, row.created_by, buf.getvalue(), title=f"شخصیتِ برند «{c.name}» — {MODES.get(row.mode, {}).get('fa', 'هوش مصنوعی')}", source_ref=f"brandchar:{key}"[:60],
                                    kind=PhotoAsset.Kind.GENERATED)
    buf2 = io.BytesIO()
    cut.save(buf2, "PNG")
    sticker = photo._asset_from_bytes(c.store, row.created_by, buf2.getvalue(), title=f"شخصیتِ برند «{c.name}» — استیکرِ هوش مصنوعی", source_ref=f"brandchar:{key[:-2]}st"[:60],
                                      kind=PhotoAsset.Kind.GENERATED)
    row.asset, row.sticker_asset, row.consistency = asset, sticker, check
    row.state, row.message, row.error = CharacterAIJob.State.DONE, ("آماده" if check["ok"] else "آماده — ولی با شخصیتِ قفل‌شده کاملاً یکی نیست"), ""
    row.save()
    S.log_use(c.store, c, "ai_render", str(asset.pk), {"mode": row.mode, "ok": check["ok"]}, user=row.created_by)
    return row


def job_dict(row: CharacterAIJob) -> dict:
    return {"id": row.pk, "character": row.character_id, "mode": row.mode, "mode_fa": MODES.get(row.mode, {}).get("fa", row.mode), "look": row.look, "look_fa": (row.params or {}).get("look_fa", ""),
            "pose": row.pose, "state": row.state, "state_fa": row.get_state_display(), "message": row.message, "error": row.error, "check": row.consistency, "progress": (row.params or {}).get("progress", 0),
            "asset": photo_asset(row.asset), "sticker": photo_asset(row.sticker_asset), "created_at": row.created_at, "character_version": row.character_version, "compute_uid": row.compute_uid}


def photo_asset(a: PhotoAsset | None) -> dict | None:
    if a is None:
        return None
    return {"id": a.pk, "title": a.title, "thumb": photo.media_url(a.thumb), "url": photo.media_url(a.original), "width": a.width, "height": a.height, "has_alpha": a.has_alpha}


def node_status() -> dict:
    """برای صفحه: سرورِ پردازش روشن است؟ FLUX و ابزارهای قفلِ هویت چه هستند؟"""
    nodes = C.known_nodes(C.capability_for(KIND))
    online = C.online_nodes(C.capability_for(KIND))
    caps = (online[0] if online else (nodes[0] if nodes else None))
    c = (caps.capabilities if caps is not None else {}) or {}
    names = c.get("comfy_nodes") or []
    identity = [k for k, needle in (("ipadapter", "IPAdapter"), ("pulid", "Pulid")) if any(needle.lower() in str(n).lower() for n in names)]
    return {"known": bool(nodes), "online": bool(online), "ready": bool(online) and KIND in (c.get("kinds") or []), "kind_known": KIND in (c.get("kinds") or []),
            "profiles": [p for p in (c.get("comfy_profiles") or []) if "flux" in p], "identity_tools": identity, "agent": c.get("agent") or c.get("agent_version") or "",
            "note": ("سرورِ پردازش روشن است." if online else "سرورِ پردازش الان خاموش است؛ کارها در صف می‌مانند و با روشن‌شدنش خودکار ساخته می‌شوند.")}
