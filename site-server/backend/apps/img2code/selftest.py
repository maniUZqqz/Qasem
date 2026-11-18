# -*- coding: utf-8 -*-
"""آزمونِ پذیرشِ «تصویر به کد» (بی‌پایگاه‌داده): یک صفحهٔ کوچکِ ساختگی از آغاز تا سندِ سایت‌ساز؛ هم‌ریشهٔ ``manage.py img2code_check`` و آزمونِ خودکارِ سرورِ پردازش
(``compute/selftests/img2code.py``، آزمونِ «مجازی» که با روشن‌شدنِ گره و هر شب خودش اجرا می‌شود).

«تصویر به کد» روی CPU ِ همین سرورِ سایت اجراست (نه روی GPU)، پس این آزمون منتظرِ گره نمی‌ماند؛ در همین ماشین خودکار می‌گذرد و اگر یکی از پیش‌نیازها
(mv2code، Tesseract فارسی+انگلیسی، مرورگرِ بی‌سر) نباشد، دلیلِ دقیق را می‌گوید.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path


def _page(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (900, 560), (241, 245, 249))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 900, 70], fill=(255, 255, 255))
    big, small = ImageFont.load_default(size=44), ImageFont.load_default(size=22)
    d.text((60, 14), "ShopName", font=small, fill=(27, 110, 194))
    d.text((220, 140), "Welcome to the shop", font=big, fill=(15, 42, 74))
    d.text((250, 215), "Everything you need to get started", font=small, fill=(65, 80, 106))
    d.rounded_rectangle([330, 300, 570, 360], radius=14, fill=(27, 110, 194))
    d.text((385, 318), "Get started", font=small, fill=(255, 255, 255))
    im.save(path)


def _page_gradient(path: Path) -> None:
    """سربرگ + هیرویِ گرادیانِ تمام‌عرض که رنگِ آخرش با پس‌زمینهٔ صفحه یکی است (الگویی که موتورِ ۲٫۲ و قبل‌تر را یک تصویر می‌کرد) + سه کارت + نوارِ دعوتِ گرادیان."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    W, H = 960, 640
    a = np.zeros((H, W, 3), np.float64)
    a[:] = (11, 18, 32)
    a[0:56] = (16, 26, 48)
    yy, xx = np.mgrid[0:290, 0:W].astype(np.float64)
    t = np.clip(((xx - W / 2) * 0.7071 + (yy - 145) * 0.7071) / (W * 0.7071 + 290 * 0.7071) + 0.5, 0, 1)[..., None]
    a[56:346] = np.array((20, 38, 77)) * (1 - t) + np.array((11, 18, 32)) * t
    for k in range(3):
        a[400:500, 40 + k * 300:320 + k * 300] = (22, 33, 58)
    yy, xx = np.mgrid[0:100, 0:W - 80].astype(np.float64)
    t = np.clip(((xx - (W - 80) / 2) * 0.7071 + (yy - 50) * 0.7071) / ((W - 80) * 0.7071 + 100 * 0.7071) + 0.5, 0, 1)[..., None]
    a[520:620, 40:W - 40] = np.array((109, 40, 217)) * (1 - t) + np.array((37, 99, 235)) * t
    im = Image.fromarray(np.round(a).astype(np.uint8))
    d = ImageDraw.Draw(im)
    big, small = ImageFont.load_default(size=44), ImageFont.load_default(size=22)
    d.text((60, 14), "ShopName", font=small, fill=(200, 211, 238))
    d.text((60, 140), "Welcome to the shop", font=big, fill=(255, 255, 255))
    d.text((60, 215), "Everything you need to get started", font=small, fill=(220, 228, 245))
    d.rounded_rectangle([60, 270, 260, 320], radius=12, fill=(34, 197, 94))
    d.text((100, 284), "Get started", font=small, fill=(6, 33, 15))
    im.save(path)


FA_LINES = [("برنامه تمرینی و غذایی اختصاصی", 26, 70), ("پشتیبانی مربیان و بدنسازی برای همه", 18, 140), ("همهٔ حقوق محفوظ است", 14, 200), ("تماس با ما و ثبت نام", 14, 240)]
FA_WORDS = ["برنامه", "تمرینی", "غذایی", "اختصاصی", "پشتیبانی", "مربیان", "بدنسازی", "حقوق", "محفوظ", "تماس"]


def _page_fa(path: Path) -> bool:
    """یک صفحهٔ فارسیِ کوچک با نوشته‌های ریز (همان‌جا که OCR ِ فارسی نقطه‌ها را گم می‌کرد) با قلمِ همراهِ موتور؛ False اگر Pillow شکل‌دهیِ فارسی (raqm) ندارد."""
    import os

    import mv2code
    from PIL import Image, ImageDraw, ImageFont, features
    if not features.check("raqm"):
        return False
    fonts = os.path.join(os.path.dirname(mv2code.__file__), "fonts")
    ttf = next((os.path.join(fonts, n) for n in sorted(os.listdir(fonts)) if n.lower().startswith("vazirmatn") and n.lower().endswith((".ttf", ".otf"))), None)
    if ttf is None:
        return False
    im = Image.new("RGB", (900, 300), (250, 251, 253))
    d = ImageDraw.Draw(im)
    for text, size, y in FA_LINES:
        d.text((860, y), text, font=ImageFont.truetype(ttf, size, layout_engine=ImageFont.Layout.RAQM), fill=(24, 32, 48), anchor="ra", direction="rtl", language="fa")
    im.save(path)
    return True


def run_engine(url: str = "", wait_s: int = 150) -> dict:
    """⇒ {ok, steps:[{name, ok, detail}], seconds}. هر مرحله جدا گزارش می‌شود؛ ``url`` (اختیاری) عکس‌گرفتن از یک نشانیِ عمومی را هم می‌سنجد."""
    import numpy as np
    from PIL import Image

    from . import mapping, services

    t0 = time.monotonic()
    steps: list = []

    def step(name: str, ok: bool, detail="") -> bool:
        steps.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})
        return bool(ok)

    def done() -> dict:
        return {"ok": all(s["ok"] for s in steps), "steps": steps, "seconds": round(time.monotonic() - t0, 1)}

    eng = services.engine_status(refresh=True)
    step("موتور (mv2code)", eng["ready"], eng["version"] or "؛ ".join(eng["messages"]))
    step("Tesseract فارسی+انگلیسی", eng["ocr"], "" if eng["ocr"] else "بدونِ OCR فقط نشانیِ صفحه متن می‌گیرد")
    step("مرورگرِ بی‌سر", eng["compare_ok"], "" if eng["compare_ok"] else "؛ ".join(eng["messages"]))
    if not eng["ready"]:
        return done()
    lock = services.RunLock()
    deadline = time.monotonic() + wait_s
    while not lock.acquire():                       # هم‌زمان فقط یک تبدیل (مثلِ تبدیل‌های کاربر)
        if time.monotonic() > deadline:
            step("نوبت", False, "یک تبدیلِ دیگر تا %d ثانیه تمام نشد" % wait_s)
            return done()
        time.sleep(2)
    tmp = Path(tempfile.mkdtemp(prefix="img2code-check-"))
    try:
        src = tmp / "page.png"
        _page(src)
        out = tmp / "out"
        res = services.run_process(["convert", "--image", src, "--outdir", out, "--mode", "responsive", "--lang", "en"], services.CONVERT_TIMEOUT, mem=services.CONVERT_MEM)
        if not step("تبدیل (پردازهٔ جدا با سقفِ حافظه و زمان)", res.get("ok"), res.get("message") or "%.1f ثانیه" % ((res.get("report") or {}).get("seconds") or {}).get("total", 0)):
            return done()
        html = (out / "index.html").read_text(encoding="utf-8")
        step("متنِ واقعی در HTML", "Welcome" in html, "text_lines=%s" % (res.get("report") or {}).get("text_lines"))
        # هیرویِ گرادیانِ تمام‌عرض باید CSS شود، نه یک تصویر (موتورِ ۲٫۳)
        grad_png = tmp / "gradient.png"
        _page_gradient(grad_png)
        res_g = services.run_process(["convert", "--image", grad_png, "--outdir", tmp / "out_grad", "--mode", "responsive", "--lang", "en"], services.CONVERT_TIMEOUT, mem=services.CONVERT_MEM)
        if step("تبدیلِ صفحهٔ دارای هیرویِ گرادیان", res_g.get("ok"), res_g.get("message") or ""):
            html_g = (tmp / "out_grad" / "index.html").read_text(encoding="utf-8")
            share = services.measure_image_share(tmp / "out_grad" / "tree.json")
            step("هیرویِ گرادیان = CSS و متنِ واقعی (نه یک تصویر)", "linear-gradient(" in html_g and "<img" not in html_g and "Welcome" in html_g and share is not None and share < 0.05,
                 "سهمِ تصویر %s، %s ناحیه" % (share, (res_g.get("report") or {}).get("regions")))
        fa_png = tmp / "fa.png"
        if eng["ocr"] and _page_fa(fa_png):
            res_fa = services.run_process(["convert", "--image", fa_png, "--outdir", tmp / "out_fa", "--mode", "responsive", "--lang", "fa", "--glossary", "چغر"], services.CONVERT_TIMEOUT, mem=services.CONVERT_MEM)
            if step("تبدیلِ صفحهٔ فارسی (متنِ ریز)", res_fa.get("ok"), res_fa.get("message") or ""):
                html_fa = (tmp / "out_fa" / "index.html").read_text(encoding="utf-8").replace("‌", "")
                got = [w for w in FA_WORDS if w in html_fa]
                step("خواندنِ متنِ فارسی (OCR + واژه‌نامه)", len(got) >= 8, "%d از %d واژه: %s" % (len(got), len(FA_WORDS), "، ".join(w for w in FA_WORDS if w not in got) or "همه"))
                rep_fa = res_fa.get("report") or {}
                step("علامت‌گذاریِ خط‌های مشکوکِ OCR («این خط را بررسی کن»)", "review_lines" in rep_fa and isinstance(rep_fa.get("review"), list), "%s خط مشکوک از %s خط" % (rep_fa.get("review_lines"), rep_fa.get("text_lines")))
        elif eng["ocr"]:
            step("تبدیلِ صفحهٔ فارسی (متنِ ریز)", True, "ردشد (Pillow شکل‌دهیِ فارسی ندارد)")
        if eng["compare_ok"]:
            r2 = services.run_process(["render", "--dir", out], services.RENDER_TIMEOUT)
            step("نمایش و سنجش در مرورگر", r2.get("ok") and (out / "rendered.png").exists(), r2.get("scores") or r2.get("message"))
        tree = json.loads((out / "tree.json").read_text(encoding="utf-8"))
        r = mapping.map_tree(tree, np.array(Image.open(out / "original.png").convert("RGB")))
        docs = mapping.clean_docs(r)
        step("درخت ⇒ سندِ سایت‌ساز (clean_doc)", "Welcome to the shop" in json.dumps(docs["page"], ensure_ascii=False), r["stats"])
        if url:
            shot, lines = tmp / "shot.png", tmp / "lines.json"
            r3 = services.run_process(["shot", "--url", url, "--out", shot, "--lines-out", lines], services.SHOT_TIMEOUT)
            if step("عکسِ کاملِ صفحه از نشانی", r3.get("ok"), ("%sx%s، %s خطِ متنِ DOM" % (r3.get("width"), r3.get("height"), r3.get("dom_lines"))) if r3.get("ok") else r3.get("message")):
                r4 = services.run_process(["convert", "--image", shot, "--outdir", tmp / "out2", "--mode", "responsive", "--lines", lines], services.CONVERT_TIMEOUT, mem=services.CONVERT_MEM)
                step("تبدیلِ همان عکس (متن از خودِ صفحه)", r4.get("ok"), "text_lines=%s nodes=%s" % ((r4.get("report") or {}).get("text_lines"), r4.get("nodes")))
    except Exception as exc:  # noqa: BLE001 — آزمون هیچ‌وقت نباید بیندازد؛ شکست را گزارش می‌کند
        step("اجرا", False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        lock.release()
        shutil.rmtree(tmp, ignore_errors=True)
    return done()
