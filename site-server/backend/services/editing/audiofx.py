"""The sound half of a timeline: per-clip chains, a mixer (track gain / pan / mute / solo / buses), auto-ducking and the
master.

Clip chain, in order: source (fast-seeked) → trim/speed (or ramp segments) → reverse → EQ preset / enhance / denoise /
compressor / loudness → gain (static or keyframed) → fades (+ the half-transition dip) → pan → stereo → `adelay` to its
place. A track mixes its clips (`amix`, no normalisation: six clips must not come back quieter than one), applies its
gain and pan, then goes to a bus (speech / music / other). **Ducking is computed from speech spans, not by sidechain
compression**: the spans of the speech tracks (silence detection on their sources, cached) become a gain curve for the
music bus — `1 - (1 - g) * max(envelope_i)` with a pre-roll (attack) and a tail (release) — so the browser preview can
draw exactly the same curve. The master is a gain and a limiter.
"""
from __future__ import annotations

import logging

from .timeline import Clip, Track, _atempo, _f

logger = logging.getLogger(__name__)

EQ_CHAINS: dict[str, list[str]] = {
    "voice": ["highpass=f=80", "equalizer=f=200:t=q:w=1:g=-2", "equalizer=f=3000:t=q:w=1:g=3", "equalizer=f=6000:t=q:w=1.5:g=1.5"],
    "bright": ["highpass=f=60", "equalizer=f=9000:t=q:w=1:g=4"],
    "warm": ["equalizer=f=150:t=q:w=1:g=3", "equalizer=f=6500:t=q:w=1:g=-3"],
    "phone": ["highpass=f=300", "lowpass=f=3400"],
    "bass_cut": ["highpass=f=120"],
    "bass_boost": ["equalizer=f=90:t=q:w=1:g=6"],
    "deess": ["equalizer=f=7000:t=q:w=2:g=-5"],
}
EQ_TITLES = {"flat": "بدون تغییر", "voice": "گفتار (واضح)", "bright": "روشن", "warm": "گرم", "phone": "تلفنی",
             "bass_cut": "حذفِ بم", "bass_boost": "بم‌دار", "deess": "کاهش «س»"}

MAX_DUCK_SPANS = 40


def carries(track: Track, clip) -> bool:
    if getattr(clip, "kind", "") == "text":
        return False
    if track.kind == "audio":
        return True
    return track.kind == "video" and clip.kind == "video" and clip.has_audio and not clip.freeze


def pan_gains(pan: float) -> tuple[float, float]:
    return (1.0 if pan <= 0 else 1.0 - pan), (1.0 if pan >= 0 else 1.0 + pan)


def _pan_filters(pan: float) -> list[str]:
    gl, gr = pan_gains(pan)
    return ["aformat=channel_layouts=stereo", f"pan=stereo|c0={gl:.3f}*c0|c1={gr:.3f}*c1"]


def rnn_model():
    """The bundled RNNoise voice model file, or None when it is missing: a neural denoiser keeps a voice natural far better
    than a spectral gate. (The file travels to the processing node like a LUT when the render runs there.)"""
    try:
        from services.audio import engines as engine_registry

        model = engine_registry.rnnoise_model("sh")
        return model if model.exists() else None
    except Exception:  # noqa: BLE001 — the denoiser is a nicety: never fail a render over it
        return None


def fx_chain(audio: dict, *, rnn: str | None = None) -> list[str]:
    """EQ / enhance / denoise / compressor / loudness for one clip's `audio` block. `rnn` = the ready `arnndn=…` filter
    (built by the graph builder so the model path is portable); without it «حذفِ نویزِ هوشمند» falls back to `afftdn`."""
    out: list[str] = []
    if audio.get("denoise_ai"):
        out.append(rnn or "afftdn=nr=14:nf=-28")
    elif audio.get("denoise"):
        out.append("afftdn=nr=12:nf=-28")
    if audio.get("enhance"):
        out += ["highpass=f=80", "afftdn=nr=10:nf=-30", *EQ_CHAINS["voice"][1:], "acompressor=threshold=0.125:ratio=3:attack=15:release=200:makeup=2"]
    eq = audio.get("eq")
    if eq in EQ_CHAINS and not audio.get("enhance"):
        out += EQ_CHAINS[eq]
    comp = float(audio.get("comp") or 0)
    if comp > 0.01:
        out.append(f"acompressor=threshold={0.25 - 0.2 * comp:.3f}:ratio={2 + 6 * comp:.1f}:attack=20:release=250:makeup={1 + 2 * comp:.2f}")
    if audio.get("normalize"):
        out.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    return out


def clip_audio(b, track: Track, clip: Clip) -> str:
    """One clip's sound as a labelled stream positioned on the timeline."""
    from . import keyframes

    if clip.nested is not None:                # a nested sequence's own mix, built into this graph
        cur = b.nested_audio(clip)
        seek = 0.0
        if cur is None:
            return None
    else:
        idx, seek = b.main_input_for(clip)
        cur = f"{idx}:a"
    segs = clip.segments()
    ch: list[str] = []
    if len(segs) == 1:
        a, e, v = segs[0]
        ch += [f"atrim={a - seek:.3f}:{e - seek:.3f}", "asetpts=PTS-STARTPTS"]
        if abs(v - 1) > 1e-6:
            ch.append(_atempo(v))
    else:
        n = len(segs)
        pads = [b.lab("p") for _ in range(n)]
        b.parts.append(f"[{cur}]asplit={n}" + "".join(f"[{p}]" for p in pads))
        outs = []
        for p, (a, e, v) in zip(pads, segs):
            o = b.lab("q")
            tempo = f",{_atempo(v)}" if abs(v - 1) > 1e-6 else ""
            b.parts.append(f"[{p}]atrim={a - seek:.3f}:{e - seek:.3f},asetpts=PTS-STARTPTS{tempo}[{o}]")
            outs.append(o)
        joined = b.lab("r")
        b.parts.append("".join(f"[{o}]" for o in outs) + f"concat=n={n}:v=0:a=1[{joined}]")
        cur = joined
        ch.append("asetpts=PTS-STARTPTS")
    if clip.reverse:
        ch.append("areverse")
    rnn = None
    if (clip.audio or {}).get("denoise_ai"):
        model = rnn_model()
        if model is not None:
            rnn = f"arnndn=m={b.file_opt(model)}:mix=0.9"
    ch += fx_chain(clip.audio or {}, rnn=rnn)
    # An audio clip's `opacity` is its level (the original, pre-panel meaning); `volume` multiplies it.
    kf_volume = clip.kf.get("volume")
    if kf_volume:
        base = 1.0 if track.kind != "audio" else clip.opacity
        ch.append(f"volume=eval=frame:volume='({keyframes.expr(kf_volume, clip.volume, 't')})*{_f(base)}'")
    else:
        level = clip.volume * (clip.opacity if track.kind == "audio" else 1.0)
        if abs(level - 1.0) > 1e-6:
            ch.append(f"volume={level:.3f}")
    length = clip.length
    fin = max(clip.fade_in, b.audio_fade_in.get(id(clip), 0.0))
    fout = max(clip.fade_out, b.audio_fade_out.get(id(clip), 0.0))
    if fin > 0:
        ch.append(f"afade=t=in:st=0:d={fin:.3f}")
    if fout > 0:
        ch.append(f"afade=t=out:st={max(0.0, length - fout):.3f}:d={fout:.3f}")
    pan = float((clip.audio or {}).get("pan") or 0.0)
    if abs(pan) > 0.01:
        ch += _pan_filters(pan)
    ms = int(clip.at * 1000)
    ch.append(f"adelay={ms}|{ms}")
    out = b.lab("a")
    b.parts.append(f"[{cur}]" + ",".join(ch) + f"[{out}]")
    return out


def _mix(b, labels: list[str], prefix: str) -> str:
    if len(labels) == 1:
        return labels[0]
    out = b.lab(prefix)
    # normalize=0: amix otherwise divides by the input count, so a six-clip timeline came back quieter than any one of its clips.
    b.parts.append("".join(f"[{x}]" for x in labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[{out}]")
    return out


def src_to_timeline(clip: Clip, t: float) -> float:
    """Where a source second of the clip lands on the timeline (speed, ramp and reverse followed)."""
    cum = 0.0
    forward = clip.length
    for a, e, v in clip.segments():
        if t <= e:
            cum += max(0.0, t - a) / v
            break
        cum += (e - a) / v
    else:
        cum = forward
    return clip.at + (forward - cum if clip.reverse else cum)


def _merge_spans(spans: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, e in sorted(spans):
        if out and s - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def duck_spans(b, speech_clips: list[Clip]) -> list[tuple[float, float]]:
    from . import media_cache

    fn = b.spans or media_cache.speech_spans
    found: list[tuple[float, float]] = []
    for clip in speech_clips:
        try:
            spans = fn(clip.source)
        except Exception as exc:  # noqa: BLE001 — a failed analysis must not fail the render
            b.notes.append(f"تشخیصِ گفتار برای کم‌کردنِ صدای موسیقی ممکن نشد: {exc}")
            continue
        for s, e in spans:
            s, e = max(float(s), clip.start), min(float(e), clip.end if clip.end is not None else float(e))
            if e - s < 0.05:
                continue
            x, y = src_to_timeline(clip, s), src_to_timeline(clip, e)
            found.append((min(x, y), max(x, y)))
    gap = 0.6
    merged = _merge_spans(found, gap)
    while len(merged) > MAX_DUCK_SPANS and gap < 30:
        gap *= 2
        merged = _merge_spans(merged, gap)
    return merged


def duck_gain_expr(spans: list[tuple[float, float]], amount_db: float, attack_s: float, release_s: float) -> str:
    """The volume expression of the music bus: 1 - (1 - g) * max over spans of the span's envelope."""
    g = 10 ** (-float(amount_db) / 20.0)
    atk, rel = max(0.005, attack_s), max(0.05, release_s)
    env = [f"min(clip((t-({s:.3f}-{atk:.3f}))/{atk:.3f},0,1),clip(({e:.3f}+{rel:.3f}-t)/{rel:.3f},0,1))" for s, e in spans]
    acc = env[-1]
    for item in reversed(env[:-1]):
        acc = f"max({item},{acc})"
    return f"1-{1 - g:.4f}*{acc}"


def duck_gain_at(spans: list[tuple[float, float]], amount_db: float, attack_s: float, release_s: float, t: float) -> float:
    """The same curve evaluated in Python (the browser mirrors this)."""
    g = 10 ** (-float(amount_db) / 20.0)
    atk, rel = max(0.005, attack_s), max(0.05, release_s)
    env = 0.0
    for s, e in spans:
        up = min(1.0, max(0.0, (t - (s - atk)) / atk))
        down = min(1.0, max(0.0, (e + rel - t) / rel))
        env = max(env, min(up, down))
    return 1 - (1 - g) * env


def build_audio(b, final: str = "aout") -> bool:
    """Append the audio part of the graph to the builder; True when there is a `[final]` (default `[aout]`)."""
    tl = b.tl
    soloing = any(t.solo for t in tl.tracks if t.kind != "text")
    buses: dict[str, list[str]] = {"speech": [], "music": [], "other": []}
    speech_clips: list[Clip] = []
    for track in tl.tracks:
        if track.kind == "text" or track.muted or (soloing and not track.solo):
            continue
        labels = []
        for clip in track.clips:
            if not carries(track, clip):
                continue
            made = clip_audio(b, track, clip)
            if made is None:
                continue
            labels.append(made)
            if track.role == "speech":
                speech_clips.append(clip)
        if not labels:
            continue
        lab = _mix(b, labels, "t")
        post = []
        if abs(track.gain_db) > 0.01:
            post.append(f"volume={track.gain_db:.2f}dB")
        if abs(track.pan) > 0.01:
            post += _pan_filters(track.pan)
        if post:
            out = b.lab("g")
            b.parts.append(f"[{lab}]" + ",".join(post) + f"[{out}]")
            lab = out
        buses[track.role if track.role in ("speech", "music") else "other"].append(lab)

    duck = tl.ducking or {}
    if duck.get("on") and buses["music"] and speech_clips:
        spans = duck_spans(b, speech_clips)
        if spans:
            music = _mix(b, buses["music"], "m")
            out = b.lab("d")
            expr = duck_gain_expr(spans, duck.get("amount_db", 12.0), duck.get("attack_ms", 40.0) / 1000.0,
                                  duck.get("release_ms", 500.0) / 1000.0)
            b.parts.append(f"[{music}]volume=eval=frame:volume='{expr}'[{out}]")
            buses["music"] = [out]
        else:
            b.notes.append("گفتاری برای کم‌کردنِ صدای موسیقی پیدا نشد.")

    every = buses["speech"] + buses["music"] + buses["other"]
    if not every:
        return False
    mixed = _mix(b, every, "z")
    tail = []
    master = tl.master or {}
    if abs(master.get("gain_db", 0.0)) > 0.01:
        tail.append(f"volume={float(master['gain_db']):.2f}dB")
    loud = master.get("loudness") or {}
    if loud.get("on"):
        # one-pass EBU R128 (dynamic) toward the social-media target; loudnorm works at 192 kHz inside, so come back to 48 k
        tp = float(loud.get("tp", -1.0))
        tail.append(f"loudnorm=I={float(loud.get('target', -14.0)):g}:TP={tp:g}:LRA=11")
        tail.append("aresample=48000")
        # the final limiter holds the true-peak ceiling the owner asked for: 0.3 dB under it for the AAC encoder's overshoot, and with
        # `level=disabled` (alimiter's auto-level would lift the peaks back up to the limit: measured −0.5 dBTP with the old 0.95)
        if master.get("limiter", True):
            tail.append(f"alimiter=limit={10 ** ((tp - 0.3) / 20):.3f}:level=disabled")
    elif master.get("limiter", True):
        tail.append("alimiter=limit=0.95")
    b.parts.append(f"[{mixed}]" + (",".join(tail) if tail else "anull") + f"[{final}]")
    return True
