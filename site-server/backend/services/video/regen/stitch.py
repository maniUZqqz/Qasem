"""از فریم‌های مدل تا تکه‌ای که به‌جای فریم‌های start…end می‌نشیند — بی‌درز.

برای هر فریمِ جایگزین j (به ترتیب):

1. **زمانِ دقیق.** جایش روی خطِ زمانیِ مدل s = (t(j) - t(b)) / (t(a) - t(b)) × G است. اگر s روی یک فریمِ مدل
   بیفتد همان، وگرنه بینِ دو فریمِ مدل با جریانِ نوریِ DIS (دوطرفه، وزن‌دار با فاصله) ساخته می‌شود — پس
   سرعتِ حرکت عوض نمی‌شود و fps ِ منبع (۲۴/۲۵/۳۰/۶۰…) دقیقاً حفظ می‌شود.
2. **هندسه.** همان نگاشتِ رفت (پدِ بازتابی + کوچک‌کردن) برعکس: بزرگ‌کردن تا بومِ پدشده و بریدنِ پد.
3. **رنگ/نور.** تفاوتِ رنگِ مدل با منبع روی دو فریمِ مرزی اندازه گرفته می‌شود (میانگین و انحرافِ هر کانال در
   Lab: فریمِ ۰ ِ مدل در برابرِ فریمِ b، فریمِ G در برابرِ a) و تصحیح از مقدارِ ابتدا تا مقدارِ انتها خطی
   روی تکه پخش می‌شود. محتوای وسطِ تکه هر چه باشد، سوگیریِ رنگِ مدل برداشته می‌شود و دو سر دقیقاً جفت می‌شوند.
4. **تیزی و دانه.** مدل در ۴۸۰p می‌سازد و تصویرش صاف است؛ انرژیِ جزئیات (واریانسِ لاپلاسین) و نویزِ منبع
   (روشِ Immerkær) در مرزها اندازه گرفته و تکه با unsharp و دانهٔ گاوسی هم‌اندازهٔ منبع می‌شود.
5. **cross-blend.** چند فریمِ اولِ تکه با فریم‌های اصلیِ همان لحظه آرام (smoothstep) ترکیب می‌شوند و چند
   فریمِ آخر هم؛ چشم درز را نمی‌بیند.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import cv2
import numpy as np

from . import media

logger = logging.getLogger(__name__)

GAIN_MIN, GAIN_MAX = 0.75, 1.33


class StitchError(RuntimeError):
    pass


# ───────────────────────────── هندسه

def to_model(frame: np.ndarray, plan: dict) -> np.ndarray:
    """فریمِ منبع (H×W) ⇐ اندازهٔ مدل (h×w) با پدِ بازتابی (هیچ لبه‌ای بریده نمی‌شود)."""
    w, h = plan["gen_size"]
    wp, hp, left, top = plan["canvas"]
    H, W = frame.shape[:2]
    padded = cv2.copyMakeBorder(frame, top, hp - H - top, left, wp - W - left, cv2.BORDER_REFLECT_101)
    return cv2.resize(padded, (w, h), interpolation=cv2.INTER_AREA)


def from_model(frame: np.ndarray, plan: dict, width: int, height: int) -> np.ndarray:
    """برعکسِ to_model: بزرگ‌کردن تا بومِ پدشده و بریدنِ همان پد."""
    wp, hp, left, top = plan["canvas"]
    if frame.shape[1] != plan["gen_size"][0] or frame.shape[0] != plan["gen_size"][1]:
        frame = cv2.resize(frame, tuple(plan["gen_size"]), interpolation=cv2.INTER_AREA)
    big = cv2.resize(frame, (wp, hp), interpolation=cv2.INTER_LANCZOS4)
    return big[top:top + height, left:left + width]


# ───────────────────────────── اندازه‌گیری

def _lab(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)


def lab_stats(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = img.shape[:2]
    small = cv2.resize(img, (256, max(2, round(256 * h / w))), interpolation=cv2.INTER_AREA) if w > 256 else img
    lab = _lab(small).reshape(-1, 3)
    lo, hi = np.percentile(lab, [1, 99], axis=0)
    core = lab[np.all((lab >= lo) & (lab <= hi), axis=1)]
    core = core if len(core) > 64 else lab
    return core.mean(axis=0), core.std(axis=0) + 1e-3


def color_params(gen: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """gain/offset ِ هر کانالِ Lab تا آمارِ gen بشود آمارِ ref."""
    mg, sg = lab_stats(gen)
    mr, sr = lab_stats(ref)
    gain = np.clip(sr / sg, GAIN_MIN, GAIN_MAX)
    offset = mr - gain * mg
    return gain.astype(np.float32), offset.astype(np.float32)


def apply_color(img: np.ndarray, gain: np.ndarray, offset: np.ndarray) -> np.ndarray:
    if np.allclose(gain, 1, atol=1e-3) and np.allclose(offset, 0, atol=1e-2):
        return img
    lab = _lab(img)
    lab = lab * gain.reshape(1, 1, 3) + offset.reshape(1, 1, 3)
    lab[..., 0] = np.clip(lab[..., 0], 0, 100)
    rgb = cv2.cvtColor(lab, cv2.COLOR_Lab2RGB)
    return np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _luma(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)


def detail(img: np.ndarray) -> float:
    """انرژیِ جزئیاتِ میان‌بسامد (تفاضلِ دو گاوسی σ=۰٫۸ و ۲) — نویزِ ریزِ دوربین در آن کم اثر دارد، تا تیزکردن
    «نویز» را هدف نگیرد (دانه جداگانه با add_grain جفت می‌شود)."""
    y = _luma(img)
    band = cv2.GaussianBlur(y, (0, 0), 0.8) - cv2.GaussianBlur(y, (0, 0), 2.0)
    return float(band.var())


def noise_sigma(img: np.ndarray) -> float:
    """Immerkær (1996): برآوردِ سریعِ انحرافِ نویزِ سفید از روی لاپلاسینِ دوم؛ لبه‌های قوی کنار گذاشته می‌شوند."""
    y = _luma(img)
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
    conv = np.abs(cv2.filter2D(y, cv2.CV_32F, k))[1:-1, 1:-1]
    edges = cv2.Sobel(y, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(y, cv2.CV_32F, 0, 1) ** 2
    flat = edges[1:-1, 1:-1] < np.percentile(edges, 60)
    vals = conv[flat] if flat.sum() > 1000 else conv.ravel()
    return float(math.sqrt(math.pi / 2) * vals.mean() / 6.0)


def sharpen(img: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0.02:
        return img
    f = img.astype(np.float32)
    blur = cv2.GaussianBlur(f, (0, 0), 1.0)
    return np.clip(f + amount * (f - blur) + 0.5, 0, 255).astype(np.uint8)


def match_sharpness(gen: np.ndarray, ref: np.ndarray) -> float:
    """چه مقدار unsharp لازم است تا انرژیِ جزئیاتِ gen به ref برسد (۰ … ۲)."""
    target = detail(ref)
    if detail(gen) >= 0.9 * target:
        return 0.0
    best, best_err = 0.0, abs(math.log((detail(gen) + 1e-3) / (target + 1e-3)))
    for amount in np.arange(0.25, 2.01, 0.25):
        err = abs(math.log((detail(sharpen(gen, float(amount))) + 1e-3) / (target + 1e-3)))
        if err < best_err:
            best, best_err = float(amount), err
    return best


def add_grain(img: np.ndarray, sigma: float, rng: np.random.Generator) -> np.ndarray:
    if sigma < 0.4:
        return img
    noise = rng.normal(0.0, sigma, img.shape[:2]).astype(np.float32)[..., None]
    return np.clip(img.astype(np.float32) + noise + 0.5, 0, 255).astype(np.uint8)


# ───────────────────────────── زمان: جریانِ نوری بینِ دو فریمِ مدل

class Interpolator:
    def __init__(self):
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        self.cache: dict[int, tuple] = {}

    def flows(self, k: int, f0: np.ndarray, f1: np.ndarray):
        if k not in self.cache:
            self.cache = {kk: v for kk, v in self.cache.items() if kk >= k - 1}
            g0 = cv2.cvtColor(f0, cv2.COLOR_RGB2GRAY)
            g1 = cv2.cvtColor(f1, cv2.COLOR_RGB2GRAY)
            self.cache[k] = (self.dis.calc(g0, g1, None), self.dis.calc(g1, g0, None))
        return self.cache[k]

    def between(self, k: int, f0: np.ndarray, f1: np.ndarray, t: float) -> np.ndarray:
        f01, f10 = self.flows(k, f0, f1)
        h, w = f0.shape[:2]
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        w0 = cv2.remap(f0, gx - t * f01[..., 0], gy - t * f01[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        w1 = cv2.remap(f1, gx - (1 - t) * f10[..., 0], gy - (1 - t) * f10[..., 1], cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)
        # جایی که دو برآورد با هم نمی‌خوانند (پوشش/ناپیدایی)، به فریمِ نزدیک‌تر تکیه کن
        disagree = np.abs(w0.astype(np.int16) - w1.astype(np.int16)).max(axis=2).astype(np.float32)
        conf = np.clip(1.0 - (disagree - 24.0) / 48.0, 0.0, 1.0)[..., None]
        wt = (1 - t) * conf + (1.0 if t < 0.5 else 0.0) * (1 - conf)
        out = wt * w0.astype(np.float32) + (1 - wt) * w1.astype(np.float32)
        return np.clip(out + 0.5, 0, 255).astype(np.uint8)


# ───────────────────────────── فریم‌های خروجیِ مدل

def gen_index_files(plan: dict, files_by_chunk: dict) -> dict[int, Path]:
    """{شمارهٔ فریمِ مدل (۰…G): فایل} — فریم‌های زمینه و تکرارِ همپوشانیِ تکه‌ها کنار گذاشته می‌شوند."""
    out: dict[int, Path] = {}
    for ch in plan["chunks"]:
        files = sorted(files_by_chunk.get(ch["index"]) or [], key=lambda p: Path(p).name)
        if len(files) < ch["length"]:
            raise StitchError(f"تکهٔ {ch['index'] + 1} از مدل {len(files)} فریم دارد؛ {ch['length']} لازم بود.")
        for k, f in enumerate(files[:ch["length"]]):
            gi = ch["first_gen_index"] + k
            keep = (0 <= gi <= ch["p1"]) if ch["index"] == 0 else (ch["p0"] < gi <= ch["p1"])
            if keep:
                out[gi] = Path(f)
    missing = [i for i in range(plan["G"] + 1) if i not in out]
    if missing:
        raise StitchError(f"فریم‌های {missing[:5]} از خروجیِ مدل کم است.")
    return out


class GenFrames:
    def __init__(self, files: dict[int, Path], plan: dict):
        self.files = files
        self.plan = plan
        self.cache: dict[int, np.ndarray] = {}

    def __getitem__(self, i: int) -> np.ndarray:
        if i not in self.cache:
            if len(self.cache) > 6:
                for k in sorted(self.cache)[:-4]:
                    self.cache.pop(k)
            img = media.load_png(self.files[i])
            w, h = self.plan["gen_size"]
            if img.shape[1] != w or img.shape[0] != h:
                img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            self.cache[i] = img
        return self.cache[i]


def smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def build_piece(plan: dict, gen: GenFrames, info: dict, base_path, out_path, *, seed: int = 1,
                on_progress=None) -> dict:
    """فریم‌های start…end ِ تازه را در out_path (x264 ِ تقریباً بی‌اتلاف، اندازه و fps ِ منبع) می‌نویسد."""
    W, H = int(info["width"]), int(info["height"])
    G = plan["G"]
    start, end, count = plan["start"], plan["end"], plan["count"]
    blend = int(plan.get("blend") or 0)

    ref_b = media.read_frame(base_path, info, plan["before"]) if plan["has_start"] else None
    ref_a = media.read_frame(base_path, info, plan["after"]) if plan["has_end"] else None
    g0 = from_model(gen[0], plan, W, H)
    gG = from_model(gen[G], plan, W, H)

    ident = (np.ones(3, np.float32), np.zeros(3, np.float32))
    cp_s = color_params(g0, ref_b) if ref_b is not None else None
    cp_e = color_params(gG, ref_a) if ref_a is not None else None
    cp_s = cp_s or cp_e or ident
    cp_e = cp_e or cp_s

    g0c, gGc = apply_color(g0, *cp_s), apply_color(gG, *cp_e)
    sh_s = match_sharpness(g0c, ref_b) if ref_b is not None else None
    sh_e = match_sharpness(gGc, ref_a) if ref_a is not None else None
    sh_s = sh_s if sh_s is not None else (sh_e or 0.0)
    sh_e = sh_e if sh_e is not None else sh_s

    def grain_for(gen_img, ref):
        if ref is None:
            return None
        so, sg = noise_sigma(ref), noise_sigma(gen_img)
        return float(min(6.0, math.sqrt(max(0.0, so * so - sg * sg)))) if so > sg + 0.6 else 0.0

    gr_s = grain_for(sharpen(g0c, sh_s), ref_b)
    gr_e = grain_for(sharpen(gGc, sh_e), ref_a)
    gr_s = gr_s if gr_s is not None else (gr_e or 0.0)
    gr_e = gr_e if gr_e is not None else gr_s

    # فریم‌های اصلیِ کنارِ دو درز برای cross-blend
    head = media.read_frames(base_path, info, start, blend) if (blend and plan["has_start"]) else []
    tail = media.read_frames(base_path, info, end - blend + 1, blend) if (blend and plan["has_end"]) else []

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    interp = Interpolator()
    writer = media.RawWriter(out_path, info)
    exact = interpolated = 0
    try:
        for j in range(count):
            s = float(plan["positions"][j])
            tau = min(1.0, max(0.0, s / G))
            k0 = int(math.floor(s + 1e-6))
            f = s - k0
            if f < 0.02 or k0 >= G:
                img = gen[min(G, k0)]
                exact += 1
            elif f > 0.98:
                img = gen[min(G, k0 + 1)]
                exact += 1
            else:
                img = interp.between(k0, gen[k0], gen[k0 + 1], f)
                interpolated += 1
            img = from_model(img, plan, W, H)
            gain = (1 - tau) * cp_s[0] + tau * cp_e[0]
            off = (1 - tau) * cp_s[1] + tau * cp_e[1]
            img = apply_color(img, gain, off)
            img = sharpen(img, (1 - tau) * sh_s + tau * sh_e)
            img = add_grain(img, (1 - tau) * gr_s + tau * gr_e, rng)
            if head and j < blend:
                wgen = smoothstep((j + 1) / (blend + 1))
                img = np.clip(wgen * img.astype(np.float32) + (1 - wgen) * head[j].astype(np.float32) + 0.5,
                              0, 255).astype(np.uint8)
            back = count - 1 - j
            if tail and back < blend:
                wgen = smoothstep((back + 1) / (blend + 1))
                orig = tail[blend - 1 - back]
                img = np.clip(wgen * img.astype(np.float32) + (1 - wgen) * orig.astype(np.float32) + 0.5,
                              0, 255).astype(np.uint8)
            writer.write(img)
            if on_progress and (j % 10 == 0 or j == count - 1):
                on_progress((j + 1) / count)
    finally:
        writer.close()
    if writer.count != count:
        raise StitchError(f"تکهٔ میانی {writer.count} فریم شد؛ {count} لازم بود.")
    return {
        "frames": count, "exact": exact, "interpolated": interpolated,
        "color_start": {"gain": [round(float(x), 3) for x in cp_s[0]], "offset": [round(float(x), 2) for x in cp_s[1]]},
        "color_end": {"gain": [round(float(x), 3) for x in cp_e[0]], "offset": [round(float(x), 2) for x in cp_e[1]]},
        "sharpen": [round(sh_s, 2), round(sh_e, 2)], "grain": [round(gr_s, 2), round(gr_e, 2)],
        "blend": blend,
    }


def model_inputs(plan: dict, info: dict, base_path, out_dir: Path, tag: str) -> tuple[list[str], list[str], dict]:
    """تصویرهای مرزی (و زمینه) به اندازهٔ مدل، PNG، با نام‌های یکتا. برمی‌گرداند (نام‌های ابتدا، انتها، {نام: مسیر})."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    def save(indices, side):
        names = []
        for k, i in enumerate(indices):
            frame = media.read_frame(base_path, info, i)
            name = f"nmregen_{tag}_{side}{k}.png"
            path = out_dir / name
            media.png(to_model(frame, plan), path)
            files[name] = str(path)
            names.append(name)
        return names

    return save(plan["start_ctx"], "s"), save(plan["end_ctx"], "e"), files
