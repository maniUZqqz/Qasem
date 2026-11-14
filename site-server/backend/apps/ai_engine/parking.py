# -*- coding: utf-8 -*-
"""«هوش مصنوعی در دسترس نبود» در سایت‌ساز: درخواست گم نمی‌شود، با پیامِ روشنِ فارسی می‌ماند و وقتی AI برگردد خودکار اجرا می‌شود.

پیش از این، هر شکستِ مسیریاب (متیس بی‌اعتبار ۴۰۲، سرورِ پردازش خاموش، …) یک پیشنهادِ «ناموفق» با پیامِ خامِ ``خطای داخلی: AllProvidersFailed(...)`` می‌ساخت و کاربر
باید از نو می‌نوشت. حالا:

* ``_call`` شکستِ «در دسترس نبودنِ AI» را به ``AiUnavailable`` با دلیلِ فارسی تبدیل می‌کند (اعتبار، سهمیه، سرور، مهلت، اتصال، خاموشیِ گره)؛
  کلیدِ نادرست و «مدل نصب نیست» پارک نمی‌شوند (باید تنظیم شوند) ولی پیامشان فارسی و روشن است؛
* ``_launch`` درخواست را با همهٔ آرگومان‌هایش در یک «برگهٔ پارک» (فایلِ JSON زیرِ ``NM_DATA_DIR/ai-parked``) نگه می‌دارد و پیشنهاد را ناموفق با همان پیام می‌گذارد؛
* ``resume_due`` (هر ۵ دقیقه، Celery beat) اگر دست‌کم یکی از دو مسیرِ AI «بازِ بسته» نباشد دوباره اجرایش می‌کند؛ تا ۲۴ ساعت و ۲۴ بار؛
* ``resume_now`` همان کار را به‌درخواستِ کاربر انجام می‌دهد (دکمهٔ «اجرای دوباره»).
هیچ مهاجرتی لازم نیست.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from django.conf import settings

from .providers import AiError

logger = logging.getLogger(__name__)

RETRY_EVERY = 300          # ثانیه
MAX_AGE = 24 * 3600
MAX_TRIES = 24
#: شکست‌هایی که با گذشتِ زمان یا شارژ/روشن‌شدنِ گره درست می‌شوند (کلیدِ نادرست و مدلِ نصب‌نشده را کاربر باید درست کند)
PARK_KINDS = {"no_credit", "rate_limit", "server", "timeout", "connection", "offline", "busy"}
FRIENDLY_KINDS = PARK_KINDS | {"bad_key", "no_model"}


class AiUnavailable(AiError):
    """هوش مصنوعی الان جواب نمی‌دهد؛ ``parkable`` یعنی با صبر درست می‌شود."""

    def __init__(self, message: str, kind: str = "", parkable: bool = True):
        super().__init__(message)
        self.kind, self.parkable = kind, parkable


def unavailable_from(exc: Exception) -> AiUnavailable | None:
    """خطای مسیریاب/ارائه‌دهنده ⇒ AiUnavailable با دلیلِ فارسی؛ هر خطای دیگر (JSON خراب، منطقِ برنامه) ⇒ None."""
    try:
        from services.ai import priority
        from services.ai.ollama import OllamaUnavailable
    except Exception:  # noqa: BLE001
        return None
    if isinstance(exc, AiUnavailable):
        return exc
    f = priority.classify(exc)
    is_outage = isinstance(exc, OllamaUnavailable) or exc.__class__.__name__ in ("AllProvidersFailed", "NodeFailed")
    if f.kind not in FRIENDLY_KINDS and not is_outage:
        return None
    raw = str(exc) if exc.__class__.__name__ == "AllProvidersFailed" and str(exc).strip() else f.sentence()
    reason = " ".join(raw.split())[:300]
    parkable = f.kind in PARK_KINDS or (is_outage and f.kind not in ("bad_key", "no_model"))
    if parkable:
        msg = (f"هوش مصنوعی در دسترس نیست: {reason}. درخواستِ شما در صف ماند و وقتی هوش مصنوعی برگردد خودکار اجرا می‌شود "
               f"(تا ۲۴ ساعت)؛ لازم نیست دوباره بنویسید.")
    else:
        msg = f"هوش مصنوعی کار نکرد: {reason}. تنظیمات را درست کنید («تنظیماتِ هوشِ مصنوعی» ⇒ «آزمونِ اتصال») و دوباره بفرستید."
    return AiUnavailable(msg, f.kind, parkable)


# ───────────────────────────── برگهٔ پارک (فایل)

def _dir() -> Path:
    p = Path(settings.NM_DATA_DIR) / "ai-parked"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(pk) -> Path:
    return _dir() / f"{int(pk)}.json"


def _ser(value):
    if hasattr(value, "_meta") and hasattr(value, "pk"):
        return {"__model__": value._meta.label_lower, "pk": value.pk}
    if isinstance(value, (list, tuple)):
        return [_ser(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _ser(v) for k, v in value.items()}
    return value


def _de(value):
    from django.apps import apps

    if isinstance(value, dict) and "__model__" in value:
        return apps.get_model(value["__model__"]).objects.get(pk=value["pk"])
    if isinstance(value, list):
        return [_de(v) for v in value]
    if isinstance(value, dict):
        return {k: _de(v) for k, v in value.items()}
    return value


def clear(pk) -> None:
    """درخواست کارش را تمام کرد (موفق یا با خطای غیرِ AI) ⇒ برگهٔ پارک پاک می‌شود."""
    try:
        _path(pk).unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        pass


def is_parked(pk) -> bool:
    try:
        return _path(pk).is_file()
    except (OSError, ValueError, TypeError):
        return False


def park(proposal, fn, args, exc: AiUnavailable) -> None:
    """پیشنهاد ⇒ ناموفق با پیامِ فارسی؛ اگر با صبر درست می‌شود برگهٔ پارک هم نوشته می‌شود."""
    proposal.status = "failed"
    proposal.error = str(exc)[:4000]
    proposal.save()
    if not exc.parkable:
        _path(proposal.pk).unlink(missing_ok=True)
        return
    old = {}
    try:
        old = json.loads(_path(proposal.pk).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    ticket = {"fn": fn.__name__, "args": _ser(list(args)), "created": old.get("created") or time.time(), "last_try": time.time(),
              "tries": int(old.get("tries", 0)) + 1, "kind": exc.kind}
    tmp = _path(proposal.pk).with_suffix(".tmp")
    tmp.write_text(json.dumps(ticket, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _path(proposal.pk))


def _circuits_open() -> bool:
    """هر دو مسیرِ AI «کلیدِ مدارشان باز» است (تازه شکست خورده‌اند) ⇒ الان امتحان نکن."""
    try:
        from services.ai import priority

        return priority.open_failure(priority.LOCAL) is not None and priority.open_failure(priority.METIS) is not None
    except Exception:  # noqa: BLE001
        return False


def _resume(pk, ticket) -> bool:
    from . import services
    from .models import AiProposal

    prop = AiProposal.objects.filter(pk=pk).first()
    fn = getattr(services, ticket.get("fn", ""), None)
    if prop is None or fn is None or prop.status != "failed":
        _path(pk).unlink(missing_ok=True)
        return False
    try:
        args = _de(ticket.get("args") or [])
    except Exception:  # noqa: BLE001 — صفحه/ویو در این فاصله پاک شده
        _path(pk).unlink(missing_ok=True)
        prop.error = "درخواستِ پارک‌شده اجرا نشد: صفحه یا قالبِ مربوط دیگر نیست."
        prop.save(update_fields=["error"])
        return False
    ticket["last_try"] = time.time()
    _path(pk).write_text(json.dumps(ticket, ensure_ascii=False), encoding="utf-8")
    prop.status, prop.error = "running", ""
    prop.save(update_fields=["status", "error"])
    services._launch(prop, fn, *args)
    return True


def resume_now(pk) -> bool:
    try:
        ticket = json.loads(_path(pk).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return _resume(pk, ticket)


def resume_due(now: float | None = None, limit: int = 1) -> list[int]:
    """نوبتِ Celery: برگه‌های سررسیدشده را (حداکثر ``limit``) دوباره اجرا می‌کند. ⇒ شناسهٔ پیشنهادهای اجراشده."""
    now = now or time.time()
    done: list[int] = []
    for p in sorted(_dir().glob("*.json")):
        try:
            pk = int(p.stem)
            ticket = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            p.unlink(missing_ok=True)
            continue
        if now - float(ticket.get("created", now)) > MAX_AGE or int(ticket.get("tries", 0)) >= MAX_TRIES:
            p.unlink(missing_ok=True)
            try:
                from .models import AiProposal

                AiProposal.objects.filter(pk=pk, status="failed").update(error="هوش مصنوعی تا ۲۴ ساعت برنگشت و درخواست رها شد؛ هر وقت برگشت دوباره بفرستید.")
            except Exception:  # noqa: BLE001
                pass
            continue
        if now - float(ticket.get("last_try", 0)) < RETRY_EVERY or len(done) >= limit or _circuits_open():
            continue
        if _resume(pk, ticket):
            done.append(pk)
    return done
