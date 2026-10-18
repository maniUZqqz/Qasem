# صدای هر چیز از روی توصیف: Stable Audio 3 Small-SFX روی CPU (LiteRT/TFLite).
# مدل: Stability AI Community License (رایگان تا درآمدِ سالانهٔ ۱ میلیون دلار) + Gemma Terms برای T5Gemma.
# مدل فقط انگلیسی می‌فهمد ⇒ توصیفِ فارسی اول از واژه‌نامه (sfx_glossary_fa.json) و بعد ترجمهٔ ماشینی می‌گذرد.
import gc
import json
import os
import re
import threading
from pathlib import Path

import numpy as np

from .sa3 import pipeline as P

_FA = re.compile(r"[؀-ۿ]")


class StableAudioSfx:
    sample_rate = P.SAMPLE_RATE

    def __init__(self, model_dir, threads=4, keep_loaded=False, dit="dit_w8a32.tflite", decoder="dec_w8a8.tflite"):
        d = Path(model_dir)
        self.paths = {
            "tok": d / "tokenizer.model",
            "t5": d / "tflite" / "t5gemma" / "encoder_fp16.tflite",
            "dit": d / "tflite" / "sa3-sm-sfx" / dit,
            "dec": d / "tflite" / "same-s" / decoder,
        }
        missing = [str(p) for p in self.paths.values() if not p.exists()]
        if missing:
            raise FileNotFoundError("فایلِ مدل نیست: " + ", ".join(missing))
        self.threads, self.keep = threads, keep_loaded
        self.tok = P.Tokenizer(self.paths["tok"])
        self._t5 = self._dec = None
        self._lock = threading.Lock()        # یک ساخت در هر لحظه (RAM)

    def generate(self, prompt_en: str, seconds=8.0, seed=None, steps=8):
        """توصیفِ انگلیسی ⇒ [۲، نمونه] (استریو، ۴۴۱۰۰ هرتز)."""
        from .sa3.rung_decoder import RungDecoder
        seconds = float(min(max(seconds, 1.0), 47.0))
        seed = int(np.random.default_rng().integers(0, 2 ** 31)) if seed is None else int(seed)
        L = P.valid_T_lat(seconds)
        with self._lock:
            t5 = self._t5 or P.T5GemmaTFLite(self.paths["t5"], self.threads)
            ids, mask = self.tok(prompt_en)
            hidden = t5(ids, mask)
            if self.keep:
                self._t5 = t5
            else:
                del t5
                gc.collect()
            dit = P.BakedDiT(self.paths["dit"], L, hidden, mask, seconds, self.threads)
            x0, noise = P.make_noise(L, steps, seed)
            lat = P.sample(dit, x0, noise, P.pingpong_schedule(steps))
            del dit
            gc.collect()
            dec = self._dec or RungDecoder(self.paths["dec"], threads=self.threads, trim=16)
            if L % 2:                                    # SAME-S طولِ زوج می‌خواهد
                lat = np.concatenate([lat, lat[:, :, -1:]], axis=2)
            audio = dec.decode(lat)[0, :, :L * P.SAMPLES_PER_LATENT]
            if self.keep:
                self._dec = dec
            else:
                del dec
                gc.collect()
        audio = audio[:, :int(round(seconds * self.sample_rate))]
        n = int(0.01 * self.sample_rate)                 # بی تق در دو سر
        audio[:, :n] *= np.linspace(0, 1, n, dtype=np.float32)
        audio[:, -n:] *= np.linspace(1, 0, n, dtype=np.float32)
        # بلندیِ یکسان: مدل گاهی خیلی آرام می‌سازد (باران: قله ۰٫۲) ⇒ سطحِ ~۲۰- dB، قله حداکثر ۱- dB
        peak = float(np.abs(audio).max())
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if peak > 1e-4 and rms > 1e-5:
            audio = audio * min(0.1 / rms, 0.89 / peak, 12.0)
        return np.clip(audio, -1, 1).astype(np.float32), seed


def free_memory_mb():
    """حافظهٔ قابلِ تخصیص (commit) به مگابایت؛ None اگر نشد سنجید."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("phys", ctypes.c_ulonglong),
                            ("avail_phys", ctypes.c_ulonglong), ("page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                            ("virt", ctypes.c_ulonglong), ("avail_virt", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
            m = MS()
            m.len = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(min(m.avail_page, m.avail_phys + m.avail_page // 2) // 2 ** 20)
        with open("/proc/meminfo") as f:
            info = {l.split(":")[0]: int(l.split()[1]) for l in f}
        return info.get("MemAvailable", 0) // 1024
    except Exception:
        return None


def _generate_worker(args):
    model_dir, prompt_en, seconds, seed, threads = args
    return StableAudioSfx(model_dir, threads=threads).generate(prompt_en, seconds, seed)


class SfxRunner:
    """روی کامپیوترِ کم‌حافظه (isolate): هر ساخت در یک فرآیندِ کوتاه‌عمرِ جدا ⇒ پس از پایان همهٔ حافظه (~۳GB) به ویندوز
    برمی‌گردد و شکستِ تخصیصِ حافظه سرویس را آلوده نمی‌کند. روی سرور (keepLoaded): مدل‌ها در حافظه می‌مانند (~۱۴ ثانیه به‌جای ~۵۰)."""
    NEED_MB = 3000

    def __init__(self, model_dir, threads=4, keep_loaded=False, isolate=True):
        self.model_dir, self.threads = str(model_dir), threads
        self.isolate = isolate and not keep_loaded
        self.engine = None if self.isolate else StableAudioSfx(model_dir, threads=threads, keep_loaded=keep_loaded)
        if self.isolate:
            StableAudioSfx(model_dir, threads=threads)      # فقط وارسیِ بودنِ فایل‌ها

    def generate(self, prompt_en, seconds=8.0, seed=None):
        try:
            if not self.isolate:
                return self.engine.generate(prompt_en, seconds, seed)
            import multiprocessing
            with multiprocessing.get_context("spawn").Pool(1) as pool:
                return pool.apply(_generate_worker, ((self.model_dir, prompt_en, seconds, seed, self.threads),))
        except (RuntimeError, MemoryError) as e:
            free = free_memory_mb()
            raise MemoryError(f"حافظهٔ کامپیوتر برای ساختِ صدا کافی نیست (حدودِ {self.NEED_MB // 1000} گیگابایت آزاد لازم است"
                              + (f"، الان {free} مگابایت" if free is not None else "") +
                              ") — برنامه‌های دیگر را ببندید یا این کار را روی سرور انجام دهید.") from e


class PromptTranslator:
    """توصیفِ فارسیِ صدا ⇒ انگلیسی: اول واژه‌نامهٔ صداها (دقیق‌تر برای این کار)، بعد M2M100 (اگر نصب باشد)."""
    def __init__(self, glossary_path, m2m_dir=None, threads=2):
        self.glossary = {}
        p = Path(glossary_path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            self.glossary = {k: v for k, v in data.items() if not k.startswith("_")}
        # بلندترین عبارت اول («بارانِ شدید» پیش از «باران»)
        self._keys = sorted(self.glossary, key=len, reverse=True)
        self.m2m_dir = Path(m2m_dir) if m2m_dir else None
        self.threads = threads
        self._tr = self._sp = None

    def _mt(self, text):
        if not self.m2m_dir or not (self.m2m_dir / "model.bin").exists():
            return None
        try:
            if self._tr is None:
                import ctranslate2
                import sentencepiece as spm
                self._tr = ctranslate2.Translator(str(self.m2m_dir), device="cpu", inter_threads=1, intra_threads=self.threads)
                self._sp = spm.SentencePieceProcessor(model_file=str(self.m2m_dir / "sentencepiece.bpe.model"))
            src = ["__fa__"] + self._sp.encode(text, out_type=str) + ["</s>"]
            r = self._tr.translate_batch([src], target_prefix=[["__en__"]], beam_size=4, max_decoding_length=96)
            toks = [t for t in r[0].hypotheses[0] if t not in ("__en__", "</s>")]
            out = self._sp.decode(toks).strip().rstrip(".")
            return re.sub(r"^(the )?(sound|voice|noise) of (an? |the )?", "", out, flags=re.I).strip()
        except Exception:
            return None

    def __call__(self, text: str):
        """⇒ (انگلیسی، روش: 'en' | 'glossary' | 'mt' | 'mixed')"""
        t = (text or "").strip()
        if not _FA.search(t):
            return t, "en"
        from .textfa import normalize
        norm = normalize(t).replace("،", ",")
        hits, rest = [], norm
        for k in self._keys:
            nk = normalize(k)
            at = rest.find(nk) if nk else -1
            if at >= 0:
                hits.append((at, self.glossary[k]))
                rest = rest.replace(nk, " " * len(nk))            # جای بقیه ثابت بماند
        hits = [h for _, h in sorted(hits)]                          # به ترتیبِ متن
        leftover = re.sub(r"[\s,.؛!]+", " ", rest).strip()
        leftover_words = [w for w in leftover.split() if w not in ("و", "با", "در", "از", "به", "یک", "روی", "صدای", "صدا", "ی")]
        if hits and not leftover_words:
            return ", ".join(hits), "glossary"
        mt = self._mt(t)
        if mt:
            return (mt + (", " + ", ".join(hits) if hits else "")), ("mixed" if hits else "mt")
        if hits:
            return ", ".join(hits), "glossary"
        return t, "none"
