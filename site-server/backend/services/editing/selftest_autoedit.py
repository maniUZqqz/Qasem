"""The acceptance run of the automatic edit's node-dependent parts: what must work the moment the GPU node is online.

Three small REAL jobs, each judged by looking at what comes back — never by the node saying "ok":

* ``render_mix``  a 10-second project (a person speaking 2–6 s, a «music» bed all along, no ducking setting at all, standard loudness) is
                  rendered ON THE NODE.  Pass: the file decodes with the right length; `audioqc` hears no doubled speech / phase
                  trouble / music over the voice; the bed sinks ≥ 8 dB while the person speaks (the default ducking really applied);
                  the loudness is near −14 LUFS.  This is the owner's bug («صداها روی هم می‌افتد») pinned on the real machine.
* ``asr``         a Persian sentence made by the site's own voice is sent to the node's speech recognition.  Pass: words with rising times
                  inside the clip, and at least two of the spoken words found.  (Everything that cuts on word boundaries — silences, retakes,
                  captions — stands on this.)
* ``matte``       a 2-second clip goes through the node's video background remover.  Pass: a grey video of the same size and length comes back.

`run()` does nothing while no node is online and says so (`state == "waiting"`): the caller (the self-test runner, or
``manage.py autoedit_selftest``) simply asks again later.  The pass/fail logic of each check is a pure function of the files
(`check_mix`, `check_words`, `check_matte`) so it is unit-tested here on the site without a node.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

KEY = "autoedit"
TITLE_FA = "تدوینِ خودکار (رندرِ میکس، تشخیصِ گفتار، جداسازیِ پس‌زمینه)"
CHECKS = ("render_mix", "asr", "matte")

SR = 32000
SECONDS = 10.0
#: the person speaks here (seconds of the 10-second sample); the music bed lives at 7 kHz, above the synthetic voice
SPEECH_WINDOW = (3.0, 5.0)
OPEN_WINDOW = (0.4, 1.6)
BED_BAND = (6920.0, 7080.0)
MIN_DIP_DB = 8.0
LUFS_RANGE = (-17.0, -11.0)
PERSIAN_TEXT = "سلام به همه دوستان، امروز می‌خواهیم دربارهٔ تمرین صبحگاهی حرف بزنیم."
EXPECTED_WORDS = ("سلام", "همه", "دوستان", "امروز", "تمرین", "صبحگاهی", "حرف")


# ------------------------------------------------------------------ the sample media (synthetic; nothing of anyone's)


def _speech_like(seconds: float, seed: int = 5, amp: float = 0.3) -> np.ndarray:
    """Syllables of a harmonic source with a wandering pitch through formant resonators (so, like speech, it does not repeat itself)."""
    from scipy import signal

    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    out = np.zeros(n, dtype=np.float64)
    t = 0.0
    while t < seconds - 0.4:
        dur = float(rng.uniform(0.12, 0.34))
        i0, i1 = int(t * SR), min(n, int((t + dur) * SR))
        m = i1 - i0
        if m < 64:
            break
        f0 = rng.uniform(95, 230)
        phase = 2 * np.pi * np.cumsum(f0 * (1 + rng.uniform(-0.25, 0.25) * np.linspace(0, 1, m))) / SR
        src = np.zeros(m)
        for h in range(1, 28):
            if h * f0 * 1.3 > 4200:
                break
            src += np.sin(h * phase + rng.uniform(0, 6.28)) / h
        src += 0.15 * rng.standard_normal(m)
        y = np.zeros(m)
        for fc, bw in ((rng.uniform(300, 800), 90), (rng.uniform(900, 2300), 140), (rng.uniform(2500, 3400), 200)):
            b, a = signal.iirpeak(fc / (SR / 2), fc / bw)
            y += signal.lfilter(b, a, src)
        out[i0:i1] += y * np.hanning(m)
        t += dur + float(rng.uniform(0.02, 0.22))
    out /= (np.max(np.abs(out)) + 1e-9)
    return (out * amp).astype(np.float32)


def _band_noise(lo: float, hi: float, seconds: float, amp: float = 0.3) -> np.ndarray:
    from scipy import signal

    rng = np.random.default_rng(4)
    b, a = signal.butter(4, [lo / (SR / 2), hi / (SR / 2)], btype="band")
    y = signal.lfilter(b, a, rng.standard_normal(int(seconds * SR)))
    return (amp * y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


def _write_wav(path: Path, x: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def _ffmpeg() -> str:
    from services.video.ffmpeg import FFMPEG

    return FFMPEG


def make_media(folder: Path) -> dict:
    """{"speech": mp4 (a picture + the person speaking 3–5 s of 10), "music": wav (the bed)} in `folder`."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    voice = _speech_like(SECONDS)
    voice[: int(SPEECH_WINDOW[0] * SR) - int(0.4 * SR)] = 0
    voice[int(SPEECH_WINDOW[1] * SR) + int(0.4 * SR):] = 0
    wav = _write_wav(folder / "voice.wav", voice)
    mp4 = folder / "speech.mp4"
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x335577:s=320x180:r=12:d={SECONDS}", "-i", str(wav),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(mp4)], check=True, capture_output=True, timeout=120)
    music = _write_wav(folder / "bed.wav", _band_noise(6700, 7300, SECONDS))
    return {"speech": mp4, "music": music}


def mix_project(speech_ref: str = "speech", music_ref: str = "music") -> dict:
    """The sample project: the person on camera + a music track, with NO ducking setting (the default must apply) and the social loudness on."""
    def clip(cid, ref, kind, video):
        return {"id": cid, "type": "media", "ref": ref, "label": ref, "kind": kind, "at": 0, "start": 0, "end": SECONDS, "src": SECONDS, "opacity": 1, "x": 0, "y": 0,
                "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": True, "has_audio": True, "effects": [],
                "transition": None}

    return {"format": {"width": 320, "height": 180, "fps": 12, "preset": "reel"}, "global_ops": [], "master": {"gain_db": 0, "limiter": True, "loudness": {"on": True, "target": -14, "tp": -1}},
            "tracks": [{"id": "v1", "kind": "video", "name": "v", "clips": [clip("c1", speech_ref, "video", True)]},
                       {"id": "a1", "kind": "audio", "name": "موسیقی", "role": "music", "clips": [clip("m1", music_ref, "audio", False)]}]}


def build_timeline(data: dict, media: dict):
    from . import timeline as tl

    files = {"speech": (media["speech"], "video"), "music": (media["music"], "audio")}

    def resolve(ref):
        if ref not in files:
            raise tl.TimelineError(ref)
        path, kind = files[ref]
        return {"path": str(path), "kind": kind, "has_audio": True, "duration": SECONDS, "width": 320, "height": 180}

    return tl.from_project(data, resolve)


# ------------------------------------------------------------------ the pass checks (pure functions of the files)


def _band_db(x: np.ndarray, lo: float, hi: float) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return float(10 * np.log10(float(spec[(f >= lo) & (f <= hi)].sum()) / len(x) + 1e-12))


def _probe(path: Path) -> dict:
    import json

    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL).stdout
        data = json.loads(out or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    streams = data.get("streams") or []
    return {"duration": float((data.get("format") or {}).get("duration") or 0.0), "video": next((s for s in streams if s.get("codec_type") == "video"), None),
            "audio": next((s for s in streams if s.get("codec_type") == "audio"), None)}


def check_mix(path) -> dict:
    """The rendered sample: `{"ok", "checks": [{"key", "ok", "detail"}]}` — the same numbers the unit tests use."""
    from . import audioqc

    path = Path(path)
    rows: list[dict] = []

    def add(key, ok, detail):
        rows.append({"key": key, "ok": bool(ok), "detail": detail})

    info = _probe(path)
    add("file", bool(info.get("video") and info.get("audio")) and abs(info.get("duration", 0) - SECONDS) <= 0.7,
        f"فایل {'سالم است' if info.get('video') and info.get('audio') else 'تصویر یا صدا ندارد'}؛ طول {info.get('duration', 0):.1f} ثانیه (انتظار {SECONDS:.0f})")
    if not info.get("audio"):
        return {"ok": False, "checks": rows}
    qc = audioqc.analyze(path)
    add("no_overlap", qc["clean"], "صدا تمیز است؛ گفتار دوبار شنیده نمی‌شود" if qc["clean"] else "؛ ".join(qc["problems"]))
    x = audioqc.decode(path, sr=SR)
    if len(x) > int(SECONDS * 0.9 * SR):
        quiet = _band_db(x[int(OPEN_WINDOW[0] * SR): int(OPEN_WINDOW[1] * SR)], *BED_BAND)
        loud = _band_db(x[int(SPEECH_WINDOW[0] * SR): int(SPEECH_WINDOW[1] * SR)], *BED_BAND)
        add("ducking", quiet - loud >= MIN_DIP_DB, f"موسیقی زیرِ گفتار {quiet - loud:.1f} دسی‌بل کم شد (حداقل {MIN_DIP_DB:.0f})")
    else:
        add("ducking", False, "صدای خروجی کوتاه‌تر از انتظار است")
    lufs = audioqc.loudness_lufs(path)
    if lufs is not None:
        add("loudness", LUFS_RANGE[0] <= lufs <= LUFS_RANGE[1], f"بلندی {lufs:.1f} LUFS (هدف ۱۴- ± ۳)")
    return {"ok": all(r["ok"] for r in rows), "checks": rows}


def check_words(words: list[dict], seconds: float, expected=None) -> dict:
    """The speech recognition's answer: rising times inside the clip and at least two of the sentence's own words (`expected`: the words of the
    sentence that was spoken; the default is this module's own sample)."""
    rows: list[dict] = []
    clean = [w for w in words or [] if isinstance(w, dict) and "w" in w and "s" in w and "e" in w]
    rising = bool(clean) and all(float(a["s"]) <= float(b["s"]) + 1e-6 for a, b in zip(clean, clean[1:])) and all(0 <= float(w["s"]) <= float(w["e"]) <= seconds + 1.0 for w in clean)
    rows.append({"key": "words", "ok": len(clean) >= 3 and rising, "detail": f"{len(clean)} کلمه با زمان‌بندیِ{' درست' if rising else ' نادرست'}"})
    from .retakes import norm

    heard = {norm(w["w"]) for w in clean}
    hit = [w for w in (expected or EXPECTED_WORDS) if norm(w) in heard]
    rows.append({"key": "right_words", "ok": len(hit) >= 2, "detail": f"{len(hit)} کلمه از جمله درست شنیده شد ({'، '.join(hit[:4])})"})
    return {"ok": all(r["ok"] for r in rows), "checks": rows}


def check_matte(path, size: tuple[int, int], seconds: float) -> dict:
    info = _probe(Path(path))
    video = info.get("video") or {}
    ok = bool(video) and abs(info.get("duration", 0) - seconds) <= 0.8 and abs(int(video.get("width") or 0) - size[0]) <= 8 and abs(int(video.get("height") or 0) - size[1]) <= 8
    return {"ok": ok, "checks": [{"key": "matte", "ok": ok, "detail": f"ماتِ {video.get('width', 0)}×{video.get('height', 0)}، {info.get('duration', 0):.1f} ثانیه"
                                  + ("" if ok else f" (انتظار {size[0]}×{size[1]}، {seconds:.0f} ثانیه)")}]}


# ------------------------------------------------------------------ the three jobs on the node


def _node_online(capability: str) -> str:
    try:
        from apps.compute import services as compute

        nodes = compute.online_nodes(capability)
    except Exception:  # noqa: BLE001
        return ""
    return nodes[0].name if nodes else ""


def run_render_mix(work: Path, *, budget: float = 420.0) -> dict:
    from . import noderender

    media = make_media(work / "mix")
    timeline = build_timeline(mix_project(), media)
    dest = work / "node_mix.mp4"
    t0 = time.monotonic()
    meta = noderender.render_on_node(None, timeline, None, dest, store=None, patient=False, budget=budget, queue_grace=90)
    result = check_mix(dest)
    result["meta"] = {k: meta.get(k) for k in ("node", "encoder", "ffmpeg", "bytes")} | {"seconds": round(time.monotonic() - t0, 1)}
    return result


def run_asr(work: Path) -> dict:
    from . import captions

    try:
        from services.audio import tts

        sample = tts.get_tts_provider("fa").synthesize(PERSIAN_TEXT, work / "fa_sample.wav")
    except Exception as exc:  # noqa: BLE001 — no local voice: the check cannot judge words, which is different from failing
        return {"ok": None, "checks": [{"key": "sample", "ok": None, "detail": f"نمونهٔ گفتار ساخته نشد: {str(exc)[:120]}"}]}
    wav = work / "fa_sample_16k.wav"
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-i", str(sample), "-ar", "16000", "-ac", "1", str(wav)], check=True, capture_output=True, timeout=120)
    seconds = _probe(wav).get("duration", 6.0)
    heard = captions.transcribe_wav(wav, store=None, timeout_s=300)
    result = check_words(heard.get("words") or [], seconds)
    result["meta"] = {"engine": heard.get("engine"), "text": heard.get("text", "")[:120]}
    if heard.get("engine") != "node":
        result["checks"].append({"key": "on_node", "ok": False, "detail": "تشخیصِ گفتار روی سرورِ پردازش انجام نشد"})
        result["ok"] = False
    return result


def run_matte(work: Path, *, seconds: float = 2.0) -> dict:
    from apps.compute import services as compute

    clip = work / "matte_in.mp4"
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x240:r=24:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                   check=True, capture_output=True, timeout=120)
    node = _node_online("ffmpeg")
    job = compute.enqueue("edit.matte", {"video": "clip.mp4", "fps": 12, "duration": seconds, "size": [320, 240]}, {"clip.mp4": clip}, store=None,
                          origin="autoedit-selftest", timeout_s=300, node=node, dedupe=False)
    job = compute.wait(job, 300, patient=False)
    out = compute.output_path(job, "matte.mp4")
    result = check_matte(out, (320, 240), seconds)
    shutil.rmtree(compute.job_root(job), ignore_errors=True)
    return result


def run(only: tuple[str, ...] | list[str] | None = None) -> dict:
    """→ {"key", "state": "passed"|"failed"|"waiting", "ok": True|False|None, "checks": {name: result}, "node"}.  `waiting` = no node online (ask again later)."""
    wanted = [c for c in CHECKS if not only or c in only]
    node = _node_online("ffmpeg")
    if not node:
        return {"key": KEY, "state": "waiting", "ok": None, "node": "", "checks": {}, "message": "سرورِ پردازش روشن نیست؛ با روشن شدنش آزمون خودکار اجرا می‌شود."}
    runners = {"render_mix": run_render_mix, "asr": run_asr, "matte": run_matte}
    results: dict = {}
    with tempfile.TemporaryDirectory(prefix="nm-autoedit-selftest-") as tmp:
        for name in wanted:
            try:
                results[name] = runners[name](Path(tmp))
            except Exception as exc:  # noqa: BLE001 — a check that cannot even run is a failed check, with the reason
                logger.info("autoedit selftest %s: %s", name, exc)
                results[name] = {"ok": False, "checks": [{"key": name, "ok": False, "detail": str(exc)[:200]}]}
    verdicts = [r.get("ok") for r in results.values()]
    ok = False if any(v is False for v in verdicts) else (True if any(v is True for v in verdicts) else None)
    return {"key": KEY, "state": "passed" if ok else ("failed" if ok is False else "waiting"), "ok": ok, "node": node, "checks": results, "message": ""}
