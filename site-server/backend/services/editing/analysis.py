"""The eye. §9 — «بینایی ماشین = چشم (می‌بیند چه خبر است)».

Everything the model is told about a video is measured here first. That ordering
is the point of §8's table: «بیشتر کارهای تدوین اصلاً هوش مصنوعی نمی‌خواهد — کد
بلد است». Finding where the silences are, how dark the picture is, how much the
camera shakes — these are arithmetic. Asking a model to watch a video and guess
at them would be slower, cost money, and be less accurate than a histogram.

So the model is never shown the video. It is shown *this*: a short factual
description, and the toolbox. Its whole job is choosing which tool goes where,
which is the one part of editing that needs judgement.

Nothing here raises. A measurement that could not be taken comes back absent,
and an absent measurement means the agent simply does not propose the tool that
would have depended on it — which is the correct behaviour and not an error
worth failing a job over.
"""
from __future__ import annotations

import logging
from pathlib import Path

from services.audio import qc as audio_qc
from services.video import frame_stats
from services.video import qc as video_qc
from services.video.ffmpeg import probe, probe_video

from .edl import Span

logger = logging.getLogger(__name__)

#: A pause shorter than this is punctuation. Removing it makes speech sound
#: spliced together, which is a more noticeable defect than the pause was.
MIN_PAUSE = 0.35

#: Handheld shake: the frame-to-frame jitter left after the smooth (intended)
#: camera path is removed, as a fraction of frame width. Calibrated on
#: synthetic clips — a smooth pan and a tripod shot sit under 0.002, a mild
#: wobble at 0.005, a bad one at 0.02–0.035. Below this, stabilisation costs a
#: two-pass render and a crop for no gain.
SHAKE_LIMIT = 0.006

#: Kept for facts measured before shake existed. Never used to PROPOSE
#: stabilisation any more: frame-to-frame difference half a second apart is
#: subject motion, not shake, and sent every moving shot through vidstab.
SHAKY_DIFF = 9.0

#: Consecutive-frame brightness step that reads as flicker (full-range luma).
FLICKER_DELTA = video_qc.FLICKER_DELTA

#: Neutral-pixel R−B beyond which the picture leans warm or cold.
CAST_DELTA = video_qc.CAST_DELTA


def has_audio(path) -> bool:
    """Whether there is an audio stream at all.

    Asked before anything else, because an absent track and a silent track lead
    to opposite decisions: no track means "do not offer audio tools", while a
    silent track means "something went wrong during recording".
    """
    try:
        info = probe(path)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not probe %s: %s", path, exc)
        return False
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


def silences(path, work_dir, *, min_pause: float = MIN_PAUSE) -> list[Span]:
    """Where nobody is talking. §8: «حذف سکوت‌های طولانی».

    Reuses the narration QC envelope rather than shelling out to ffmpeg's
    `silencedetect`, for one reason that matters: the threshold is relative to
    the clip's own speech level. A fixed dB threshold calls a quietly recorded
    video silent from end to end, and that is precisely the input that produces
    an edit removing the entire video.
    """
    try:
        samples, rate = audio_qc.decode(path, work_dir)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not read audio of %s: %s", path, exc)
        return []
    if not samples:
        return []

    levels = audio_qc._windows(samples, rate)
    if not levels:
        return []
    # Relative to the typical speech level, with hysteresis — see
    # audio.qc.reference_level for the clap that used to silence the talking.
    floor = audio_qc.silence_floor(levels)
    window = audio_qc.WINDOW_MS / 1000
    silent = audio_qc.silence_mask(levels, floor)

    spans, start = [], None
    for index, quiet in enumerate(silent):
        if quiet:
            start = index if start is None else start
        elif start is not None:
            spans.append(Span(start * window, index * window))
            start = None
    if start is not None:
        spans.append(Span(start * window, len(levels) * window))

    return [s for s in spans if s.length >= min_pause]


def speech_spans(path, work_dir) -> list[Span]:
    """The complement of the silences — where the talking actually is."""
    try:
        samples, rate = audio_qc.decode(path, work_dir)
    except Exception:  # noqa: BLE001
        return []
    duration = len(samples) / rate if rate else 0.0
    quiet = silences(path, work_dir, min_pause=0.2)
    spans, cursor = [], 0.0
    for span in quiet:
        if span.start > cursor + 0.05:
            spans.append(Span(cursor, span.start))
        cursor = span.end
    if cursor < duration - 0.05:
        spans.append(Span(cursor, duration))
    return spans


def picture(path, work_dir) -> dict:
    """Brightness, colour and steadiness, from a handful of sampled frames."""
    frames = video_qc.sample_frames(path, Path(work_dir) / "look")
    if len(frames) < 2:
        return {}

    from PIL import Image

    images = []
    for frame in frames:
        try:
            images.append(Image.open(frame).copy())
        except Exception as exc:  # noqa: BLE001 — a bad frame is data
            logger.debug("Could not open %s: %s", frame, exc)
    if len(images) < 2:
        return {}

    lumas = [video_qc._luma(image) for image in images]
    diffs = [
        video_qc._mean_abs_diff(images[i], images[i + 1])
        for i in range(len(images) - 1)
    ]
    reds, greens, blues = zip(*(video_qc._mean_rgb(image) for image in images))
    greys = sum(abs(r - b) for r, b in zip(reds, blues)) / len(reds)
    clipping = sum(video_qc._clipping(image) for image in images) / len(images)

    # Percentiles, because the mean cannot tell a white background from a
    # burnt frame (both average 220) or a black backdrop from an underexposed
    # one — and the "fix" for the misreading makes the picture worse.
    stats = [video_qc.luma_stats(image) for image in images]
    middle = len(stats) // 2

    def median_of(key):
        ordered = sorted(s[key] for s in stats)
        return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2

    # A cast is measured on near-grey pixels only. A frame that has none — a
    # coloured product filling it — has no cast, however far its mean R−B is.
    casts = [c for c in (video_qc.neutral_cast(image) for image in images) if c is not None]
    cast_ok = len(casts) >= max(2, len(images) // 2)
    cast_rb = sum(c["rb"] for c in casts) / len(casts) if cast_ok else None
    neutral_rgb = (
        [round(sum(c["rgb"][i] for c in casts) / len(casts), 1) for i in range(3)]
        if cast_ok else None
    )

    return {
        "brightness": round(sum(lumas) / len(lumas), 1),
        "brightness_swing": round(max(lumas) - min(lumas), 1),
        "motion": round(sum(diffs) / len(diffs), 2),
        # Whole-frame |R−B|, kept for old rows and for display; decisions use
        # `cast_rb`, the neutral-pixel measurement.
        "colour_cast": round(greys, 1),
        "clipped_pixels": round(clipping, 4),
        "frames_sampled": len(images),
        "p5": round(median_of("p5"), 1),
        "p50": round(median_of("p50"), 1),
        "p95": round(median_of("p95"), 1),
        "clip_hi": round(sum(s["clip_hi"] for s in stats) / len(stats), 4),
        "cast_measurable": cast_ok,
        "cast_rb": round(cast_rb, 1) if cast_rb is not None else None,
        "neutral_rgb": neutral_rgb,
    }


#: Scene-change score (ffmpeg scdet, 0–100) above which a frame starts a new
#: shot, and the shortest shot kept on its own (a flash is not a shot).
SHOT_THRESHOLD = 12.0
MIN_SHOT = 1.0
MAX_SHOTS = 8


def shot_boundaries(path, duration: float) -> list[tuple[float, float]]:
    """[(start, end)] of each shot. One shot when there is no cut."""
    import re
    import subprocess

    from services.video.ffmpeg import FFMPEG

    try:
        result = subprocess.run(
            [FFMPEG, "-hide_banner", "-i", str(path), "-an",
             "-vf", f"scale=320:-2,scdet=threshold={SHOT_THRESHOLD}", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
        cuts = sorted(float(t) for t in re.findall(r"lavfi\.scd\.time:\s*([0-9.]+)", result.stderr))
    except Exception as exc:  # noqa: BLE001 — one shot is the safe answer
        logger.info("Shot detection failed for %s: %s", path, exc)
        cuts = []
    edges = [0.0]
    for cut in cuts:
        if cut - edges[-1] >= MIN_SHOT and duration - cut >= MIN_SHOT:
            edges.append(cut)
    edges.append(duration)
    shots = list(zip(edges[:-1], edges[1:]))
    return shots[:MAX_SHOTS]


def shots(path, work_dir, duration: float) -> list[dict]:
    """Exposure and colour of EACH shot — for a phone video that cuts from a
    dim shop floor to a sunlit street. One correction for the whole clip fixes
    one of them and ruins the other; measured per shot, each gets its own.

    Empty when the video is one shot: the whole-clip numbers already say it.
    """
    from PIL import Image

    from services.video.ffmpeg import FFMPEG, _run

    spans = shot_boundaries(path, duration)
    if len(spans) < 2:
        return []
    out = []
    for number, (start, end) in enumerate(spans, start=1):
        stats = window_stats(path, start, end, work_dir, tag=f"shot{number}")
        if stats:
            out.append({"shot": number, "start": round(start, 2), "end": round(end, 2), **stats})
    return out if len(out) >= 2 else []


def window_stats(path, start: float, end: float, work_dir, *, tag: str = "window") -> dict | None:
    """Exposure and neutral-pixel colour of one stretch of a video (3 frames)."""
    from PIL import Image

    from services.video.ffmpeg import FFMPEG, _run

    work = Path(work_dir) / "shots"
    work.mkdir(parents=True, exist_ok=True)
    images = []
    length = end - start
    for k in range(3):
        at = start + length * (k + 1) / 4
        frame = work / f"{tag}_{k}.png"
        try:
            _run([FFMPEG, "-y", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1",
                  "-vf", "scale=256:-2", str(frame)])
            images.append(Image.open(frame).copy())
        except Exception as exc:  # noqa: BLE001
            logger.debug("Frame %s@%.2f failed: %s", path, at, exc)
    if not images:
        return None
    stats = [video_qc.luma_stats(image) for image in images]
    median = lambda key: sorted(s[key] for s in stats)[len(stats) // 2]  # noqa: E731
    casts = [c for c in (video_qc.neutral_cast(image) for image in images) if c is not None]
    cast_ok = len(casts) >= 2
    return {
        "p5": round(median("p5"), 1), "p50": round(median("p50"), 1),
        "p95": round(median("p95"), 1),
        "clip_hi": round(sum(s["clip_hi"] for s in stats) / len(stats), 4),
        "cast_measurable": cast_ok,
        "cast_rb": round(sum(c["rb"] for c in casts) / len(casts), 1) if cast_ok else None,
    }


def _shot_findings(per_shot: list[dict]) -> list[dict]:
    """Findings for the shots that need a correction the others do not.

    Only when the shots DISAGREE: if every shot is dark, the video is dark and
    one whole-clip finding says so (and one correction fixes it).
    """
    if len(per_shot) < 2:
        return []
    out = []
    states = [
        video_qc.exposure_state({k: float(shot.get(k) or 0) for k in ("p5", "p50", "p95", "clip_hi")})
        for shot in per_shot
    ]
    if len(set(states)) > 1:
        for shot, state in zip(per_shot, states):
            where = f"نمای {shot['shot']} (ثانیه‌ی {shot['start']:.1f} تا {shot['end']:.1f})"
            window = [shot["start"], shot["end"]]
            if state in ("dark", "black"):
                out.append({"what": "dark", "note": f"{where} تاریک است", "value": shot["p95"],
                            "window": window, "shot": shot})
            elif state == "blown":
                out.append({"what": "bright", "note": f"{where} سوخته است", "value": shot["p5"],
                            "window": window, "shot": shot})
    casts = [
        (shot, float(shot["cast_rb"])) for shot in per_shot
        if shot.get("cast_measurable") and shot.get("cast_rb") is not None
    ]
    leaning = [(shot, cast) for shot, cast in casts if abs(cast) > CAST_DELTA]
    if leaning and len(leaning) < len(per_shot):
        for shot, cast in leaning:
            where = f"نمای {shot['shot']} (ثانیه‌ی {shot['start']:.1f} تا {shot['end']:.1f})"
            out.append({
                "what": "colour_cast",
                "note": f"رنگ {where} به {'گرمی' if cast > 0 else 'سردی'} زده",
                "value": cast, "window": [shot["start"], shot["end"]], "shot": shot,
            })
    return out


def describe(path, work_dir, *, duration: float | None = None) -> dict:
    """Everything the brain gets to know about this video.

    Deliberately small and factual. A description that editorialises («تصویر
    تاریک است») is already making the decision the model is there to make, and
    when the threshold behind that adjective is wrong nobody can tell.
    """
    from services.video.ffmpeg import probe_duration

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    audio = has_audio(path)

    try:
        total = duration if duration is not None else probe_duration(path)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not measure %s: %s", path, exc)
        return {"readable": False, "reason": str(exc)}

    quiet = silences(path, work) if audio else []
    look = picture(path, work)
    # How far the voice stands above whatever is behind it. The basis of the
    # "حذف نویز" suggestion — a number, not a guess.
    noise = {}
    if audio:
        from services.audio import denoise as denoiser

        noise = denoiser.measure(path, work / "noise")
    # Who is in shot. Gathered here because both the zoom and the subtitle
    # placement need the same answer, and finding it twice costs two passes.
    from services.video import faces

    who = faces.in_video(path, work)

    # The frame's shape, for every filter that has to scale back to it.
    shape: dict = {}
    try:
        shape = probe_video(path)
    except Exception as exc:  # noqa: BLE001 — a zoom is refused later, nothing else needs it
        logger.info("Could not read the shape of %s: %s", path, exc)

    # Between neighbouring frames: flicker and freezes (one ffmpeg pass) and
    # camera shake as distinct from intended motion (a second of frames).
    consecutive = frame_stats.measure(path, work / "stats")
    shake = frame_stats.camera_shake(path)
    per_shot = shots(path, work, total)

    return {
        "readable": True,
        "duration": round(total, 2),
        "has_audio": audio,
        "width": shape.get("width"),
        "height": shape.get("height"),
        "fps": shape.get("fps"),
        "fps_text": shape.get("fps_text"),
        "consecutive_stats": bool(consecutive),
        "flicker": consecutive.get("flicker"),
        "flicker_alternations": consecutive.get("flicker_alternations"),
        "frozen_share": consecutive.get("frozen_share"),
        "longest_freeze": consecutive.get("longest_freeze"),
        "mean_ydif": consecutive.get("mean_ydif"),
        "shake": shake.get("shake"),
        "pan": shake.get("pan"),
        "noise_floor_db": noise.get("noise_floor_db"),
        "speech_db": noise.get("speech_db"),
        "snr_db": noise.get("snr_db"),
        "speech_ratio": noise.get("speech_ratio"),
        "silence_count": len(quiet),
        "silence_seconds": round(sum(s.length for s in quiet), 1),
        "longest_silence": round(max((s.length for s in quiet), default=0.0), 1),
        "silences": [
            {"start": round(s.start, 2), "end": round(s.end, 2)} for s in quiet[:40]
        ],
        "faces": who["faces"],
        "face_boxes": who["boxes"],
        # False means we could not look — a missing OpenCV, an unreadable file.
        # Different from "nobody is there", and the callers treat them
        # differently: one falls back to the default, the other is free rein.
        "faces_checked": who["looked"],
        # Per shot, when the video has cuts; see `shots`.
        "shots": per_shot,
        **look,
    }


# ------------------------------------------------------- what code alone knows


def obvious_problems(facts: dict) -> list[dict]:
    """Findings a threshold can state without any judgement.

    These are offered to the model as observations, not as instructions. It is
    still the model that decides whether a dark video should be brightened —
    sometimes dark is the point — but it should not have to rediscover from raw
    numbers that the picture is dark.
    """
    found = []
    if not facts.get("readable"):
        return found

    # A video with cuts whose shots DISAGREE (one dark, one fine) gets one
    # finding per shot that needs it, each with its time window — a single
    # whole-clip correction would fix one shot and spoil the other. When all
    # shots agree, the whole-clip finding below says it once.
    per_shot = _shot_findings(facts.get("shots") or [])
    exposure_by_shot = any(f["what"] in ("dark", "bright") for f in per_shot)
    cast_by_shot = any(f["what"] == "colour_cast" for f in per_shot)
    found.extend(per_shot)

    # Exposure from percentiles when they were measured; the old mean-luma
    # rule only for rows analysed before percentiles existed.
    if exposure_by_shot:
        pass
    elif facts.get("p95") is not None:
        state = video_qc.exposure_state({
            "p5": float(facts.get("p5") or 0), "p50": float(facts.get("p50") or 0),
            "p95": float(facts.get("p95") or 0), "clip_hi": float(facts.get("clip_hi") or 0),
        })
        if state in ("dark", "black"):
            found.append({
                "what": "dark",
                "note": "تصویر تاریک است" if state == "dark" else "تصویر تقریباً سیاه است",
                "value": facts["p95"],
            })
        elif state == "blown":
            found.append({"what": "bright", "note": "تصویر سوخته است", "value": facts["p5"]})
    else:
        brightness = facts.get("brightness")
        if brightness is not None:
            if brightness < 60:
                found.append({"what": "dark", "note": "تصویر تاریک است", "value": brightness})
            elif brightness > 200:
                found.append({"what": "bright", "note": "تصویر سوخته است", "value": brightness})

    # Flicker between NEIGHBOURING frames when the one-pass statistics exist;
    # the coarse half-second swing only when they do not.
    if facts.get("consecutive_stats"):
        step = float(facts.get("flicker") or 0)
        alternations = int(facts.get("flicker_alternations") or 0)
        if step > FLICKER_DELTA and (alternations >= 2 or step > 2 * FLICKER_DELTA):
            found.append({
                "what": "flicker",
                "note": "روشنایی بین فریم‌های پشت‌سرهم می‌پرد",
                "value": step,
            })
    elif (facts.get("brightness_swing") or 0) > 25:
        found.append({
            "what": "flicker",
            "note": "روشنایی بین فریم‌ها می‌پرد",
            "value": facts["brightness_swing"],
        })

    # A cast only where it can be measured — on neutral pixels. The old
    # whole-frame number called an orange product a "warm cast".
    if cast_by_shot:
        pass
    elif facts.get("cast_measurable"):
        cast = float(facts.get("cast_rb") or 0)
        if abs(cast) > CAST_DELTA:
            found.append({
                "what": "colour_cast",
                "note": "رنگ تصویر به گرمی زده" if cast > 0 else "رنگ تصویر به سردی زده",
                "value": cast,
            })
    elif facts.get("cast_measurable") is None and (facts.get("colour_cast") or 0) > 18:
        found.append({
            "what": "colour_cast",
            "note": "رنگ تصویر به یک سمت زده",
            "value": facts["colour_cast"],
        })

    # Noise behind the voice: audible floor AND close to the speech level.
    if facts.get("has_audio") and facts.get("snr_db") is not None:
        from services.audio import denoise as denoiser
        from services.audio.polish import settings_mix

        mix = settings_mix()
        if getattr(mix, "suggest_denoise", True) and denoiser.is_noisy(
            facts, min_snr_db=float(getattr(mix, "min_snr_db", 30.0)),
        ):
            found.append({
                "what": "noisy",
                "note": (
                    f"صدای زمینه زیاد است — صدای شما فقط {facts['snr_db']:.0f} دسی‌بل "
                    "از نویز بلندتر است"
                ),
                "value": facts["snr_db"],
            })

    # Shake is proposed only when it was actually measured as shake. No
    # measurement (no OpenCV) means no proposal — a needless stabilisation
    # crops the frame and softens it, which is worse than a little wobble.
    if facts.get("shake") is not None and float(facts["shake"]) > SHAKE_LIMIT:
        found.append({
            "what": "shaky",
            "note": "تصویر لرزان است (لرزش دست)",
            "value": round(float(facts["shake"]) * 1000, 1),
        })

    if facts.get("has_audio") and (facts.get("silence_seconds") or 0) > 2:
        found.append({
            "what": "silence",
            "note": (
                f"{facts['silence_count']} سکوت، روی‌هم "
                f"{facts['silence_seconds']:.0f} ثانیه"
            ),
            "value": facts["silence_seconds"],
        })

    # Named as its own finding because the fix is the opposite of the others:
    # nothing to do with filters, everything to do with the recording.
    if facts.get("has_audio") and facts.get("duration") and \
            facts.get("silence_seconds", 0) > facts["duration"] * 0.9:
        found.append({
            "what": "no_speech",
            "note": "تقریباً کل ویدیو ساکت است — احتمالاً میکروفن ضبط نکرده",
            "value": facts["silence_seconds"],
        })

    return found
