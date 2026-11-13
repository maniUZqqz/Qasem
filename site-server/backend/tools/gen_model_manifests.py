#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generates processing/downloads/{image,upscale,control,depth,video-extra}.json - the curated ComfyUI / Hugging Face packages.

    python backend/tools/gen_model_manifests.py            # query the Hugging Face API, (re)write the manifests
    python backend/tools/gen_model_manifests.py --verify   # + HEAD/Range every URL on huggingface.co and hf-mirror.com

Every file is pinned to the commit the Hugging Face API reported when this was run; size and sha256 are the LFS metadata of
that commit (https://huggingface.co/api/models/<repo>/tree/<commit>?recursive=1), small non-LFS files are hashed here.
Nothing is ever downloaded in full by this script (--verify reads one byte per URL). The downloader
(processing/download_models.py) verifies size + sha256 of every file again on the node.

License classes (package_info.license_class):
  open           permissive (Apache-2.0, MIT, BSD, OpenRAIL++) - may be downloaded automatically
  restricted     usable under conditions that the owner has to read (e.g. LTX-Video: companies >= $10M revenue need a licence)
  noncommercial  weights may not be used commercially (FLUX.1 dev family, CC-BY-NC-SA, S-Lab) or the licence could not be verified
restricted / noncommercial packages are always optional and are never downloaded by the automatic mode or by --all.
"""
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "processing", "downloads")
GENERATED = "2026-11-13"
UA = {"User-Agent": "nm-model-catalog/1"}
C = "{COMFYUI}\\models\\"
M = "{MODELS}\\"


class _Follow308(urllib.request.HTTPRedirectHandler):
    """Python < 3.11 does not follow HTTP 308 (hf-mirror.com answers with it); treat it like 307."""

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_307(req, fp, 307, msg, headers)


_OPENER = urllib.request.build_opener(_Follow308)


def http_json(url):
    with _OPENER.open(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return json.load(r)


_info, _tree = {}, {}


def repo_info(repo):
    if repo not in _info:
        _info[repo] = http_json("https://huggingface.co/api/models/%s" % repo)
    return _info[repo]


def repo_tree(repo, sha):
    if (repo, sha) not in _tree:
        rows = http_json("https://huggingface.co/api/models/%s/tree/%s?recursive=1" % (repo, sha))
        _tree[(repo, sha)] = {r["path"]: r for r in rows if r.get("type") == "file"}
    return _tree[(repo, sha)]


def sha256_url(url):
    h = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def F(pkg, slug, repo, path, dest, title, lic, aliases=(), optional=True):
    """One file of a Hugging Face repo -> a manifest item (size + sha256 from the API)."""
    info = repo_info(repo)
    sha = info["sha"]
    row = repo_tree(repo, sha).get(path)
    if row is None:
        raise SystemExit("%s: %s not found at %s" % (repo, path, sha))
    lfs = row.get("lfs") or {}
    url = "{HF}/%s/resolve/%s/%s" % (info["id"], sha, path)
    digest = lfs.get("oid") or sha256_url(url.replace("{HF}", "https://huggingface.co"))
    item = {"id": "%s:%s" % (pkg, slug), "package": pkg, "kind": "file", "title": title,
            "urls": [url], "dest": dest, "size": int(lfs.get("size") or row["size"]), "sha256": digest,
            "license": lic, "source": "https://huggingface.co/%s/blob/%s/%s" % (info["id"], sha, path)}
    if aliases:
        item["aliases"] = list(aliases)
    if optional:
        item["optional"] = True
    return item


def G(pkg, slug, url, ref, dest, title, lic, size, aliases=()):
    item = {"id": "%s:%s" % (pkg, slug), "package": pkg, "kind": "git", "title": title, "url": url, "ref": ref,
            "dest": dest, "size": size, "license": lic, "optional": True}
    if aliases:
        item["aliases"] = list(aliases)
    return item


def vram(fit, gb, note):
    return {"fit": fit, "gb": gb, "note_fa": note}


OFFLOAD12 = "کاملاً در حافظهٔ کارت (۱۲ گیگابایت) جا نمی‌شود؛ ComfyUI بخشی را در رم نگه می‌دارد، کمی کندتر ولی کار می‌کند."

# ───────────────────────────────────────────────────────────── the catalog
# package -> display group, Persian text, licence, VRAM, features (keys of apps/compute/model_packages.py FEATURES), needs

T5 = ["t5xxl_fp8_e4m3fn.safetensors", "t5xxl_fp8_e4m3fn_scaled.safetensors", "t5xxl_fp16.safetensors"]
FLUX_DEV_ALIASES = ["FLUX.1 [dev] FP8.safetensors", "flux1-dev-fp8.safetensors", "flux1-dev.safetensors",
                    "flux1-dev-fp8-e4m3fn.safetensors"]


def build():
    files = {}

    # ───────────── image.json
    files["image.json"] = {
        "group": "image",
        "title": "Image generation for ComfyUI: FLUX.1 schnell / dev / Fill / Kontext (fp8), SDXL base + RealVisXL, Z-Image Turbo",
        "license_note": ("FLUX.1 schnell (Apache-2.0), SDXL 1.0 (CreativeML OpenRAIL++-M), RealVisXL V5.0 (OpenRAIL++), Z-Image Turbo "
                         "(Apache-2.0), the VAE and the text encoders (Apache-2.0 / MIT) may be used commercially. FLUX.1 dev, Fill dev and "
                         "Kontext dev are under the FLUX.1 [dev] Non-Commercial License: the weights are not for commercial use (the images "
                         "you make with them may be used as the licence allows) - they are optional, never automatic. Files ComfyUI "
                         "already has (any models subfolder, also under another listed name) are never downloaded again."),
        "generated": GENERATED,
        "packages": {
            "flux-common": "FLUX text encoders (T5-XXL fp8, CLIP-L) and the ae VAE - shared by every FLUX model",
            "flux-schnell": "FLUX.1 schnell fp8 (Apache-2.0) - 4-step images",
            "flux-dev": "FLUX.1 dev fp8 (non-commercial) - best FLUX quality",
            "flux-fill": "FLUX.1 Fill dev fp8 (non-commercial) - inpainting / outpainting",
            "flux-kontext": "FLUX.1 Kontext dev fp8 (non-commercial) - instruction-based image editing",
            "sdxl-base": "SDXL 1.0 base + fp16-fix VAE (OpenRAIL++)",
            "sdxl-realvis": "RealVisXL V5.0 fp16 (OpenRAIL++) - photorealistic SDXL",
            "zimage-turbo": "Z-Image Turbo bf16 + Qwen3-4B text encoder + ae VAE (Apache-2.0)",
        },
        "package_info": {
            "flux-common": {
                "display": "image", "priority": 10, "license": "Apache-2.0 / MIT", "license_class": "open",
                "title_fa": "FLUX — رمزگذارهای متن و VAE (مشترکِ همهٔ مدل‌های FLUX)",
                "note_fa": "T5-XXL (fp8)، CLIP-L و ae؛ بدونِ این‌ها هیچ مدلِ FLUX اجرا نمی‌شود. یک بار گرفته می‌شود و همهٔ مدل‌های FLUX از آن استفاده می‌کنند.",
                "vram": vram("full", 6, "T5 در رم می‌ماند و فقط هنگامِ رمزگذاریِ متن به کارت می‌آید."),
                "features": ["image_studio", "image_edit"], "needs": [], "auto": False,
            },
            "flux-schnell": {
                "display": "image", "priority": 11, "license": "Apache-2.0", "license_class": "open",
                "title_fa": "FLUX.1 schnell (fp8) — تصویرِ سریع در ۴ گام",
                "note_fa": "استفادهٔ تجاری آزاد (Apache-2.0). در ۴ گام تصویر می‌سازد؛ برای پیش‌نمایش، بندانگشتی، پستِ شبکه‌های اجتماعی و کارهای پرتعداد مناسب است.",
                "vram": vram("offload", 12, OFFLOAD12),
                "features": ["image_studio", "thumbnails"], "needs": ["flux-common"], "auto": True,
            },
            "flux-dev": {
                "display": "image", "priority": 40, "license": "FLUX.1 [dev] Non-Commercial", "license_class": "noncommercial",
                "title_fa": "FLUX.1 dev (fp8) — بهترین کیفیتِ FLUX",
                "note_fa": "مجوزِ غیرتجاری: خودِ مدل را نمی‌شود برای کارِ تجاری سرویس داد (خروجی‌ها طبقِ مجوزِ سازنده). اگر «FLUX.1 [dev] FP8» از قبل روی ComfyUI باشد، نصب‌شده حساب می‌شود.",
                "vram": vram("offload", 12, OFFLOAD12),
                "features": ["image_studio"], "needs": ["flux-common"], "auto": False,
            },
            "flux-fill": {
                "display": "image", "priority": 41, "license": "FLUX.1 [dev] Non-Commercial", "license_class": "noncommercial",
                "title_fa": "FLUX.1 Fill dev (fp8) — پرکردنِ بخشی از تصویر (inpaint / outpaint)",
                "note_fa": "پاک‌کردن و جایگزینیِ بخشی از عکس و گسترشِ بومِ تصویر. مجوزِ غیرتجاری. فایل بازنشرِ غیررسمیِ fp8 از مدلِ اصلی است؛ در Hugging Face خودِ سازنده نسخهٔ fp8 ندارد.",
                "vram": vram("offload", 12, OFFLOAD12),
                "features": ["image_edit"], "needs": ["flux-common"], "auto": False,
                "provenance": "third-party fp8 conversion of black-forest-labs/FLUX.1-Fill-dev",
            },
            "flux-kontext": {
                "display": "image", "priority": 42, "license": "FLUX.1 [dev] Non-Commercial", "license_class": "noncommercial",
                "title_fa": "FLUX.1 Kontext dev (fp8) — ویرایشِ تصویر با دستور",
                "note_fa": "با یک جمله عکس را ویرایش می‌کند و چهره/محصول را نگه می‌دارد (ثباتِ شخصیت). مجوزِ غیرتجاری.",
                "vram": vram("offload", 12, OFFLOAD12),
                "features": ["image_edit", "consistency"], "needs": ["flux-common"], "auto": False,
            },
            "sdxl-base": {
                "display": "image", "priority": 20, "license": "CreativeML OpenRAIL++-M", "license_class": "open",
                "title_fa": "SDXL 1.0 پایه + VAEِ fp16",
                "note_fa": "مدلِ پایهٔ سبک‌های طراحی؛ با ControlNet و IP-Adapter کار می‌کند. استفادهٔ تجاری مجاز (با محدودیتِ استفادهٔ مضر).",
                "vram": vram("full", 8, "کاملاً روی کارتِ ۱۲ گیگابایتی اجرا می‌شود."),
                "features": ["design_styles", "thumbnails"], "needs": [], "auto": False,
            },
            "sdxl-realvis": {
                "display": "image", "priority": 21, "license": "CreativeML OpenRAIL++-M", "license_class": "open",
                "title_fa": "RealVisXL V5.0 — SDXLِ واقع‌گرا",
                "note_fa": "عکسِ واقع‌گرا از آدم و محصول؛ مجوزِ OpenRAIL++ (تجاری مجاز).",
                "vram": vram("full", 8, "کاملاً روی کارتِ ۱۲ گیگابایتی اجرا می‌شود."),
                "features": ["design_styles", "thumbnails"], "needs": [], "auto": False,
            },
            "zimage-turbo": {
                "display": "image", "priority": 22, "license": "Apache-2.0", "license_class": "open",
                "title_fa": "Z-Image Turbo — تصویرِ سریع و باکیفیت",
                "note_fa": "مدلِ ۶ میلیاردیِ Apache-2.0 با ۸ گام؛ جایگزینِ آزادِ FLUX. متنِ انگلیسی و چینی را خوب می‌نویسد.",
                "vram": vram("offload", 12, OFFLOAD12),
                "features": ["image_studio", "thumbnails"], "needs": [], "auto": False,
            },
        },
        "items": [
            F("flux-common", "t5xxl_fp8", "comfyanonymous/flux_text_encoders", "t5xxl_fp8_e4m3fn.safetensors",
              C + "text_encoders\\t5xxl_fp8_e4m3fn.safetensors", "T5-XXL text encoder fp8 e4m3fn (Apache-2.0)", "Apache-2.0", aliases=T5),
            F("flux-common", "clip_l", "comfyanonymous/flux_text_encoders", "clip_l.safetensors",
              C + "text_encoders\\clip_l.safetensors", "CLIP-L text encoder (MIT)", "MIT"),
            F("flux-common", "ae_vae", "Comfy-Org/Z-Image-Turbo", "split_files/vae/ae.safetensors",
              C + "vae\\ae.safetensors", "FLUX ae VAE (same bytes as black-forest-labs/FLUX.1-schnell ae.safetensors, Apache-2.0; "
              "fetched from an ungated repo)", "Apache-2.0", aliases=["ae.sft"]),
            F("flux-schnell", "schnell_fp8", "Kijai/flux-fp8", "flux1-schnell-fp8-e4m3fn.safetensors",
              C + "diffusion_models\\flux1-schnell-fp8-e4m3fn.safetensors", "FLUX.1 schnell diffusion model fp8 e4m3fn (Apache-2.0)",
              "Apache-2.0", aliases=["flux1-schnell-fp8.safetensors", "flux1-schnell.safetensors"]),
            F("flux-dev", "dev_fp8", "Kijai/flux-fp8", "flux1-dev-fp8-e4m3fn.safetensors",
              C + "diffusion_models\\flux1-dev-fp8-e4m3fn.safetensors", "FLUX.1 dev diffusion model fp8 e4m3fn (FLUX.1 [dev] Non-Commercial)",
              "FLUX.1 [dev] Non-Commercial", aliases=FLUX_DEV_ALIASES),
            F("flux-fill", "fill_dev_fp8", "wjndd/flux1-fill-dev-fp8", "flux1-fill-dev-fp8.safetensors",
              C + "diffusion_models\\flux1-fill-dev-fp8.safetensors", "FLUX.1 Fill dev fp8 e4m3fn (FLUX.1 [dev] Non-Commercial)",
              "FLUX.1 [dev] Non-Commercial", aliases=["flux1-fill-dev.safetensors", "FLUX.1-Fill-dev_fp8.safetensors"]),
            F("flux-kontext", "kontext_fp8", "Comfy-Org/Flux-1-Kontext-Dev", "split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors",
              C + "diffusion_models\\flux1-dev-kontext_fp8_scaled.safetensors", "FLUX.1 Kontext dev fp8 scaled (FLUX.1 [dev] Non-Commercial)",
              "FLUX.1 [dev] Non-Commercial", aliases=["flux1-kontext-dev.safetensors"]),
            F("sdxl-base", "sdxl_base", "stabilityai/stable-diffusion-xl-base-1.0", "sd_xl_base_1.0.safetensors",
              C + "checkpoints\\sd_xl_base_1.0.safetensors", "SDXL 1.0 base checkpoint (CreativeML OpenRAIL++-M)", "OpenRAIL++-M"),
            F("sdxl-base", "sdxl_vae_fp16", "madebyollin/sdxl-vae-fp16-fix", "sdxl_vae.safetensors",
              C + "vae\\sdxl_vae.safetensors", "SDXL VAE fp16-fix (MIT) - no NaN in half precision", "MIT", aliases=["sdxl.vae.safetensors"]),
            F("sdxl-realvis", "realvisxl_v5", "SG161222/RealVisXL_V5.0", "RealVisXL_V5.0_fp16.safetensors",
              C + "checkpoints\\RealVisXL_V5.0_fp16.safetensors", "RealVisXL V5.0 fp16 checkpoint (CreativeML OpenRAIL++-M)", "OpenRAIL++-M"),
            F("zimage-turbo", "zimage_bf16", "Comfy-Org/Z-Image-Turbo", "split_files/diffusion_models/z_image_turbo_bf16.safetensors",
              C + "diffusion_models\\z_image_turbo_bf16.safetensors", "Z-Image Turbo diffusion model bf16 (Apache-2.0)", "Apache-2.0"),
            F("zimage-turbo", "qwen3_4b_fp8", "Comfy-Org/Z-Image-Turbo", "split_files/text_encoders/qwen_3_4b_fp8_mixed.safetensors",
              C + "text_encoders\\qwen_3_4b_fp8_mixed.safetensors", "Qwen3-4B text encoder fp8 mixed (Apache-2.0)", "Apache-2.0"),
            F("zimage-turbo", "ae_vae", "Comfy-Org/Z-Image-Turbo", "split_files/vae/ae.safetensors",
              C + "vae\\ae.safetensors", "ae VAE (same file as flux-common:ae_vae - fetched once)", "Apache-2.0", aliases=["ae.sft"]),
        ],
    }

    # ───────────── upscale.json
    files["upscale.json"] = {
        "group": "upscale",
        "title": "Upscalers and face restoration for ComfyUI (Real-ESRGAN x4plus, 4x-UltraSharp, 4x NMKD-Siax, GFPGAN, CodeFormer)",
        "license_note": ("Real-ESRGAN x4plus is BSD-3-Clause and GFPGAN v1.4 is Apache-2.0 (code and weights of TencentARC; the face data they were "
                         "trained on carries its own terms) - commercial use allowed. 4x-UltraSharp is CC BY-NC-SA 4.0 and CodeFormer is under the "
                         "S-Lab License 1.0 (non-commercial). The licence of 4x NMKD-Siax could not be verified from its Hugging Face mirror, so it "
                         "is treated as non-commercial. Non-commercial packages are optional and never automatic. The face models need a ComfyUI "
                         "face-restore custom node to be used inside ComfyUI (not installed automatically: its pip requirements would touch "
                         "ComfyUI's torch); the files are placed where such nodes look for them."),
        "generated": GENERATED,
        "packages": {
            "esrgan-x4plus": "Real-ESRGAN x4plus (BSD-3-Clause) - 4x upscaler, safetensors",
            "ultrasharp-4x": "4x-UltraSharp (CC BY-NC-SA 4.0) - sharp 4x upscaler, safetensors",
            "nmkd-siax-4x": "4x NMKD-Siax 200k - natural 4x upscaler (licence unverified)",
            "face-restore": "GFPGAN v1.4 + facexlib detection/parsing models - face restoration",
            "codeformer": "CodeFormer v0.1.0 (S-Lab, non-commercial) - face restoration",
        },
        "package_info": {
            "esrgan-x4plus": {
                "display": "upscale", "priority": 10, "license": "BSD-3-Clause", "license_class": "open",
                "title_fa": "Real-ESRGAN x4plus — بزرگ‌کردنِ ۴ برابریِ عکس",
                "note_fa": "کوچک (۶۴ مگابایت) و سریع؛ بهترین انتخابِ عمومی برای بزرگ‌کردنِ عکسِ محصول و آدم. مجوزِ BSD-3 (تجاری مجاز).",
                "vram": vram("full", 2, "خیلی کم‌حجم؛ هم‌زمان با مدل‌های دیگر هم جا می‌شود."),
                "features": ["photo_enhance", "thumbnails"], "needs": [], "auto": True,
            },
            "ultrasharp-4x": {
                "display": "upscale", "priority": 40, "license": "CC BY-NC-SA 4.0", "license_class": "noncommercial",
                "title_fa": "4x-UltraSharp — بزرگ‌کردنِ تیز",
                "note_fa": "لبه‌ها را تیزتر از Real-ESRGAN می‌کند. مجوزِ غیرتجاری (CC BY-NC-SA 4.0).",
                "vram": vram("full", 2, "خیلی کم‌حجم."),
                "features": ["photo_enhance"], "needs": [], "auto": False,
            },
            "nmkd-siax-4x": {
                "display": "upscale", "priority": 41, "license": "unverified", "license_class": "noncommercial",
                "title_fa": "4x NMKD-Siax — بزرگ‌کردنِ طبیعی",
                "note_fa": "جزئیاتِ طبیعی و کم‌نویز. مجوزِ این فایل را نتوانستیم تأیید کنیم؛ تا روشن‌شدن غیرتجاری حساب می‌شود.",
                "vram": vram("full", 2, "خیلی کم‌حجم."),
                "features": ["photo_enhance"], "needs": [], "auto": False,
            },
            "face-restore": {
                "display": "upscale", "priority": 20, "license": "Apache-2.0", "license_class": "open",
                "title_fa": "ترمیمِ چهره — GFPGAN v1.4 (+ تشخیصِ چهره)",
                "note_fa": "چهرهٔ تارِ عکس را واضح می‌کند. برای استفاده در ComfyUI به یک نودِ ترمیمِ چهره نیاز است (خودکار نصب نمی‌شود)؛ فایل‌ها در پوشه‌ای که این نودها می‌خوانند گذاشته می‌شود.",
                "vram": vram("full", 2, "کم‌حجم."),
                "features": ["face_restore"], "needs": [], "auto": False,
            },
            "codeformer": {
                "display": "upscale", "priority": 42, "license": "S-Lab License 1.0", "license_class": "noncommercial",
                "title_fa": "ترمیمِ چهره — CodeFormer",
                "note_fa": "ترمیمِ چهره با کنترلِ وفاداری. مجوزِ غیرتجاری (S-Lab).",
                "vram": vram("full", 2, "کم‌حجم."),
                "features": ["face_restore"], "needs": [], "auto": False,
            },
        },
        "items": [
            F("esrgan-x4plus", "realesrgan_x4plus", "Comfy-Org/Real-ESRGAN", "RealESRGAN_x4plus.safetensors",
              C + "upscale_models\\RealESRGAN_x4plus.safetensors", "Real-ESRGAN x4plus (BSD-3-Clause)", "BSD-3-Clause",
              aliases=["RealESRGAN_x4plus.pth", "realesrgan_x4plus.pth", "RealESRGAN_x4.pth"]),
            F("ultrasharp-4x", "ultrasharp", "Kim2091/UltraSharp", "4x-UltraSharp.safetensors",
              C + "upscale_models\\4x-UltraSharp.safetensors", "4x-UltraSharp (CC BY-NC-SA 4.0)", "CC BY-NC-SA 4.0",
              aliases=["4x-UltraSharp.pth", "4xUltrasharp_4xUltrasharpV10.pt"]),
            F("nmkd-siax-4x", "siax", "gemasai/4x_NMKD-Siax_200k", "4x_NMKD-Siax_200k.pth",
              C + "upscale_models\\4x_NMKD-Siax_200k.pth", "4x NMKD-Siax 200k (licence unverified)", "unverified"),
            F("face-restore", "gfpgan_v14", "leonelhs/gfpgan", "GFPGANv1.4.pth",
              C + "facerestore_models\\GFPGANv1.4.pth", "GFPGAN v1.4 (Apache-2.0; mirror of the official file, sha256 matches TencentARC's release)",
              "Apache-2.0"),
            F("face-restore", "facexlib_detection", "leonelhs/facexlib", "detection_Resnet50_Final.pth",
              C + "facedetection\\detection_Resnet50_Final.pth", "facexlib face detector RetinaFace-ResNet50 (MIT)", "MIT"),
            F("face-restore", "facexlib_parsing", "leonelhs/facexlib", "parsing_parsenet.pth",
              C + "facedetection\\parsing_parsenet.pth", "facexlib face parser ParseNet (MIT)", "MIT"),
            F("codeformer", "codeformer_v010", "leonelhs/gfpgan", "CodeFormer.pth",
              C + "facerestore_models\\codeformer-v0.1.0.pth", "CodeFormer v0.1.0 (S-Lab License 1.0, non-commercial)", "S-Lab License 1.0",
              aliases=["codeformer.pth", "CodeFormer.pth"]),
        ],
    }

    # ───────────── control.json
    files["control.json"] = {
        "group": "control",
        "title": "Control and consistency for ComfyUI: ControlNet union (SDXL, FLUX), IP-Adapter for SDXL + its custom node",
        "license_note": ("ControlNet-Union SDXL (xinsir, Apache-2.0), IP-Adapter (h94, Apache-2.0) and the CLIP ViT-H image encoder (MIT) may be "
                         "used commercially. The FLUX ControlNet-Union-Pro 2.0 (Shakker-Labs) follows the FLUX.1 [dev] Non-Commercial License. "
                         "The IP-Adapter custom node (cubiq/ComfyUI_IPAdapter_plus, GPL-3.0) is only installed on this computer (a git checkout "
                         "of a pinned commit into ComfyUI's custom_nodes; nothing is redistributed) and needs a ComfyUI restart. PuLID is not "
                         "listed on purpose: it needs InsightFace weights (research / non-commercial) and a native build of insightface on "
                         "Windows, which cannot be installed reliably without a person; FLUX Kontext (image group) covers character consistency."),
        "generated": GENERATED,
        "packages": {
            "controlnet-union-sdxl": "ControlNet union promax for SDXL (xinsir, Apache-2.0): pose, depth, canny, lines ... in one model",
            "controlnet-union-flux": "ControlNet union Pro 2.0 for FLUX.1 dev (Shakker-Labs, non-commercial)",
            "ipadapter-sdxl": "IP-Adapter plus + plus-face for SDXL (ViT-H) and the CLIP ViT-H image encoder",
            "nodes-ipadapter-plus": "ComfyUI_IPAdapter_plus custom node (pinned commit) - needs a ComfyUI restart",
        },
        "package_info": {
            "controlnet-union-sdxl": {
                "display": "control", "priority": 10, "license": "Apache-2.0", "license_class": "open",
                "title_fa": "ControlNet یکپارچه برای SDXL (xinsir Promax)",
                "note_fa": "یک مدل به‌جای ده‌ها ControlNet: ژستِ بدن، عمق، لبه (canny)، خط، اسکریبل و … برای حفظِ چیدمان و ژستِ تصویر. تجاری مجاز.",
                "vram": vram("full", 10, "کنارِ SDXL روی کارتِ ۱۲ گیگابایتی جا می‌شود."),
                "features": ["design_styles", "consistency"], "needs": ["sdxl-base"], "auto": False,
            },
            "controlnet-union-flux": {
                "display": "control", "priority": 40, "license": "FLUX.1 [dev] Non-Commercial", "license_class": "noncommercial",
                "title_fa": "ControlNet یکپارچه برای FLUX (Shakker Union Pro 2.0)",
                "note_fa": "کنترلِ ژست/عمق/لبه روی FLUX dev. مجوزِ غیرتجاری. با FLUX روی ۱۲ گیگابایت کند می‌شود.",
                "vram": vram("tight", 14, "همراهِ FLUX بیشترِ کارت را می‌گیرد؛ کند ولی ممکن است."),
                "features": ["image_edit", "consistency"], "needs": ["flux-common"], "auto": False,
            },
            "ipadapter-sdxl": {
                "display": "control", "priority": 20, "license": "Apache-2.0 / MIT", "license_class": "open",
                "title_fa": "IP-Adapter برای SDXL — تکرارِ سبک و چهره از روی عکسِ مرجع",
                "note_fa": "با یک عکسِ مرجع، سبک یا چهرهٔ همان را در تصویرِ تازه نگه می‌دارد (ثباتِ شخصیت و سبک). به نودِ IPAdapter plus و راه‌اندازیِ دوبارهٔ ComfyUI نیاز دارد (همراهش نصب می‌شود).",
                "vram": vram("full", 10, "کنارِ SDXL جا می‌شود."),
                "features": ["design_styles", "consistency"], "needs": ["sdxl-base", "nodes-ipadapter-plus"], "auto": False,
            },
            "nodes-ipadapter-plus": {
                "display": "control", "priority": 21, "license": "GPL-3.0 (local install only)", "license_class": "open",
                "title_fa": "نودِ ComfyUI — IPAdapter plus",
                "note_fa": "کدِ نود در پوشهٔ custom_nodes نصب می‌شود (commit ثابت). بعد از نصب ComfyUI را یک بار دوباره راه بیندازید.",
                "vram": vram("full", 0, "کدِ کوچک؛ حافظه‌ای نمی‌گیرد."),
                "features": ["design_styles", "consistency"], "needs": [], "auto": False, "needs_restart": True,
            },
        },
        "items": [
            F("controlnet-union-sdxl", "xinsir_union_promax", "xinsir/controlnet-union-sdxl-1.0", "diffusion_pytorch_model_promax.safetensors",
              C + "controlnet\\controlnet-union-sdxl-1.0-promax.safetensors", "xinsir ControlNet union promax for SDXL (Apache-2.0)", "Apache-2.0",
              aliases=["xinsir-controlnet-union-sdxl-promax.safetensors", "diffusion_pytorch_model_promax.safetensors"]),
            F("controlnet-union-flux", "shakker_union_pro2", "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0", "diffusion_pytorch_model.safetensors",
              C + "controlnet\\FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors", "Shakker-Labs ControlNet Union Pro 2.0 for FLUX.1 dev "
              "(FLUX.1 [dev] Non-Commercial)", "FLUX.1 [dev] Non-Commercial",
              aliases=["flux_shakker_labs_union_pro-fp8_e4m3fn.safetensors", "FLUX.1-dev-ControlNet-Union-Pro.safetensors"]),
            F("ipadapter-sdxl", "plus_sdxl_vith", "h94/IP-Adapter", "sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors",
              C + "ipadapter\\ip-adapter-plus_sdxl_vit-h.safetensors", "IP-Adapter plus SDXL ViT-H (Apache-2.0)", "Apache-2.0"),
            F("ipadapter-sdxl", "plus_face_sdxl_vith", "h94/IP-Adapter", "sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors",
              C + "ipadapter\\ip-adapter-plus-face_sdxl_vit-h.safetensors", "IP-Adapter plus FACE SDXL ViT-H (Apache-2.0)", "Apache-2.0"),
            F("ipadapter-sdxl", "clip_vision_vith", "Comfy-Org/CLIP-ViT-H-14-laion2B-s32B-b79K_repackaged",
              "split_files/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
              C + "clip_vision\\CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors", "CLIP ViT-H/14 image encoder (MIT; same bytes as h94/IP-Adapter "
              "models/image_encoder/model.safetensors)", "MIT", aliases=["CLIP-ViT-H-14-laion2B-s32B-b79K.bin"]),
            G("nodes-ipadapter-plus", "code", "https://github.com/cubiq/ComfyUI_IPAdapter_plus", "a0f451a5113cf9becb0847b92884cb10cbdec0ef",
              "{COMFYUI}\\custom_nodes\\ComfyUI_IPAdapter_plus", "ComfyUI_IPAdapter_plus custom node, pinned commit (GPL-3.0, local install only)",
              "GPL-3.0", 4000000, aliases=["comfyui_ipadapter_plus", "ComfyUI_IPAdapter_plus"]),
        ],
    }

    # ───────────── depth.json
    files["depth.json"] = {
        "group": "depth",
        "title": "Depth for 3D and parallax: Depth-Anything-V2-Small (Apache-2.0) as safetensors (torch) and ONNX (onnxruntime, DirectML)",
        "license_note": ("Depth-Anything-V2-Small is Apache-2.0 (commercial use allowed). The Base / Large / Giant models are CC BY-NC 4.0 and are "
                         "deliberately not listed. Files go to the node's own models folder (not ComfyUI): the 3D / parallax code on the node loads "
                         "them from there; the ONNX file runs through the same onnxruntime the background-removal models use."),
        "generated": GENERATED,
        "packages": {"depth-anything-v2-small": "Depth-Anything-V2-Small (25 M parameters): torch safetensors + ONNX fp32"},
        "package_info": {
            "depth-anything-v2-small": {
                "display": "depth", "priority": 10, "license": "Apache-2.0", "license_class": "open",
                "title_fa": "Depth Anything V2 Small — نقشهٔ عمق از یک عکس",
                "note_fa": "برای ویدیوی سه‌بعدی، پارالکس و جداکردنِ پیش‌زمینه از پس‌زمینه. کوچک (حدود ۲۰۰ مگابایت)، Apache-2.0؛ مدل‌های بزرگ‌تر این خانواده غیرتجاری‌اند و عمداً نیامده‌اند.",
                "vram": vram("full", 1, "خیلی سبک؛ روی کارت یا حتی پردازنده کار می‌کند."),
                "features": ["depth_3d"], "needs": [], "auto": True,
            },
        },
        "items": [
            F("depth-anything-v2-small", "hf_weights", "depth-anything/Depth-Anything-V2-Small-hf", "model.safetensors",
              M + "depth-anything-v2-small\\model.safetensors", "Depth-Anything-V2-Small weights, transformers format (Apache-2.0)", "Apache-2.0"),
            F("depth-anything-v2-small", "hf_config", "depth-anything/Depth-Anything-V2-Small-hf", "config.json",
              M + "depth-anything-v2-small\\config.json", "Depth-Anything-V2-Small config.json", "Apache-2.0"),
            F("depth-anything-v2-small", "hf_preprocessor", "depth-anything/Depth-Anything-V2-Small-hf", "preprocessor_config.json",
              M + "depth-anything-v2-small\\preprocessor_config.json", "Depth-Anything-V2-Small preprocessor_config.json", "Apache-2.0"),
            F("depth-anything-v2-small", "onnx_fp32", "onnx-community/depth-anything-v2-small", "onnx/model.onnx",
              M + "depth-anything-v2-small\\onnx\\model.onnx", "Depth-Anything-V2-Small ONNX fp32 (Apache-2.0)", "Apache-2.0"),
        ],
    }

    # ───────────── video-extra.json
    files["video-extra.json"] = {
        "group": "video-extra",
        "title": "More video for ComfyUI: Wan 2.2 TI2V-5B (fits 12 GB), LTX-Video 2B distilled fp8, RIFE / FILM frame interpolation",
        "license_note": ("Wan 2.2 TI2V-5B (Wan-AI, repackaged by Comfy-Org) is Apache-2.0. LTX-Video is under the LTXV Open Weights License 0.X: "
                         "free for any purpose for entities under US$10M annual revenue; larger companies need a paid commercial licence from "
                         "Lightricks - so it is optional and never automatic. RIFE (MIT) and FILM (Apache-2.0) are repackaged by Comfy-Org for "
                         "ComfyUI's built-in frame-interpolation nodes. The umT5 text encoder and the Wan 2.1 VAE are shared with the Wan 2.2 "
                         "A14B package (fetched once)."),
        "generated": GENERATED,
        "packages": {
            "wan22-ti2v-5b": "Wan 2.2 TI2V-5B fp16 + Wan 2.2 VAE + umT5 fp8 (Apache-2.0) - text/image to video, 12 GB friendly",
            "ltx-video-distilled": "LTX-Video 2B 0.9.8 distilled fp8 + spatial upscaler (LTXV Open Weights License)",
            "frame-interp": "RIFE v4.25 / v4.25 lite and FILM fp16 for ComfyUI frame interpolation (MIT / Apache-2.0)",
        },
        "package_info": {
            "wan22-ti2v-5b": {
                "display": "video", "priority": 20, "license": "Apache-2.0", "license_class": "open",
                "title_fa": "Wan 2.2 TI2V ۵B — ویدیو از متن یا عکس (سبک)",
                "note_fa": "مدلِ ۵ میلیاردیِ ویدیو با خروجیِ ۷۲۰p و ۲۴ فریم؛ از Wan 2.2 A14B خیلی سبک‌تر است و در کارتِ ۱۲ گیگابایتی راحت اجرا می‌شود. Apache-2.0.",
                "vram": vram("full", 10, "برای کارتِ ۱۲ گیگابایتی ساخته شده؛ کمی ازش بیرون نمی‌زند."),
                "features": ["video_ai"], "needs": [], "auto": False,
            },
            "ltx-video-distilled": {
                "display": "video", "priority": 40, "license": "LTXV Open Weights License 0.X", "license_class": "restricted",
                "title_fa": "LTX-Video ۲B (distilled، fp8) — ویدیوی بسیار سریع",
                "note_fa": "چند ثانیه ویدیو در چند ده ثانیه. مجوز: برای هر کاری آزاد است مگر شرکت‌های با درآمدِ سالانهٔ بالای ۱۰ میلیون دلار که قراردادِ جدا می‌خواهند.",
                "vram": vram("full", 8, "کاملاً روی کارتِ ۱۲ گیگابایتی اجرا می‌شود."),
                "features": ["video_ai"], "needs": ["flux-common"], "auto": False,
            },
            "frame-interp": {
                "display": "video", "priority": 10, "license": "MIT / Apache-2.0", "license_class": "open",
                "title_fa": "RIFE و FILM — نرم‌کردنِ حرکتِ ویدیو (فریمِ میانی)",
                "note_fa": "از ۲۴ به ۴۸ یا ۶۰ فریم؛ برای ویدیوهای هوش مصنوعی و اسلوموشن. ComfyUI نودِ داخلی‌اش را دارد؛ بسیار کوچک (حدود ۱۱۵ مگابایت).",
                "vram": vram("full", 2, "خیلی سبک."),
                "features": ["smooth_motion", "video_ai"], "needs": [], "auto": True,
            },
        },
        "items": [
            F("wan22-ti2v-5b", "ti2v_5b_fp16", "Comfy-Org/Wan-2.2", "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
              C + "diffusion_models\\wan2.2_ti2v_5B_fp16.safetensors", "Wan 2.2 TI2V-5B diffusion model fp16 (Apache-2.0)", "Apache-2.0"),
            F("wan22-ti2v-5b", "wan22_vae", "Comfy-Org/Wan-2.2", "split_files/vae/wan2.2_vae.safetensors",
              C + "vae\\wan2.2_vae.safetensors", "Wan 2.2 VAE (used by TI2V-5B, Apache-2.0)", "Apache-2.0"),
            F("wan22-ti2v-5b", "umt5_xxl_fp8", "Comfy-Org/Wan-2.2", "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
              C + "text_encoders\\umt5_xxl_fp8_e4m3fn_scaled.safetensors", "umT5-XXL text encoder fp8 (shared with wan22-flf, Apache-2.0)",
              "Apache-2.0"),
            F("ltx-video-distilled", "ltxv_2b_distilled_fp8", "Lightricks/LTX-Video", "ltxv-2b-0.9.8-distilled-fp8.safetensors",
              C + "checkpoints\\ltxv-2b-0.9.8-distilled-fp8.safetensors", "LTX-Video 2B 0.9.8 distilled fp8 checkpoint (LTXV Open Weights License 0.X)",
              "LTXV Open Weights License 0.X"),
            F("ltx-video-distilled", "ltxv_spatial_upscaler", "Lightricks/LTX-Video", "ltxv-spatial-upscaler-0.9.8.safetensors",
              C + "latent_upscale_models\\ltxv-spatial-upscaler-0.9.8.safetensors", "LTX-Video latent spatial upscaler 0.9.8 (LTXV Open Weights License 0.X)",
              "LTXV Open Weights License 0.X"),
            F("frame-interp", "rife_v425", "Comfy-Org/Frame-Interpolation", "frame_interpolation/rife_v4.25.safetensors",
              C + "frame_interpolation\\rife_v4.25.safetensors", "RIFE v4.25 for ComfyUI (MIT)", "MIT"),
            F("frame-interp", "rife_v425_lite", "Comfy-Org/Frame-Interpolation", "frame_interpolation/rife_v4.25_lite.safetensors",
              C + "frame_interpolation\\rife_v4.25_lite.safetensors", "RIFE v4.25 lite for ComfyUI (MIT) - fastest", "MIT"),
            F("frame-interp", "film_net_fp16", "Comfy-Org/Frame-Interpolation", "frame_interpolation/film_net_fp16.safetensors",
              C + "frame_interpolation\\film_net_fp16.safetensors", "FILM net fp16 for ComfyUI (Apache-2.0) - large motion", "Apache-2.0"),
        ],
    }
    # «auto» = downloaded by itself when one of the package's switch-features is on (apps/compute/auto_models.py) - open licences only
    for doc in files.values():
        for pk, info in doc["package_info"].items():
            info["auto"] = pk in AUTO and info["license_class"] == "open"
            if info["license_class"] != "open":
                assert not any(i.get("optional") is not True for i in doc["items"] if i["package"] == pk)
    return files


#: packages the owner gets without a click once the matching feature is on (flux-common / sdxl-base ... come with them through `needs`)
AUTO = {"flux-schnell", "esrgan-x4plus", "frame-interp", "depth-anything-v2-small", "sdxl-base", "sdxl-realvis",
        "controlnet-union-sdxl", "ipadapter-sdxl", "nodes-ipadapter-plus", "wan22-ti2v-5b", "face-restore"}


def verify(files):
    """One byte of every URL on both endpoints: status, size reported by the server, redirect target host."""
    bad = 0
    rows = []
    for name, doc in files.items():
        for it in doc["items"]:
            if it["kind"] != "file":
                continue
            for ep in ("https://huggingface.co", "https://hf-mirror.com"):
                url = it["urls"][0].replace("{HF}", ep)
                req = urllib.request.Request(url, headers=dict(UA, Range="bytes=0-0"))
                try:
                    with _OPENER.open(req, timeout=90) as r:
                        cr = r.headers.get("Content-Range") or ""
                        total = int(cr.rsplit("/", 1)[-1]) if "/" in cr else int(r.headers.get("Content-Length") or -1)
                        ok = total == it["size"]
                        note = "ok" if ok else "SIZE %s != %s" % (total, it["size"])
                except Exception as e:  # noqa: BLE001
                    ok, note = False, "ERR %s" % str(e)[:80]
                bad += 0 if ok else 1
                rows.append((it["id"], ep.split("//")[1], note))
                print("%-48s %-16s %s" % (it["id"], ep.split("//")[1], note), flush=True)
    print("verify: %d problems" % bad)
    return bad, rows


def main():
    files = build()
    os.makedirs(OUT, exist_ok=True)
    for name, doc in files.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        total = sum(i.get("size", 0) for i in doc["items"])
        print("wrote %s: %d items, %.2f GB" % (name, len(doc["items"]), total / 2 ** 30))
    if "--verify" in sys.argv:
        bad, _rows = verify(files)
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
