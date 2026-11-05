"""What the director learns about the footage before it plans: shots, silences/speech, beats, a transcript (when speech
recognition is available), faces, and the *best moments*.

Everything is cheap (ffmpeg + numpy/OpenCV on small frames) and cached by the caller through `Ctx` (media_cache already
caches speech spans and beats). Each part is optional: a part that cannot run is reported in `analysis["missing"]` with the
Persian reason, so the owner sees what the edit did NOT know.
"""
from __future__ import annotations

import logging

import numpy as np

from .. import reframe
from .spec import Ctx

logger = logging.getLogger(__name__)

MOMENT_FPS = 2.0
MAX_MOMENT_SECONDS = 180.0


def moment_scores(path, duration: float, size: tuple[int, int] | None = None, *, frames=None) -> list[float]:
    """One 0..1 score per second of the source: how much is HAPPENING and how sharp it looks (motion + detail).
    `frames` (an (n,h,w,3) BGR array at MOMENT_FPS) is injectable for tests."""
    import cv2

    seconds = min(float(duration), MAX_MOMENT_SECONDS)
    if frames is None:
        w, h = size or reframe._probe_size(path)
        frames = reframe._frames(path, 0.0, seconds, MOMENT_FPS, 160, w, h)
    n = len(frames)
    if n < 2:
        return []
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    motion = [0.0] + [float(cv2.absdiff(gray[i], gray[i - 1]).mean()) for i in range(1, n)]
    sharp = [float(cv2.Laplacian(g, cv2.CV_32F).var()) for g in gray]
    per = int(round(MOMENT_FPS))
    secs = int(np.ceil(n / MOMENT_FPS))
    m = np.array([np.mean(motion[i * per:(i + 1) * per] or [0.0]) for i in range(secs)])
    s = np.array([np.mean(sharp[i * per:(i + 1) * per] or [0.0]) for i in range(secs)])

    def norm(a: np.ndarray) -> np.ndarray:
        lo, hi = float(np.percentile(a, 5)), float(np.percentile(a, 95))
        return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)

    score = 0.6 * norm(m) + 0.4 * norm(s)
    return [round(float(x), 3) for x in score]


def best_windows(scores: list[float], length: float, count: int, *, min_gap: float = 0.5, total: float | None = None,
                 spans: list | None = None) -> list[dict]:
    """The `count` best non-overlapping windows of `length` seconds: [{"s","e","score"}], best first.
    Windows that start or end inside a spoken phrase are slid to the phrase edges (never cut a word off)."""
    total = float(total if total is not None else len(scores))
    length = max(0.5, min(length, total))
    if not scores or total <= length + 0.01:
        return [{"s": 0.0, "e": round(total, 3), "score": float(np.mean(scores)) if scores else 0.0}]
    cs = np.concatenate([[0.0], np.cumsum(scores)])

    def mean_at(a: float) -> float:
        i0, i1 = int(a), int(min(len(scores), np.ceil(a + length)))
        return float((cs[i1] - cs[i0]) / max(1, i1 - i0))

    cands = []
    step = 0.5
    a = 0.0
    while a + length <= total + 1e-6:
        cands.append((mean_at(a), a))
        a += step
    cands.sort(reverse=True)
    picked: list[dict] = []
    for score, a in cands:
        s, e = a, a + length
        if spans:
            s, e = snap_to_speech(spans, s, e, total)
        if any(not (e <= p["s"] - min_gap or s >= p["e"] + min_gap) for p in picked):
            continue
        picked.append({"s": round(s, 3), "e": round(e, 3), "score": round(score, 3)})
        if len(picked) >= count:
            break
    return picked


def snap_to_speech(spans: list, s: float, e: float, total: float) -> tuple[float, float]:
    """Move a window's edges out of the middle of a spoken phrase (to just before/after it) — no half-words at a cut."""
    for a, b in spans:
        a, b = float(a), float(b)
        if a < s < b and b - a < 12:
            s = max(0.0, a - 0.05)
        if a < e < b and b - a < 12:
            e = min(total, b + 0.05)
    return s, e


def analyze(assets: list[dict], ctx: Ctx, *, want_words: bool = False, want_moments: bool = True, progress=None) -> dict:
    """assets = describe dicts. Returns {"by_ref": {ref: {...}}, "missing": [Persian reasons], "has_speech": bool, "music_ref": str}."""
    by_ref: dict[str, dict] = {}
    missing: list[str] = []
    asr_failed = ""
    total = max(1, len(assets))
    for i, a in enumerate(assets):
        ref = a["ref"]
        row = {"ref": ref, "kind": a.get("kind"), "title": a.get("title", ""), "duration": float(a.get("duration") or 0), "has_audio": bool(a.get("has_audio")),
               "width": int(a.get("width") or 0), "height": int(a.get("height") or 0), "spans": [], "words": [], "moments": [], "beats": [], "bpm": None}
        if progress:
            progress(i / total, f"بررسیِ «{(a.get('title') or ref)[:24]}»")
        if a.get("kind") == "video":
            if a.get("has_audio"):
                try:
                    row["spans"] = [[float(s), float(e)] for s, e in (ctx.spans(ref) or [])]
                except Exception as exc:  # noqa: BLE001
                    missing.append(f"تشخیصِ گفتارِ «{a.get('title', ref)[:20]}» ممکن نشد.")
                    logger.info("spans(%s) failed: %s", ref, exc)
                speech_len = sum(e - s for s, e in row["spans"])
                if want_words and speech_len >= 2.0 and not asr_failed:
                    try:
                        row["words"] = ctx.words(ref, 0.0, min(row["duration"], 180.0)) or []
                    except Exception as exc:  # noqa: BLE001 — ASR is down/off: remember why, do not retry per clip
                        asr_failed = str(exc)
            if want_moments and row["duration"] > 0.5:
                path = ctx.path_of(ref)
                if path:
                    try:
                        row["moments"] = moment_scores(path, row["duration"], (row["width"], row["height"]) if row["width"] else None)
                    except Exception as exc:  # noqa: BLE001
                        logger.info("moment scores for %s failed: %s", ref, exc)
        elif a.get("kind") == "audio":
            try:
                b = ctx.beats(ref) or {}
                row["beats"] = [float(x) for x in (b.get("beats") or [])]
                row["bpm"] = b.get("bpm")
            except Exception as exc:  # noqa: BLE001
                logger.info("beats(%s) failed: %s", ref, exc)
        by_ref[ref] = row
    if asr_failed:
        missing.append("زیرنویسِ خودکار و پرهیز از بریدنِ وسطِ کلمه به تشخیصِ گفتار نیاز دارد و انجام نشد: " + asr_failed[:160])
    music = next((r["ref"] for r in by_ref.values() if r["kind"] == "audio"), "")
    return {"by_ref": by_ref, "missing": missing, "has_speech": any(sum(e - s for s, e in r["spans"]) >= 2.0 for r in by_ref.values()),
            "has_words": any(r["words"] for r in by_ref.values()), "music_ref": music}


def pick_segments(an: dict, refs: list[str], target: float, shot: tuple[float, float], pace: str, *, chronological: bool = False) -> list[dict]:
    """The shot list: [{"ref","start","end"}] (video) / [{"ref","duration"}] (photo), in play order, summing to ≈ `target`.
    The best-scoring moment among all footage opens the video (the hook); the rest interleave the assets."""
    lo, hi = shot
    seg = {"fast": lo + 0.15 * (hi - lo), "normal": lo + 0.45 * (hi - lo), "slow": lo + 0.8 * (hi - lo)}.get(pace, (lo + hi) / 2)
    seg = max(1.0, seg)
    count = max(2, int(round(target / seg)))
    pools: dict[str, list[dict]] = {}
    for ref in refs:
        row = an["by_ref"].get(ref)
        if not row or row["kind"] == "audio":
            continue
        if row["kind"] == "image":
            pools[ref] = [{"ref": ref, "duration": round(min(seg + 0.4, 3.2), 2), "score": 0.4}]
            continue
        dur = row["duration"] or seg
        if dur <= seg + 0.25:
            pools[ref] = [{"ref": ref, "start": 0.0, "end": round(dur, 3), "score": 0.5}]
            continue
        n_here = max(1, min(count, int(dur // (seg + 0.3))))
        wins = best_windows(row["moments"], seg, n_here, total=dur, spans=row["spans"]) if row["moments"] else _even_windows(dur, seg, n_here)
        pools[ref] = [{"ref": ref, "start": w["s"], "end": w["e"], "score": w["score"]} for w in wins]
    flat = [s for pool in pools.values() for s in pool]
    if not flat:
        return []
    if chronological:                                         # unboxing: the owner's order is the story
        out = []
        for pool in pools.values():
            out += sorted(pool, key=lambda s: s.get("start", 0))
        return [{k: v for k, v in s.items() if k != "score"} for s in out[:max(count, len(pools))]]
    hook = max(flat, key=lambda s: s["score"])
    order = [hook]
    rest = {ref: [s for s in pool if s is not hook] for ref, pool in pools.items()}
    for ref in rest:                                           # inside an asset: chronological
        rest[ref].sort(key=lambda s: s.get("start", 0))
    while len(order) < count and any(rest.values()):
        for ref in list(rest):
            if rest[ref] and len(order) < count:
                order.append(rest[ref].pop(0))
    return [{k: v for k, v in s.items() if k != "score"} for s in order]


def _even_windows(dur: float, seg: float, n: int) -> list[dict]:
    if n <= 1:
        return [{"s": 0.0, "e": round(min(dur, seg), 3), "score": 0.5}]
    gap = (dur - seg) / (n - 1)
    return [{"s": round(i * gap, 3), "e": round(i * gap + seg, 3), "score": 0.5} for i in range(n)]
