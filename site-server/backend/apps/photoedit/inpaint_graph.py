"""گرافِ ComfyUI برای «پرکردنِ هوشمند» (حذفِ شیء / ساختنِ محتوا در ناحیهٔ ماسک‌شده) با FLUX.

ماژولِ خالص: نه Django می‌خواهد نه شبکه؛ با «توانایی‌های گره» (``ComputeNode.capabilities``) کار می‌کند و گرافِ
فرمتِ API ِ ComfyUI برمی‌گرداند. فقط نودهای هستهٔ ComfyUI به کار می‌روند (بی نودِ سفارشی).

    caps = node.capabilities       # {"comfy_nodes": [...], "comfy_models": {"checkpoints": [...], "unet": [...], ...}}
    choice = choose(caps)          # کدام مدل؛ GraphError (پیامِ فارسی) اگر هیچ FLUX ای نیست
    graph = build(choice, "nmgf_x_image.png", "nmgf_x_mask.png", prompt, seed, (1024, 768))
    check_nodes(graph, caps.get("comfy_nodes"))   # نودهایی که روی گره نیست
    validate(graph)                # پیوندهای گراف سالم‌اند؟ (برای آزمون)

اولویتِ مدل (هرگز دانلود نمی‌کنیم؛ فقط آنچه روی گره نصب است):

1. «FLUX.1 Fill dev» (نامی که «flux» و «fill» دارد) به‌صورتِ چک‌پوینت یا UNET — راهنمایی ۳۰، ۲۰ گام؛
2. FLUX.1 dev (چک‌پوینتِ مالک: «FLUX.1 [dev] FP8.safetensors») با DifferentialDiffusion + InpaintModelConditioning
   (noise_mask) — راهنمایی ۴، ۲۸ گام؛ اگر فقط به‌صورتِ UNET باشد با DualCLIPLoader + VAELoader؛
3. گره هنوز چیزی گزارش نکرده (ComfyUI خاموش بوده) ⇐ همان چک‌پوینتِ پیش‌فرضِ مالک.
"""
from __future__ import annotations

import re

#: چک‌پوینتِ FLUX dev ِ نصب‌شدهٔ مالک (همان flux_img_edit_v1.json در services/comfyui/workflows)
DEFAULT_DEV_CKPT = "FLUX.1 [dev] FP8.safetensors"
DEFAULT_CLIP_L = "clip_l.safetensors"
DEFAULT_T5_FP16 = "t5xxl_fp16.safetensors"
DEFAULT_T5_FP8 = "t5xxl_fp8_e4m3fn.safetensors"
DEFAULT_VAE = "ae.safetensors"

FILL_GUIDANCE, FILL_STEPS = 30.0, 20
DEV_GUIDANCE, DEV_STEPS = 4.0, 28
FILENAME_PREFIX = "nm/genfill"

#: پرامپتِ «حذف و پر کردن با پس‌زمینه» وقتی کاربر چیزی ننوشته (FLUX نگاتیو ندارد ⇒ مثبت می‌نویسیم)
DEFAULT_PROMPT = ("clean empty background, seamless natural continuation of the surrounding scene, "
                  "same lighting, texture and colours, nothing else")
PROMPT_SUFFIX = "seamlessly blended with the surrounding image, matching light and texture"

#: خروجی‌های هر نود (برای وارسیِ پیوندها)
OUTPUTS = {
    "LoadImage": 2, "LoadImageMask": 1, "GrowMask": 1, "CheckpointLoaderSimple": 3, "UNETLoader": 1,
    "DualCLIPLoader": 1, "VAELoader": 1, "CLIPTextEncode": 1, "FluxGuidance": 1, "DifferentialDiffusion": 1,
    "InpaintModelConditioning": 3, "KSampler": 1, "VAEDecode": 1, "SaveImage": 0,
}

_NOT_DEV = ("fill", "canny", "depth", "redux", "schnell", "kontext", "controlnet", "lora", "vae")


class GraphError(Exception):
    """متنش برای کاربر است (فارسی)."""


# ───────────────────────────── انتخابِ مدل

def is_fill(name: str) -> bool:
    n = str(name).lower()
    return "flux" in n and "fill" in n


def is_dev(name: str) -> bool:
    n = str(name).lower()
    return "flux" in n and "dev" in n and not any(b in n for b in _NOT_DEV)


def _models(caps) -> dict | None:
    """``caps["comfy_models"]`` ⇐ {کلید: فهرست یا None}؛ None = گره چیزی گزارش نکرده."""
    cm = caps.get("comfy_models") if isinstance(caps, dict) else None
    if not isinstance(cm, dict):
        return None
    return {k: ([str(x) for x in cm[k]] if isinstance(cm.get(k), list) else None)
            for k in ("checkpoints", "unet", "clip", "vae", "loras")}


def _vram(caps) -> float | None:
    v = caps.get("vram_total_mb") if isinstance(caps, dict) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _want_fp8(vram_mb: float | None) -> bool:
    """روی کارتِ کوچک/ناشناخته نسخهٔ fp8 را ترجیح بده (حافظهٔ کمتر)؛ از ~۲۴ گیگ به بالا دقتِ کامل."""
    return not (vram_mb and vram_mb >= 23000)


def _sort(names: list[str], vram_mb: float | None) -> list[str]:
    want = _want_fp8(vram_mb)
    return sorted(names, key=lambda n: ("fp8" in n.lower()) != want)      # پایدار: ترتیبِ فهرست حفظ می‌شود


def _encoders(models: dict | None, vram_mb: float | None) -> tuple[dict | None, list[str], str]:
    """(نام‌ها یا None، یادداشت‌ها، دلیلِ ناممکن بودن). فهرستِ گزارش‌نشده ⇒ نامِ پیش‌فرض."""
    notes: list[str] = []
    want8 = _want_fp8(vram_mb)
    clips = (models or {}).get("clip")
    vaes = (models or {}).get("vae")
    if clips is None:
        clip_l, t5 = DEFAULT_CLIP_L, DEFAULT_T5_FP8 if want8 else DEFAULT_T5_FP16
        notes.append("نامِ فایل‌های CLIP روی گره گزارش نشده؛ نامِ پیش‌فرض به کار رفت")
    else:
        ls = [n for n in clips if "clip_l" in n.lower()]
        ts = sorted([n for n in clips if "t5xxl" in n.lower()], key=lambda n: ("fp8" in n.lower()) != want8)
        if not ls or not ts:
            return None, notes, "فایل‌های clip_l / t5xxl روی گره پیدا نشد"
        clip_l, t5 = ls[0], ts[0]
    if vaes is None:
        vae = DEFAULT_VAE
        notes.append("نامِ فایلِ VAE روی گره گزارش نشده؛ نامِ پیش‌فرض به کار رفت")
    else:
        exact = [n for n in vaes if n.lower().replace("\\", "/").split("/")[-1] == DEFAULT_VAE]
        flux = [n for n in vaes if "flux" in n.lower() and ("vae" in n.lower() or re.search(r"(^|[\W_])ae([\W_]|$)", n.lower()))]
        ae = [n for n in vaes if re.search(r"(^|[\W_])ae([\W_]|$)", n.lower())]
        pick = exact or flux or ae
        if not pick:
            return None, notes, "فایلِ VAE ِ FLUX (ae.safetensors) روی گره پیدا نشد"
        vae = pick[0]
    return {"clip_l": clip_l, "t5": t5, "vae": vae}, notes, ""


def _weight_dtype(name: str, vram_mb: float | None) -> str:
    """مدلِ بزرگِ غیر fp8 روی کارتِ کوچک ⇐ بارگذاری با fp8 (حافظه نصف)."""
    if "fp8" in name.lower():
        return "default"
    return "fp8_e4m3fn" if _want_fp8(vram_mb) else "default"


def _short(names: list[str] | None, limit: int = 8) -> str:
    names = names or []
    if not names:
        return "هیچ"
    more = f" و {len(names) - limit} موردِ دیگر" if len(names) > limit else ""
    return "، ".join(f"«{n}»" for n in names[:limit]) + more


def choose(caps) -> dict:
    """انتخابِ مدل از روی توانایی‌های گره ⇐ {kind, loader, ckpt/unet, clip_l, t5, vae, guidance, steps, …، required_nodes}.

    ``kind``: "fill" | "dev"؛ ``loader``: "checkpoint" | "unet"؛ ``assumed``: True وقتی گره چیزی گزارش نکرده.
    اگر هیچ FLUX ای (fill یا dev) گزارش نشده باشد، GraphError با فهرستِ آنچه پیدا شد.
    """
    models = _models(caps)
    vram = _vram(caps)
    reported = bool(models and (models["checkpoints"] is not None or models["unet"] is not None))
    skipped: list[str] = []

    def done(**c):
        c.setdefault("assumed", False)
        c["notes"] = list(c.get("notes") or []) + skipped
        c["vram_mb"] = vram
        c["required_nodes"] = required_nodes(c)
        return c

    if not reported:
        return done(kind="dev", loader="checkpoint", ckpt=DEFAULT_DEV_CKPT, unet=None, clip_l=None, t5=None, vae=None,
                    guidance=DEV_GUIDANCE, steps=DEV_STEPS, sampler="euler", scheduler="simple", assumed=True,
                    label=f"FLUX dev (چک‌پوینتِ پیش‌فرض «{DEFAULT_DEV_CKPT}»)",
                    notes=["گره هنوز فهرستِ مدل‌هایش را نداده؛ چک‌پوینتِ FLUX dev ِ پیش‌فرض فرض شد"])
    ckpts = models["checkpoints"] or []
    unets = models["unet"] or []

    for name in _sort([n for n in ckpts if is_fill(n)], vram):
        return done(kind="fill", loader="checkpoint", ckpt=name, unet=None, clip_l=None, t5=None, vae=None,
                    guidance=FILL_GUIDANCE, steps=FILL_STEPS, sampler="euler", scheduler="normal",
                    label=f"FLUX Fill (چک‌پوینتِ «{name}»)", notes=[])
    for name in _sort([n for n in unets if is_fill(n)], vram):
        enc, notes, why = _encoders(models, vram)
        if enc is None:
            skipped.append(f"مدلِ Fill «{name}» نصب است ولی {why}؛ کنار گذاشته شد")
            continue
        return done(kind="fill", loader="unet", ckpt=None, unet=name, weight_dtype=_weight_dtype(name, vram), **enc,
                    guidance=FILL_GUIDANCE, steps=FILL_STEPS, sampler="euler", scheduler="normal",
                    label=f"FLUX Fill (UNET «{name}»)", notes=notes)
    for name in _sort([n for n in ckpts if is_dev(n)], vram):
        return done(kind="dev", loader="checkpoint", ckpt=name, unet=None, clip_l=None, t5=None, vae=None,
                    guidance=DEV_GUIDANCE, steps=DEV_STEPS, sampler="euler", scheduler="simple",
                    label=f"FLUX dev (چک‌پوینتِ «{name}»)", notes=[])
    for name in _sort([n for n in unets if is_dev(n)], vram):
        enc, notes, why = _encoders(models, vram)
        if enc is None:
            skipped.append(f"مدلِ dev «{name}» نصب است ولی {why}؛ کنار گذاشته شد")
            continue
        return done(kind="dev", loader="unet", ckpt=None, unet=name, weight_dtype=_weight_dtype(name, vram), **enc,
                    guidance=DEV_GUIDANCE, steps=DEV_STEPS, sampler="euler", scheduler="simple",
                    label=f"FLUX dev (UNET «{name}»)", notes=notes)

    found = (f"چک‌پوینت‌ها: {_short(ckpts)}؛ مدل‌های UNET: {_short(unets)}"
             if (ckpts or unets) else "سرور هیچ چک‌پوینت و مدلِ UNET ای گزارش نکرد")
    extra = (" " + " ".join(skipped)) if skipped else ""
    raise GraphError(
        "روی سرورِ پردازش مدلِ FLUX نصب نیست، برای همین «پرکردنِ هوشمند» انجام نمی‌شود. "
        "باید FLUX.1 dev (مثلاً «FLUX.1 [dev] FP8.safetensors» در پوشهٔ checkpoints) یا FLUX.1 Fill dev "
        f"روی ComfyUI نصب باشد. آنچه سرور گزارش کرد — {found}.{extra}")


# ───────────────────────────── ساختِ گراف

def grow_for(size) -> int:
    """بزرگ‌کردنِ ماسک (پیکسلِ اندازهٔ مدل) تا لبه/سایهٔ شیء هم پوشیده شود."""
    w, h = size
    return int(max(4, min(24, round(max(int(w), int(h)) * 0.015))))


def effective_prompt(prompt: str) -> str:
    p = " ".join(str(prompt or "").split()).strip()
    if not p:
        return DEFAULT_PROMPT
    return p if p.endswith((".", "!", "؟", "?")) else f"{p}, {PROMPT_SUFFIX}"


def build(choice: dict, image_name: str, mask_name: str, prompt: str, seed: int, size, *,
          filename_prefix: str = FILENAME_PREFIX) -> dict:
    """گرافِ API ِ ComfyUI. ``size`` = (پهنا، ارتفاع) ِ تصویری که به گره می‌رود؛ فقط برای اندازهٔ GrowMask."""
    g: dict = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "LoadImageMask", "inputs": {"image": mask_name, "channel": "red"}},
        "3": {"class_type": "GrowMask", "inputs": {"mask": ["2", 0], "expand": grow_for(size), "tapered_corners": True}},
    }
    if choice["loader"] == "checkpoint":
        g["10"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": choice["ckpt"]}}
        model, clip, vae = ["10", 0], ["10", 1], ["10", 2]
    else:
        g["10"] = {"class_type": "UNETLoader", "inputs": {"unet_name": choice["unet"],
                                                         "weight_dtype": choice.get("weight_dtype") or "default"}}
        g["11"] = {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": choice["t5"], "clip_name2": choice["clip_l"],
                                                              "type": "flux"}}
        g["12"] = {"class_type": "VAELoader", "inputs": {"vae_name": choice["vae"]}}
        model, clip, vae = ["10", 0], ["11", 0], ["12", 0]
    g["20"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": effective_prompt(prompt)}}
    g["21"] = {"class_type": "FluxGuidance", "inputs": {"conditioning": ["20", 0], "guidance": float(choice["guidance"])}}
    g["22"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": ""}}
    g["23"] = {"class_type": "DifferentialDiffusion", "inputs": {"model": model}}
    g["24"] = {"class_type": "InpaintModelConditioning", "inputs": {
        "positive": ["21", 0], "negative": ["22", 0], "vae": vae, "pixels": ["1", 0], "mask": ["3", 0],
        "noise_mask": True}}
    g["25"] = {"class_type": "KSampler", "inputs": {
        "model": ["23", 0], "positive": ["24", 0], "negative": ["24", 1], "latent_image": ["24", 2],
        "seed": int(seed), "steps": int(choice["steps"]), "cfg": 1.0, "sampler_name": choice.get("sampler") or "euler",
        "scheduler": choice.get("scheduler") or "simple", "denoise": 1.0}}
    g["26"] = {"class_type": "VAEDecode", "inputs": {"samples": ["25", 0], "vae": vae}}
    g["27"] = {"class_type": "SaveImage", "inputs": {"images": ["26", 0], "filename_prefix": filename_prefix}}
    return g


def required_nodes(choice: dict) -> list[str]:
    """نودهای لازم برای این انتخاب (از خودِ گراف، تا یک منبع حقیقت باشد)."""
    g = build(choice, "x.png", "m.png", "", 0, (512, 512))
    return sorted({n["class_type"] for n in g.values()})


def check_nodes(graph: dict, comfy_nodes) -> list[str]:
    """نام‌هایی از نودهای گراف که روی گره نیست. فهرستِ نودهای گره ناشناخته/خالی ⇒ [] (نمی‌دانیم)."""
    if not isinstance(comfy_nodes, (list, tuple, set)) or not comfy_nodes:
        return []
    have = set(map(str, comfy_nodes))
    return sorted({n["class_type"] for n in graph.values() if n["class_type"] not in have})


def validate(graph: dict) -> list[str]:
    """مشکلاتِ گراف (فهرستِ خالی = سالم): هر پیوند باید به نود و شمارهٔ خروجیِ موجود برسد، نودِ ناشناخته و دور نباشد."""
    problems: list[str] = []
    if not isinstance(graph, dict) or not graph:
        return ["گراف خالی است"]
    deps: dict[str, set[str]] = {}
    for nid, node in graph.items():
        if not isinstance(node, dict) or "class_type" not in node or not isinstance(node.get("inputs"), dict):
            problems.append(f"نودِ {nid} شکلِ درست ندارد")
            continue
        if node["class_type"] not in OUTPUTS:
            problems.append(f"نودِ {nid}: کلاسِ ناشناخته {node['class_type']}")
        deps[nid] = set()
        for key, val in node["inputs"].items():
            if isinstance(val, list):
                if len(val) != 2 or not isinstance(val[0], str) or not isinstance(val[1], int):
                    problems.append(f"نودِ {nid}.{key}: پیوندِ نامعتبر {val!r}")
                    continue
                src, idx = val
                if src not in graph:
                    problems.append(f"نودِ {nid}.{key}: پیوند به نودِ ناموجودِ {src}")
                    continue
                arity = OUTPUTS.get(graph[src].get("class_type"), 0)
                if not 0 <= idx < arity:
                    problems.append(f"نودِ {nid}.{key}: خروجیِ {idx} در {graph[src].get('class_type')} نیست")
                deps[nid].add(src)
    seen: dict[str, int] = {}

    def visit(n: str) -> bool:
        if seen.get(n) == 1:
            return True
        if seen.get(n) == 2:
            return False
        seen[n] = 1
        if any(visit(d) for d in deps.get(n, ()) if d in deps):
            return True
        seen[n] = 2
        return False

    if any(visit(n) for n in deps):
        problems.append("گراف دور دارد")
    if not any(n.get("class_type") == "SaveImage" for n in graph.values() if isinstance(n, dict)):
        problems.append("SaveImage ندارد")
    return problems
