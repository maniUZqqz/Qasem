# Pocket-TTS-Farsi v2 (ONNX): گفتارِ فارسی با کلونِ صدا از ~۵ ثانیه، روی CPU و بی torch.
# مدل: huggingface.co/Nimaone/pocket-tts-farsi-v2-onnx — CC-BY-NC-4.0 (فقط غیرتجاری)؛ G2P: MIT.
# این کد از روی manifest.jsonِ همان بسته نوشته شده است.
#
# مسیر: متن ⇒ یکدست‌سازی (textfa) ⇒ G2P (ByT5، متن ⇒ آوا) ⇒ تکه‌های ≤۱۸ توکن ⇒ برای هر تکه از «حالتِ صدا»
#       latentها را گام‌به‌گام می‌سازد (flow_lm_step) تا نشانِ پایان ⇒ رمزگشای Mimi ⇒ ۲۴kHz ⇒ چسباندنِ تکه‌ها.
# مدل گاهی تکه‌ای را بد می‌سازد (سکوت، واژهٔ افتاده، تکرار) ⇒ هر تکه وارسی و در صورتِ نیاز دوباره ساخته می‌شود.
import json
import math
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import onnxruntime as ort
import sentencepiece as spm

from . import textfa, wavio

MAX_TOKENS = 18          # بودجهٔ امنِ هر تکه (آموزش روی ~۱۱ توکن؛ از ۲۱ به بعد پایان نمی‌یابد)
HARD_TOKENS = 20
GAP_SENTENCE, GAP_PHRASE, GAP_CHUNK = 0.42, 0.16, 0.10

# واژه‌هایی که نباید از قبلی یا بعدی جدا شوند (شکلِ آوایی، خروجیِ G2P)
_LIGHT_VERBS = {
    "?ast", "Ast", "hast", "hastand", "bud", "budand", "bASad", "bASand", "Sod", "Sodand", "Savad", "Savand",
    "miSavad", "miSavand", "kard", "kardand", "karde", "konad", "konand", "mikonad", "mikonand", "mikard",
    "dAd", "dAdand", "dAde", "dAhad", "midAd", "midahad", "midahand", "dArad", "dArand", "dASt",
}
_BINDS_LEFT = {"rA", "va", "yA", "ke", "hattA"}
_FUNCTION = {"dar", "be", "?az", "tA", "bA", "barAye", "bedune", "va", "ke", "yA", "vali", "?amA", "ruye", "zire"}


class Voice:
    """صدای مرجع ⇒ حافظهٔ KVِ آماده (یک بار حساب می‌شود و برای هر تکه کپی می‌شود)."""
    def __init__(self, cache, offset, seconds):
        self.cache, self.offset, self.seconds = cache, offset, seconds


class Pocket:
    sample_rate = 24000

    def __init__(self, model_dir, threads=2, workers=2):
        self.dir = Path(model_dir)
        man = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        c = man["constants"]
        self.ldim, self.dim = c["ldim"], c["dim"]
        self.L, self.H, self.D, self.cap = c["layers"], c["heads"], c["dim_per_head"], c["cache_capacity"]
        self.sample_rate = c["sample_rate"]
        self.dec_step = c["mimi_steps_per_latent"]
        self.temp = c["temp"]
        self.frame_rate = c["frame_rate"]
        w = np.load(self.dir / "weights.npz")
        self.lut = w["lut_weight"]
        self.spk_proj = w["speaker_proj"]
        self.bos_voice = w["bos_before_voice"][0]
        self.emb_std, self.emb_mean = w["emb_std"], w["emb_mean"]
        self.sp = spm.SentencePieceProcessor(model_file=str(self.dir / "v2" / "tokenizer_ph.model"))

        o = ort.SessionOptions()
        o.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        o.intra_op_num_threads, o.inter_op_num_threads = threads, 1
        load = lambda n: ort.InferenceSession(str(self.dir / n), o, providers=["CPUExecutionProvider"])
        self.flow, self.enc, self.dec = load("flow_lm_step.onnx"), load("mimi_encoder.onnx"), load("mimi_decoder_step_kv.onnx")
        self.g2p_enc, self.g2p_dec = load("g2p_encoder.onnx"), load("g2p_decoder.onnx")

        # رمزگشا: ورودیِ ۰ latent است و بقیه حالت‌ها به ترتیبِ decode_state_init.npz؛ حالت‌های «.cache» با kv پر می‌شوند
        self.dec_in = [i.name for i in self.dec.get_inputs()]
        dec_out = [x.name for x in self.dec.get_outputs()]
        init = np.load(self.dir / "decode_state_init.npz")
        self.dec_init = [init[k] for k in init.files]
        self.cache_slots = [i for i, k in enumerate(init.files) if k.endswith(".cache")]
        self.small_slots = [i for i in range(len(self.dec_init)) if i not in self.cache_slots]
        self.out_small = [i for i, n in enumerate(dec_out) if n.endswith("o") and n != "audio"]
        self.out_kv = [i for i, n in enumerate(dec_out) if n.startswith("kv")]
        self.dec_capacity = min(self.dec_init[i].shape[2] for i in self.cache_slots)

        self.pool = ThreadPoolExecutor(max_workers=max(1, workers))
        self._retries, self.last_stats = [], {}
        self._voices = OrderedDict()
        self._g2p_cache = OrderedDict()
        self._lock = threading.Lock()

    # ───────────── G2P: متنِ فارسی ⇒ آوا («1» پس از واژه یعنی کسرهٔ اضافه) ─────────────
    def phonemize(self, text: str) -> str:
        with self._lock:
            hit = self._g2p_cache.get(text)
        if hit is not None:
            return hit
        t = text.replace("؟", "").replace(":", "").strip()
        words = t.split()
        parts = [" ".join(words[i:i + 24]) for i in range(0, len(words), 24)] or [""]   # G2P بعد از ~۳۰ واژه خراب می‌شود
        out = " ".join(self._g2p(p) for p in parts if p).split()
        res = " ".join("ba?d" if w == "bo?d" else w for w in out)   # «بعد» گاهی «بود» خوانده می‌شود
        with self._lock:
            self._g2p_cache[text] = res
            while len(self._g2p_cache) > 2000:
                self._g2p_cache.popitem(last=False)
        return res

    def _g2p(self, text):
        ids = [b + 3 for b in text.encode("utf-8")]            # ByT5: شناسه = بایت + ۳
        enc = self.g2p_enc.run(None, {"input_ids": np.asarray([ids], np.int64)})[0]
        seq = [0]
        for _ in range(min(512, 8 * len(ids) + 16)):
            logits = self.g2p_dec.run(None, {"decoder_input_ids": np.asarray([seq], np.int64), "encoder_hidden": enc})[0]
            nxt = int(np.argmax(logits[0, -1]))
            if nxt == 1:
                break
            seq.append(nxt)
        raw = bytes(i - 3 for i in seq[1:] if 3 <= i <= 258).decode("utf-8", errors="replace")
        # الفبای G2P ⇒ الفبای توکن‌سازِ مدلِ گفتار
        return raw.translate(str.maketrans({"/": "a", "a": "A", "@": "?", "$": "S", "c": "C"}))

    # ───────────── تقسیم به تکه‌های اندازهٔ مدل ─────────────
    def _ntok(self, s):
        return len(self.sp.encode(s, out_type=int))

    def chunk(self, phonemes: str):
        """آوای یک عبارت ⇒ تکه‌ها. کم‌هزینه‌ترین جای بریدن با برنامه‌ریزیِ پویا:
        تکه‌ها نزدیکِ هم‌اندازه، هیچ تکه‌ای بالای ۲۰ توکن، و بریدن نه وسطِ کسرهٔ اضافه یا فعلِ مرکب."""
        words = phonemes.split()
        if not words:
            return []
        plain = [w.replace("1", "") for w in words]
        tok = [self._ntok(w) for w in plain]
        n = len(words)
        if sum(tok) <= HARD_TOKENS:
            return [" ".join(plain)]

        def joint(i):          # هزینهٔ بریدن پس از واژهٔ i
            a, b = words[i], plain[i + 1] if i + 1 < n else ""
            if a.endswith("1"):
                return 12       # «کتابِ | من»
            if b in _LIGHT_VERBS or b == "rA":
                return 10
            if plain[i] in _FUNCTION:
                return 7
            if b in _BINDS_LEFT:
                return 4
            if plain[i] in _LIGHT_VERBS or plain[i] == "rA":
                return -3       # پایانِ فعل یا مفعول: جای خوبی برای نفس
            return 0

        INF = float("inf")
        best = [INF] * (n + 1)
        back = [0] * (n + 1)
        best[0] = 0.0
        for j in range(1, n + 1):
            t = 0
            for i in range(j - 1, -1, -1):     # تکه = واژه‌های i..j-1
                t += tok[i]
                if t > HARD_TOKENS and i < j - 1:
                    break
                size = 4 + 0.03 * (t - 14) ** 2 + (15 if t > MAX_TOKENS else 0) + (8 if t < 6 or j - i < 3 else 0)
                c = best[i] + size + (joint(j - 1) if j < n else 0)
                if c < best[j]:
                    best[j], back[j] = c, i
        cuts, j = [], n
        while j > 0:
            cuts.append((back[j], j))
            j = back[j]
        return [" ".join(plain[i:j]) for i, j in reversed(cuts)]

    # ───────────── صدای مرجع ─────────────
    def voice(self, wav_path) -> Voice:
        p = Path(wav_path)
        st = p.stat()
        key = (str(p.resolve()), st.st_mtime, st.st_size)
        with self._lock:
            v = self._voices.get(key)
            if v is not None:
                self._voices.move_to_end(key)
                return v
        audio = prepare_reference(read_audio(p, self.sample_rate), self.sample_rate)
        lat = self.enc.run(None, {"audio": audio[None, None, :]})[0]            # [1,T,32]
        cond = (lat[0] @ self.spk_proj.T).astype(np.float32)
        text_emb = np.concatenate([self.bos_voice, cond])[None]
        cache = np.zeros((self.L, 2, self.cap, self.H, self.D), np.float32)
        _, _, off = self._step(np.zeros((1, 0, self.ldim), np.float32), text_emb, 0, np.zeros((1, self.ldim), np.float32), cache)
        v = Voice(cache, off, len(audio) / self.sample_rate)
        with self._lock:
            self._voices[key] = v
            while len(self._voices) > 6:
                self._voices.popitem(last=False)
        return v

    def _step(self, seq, text_emb, off, noise, cache):
        lat, eos, kv = self.flow.run(None, {"sequence": seq, "text_emb": text_emb, "offset": np.array(off, np.int64),
                                            "noise": noise, "cache": cache})
        kv = kv.reshape(self.L, 2, -1, self.H, self.D)
        s = kv.shape[2]
        if off + s > self.cap:
            raise RuntimeError("تکهٔ متن برای مدل بلند است")
        cache[:, :, off:off + s] = kv
        return lat, eos, off + s

    # ───────────── ساختِ یک تکه ─────────────
    def _generate(self, v: Voice, chunk: str, rng):
        """latent و صدا گام‌به‌گام با هم (رمزگشا جریانی است) ⇒ می‌شود زود فهمید:
        · مدل ساکت مانده و حرف نمی‌زند ⇒ همین‌جا رها (تلاشِ بعد) به‌جای ساختنِ چند ثانیه سکوت؛
        · نشانِ پایان آمده ولی هجای آخر هنوز صدا دارد ⇒ تا خاموش شدنِ صدا ادامه (وگرنه هجای آخر بریده می‌شود)."""
        ids = self.sp.encode(chunk, out_type=int)
        cache = v.cache.copy()
        scale = math.sqrt(self.temp)
        noise = lambda: (rng.standard_normal((1, self.ldim)) * scale).astype(np.float32)
        st = [a.copy() for a in self.dec_init]
        dec_off = [0]

        def decode(lt):
            feeds = {"latent": (lt.reshape(1, 1, self.ldim) * self.emb_std + self.emb_mean).astype(np.float32)}
            for i, a in enumerate(st):
                feeds[self.dec_in[1 + i]] = a
            res = self.dec.run(None, feeds)
            for j, o in enumerate(self.out_small):
                st[self.small_slots[j]] = res[o]
            for j, o in enumerate(self.out_kv):
                st[self.cache_slots[j]][:, :, dec_off[0]:dec_off[0] + self.dec_step] = res[o]
            dec_off[0] += self.dec_step
            return res[0].reshape(-1)

        lat, _, off = self._step(np.full((1, 1, self.ldim), np.nan, np.float32), self.lut[np.asarray(ids)][None].astype(np.float32),
                                 v.offset, noise(), cache)
        frames = [decode(lat)]
        limit = int(math.ceil((len(ids) / 3.0 + 2.0) * self.frame_rate))
        limit = min(limit, (self.cap - off) - 1, self.dec_capacity // self.dec_step - 2)
        lead_limit = int(1.6 * self.frame_rate)             # ۱٫۶ ثانیه سکوتِ آغاز ⇒ این تلاش خراب است
        empty = np.zeros((1, 0, self.dim), np.float32)
        peak, started, eos_at, quiet, ended = 0.0, None, None, 0, False
        for step in range(limit):
            lat, eos, off = self._step(lat.reshape(1, 1, self.ldim), empty, off, noise(), cache)
            a = decode(lat)
            frames.append(a)
            r = float(np.sqrt(np.mean(a ** 2)))
            peak = max(peak, r)
            if started is None:
                if r > 0.03:
                    started = step
                elif step >= lead_limit:
                    return None, len(ids), False
            if eos_at is None and float(eos.reshape(-1)[0]) > 0.5:
                eos_at = step
            if eos_at is not None:
                quiet = quiet + 1 if r < 0.08 * peak else 0
                if quiet >= 2 or step >= eos_at + 8:
                    ended = True
                    break
        return np.concatenate(frames).astype(np.float32), len(ids), ended

    def _chunk_audio(self, v: Voice, chunk: str, seed: int, attempts=3):
        """یک تکه، با وارسی: صدا دارد؟ طولش با تعدادِ آواها جور است؟ مکثِ بی‌جای بلند ندارد؟ پایان یافت؟"""
        rng = np.random.default_rng(seed)
        best, best_key = None, None
        for attempt in range(attempts):
            if attempt:
                self._retries.append(chunk)
            raw, ntok, ended = self._generate(v, chunk, rng)
            if raw is None:                                   # ساکت ماند
                continue
            a = trim_silence(raw, self.sample_rate)
            a = shorten_pauses(a, self.sample_rate, max_pause=0.32, keep=0.14)
            dur = len(a) / self.sample_rate
            rms = float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0
            voiced = voiced_seconds(a, self.sample_rate)
            expect = ntok / 5.0                     # ~۴ تا ۷ توکن در ثانیه
            # خیلی بلندتر از انتظار = تکرار یا گفتنِ واژه‌های خودِ صدای مرجع؛ خیلی کوتاه‌تر = واژهٔ افتاده
            ok = (rms > 0.015, ended, 0.45 * expect <= voiced <= 1.7 * expect + 0.3, longest_pause(a, self.sample_rate) <= 0.45)
            key = (ok[0], sum(ok), -abs(math.log(max(voiced, 1e-3) / expect)))
            if best_key is None or key > best_key:
                best, best_key = a, key
            if all(ok):
                break
        return best if best is not None else np.zeros(0, np.float32)

    # ───────────── ورودی ─────────────
    def synthesize(self, text: str, voice_wav, seed=None) -> np.ndarray:
        v = self.voice(voice_wav)
        # عبارت‌ها (جایی که نویسنده مکث گذاشته) با مکثِ پیش از هر کدام
        units = []                                  # [آوا، مکثِ پیش از آن]
        for phrases in textfa.sentences(text):
            for pi, ph in enumerate(phrases):
                p = self.phonemize(ph)
                if p:
                    units.append([p, GAP_SENTENCE if pi == 0 else GAP_PHRASE])
        # مدل روی تکهٔ خیلی کوتاه (کمتر از ۶ توکن، مثلِ «سلام،») بد می‌خواند: کش می‌دهد یا واژه می‌اندازد
        # ⇒ به عبارتِ بعدی (یا اگر آخری است، قبلی) می‌چسبد؛ مکثِ آن ویرگول فدای درست خواندن می‌شود.
        i = 0
        while len(units) > 1 and i < len(units):
            if self._ntok(units[i][0].replace("1", "")) < 6:
                if i + 1 < len(units):
                    units[i + 1] = [units[i][0] + " " + units[i + 1][0], units[i][1]]
                else:
                    units[i - 1][0] += " " + units[i][0]
                del units[i]
                continue
            i += 1
        jobs = []                                   # (تکه, مکثِ پیش از آن)
        for ph, gap in units:
            for ci, c in enumerate(self.chunk(ph)):
                jobs.append((c, 0.0 if not jobs else gap if ci == 0 else GAP_CHUNK))
        if not jobs:
            return np.zeros(0, np.float32)
        seeds = np.random.default_rng(seed).integers(0, 2 ** 62, size=len(jobs))
        self._retries = []
        audios = list(self.pool.map(lambda i: self._chunk_audio(v, jobs[i][0], int(seeds[i])), range(len(jobs))))
        self.last_stats = {"chunks": len(jobs), "retries": len(self._retries)}
        return stitch([(a, g) for a, (_, g) in zip(audios, jobs)], self.sample_rate)


# ───────────── صدا: خواندن، آماده‌سازیِ مرجع، برش و چسباندن ─────────────
def read_audio(path, sr):
    return wavio.load(str(path), sr)


def _frames_rms(a, sr, win=0.01):
    h = max(1, int(win * sr))
    n = len(a) // h
    if n == 0:
        return np.zeros(0), h
    return np.sqrt((a[:n * h].reshape(n, h) ** 2).astype(np.float64).mean(axis=1)), h


def _speech_mask(a, sr, rel=0.06):
    """قاب‌های ۱۰ میلی‌ثانیه‌ای که گفتار دارند: بلندتر از ۶٪ِ سطحِ گفتار (صدکِ ۹۵) و پایدار
    (دست‌کم ۳ از ۵ قاب) — تقه و خش‌های کوتاه گفتار حساب نمی‌شوند."""
    f, h = _frames_rms(a, sr)
    if not len(f):
        return np.zeros(0, bool), h
    level = float(np.percentile(f, 95))
    if level < 1e-5:
        return np.zeros(len(f), bool), h
    loud = (f > rel * level).astype(np.float64)
    return np.convolve(loud, np.ones(5), "same") >= 3, h


def _runs(mask):
    """[(آغاز، پایان)] برای بخش‌های پشتِ همِ True."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def prepare_reference(a, sr, max_s=5.0):
    """مرجعِ کلون (مدل ادامهٔ همین صدا را می‌سازد، پس سکوت و تقهٔ آن هم ادامه می‌یابد):
    سکوتِ دو سر حذف؛ تقه یا هجای تنهای آغاز که سکوتی بلند پشتش است حذف؛ مکث‌های درونیِ بلند کوتاه؛
    حداکثر ۵ ثانیه (بیشتر برای مدل ناآشناست) با بریدن در مکث نه وسطِ واژه؛ سطحِ صدا یکدست."""
    a = trim_silence(a, sr, keep=0.03)
    mask, h = _speech_mask(a, sr)
    speech = _runs(mask)
    if len(speech) >= 2 and (speech[0][1] - speech[0][0]) * h < 0.4 * sr and (speech[1][0] - speech[0][1]) * h > 0.35 * sr:
        a = a[max(0, speech[1][0] * h - int(0.03 * sr)):]
    a = shorten_pauses(a, sr, max_pause=0.35, keep=0.2)
    if len(a) > max_s * sr:
        mask, h = _speech_mask(a, sr)
        lo, hi = int(3.0 * sr) // h, int(max_s * sr) // h
        gaps = [(s, e) for s, e in _runs(~mask) if s >= lo and s < hi]
        if gaps:                                           # آخرین مکثِ پیش از ۵ ثانیه
            s, e = gaps[-1]
            cut = min((s + e) // 2, hi) * h
        else:
            f, _ = _frames_rms(a[lo * h:hi * h], sr)
            cut = lo * h + int(np.argmin(f)) * h
        a = a[:cut]
        n = int(0.02 * sr)
        a[-n:] *= np.linspace(1, 0, n, dtype=np.float32)
    f, h = _frames_rms(a, sr, 0.02)
    if len(f) > 20:                                        # هجای اولِ خیلی بلند: مدل آن را اولِ هر تکه تکرار می‌کند
        voiced = f[f > 0.05 * f.max()]
        if len(voiced) and np.sqrt(np.mean(f[:15] ** 2)) > 1.8 * np.median(voiced) and len(a) - 15 * h > 1.5 * sr:
            a = a[15 * h:].copy()
            n = int(0.02 * sr)
            a[:n] *= np.linspace(0, 1, n, dtype=np.float32)
    rms = float(np.sqrt(np.mean(a ** 2))) if len(a) else 0
    if rms > 1e-4:
        a = a * min(0.12 / rms, 0.9 / max(float(np.abs(a).max()), 1e-6))   # سطحِ نمونه‌های خودِ مدل (~۰٫۱۲)
    return a.astype(np.float32)


def trim_silence(a, sr, keep=0.04):
    mask, h = _speech_mask(a, sr)
    idx = np.where(mask)[0]
    if not len(idx):
        return a
    s = max(0, idx[0] * h - int(keep * sr))
    e = min(len(a), (idx[-1] + 1) * h + int(keep * 1.5 * sr))
    return a[s:e]


def _quiet_runs(a, sr):
    mask, h = _speech_mask(a, sr)
    return _runs(~mask), h


def longest_pause(a, sr):
    runs, h = _quiet_runs(a, sr)
    return max(((e - s) * h for s, e in runs), default=0) / sr


def voiced_seconds(a, sr):
    runs, h = _quiet_runs(a, sr)
    return max(0.0, len(a) - sum((e - s) * h for s, e in runs)) / sr


def shorten_pauses(a, sr, max_pause=0.38, keep=0.24):
    runs, h = _quiet_runs(a, sr)
    runs = [(s * h, e * h) for s, e in runs if (e - s) * h > max_pause * sr and s > 0 and e * h < len(a)]
    if not runs:
        return a
    out, pos, k = [], 0, int(keep * sr)
    for s, e in runs:
        out.append(a[pos:s + k // 2])
        pos = e - k // 2
    out.append(a[pos:])
    return np.concatenate(out)


def stitch(parts, sr):
    """تکه‌ها با بلندیِ یکسان (میانهٔ همه)، محو شدنِ ۸ میلی‌ثانیه‌ای دو سر و مکث‌های ثابت."""
    levels = [float(np.sqrt(np.mean(a ** 2))) for a, _ in parts if len(a)]
    target = float(np.median(levels)) if levels else 0.0
    f = int(0.008 * sr)
    out = []
    for a, gap in parts:
        if not len(a):
            continue
        r = float(np.sqrt(np.mean(a ** 2)))
        a = a * (float(np.clip(target / r, 0.4, 2.5)) if r > 1e-6 and target > 1e-6 else 1.0)
        if len(a) > 2 * f:
            a = a.copy()
            a[:f] *= np.linspace(0, 1, f, dtype=np.float32)
            a[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
        if gap > 0 and out:
            out.append(np.zeros(int(gap * sr), np.float32))
        out.append(a.astype(np.float32))
    if not out:
        return np.zeros(0, np.float32)
    y = np.concatenate(out)
    peak = float(np.abs(y).max())
    return (y * (0.95 / peak) if peak > 0.95 else y).astype(np.float32)
