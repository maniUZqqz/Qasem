"""Can the node read Instagram right now, and if not, what exactly should a person do. Pure reading of what the node reports
(`ComputeNode.capabilities["abagram"]`, written by processing/abagram_jobs.py) - this module never calls the node."""
from __future__ import annotations

import time

from django.utils import timezone

from apps.compute.models import ComputeNode

from .explain import fa

BLOCKING = {"no_node", "node_old"}          # nothing can even be queued
PROXY_EXAMPLE = "http://127.0.0.1:10809"


def _clock(epoch_s) -> str:
    try:
        t = time.localtime(float(epoch_s))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
    return fa("%02d:%02d" % (t.tm_hour, t.tm_min))


def instruction(problem: str, rep: dict | None, node_name: str = "") -> str:
    """The Persian text for one problem code. `rep` is the node's abagram report (may be empty)."""
    rep = rep or {}
    where = "«%s»" % node_name if node_name else "سرورِ پردازش"
    url = rep.get("url") or ""
    if problem == "no_node":
        return "هنوز هیچ سرورِ پردازشی ثبت نشده. روی کامپیوترِ گرافیکی START.bat را یک بار اجرا کنید (ابزارها ← سرورهای پردازش)."
    if problem == "node_old":
        return ("نسخهٔ نرم‌افزارِ %s آباگرام را ندارد. در «ابزارها ← سرورهای پردازش» دکمهٔ «به‌روزرسانی» را بزنید یا START.bat را دوباره اجرا کنید؛ "
                "خودش آباگرام را نصب می‌کند." % where)
    if problem == "node_offline":
        return "%s الان خاموش است. خواندن در صف می‌ماند و با روشن‌شدنِ آن خودکار انجام می‌شود." % where
    if problem == "installing":
        step = rep.get("step")
        return "آباگرام در حال نصبِ خودکار روی %s است (فقط بار اول؛ چند دقیقه)%s. کاری لازم نیست." % (where, "؛ مرحله: " + step if step else "")
    if problem == "install_error":
        return ("نصبِ خودکارِ آباگرام روی %s خطا داد: %s. خودش چند دقیقه بعد دوباره تلاش می‌کند؛ اگر تکرار شد «لاگ‌ها» در صفحهٔ سرور را ببینید."
                % (where, (rep.get("error") or "نامشخص")[:160]))
    if problem in ("service_down", "starting"):
        return "آباگرام روی %s الان روشن نیست؛ ناظرِ سرور خودکار دوباره روشنش می‌کند (حدود یک دقیقه)." % where
    if problem == "not_signed_in":
        return ("آباگرام روی %s آماده است ولی هنوز وارد اینستاگرام نشده. روی خودِ آن کامپیوتر فایلِ «Open-Abagram.bat» (کنار START.bat) را اجرا کنید؛ "
                "آباگرام در مرورگر باز می‌شود (نشانی: %s). در صفحهٔ «ورود» نامِ کاربری و رمزِ یک حسابِ اینستاگرام را بزنید و اگر اینستاگرام کد یا کپچا "
                "خواست، همان‌جا انجام دهید. اینستاگرام در ایران فیلتر است: VPN یا پراکسیِ خودتان را روشن کنید و در آباگرام ← تنظیمات ← پراکسی "
                "نشانیِ محلیِ آن را بگذارید (مثلاً %s برای v2rayN). تا این کار انجام نشود، ترندها با «واردکردنِ فایلِ آباگرام» هم کار می‌کنند."
                % (where, url or "http://127.0.0.1:<پورت>/", PROXY_EXAMPLE))
    if problem == "unreachable":
        return ("آباگرام روی %s وارد است ولی اینستاگرام را نمی‌بیند (فیلتر). VPN/پراکسی را روشن کنید و در آباگرام ← تنظیمات ← پراکسی نشانیِ محلیِ آن را "
                "بگذارید (مثلاً %s). ساعتی یک بار خودش دوباره امتحان می‌کند." % (where, PROXY_EXAMPLE))
    if problem == "cooldown":
        until = _clock(rep.get("cooldown_until"))
        return "اینستاگرام گفته چند دقیقه صبر کن؛ آباگرام تا %s هیچ درخواستی نمی‌فرستد. لازم نیست کاری کنید." % (until or "چند دقیقهٔ دیگر")
    return ""


def _row(node: ComputeNode) -> dict:
    caps = node.capabilities or {}
    rep = caps.get("abagram") if isinstance(caps.get("abagram"), dict) else None
    return {"id": node.pk, "name": node.name, "online": node.online, "last_seen": node.last_seen, "agent": caps.get("agent"),
            "capable": bool(caps.get("instagram")), "report": rep, "ready": bool(rep and rep.get("ready") and node.online)}


def node_status() -> dict:
    """{'ready', 'problem', 'message', 'node', 'nodes', 'can_queue', 'open_with'}."""
    nodes = [_row(n) for n in ComputeNode.objects.filter(enabled=True).order_by("name")]
    if not nodes:
        problem, best = "no_node", None
    else:
        capable = [r for r in nodes if r["capable"]]
        if not capable:
            problem, best = "node_old", nodes[0]
        else:
            ready = [r for r in capable if r["ready"]]
            online = [r for r in capable if r["online"]]
            best = (ready or online or capable)[0]
            if ready:
                problem = None
            elif not best["online"]:
                problem = "node_offline"
            else:
                problem = (best["report"] or {}).get("problem") or "service_down"
    rep = best["report"] if best else None
    msg = instruction(problem, rep, best["name"] if best else "") if problem else ""
    return {"ready": problem is None, "problem": problem, "message": msg, "node": best, "nodes": nodes,
            "can_queue": problem not in BLOCKING and problem in (None, "node_offline"), "open_with": "Open-Abagram.bat",
            "address": (rep or {}).get("url") or "", "checked_at": timezone.now()}
