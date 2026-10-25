"""نقشهٔ تولید و گرافِ ComfyUI برای یک تکه.

مدل‌ها (هر دو Apache-2.0، هر دو با نودهای خودِ ComfyUI، بی نودِ سفارشی):

* ``wan22_flf`` — **Wan 2.2 I2V A14B** با نودِ ``WanFirstLastFrameToVideo`` (همان قالبِ رسمیِ FLF2V ِ ComfyUI):
  دو مدلِ high/low ِ fp8_scaled که پروفایل‌های ویدیوی فعلی هم دارند + LoRA ی ۴مرحله‌ایِ lightx2v ِ Wan 2.2
  (اگر روی گره نباشد، LoRA ی ۸مرحله‌ایِ Wan 2.1 که الان هست). کیفیتِ درز بهتر، کندتر.
* ``fun_inp_13b`` — **Wan 2.1 Fun-InP 1.3B** با ``WanFunInpaintToVideo`` (همان منطقِ اول/آخر + CLIP-Vision):
  کلِ مدل در ۱۲ گیگ جا می‌شود، چند برابر سریع‌تر، جزئیاتِ کمتر.

قاعده‌های زمان (Wan 16fps می‌سازد، طولِ هر تکه 4k+1 فریم، حداکثر ۸۱):

* بازهٔ زمانی از «آخرین فریمِ قبل از برش» (b) تا «اولین فریمِ بعد از برش» (a) است: D = t(a) - t(b).
* fps ِ مدل ۱۶ است، یا اگر fps ِ منبع تقسیم بر عددی صحیح کمتر از ۱۲٪ با ۱۶ فرق کند همان (۳۰ ⇐ ۱۵، ۶۰ ⇐ ۱۵،
  ۳۲ ⇐ ۱۶) تا فریم‌های مدل روی فریم‌های منبع بنشینند. G = نزدیک‌ترین مضربِ ۴ به D×fps؛ مدل G+1 فریم می‌سازد که
  اولی b و آخری a است (سرعتِ حرکت حداکثر چند درصد عوض می‌شود).
* G بزرگ‌تر از ۸۰ ⇐ چند تکهٔ زنجیره‌ای: تکهٔ اول از b (I2V)، هر تکهٔ بعد از آخرین فریم(های) تکهٔ قبل، و تکهٔ آخر
  FLF که دقیقاً به a می‌رسد — همه در **یک** گراف، تا مدل‌ها یک بار بار شوند.
* «زمینهٔ حرکت» (آزمایشی): به‌جای یک فریم، ۵ فریمِ منبع در هر سر (هم‌ترازِ لایه‌های زمانیِ VAE) به مدل داده
  می‌شود تا جهت و سرعتِ حرکتِ دو طرف را ببیند. نودِ FLF ِ ComfyUI دسته‌ای از تصویرها را برای اول/آخر می‌پذیرد.
"""
from __future__ import annotations

import math

NATIVE_FPS = 16.0
MAX_LEN = 81                     # طولِ امنِ هر تکه (۵ ثانیه در ۱۶fps)
FPS_TOLERANCE = 0.12

NEGATIVE = ("flicker, jitter, sudden jump, scene cut, abrupt change, morphing, warping, deformed, distorted face, "
            "extra limbs, blurry, low quality, watermark, text, subtitles, logo, color shift, overexposed, frozen frame")

#: پرونده‌های هر موتور روی گره (نامِ فایل؛ زیرپوشه‌ها را روی خودِ گره از فهرستِ ComfyUI پیدا می‌کنیم)
WAN22 = {
    "high": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    "low": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    "lora_high": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    "lora_low": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    "lora_21": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae": "wan_2.1_vae.safetensors",
}
FUN13 = {
    "unet": "wan2.1_fun_inp_1.3B_bf16.safetensors",
    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae": "wan_2.1_vae.safetensors",
    "clip_vision": "clip_vision_h.safetensors",
}

ENGINES = {
    "wan22_flf": {
        "label": "Wan 2.2 A14B — کیفیتِ بالا",
        "short": "باکیفیت",
        "license": "Apache-2.0 (Wan-AI/Wan2.2-I2V-A14B؛ LoRA ی lightx2v هم Apache-2.0)",
        "qualities": {"480p": 832 * 480, "720p": 1280 * 720},
        # ۷۲۰p با ۸۱ فریم روی ۱۲ گیگ جا نمی‌شود ⇐ تکه‌های کوتاه‌تر (۳ ثانیه)
        "max_len": {"480p": 81, "720p": 49},
        "node": "WanFirstLastFrameToVideo",
        "files": {"unet": [WAN22["high"], WAN22["low"]], "clip": [WAN22["clip"]], "vae": [WAN22["vae"]]},
        # ثانیه بر فریم روی RTX 3060 (۴ گام، ۴۸۰p) + سربارِ هر تکه (بارکردن/جابه‌جاییِ دو مدلِ ۱۴ گیگی)؛
        # بعد از چند اجرا از زمان‌های واقعیِ همین گره یاد گرفته می‌شود
        "sec_per_frame": {"480p": 4.5, "720p": 12.0},
        "overhead": 150.0,
    },
    "fun_inp_13b": {
        "label": "Wan 2.1 Fun-InP 1.3B — سریع",
        "short": "سریع",
        "license": "Apache-2.0 (alibaba-pai/Wan2.1-Fun-1.3B-InP)",
        "qualities": {"480p": 832 * 480},
        "max_len": {"480p": 81},
        "node": "WanFunInpaintToVideo",
        "files": {"unet": [FUN13["unet"]], "clip": [FUN13["clip"]], "vae": [FUN13["vae"]],
                  "clip_vision": [FUN13["clip_vision"]]},
        "sec_per_frame": {"480p": 1.4},
        "overhead": 40.0,
    },
}


class PlanError(ValueError):
    pass


def round16(x: float) -> int:
    return max(16, int(round(x / 16.0)) * 16)


def gen_size(width: int, height: int, area: int) -> tuple[int, int]:
    aspect = width / height
    return round16(math.sqrt(area * aspect)), round16(math.sqrt(area / aspect))


def canvas(width: int, height: int, w: int, h: int) -> tuple[int, int, int, int]:
    """بومِ پدشده (Wp, Hp, left, top) با نسبتِ ابعادِ مدل که کلِ فریمِ منبع را در بر دارد.

    رفت: منبع ⇐ پدِ بازتابی تا Wp×Hp ⇐ w×h. برگشت: w×h ⇐ Wp×Hp ⇐ برشِ همان پد. چون دو طرف یک نگاشت‌اند،
    هندسهٔ تکه دقیقاً روی منبع می‌نشیند (نه بزرگ‌نماییِ چندپیکسلی در درز) و هیچ لبه‌ای از تصویر کم نمی‌شود."""
    if width * h >= height * w:
        wp, hp = width, max(height, int(math.ceil(width * h / w)))
    else:
        wp, hp = max(width, int(math.ceil(height * w / h))), height
    return wp, hp, (wp - width) // 2, (hp - height) // 2


def model_fps(src_fps: float) -> float:
    k = max(1, round(src_fps / NATIVE_FPS))
    cand = src_fps / k
    return cand if abs(cand / NATIVE_FPS - 1) <= FPS_TOLERANCE else NATIVE_FPS


def _split(total: int, caps: list[int]) -> list[int] | None:
    """total (مضربِ ۴) ⇐ len(caps) سهمِ مضربِ ۴، هرکدام ≤ سقفِ خودش و ≥ ۴، تا جای ممکن مساوی."""
    k = len(caps)
    units = total // 4
    caps_u = [c // 4 for c in caps]
    if units < k or sum(caps_u) < units or min(caps_u) < 1:
        return None
    share = [units // k + (1 if i < units % k else 0) for i in range(k)]
    # سرریزِ سهمِ بالاتر از سقف به بقیه
    for _ in range(k):
        over = 0
        for i in range(k):
            if share[i] > caps_u[i]:
                over += share[i] - caps_u[i]
                share[i] = caps_u[i]
        if not over:
            break
        for i in range(k):
            room = caps_u[i] - share[i]
            take = min(room, over)
            share[i] += take
            over -= take
    if sum(share) != units:
        return None
    return [s * 4 for s in share]


def make_plan(info: dict, start: int, end: int, *, engine: str = "wan22_flf", quality: str = "480p",
              context: int = 1, blend: int | None = None, max_seconds: float = 20.0) -> dict:
    """همهٔ عددهای یک بازسازی (بدونِ دیتابیس؛ تست‌پذیر)."""
    from .media import frame_time

    if engine not in ENGINES:
        raise PlanError("موتورِ ناشناخته: %s" % engine)
    spec = ENGINES[engine]
    if quality not in spec["qualities"]:
        quality = next(iter(spec["qualities"]))
    n = int(info["n_frames"])
    if not (0 <= start <= end < n):
        raise PlanError("بازه باید داخلِ ویدیو باشد (فریمِ ۰ تا %d)." % (n - 1))
    if start == 0 and end == n - 1:
        raise PlanError("کلِ ویدیو انتخاب شده؛ دستِ کم یک سر باید بماند تا تکه به آن بچسبد.")
    fps = float(info["fps"])
    b, a = start - 1, end + 1
    has_start, has_end = b >= 0, a < n
    t_b, t_a = frame_time(info, b), frame_time(info, a)
    span = t_a - t_b
    if span - 1.0 / fps > max_seconds + 1e-6:
        raise PlanError("بازهٔ انتخابی %.1f ثانیه است؛ حداکثر %.0f ثانیه." % (span - 1.0 / fps, max_seconds))

    f_m = model_fps(fps)
    G = max(4, 4 * int(round(span * f_m / 4.0)))
    context = 5 if int(context or 1) >= 5 else 1
    # زمینهٔ حرکت از فریم‌های منبع: باید آن‌قدر فریم قبل/بعد از برش باشد
    f_eff = G / span
    step_src = fps / f_eff                                   # چند فریمِ منبع بینِ دو فریمِ مدل
    cs = context if has_start and (b - round((context - 1) * step_src)) >= 0 else 1
    ce = context if has_end and (a + round((context - 1) * step_src)) <= n - 1 else 1
    cc = context                                             # زمینهٔ بینِ تکه‌های زنجیره

    max_len = int(spec.get("max_len", {}).get(quality, MAX_LEN))
    chunks = None
    for k in range(1, 64):
        caps = []
        for i in range(k):
            c_start = (cs if has_start else 1) if i == 0 else cc
            c_end = ce if (i == k - 1 and has_end) else 1
            caps.append(max_len - 1 - (c_start - 1) - (c_end - 1))
        g = _split(G, caps)
        if g:
            chunks = []
            p = 0
            for i, gi in enumerate(g):
                c_start = (cs if has_start else 1) if i == 0 else cc
                c_end = ce if (i == k - 1 and has_end) else 1
                length = gi + 1 + (c_start - 1) + (c_end - 1)
                chunks.append({"index": i, "p0": p, "p1": p + gi, "length": length,
                               "ctx_start": c_start if (i > 0 or has_start) else 0,
                               "ctx_end": c_end if (i == k - 1 and has_end) else 0,
                               "first_gen_index": p - (c_start - 1)})
                p += gi
            break
    if not chunks:
        raise PlanError("نقشهٔ تکه‌ها ساخته نشد.")

    # فریم‌های منبعی که به مدل داده می‌شوند (شمارهٔ فریم): زمینهٔ ابتدا … b و a … زمینهٔ انتها
    start_ctx = [b - int(round((cs - 1 - j) * step_src)) for j in range(cs)] if has_start else []
    end_ctx = [a + int(round(j * step_src)) for j in range(ce)] if has_end else []

    W, H = int(info["width"]), int(info["height"])
    w, h = gen_size(W, H, spec["qualities"][quality])
    wp, hp, left, top = canvas(W, H, w, h)

    # هر فریمِ جایگزین (start…end) در کجای خطِ زمانیِ مدل می‌نشیند (۰ = b، G = a)
    positions = [(frame_time(info, j) - t_b) / span * G for j in range(start, end + 1)]
    count = end - start + 1
    if blend is None:
        blend = int(round(0.12 * fps))
    blend = max(0, min(int(blend), 8, (count - 1) // 3 if count > 3 else 0))

    frames_total = sum(c["length"] for c in chunks)
    sec = spec["sec_per_frame"][quality] * frames_total + spec["overhead"] * len(chunks)
    return {
        "engine": engine, "quality": quality,
        "start": start, "end": end, "count": count,
        "before": b, "after": a, "has_start": has_start, "has_end": has_end,
        "span": span, "fps": fps, "model_fps": f_m, "effective_fps": f_eff,
        "speed": f_eff / f_m, "G": G,
        "context": context, "start_ctx": start_ctx, "end_ctx": end_ctx,
        "chunks": chunks, "gen_size": [w, h], "canvas": [wp, hp, left, top],
        "positions": positions, "blend": blend,
        "frames_total": frames_total, "estimate_seconds": round(sec),
    }


# ───────────────────────────── گراف

def _pick(names: list | None, wanted: str) -> str:
    """نامِ فایل همان‌طور که ComfyUI ِ گره گزارش داده (شاید با زیرپوشه، مثلاً «wan\\x.safetensors»)."""
    for n in names or []:
        if n.replace("\\", "/").rsplit("/", 1)[-1] == wanted:
            return n
    return wanted


def lora_mode(loras: list | None) -> str:
    base = {str(n).replace("\\", "/").rsplit("/", 1)[-1] for n in (loras or [])}
    if WAN22["lora_high"] in base and WAN22["lora_low"] in base:
        return "wan22_4step"
    if WAN22["lora_21"] in base:
        return "wan21_8step"
    if loras is None:              # گره فهرست نداده ⇐ همان که video.json دانلود می‌کند
        return "wan22_4step"
    return "none"


class _G:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.n = 0

    def add(self, cls: str, **inputs) -> str:
        self.n += 1
        nid = str(self.n)
        self.nodes[nid] = {"class_type": cls, "inputs": inputs}
        return nid


def _batch(g: _G, names: list[str]) -> list | None:
    """LoadImage برای هر فایل و ImageBatch ِ پشتِ هم ⇐ یک دسته به ترتیب."""
    if not names:
        return None
    out = [g.add("LoadImage", image=names[0]), 0]
    for name in names[1:]:
        nxt = g.add("LoadImage", image=name)
        out = [g.add("ImageBatch", image1=out, image2=[nxt, 0]), 0]
    return out


def build_graph(plan: dict, *, prompt: str, negative: str = NEGATIVE, seed: int = 1, start_names: list | None = None,
                end_names: list | None = None, prefix: str = "nmregen/x", models: dict | None = None) -> dict:
    """گرافِ API ِ ComfyUI برای همهٔ تکه‌ها. خروجیِ هر تکه = SaveImage با پیشوندِ «c<i>» (PNG ِ بی‌اتلاف)."""
    models = models or {}
    unets, loras, clips, vaes, cvs = (models.get(k) for k in ("unet", "loras", "clip", "vae", "clip_vision"))
    w, h = plan["gen_size"]
    g = _G()
    engine = plan["engine"]
    if engine == "wan22_flf":
        mode = lora_mode(loras)
        hi = g.add("UNETLoader", unet_name=_pick(unets, WAN22["high"]), weight_dtype="default")
        lo = g.add("UNETLoader", unet_name=_pick(unets, WAN22["low"]), weight_dtype="default")
        if mode == "wan22_4step":
            hi = g.add("LoraLoaderModelOnly", model=[hi, 0], lora_name=_pick(loras, WAN22["lora_high"]), strength_model=1.0)
            lo = g.add("LoraLoaderModelOnly", model=[lo, 0], lora_name=_pick(loras, WAN22["lora_low"]), strength_model=1.0)
            steps, split, cfg, shift = 4, 2, 1.0, 5.0
        elif mode == "wan21_8step":
            hi = g.add("LoraLoaderModelOnly", model=[hi, 0], lora_name=_pick(loras, WAN22["lora_21"]), strength_model=3.0)
            lo = g.add("LoraLoaderModelOnly", model=[lo, 0], lora_name=_pick(loras, WAN22["lora_21"]), strength_model=1.5)
            steps, split, cfg, shift = 8, 4, 1.0, 8.0
        else:
            steps, split, cfg, shift = 20, 10, 3.5, 8.0
        hi = g.add("ModelSamplingSD3", model=[hi, 0], shift=shift)
        lo = g.add("ModelSamplingSD3", model=[lo, 0], shift=shift)
        clip = g.add("CLIPLoader", clip_name=_pick(clips, WAN22["clip"]), type="wan", device="default")
        vae = g.add("VAELoader", vae_name=_pick(vaes, WAN22["vae"]))
        cvl = None
        sampler = {"mode": mode, "steps": steps, "split": split, "cfg": cfg, "shift": shift}
    elif engine == "fun_inp_13b":
        m = g.add("UNETLoader", unet_name=_pick(unets, FUN13["unet"]), weight_dtype="default")
        m = g.add("ModelSamplingSD3", model=[m, 0], shift=8.0)
        clip = g.add("CLIPLoader", clip_name=_pick(clips, FUN13["clip"]), type="wan", device="default")
        vae = g.add("VAELoader", vae_name=_pick(vaes, FUN13["vae"]))
        cvl = g.add("CLIPVisionLoader", clip_name=_pick(cvs, FUN13["clip_vision"]))
        sampler = {"mode": "fun_inp", "steps": 20, "cfg": 6.0, "shift": 8.0}
    else:
        raise PlanError("موتورِ ناشناخته: %s" % engine)
    pos = g.add("CLIPTextEncode", clip=[clip, 0], text=prompt)
    neg = g.add("CLIPTextEncode", clip=[clip, 0], text=negative)

    prev_decode, prev_first = None, 0
    for ch in plan["chunks"]:
        i = ch["index"]
        last = i == len(plan["chunks"]) - 1
        if i == 0:
            start_img = _batch(g, start_names or []) if plan["has_start"] else None
        else:
            c = ch["ctx_start"]
            start_img = [g.add("ImageFromBatch", image=prev_decode, batch_index=ch["first_gen_index"] - prev_first,
                               length=c), 0]
        end_img = _batch(g, end_names or []) if (last and plan["has_end"]) else None
        common = dict(positive=[pos, 0], negative=[neg, 0], vae=[vae, 0], width=w, height=h, length=ch["length"],
                      batch_size=1)
        if start_img:
            common["start_image"] = start_img
        if end_img:
            common["end_image"] = end_img
        if engine == "wan22_flf":
            cond = g.add("WanFirstLastFrameToVideo", **common)
            k1 = g.add("KSamplerAdvanced", model=[hi, 0], add_noise="enable", noise_seed=int(seed) + i,
                       steps=sampler["steps"], cfg=sampler["cfg"], sampler_name="euler", scheduler="simple",
                       positive=[cond, 0], negative=[cond, 1], latent_image=[cond, 2], start_at_step=0,
                       end_at_step=sampler["split"], return_with_leftover_noise="enable")
            lat = g.add("KSamplerAdvanced", model=[lo, 0], add_noise="disable", noise_seed=int(seed) + i,
                        steps=sampler["steps"], cfg=sampler["cfg"], sampler_name="euler", scheduler="simple",
                        positive=[cond, 0], negative=[cond, 1], latent_image=[k1, 0], start_at_step=sampler["split"],
                        end_at_step=10000, return_with_leftover_noise="disable")
        else:
            ref = start_img or end_img
            if ref is not None:
                # آخرین تصویرِ دستهٔ ابتدا (= فریمِ b یا آخرین فریمِ تکهٔ قبل)؛ اندیسِ منفی در ComfyUI ِ قدیمی پذیرفته نمی‌شد
                idx = (ch["ctx_start"] - 1 if i > 0 else max(0, len(start_names or []) - 1)) if ref is start_img else 0
                one = [g.add("ImageFromBatch", image=ref, batch_index=idx, length=1), 0]
                common["clip_vision_output"] = [g.add("CLIPVisionEncode", clip_vision=[cvl, 0], image=one, crop="none"), 0]
            cond = g.add("WanFunInpaintToVideo", **common)
            lat = g.add("KSampler", model=[m, 0], seed=int(seed) + i, steps=sampler["steps"], cfg=sampler["cfg"],
                        sampler_name="uni_pc", scheduler="simple", positive=[cond, 0], negative=[cond, 1],
                        latent_image=[cond, 2], denoise=1.0)
        dec = g.add("VAEDecode", samples=[lat, 0], vae=[vae, 0])
        g.add("SaveImage", images=[dec, 0], filename_prefix=f"{prefix}/c{i}")
        prev_decode, prev_first = [dec, 0], ch["first_gen_index"]
    plan["sampler"] = sampler
    return g.nodes


def required_files(engine: str, mode: str | None = None) -> dict:
    spec = ENGINES[engine]
    files = {k: list(v) for k, v in spec["files"].items()}
    if engine == "wan22_flf":
        files["loras"] = [WAN22["lora_high"], WAN22["lora_low"]] if mode in (None, "wan22_4step") else [WAN22["lora_21"]]
    return files


def output_index(plan: dict, chunk: int, k: int) -> int:
    """شمارهٔ فریم در خطِ زمانیِ مدل (۰…G) برای k-امین تصویرِ خروجیِ تکهٔ chunk."""
    return plan["chunks"][chunk]["first_gen_index"] + k
