"""«پرکردنِ هوشمند» (FLUX inpaint): انتخابِ مدل و ساختِ گراف از روی توانایی‌های گره، ریاضیِ برش، چسباندنِ برگشتی،
و API با گرهٔ ساختگی (خاموش ⇐ «در صف می‌ماند»، تمام ⇐ عکسِ کتابخانه + جای لایه).

هیچ تماسی با شبکه/هوشِ مصنوعیِ واقعی نیست؛ گرهٔ GPU با ``services.genfill_finish_for_test`` شبیه‌سازی می‌شود.
"""
import io
import json
import random
from unittest import mock

import numpy as np
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.utils import timezone
from PIL import Image, ImageDraw
from rest_framework.test import APIClient

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode
from apps.stores.models import Store

from . import inpaint, inpaint_graph as ig, services
from .models import PhotoAsset
from .tests import ApiTestBase, photo

User = get_user_model()

CKPT = "FLUX.1 [dev] FP8.safetensors"
FILL = "flux1-fill-dev.safetensors"
ALL_NODES = sorted(ig.OUTPUTS) + ["KSamplerAdvanced"]


def caps(checkpoints=None, unet=None, clip=None, vae=None, nodes=ALL_NODES, vram=None, **more):
    models = {k: v for k, v in (("checkpoints", checkpoints), ("unet", unet), ("clip", clip), ("vae", vae)) if v is not None}
    out = {"comfyui": True, "comfy_nodes": list(nodes), "comfy_models": models} | more
    if vram:
        out["vram_total_mb"] = vram
    return out


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def png_file(im: Image.Image, name: str) -> io.BytesIO:
    f = io.BytesIO(png_bytes(im))
    f.name = name
    return f


def disc_mask(w, h, cx, cy, r) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return m


def classes(graph) -> list[str]:
    return sorted(n["class_type"] for n in graph.values())


def graph_for(choice, prompt="", seed=7, size=(1024, 768)):
    g = ig.build(choice, "i.png", "m.png", prompt, seed, size)
    assert ig.validate(g) == [], ig.validate(g)
    return g


# ═════════════════════════════ انتخابِ مدل و گراف

class ChooseAndBuildTests(SimpleTestCase):
    def test_fill_checkpoint_wins_over_dev(self):
        c = ig.choose(caps(checkpoints=["sdxl_base.safetensors", CKPT, "FLUX1-Fill-dev-fp8.safetensors"]))
        self.assertEqual((c["kind"], c["loader"], c["ckpt"]), ("fill", "checkpoint", "FLUX1-Fill-dev-fp8.safetensors"))
        self.assertEqual((c["guidance"], c["steps"]), (30.0, 20))
        g = graph_for(c)
        self.assertEqual(g["10"]["class_type"], "CheckpointLoaderSimple")
        self.assertEqual(g["10"]["inputs"]["ckpt_name"], "FLUX1-Fill-dev-fp8.safetensors")
        self.assertNotIn("UNETLoader", classes(g))
        self.assertEqual(g["21"]["inputs"]["guidance"], 30.0)
        self.assertEqual(g["25"]["inputs"]["steps"], 20)
        self.assertFalse(c["assumed"])

    def test_fill_unet_with_encoder_lists(self):
        lists = dict(unet=[FILL, "flux1-dev.safetensors"],
                     clip=["clip_l.safetensors", "t5xxl_fp16.safetensors", "t5xxl_fp8_e4m3fn.safetensors", "umt5.safetensors"],
                     vae=["sdxl_vae.safetensors", "ae.safetensors"], checkpoints=[])
        big = ig.choose(caps(vram=24576, **lists))
        self.assertEqual((big["kind"], big["loader"], big["unet"]), ("fill", "unet", FILL))
        self.assertEqual((big["clip_l"], big["t5"], big["vae"]), ("clip_l.safetensors", "t5xxl_fp16.safetensors", "ae.safetensors"))
        self.assertEqual(big["weight_dtype"], "default")
        small = ig.choose(caps(vram=12288, **lists))
        self.assertEqual(small["t5"], "t5xxl_fp8_e4m3fn.safetensors")
        self.assertEqual(small["weight_dtype"], "fp8_e4m3fn")          # مدلِ بزرگِ غیر fp8 روی کارتِ کوچک
        g = graph_for(small)
        self.assertEqual(g["10"]["class_type"], "UNETLoader")
        self.assertEqual(g["10"]["inputs"], {"unet_name": FILL, "weight_dtype": "fp8_e4m3fn"})
        self.assertEqual(g["11"]["class_type"], "DualCLIPLoader")
        self.assertEqual(g["11"]["inputs"], {"clip_name1": "t5xxl_fp8_e4m3fn.safetensors", "clip_name2": "clip_l.safetensors", "type": "flux"})
        self.assertEqual(g["12"]["inputs"], {"vae_name": "ae.safetensors"})
        self.assertEqual(g["20"]["inputs"]["clip"], ["11", 0])
        self.assertEqual(g["24"]["inputs"]["vae"], ["12", 0])
        self.assertNotIn("CheckpointLoaderSimple", classes(g))

    def test_fill_unet_without_encoder_lists_uses_defaults(self):
        c = ig.choose(caps(unet=[FILL], checkpoints=[]))      # clip/vae گزارش نشده (agent فعلی)
        self.assertEqual((c["kind"], c["loader"]), ("fill", "unet"))
        self.assertEqual((c["clip_l"], c["vae"]), (ig.DEFAULT_CLIP_L, ig.DEFAULT_VAE))
        self.assertEqual(c["t5"], ig.DEFAULT_T5_FP8)           # vram ناشناخته ⇒ fp8
        self.assertTrue(any("پیش‌فرض" in n for n in c["notes"]))
        graph_for(c)
        self.assertEqual(ig.choose(caps(unet=[FILL], checkpoints=[], vram=32000))["t5"], ig.DEFAULT_T5_FP16)

    def test_fill_unet_with_unusable_encoders_falls_back_to_dev_checkpoint(self):
        c = ig.choose(caps(unet=[FILL], checkpoints=[CKPT], clip=["only_something_else.safetensors"], vae=["ae.safetensors"]))
        self.assertEqual((c["kind"], c["loader"], c["ckpt"]), ("dev", "checkpoint", CKPT))
        self.assertTrue(any("Fill" in n and "کنار گذاشته شد" in n for n in c["notes"]), c["notes"])

    def test_dev_checkpoint_graph_shape(self):
        c = ig.choose(caps(checkpoints=["sd_xl_base_1.0.safetensors", CKPT], unet=[]))
        self.assertEqual((c["kind"], c["loader"], c["ckpt"]), ("dev", "checkpoint", CKPT))
        self.assertEqual((c["guidance"], c["steps"]), (4.0, 28))
        g = graph_for(c, "blue sky", 99, (1024, 1024))
        self.assertEqual(classes(g), sorted([
            "LoadImage", "LoadImageMask", "GrowMask", "CheckpointLoaderSimple", "CLIPTextEncode", "CLIPTextEncode",
            "FluxGuidance", "DifferentialDiffusion", "InpaintModelConditioning", "KSampler", "VAEDecode", "SaveImage"]))
        self.assertEqual(g["1"]["inputs"], {"image": "i.png"})
        self.assertEqual(g["2"]["inputs"], {"image": "m.png", "channel": "red"})
        self.assertEqual(g["3"]["inputs"]["mask"], ["2", 0])
        self.assertEqual(g["3"]["inputs"]["expand"], ig.grow_for((1024, 1024)))
        self.assertTrue(g["24"]["inputs"]["noise_mask"])
        self.assertEqual(g["24"]["inputs"]["mask"], ["3", 0])
        self.assertEqual(g["24"]["inputs"]["pixels"], ["1", 0])
        self.assertEqual(g["23"]["inputs"]["model"], ["10", 0])
        ks = g["25"]["inputs"]
        self.assertEqual((ks["model"], ks["seed"], ks["steps"], ks["denoise"], ks["cfg"]), (["23", 0], 99, 28, 1.0, 1.0))
        self.assertEqual((ks["positive"], ks["negative"], ks["latent_image"]), (["24", 0], ["24", 1], ["24", 2]))
        self.assertEqual(g["21"]["inputs"], {"conditioning": ["20", 0], "guidance": 4.0})
        self.assertIn("blue sky", g["20"]["inputs"]["text"])
        self.assertEqual(g["22"]["inputs"]["text"], "")
        self.assertEqual(g["27"]["inputs"]["filename_prefix"], "nm/genfill")

    def test_dev_unet(self):
        c = ig.choose(caps(checkpoints=[], unet=["flux1-dev-fp8.safetensors"], clip=["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
                           vae=["ae.safetensors"]))
        self.assertEqual((c["kind"], c["loader"], c["unet"]), ("dev", "unet", "flux1-dev-fp8.safetensors"))
        self.assertEqual(c["weight_dtype"], "default")
        g = graph_for(c)
        self.assertEqual(g["10"]["class_type"], "UNETLoader")
        self.assertEqual(g["25"]["inputs"]["steps"], 28)

    def test_unknown_caps_assume_default_dev_checkpoint(self):
        for unknown in (None, {}, {"photo": True}, {"comfyui": True, "comfy_models": {}},
                        {"comfy_models": {"upscale": ["4x.pth"]}}, "garbage"):
            c = ig.choose(unknown)
            self.assertEqual((c["kind"], c["loader"], c["ckpt"], c["assumed"]), ("dev", "checkpoint", ig.DEFAULT_DEV_CKPT, True), unknown)
            self.assertEqual(ig.DEFAULT_DEV_CKPT, CKPT)
            graph_for(c)

    def test_nothing_flux_like_lists_what_was_found(self):
        with self.assertRaises(ig.GraphError) as cm:
            ig.choose(caps(checkpoints=["sd_xl_base_1.0.safetensors", "v1-5-pruned.safetensors"], unet=["wan2.2_i2v.safetensors"]))
        msg = str(cm.exception)
        self.assertIn("FLUX", msg)
        self.assertIn("sd_xl_base_1.0.safetensors", msg)
        self.assertIn("wan2.2_i2v.safetensors", msg)
        with self.assertRaises(ig.GraphError) as cm:
            ig.choose(caps(checkpoints=[], unet=[]))
        self.assertIn("هیچ", str(cm.exception))

    def test_other_flux_variants_are_not_dev(self):
        for name in ("flux1-schnell.safetensors", "flux1-canny-dev.safetensors", "flux1-depth-dev.safetensors",
                     "flux1-redux-dev.safetensors", "FLUX.1-Kontext-dev.safetensors", "flux-dev-lora.safetensors"):
            self.assertFalse(ig.is_dev(name), name)
        self.assertTrue(ig.is_dev("flux/flux1-dev-fp8.safetensors"))
        with self.assertRaises(ig.GraphError):
            ig.choose(caps(checkpoints=["flux1-schnell.safetensors"], unet=["flux1-canny-dev.safetensors"]))

    def test_prefers_fp8_on_small_gpu_and_full_precision_on_big(self):
        names = ["flux1-dev.safetensors", "flux1-dev-fp8.safetensors"]
        self.assertEqual(ig.choose(caps(checkpoints=names))["ckpt"], "flux1-dev-fp8.safetensors")
        self.assertEqual(ig.choose(caps(checkpoints=names, vram=24576))["ckpt"], "flux1-dev.safetensors")

    def test_required_nodes_and_check_nodes(self):
        c = ig.choose(caps(unet=[FILL], checkpoints=[]))
        self.assertEqual(c["required_nodes"], classes_unique(graph_for(c)))
        for must in ("DifferentialDiffusion", "InpaintModelConditioning", "GrowMask", "UNETLoader", "DualCLIPLoader", "VAELoader"):
            self.assertIn(must, c["required_nodes"])
        g = graph_for(c)
        self.assertEqual(ig.check_nodes(g, ALL_NODES), [])
        have = [n for n in ALL_NODES if n not in ("DifferentialDiffusion", "VAELoader")]
        self.assertEqual(ig.check_nodes(g, have), ["DifferentialDiffusion", "VAELoader"])
        self.assertEqual(ig.check_nodes(g, None), [])            # گره هنوز چیزی گزارش نکرده ⇒ نمی‌دانیم
        self.assertEqual(ig.check_nodes(g, []), [])

    def test_validator_catches_broken_graphs(self):
        good = graph_for(ig.choose(None))
        self.assertEqual(ig.validate(good), [])
        import copy
        dangling = copy.deepcopy(good)
        dangling["25"]["inputs"]["model"] = ["99", 0]
        self.assertTrue(any("ناموجود" in p for p in ig.validate(dangling)))
        bad_idx = copy.deepcopy(good)
        bad_idx["3"]["inputs"]["mask"] = ["2", 1]            # LoadImageMask فقط یک خروجی دارد
        self.assertTrue(any("خروجیِ 1" in p for p in ig.validate(bad_idx)))
        bad_idx2 = copy.deepcopy(good)
        bad_idx2["26"]["inputs"]["vae"] = ["10", 3]          # چک‌پوینت سه خروجی دارد (۰..۲)
        self.assertTrue(ig.validate(bad_idx2))
        unknown = copy.deepcopy(good)
        unknown["25"]["class_type"] = "Mystery"
        self.assertTrue(any("ناشناخته" in p for p in ig.validate(unknown)))
        cyc = copy.deepcopy(good)
        cyc["1"]["inputs"]["image"] = ["26", 0]
        self.assertIn("گراف دور دارد", ig.validate(cyc))
        no_save = {k: v for k, v in good.items() if k != "27"}
        self.assertIn("SaveImage ندارد", ig.validate(no_save))
        self.assertTrue(ig.validate({}))

    def test_every_link_in_every_case_is_valid(self):
        cases = [caps(checkpoints=[FILL]), caps(unet=[FILL], checkpoints=[]), caps(checkpoints=[CKPT]),
                 caps(unet=["flux1-dev.safetensors"], checkpoints=[]), None, {}]
        for cs in cases:
            c = ig.choose(cs)
            for prompt in ("", "یک آسمان آبی", "a red car, parked."):
                self.assertEqual(ig.validate(ig.build(c, "a.png", "b.png", prompt, 1, (512, 512))), [], (cs, prompt))

    def test_prompt_rules(self):
        self.assertEqual(ig.effective_prompt(""), ig.DEFAULT_PROMPT)
        self.assertEqual(ig.effective_prompt("   \n "), ig.DEFAULT_PROMPT)
        self.assertTrue(ig.effective_prompt("blue sky").startswith("blue sky, "))
        self.assertEqual(ig.effective_prompt("A wooden table."), "A wooden table.")
        self.assertEqual(ig.effective_prompt("  two   spaces "), "two spaces, " + ig.PROMPT_SUFFIX)

    def test_grow_scales_with_size_and_is_bounded(self):
        self.assertEqual(ig.grow_for((64, 64)), 4)
        self.assertEqual(ig.grow_for((512, 512)), 8)
        self.assertEqual(ig.grow_for((1024, 1024)), 15)
        self.assertLessEqual(ig.grow_for((5000, 5000)), 24)


def classes_unique(graph) -> list[str]:
    return sorted({n["class_type"] for n in graph.values()})


# ═════════════════════════════ ریاضیِ برش

class CropMathTests(SimpleTestCase):
    def check(self, canvas, bbox):
        rect, size, scale = inpaint.plan_crop(canvas, bbox)
        W, H = canvas
        x0, y0, x1, y1 = rect
        self.assertTrue(0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H, (canvas, bbox, rect))
        self.assertTrue(x0 <= bbox[0] and y0 <= bbox[1] and x1 >= bbox[2] and y1 >= bbox[3], (canvas, bbox, rect))
        self.assertEqual((size[0] % 16, size[1] % 16), (0, 0), (canvas, bbox, size))
        self.assertLessEqual(max(size), 1024)
        self.assertGreaterEqual(min(size), 64)
        self.assertAlmostEqual(scale, size[0] / (x1 - x0))
        return rect, size, scale

    def test_padding_is_35_percent_of_the_mask_box(self):
        rect, size, scale = self.check((2048, 1536), (800, 600, 1200, 900))        # ۴۰۰ × ۳۰۰ ⇒ حاشیه ۱۴۰
        self.assertLessEqual(rect[0], 800 - 140)
        self.assertGreaterEqual(rect[2], 1200 + 140)
        self.assertLessEqual(rect[1], 600 - 140)
        self.assertGreaterEqual(rect[3], 900 + 140)
        self.assertLessEqual(rect[2] - rect[0], 680 + 15)        # فقط تا تراز ۱۶ بزرگ‌تر
        self.assertEqual(scale, 1.0)

    def test_tiny_mask_gets_min_padding_and_context(self):
        rect, size, scale = self.check((2048, 1536), (1000, 700, 1010, 710))
        self.assertEqual((rect[2] - rect[0], rect[3] - rect[1]), (512, 512))
        self.assertEqual((size, scale), ((512, 512), 1.0))
        # حتی یک پیکسل
        self.check((2048, 1536), (5, 5, 6, 6))
        self.check((2048, 1536), (2047, 1535, 2048, 1536))

    def test_edge_and_corner_masks(self):
        for bbox in ((0, 0, 20, 20), (1980, 1500, 2048, 1536), (0, 700, 30, 760), (1000, 0, 1100, 40),
                     (0, 0, 2048, 10), (0, 0, 10, 1536)):
            self.check((2048, 1536), bbox)

    def test_mask_over_whole_canvas_is_scaled_down_to_1024(self):
        rect, size, scale = self.check((2048, 1536), (0, 0, 2048, 1536))
        self.assertEqual(rect, (0, 0, 2048, 1536))
        self.assertEqual(size, (1024, 768))
        self.assertAlmostEqual(scale, 0.5)

    def test_small_image_is_scaled_up_to_512(self):
        rect, size, scale = self.check((200, 150), (80, 60, 120, 90))
        self.assertEqual(rect, (0, 0, 200, 150))
        self.assertEqual(size, (512, 384))
        self.assertAlmostEqual(scale, 2.56)

    def test_unaligned_canvas_crop_is_resampled_to_a_multiple_of_16(self):
        rect, size, scale = self.check((1000, 723), (0, 0, 1000, 723))
        self.assertEqual(rect, (0, 0, 1000, 723))             # به مضرب ۱۶ نمی‌رسد؛ اندازهٔ مدل گرد می‌شود
        self.assertEqual(size[0] % 16, 0)

    def test_aligned_crop_is_sent_without_resampling(self):
        rect, size, scale = self.check((1600, 1200), (700, 500, 900, 700))
        self.assertEqual(size, (rect[2] - rect[0], rect[3] - rect[1]))
        self.assertEqual(scale, 1.0)

    def test_invariants_on_random_masks(self):
        rnd = random.Random(7)
        for _ in range(400):
            W, H = rnd.choice([64, 100, 333, 700, 1000, 1500, 2048]), rnd.choice([64, 90, 400, 800, 1200, 2048])
            x0, y0 = rnd.randrange(W), rnd.randrange(H)
            x1, y1 = rnd.randrange(x0 + 1, W + 1), rnd.randrange(y0 + 1, H + 1)
            if rnd.random() < .3:
                x0 = 0
            if rnd.random() < .3:
                x1 = W
            self.check((W, H), (x0, y0, x1, y1))

    # ───── prepare()
    def scene(self, w=1200, h=900):
        return photo(w, h), disc_mask(w, h, 600, 450, 70)

    def test_prepare_outputs_match_the_plan(self):
        img, mask = self.scene()
        p = inpaint.prepare(png_bytes(img), png_bytes(mask), "  یک   گل ")
        self.assertEqual(p.canvas, (1200, 900))
        self.assertEqual(p.bbox, (530, 380, 671, 521))
        sent = Image.open(io.BytesIO(p.image_png))
        self.assertEqual((sent.mode, sent.size), ("RGB", p.size))
        soft = Image.open(io.BytesIO(p.mask_png))
        self.assertEqual((soft.mode, soft.size), ("L", p.size))
        full = Image.open(io.BytesIO(p.full_mask_png))
        self.assertEqual((full.mode, full.size), ("L", p.crop_size))
        self.assertEqual(sorted(set(np.asarray(full).ravel().tolist())), [0, 255])
        self.assertEqual(int(np.asarray(soft)[p.size[1] // 2, p.size[0] // 2]), 255)
        self.assertEqual(int(np.asarray(soft)[0, 0]), 0)
        self.assertEqual(p.prompt, "یک گل")
        self.assertEqual(p.scale, 1.0)
        x0, y0 = p.rect[:2]
        crop = img.crop(p.rect)
        self.assertEqual(np.asarray(sent).tobytes(), np.asarray(crop).tobytes())     # بی بازنمونه ⇒ بایتِ اصل
        self.assertGreaterEqual(int(np.asarray(full)[450 - y0, 600 - x0]), 255)
        json.dumps(p.meta())
        self.assertEqual(p.grow, ig.grow_for(p.size))

    def test_prepare_scales_big_crops_down_and_keeps_thin_strokes(self):
        img = photo(2048, 1536)
        mask = Image.new("L", (2048, 1536), 0)
        ImageDraw.Draw(mask).line([(0, 0), (2047, 1535)], fill=255, width=3)      # قلمِ نازکِ قطری
        p = inpaint.prepare(png_bytes(img), png_bytes(mask))
        self.assertEqual(max(p.size), 1024)
        self.assertLess(p.scale, 1.0)
        soft = np.asarray(Image.open(io.BytesIO(p.mask_png)))
        self.assertGreater(int((soft == 255).sum()), 500)            # بعد از کوچک‌کردن گم نشد

    def test_prepare_mask_conventions(self):
        img = photo(400, 300)
        m = disc_mask(400, 300, 200, 150, 30)
        white_on_clear = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
        white_on_clear.paste(Image.new("RGBA", (400, 300), (255, 255, 255, 255)), mask=m)
        alpha_only = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
        alpha_only.putalpha(m)
        for name, mask in (("L", m), ("RGBA سفید روی شفاف", white_on_clear), ("فقط آلفا", alpha_only), ("RGB", m.convert("RGB"))):
            p = inpaint.prepare(png_bytes(img), png_bytes(mask))
            self.assertEqual(p.bbox, (170, 120, 231, 181), name)
        jpeg = io.BytesIO()
        m.save(jpeg, "JPEG", quality=95)
        self.assertAlmostEqual(inpaint.prepare(png_bytes(img), jpeg.getvalue()).bbox[0], 170, delta=2)
        # ماسکِ کوچک‌تر با همان نسبت ⇒ بزرگ می‌شود؛ نسبتِ دیگر ⇒ خطا
        small = m.resize((200, 150))
        self.assertAlmostEqual(inpaint.prepare(png_bytes(img), png_bytes(small)).bbox[0], 170, delta=3)
        with self.assertRaises(inpaint.InpaintError) as cm:
            inpaint.prepare(png_bytes(img), png_bytes(m.resize((300, 300))))
        self.assertIn("اندازهٔ ماسک", str(cm.exception))

    def test_prepare_validation_errors_are_persian(self):
        img = photo(400, 300)
        empty = Image.new("L", (400, 300), 0)
        dim = Image.new("L", (400, 300), 100)                     # هیچ پیکسلِ ≥ ۱۲۸ ⇒ خالی
        for bad in (empty, dim):
            with self.assertRaises(inpaint.InpaintError) as cm:
                inpaint.prepare(png_bytes(img), png_bytes(bad))
            self.assertIn("ناحیه‌ای انتخاب نشده", str(cm.exception))
        ok_mask = png_bytes(disc_mask(400, 300, 200, 150, 30))
        big = Image.new("RGB", (2100, 100), (1, 2, 3))
        with self.assertRaises(inpaint.InpaintError) as cm:
            inpaint.prepare(png_bytes(big), ok_mask)
        self.assertIn("۲۰۴۸", str(cm.exception))
        with self.assertRaises(inpaint.InpaintError) as cm:
            inpaint.prepare(png_bytes(Image.new("RGB", (32, 32))), ok_mask)
        self.assertIn("خیلی کوچک", str(cm.exception))
        with self.assertRaises(inpaint.InpaintError) as cm:
            inpaint.prepare(b"not an image at all", ok_mask)
        self.assertIn("معتبر", str(cm.exception))
        with self.assertRaises(inpaint.InpaintError) as cm:
            inpaint.prepare(b"x" * (20 * 1024 * 1024 + 1), ok_mask)
        self.assertIn("۲۰ مگابایت", str(cm.exception))
        with self.assertRaises(inpaint.InpaintError):
            inpaint.prepare(b"", ok_mask)
        with self.assertRaises(inpaint.InpaintError):
            inpaint.prepare(png_bytes(img), b"")

    def test_prepare_flattens_transparent_image_on_white(self):
        rgba = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        p = inpaint.prepare(png_bytes(rgba), png_bytes(disc_mask(300, 300, 150, 150, 20)))
        sent = np.asarray(Image.open(io.BytesIO(p.image_png)))
        self.assertTrue((sent == 255).all())


# ═════════════════════════════ چسباندنِ برگشتی

class PasteBackTests(SimpleTestCase):
    def setUp(self):
        self.canvas = (800, 600)
        self.orig = photo(800, 600, seed=3)
        self.mask = disc_mask(800, 600, 400, 300, 60)

    def run_prep(self, result_of=None):
        prep = inpaint.prepare(png_bytes(self.orig), png_bytes(self.mask))
        crop_orig = self.orig.crop(prep.rect)
        full = Image.open(io.BytesIO(prep.full_mask_png))
        result = result_of(prep, crop_orig) if result_of else crop_orig
        return prep, crop_orig, full, result

    def paste(self, prep, crop_orig, full, result, **kw):
        return inpaint.paste_back(crop_orig, result, full, prep.feather, origin=prep.rect[:2], canvas=prep.canvas,
                                  grow=prep.grow_full, **kw)

    def blue_result(self, prep, crop_orig):
        return Image.new("RGB", crop_orig.size, (20, 40, 220))

    def test_alpha_is_feathered_and_full_inside_the_mask(self):
        crop = Image.new("RGB", (300, 300), (128, 128, 128))
        mask = disc_mask(300, 300, 150, 150, 60)
        res = inpaint.paste_back(crop, Image.new("RGB", (300, 300), (255, 0, 0)), mask, 6.0)
        a = np.asarray(res.patch.getchannel("A"))
        x0, y0, x1, y1 = res.bbox
        self.assertGreater(x1 - x0, 121 + 2 * 6)                  # لبه فراتر از ماسک می‌رود (شیبِ نرم)
        full = np.zeros((300, 300), np.uint8)
        full[y0:y1, x0:x1] = a
        m = np.asarray(mask) > 127
        self.assertTrue((full[m] == 255).all(), "درونِ ماسک باید کاملاً نتیجه باشد")
        row = full[150, 150 + 60:]                                  # از لبهٔ ماسک به بیرون
        self.assertTrue((np.diff(row.astype(int)) <= 0).all(), "شیب باید یکنوا کم شود")
        self.assertGreater(int(row[0]), 120)
        self.assertLess(int(row[3 * 6]), 20)
        self.assertEqual(int(row[-1]), 0)
        self.assertTrue(0 < int(row[6]) < 255)
        self.assertEqual(res.patch.mode, "RGBA")
        self.assertEqual(tuple(res.patch.getpixel((150 - x0, 150 - y0)))[:3], (255, 0, 0))

    def test_exact_placement_over_the_original_pixels(self):
        prep, crop_orig, full, result = self.run_prep(self.blue_result)
        res = self.paste(prep, crop_orig, full, result)
        W, H = self.canvas
        pw, ph = res.patch.size
        cx, cy, w = res.placement["cx"], res.placement["cy"], res.placement["w"]
        self.assertAlmostEqual(w * W, pw, delta=1e-3 * W)
        left, top = round(cx * W - pw / 2), round(cy * H - ph / 2)
        self.assertEqual((left, top), res.bbox[:2])
        self.assertEqual((left + pw, top + ph), res.bbox[2:])
        out = self.orig.convert("RGBA")
        out.alpha_composite(res.patch, (left, top))
        out = np.asarray(out.convert("RGB")).astype(int)
        before = np.asarray(self.orig).astype(int)
        m = np.asarray(self.mask) > 127
        self.assertTrue((out[m] == (20, 40, 220)).all(), "درونِ ماسک باید نتیجه باشد")
        changed = (out != before).any(axis=2)
        self.assertFalse(changed[:top].any() or changed[top + ph:].any() or changed[:, :left].any() or changed[:, left + pw:].any(),
                         "بیرونِ جعبهٔ patch دست‌نخورده است")
        # دورتر از ماسک + grow + سه σ هیچ پیکسلی عوض نشده
        import cv2
        reach = prep.grow_full + int(3.5 * prep.feather) + 2
        near = cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * reach + 1, 2 * reach + 1))) > 0
        self.assertFalse(changed[~near].any())
        # composite داخلی با همین حساب یکی است
        comp = np.asarray(res.composite).astype(int)
        x0, y0 = prep.rect[:2]
        self.assertTrue((comp == out[y0:y0 + comp.shape[0], x0:x0 + comp.shape[1]]).all())

    def test_node_may_return_a_different_size(self):
        prep, crop_orig, full, _ = self.run_prep()
        for factor in (2.0, 0.5, 1.37):
            result = Image.new("RGB", (round(crop_orig.width * factor), round(crop_orig.height * factor)), (10, 200, 30))
            res = self.paste(prep, crop_orig, full, result)
            self.assertEqual(res.bbox, self.paste(prep, crop_orig, full, crop_orig).bbox)
            px = np.asarray(res.patch)[res.patch.height // 2, res.patch.width // 2].astype(int)
            self.assertTrue((np.abs(px - (10, 200, 30, 255)) <= 1).all(), px)
        sized = inpaint.paste_back(crop_orig.size, Image.new("RGB", (64, 64), (1, 2, 3)), full, 4.0)      # فقط اندازه هم بس است
        mid = np.asarray(sized.patch.getpixel((sized.patch.width // 2, sized.patch.height // 2))[:3]).astype(int)
        self.assertTrue((np.abs(mid - (1, 2, 3)) <= 1).all(), mid)
        self.assertIsNone(sized.placement)
        self.assertIsNone(sized.composite)

    def test_grow_extends_the_replaced_area_past_the_users_mask(self):
        crop = Image.new("RGB", (300, 300), (0, 0, 0))
        mask = disc_mask(300, 300, 150, 150, 40)
        plain = inpaint.paste_back(crop, Image.new("RGB", (300, 300), (255, 255, 255)), mask, 1.0, grow=0)
        grown = inpaint.paste_back(crop, Image.new("RGB", (300, 300), (255, 255, 255)), mask, 1.0, grow=12)
        self.assertGreaterEqual((grown.bbox[2] - grown.bbox[0]) - (plain.bbox[2] - plain.bbox[0]), 2 * 11)
        a = np.asarray(grown.patch.getchannel("A"))
        left = 150 - 40 - 8 - grown.bbox[0]                          # ۸ پیکسل بیرونِ ماسک هنوز کاملاً پرشده
        self.assertEqual(int(a[grown.patch.height // 2, left]), 255)

    def test_thin_stroke_survives(self):
        crop = Image.new("RGB", (200, 200), (0, 0, 0))
        mask = Image.new("L", (200, 200), 0)
        ImageDraw.Draw(mask).line([(20, 100), (180, 100)], fill=255, width=1)
        res = inpaint.paste_back(crop, Image.new("RGB", (200, 200), (9, 9, 9)), mask, 3.0)
        a = np.asarray(res.patch.getchannel("A"))
        self.assertEqual(int(a.max()), 255)
        self.assertGreaterEqual(int((a == 255).sum()), 150)

    def test_empty_mask_is_rejected(self):
        with self.assertRaises(inpaint.InpaintError):
            inpaint.paste_back((50, 50), Image.new("RGB", (50, 50)), Image.new("L", (50, 50), 0), 3.0)

    def test_mask_of_other_size_is_resized(self):
        crop = Image.new("RGB", (200, 200), (0, 0, 0))
        res = inpaint.paste_back(crop, Image.new("RGB", (200, 200), (50, 60, 70)), disc_mask(100, 100, 50, 50, 20), 2.0)
        self.assertTrue(70 <= res.patch.width <= 100)


# ═════════════════════════════ API با گرهٔ ساختگی

class GenFillApiTests(ApiTestBase):
    W, H = 900, 700

    def setUp(self):
        super().setUp()
        (self.aid,) = self.upload(photo(self.W, self.H, seed=5))
        self.scene = photo(self.W, self.H, seed=9)
        self.mask = disc_mask(self.W, self.H, 450, 350, 55)
        self.url = f"{self.base}/genfill/"

    def comfy_node(self, **extra):
        return ComputeNode.objects.create(name="gpu-comfy", last_seen=timezone.now(),
                                          capabilities={"photo": True} | services.genfill_fake_caps() | extra)

    def post(self, *, asset=None, image=None, mask=None, base=None, **fields):
        body = {"image": png_file(image or self.scene, "image.png"), "mask": png_file(mask or self.mask, "mask.png"),
                "asset": self.aid if asset is None else asset} | fields
        return self.api.post(base or self.url, body, format="multipart")

    def finish(self, uid, **kw):
        return services.genfill_finish_for_test(ComputeJob.objects.get(uid=uid), None, **kw)

    def test_offline_request_waits_in_the_queue(self):
        r = self.post(prompt="blue sky over the sea", seed="12")      # انگلیسی ⇒ بی ترجمه؛ فارسی: tests_translate.py
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["state"], "QUEUED")
        self.assertFalse(body["online"])
        self.assertEqual(body["message"], "در صف — منتظرِ سرورِ پردازش (سرورِ پردازش خاموش است؛ کار گم نمی‌شود و وقتی روشن شد انجام می‌شود)")
        job = ComputeJob.objects.get(uid=body["job"])
        self.assertEqual((job.kind, job.origin, job.store_id, job.state), ("comfy.graph", "photogenfill", self.store.pk, "QUEUED"))
        self.assertEqual(job.priority, 105)
        self.assertGreater(job.priority, 95)                                  # پایین‌تر از ویرایش‌های معمولی
        g = job.payload["graph"]
        self.assertEqual(ig.validate(g), [])
        self.assertEqual(g["10"]["inputs"]["ckpt_name"], CKPT)               # گره چیزی گزارش نکرده ⇒ چک‌پوینتِ مالک
        self.assertEqual(g["25"]["inputs"]["seed"], 12)
        self.assertIn("blue sky over the sea", g["20"]["inputs"]["text"])
        up = job.payload["uploads"]
        self.assertEqual(g["1"]["inputs"]["image"], up[0])
        self.assertEqual(g["2"]["inputs"]["image"], up[1])
        self.assertEqual(sorted(job.inputs), sorted(up + [job.payload["x_genfill"]["full_mask"]]))
        for name in up:
            self.assertTrue((compute.job_root(job) / "inputs" / name).is_file())
        meta = job.payload["x_genfill"]
        self.assertEqual((meta["asset"], meta["user"], meta["canvas"]), (self.aid, self.owner.pk, [self.W, self.H]))
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual((st["state"], st["online"]), ("QUEUED", False))
        self.assertEqual(st["message"], body["message"])
        self.assertNotIn("asset", st)

    def test_empty_prompt_removes_object(self):
        job = ComputeJob.objects.get(uid=self.post().json()["job"])
        self.assertEqual(job.payload["graph"]["20"]["inputs"]["text"], ig.DEFAULT_PROMPT)
        self.assertEqual(job.payload["x_genfill"]["prompt"], "")

    def test_online_node_with_models_picks_fill_when_installed(self):
        self.comfy_node(comfy_models={"checkpoints": [CKPT], "unet": [FILL],
                                      "clip": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"], "vae": ["ae.safetensors"]},
                        comfy_nodes=ALL_NODES)
        body = self.post().json()
        self.assertEqual((body["state"], body["online"], body["message"]), ("QUEUED", True, "در صفِ سرورِ پردازش"))
        self.assertIn("Fill", body["engine"])
        g = ComputeJob.objects.get(uid=body["job"]).payload["graph"]
        self.assertEqual(g["10"]["class_type"], "UNETLoader")
        self.assertEqual(g["21"]["inputs"]["guidance"], 30.0)

    def test_node_without_flux_gets_a_clear_error_and_no_job(self):
        self.comfy_node(comfy_models={"checkpoints": ["sd_xl_base_1.0.safetensors"], "unet": []})
        r = self.post()
        self.assertEqual(r.status_code, 400)
        msg = r.json()["error"]["message"]
        self.assertIn("FLUX", msg)
        self.assertIn("sd_xl_base_1.0.safetensors", msg)
        self.assertEqual(ComputeJob.objects.filter(origin="photogenfill").count(), 0)

    def test_missing_comfy_nodes_are_named(self):
        nodes = [n for n in services.genfill_fake_caps()["comfy_nodes"] if n != "DifferentialDiffusion"]
        self.comfy_node(comfy_nodes=nodes)
        r = self.post()
        self.assertEqual(r.status_code, 400)
        self.assertIn("DifferentialDiffusion", r.json()["error"]["message"])
        self.assertEqual(ComputeJob.objects.filter(origin="photogenfill").count(), 0)

    def test_complete_makes_asset_and_exact_layer(self):
        self.comfy_node()
        body = self.post(prompt="blue sky", seed=3).json()
        job = ComputeJob.objects.get(uid=body["job"])
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual(st["state"], "QUEUED")
        done = self.finish(body["job"])
        self.assertEqual(done.state, ComputeJob.State.COMPLETED)
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual(st["state"], "READY", st)
        self.assertEqual(st["node"], "gpu-comfy")
        self.assertIsNotNone(st["seconds"])
        a = st["asset"]
        self.assertEqual((a["title"], a["source_kind"], a["has_alpha"]), ("پرکردن هوشمند", "generated", True))
        self.assertEqual(PhotoAsset.objects.get(pk=a["id"]).store_id, self.store.pk)
        layer = st["layer"]
        self.assertTrue(all(0 < layer[k] <= 1 for k in ("cx", "cy", "w")))
        # patch را روی بوم بگذار: درونِ ماسک = خروجیِ گره، بیرونِ patch = بوم
        patch = Image.open(self.media / PhotoAsset.objects.get(pk=a["id"]).original)
        self.assertEqual((patch.mode, patch.size), ("RGBA", tuple(st["size"])))
        left, top = round(layer["cx"] * self.W - patch.width / 2), round(layer["cy"] * self.H - patch.height / 2)
        self.assertAlmostEqual(layer["w"] * self.W, patch.width, delta=1)
        out = self.scene.convert("RGBA")
        out.alpha_composite(patch, (left, top))
        out = np.asarray(out.convert("RGB")).astype(int)
        node_out = Image.open(compute.output_path(job, "genfill_00001_.png")).convert("RGB")
        rx, ry = job.payload["x_genfill"]["rect"][:2]
        m = np.asarray(self.mask) > 127
        ys, xs = np.nonzero(m)
        for y, x in list(zip(ys, xs))[::37]:
            self.assertEqual(tuple(out[y, x]), node_out.getpixel((x - rx, y - ry)))
        before = np.asarray(self.scene).astype(int)
        changed = (out != before).any(axis=2)
        self.assertTrue(changed[m].any())
        self.assertFalse(changed[:top].any() or changed[:, :left].any() or changed[top + patch.height:].any()
                         or changed[:, left + patch.width:].any())
        # دوباره پرسیدن ⇒ همان عکس، نه عکسِ تازه
        again = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual((again["state"], again["asset"]["id"], again["layer"]), ("READY", a["id"], layer))
        self.assertEqual(PhotoAsset.objects.filter(store=self.store, source_ref=f"genfill:{body['job']}").count(), 1)
        self.assertEqual(PhotoAsset.objects.filter(title="پرکردن هوشمند").count(), 1)
        # لایهٔ تصویریِ ساخته‌شده روی همین عکس قبول می‌شود
        from . import layers as layers_mod
        ok = layers_mod.normalize_layers([{"id": "base", "type": "base"}, {"id": "g1", "type": "image", "src": {"kind": "asset", "asset": a["id"]},
                                                                              "cx": layer["cx"], "cy": layer["cy"], "w": layer["w"]}],
                                         store=self.store, base="one")
        self.assertEqual(ok[1]["src"]["asset"], a["id"])

    def test_result_of_other_size_still_lands_exactly(self):
        self.comfy_node()
        same = self.post(seed=4).json()
        self.finish(same["job"])
        half = self.post(seed=5).json()
        self.finish(half["job"], result_scale=0.5)         # گره عکسی نصفِ اندازه برگرداند
        a = self.api.get(f"{self.url}{same['job']}/").json()
        b = self.api.get(f"{self.url}{half['job']}/").json()
        self.assertEqual((a["state"], b["state"]), ("READY", "READY"), b)
        self.assertEqual((a["layer"], a["size"]), (b["layer"], b["size"]))      # جا و اندازه فقط از ماسک می‌آید
        patch = Image.open(self.media / PhotoAsset.objects.get(pk=b["asset"]["id"]).original)
        self.assertEqual(patch.size, tuple(b["size"]))

    def test_failed_job_is_reported_in_persian(self):
        self.comfy_node()
        body = self.post().json()
        self.finish(body["job"], error="ComfyUI rejected the graph (HTTP 400): ckpt_name: Value not in list: 'x.safetensors'")
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual(st["state"], "FAILED")
        self.assertIn("پیدا نشد", st["error"])
        self.assertIn("Value not in list", st["error"])
        self.assertNotIn("asset", st)
        self.assertEqual(PhotoAsset.objects.filter(title="پرکردن هوشمند").count(), 0)
        self.assertIn("حافظهٔ کارتِ گرافیک", services._genfill_error_text("CUDA out of memory. Tried to allocate"))

    def test_running_state_names_the_node(self):
        node = self.comfy_node()
        body = self.post().json()
        ComputeJob.objects.filter(uid=body["job"]).update(state="RUNNING", node=node, progress=0.5)
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual(st["state"], "RUNNING")
        self.assertIn("gpu-comfy", st["message"])
        self.assertEqual(st["progress"], 0.5)

    def test_cancel(self):
        body = self.post().json()
        self.assertEqual(self.api.delete(f"{self.url}{body['job']}/").status_code, 204)
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual((st["state"], st["message"]), ("CANCELLED", "لغو شد"))

    def test_bad_requests(self):
        r = self.api.post(self.url, {"asset": self.aid}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("image", r.json()["error"]["message"])
        r = self.api.post(self.url, {"asset": self.aid, "image": png_file(self.scene, "i.png")}, format="multipart")
        self.assertEqual(r.status_code, 400)
        r = self.post(mask=Image.new("L", (self.W, self.H), 0))
        self.assertEqual(r.status_code, 400)
        self.assertIn("ناحیه‌ای انتخاب نشده", r.json()["error"]["message"])
        r = self.post(image=Image.new("RGB", (2100, 300)), mask=Image.new("L", (2100, 300), 255))
        self.assertEqual(r.status_code, 400)
        self.assertIn("۲۰۴۸", r.json()["error"]["message"])
        r = self.post(seed="abc")
        self.assertEqual(r.status_code, 400)
        self.assertIn("seed", r.json()["error"]["message"])
        self.assertEqual(self.post(asset=999999).status_code, 404)
        self.assertEqual(self.api.get(f"{self.url}00000000-0000-0000-0000-000000000000/").status_code, 404)
        self.assertEqual(ComputeJob.objects.filter(origin="photogenfill").count(), 0)

    def test_store_isolation(self):
        other_owner = User.objects.create_user("photo-other", password="x")
        other_store = Store.objects.create(owner=other_owner, name="فروشگاهِ دیگر")
        foreign = PhotoAsset.objects.create(store=other_store, title="x", original="-")
        self.assertEqual(self.post(asset=foreign.pk).status_code, 404)             # عکسِ فروشگاهِ دیگر
        job = ComputeJob.objects.create(kind="comfy.graph", origin="photogenfill", store=other_store, payload={})
        self.assertEqual(self.api.get(f"{self.url}{job.uid}/").status_code, 404)    # کارِ فروشگاهِ دیگر
        self.assertEqual(self.api.delete(f"{self.url}{job.uid}/").status_code, 404)
        job.refresh_from_db()
        self.assertFalse(job.cancel_requested or job.state == "CANCELLED")
        mine = self.post().json()["job"]
        intruder = APIClient()
        intruder.force_authenticate(other_owner)
        self.assertIn(intruder.get(f"{self.url}{mine}/").status_code, (403, 404))
        self.assertIn(intruder.post(self.url, {"asset": self.aid}, format="multipart").status_code, (403, 404))
        # کارِ دیگری با origin ِ دیگر هم از این مسیر دیده نمی‌شود
        exact = ComputeJob.objects.create(kind="photo.edit", origin="photoexact", store=self.store, payload={})
        self.assertEqual(self.api.get(f"{self.url}{exact.uid}/").status_code, 404)

    def test_too_many_active_jobs_are_refused(self):
        for _ in range(services.GENFILL_MAX_ACTIVE):
            ComputeJob.objects.create(kind="comfy.graph", origin="photogenfill", store=self.store, payload={})
        r = self.post()
        self.assertEqual(r.status_code, 400)
        self.assertIn("در صف", r.json()["error"]["message"])
        ComputeJob.objects.filter(origin="photogenfill").first().delete()
        self.assertEqual(self.post().status_code, 201)

    def test_same_request_with_same_seed_reuses_the_finished_job(self):
        self.comfy_node()
        first = self.post(seed=21).json()
        self.finish(first["job"])
        self.assertEqual(self.api.get(f"{self.url}{first['job']}/").json()["state"], "READY")
        again = self.post(seed=21).json()
        self.assertEqual((again["job"], again["state"], again["message"]), (first["job"], "COMPLETED", "آماده"))
        fresh = self.post(seed=22).json()
        self.assertNotEqual(fresh["job"], first["job"])
        self.assertEqual(fresh["state"], "QUEUED")

    def test_two_pollers_make_one_asset(self):
        self.comfy_node()
        body = self.post().json()
        self.finish(body["job"])
        first = self.api.get(f"{self.url}{body['job']}/").json()
        job = ComputeJob.objects.get(uid=body["job"])
        # کسِ دیگری قفل را دارد و هنوز تمام نکرده ⇒ «در حالِ ساختنِ لایه»، نه عکسِ دوم
        folder = services._genfill_dir(self.store, self.aid)
        info = folder / f"{str(job.uid)[:12]}.json"
        info.unlink()
        lock = folder / f"{str(job.uid)[:12]}.lock"
        lock.write_text("x")
        with mock.patch("time.sleep"):
            st = services.genfill_status(self.store, job.uid)
        self.assertEqual((st["state"], st["message"]), ("RUNNING", "در حالِ ساختنِ لایه…"))
        lock.unlink()
        self.assertEqual(PhotoAsset.objects.filter(source_ref=f"genfill:{body['job']}").count(), 1)
        self.assertEqual(first["state"], "READY")

    def test_lost_mask_input_fails_cleanly(self):
        self.comfy_node()
        body = self.post().json()
        self.finish(body["job"])
        job = ComputeJob.objects.get(uid=body["job"])
        (compute.job_root(job) / "inputs" / job.payload["x_genfill"]["full_mask"]).unlink()
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual(st["state"], "FAILED")
        self.assertIn("ماسک", st["error"])

    def test_deleting_the_source_asset_does_not_break_the_result(self):
        self.comfy_node()
        body = self.post().json()
        self.finish(body["job"])
        services.delete_asset(PhotoAsset.objects.get(pk=self.aid))
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual(st["state"], "READY", st)

    def test_fake_node_command_drives_genfill(self):
        (aid,) = self.upload(photo(500, 400, seed=2))
        call_command("photoedit_fake_node", "online", "--comfy", stdout=io.StringIO())
        r = self.post(asset=aid, image=photo(500, 400, seed=8), mask=disc_mask(500, 400, 250, 200, 30)).json()
        self.assertEqual((r["state"], r["online"]), ("QUEUED", True))
        call_command("photoedit_fake_node", "finish", stdout=io.StringIO())
        st = self.api.get(f"{self.url}{r['job']}/").json()
        self.assertEqual((st["state"], st["node"]), ("READY", "gpu-fake"))
        with self.assertRaises(CommandError):
            call_command("photoedit_fake_node", "finish", stdout=io.StringIO())
        call_command("photoedit_fake_node", "offline", stdout=io.StringIO())
        self.assertFalse(ComputeNode.objects.filter(name="gpu-fake").exists())
