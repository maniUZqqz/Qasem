# -*- coding: utf-8 -*-
"""کارگرِ جدا برای «تصویر به کد»: هر کارِ سنگین در یک پردازهٔ خودش اجرا می‌شود (از services.py)، نه داخلِ worker ِ celery.

چرا پردازهٔ جدا؟ ⇒ (۱) سقفِ حافظه و زمان را می‌شود روی خودِ پردازه گذاشت (RLIMIT_AS، timeout، kill گروهی) بی‌آنکه worker ِ سایت بمیرد؛
(۲) مرورگر (Chromium) و OCR (Tesseract) هر کدام آزاد می‌شوند و چیزی در رمِ worker نمی‌ماند؛ (۳) جنگو لازم نیست (شروعِ سریع).

    python -m apps.img2code.runner probe
    python -m apps.img2code.runner shot    --url URL --out shot.png [--width 1280] [--max-height 9000]
    python -m apps.img2code.runner convert --image in.png --outdir DIR [--mode responsive|exact] [--lang auto|fa|en] [--title T]
    python -m apps.img2code.runner render  --dir DIR [--out rendered.png]

خروجی: هر فرمان در آخرین خط «RESULT {json}» چاپ می‌کند؛ خط‌های دیگر لاگ‌اند. کدِ خروج همیشه ۰ است مگر خودِ پردازه بمیرد؛ خطا در json (ok=false).
فقط کتابخانهٔ mv2code (پین‌شده در deploy/nm/requirements-img2code.txt) + playwright استفاده می‌شود؛ هیچ‌چیزِ mv2code کپی نشده است.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

MAX_SHOT_HEIGHT = 9000
MAX_SHOT_PIXELS = 30_000_000


def emit(obj: dict) -> None:
    print("RESULT " + json.dumps(obj, ensure_ascii=False), flush=True)


def fail(code: str, message: str, **extra) -> None:
    emit({"ok": False, "error": code, "message": message, **extra})


# ----------------------------------------------------------------------------------------------- probe
def cmd_probe(_args) -> None:
    out: dict = {"ok": True}
    try:
        import mv2code
        out["mv2code"] = mv2code.__version__
    except Exception as exc:  # noqa: BLE001
        out["mv2code"] = None
        out["mv2code_error"] = "%s: %s" % (type(exc).__name__, exc)
    tess = shutil.which("tesseract")
    out["tesseract"] = None
    if tess:
        try:
            langs = subprocess.run([tess, "--list-langs"], capture_output=True, text=True, timeout=15).stdout.split()
        except Exception:  # noqa: BLE001
            langs = []
        out["tesseract"] = {"path": tess, "fas": "fas" in langs, "eng": "eng" in langs}
    try:
        import pytesseract  # noqa: F401
        out["pytesseract"] = True
    except Exception:  # noqa: BLE001
        out["pytesseract"] = False
    try:
        import playwright  # noqa: F401
        out["playwright"] = True
    except Exception:  # noqa: BLE001
        out["playwright"] = False
    try:
        from mv2code.browser import find_chrome
        out["chrome"] = find_chrome()
    except Exception:  # noqa: BLE001
        out["chrome"] = None
    emit(out)


# ----------------------------------------------------------------------------------------------- shot
def _dom_lines(page, width: int, height: int) -> list:
    """خط‌های متنِ واقعیِ صفحه (از DOM) با جعبه‌شان؛ همان قالبی که mv2code برای ``ocr_lines`` می‌گیرد.
    وقتی نشانیِ صفحه را داریم، متن را از خودِ صفحه می‌خوانیم (دقیق، فارسیِ درست) نه از OCR؛ جعبه‌ها از همان کاوشگرِ خودِ mv2code می‌آید."""
    from mv2code.browser import PROBE_JS
    try:
        data = page.evaluate(PROBE_JS)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for t in (data or {}).get("texts", []):
        if t.get("occluded"):
            continue
        rows = t.get("lines") or [{"text": t.get("text", ""), "box": t.get("box")}]
        for ln in rows:
            txt = " ".join(str(ln.get("text", "")).split())
            b = ln.get("box") or []
            if not txt or len(b) != 4:
                continue
            x, y, w, h = [float(v) for v in b]
            if w < 3 or h < 5 or x + w < 0 or y + h < 0 or x > width or y > height:
                continue
            out.append({"box": [round(x, 1), round(y, 1), round(w, 1), round(h, 1)], "text": txt[:600], "conf": 1.0})
            if len(out) >= 1500:
                return out
    return out


def _chrome_args() -> list[str]:
    return ["--no-sandbox", "--disable-gpu", "--force-device-scale-factor=1", "--font-render-hinting=none", "--hide-scrollbars",
            "--disable-dev-shm-usage", "--mute-audio"]


def cmd_shot(args) -> None:
    from apps.img2code import netguard
    try:
        url = netguard.check_url(args.url)
    except netguard.UrlRefused as exc:
        return fail("url_refused", str(exc))
    try:
        from playwright.sync_api import sync_playwright
        from mv2code.browser import find_chrome
    except Exception as exc:  # noqa: BLE001
        return fail("no_browser", "مرورگرِ بی‌سرِ سرور آماده نیست؛ از «تصویر را بارگذاری کنید» استفاده کنید.", detail=str(exc)[:200])

    width = max(320, min(2000, int(args.width)))
    max_h = max(600, min(MAX_SHOT_HEIGHT, int(args.max_height)))
    verdicts: dict[str, bool] = {}

    def host_ok(u: str) -> bool:
        from urllib.parse import urlsplit
        p = urlsplit(u)
        if p.scheme in ("data", "blob", "about"):
            return True
        if p.scheme not in ("http", "https"):
            return False
        h = (p.hostname or "").lower()
        if h not in verdicts:
            try:
                netguard.resolve_public(h)
                verdicts[h] = True
            except netguard.UrlRefused:
                verdicts[h] = False
        return verdicts[h]

    blocked = []

    def guard(route):
        req = route.request
        if req.resource_type in ("media", "websocket", "eventsource") or not host_ok(req.url):
            if req.resource_type not in ("media", "websocket", "eventsource"):
                blocked.append(req.url[:120])
            return route.abort()
        return route.continue_()

    t0 = time.perf_counter()
    exe = find_chrome()
    title = ""
    final_url = url
    truncated = False
    dom_lines: list = []
    with sync_playwright() as pw:
        kwargs = {"args": _chrome_args()}
        browser = pw.chromium.launch(executable_path=exe, **kwargs) if exe else pw.chromium.launch(channel="chromium", **kwargs)
        try:
            ctx = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1, locale="fa-IR", service_workers="block",
                                      java_script_enabled=True, accept_downloads=False, bypass_csp=False)
            ctx.route("**/*", guard)
            page = ctx.new_page()
            page.set_default_timeout(25000)
            try:
                page.goto(url, wait_until="load", timeout=40000)
            except Exception as exc:  # noqa: BLE001
                return fail("load_failed", "صفحه باز نشد یا بیش از اندازه کند بود.", detail=str(exc)[:200])
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:  # noqa: BLE001 — سایت‌های همیشه‌پرسه‌زن
                pass
            final_url = page.url
            if not host_ok(final_url):
                return fail("url_refused", "نشانی پس از ریدایرکت به شبکهٔ داخلی رسید؛ پذیرفته نشد.")
            try:  # بارگذاریِ تنبلِ تصویرها: نرم تا پایینِ صفحه برو
                page.evaluate("""async (maxH) => { const step = Math.max(300, innerHeight * 0.8); let y = 0;
                    while (y < Math.min(document.documentElement.scrollHeight, maxH)) { scrollTo(0, y); await new Promise(r => setTimeout(r, 140)); y += step; }
                    scrollTo(0, 0); await new Promise(r => setTimeout(r, 250)); }""", max_h)
                page.evaluate("document.fonts && document.fonts.ready")
                page.wait_for_timeout(300)
            except Exception:  # noqa: BLE001
                pass
            try:
                title = (page.title() or "")[:140]
            except Exception:  # noqa: BLE001
                title = ""
            full_h = int(page.evaluate("Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)") or 900)
            h = min(max(full_h, 200), max_h)
            if width * h > MAX_SHOT_PIXELS:
                h = MAX_SHOT_PIXELS // width
            truncated = full_h > h
            if args.lines_out:
                dom_lines = _dom_lines(page, width, h)
            if truncated:
                png = page.screenshot(type="png", full_page=True, clip={"x": 0, "y": 0, "width": width, "height": h}, animations="disabled")
            else:
                png = page.screenshot(type="png", full_page=True, animations="disabled")
        finally:
            browser.close()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(png)
    try:
        from PIL import Image
        with Image.open(args.out) as im:
            w, hh = im.size
    except Exception:  # noqa: BLE001
        w, hh = width, h
    if args.lines_out:
        with open(args.lines_out, "w", encoding="utf-8") as fh:
            json.dump(dom_lines, fh, ensure_ascii=False)
    emit({"ok": True, "width": w, "height": hh, "title": title, "final_url": final_url, "truncated": truncated, "page_height": full_h,
          "dom_lines": len(dom_lines),
          "blocked_requests": blocked[:10], "seconds": round(time.perf_counter() - t0, 2)})


# ----------------------------------------------------------------------------------------------- convert
def cmd_convert(args) -> None:
    try:
        from mv2code import ImageError, convert
        from mv2code.bundle import write_bundle
        from mv2code.imaging import load_image
    except Exception as exc:  # noqa: BLE001
        return fail("no_engine", "موتورِ تبدیل (mv2code) روی سرور نصب نیست.", detail=str(exc)[:200])
    dpr = float(args.dpr) if args.dpr else None
    try:
        rgb, info = load_image(args.image, dpr=dpr)
        lines = None
        if args.lines and os.path.exists(args.lines):
            with open(args.lines, encoding="utf-8") as fh:
                lines = json.load(fh) or None
        res = convert(args.image, mode=args.mode, lang=args.lang, ocr="auto", refine="off", dpr=dpr, title=args.title or "Converted page",
                      ocr_lines=lines)
    except ImageError as exc:
        return fail("bad_image", "این فایل تصویرِ قابلِ خواندنی نیست یا خیلی کوچک/بزرگ است.", detail=str(exc)[:200])
    except (RuntimeError, ValueError) as exc:
        return fail("convert_failed", "تبدیل شکست خورد.", detail="%s: %s" % (type(exc).__name__, str(exc)[:300]))
    write_bundle(res, args.outdir, "index", original=rgb)
    with open(os.path.join(args.outdir, "style.css"), "w", encoding="utf-8") as fh:
        fh.write(res.get("css") or "")
    emit({"ok": True, "report": res["report"], "size": [int(rgb.shape[1]), int(rgb.shape[0])], "scale": info["scale"],
          "html_bytes": len(res["html"].encode("utf-8")), "nodes": res["report"].get("nodes")})


# ----------------------------------------------------------------------------------------------- render + score
def cmd_render(args) -> None:
    try:
        import cv2
        from mv2code.browser import Browser
        from mv2code.emit import font_assets
        from mv2code.score import compare
    except Exception as exc:  # noqa: BLE001
        return fail("no_browser", "مرورگرِ بی‌سر یا موتورِ تبدیل روی سرور آماده نیست؛ نتیجه بدونِ تصویرِ مقایسه می‌ماند.", detail=str(exc)[:200])
    d = os.path.abspath(args.dir)
    try:
        with open(os.path.join(d, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        orig_bgr = cv2.imread(os.path.join(d, "original.png"), cv2.IMREAD_COLOR)
        if orig_bgr is None:
            return fail("no_original", "تصویرِ اصلی کنارِ نتیجه پیدا نشد.")
        orig = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2RGB)
        H, W = orig.shape[:2]
        out = args.out or os.path.join(d, "rendered.png")
        with Browser() as br:
            img, _ = br.render("file://" + os.path.join(d, "index.html").replace("\\", "/"), W, min_height=min(H, 900), max_height=MAX_SHOT_HEIGHT,
                               probe=False, shot=True, js="() => 0")
            scores = compare(orig, html, font_assets(), br)
        cv2.imwrite(out, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    except Exception as exc:  # noqa: BLE001
        return fail("render_failed", "نتیجه در مرورگر نمایش داده نشد.", detail="%s: %s" % (type(exc).__name__, str(exc)[:300]))
    emit({"ok": True, "scores": scores, "rendered": os.path.basename(out)})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="img2code-runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe")
    s = sub.add_parser("shot")
    s.add_argument("--url", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--width", type=int, default=1280)
    s.add_argument("--max-height", type=int, default=MAX_SHOT_HEIGHT)
    s.add_argument("--lines-out", default="", help="write the page's real text lines (DOM) as ocr_lines json")
    c = sub.add_parser("convert")
    c.add_argument("--image", required=True)
    c.add_argument("--outdir", required=True)
    c.add_argument("--mode", default="responsive", choices=["responsive", "exact"])
    c.add_argument("--lang", default="auto", choices=["auto", "fa", "en"])
    c.add_argument("--title", default="")
    c.add_argument("--dpr", default="")
    c.add_argument("--lines", default="", help="json with ocr_lines (text read from the page itself) instead of OCR")
    r = sub.add_parser("render")
    r.add_argument("--dir", required=True)
    r.add_argument("--out", default="")
    args = ap.parse_args(argv)
    try:
        {"probe": cmd_probe, "shot": cmd_shot, "convert": cmd_convert, "render": cmd_render}[args.cmd](args)
    except MemoryError:
        fail("memory", "حافظهٔ سرور برای این تصویر کافی نبود؛ تصویرِ کوچک‌تری امتحان کنید.")
    except Exception as exc:  # noqa: BLE001
        fail("crashed", "خطای پیش‌بینی‌نشده در پردازش.", detail="%s: %s" % (type(exc).__name__, str(exc)[:300]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
