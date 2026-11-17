# -*- coding: utf-8 -*-
"""سنجشِ راست‌به‌چپ و موبایلِ قطعه‌های تبدیل‌شده در مرورگرِ واقعی (Chromium بی‌سر) — ``deploy/c21/rtl_check.py``.

هر قطعه با ``dir="rtl"`` در عرضِ ۳۹۰ و ۱۲۸۰ باز می‌شود: سرریزِ افقیِ صفحه و عنصرهای بیرون‌زده شمرده می‌شود. نتیجه در رکوردِ قطعه (``rtl``) می‌ماند؛
«fail» (گوشی از کنار سرریز می‌کند، یا قطعه به‌صورتِ ایستا هیچ‌چیزِ دیدنی ندارد: «blank») قطعه را از فهرستِ «قابلِ درج» برمی‌دارد، «warn» فقط هشدار است.
«blank»: انیمیشنِ تایپ، canvas، لغزنده روی صفر و مانندش به‌صورتِ HTMLِ ایستا خالی دیده می‌شوند؛ از اسکرین‌شاتِ هر دو عرض شمرده می‌شود چند پیکسل با زمینه فرق دارد (``ink_of``).
مرورگر: ``NM_C21_PLAYWRIGHT_PY`` (پایتونی که Playwright دارد؛ پیش‌فرض /opt/up3d-uitest/venv) و ``PLAYWRIGHT_BROWSERS_PATH``؛ نبودنشان ⇒ «سنجیده نشد» (کارِ دیگر نمی‌ایستد).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import c21_convert as CV, c21_embed as EM, c21st

DEFAULT_PY = "/opt/up3d-uitest/venv/bin/python"
DEFAULT_BROWSERS = "/opt/up3d-uitest/browsers"
_REPO_SCRIPT = Path(__file__).resolve().parents[4] / "deploy" / "c21" / "rtl_check.py"        # همیشه هم‌نسخهٔ کد (بی‌نصبِ دستی)
SCRIPT = _REPO_SCRIPT if _REPO_SCRIPT.exists() else Path(CV.TOOLCHAIN) / "rtl_check.py"
CHECK_VERSION = 3                    # ۲ = اسکرین‌شاتِ «blank» + سرریزِ گوشی ⇒ fail؛ ۳ = «فقط یک قابِ خالی» (بی‌متن و بی‌تصویر) هم blank است؛ رکوردهای با نسخهٔ کمتر خودکار دوباره سنجیده می‌شوند (recheck_outdated)
INK_MIN = 150                        # کمتر از این تعداد پیکسلِ «پررنگ» (اختلافِ هر کانال با زمینه > ۴۰ از ۲۵۵؛ نقطه‌های محوِ شبکهٔ سوسوزن حساب نمی‌شوند) در هر دو عرض ⇒ قطعه خالی است
PAGE_BG = (0xf7, 0xf8, 0xfa)

PAGE = ('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>:root{--brand:#126f85;--brand-ink:#fff;--ink:#111827;--ink-2:#374151;--ink-3:#6b7280;--line:#e5e7eb;--bg:#f7f8fa;--card:#fff;--r:16px}'
        'body{margin:0;background:var(--bg);color:var(--ink);font-family:Tahoma,sans-serif}.nb-wrap{max-width:1140px;margin:0 auto;padding:24px 16px}</style>'
        '<style>%s</style></head><body>%s</body></html>')


def available() -> tuple[bool, str]:
    py = os.environ.get("NM_C21_PLAYWRIGHT_PY") or DEFAULT_PY
    if not os.path.exists(py):
        return False, "پایتونِ Playwright نیست (%s)" % py
    if not SCRIPT.exists():
        return False, "rtl_check.py در جعبه‌ابزار نیست"
    return True, ""


def ink_of(png_path, bg=PAGE_BG, step: int = 2, delta: int = 40):
    """اسکرین‌شات ⇒ تعدادِ (تقریبیِ) پیکسل‌هایی که با زمینهٔ صفحه فرق دارند؛ فایل/Pillow نبود ⇒ None."""
    try:
        from PIL import Image
        im = Image.open(png_path).convert("RGB")
    except Exception:                      # noqa: BLE001
        return None
    px, (w, h), n = im.load(), im.size, 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = px[x, y]
            if abs(c[0] - bg[0]) > delta or abs(c[1] - bg[1]) > delta or abs(c[2] - bg[2]) > delta:
                n += 1
    return n * step * step


def check(keys: list[str], *, runner=subprocess.run, timeout: int = 600) -> dict:
    """⇒ {key: {status, overflow_390, overflow_1280, …}}؛ مرورگر نبود ⇒ {key: {status: 'skipped', why}}."""
    ok, why = available()
    if not ok:
        return {k: {"status": "skipped", "why": why} for k in keys}
    tmp = Path(tempfile.mkdtemp(prefix="nm-c21-rtl-"))
    try:
        for k in keys:
            pv = EM.preview_page(k)
            if pv:
                (tmp / (k + ".html")).write_text(PAGE % (pv["css"], pv["html"]), encoding="utf-8")
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or DEFAULT_BROWSERS)
        py = os.environ.get("NM_C21_PLAYWRIGHT_PY") or DEFAULT_PY
        r = runner([py, str(SCRIPT), str(tmp), str(tmp / "rtl.json")], capture_output=True, text=True, timeout=timeout, env=env)
        try:
            res = json.loads((tmp / "rtl.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {k: {"status": "skipped", "why": "مرورگر نتیجه نداد: " + (r.stderr or "")[-120:]} for k in keys}
        for k, row in res.items():                                        # «خالیِ ایستا»: در هیچ‌کدام از دو عرض چیزِ دیدنی نیست
            inks = [ink_of(tmp / ("%s-%d.png" % (k, w))) for w in (390, 1280)]
            inks = [i for i in inks if i is not None]
            if inks:
                row["ink"] = max(inks)
                if row.get("status") in ("ok", "warn") and max(inks) < INK_MIN:
                    row["status"], row["blank"] = "fail", True
                    row["why"] = "به‌صورتِ ایستا چیزِ دیدنی ندارد (انیمیشن/canvas/مقدارِ صفر)"
            # فقط یک قابِ خالی (حاشیه یا پس‌زمینه «جوهر» می‌دهد ولی نه متنی هست نه تصویر/فیلد/دکمه): کارِ canvas یا انیمیشنِ جاوااسکریپتی است
            if row.get("status") in ("ok", "warn") and all(int(row.get("text_%d" % w, 1)) == 0 and int(row.get("visual_%d" % w, 1)) == 0 for w in (390, 1280)):
                row["status"], row["blank"] = "fail", True
                row["why"] = "به‌صورتِ ایستا فقط یک قابِ خالی است (بی‌متن و بی‌تصویر؛ canvas/انیمیشن)"
        return res
    except subprocess.TimeoutExpired:
        return {k: {"status": "skipped", "why": "مهلتِ سنجش تمام شد"} for k in keys}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def apply(keys: list[str], **kw) -> dict:
    res = check(keys, **kw)
    status = {}
    for k, row in res.items():
        rec = CV.load_record(k)
        if rec:
            rec["rtl"] = {"status": row.get("status", "skipped"), "overflow_390": bool(row.get("overflow_390")), "overflow_1280": bool(row.get("overflow_1280")),
                          "rtl": bool(row.get("rtl", True)), "why": row.get("why", ""), "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "blank": bool(row.get("blank")), "ink": row.get("ink"), "v": CHECK_VERSION if row.get("status") not in ("skipped", "error") else 0}
            CV.save_record(rec)
            status[k] = rec["rtl"]["status"]
    rows = c21st.load()
    for r in rows:
        conv = r.get("conv") or {}
        if conv.get("key") in status:
            conv["rtl"] = status[conv["key"]]
    c21st.save(rows)
    return res


def outdated_keys(limit: int = 60) -> list[str]:
    """رکوردهای تبدیل‌شده‌ای که با نسخهٔ فعلیِ سنجش نسنجیده‌اند (یا هرگز سنجیده نشدند)."""
    out = []
    for e in CV.load_index().values():
        rec = CV.load_record(e["key"])
        if rec and int((rec.get("rtl") or {}).get("v") or 0) < CHECK_VERSION:
            out.append(e["key"])
            if len(out) >= limit:
                break
    return out


def recheck_outdated(limit: int = 60, **kw) -> dict:
    """دسته‌ای از قطعه‌های قدیمی را دوباره می‌سنجد (خودکار از تسکِ تبدیل؛ مرورگر نبود ⇒ هیچ‌چیز عوض نمی‌شود). ⇒ {checked, statuses}."""
    ok, why = available()
    if not ok:
        return {"checked": 0, "left": -1, "why": why}
    keys = outdated_keys(limit)
    if not keys:
        return {"checked": 0, "left": 0}
    res = apply(keys, **kw)
    done = {k: (v or {}).get("status", "skipped") for k, v in res.items()}
    return {"checked": sum(1 for v in done.values() if v not in ("skipped", "error")), "statuses": done, "left": len(outdated_keys(1000))}
