"""خودکارها (۱۴۰۵/۰۸/۲۱): شب می‌روم خانه و سرورِ پردازش را روشن می‌کنم؛ همه‌چیز خودش انجام شود.

  * به‌روزرسانیِ خودکار — بستهٔ کدِ سایت از عاملِ گره تازه‌تر است و گره بی‌کار است ⇒ سایت خودش دستورِ «update» را می‌فرستد
    (تنظیم: ComputeSettings.auto_update، پیش‌فرض روشن). تا انجامِ به‌روزرسانی کارِ تازه‌ای به گره داده نمی‌شود
    (`should_withhold`)، وگرنه صفِ پر هیچ‌وقت گره را بی‌کار نمی‌گذاشت. حداکثر ۳ تلاش برای هر بسته؛ بعد از آن گره دوباره کار می‌گیرد.
  * آزمونِ خودکار — پس از هر نسخهٔ تازهٔ عامل (همین جا در heartbeat)، هر شب (ساعتِ تنظیم‌شده، وقتِ تهران) و با دکمه.
  * `tick()` هر دقیقه از `tasks.maintenance` صدا زده می‌شود.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from . import commands as C
from . import services as SV
from . import updates as U
from .models import ComputeJob, ComputeNode, ComputeSettings, NodeAuto

logger = logging.getLogger(__name__)

MAX_AUTO_TRIES = 3
RETRY_AFTER = timedelta(minutes=20)       # دستور رفته ولی گره هنوز قدیمی است ⇒ بعد از این‌قدر یک تلاشِ تازه
BACKGROUND_KINDS = ("ollama.pull", "node.models")


def code_key(caps: dict) -> str:
    code = caps.get("code") if isinstance(caps.get("code"), dict) else {}
    return "%s|%s" % (caps.get("agent") or "", str(code.get("id") or "")[:16])


def node_idle(node) -> bool:
    """کاری که گره را مشغول نگه می‌دارد نیست (دانلودِ پس‌زمینه، که بعد از ری‌استارت ادامه پیدا می‌کند، حساب نمی‌شود)."""
    return not ComputeJob.objects.filter(node=node, state__in=[ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING]).exclude(
        kind__in=BACKGROUND_KINDS).exists()


def update_wanted(node, cfg=None) -> tuple[bool, str]:
    """سایت باید برای این گره «به‌روزرسانیِ خودکار» بفرستد (یا تا آن موقع کار ندهد)؟ (بله/خیر، علت)"""
    cfg = cfg or ComputeSettings.get()
    if not cfg.auto_update:
        return False, "به‌روزرسانیِ خودکار خاموش است"
    caps = node.capabilities or {}
    if not caps.get("agent"):
        return False, "عاملِ گره هنوز نسخه‌اش را نگفته است"
    latest = U.latest()
    if not latest.get("id") or not U.update_state(caps, latest).get("update_waiting"):
        return False, "گره با بستهٔ سایت یکی است"
    if not C.supported(node) or "update" not in (caps.get("commands") or []):
        return False, "عاملِ گره دستورِ به‌روزرسانی را نمی‌شناسد (با START.bat خودش به‌روز می‌شود)"
    auto = NodeAuto.of(node)
    tries = auto.update_tries if auto.update_pkg == latest["id"] else 0
    if tries >= MAX_AUTO_TRIES:
        return False, "سه تلاشِ خودکار برای این بسته انجام شد و گره هنوز قدیمی است؛ دستی بررسی کنید"
    return True, ""


def send_update(node, force: bool = False) -> dict | None:
    """اگر لازم و ممکن است دستورِ update را می‌فرستد؛ برمی‌گرداند آخرین دستور یا None."""
    cfg = ComputeSettings.get()
    wanted, why = update_wanted(node, cfg)
    if not wanted or not node.online or not node_idle(node):
        return None
    latest = U.latest()
    auto = NodeAuto.of(node)
    now = timezone.now()
    if auto.update_pkg == latest["id"] and auto.update_last_at and now - auto.update_last_at < RETRY_AFTER and not force:
        return None                                      # دستورِ قبلی هنوز در جریان است یا تازه رفته
    try:
        last = C.request(node, "update", "به‌روزرسانیِ خودکار")
    except C.CommandError as exc:
        logger.info("autopilot: update of %s not sent: %s", node.name, exc)
        return None
    caps = node.capabilities or {}
    if auto.update_pkg != latest["id"]:
        auto.update_pkg, auto.update_tries = latest["id"], 0
    auto.update_tries += 1
    auto.update_last_at = now
    auto.update_note = ("v%s ⇒ v%s (تلاش %d)" % (caps.get("agent") or "?", latest.get("version") or "?", auto.update_tries))[:300]
    auto.save()
    logger.info("autopilot: update command sent to %s (%s)", node.name, auto.update_note)
    return last


def should_withhold(node) -> bool:
    """از `services.claim`: بستهٔ تازه‌تر هست و به‌روزرسانیِ خودکار روشن است ⇒ به این گره کارِ تازه نمی‌دهیم تا خودش را به‌روز کند.
    (گره‌ای که کارِ در حال اجرا دارد همین‌طور تا پایانِ کار منتظر می‌ماند؛ همان لحظه که بی‌کار شد دستور می‌رود.)"""
    wanted, _why = update_wanted(node)
    if not wanted:
        return False
    if node_idle(node):
        send_update(node)
    return True


# ───────────────────────────── آزمونِ خودکار

def on_heartbeat(node) -> None:
    """نسخهٔ تازهٔ عامل (یا کد) دیده شد ⇒ آزمونِ کامل. ارزان: فقط وقتی کلید عوض شده کاری می‌کند."""
    caps = node.capabilities or {}
    key = code_key(caps)
    if not caps.get("agent"):
        return
    auto = NodeAuto.of(node)
    if auto.last_selftest_key == key:
        return
    auto.last_selftest_key = key
    auto.save(update_fields=["last_selftest_key", "updated_at"])
    if ComputeSettings.get().auto_selftest:
        from .selftests import runner

        runner.start_run(node, "version")


def nightly_due(node, cfg, now=None) -> str:
    """تاریخِ امروزِ تهران اگر آزمونِ شبانه باید الان بسته شود، وگرنه ''."""
    if not cfg.nightly_selftest:
        return ""
    t = SV.tehran_now(now)
    today = t.strftime("%Y-%m-%d")
    try:
        hh, mm = cfg.nightly_time.split(":")
        due = t.hour * 60 + t.minute >= int(hh) * 60 + int(mm)
    except ValueError:
        due = False
    return today if due and NodeAuto.of(node).last_nightly != today else ""


def tick(now=None) -> dict:
    """هر دقیقه: به‌روزرسانیِ گره‌های بی‌کار، آزمونِ شبانه، و جلو بردنِ آزمون‌های در جریان."""
    from .selftests import runner

    cfg = ComputeSettings.get()
    out = {"updates": 0, "nightly": 0}
    for node in ComputeNode.objects.filter(enabled=True):
        if not node.online:
            continue
        try:
            if send_update(node):
                out["updates"] += 1
            today = nightly_due(node, cfg, now)
            if today:
                auto = NodeAuto.of(node)
                auto.last_nightly = today
                auto.save(update_fields=["last_nightly", "updated_at"])
                runner.start_run(node, "nightly")
                out["nightly"] += 1
        except Exception:  # noqa: BLE001 — خطای یک گره بقیه را نمی‌خواباند
            logger.exception("autopilot: node %s failed", node.name)
    out.update(runner.advance_all())
    return out


def status_of(node) -> dict:
    """برای پنل: وضعیتِ خودکارهای یک گره."""
    cfg = ComputeSettings.get()
    wanted, why = update_wanted(node, cfg)
    auto = NodeAuto.of(node)
    latest = U.latest()
    return {"auto_update": cfg.auto_update, "update_wanted": wanted, "update_note": why or auto.update_note,
            "update_tries": auto.update_tries if auto.update_pkg == latest.get("id") else 0, "update_last_at": auto.update_last_at,
            "latest_version": latest.get("version"), "node_version": (node.capabilities or {}).get("agent"),
            "withholding": bool(wanted and node.online)}
