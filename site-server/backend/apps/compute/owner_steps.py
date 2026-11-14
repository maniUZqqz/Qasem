# -*- coding: utf-8 -*-
"""«کارهایی که فقط خودِ مالک می‌تواند بکند» — در پنل (ابزارها ⇒ سرورهای پردازش ⇒ آزمونِ خودکار) روشن و زنده، نه فقط در یک فایل.

هدفِ این دور: مالک سرورِ پردازش را به‌روز و روشن می‌کند و همه‌چیز خودش کار می‌کند. چیزهایی که هیچ کدی نمی‌تواند به‌جای مالک انجام دهد
(حساب، اعتبار، مجوز، تأییدِ واقعیت‌های برند) اینجا یک‌جا و با وضعیتِ زنده فهرست می‌شوند:

    state = ok      خودش (از روی داده‌های زنده) معلوم است که انجام شده
            todo    هنوز مانده؛ ``how`` می‌گوید دقیقاً چه کنید
            wait    منتظرِ تأییدِ مالک (تصمیم یا حساب)؛ با تیکِ «انجام شد» بسته می‌شود
            unknown هنوز داده‌ای نیست (مثلاً گره هنوز روشن نشده)

وضعیتِ «تیکِ مالک» در ``NM_DATA_DIR/owner-steps.json`` می‌ماند (فایل؛ بدونِ مهاجرت). هیچ سازوکاری از راهِ دور (PC Remote) این‌جا نیست: آن ابزارِ جداست.
هر بررسیِ زنده با try/except می‌گذرد: خرابیِ یکی بقیه را نمی‌اندازد.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

TERMINAL = ("ok",)


def _path() -> Path:
    return Path(settings.NM_DATA_DIR) / "owner-steps.json"


def _marks() -> dict:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def set_mark(key: str, done: bool) -> dict:
    if key not in {s["key"] for s in definitions()}:
        raise KeyError(key)
    m = _marks()
    if done:
        m[key] = {"at": timezone.now().isoformat(timespec="seconds")}
    else:
        m.pop(key, None)
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return m


# ───────────────────────────── بررسی‌های زنده (هرکدام ⇒ (state, detail))

def _latest_selftest(key: str):
    from .models import ComputeNode, SelfTestResult

    node = ComputeNode.objects.filter(enabled=True).order_by("-last_seen").first()
    if node is None:
        return None, None
    r = SelfTestResult.objects.filter(run__node=node, key=key).order_by("-run_id").first()
    return node, r


def _live_node():
    from .models import ComputeNode

    node = ComputeNode.objects.filter(enabled=True).order_by("-last_seen").first()
    if node is None or not node.last_seen:
        return "unknown", "هنوز هیچ سرورِ پردازشی ثبت نشده است."
    if node.online:
        return "ok", "«%s» روشن است (نسخهٔ عامل %s)." % (node.name, (node.capabilities or {}).get("agent") or "؟")
    hours = int((timezone.now() - node.last_seen).total_seconds() // 3600)
    return "todo", "«%s» از %d ساعت پیش خاموش است؛ کامپیوتر را روشن کنید (همه‌چیز خودش بالا می‌آید و آزمایش می‌شود)." % (node.name, hours)


def _instai_auto() -> bool:
    """عاملِ گره «همسایهٔ InstAI» (processing/instai_jobs.py) را دارد؟ آن‌گاه خودش پوشه را پیدا، به‌روز و روشن می‌کند."""
    try:
        return (Path(settings.BASE_DIR).parent / "processing" / "instai_jobs.py").is_file()
    except Exception:  # noqa: BLE001
        return False


_INSTAI_ZIP = ("ZIPِ شاخهٔ main از github.com/maniUZqqz/Instai را بگیرید، data و models و tools و فایلِ .env را از پوشهٔ قدیمی رویش کپی کنید و START.bat را بزنید. "
               "از آن به بعد خودش به‌روز می‌شود و با ورود به ویندوز بالا می‌آید.")


def _instai():
    """InstAI را (اگر عاملِ گره همسایه‌اش را داشته باشد) خودِ عامل پیدا، به‌روز و روشن می‌کند؛ آزمونِ «instai» از گزارشِ ضربان می‌خواند.
    بدونِ آن عامل، همان یک بار ZIPِ تازه کارِ دستیِ مالک می‌ماند."""
    if not _instai_auto():
        return "todo", "عاملِ سرورِ پردازش هنوز InstAI را خودکار به‌روز نمی‌کند؛ پوشه را یک بار دستی با ZIPِ تازه عوض کنید."
    node, r = _latest_selftest("instai")
    if r is None:
        return "unknown", "آزمونِ InstAI هنوز اجرا نشده (با روشن‌شدنِ سرورِ پردازش خودکار اجرا می‌شود)."
    if r.state == "PASSED":
        return "ok", r.detail or "InstAI روشن و به‌روز است."
    if r.state in ("PENDING", "WAITING", "QUEUED", "RUNNING"):
        return "wait", r.detail or "InstAI در حالِ به‌روزرسانی یا بالا آمدن است؛ خودش تمام می‌کند."
    return "todo", r.detail or "InstAI به توجهِ شما نیاز دارد."


def _abagram():
    node, r = _latest_selftest("ig_scrape")
    if r is None:
        return "unknown", "آزمونِ خوانندهٔ اینستاگرام هنوز اجرا نشده."
    if r.state == "PASSED":
        return "ok", r.detail or "خوانندهٔ اینستاگرام کار می‌کند."
    return "todo", r.detail or "خوانندهٔ اینستاگرام نیاز به ورود و پراکسی دارد."


def _metis():
    try:
        from services.ai import status as ai_status

        snap = ai_status.snapshot()
    except Exception as exc:  # noqa: BLE001
        return "unknown", "وضعِ هوش مصنوعی خوانده نشد (%s)." % exc.__class__.__name__
    metis = (snap.get("providers") or {}).get("metis") if isinstance(snap.get("providers"), dict) else None
    text = json.dumps(snap, ensure_ascii=False)
    if metis and (metis.get("state") in ("ok", "healthy") or metis.get("ok") is True):
        return "ok", "متیس جواب می‌دهد."
    if "402" in text or "no_credit" in text or "اعتبار" in text:
        return "todo", "اعتبارِ متیس تمام شده (۴۰۲). تا شارژ نشود فقط هوشِ مصنوعیِ روی سرورِ پردازش کار می‌کند؛ درخواست‌های ساخت در صف می‌مانند و با برگشتنِ AI خودکار اجرا می‌شوند."
    return "unknown", "وضعِ متیس معلوم نیست؛ «تنظیماتِ هوش مصنوعی ⇒ آزمونِ اتصال» را بزنید."


def _c21st_key():
    try:
        from apps.projects.builder import c21st

        ks = c21st.key_status()
        n = len(c21st.load())
    except Exception as exc:  # noqa: BLE001
        return "unknown", "کاتالوگِ 21st.dev خوانده نشد (%s)." % exc.__class__.__name__
    if ks["has_key"]:
        return "ok", "کلید ثبت است؛ سهمِ امروز %d از %d. کاتالوگ %d قطعه دارد." % (ks["left_today"], ks["limit"], n)
    return "wait", "فهرستِ 21st.dev (%d قطعه) بی‌کلید کار می‌کند؛ برای گرفتنِ «کدِ» قطعه‌ها کلیدِ رایگانِ 21st.dev/mcp لازم است (۲ قطعه در روز)." % n


def _chagher_facts():
    return "wait", ("قیمتِ هر بسته و واحدش، آمارِ صفحهٔ اصلی (۹۸٪ رضایت، +۵۰۰ برنامه)، نامِ کاربریِ اینستاگرام (cheg_her یا Chagherg؟) و اسکرین‌شاتِ اپ را تأیید کنید؛ "
                    "تا آن موقع در هیچ پیش‌نویسی نمی‌آید.")


def _remotion():
    return "wait", ("«استودیوی موشن» با Remotion ساخته می‌شود؛ برای شرکت‌های بزرگ‌تر از سه نفر مجوزِ تجاریِ Remotion لازم است. اگر کسب‌وکارتان کوچک‌تر است یا مجوز دارید تیک بزنید.")


def definitions() -> list[dict]:
    """فهرستِ ثابتِ کارها؛ ``live`` تابعِ بررسیِ زنده (یا None)."""
    auto = _instai_auto()
    return [
        {"key": "node_on", "title": "روشن‌کردنِ سرورِ پردازش (کامپیوترِ گرافیکی)", "live": _live_node,
         "how": "کامپیوترِ گرافیکی را روشن کنید؛ برنامه خودش به‌روز و بالا می‌آید، نیازمندی‌ها نصب می‌شوند و آزمونِ خودکار اجرا می‌شود؛ کارهای منتظر خودشان اجرا می‌شوند."},
        {"key": "instai_fresh", "live": _instai,
         "title": ("InstAI: به‌روز و روشن‌شدنِ خودکار (فقط اگر آزمون خطا داد، یک بار ZIPِ تازه)" if auto else "InstAI: یک بار پوشه را با ZIPِ تازه عوض کنید"),
         "how": (("کارِ دستی لازم نیست: عاملِ سرورِ پردازش پوشهٔ InstAI را پیدا می‌کند، اگر قدیمی بود با به‌روزرسانِ خودِ InstAI از GitHub به‌روزش می‌کند و روشنش می‌کند. "
                  "فقط اگر این ردیف «خطا» نشان داد (مثلاً پوشه پیدا نشد): ") if auto else "") + _INSTAI_ZIP},
        {"key": "ig_login", "title": "اینستاگرام: ورود با حسابِ خودتان و پراکسیِ VPN در Abagram", "live": _abagram,
         "how": "«Open-Abagram.bat» را باز کنید، یک بار با حسابِ خودتان وارد شوید و در تنظیمات پراکسیِ VPN را بگذارید (خودِ برنامه این را برای شما نمی‌تواند)."},
        {"key": "metis_credit", "title": "اعتبارِ متیس (هوش مصنوعیِ ابری)", "live": _metis,
         "how": "حسابِ متیس را شارژ کنید؛ یا فقط با مدل‌های روی کارت کار کنید (درخواست‌های ساخت تا آن موقع در صف می‌مانند)."},
        {"key": "c21st_key", "decision": True, "title": "21st.dev: کلیدِ API برای گرفتنِ کدِ قطعه‌ها (اختیاری)", "live": _c21st_key,
         "how": "در سایت‌ساز ⇒ قطعه‌ها ⇒ «کاتالوگِ 21st.dev» ⇒ «کلیدِ API» کلیدِ رایگانِ 21st.dev/mcp را بچسبانید."},
        {"key": "chagher_facts", "decision": True, "title": "چغر: تأییدِ قیمت‌ها و ادعاها، نامِ کاربریِ اینستاگرام و اسکرین‌شات", "live": _chagher_facts,
         "how": "فهرستِ «نامعلوم و تأییدنشده» در docs/chagher/brand-facts-fa.md؛ هر چه تأیید کردید در «جذب مشتری ⇒ دانشِ محصول» (محصولِ چغر) وارد کنید."},
        {"key": "remotion_licence", "decision": True, "title": "Remotion: تأییدِ مجوز", "live": _remotion,
         "how": "از remotion.dev/license ببینید به کسب‌وکارِ شما مجوزِ رایگان می‌رسد یا تجاری لازم است."},
    ]


def build() -> dict:
    marks = _marks()
    rows = []
    for d in definitions():
        try:
            state, detail = d["live"]()
        except Exception as exc:  # noqa: BLE001
            logger.exception("owner step %s failed", d["key"])
            state, detail = "unknown", "بررسی نشد (%s)." % exc.__class__.__name__
        mark = marks.get(d["key"])
        if d.get("decision") and mark and state == "wait":
            state = "ok"                                   # تصمیم/تأییدِ مالک؛ داده‌ای نیست که زنده بسنجیم
        rows.append({"key": d["key"], "title": d["title"], "state": state, "detail": detail, "how": d["how"], "marked": bool(mark), "marked_at": (mark or {}).get("at", ""),
                     "markable": bool(d.get("decision"))})
    open_n = sum(1 for r in rows if r["state"] in ("todo", "wait"))
    return {"steps": rows, "open": open_n, "total": len(rows), "checked_at": timezone.now().isoformat(timespec="seconds")}
