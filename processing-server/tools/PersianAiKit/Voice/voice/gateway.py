# سرویسِ صدای PersianAiKit — گفتارِ طبیعی (چند صدا)، کلونِ صدا، صدای هر چیز. راهنما: VOICE-SETUP.md
#
# فقط روی 127.0.0.1؛ درِ ورود برای برنامه‌ها کیت است (/api/voice/*) که کلید، ToSpeakable و گفتار‌به‌متن را انجام می‌دهد.
# وابستگی: numpy، onnxruntime، sentencepiece (+ ai-edge-litert برای صدای هر چیز، ctranslate2 برای ترجمه) — HTTP با کتابخانهٔ استاندارد.
#
#   GET    /health  /engines  /voices  /script
#   GET    /voices/{id}/sample                                 ⇒ WAVِ مرجعِ آن صدا
#   POST   /tts          {"text","voice","engine"?,"seed"?}     ⇒ WAV
#   POST   /sfx          {"prompt","seconds"?,"seed"?,"promptEn"?}   ⇒ WAV (استریو ۴۴٫۱kHz)
#   POST   /sfx/translate {"prompt"}                           ⇒ {"en","method"}
#   POST   /clone        {"name","person","consent":true,"purpose"}   ⇒ صدای تازه
#   POST   /clone/clip?voice=ID&index=N   بدنه WAV، سرآیندهای X-Text و X-Heard (URL-encoded)  ⇒ وارسیِ تکه
#   DELETE /voices/{id}
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from engines import textfa, wavio  # noqa: E402


class HttpError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ───────────────────────── تنظیمات ─────────────────────────

def load_config(path):
    cfg = {
        "Port": 5620, "ModelsDir": "../models", "DataDir": "../data", "Threads": 4,
        "Engines": {"pocket": {"enabled": True, "threads": 2, "workers": 2},
                    "sa3-small-sfx": {"enabled": True, "threads": 4, "keepLoaded": False}},
    }
    if path and Path(path).exists():
        user = json.loads(Path(path).read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                for kk, vv in v.items():
                    cfg[k][kk] = {**cfg[k].get(kk, {}), **vv} if isinstance(vv, dict) else vv
            else:
                cfg[k] = v
    return cfg


def resolve(p, base=HERE):
    p = Path(p)
    return (p if p.is_absolute() else base / p).resolve()


# ───────────────────────── صداها ─────────────────────────

_SAFE_ID = re.compile(r"[^0-9A-Za-z؀-ۿ_\-]+")


class VoiceBank:
    """صداهای آماده (voice/voices/voices.json) + صداهای کلون‌شده (data/voices/<id>/)."""

    def __init__(self, builtin_dir, clone_dir):
        self.builtin_dir, self.clone_dir = Path(builtin_dir), Path(clone_dir)
        self.clone_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def builtin(self):
        p = self.builtin_dir / "voices.json"
        items = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        return [dict(v, kind="builtin") for v in items if (self.builtin_dir / v["file"]).exists()]

    def cloned(self):
        out = []
        for d in sorted(self.clone_dir.iterdir()) if self.clone_dir.exists() else []:
            meta = d / "voice.json"
            if meta.exists():
                m = json.loads(meta.read_text(encoding="utf-8"))
                m.update(kind="cloned", ready=(d / "ref.wav").exists(), clips=len(self._clips(d)))
                m["minutes"] = round(sum(c["seconds"] for c in self._clips(d)) / 60, 1)
                out.append(m)
        return out

    def all(self):
        return self.builtin() + self.cloned()

    def reference(self, voice_id):
        """شناسهٔ صدا ⇒ مسیرِ WAVِ مرجع."""
        for v in self.builtin():
            if v["id"] == voice_id:
                return self.builtin_dir / v["file"]
        d = self.clone_dir / voice_id
        if (d / "voice.json").exists():
            if not (d / "ref.wav").exists():
                raise HttpError(409, "این صدا هنوز آماده نیست — دست‌کم یک جمله را ضبط کنید.")
            return d / "ref.wav"
        raise HttpError(404, f"صدای «{voice_id}» پیدا نشد.")

    # ── کلون ──
    def create(self, name, person, purpose):
        name = (name or "").strip()
        if not name:
            raise HttpError(400, "نامِ صدا لازم است.")
        plain = re.sub(r"[ً-ٰٟ]", "", unicodedata.normalize("NFC", name))   # بی اعراب
        vid = _SAFE_ID.sub("-", plain).strip("-")[:40] or "voice"
        with self.lock:
            base, i = vid, 2
            while (self.clone_dir / vid).exists():
                vid, i = f"{base}-{i}", i + 1
            d = self.clone_dir / vid
            (d / "clips").mkdir(parents=True)
            meta = {"id": vid, "name": name, "person": (person or "").strip(), "purpose": (purpose or "").strip(),
                    "consent": True, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
            (d / "voice.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def _dir(self, vid):
        d = self.clone_dir / vid
        if not (d / "voice.json").exists():
            raise HttpError(404, f"صدای «{vid}» پیدا نشد.")
        return d

    def _clips(self, d):
        p = d / "clips.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def add_clip(self, vid, index, text, wav_bytes, heard=None):
        d = self._dir(vid)
        try:
            a, sr = wavio.read_wav(wav_bytes)
        except ValueError as e:
            raise HttpError(400, str(e))
        check = clip_quality(a, sr, text, heard)
        if not check["ok"]:
            return check
        name = f"{int(index):03d}.wav"
        a16 = wavio.resample(trim_edges(a, sr), sr, 22050)          # همه یکدست: ۲۲۰۵۰ هرتز، تک‌کاناله (مثلِ آموزشِ Piper)
        with self.lock:
            wavio.write_wav(d / "clips" / name, a16, 22050)
            clips = [c for c in self._clips(d) if c["file"] != name]
            clips.append({"file": name, "index": int(index), "text": text, "heard": heard, "seconds": round(len(a16) / 22050, 2),
                          "snr": check["snr"]})
            clips.sort(key=lambda c: c["index"])
            (d / "clips.json").write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
            (d / "metadata.csv").write_text("".join(f"{c['file']}|{c['text']}\n" for c in clips), encoding="utf-8")
            self._pick_reference(d, clips)
        check.update(clips=len(clips), minutes=round(sum(c["seconds"] for c in clips) / 60, 1))
        return check

    def _pick_reference(self, d, clips):
        """مرجعِ کلونِ فوری: تمیزترین تکهٔ ۳ تا ۱۰ ثانیه‌ای (موتورهای بی‌آموزش فقط چند ثانیه می‌خواهند)."""
        good = [c for c in clips if 3.0 <= c["seconds"] <= 10.0] or clips
        best = max(good, key=lambda c: (c["snr"], -abs(c["seconds"] - 6)))
        a, sr = wavio.read_wav(str(d / "clips" / best["file"]))
        wavio.write_wav(d / "ref.wav", a, sr)
        (d / "ref.txt").write_text(best["text"], encoding="utf-8")

    def delete(self, vid):
        import shutil
        d = self._dir(vid)
        with self.lock:
            shutil.rmtree(d)
        return True


def trim_edges(a, sr):
    from engines.pocket import trim_silence
    return trim_silence(a, sr, keep=0.15)


def _words(s):
    s = textfa.normalize(s or "")
    return [w for w in re.sub(r"[.،؛؟!:]", " ", s).replace("‌", "").split() if w]


def word_error_rate(ref, hyp):
    r, h = _words(ref), _words(hyp)
    if not r:
        return 0.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return min(1.0, prev[-1] / len(r))


def clip_quality(a, sr, text, heard):
    """یک جملهٔ ضبط‌شده برای کلون: طول، بلندی، بریدگی، نویز، و (اگر کیت شنیده را فرستاد) درست خوانده شده؟"""
    dur = len(a) / sr
    h = max(1, int(0.02 * sr))
    n = len(a) // h
    frames = np.sqrt((a[:n * h].reshape(n, h) ** 2).mean(axis=1)) if n else np.zeros(1)
    noise = float(np.percentile(frames, 10)) + 1e-7
    speech = float(np.percentile(frames, 90)) + 1e-7
    snr = round(20 * np.log10(speech / noise), 1)
    level_db = round(20 * np.log10(speech), 1)
    clipped = float(np.mean(np.abs(a) >= 0.985))
    wer = None if heard is None else round(word_error_rate(text, heard), 2)
    problems = []
    if dur < 1.2:
        problems.append("خیلی کوتاه بود — کلِ جمله را بخوانید.")
    elif dur > 25:
        problems.append("خیلی بلند بود — فقط همین یک جمله را بخوانید.")
    if level_db < -38:
        problems.append("صدا خیلی آرام است — نزدیک‌تر به میکروفون یا بلندتر بخوانید.")
    if clipped > 0.002:
        problems.append("صدا بریده (خیلی بلند) است — کمی دورتر از میکروفون یا آرام‌تر بخوانید.")
    if snr < 18:
        problems.append("نویزِ زمینه زیاد است — جای ساکت‌تری بروید یا پنکه/کولر را خاموش کنید.")
    if wer is not None and wer > 0.45:
        problems.append("جمله با متن جور نبود — همان متنِ نوشته‌شده را کامل و شمرده بخوانید.")
    return {"ok": not problems, "message": " ".join(problems) if problems else "خوب بود ✓", "seconds": round(dur, 2),
            "snr": snr, "level": level_db, "clipped": round(clipped, 4), "wer": wer, "heard": heard}


# ───────────────────────── موتورها ─────────────────────────

ENGINE_INFO = {
    "pocket": {"needs": ["tts", "clone"], "tier": "light", "license": "CC-BY-NC-4.0", "commercial": False,
               "name": "Pocket-TTS فارسی (طبیعی، کلون از ۵ ثانیه)"},
    "sa3-small-sfx": {"needs": ["sfx"], "tier": "light", "license": "Stability AI Community (تا ۱M$ درآمد)",
                      "commercial": True, "name": "Stable Audio 3 Small-SFX (صدای هر چیز)"},
}


class Engines:
    def __init__(self, cfg):
        self.cfg = cfg
        self.models = resolve(cfg["ModelsDir"])
        self._pocket = self._sfx = self._tr = None
        self.errors = {}
        self.locks = {"pocket": threading.Semaphore(1), "sfx": threading.Semaphore(1)}
        self.waiting = {"pocket": 0, "sfx": 0}
        self._init_lock = threading.Lock()

    def status(self):
        out = []
        for eid, info in ENGINE_INFO.items():
            e = self.cfg["Engines"].get(eid, {})
            out.append(dict(info, id=eid, enabled=bool(e.get("enabled", True)), available=self.available(eid),
                            error=self.errors.get(eid)))
        return out

    def available(self, eid):
        if eid == "pocket":
            return (self.models / "tts" / "pocket-fa" / "flow_lm_step.onnx.data").exists()
        if eid == "sa3-small-sfx":
            d = self.models / "sfx" / "sa3-small" / "tflite"
            return (d / "sa3-sm-sfx" / "dit_w8a32.tflite").exists() and (d / "t5gemma" / "encoder_fp16.tflite").exists()
        return False

    def pocket(self):
        with self._init_lock:
            if self._pocket is None:
                if not self.available("pocket"):
                    raise HttpError(503, "مدلِ Pocket نصب نیست: python tools/download_voice_models.py --only pocket-fa")
                from engines.pocket import Pocket
                e = self.cfg["Engines"]["pocket"]
                t0 = time.time()
                self._pocket = Pocket(self.models / "tts" / "pocket-fa", threads=e.get("threads", 2), workers=e.get("workers", 2))
                print(f"  Pocket بار شد در {time.time() - t0:.1f} ثانیه", flush=True)
            return self._pocket

    def sfx(self):
        with self._init_lock:
            if self._sfx is None:
                if not self.available("sa3-small-sfx"):
                    raise HttpError(503, "مدلِ صدای هر چیز نصب نیست: python tools/download_voice_models.py --only sa3-small-sfx")
                from engines.sfx import SfxRunner
                e = self.cfg["Engines"]["sa3-small-sfx"]
                self._sfx = SfxRunner(self.models / "sfx" / "sa3-small", threads=e.get("threads", 4),
                                      keep_loaded=e.get("keepLoaded", False), isolate=e.get("isolate", True))
            return self._sfx

    def make_room(self, need_mb):
        """حافظه کم است ⇒ Pocket از حافظه بیرون (دفعهٔ بعد در ~۵ ثانیه دوباره بار می‌شود)."""
        from engines.sfx import free_memory_mb
        free = free_memory_mb()
        if free is not None and free < need_mb and self._pocket is not None:
            with self.locks["pocket"]:
                self._pocket = None
                import gc
                gc.collect()
            print(f"  حافظه کم بود ({free}MB) ⇒ Pocket موقتاً از حافظه بیرون رفت", flush=True)

    def translator(self):
        with self._init_lock:
            if self._tr is None:
                from engines.sfx import PromptTranslator
                self._tr = PromptTranslator(HERE / "sfx_glossary_fa.json", self.models / "text" / "m2m100-ct2")
            return self._tr

    def run(self, kind, fn):
        """یک کار در هر لحظه برای هر موتور (RAM)؛ صفِ بیشتر از ۴ ⇒ ۴۲۹."""
        if self.waiting[kind] >= 4:
            raise HttpError(429, "سرِ موتورِ صدا شلوغ است — چند ثانیهٔ دیگر دوباره بفرستید.")
        self.waiting[kind] += 1
        try:
            with self.locks[kind]:
                return fn()
        finally:
            self.waiting[kind] -= 1


# ───────────────────────── HTTP ─────────────────────────

class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.data = resolve(cfg["DataDir"])
        self.engines = Engines(cfg)
        self.voices = VoiceBank(HERE / "voices", self.data / "voices")
        self.cache = self.data / "voice_cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.script = self._load_script()

    def _load_script(self):
        p = HERE.parent / "tools" / "voice-clone-script-fa.txt"
        if not p.exists():
            return []
        return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]

    def tts(self, body):
        text = (body.get("text") or "").strip()
        if not text:
            raise HttpError(400, "متن خالی است.")
        if len(text) > 3000:
            raise HttpError(400, "متن بیشتر از ۳۰۰۰ نویسه است — تکه‌تکه بفرستید.")
        engine = body.get("engine") or "pocket"
        if engine != "pocket":
            raise HttpError(400, f"موتورِ «{engine}» در این سرویس نیست (موتورها: GET /engines).")
        voices = self.voices.all()
        vid = body.get("voice") or (voices[0]["id"] if voices else "")
        ref = self.voices.reference(vid)
        seed = body.get("seed")
        seed = int(seed) if seed not in (None, "") else int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)
        st = ref.stat()
        key = hashlib.sha1(f"{engine}|{ref}|{st.st_mtime}|{st.st_size}|{seed}|{text}".encode()).hexdigest()
        cached = self.cache / f"{key}.wav"
        if cached.exists():
            return cached.read_bytes(), {"X-Voice-Engine": engine, "X-Voice-Cache": "hit", "X-Seed": str(seed)}
        eng = self.engines.pocket()
        t0 = time.time()
        audio = self.engines.run("pocket", lambda: eng.synthesize(text, ref, seed=seed))
        if not len(audio):
            raise HttpError(400, "متن چیزِ خواندنی نداشت.")
        st = eng.last_stats
        print(f"  گفتار: {len(audio) / eng.sample_rate:.1f} ثانیه صدا در {time.time() - t0:.1f} ثانیه، "
              f"{st.get('chunks', 0)} تکه" + (f"، {st['retries']} بار دوباره‌سازی" if st.get("retries") else ""), flush=True)
        wav = wavio.to_wav_bytes(audio, eng.sample_rate)
        tmp = cached.with_suffix(".tmp")
        tmp.write_bytes(wav)
        os.replace(tmp, cached)
        return wav, {"X-Voice-Engine": engine, "X-Voice-Seconds": f"{len(audio) / eng.sample_rate:.2f}",
                     "X-Voice-Took": f"{time.time() - t0:.2f}", "X-Seed": str(seed)}

    def sfx(self, body):
        prompt = (body.get("prompt") or "").strip()
        en = (body.get("promptEn") or "").strip()
        if not prompt and not en:
            raise HttpError(400, "توصیفِ صدا خالی است.")
        method = "given"
        if not en:
            en, method = self.engines.translator()(prompt)
            if method == "none":
                raise HttpError(400, "این توصیف ترجمه نشد — آن را به انگلیسی بنویسید یا مدلِ ترجمه را نصب کنید "
                                     "(python tools/download_voice_models.py --only m2m100-ct2).")
        try:
            seconds = float(body.get("seconds") or 8)
        except ValueError:
            raise HttpError(400, "مدت باید عدد باشد.")
        if not 1 <= seconds <= 47:
            raise HttpError(400, "مدت باید بینِ ۱ تا ۴۷ ثانیه باشد.")
        seed = body.get("seed")
        eng = self.engines.sfx()
        t0 = time.time()

        def work():
            if eng.isolate:
                self.engines.make_room(eng.NEED_MB)
            return eng.generate(en, seconds, None if seed in (None, "") else int(seed))
        try:
            audio, seed = self.engines.run("sfx", work)
        except MemoryError as e:
            raise HttpError(503, str(e))
        wav = wavio.to_wav_bytes(audio, 44100)
        return wav, {"X-Prompt-En": urllib.parse.quote(en), "X-Prompt-Method": method, "X-Seed": str(seed),
                     "X-Voice-Took": f"{time.time() - t0:.2f}"}


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "PersianAiKitVoice/1.0"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 40 * 1024 * 1024:
                raise HttpError(413, "بدنه خیلی بزرگ است.")
            return self.rfile.read(n) if n else b""

        def _json(self):
            raw = self._body()
            if not raw:
                return {}
            try:
                v = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise HttpError(400, "JSON نامعتبر است.")
            if not isinstance(v, dict):
                raise HttpError(400, "بدنه باید یک شیءِ JSON باشد.")
            return v

        def _route(self, method):
            u = urllib.parse.urlsplit(self.path)
            path = u.path.rstrip("/") or "/"
            q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
            t0 = time.time()
            try:
                self._dispatch(method, path, q)
            except HttpError as e:
                self._send(e.code, {"error": str(e)})
            except Exception as e:                             # خطای پیش‌بینی‌نشده: پیام + ردپا در گزارش
                traceback.print_exc()
                self._send(500, {"error": f"خطای داخلیِ سرویسِ صدا: {type(e).__name__} {e}".strip()})
            finally:
                if path not in ("/health", "/"):                  # کیت هر بار وضعیت را می‌پرسد
                    print(f"{time.strftime('%H:%M:%S')} {method} {path} {time.time() - t0:.1f}s", flush=True)

        def _dispatch(self, method, path, q):
            parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
            if method == "GET" and path in ("/", "/health"):
                return self._send(200, {"ok": True, "engines": app.engines.status(), "voices": len(app.voices.all())})
            if method == "GET" and path == "/engines":
                return self._send(200, {"engines": app.engines.status()})
            if method == "GET" and path == "/voices":
                return self._send(200, {"voices": app.voices.all()})
            if method == "GET" and path == "/script":
                return self._send(200, {"sentences": app.script})
            if method == "GET" and len(parts) == 3 and parts[0] == "voices" and parts[2] == "sample":
                return self._send(200, app.voices.reference(parts[1]).read_bytes(), "audio/wav")
            if method == "DELETE" and len(parts) == 2 and parts[0] == "voices":
                return self._send(200, {"removed": app.voices.delete(parts[1])})
            if method == "POST" and path == "/tts":
                wav, h = app.tts(self._json())
                return self._send(200, wav, "audio/wav", h)
            if method == "POST" and path == "/sfx":
                wav, h = app.sfx(self._json())
                return self._send(200, wav, "audio/wav", h)
            if method == "POST" and path == "/sfx/translate":
                en, how = app.engines.translator()(self._json().get("prompt") or "")
                return self._send(200, {"en": en, "method": how})
            if method == "POST" and path == "/clone":
                b = self._json()
                if b.get("consent") is not True:
                    raise HttpError(400, "بدونِ رضایتِ صاحبِ صدا نمی‌شود (consent: true).")
                return self._send(200, app.voices.create(b.get("name"), b.get("person"), b.get("purpose")))
            if method == "POST" and path == "/clone/clip":
                text = urllib.parse.unquote(self.headers.get("X-Text") or q.get("text") or "")
                heard = self.headers.get("X-Heard")
                heard = urllib.parse.unquote(heard) if heard is not None else None
                if not text or "voice" not in q or "index" not in q:
                    raise HttpError(400, "voice، index و متنِ جمله (X-Text) لازم است.")
                return self._send(200, app.voices.add_clip(q["voice"], int(q["index"]), text, self._body(), heard))
            raise HttpError(404, "چنین مسیری نیست.")

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_DELETE(self):
            self._route("DELETE")

    return H


def watch_parent(pid):
    """کیت بسته شد (حتی ناگهانی) ⇒ این سرویس هم بسته شود تا RAM نگه ندارد."""
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
        if not h:
            os._exit(0)
        k.WaitForSingleObject(h, 0xFFFFFFFF)
        os._exit(0)
    while True:
        time.sleep(2)
        try:
            os.kill(pid, 0)
        except OSError:
            os._exit(0)


def main():
    ap = argparse.ArgumentParser(description="سرویسِ صدای PersianAiKit")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--port", type=int)
    ap.add_argument("--data", help="پوشهٔ داده (کیت همان DataDirِ خودش را می‌دهد)")
    ap.add_argument("--models")
    ap.add_argument("--parent-pid", type=int, help="با بسته شدنِ این برنامه (کیت) بسته شود")
    a = ap.parse_args()
    if a.parent_pid:
        threading.Thread(target=watch_parent, args=(a.parent_pid,), daemon=True).start()
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    cfg = load_config(a.config)
    if a.port:
        cfg["Port"] = a.port
    if a.data:
        cfg["DataDir"] = a.data
    if a.models:
        cfg["ModelsDir"] = a.models
    app = App(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", cfg["Port"]), make_handler(app))
    srv.daemon_threads = True
    ok = lambda b: "✓" if b else "✗ (مدل نیست)"
    print(f"سرویسِ صدا روی http://127.0.0.1:{cfg['Port']}  داده: {app.data}", flush=True)
    for e in app.engines.status():
        print(f"  {e['id']:15s} {ok(e['available'])}", flush=True)
    print(f"  صداها: {len(app.voices.all())}", flush=True)
    pc = cfg["Engines"].get("pocket", {})
    if pc.get("enabled", True) and pc.get("warm", True) and app.engines.available("pocket"):
        # بارِ اولِ مدل ۵ تا ۱۵ ثانیه است ⇒ از همین حالا در پس‌زمینه، تا درخواستِ اول منتظر نماند
        threading.Thread(target=lambda: (app.engines.pocket(), app.engines.pocket().voice(app.voices.reference(app.voices.builtin()[0]["id"]))),
                         daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
