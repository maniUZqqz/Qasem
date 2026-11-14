"""پس‌زمینهٔ هوش مصنوعی برای تامنیل: FLUX روی کارتِ گرافیکِ سرورِ پردازش (ComfyUI)، از همان مسیرِ «پرکردنِ هوشمند».

هیچ نوعِ کارِ تازه‌ای در عاملِ گره لازم نیست: کارِ عمومیِ ``comfy.graph`` (گرافِ API ِ ComfyUI در ``payload.graph``) همین را اجرا می‌کند.
گراف از «توانایی‌های گره» (``ComputeNode.capabilities["comfy_models"]``) ساخته می‌شود؛ مدلِ FLUX dev ِ مالک (چک‌پوینتِ fp8 یا UNET + CLIP + VAE)
بدونِ دانلودِ تازه. کار در «صفِ ماندگار» می‌نشیند: گره خاموش بود، کار گم نمی‌شود و وقتی روشن شد خودش انجام می‌شود.

* دستور انگلیسی است (FLUX فارسی نمی‌فهمد و متن نمی‌کشد؛ متنِ فارسیِ تامنیل را همیشه سرور با Pillow می‌کشد).
  دستورِ آماده برای هر سبک/صحنه هست، پس بدونِ هیچ مترجمی هم کار می‌کند؛ توضیحِ فارسیِ آزاد با ``photoedit.translate`` ترجمه می‌شود
  و اگر مترجم نبود با دستورِ آماده می‌سازیم و به کاربر می‌گوییم.
* نتیجه یک ``PhotoAsset`` (کتابخانهٔ ادیتورِ عکس) می‌شود که تامنیل‌ساز به‌عنوانِ پس‌زمینه می‌خواندش.
"""
from __future__ import annotations

import logging
import os
import random
from pathlib import Path

from django.utils import timezone

from apps.photoedit import inpaint_graph as ig
from apps.photoedit import services as photo
from apps.photoedit.designer import colorx
from apps.photoedit.models import PhotoAsset

from . import hooks

logger = logging.getLogger(__name__)

ORIGIN = "thumbbg"
JOB_KIND = "comfy.graph"
PRIORITY = 100
TIMEOUT_S = 1500
MAX_ACTIVE = 6
FILENAME_PREFIX = "nm/thumbbg"
GUIDANCE = 3.5
STEPS = 24

#: اندازهٔ خروجیِ مدل برای هر قالب (مضربِ ۱۶، حدودِ یک مگاپیکسل)؛ بعد با cover به قالب می‌نشیند
SIZES = {
    "youtube": (1344, 768), "aparat": (1344, 768), "telegram": (1344, 768),
    "ig_portrait": (896, 1120), "ig_square": (1024, 1024), "story": (768, 1344),
    "pinterest": (832, 1248), "poster": (832, 1248),
}

#: صحنه‌های آماده (انتخابِ سریع در پنل؛ همه انگلیسی و بی‌متن)
PRESETS = {
    "studio_light": ("استودیوی روشن", "bright photography studio backdrop with soft diffused light and a smooth colour gradient"),
    "neon_city": ("شهرِ نئونی", "rainy cyberpunk city street at night with neon reflections and bokeh, dark purple and cyan glow"),
    "cinematic_fog": ("مهِ سینمایی", "cinematic atmospheric fog with volumetric light beams, teal and orange colour grading, dramatic"),
    "pastel_paper": ("کاغذِ پاستلی", "soft pastel paper texture with gentle natural window shadows, flat lay, warm cream tones"),
    "gym_blur": ("باشگاهِ محو", "modern gym interior with equipment, strongly blurred background, shallow depth of field, warm light"),
    "nature_bokeh": ("طبیعتِ محو", "sunlit green nature scene with creamy bokeh, shallow depth of field, fresh and bright"),
    "luxury_dark": ("تیرهٔ لوکس", "luxury dark backdrop with soft golden bokeh highlights and a smooth vignette, elegant"),
    "pop_confetti": ("پاپِ شاد", "playful pop-art background with confetti shapes and flat bright colours, cheerful, high saturation"),
    "tech_gradient": ("گرادیانِ فناوری", "abstract futuristic technology background with glowing lines and a deep blue gradient, clean"),
    "kitchen_warm": ("آشپزخانهٔ گرم", "cozy warm kitchen counter scene softly blurred, golden light, inviting food photography backdrop"),
}


class BgError(Exception):
    """متنش برای کاربر است."""


# ───────────────────────────── گره و مدل

def _nodes():
    from apps.compute.models import ComputeNode

    return [n for n in ComputeNode.objects.filter(enabled=True) if n.has("comfyui")]


def node_caps() -> dict:
    """توانایی‌های گرهٔ ComfyUI ِ مناسب (آنلاین‌ها اول)؛ بدونِ گزارش ⇒ {} (چکِ نامِ پیش‌فرضِ مالک)."""
    from apps.compute import services as compute

    rows = _nodes()
    try:
        online = {n.pk for n in compute.online_nodes("comfyui")}
    except Exception:  # noqa: BLE001
        online = set()
    rows.sort(key=lambda n: n.pk not in online)
    for n in rows:
        caps = n.capabilities or {}
        if isinstance(caps.get("comfy_models"), dict) and caps["comfy_models"]:
            return caps
    return {}


def txt2img_choice(caps) -> dict:
    """مدلِ FLUX dev از روی توانایی‌های گره (مدلِ Fill برای متن‌به‌تصویر مناسب نیست و کنار می‌رود)."""
    caps = dict(caps or {})
    cm = caps.get("comfy_models")
    if isinstance(cm, dict):
        cm = dict(cm)
        for key in ("checkpoints", "unet"):
            if isinstance(cm.get(key), list):
                cm[key] = [n for n in cm[key] if not ig.is_fill(n)]
        caps["comfy_models"] = cm
    choice = ig.choose(caps)
    if choice["kind"] != "dev":
        raise ig.GraphError("روی سرورِ پردازش فقط مدلِ FLUX Fill هست و برای ساختنِ پس‌زمینه مدلِ FLUX dev لازم است.")
    return choice


def build_graph(choice: dict, prompt: str, seed: int, size: tuple[int, int], *, steps: int | None = None,
                prefix: str = FILENAME_PREFIX) -> dict:
    """گرافِ API ِ ComfyUI برای متن‌به‌تصویرِ FLUX (فقط نودهای هستهٔ ComfyUI)."""
    g: dict = {}
    if choice["loader"] == "checkpoint":
        g["10"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": choice["ckpt"]}}
        model, clip, vae = ["10", 0], ["10", 1], ["10", 2]
    else:
        g["10"] = {"class_type": "UNETLoader", "inputs": {"unet_name": choice["unet"], "weight_dtype": choice.get("weight_dtype") or "default"}}
        g["11"] = {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": choice["t5"], "clip_name2": choice["clip_l"], "type": "flux"}}
        g["12"] = {"class_type": "VAELoader", "inputs": {"vae_name": choice["vae"]}}
        model, clip, vae = ["10", 0], ["11", 0], ["12", 0]
    w, h = int(size[0]), int(size[1])
    g["20"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": prompt}}
    g["21"] = {"class_type": "FluxGuidance", "inputs": {"conditioning": ["20", 0], "guidance": GUIDANCE}}
    g["22"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": ""}}
    g["23"] = {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
    g["24"] = {"class_type": "KSampler", "inputs": {
        "model": model, "positive": ["21", 0], "negative": ["22", 0], "latent_image": ["23", 0], "seed": int(seed),
        "steps": int(steps or STEPS), "cfg": 1.0, "sampler_name": choice.get("sampler") or "euler",
        "scheduler": choice.get("scheduler") or "simple", "denoise": 1.0}}
    g["25"] = {"class_type": "VAEDecode", "inputs": {"samples": ["24", 0], "vae": vae}}
    g["26"] = {"class_type": "SaveImage", "inputs": {"images": ["25", 0], "filename_prefix": prefix}}
    return g


def required_nodes(choice: dict) -> list[str]:
    return sorted({n["class_type"] for n in build_graph(choice, "x", 0, (512, 512)).values()})


def availability() -> dict:
    """برای پنل: ساختنِ پس‌زمینه با هوش مصنوعی ممکن است؟ (گره خاموش هم ممکن است؛ کار در صف می‌ماند)"""
    from apps.compute import services as compute

    known = _nodes()
    try:
        online = bool(compute.online_nodes("comfyui"))
    except Exception:  # noqa: BLE001
        online = False
    if not known:
        return {"possible": False, "online": False, "model": "", "message": "هیچ سرورِ پردازشِ دارای ComfyUI ثبت نیست؛ با START.bat روی کامپیوترِ گرافیکی یک بار ثبتش کنید."}
    try:
        choice = txt2img_choice(node_caps())
        label = choice["label"]
    except ig.GraphError as exc:
        return {"possible": False, "online": online, "model": "", "message": str(exc)}
    msg = "سرورِ پردازش آماده است." if online else "سرورِ پردازش خاموش است؛ درخواست در صف می‌ماند و وقتی روشن شد خودکار ساخته می‌شود."
    return {"possible": True, "online": online, "model": label, "message": msg}


def availability_with_selftest() -> dict:
    """``availability()`` + نتیجهٔ آزمونِ خودکارِ GPU (برای پنل)."""
    from . import selftest

    out = availability()
    try:
        out["selftest"] = selftest.status()
    except Exception:  # noqa: BLE001 — نمایشِ آزمون نباید پنل را بخواباند
        out["selftest"] = {"state": "none", "message": ""}
    return out


# ───────────────────────────── دستور

def color_words(colors: list[str]) -> str:
    """رنگ‌های برند ⇒ «deep teal and navy blue» (برای دستورِ انگلیسی)."""
    names: list[str] = []
    for c in colors[:2]:
        if not colorx.is_hex(c):
            continue
        h, s, l = colorx.to_hsl(c)
        if s < 0.12:
            base = "white" if l > 0.8 else "grey" if l > 0.25 else "black"
        else:
            base = next(n for lim, n in ((15, "red"), (40, "orange"), (68, "yellow"), (160, "green"), (195, "teal"), (255, "blue"),
                                         (290, "purple"), (335, "pink"), (361, "red")) if h < lim)
        tone = "light " if l > 0.7 else "deep " if l < 0.3 else ""
        names.append(tone + base)
    return " and ".join(dict.fromkeys(names))


def resolve_prompt(store, *, text: str = "", preset: str = "", style: str = "", colors: list[str] | None = None, prompt_en: str = "") -> tuple[str, dict]:
    """⇒ (دستورِ انگلیسیِ نهایی، {note, translated, preset, style}). ``prompt_en`` اگر داده شود (ایدهٔ هوش مصنوعی/کاربر) همان به کار می‌رود."""
    info = {"note": "", "translated": False, "preset": preset or "", "style": style or ""}
    base = ""
    if prompt_en and hooks.ASCII_PROMPT.match(prompt_en):
        base = prompt_en.strip()
    elif preset in PRESETS:
        base = PRESETS[preset][1]
    elif text and text.strip():
        from apps.photoedit import translate

        try:
            tr = translate.translate(text, store=store)
            base = tr.en
            info["translated"] = tr.source != "none"
        except (translate.Unavailable, translate.Failed) as exc:
            info["note"] = hooks.fit_text("توضیحِ فارسیِ شما ترجمه نشد (%s). به‌جایش پس‌زمینهٔ آمادهٔ سبک ساخته شد. "
                                          "وقتی مترجمِ هوش مصنوعی برگشت، همین توضیح ترجمه می‌شود." % hooks.friendly_reason(exc, 90), 300)
        except Exception as exc:  # noqa: BLE001
            info["note"] = hooks.fit_text("ترجمهٔ توضیح انجام نشد (%s). پس‌زمینهٔ آمادهٔ سبک ساخته شد." % hooks.friendly_reason(translate.explain(exc), 90), 300)
    if not base:
        base = hooks.BG_PROMPTS.get(style) or hooks.BG_PROMPTS["face_text"]
        if not info["note"] and not text and not preset:
            info["note"] = ""
    words = color_words(colors or [])
    out = base.rstrip(" .,") + (f", colour palette of {words}" if words and "colour palette" not in base else "")
    if "no text" not in out.lower():
        out += hooks.BG_SUFFIX
    return out[:700], info


# ───────────────────────────── درخواست و وضعیت

def _active_count(store) -> int:
    from apps.compute.models import ComputeJob

    return ComputeJob.objects.filter(origin=ORIGIN, store=store, state__in=(ComputeJob.State.QUEUED, ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING)).count()


def request(store, user, *, prompt_en: str, fmt: str, seed: int | None = None, meta: dict | None = None) -> dict:
    """یک پس‌زمینه در صفِ سرورِ پردازش. ⇒ {job, state, message, engine, size}. BgError با متنِ فارسی اگر ممکن نبود."""
    from apps.compute import services as compute

    if _active_count(store) >= MAX_ACTIVE:
        raise BgError(f"هم‌اکنون {hooks.fa_digits(MAX_ACTIVE)} پس‌زمینه در صف یا در حالِ ساخت است؛ صبر کنید تمام شوند یا یکی را لغو کنید.")
    size = SIZES.get(fmt) or SIZES["youtube"]
    if not _nodes():
        raise BgError("هیچ سرورِ پردازشِ دارای ComfyUI ثبت نیست؛ با START.bat روی کامپیوترِ گرافیکی یک بار ثبتش کنید.")
    try:
        choice = txt2img_choice(node_caps())
    except ig.GraphError as exc:
        raise BgError(str(exc)) from exc
    seed = random.randint(1, 2**31 - 1) if seed is None else int(seed)
    graph = build_graph(choice, prompt_en, seed, size)
    caps = node_caps()
    missing = ig.check_nodes(graph, caps.get("comfy_nodes"))
    if missing:
        raise BgError("روی سرورِ پردازش این نودهای ComfyUI نصب نیست: " + "، ".join(missing))
    payload = {"graph": graph, "uploads": [], "x_thumbbg": {"prompt": prompt_en, "seed": seed, "format": fmt, "size": list(size),
                                                              "user": getattr(user, "pk", None), "engine": choice["label"], **(meta or {})}}
    try:
        job = compute.enqueue_durable(JOB_KIND, payload, {}, store=store, origin=ORIGIN, priority=PRIORITY, timeout_s=TIMEOUT_S)
    except compute.ComputeUnavailable as exc:
        raise BgError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("thumbs.aibg: enqueue failed")
        raise BgError(f"ثبت در صفِ سرورِ پردازش نشد: {exc}") from exc
    online = availability()["online"]
    return {"job": str(job.uid), "state": photo._job_state(job), "message": "در صفِ سرورِ پردازش" if online else photo.WAIT_NODE,
            "engine": choice["label"], "size": list(size), "seed": seed}


def _error_text(raw: str) -> str:
    low = (raw or "").lower()
    if "not in list" in low:
        why = "نامِ مدل یا فایلِ لازم (چک‌پوینت/CLIP/VAE) روی سرورِ پردازش پیدا نشد."
    elif "out of memory" in low or "oom" in low.split():
        why = "حافظهٔ کارتِ گرافیک کم آمد."
    elif "missing_node_type" in low:
        why = "یکی از نودهای لازمِ ComfyUI نصب نیست."
    elif "unavailable" in low or "refused" in low or "10061" in low:
        why = "ComfyUI روی سرورِ پردازش پاسخ نداد."
    else:
        why = "ساختنِ تصویر روی سرورِ پردازش ناموفق بود."
    return f"پس‌زمینهٔ هوش مصنوعی ساخته نشد: {why}" + (f" (جزئیات: {raw[:240]})" if raw else "")


def finalize(store, job) -> PhotoAsset | None:
    """خروجیِ گره ⇒ عکسِ کتابخانه. تکرارپذیر (بارِ دوم همان عکس)؛ None = هم‌زمان کسِ دیگری می‌سازد."""
    import time

    from django.contrib.auth import get_user_model

    ref = f"thumbbg:{job.uid}"
    existing = PhotoAsset.objects.filter(store=store, source_ref=ref).first()
    if existing is not None:
        return existing
    folder = photo.abs_path(f"photoedit/s{store.pk}") / "thumbbg"
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / f"{str(job.uid)[:12]}.lock"
    if not photo._take_lock(lock):
        for _ in range(40):
            time.sleep(0.25)
            existing = PhotoAsset.objects.filter(store=store, source_ref=ref).first()
            if existing is not None:
                return existing
        return None
    try:
        existing = PhotoAsset.objects.filter(store=store, source_ref=ref).first()
        if existing is not None:
            return existing
        _meta, src = photo._image_output(job)
        if src is None or not Path(src).is_file():
            raise BgError("سرورِ پردازش عکسی پس نفرستاد.")
        meta = (job.payload or {}).get("x_thumbbg") or {}
        user = get_user_model().objects.filter(pk=meta.get("user")).first() if meta.get("user") else None
        return photo._asset_from_bytes(store, user, Path(src).read_bytes(), title="پس‌زمینهٔ هوش مصنوعی", source_ref=ref)
    finally:
        lock.unlink(missing_ok=True)


def job_for(store, uid):
    return photo._job_for(store, uid, ORIGIN)


def status(store, uid) -> dict | None:
    """وضعیتِ یک پس‌زمینه؛ وقتی گره تمام کرد ⇒ همین‌جا عکسِ کتابخانه ساخته می‌شود (فقط یک بار)."""
    job = job_for(store, uid)
    if job is None:
        return None
    state = photo._job_state(job)
    online = availability()["online"]
    node = job.node.name if job.node_id else None
    out = {"job": str(job.uid), "state": state, "message": "", "progress": round(float(job.progress or 0), 3), "node": node, "online": online}
    meta = (job.payload or {}).get("x_thumbbg") or {}
    out["prompt"] = meta.get("prompt", "")
    if state == "QUEUED":
        out.update(message=photo.queued_message(job, online), progress=max(out["progress"], 0.02))
    elif state == "RUNNING":
        out["message"] = f"روی «{node or 'سرورِ پردازش'}» در حالِ ساختن…"
    elif state == "FAILED":
        out.update(message="ناموفق", error=_error_text(job.error))
    elif state == "CANCELLED":
        out["message"] = "لغو شد"
    elif state == "COMPLETED":
        try:
            asset = finalize(store, job)
        except (BgError, photo.PhotoError) as exc:
            out.update(state="FAILED", message="ناموفق", error=str(exc))
            return out
        except Exception as exc:  # noqa: BLE001
            logger.exception("thumbs.aibg: finalize of %s failed", job.uid)
            out.update(state="FAILED", message="ناموفق", error=f"خطای داخلی: {exc}")
            return out
        if asset is None:
            out.update(state="RUNNING", message="در حالِ ذخیرهٔ تصویر…")
            return out
        took = (job.finished_at - job.claimed_at).total_seconds() if (job.finished_at and job.claimed_at) else None
        out.update(state="READY", message="آماده", progress=1.0, asset=photo.asset_dict(asset), seconds=round(took, 1) if took is not None else None)
    return out


def cancel(store, uid) -> bool:
    return photo.exact_cancel(store, uid, ORIGIN)


# ───────────────────────────── آزمون‌ها

def finish_for_test(job, node=None, *, size=None, error: str = "", flat: bool = False):
    """آزمون/توسعه: نقشِ گرهٔ ComfyUI را بازی می‌کند: کار را برمی‌دارد، یک گرادیانِ رنگی با اندازهٔ خواسته می‌سازد و مثلِ عامل تمامش می‌کند."""
    import numpy as np
    from PIL import Image

    from apps.compute import services as compute
    from apps.compute.models import ComputeNode

    node = node or ComputeNode.objects.filter(enabled=True).first() or ComputeNode.objects.create(
        name="gpu-fake", last_seen=timezone.now(), capabilities=fake_caps())
    job.node, job.state, job.attempts = node, job.State.RUNNING, job.attempts + 1
    job.claimed_at = job.heartbeat_at = timezone.now()
    job.save()
    if error:
        return compute.finish(job, node, False, error=error, meta={"retryable": False})
    meta = (job.payload or {}).get("x_thumbbg") or {}
    w, h = size or tuple(meta.get("size") or (512, 512))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if flat:
        arr = np.full((h, w, 3), 128, dtype=np.uint8)
    else:
        arr = np.stack([60 + 150 * xx / w, 40 + 120 * yy / h, 160 - 90 * xx / w], axis=2).clip(0, 255).astype(np.uint8)
    name = "thumbbg_00001_.png"
    Image.fromarray(arr).save(compute.output_path(job, name), "PNG")
    return compute.finish(job, node, True, meta={"primary": name, "engine": "comfyui"})


def fake_caps() -> dict:
    choice = ig.choose({"comfy_models": {"checkpoints": [ig.DEFAULT_DEV_CKPT], "unet": []}})
    return {"comfyui": True, "comfy_nodes": sorted(set(required_nodes(choice)) | {"KSampler"}),
            "comfy_models": {"checkpoints": [ig.DEFAULT_DEV_CKPT], "unet": []}}
