"""«چندزاویه» on the site: the shared math, the Persian texts and the editor project (a multicam sequence).

One camera, several angles. The math (camera operator, crop windows, cut planner, 2.5D moves) lives in `processing/multiangle_core.py` —
the same file the processing node runs — and is loaded from there, so there is exactly one copy of every rule. This module adds what only
the site needs:

* `core()`                 the loaded math module;
* `warning_text(w)`        a structured warning from the engine («upscale_soft», «no_subject» …) -> Persian;
* `build_project(...)`     the editor's project JSON with a **multicam sequence** (the same shape `createMulticam` in
                           frontend/src/features/content/video/manual/ops.ts builds) so «باز کردن در ادیتور» gives the owner the angles as a
                           multicam group with the automatic cuts already placed - he can change any cut with the keys 1-9;
* `plan_real_cameras(...)` the same auto-switch for REAL cameras: the recordings are lined up by sound (multicam.sync) and the cuts are
                           planned from the first recording's pauses.
"""
from __future__ import annotations

import importlib.util
import secrets
import threading
from pathlib import Path

from django.conf import settings

_CORE = None
_LOCK = threading.Lock()


def core_path() -> Path:
    return Path(getattr(settings, "NM_PROCESSING_DIR", "") or Path(settings.BASE_DIR).parent / "processing") / "multiangle_core.py"


def core():
    """The shared math (processing/multiangle_core.py), loaded once."""
    global _CORE
    with _LOCK:
        if _CORE is None:
            path = core_path()
            spec = importlib.util.spec_from_file_location("nm_multiangle_core", path)
            if spec is None or spec.loader is None or not path.is_file():
                raise RuntimeError(f"multiangle_core.py not found at {path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _CORE = mod
    return _CORE


# ------------------------------------------------------------------ Persian texts

ANGLE_FA = {"wide": "نمای باز", "medium": "نمای متوسط", "close": "نمای نزدیک", "two_shot": "دو نفره", "over_shoulder": "از روی شانه"}
ANGLE_HINT_FA = {
    "wide": "کلِ صحنه؛ برای شروع و جای نفس‌گرفتن",
    "medium": "از کمر به بالا؛ برای توضیح دادن",
    "close": "سر و شانه؛ برای تأکید و احساس",
    "two_shot": "دو نفر با هم (نیاز به دو سوژه)",
    "over_shoulder": "از روی شانهٔ نفرِ دوم (نیاز به دو سوژه)",
}
FORMAT_FA = {"source": "هم‌شکلِ فیلمِ اصلی", "reel": "ریلز و استوری ۹:۱۶", "feed": "پستِ عمودی ۴:۵", "square": "مربع ۱:۱", "wide": "افقی ۱۶:۹"}
PACE_FA = {"slow": "آرام (۳ تا ۹ ثانیه)", "medium": "متوسط (۲ تا ۶ ثانیه)", "fast": "تند (۱ تا ۴ ثانیه)"}
RHYTHM_FA = {"auto": "خودکار", "speech": "روی مکثِ گفتار", "beat": "روی ضربِ موسیقی"}
MOVE_FA = {
    "dolly_in": "حرکت به جلو", "dolly_out": "حرکت به عقب", "truck_left": "حرکت به چپ", "truck_right": "حرکت به راست",
    "crane_up": "جرثقیل: بالا رفتن", "crane_down": "جرثقیل: پایین آمدن", "orbit_left": "چرخش دورِ سوژه به چپ",
    "orbit_right": "چرخش دورِ سوژه به راست", "push_parallax": "نزدیک شدن با پارالاکس",
}
MOVE_HINT_FA = {
    "dolly_in": "دوربین به سوژه نزدیک می‌شود؛ پس‌زمینه کمتر از جلو بزرگ می‌شود",
    "dolly_out": "دوربین عقب می‌رود و صحنه باز می‌شود",
    "truck_left": "دوربین به کنار می‌لغزد؛ نزدیک‌ها بیشتر از دورها جابه‌جا می‌شوند",
    "truck_right": "دوربین به کنار می‌لغزد؛ نزدیک‌ها بیشتر از دورها جابه‌جا می‌شوند",
    "crane_up": "دوربین بالا می‌رود و کمی به پایین خم می‌شود",
    "crane_down": "دوربین پایین می‌آید",
    "orbit_left": "دوربین دورِ سوژه می‌چرخد؛ سوژه سرِ جایش می‌ماند و پس‌زمینه می‌لغزد",
    "orbit_right": "دوربین دورِ سوژه می‌چرخد؛ سوژه سرِ جایش می‌ماند و پس‌زمینه می‌لغزد",
    "push_parallax": "نزدیک شدنِ آرام با پارالاکسِ بیشتر",
}
REASON_FA = {"start": "شروع", "pause": "مکثِ گفتار", "sentence": "پایانِ جمله", "beat": "ضربِ موسیقی", "forced": "برشِ اجباری (مکثی نبود)"}
SUBJECT_FA = {"person": "آدم", "face": "چهره", "motion": "حرکتِ صحنه", "center": "مرکزِ تصویر"}
CHECK_FA = {
    "runtime": "محیطِ اجرا (numpy، OpenCV، onnxruntime)", "models": "مدل‌ها (چهره، آدم، عمق)", "virtual.angles": "ساختِ زاویه‌های مجازی",
    "virtual.synced": "هم‌زمانیِ زاویه‌ها (هم‌طول و هم‌فریم)", "virtual.cuts": "برشِ خودکار و فیلمِ مولتی‌کم",
    "virtual.on_sound": "افتادنِ برش‌ها روی مکثِ صدا", "virtual.models_ran": "اجرای مدل‌ها", "move.frames": "حرکتِ دوربینِ ۲٫۵بعدی: تعدادِ فریم‌ها",
    "move.parallax": "حرکتِ دوربینِ ۲٫۵بعدی: تغییرِ واقعیِ نما", "move.depth": "حرکتِ دوربینِ ۲٫۵بعدی: نقشهٔ عمق",
    "virtual.bars": "نوارهای سیاهِ متغیر (فیلمِ ترکیبی): تشخیص در لحظهٔ تغییر",
}


def _fa_num(x, digits=1) -> str:
    s = f"{x:.{digits}f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)
    return s.translate(str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫"))


def warning_text(w: dict) -> str:
    """One structured warning of the engine -> a sentence the owner can act on."""
    code = w.get("code")
    angle = ANGLE_FA.get(w.get("angle") or "", w.get("angle") or "")
    if code == "upscale_hard":
        return (f"«{angle}» از فیلمِ اصلی بیش از حدِ امن بزرگ می‌شود (تا {_fa_num(float(w.get('factor') or 0))} برابر) و نرم و کم‌جزئیات می‌شود؛ "
                "با فیلمِ پرجزئیات‌تر (کیفیتِ بالاتر یا نزدیک‌تر به سوژه) یا بدونِ این زاویه بهتر است.")
    if code == "upscale_soft":
        return f"«{angle}» کمی از فیلمِ اصلی بزرگ می‌شود (حدود {_fa_num(float(w.get('factor') or 0))} برابر)؛ کمی نرم‌تر از زاویه‌های دیگر است."
    if code == "no_subject":
        return ("آدم یا چهره‌ای پیدا نشد؛ دوربین‌ها دنبالِ حرکتِ صحنه و بخشِ برجستهٔ تصویر رفتند. اگر سوژه‌ای هست، فیلم را روشن‌تر "
                "یا سوژه را بزرگ‌تر بگیرید.") if w.get("mode") == "motion" else "سوژه‌ای تشخیص داده نشد؛ مرکزِ تصویر قاب شد."
    if code == "angle_skipped":
        return f"«{angle}» ساخته نشد: " + ("برای این نما دو نفر در تصویر لازم است و فقط یک نفر دیده شد." if w.get("why") == "one_subject" else "شرایطش فراهم نبود.")
    if code == "no_cut_points":
        return "مکثِ مشخصی در صدا پیدا نشد؛ برش‌ها در آرام‌ترین لحظه‌های نزدیک به زمانِ دلخواه افتادند. می‌توانید در ادیتور جابه‌جایشان کنید."
    if code == "too_short":
        return "فیلم کوتاه است؛ برش‌های خودکار کم‌اند."
    if code == "holes_large":
        return "در بعضی فریم‌ها بخشی از پس‌زمینه که قبلاً پشتِ سوژه بود دیده شد و با گسترشِ پس‌زمینه پر شد؛ مقدارِ حرکت را کمتر کنید تا طبیعی‌تر شود."
    if code == "trimmed":
        return f"فقط {_fa_num(float(w.get('seconds') or 0), 0)} ثانیهٔ اولِ فیلم پردازش شد."
    return str(code or "")


def warnings_fa(items) -> list[str]:
    out = []
    for w in items or []:
        if isinstance(w, dict):
            t = warning_text(w)
            if t and t not in out:
                out.append(t)
    return out


# ------------------------------------------------------------------ the editor project (multicam sequence)

def _uid(prefix: str = "c") -> str:
    return prefix + secrets.token_hex(4)


def _media_clip(ref: str, label: str, kind: str, at: float, start: float, end: float, src: float, *, has_audio: bool, audio_on: bool,
                fit: str = "cover") -> dict:
    return {
        "id": _uid(), "type": "media", "ref": ref, "label": label, "kind": kind, "at": round(at, 3), "start": round(start, 3), "end": round(end, 3),
        "src": round(src, 3), "opacity": 1, "x": 0, "y": 0, "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": fit, "fade_in": 0, "fade_out": 0,
        "audio_on": audio_on, "has_audio": has_audio, "effects": [], "transition": None,
    }


def _track(kind: str, name: str, role: str = "", clips=None) -> dict:
    t = {"id": _uid("t"), "kind": kind, "name": name, "muted": False, "locked": False, "clips": list(clips or [])}
    if role:
        t["role"] = role
    return t


def preset_for(width: int, height: int) -> str:
    r = width / float(height or 1)
    for key, ratio in (("reel", 9 / 16), ("feed", 4 / 5), ("square", 1.0), ("wide", 16 / 9)):
        if abs(r - ratio) < 0.03:
            return key
    return "wide" if r >= 1 else "reel"


def build_project(angles: list[dict], cuts: list[dict], duration: float, width: int, height: int, fps: float, *, audio_angle: int = 0) -> dict:
    """The editor's project: a nested multicam sequence (one video track with the cuts, one audio track from `audio_angle`) placed on the
    timeline as one clip.

    `angles` = [{"ref": "video:12", "label": "نمای باز", "duration": s, "has_audio": bool, "offset": s}, ...]. `offset` is where the angle
    starts on the common timeline: 0 for virtual cameras (cut from one recording: synced by construction), the sound-sync offset for real
    recordings. `cuts` = [{"t": seconds, "angle": index into `angles`}] sorted, the first at 0. The project is validated by the same server
    code that renders it (see tests)."""
    if len(angles) < 2:
        raise ValueError("a multicam needs at least two angles")
    offs = [round(float(a.get("offset") or 0.0), 3) for a in angles]
    total = min(float(duration), max(o + float(a["duration"]) for o, a in zip(offs, angles)))
    info_angles = [{"ref": a["ref"], "label": a["label"], "offset": offs[i], "duration": round(float(a["duration"]), 3), "has_audio": bool(a.get("has_audio"))}
                   for i, a in enumerate(angles)]
    clean = []
    for c in sorted(cuts, key=lambda c: c["t"]):
        t = round(float(c["t"]), 3)
        idx = int(c["angle"])
        if not (0 <= t < total) or not (0 <= idx < len(angles)):
            continue
        if clean and clean[-1]["angle"] == idx:
            continue
        if clean and abs(clean[-1]["t"] - t) < 0.05:
            clean[-1] = {"t": t, "angle": idx}
            continue
        clean.append({"t": t, "angle": idx})
    if not clean:
        clean.append({"t": 0.0, "angle": next((i for i, o in enumerate(offs) if o <= 0.001), 0)})
    clean[0]["t"] = 0.0                      # the first shot always starts at 0 (never a duplicate of the same angle in front of it)
    video = []
    for i, cut in enumerate(clean):
        t1 = clean[i + 1]["t"] if i + 1 < len(clean) else total
        a, off = angles[cut["angle"]], offs[cut["angle"]]
        dur = float(a["duration"])
        start, end = max(0.0, cut["t"] - off), min(dur, t1 - off)
        if end - start < 0.05:
            continue
        video.append(_media_clip(a["ref"], a["label"], "video", max(cut["t"], off), start, end, dur, has_audio=bool(a.get("has_audio")), audio_on=False))
    src = angles[audio_angle] if 0 <= audio_angle < len(angles) else angles[0]
    audio = []
    if src.get("has_audio"):
        audio.append(_media_clip(src["ref"], f"{src['label']} (صدا)", "audio", offs[audio_angle], 0, float(src["duration"]), float(src["duration"]), has_audio=True, audio_on=True))
    seq_id = _uid("s")
    fmt = {"width": int(width), "height": int(height), "fps": int(round(fps)), "preset": preset_for(width, height)}
    sequence = {
        "name": "مولتی‌کمِ خودکار",
        "tracks": [_track("video", "زاویه‌ها", clips=video), _track("audio", "صدا", role="speech", clips=audio)],
        "format": dict(fmt),
        "multicam": {"angles": info_angles, "cuts": clean, "audio": audio_angle if src.get("has_audio") else -1},
    }
    nested = _media_clip(f"seq:{seq_id}", "مولتی‌کم", "video", 0, 0, total, total, has_audio=bool(audio), audio_on=True, fit="stretch")
    return {
        "format": fmt,
        "tracks": [
            _track("video", "تصویر ۱", clips=[nested]), _track("video", "تصویر ۲"), _track("text", "متن"),
            _track("audio", "صدا ۱", role="speech"), _track("audio", "موسیقی", role="music"),
        ],
        "global_ops": [], "markers": [], "inout": None,
        "sequences": {seq_id: sequence},
    }


# ------------------------------------------------------------------ the same auto-switch for REAL cameras

def plan_real_cameras(paths: list, durations: list[float], *, pace: str = "medium", seed: int = 7, max_seconds: float = 180.0) -> dict:
    """Several recordings of ONE event: line them up by sound (services/editing/multicam.sync), then plan the cuts from the first
    recording's pauses -> {"offsets", "confidence", "cuts": [{"t","angle"(index)}], "segments", "length"}. `t` is on the common timeline
    (0 = the earliest start). The recordings need not start together; a switch only goes to a camera that is running at that moment."""
    from . import multicam

    mc = core()
    rows = multicam.sync(paths, max_seconds=max_seconds)
    offsets = [r["offset"] for r in rows]
    lo = min(offsets)
    starts = [o - lo for o in offsets]
    ends = [s + float(d) for s, d in zip(starts, durations)]
    length = max(ends)
    base = multicam._audio(paths[0], max_seconds)
    env, hop = mc.energy_db(base, multicam.SR, hop=0.02)
    pauses = mc.pause_boundaries(env, hop)
    pauses = [{**p, "t": round(p["t"] + starts[0], 3)} for p in pauses]
    keys = [f"cam{i}" for i in range(len(paths))]
    plan = mc.plan_edit(length, [{"key": "wide"}, {"key": "medium"}] if len(paths) == 2 else [{"key": k} for k in ("wide", "medium", "close")][: len(paths)], pauses, pace,
                        30.0, None, hop, seed)
    # angle names of the planner are only a rotation order here: map them onto the cameras that are running at that moment
    order = {name: i for i, name in enumerate(sorted({s["angle"] for s in plan["segments"]}, key=lambda n: mc.ANGLES[n]["tier"]))}
    cuts, prev = [], None
    for seg in plan["segments"]:
        want = order[seg["angle"]] % len(paths)
        cam = want
        if not (starts[cam] <= seg["t0"] + 1e-6 < ends[cam]):
            running = [i for i in range(len(paths)) if starts[i] <= seg["t0"] + 1e-6 < ends[i] and i != prev]
            cam = running[0] if running else prev if prev is not None else 0
        if cam != prev:
            cuts.append({"t": seg["t0"], "angle": cam})
            prev = cam
    return {"offsets": [round(s, 3) for s in starts], "confidence": [r["confidence"] for r in rows], "ok": [r["ok"] for r in rows], "cuts": cuts,
            "segments": plan["segments"], "length": round(length, 3), "cameras": keys}
