# -*- coding: utf-8 -*-
"""سنجشِ راست‌به‌چپ و موبایلِ قطعه‌های تبدیل‌شده در مرورگرِ واقعی (Chromium بی‌سر) — ``deploy/c21/rtl_check.py``.

هر قطعه با ``dir="rtl"`` در عرضِ ۳۹۰ و ۱۲۸۰ باز می‌شود: سرریزِ افقیِ صفحه و عنصرهای بیرون‌زده شمرده می‌شود. نتیجه در رکوردِ قطعه (``rtl``) می‌ماند؛
«fail» (در هر دو عرض سرریز) قطعه را از فهرستِ «قابلِ درج» برمی‌دارد، «warn» فقط هشدار است.
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
SCRIPT = Path(CV.TOOLCHAIN) / "rtl_check.py"

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
            return json.loads((tmp / "rtl.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {k: {"status": "skipped", "why": "مرورگر نتیجه نداد: " + (r.stderr or "")[-120:]} for k in keys}
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
                          "rtl": bool(row.get("rtl", True)), "why": row.get("why", ""), "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            CV.save_record(rec)
            status[k] = rec["rtl"]["status"]
    rows = c21st.load()
    for r in rows:
        conv = r.get("conv") or {}
        if conv.get("key") in status:
            conv["rtl"] = status[conv["key"]]
    c21st.save(rows)
    return res
