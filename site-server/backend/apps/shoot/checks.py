"""وارسیِ هر برداشت، همان لحظه: تاری، نور، «محصول دیده می‌شود و وسطِ کادر است؟».

عکس: اندازه‌های ادیتورِ عکس (apps.photoedit.ops.measure: تیزی، صدک‌های روشنایی، سوختگی) + «جعبهٔ سوژه» از
فاصلهٔ رنگِ هر پیکسل با رنگِ میانهٔ لبه‌های کادر. اگر مدلِ بینایی در دسترس باشد، فقط وقتی اندازه‌ها مشکلی
نمی‌بینند از آن هم می‌پرسیم «محصول پیداست؟ زاویه درست است؟» (پاسخِ بد ⇐ پیشنهادِ دوباره‌گرفتن).
ویدیو: مدت، روشنایی و تیزیِ چند فریمِ نمونه (ffmpeg روی سرورِ سایت).
هر مشکل یک جملهٔ فارسیِ قابلِ‌اجراست («گوشی را کمی به راست ببر»)، نه یک عدد.
"""
from __future__ import annotations

import base64
import io
import logging
import math
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

SHARP_BAD = 25.0
SHARP_WARN = 60.0
DARK_P95 = 120
BRIGHT_CLIP = 0.14
CENTER_TOL = 0.2


def _gray_small(img: Image.Image, side: int = 256) -> np.ndarray:
    t = img.convert("RGB")
    t.thumbnail((side, side))
    return np.asarray(t, dtype=np.float32)


def subject_box(img: Image.Image) -> dict:
    """جعبهٔ تقریبیِ محصول: پیکسل‌هایی که رنگشان از رنگِ لبه‌های کادر دور است."""
    a = _gray_small(img)
    h, w = a.shape[:2]
    m = max(2, int(min(h, w) * 0.05))
    border = np.concatenate([a[:m].reshape(-1, 3), a[-m:].reshape(-1, 3), a[:, :m].reshape(-1, 3),
                             a[:, -m:].reshape(-1, 3)])
    med = np.median(border, axis=0)
    dist = np.sqrt(((a - med) ** 2).sum(axis=2))
    bdist = np.sqrt(((border - med) ** 2).sum(axis=1))
    busy = float(np.percentile(bdist, 90))
    thr = max(30.0, busy * 1.6)
    mask = dist > thr
    share = float(mask.mean())
    out = {"reliable": busy < 55, "busy": round(busy, 1), "share": round(share, 3)}
    if share < 0.01:
        return out | {"found": False}
    ys, xs = np.nonzero(mask)
    x0, x1 = (float(v) for v in np.percentile(xs, [3, 97]))
    y0, y1 = (float(v) for v in np.percentile(ys, [3, 97]))
    fill = max(0.0, (x1 - x0) * (y1 - y0) / float(w * h))
    edge = 0.02
    touches = int(x0 / w < edge) + int(x1 / w > 1 - edge) + int(y0 / h < edge) + int(y1 / h > 1 - edge)
    return out | {
        "found": True, "box": [round(x0 / w, 3), round(y0 / h, 3), round(x1 / w, 3), round(y1 / h, 3)],
        "fill": round(fill, 3), "dx": round((x0 + x1) / 2 / w - 0.5, 3), "dy": round((y0 + y1) / 2 / h - 0.5, 3),
        "touches": touches,
    }


def peak_sharpness(g: np.ndarray, grid: int = 8) -> float:
    """تیزیِ «تیزترین بخش‌ها» (صدکِ ۹۰ ِ واریانسِ لاپلاسینِ ۶۴ خانه): عکسِ محصول با پس‌زمینهٔ محو (عمقِ میدانِ کم)
    تار حساب نمی‌شود، ولی عکسی که هیچ جایش تیز نیست می‌شود."""
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    h, w = lap.shape
    bh, bw = max(1, h // grid), max(1, w // grid)
    vals = sorted(float(lap[i * bh:(i + 1) * bh, j * bw:(j + 1) * bw].var())
                  for i in range(grid) for j in range(grid) if lap[i * bh:(i + 1) * bh, j * bw:(j + 1) * bw].size)
    return vals[int(len(vals) * 0.9)] if vals else 0.0


def photo_metrics(img: Image.Image) -> dict:
    from apps.photoedit import ops

    m = ops.measure(img)
    keep = {k: m[k] for k in ("width", "height", "p5", "p50", "p95", "contrast", "clip_hi", "clip_lo", "sharpness",
                               "noise", "cast_rb")}
    _a, g, _alpha = ops._small_gray(img)
    keep["sharp_peak"] = round(peak_sharpness(g), 1)
    keep["subject"] = subject_box(img)
    return keep


def _problem(code: str, message: str, weight: float) -> dict:
    return {"code": code, "message": message, "weight": weight}


def judge_photo(metrics: dict, check: dict | None = None) -> dict:
    """اندازه‌ها + شرطِ قبولِ همان زاویه ⇐ {ok, score, problems}."""
    check = check or {}
    problems = []
    sharp = float(metrics.get("sharp_peak") if metrics.get("sharp_peak") is not None else metrics.get("sharpness") or 0)
    if sharp < SHARP_BAD:
        problems.append(_problem("blurry", "تار شد؛ گوشی را ثابت نگه دار و روی محصول ضربه بزن تا فوکوس شود.", 45))
    elif sharp < SHARP_WARN:
        problems.append(_problem("soft", "کمی نرم/تار است؛ اگر می‌شود یک بارِ دیگر با دستِ ثابت بگیر.", 12))
    p50, p95 = float(metrics.get("p50") or 0), float(metrics.get("p95") or 255)
    # عکسِ «کم‌نور ولی درست» (زمینهٔ تیره، نورِ موضعی) روشنایی‌های بالا دارد؛ عکسِ واقعاً تاریک ندارد
    if p95 < DARK_P95 or (p50 < 30 and p95 < 170) or float(metrics.get("clip_lo") or 0) > 0.35:
        problems.append(_problem("dark", "تاریک است؛ نزدیکِ پنجره برو یا چراغ روشن کن.", 35))
    elif float(metrics.get("clip_hi") or 0) > BRIGHT_CLIP and p50 > 170:
        problems.append(_problem("bright", "بخشی سوخته (سفیدِ بی‌جزئیات)؛ از نورِ مستقیم کمی دور شو.", 25))
    sub = metrics.get("subject") or {}
    if sub.get("reliable") and check.get("centered", True) is not False:
        if not sub.get("found"):
            problems.append(_problem("no_subject", "محصول از زمینه جدا دیده نمی‌شود؛ زمینهٔ ساده‌تر بگذار.", 20))
        else:
            fill = float(sub.get("fill") or 0)
            if fill < float(check.get("min_fill", 0.12)):
                problems.append(_problem("small", "محصول خیلی کوچک افتاده؛ نزدیک‌تر شو.", 25))
            elif fill > float(check.get("max_fill", 0.92)) and sub.get("touches", 0) >= 3:
                problems.append(_problem("cut", "محصول از کادر بیرون زده؛ کمی عقب برو.", 25))
            if check.get("centered", True):
                dx, dy = float(sub.get("dx") or 0), float(sub.get("dy") or 0)
                moves = []
                if dx > CENTER_TOL:
                    moves.append("کمی به راست")
                elif dx < -CENTER_TOL:
                    moves.append("کمی به چپ")
                if dy > CENTER_TOL:
                    moves.append("کمی پایین")
                elif dy < -CENTER_TOL:
                    moves.append("کمی بالا")
                if moves:
                    problems.append(_problem(
                        "off_center", f"محصول وسطِ کادر نیست؛ گوشی را {' و '.join(moves)} ببر.", 15))
    score = 100.0 - sum(p["weight"] for p in problems) + min(10.0, sharp / 40.0)
    hard = {"blurry", "dark", "small", "cut", "no_subject"}
    ok = not any(p["code"] in hard for p in problems)
    return {"ok": ok, "score": round(max(0.0, score), 1), "problems": problems}


# ───────────────────────────── مدلِ بینایی

VISION_TIMEOUT = 30


def vision_check(store, img: Image.Image, *, product_name: str, shot: dict) -> dict | None:
    """«محصول پیداست؟ زاویه درست است؟» از مدلِ بینایی؛ None اگر در دسترس نبود (هیچ خطایی بیرون نمی‌زند)."""
    from django.core.cache import cache

    flag = f"shoot:vision-down:{getattr(store, 'pk', 0)}"
    if cache.get(flag):
        return None
    try:
        from apps.ai.services import _models_for_provider
        from services.ai import gateway
        from services.ai.router import TASK_VISION, models_for

        provider = gateway.vision_provider(store)
        model = _models_for_provider(provider, models_for(TASK_VISION))[0]
        t = img.convert("RGB")
        t.thumbnail((768, 768))
        buf = io.BytesIO()
        t.save(buf, "JPEG", quality=82)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        prompt = (
            f"این عکس باید محصولِ «{product_name}» را از زاویهٔ «{shot.get('title', '')}» نشان دهد. "
            f"دستورِ عکاس: {shot.get('instruction', '')}\n"
            'فقط JSON: {"product_visible": true/false, "centered": true/false, "angle_ok": true/false, '
            '"sharp": true/false, "well_lit": true/false, "problems": ["حداکثر ۲ جملهٔ کوتاهِ فارسی که بگوید چه کند"], '
            '"verdict": "ok" یا "retake"}'
        )
        parsed, _raw = provider.generate_json(model, prompt, images=[b64], timeout=VISION_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.info("shoot: vision check unavailable: %s", exc)
        cache.set(flag, 1, 300)
        return None
    if not isinstance(parsed, dict):
        return None
    probs = [str(p)[:140] for p in (parsed.get("problems") or []) if str(p).strip()][:2]
    return {
        "product_visible": bool(parsed.get("product_visible", True)),
        "centered": bool(parsed.get("centered", True)),
        "angle_ok": bool(parsed.get("angle_ok", True)),
        "verdict": "retake" if str(parsed.get("verdict", "ok")).lower().startswith("re") else "ok",
        "problems": probs,
    }


def merge_vision(result: dict, vision: dict | None) -> dict:
    if not vision:
        return result
    extra, ok = [], result["ok"]
    first = vision["problems"][0] if vision["problems"] else ""
    if not vision["product_visible"]:
        extra.append(_problem("ai_not_visible", first or "هوش مصنوعی محصول را در عکس پیدا نکرد.", 40))
        ok = False
    elif not vision["angle_ok"]:
        extra.append(_problem("ai_angle", first or "زاویه با دستور نمی‌خواند.", 20))
        ok = False
    elif vision["verdict"] == "retake" and first:
        extra.append(_problem("ai_note", first, 8))
    return {"ok": ok, "score": round(max(0.0, result["score"] - sum(p["weight"] for p in extra)), 1),
            "problems": list(result["problems"]) + extra}


def summary(result: dict) -> str:
    if result["ok"] and not result["problems"]:
        return "عالی؛ قبول شد."
    if result["ok"]:
        return "قبول شد، با یک نکته: " + result["problems"][0]["message"]
    return result["problems"][0]["message"] if result["problems"] else "دوباره بگیر."


# ───────────────────────────── ویدیو

def _frame_sharpness(path: Path) -> float:
    return peak_sharpness(np.asarray(Image.open(path).convert("L"), dtype=np.float32), grid=6)


def video_metrics(path, work_dir) -> dict:
    from services.video import qc
    from services.video.ffmpeg import probe_video

    shape = probe_video(path)
    frames = qc.sample_frames(path, Path(work_dir), 6, width=480, prefix="chk")
    lumas, sharps = [], []
    for f in frames:
        try:
            img = Image.open(f)
            img.load()
            lumas.append(qc._luma(img))
            sharps.append(_frame_sharpness(f))
        except Exception:  # noqa: BLE001
            continue
    for f in frames:
        try:
            f.unlink()
        except OSError:
            pass
    sharps.sort()
    return {
        "duration": round(float(shape.get("duration") or 0), 2), "width": shape.get("width"),
        "height": shape.get("height"), "fps": shape.get("fps"), "rotation": shape.get("rotation"),
        "brightness": round(sum(lumas) / len(lumas), 1) if lumas else None,
        "sharpness": round(sharps[len(sharps) // 2], 1) if sharps else None,
        "sharpness_min": round(sharps[0], 1) if sharps else None,
        "frames": len(frames),
    }


def judge_video(metrics: dict, check: dict | None = None) -> dict:
    check = check or {}
    problems = []
    dur = float(metrics.get("duration") or 0)
    need = float(check.get("min_seconds") or 2)
    if dur < need:
        problems.append(_problem("short", f"کوتاه بود ({_fa(round(dur, 1))} ثانیه)؛ دست‌کم {_fa(need)} ثانیه بگیر.", 40))
    b = metrics.get("brightness")
    if b is not None and b < 50:
        problems.append(_problem("dark", "تاریک است؛ نورِ بیشتر لازم است.", 35))
    elif b is not None and b > 215:
        problems.append(_problem("bright", "خیلی روشن است؛ از نورِ مستقیم دور شو.", 20))
    s = metrics.get("sharpness")
    if s is not None and s < 18:
        problems.append(_problem("shaky", "تار یا لرزان است؛ آرام‌تر حرکت کن و گوشی را با دو دست بگیر.", 30))
    elif s is not None and s < 35:
        problems.append(_problem("soft", "کمی نرم است؛ اگر می‌شود آرام‌تر بگیر.", 10))
    if metrics.get("width") and metrics.get("height") and metrics["width"] > metrics["height"]:
        problems.append(_problem("landscape", "افقی گرفتی؛ برای استوری عمودی بهتر است (لبه‌ها بریده می‌شود).", 8))
    score = 100.0 - sum(p["weight"] for p in problems) + min(10.0, (s or 0) / 20.0) - abs(dur - need / 0.7) * 0.5
    ok = not any(p["code"] in ("short", "dark", "shaky") for p in problems)
    return {"ok": ok, "score": round(max(0.0, score), 1), "problems": problems}


def _fa(value) -> str:
    from .plan import fa_num

    return fa_num(value)


def clean_problems(problems: list[dict]) -> list[dict]:
    return [{"code": p["code"], "message": p["message"]} for p in problems]


def is_finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False
