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
