# -*- coding: utf-8 -*-
"""درخواست‌های هوش مصنوعی که «در صف تا روشن شدنِ سرورِ پردازش» می‌مانند و خودشان اجرا می‌شوند (۱۴۰۵/۰۸/۲۸).

مسئله: ویژگی‌های تعاملی (پیش‌نویسِ شخصیت، ایده‌های برند، ایده‌ی تامنیل، «توصیف کن، بساز»، …) وقتی هر دو مسیرِ هوش مصنوعی جواب نمی‌دادند
(سرورِ پردازش خاموش + اعتبارِ متیس تمام) یا بی‌صدا به فرمول‌های آماده برمی‌گشتند یا خطا می‌دادند و درخواست گم می‌شد. کارهای Celeryِ کاربر از قبل
در صفِ ماندگار (`park.py`) می‌مانند؛ این ماژول همان رفتار را برای درخواست‌هایی می‌آورد که جوابشان همان لحظه به کاربر می‌رسد:

  * `defer(feature, store, params)` ⇒ یک «کارِ منتظر» (ComputeJob با kind=wait.node، همان‌که در «صفِ پردازش» دیده و لغو می‌شود) با شناسهٔ `uid`
    ساخته می‌شود؛ پاسخِ ویژگی همان پاسخِ فرمولیِ همیشگی است + `queued: {uid, message: «در صف تا روشن شدنِ سرورِ پردازش»}`؛
  * `wake()` (هر دقیقه از `park.wake_parked` ⇐ `tasks.maintenance`): اگر یکی از دو مسیر (گرهٔ روشن، یا متیسِ بی‌مدارِ باز) آماده است، یک درخواست را
    (هر بار یکی؛ گره یک کارت دارد) با `tasks.run_deferred` می‌فرستد؛
  * `run(uid)` همان تابعِ ویژگی را با هوش مصنوعیِ واقعی اجرا می‌کند؛ جواب = همان JSON که پاسخِ همزمان می‌داد ⇒ فایلِ `ai-deferred/<uid>.json`؛
    هنوز در دسترس نبود ⇒ درخواست در صف می‌ماند (تا ۷۲ ساعت)؛ خطای غیرِ AI ⇒ «ناموفق» با پیامِ فارسی؛
  * `status(uid)` را صفحه هر چند ثانیه می‌پرسد (`GET /api/v1/compute/deferred/<uid>/`) و جواب را جای پیش‌نویسِ فرمولی می‌گذارد.

هیچ مهاجرتی لازم نیست: ردیفِ صف همان ComputeJob است و نتیجه فایلِ JSON زیرِ NM_DATA_DIR/ai-deferred (۷ روز می‌ماند).
هر ویژگی فقط در `FEATURES` ثبت می‌شود (فهرستِ سفید: مسیرِ تابع از ورودیِ کاربر نمی‌آید).
"""
from __future__ import annotations

import contextvars
import importlib
import json
import logging
import os
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import services as SV
from .dbretry import call_with_retry
from .models import ComputeJob
from .park import PARK_KIND

logger = logging.getLogger(__name__)

QUEUED_TEXT = SV.NO_NODE_QUEUED_TEXT            # «در صف — منتظرِ روشن شدنِ سرورِ پردازش»
UI_TEXT = "در صف تا روشن شدنِ سرورِ پردازش"       # جملهٔ کوتاهِ دکمه/برچسب
MAX_AGE_S = 72 * 3600
RESULT_KEEP_S = 7 * 24 * 3600
STALE_RUN_S = 20 * 60                           # اجرایی که این‌قدر «در حال اجرا» مانده (کارگر مرده) دوباره بیدار می‌شود
MAX_PENDING = 100
WAKE_PER_MINUTE = 1

#: درون یک اجرای صف‌دار (کارگر Celery) مهلتِ انتظار برای نوبتِ گره بلندتر است (کاربری منتظرِ دکمه نیست)
_IN_RUN = contextvars.ContextVar("nm_deferred_run", default=False)


def in_deferred_run() -> bool:
    return bool(_IN_RUN.get())


class StillDown(Exception):
    """ویژگی در اجرای صف‌دار می‌گوید «هنوز هیچ مسیرِ هوش مصنوعی جواب نمی‌دهد» ⇒ درخواست در صف می‌ماند (is_outage ⇒ True)."""

    parkable = True


# ───────────────────────────── ویژگی‌ها (فهرستِ سفید)

def _used_ai_flag(result) -> bool:
    return bool(isinstance(result, dict) and (result.get("ai_used") is True or (result.get("ai") or {}).get("used") is True))


def _used_via(result) -> bool:
    return bool(isinstance(result, dict) and result.get("via") in ("ai", "mixed"))


def _used_source_ai(result) -> bool:
    return bool(isinstance(result, dict) and result.get("source") == "ai")


def _always(_result) -> bool:
    return True


#: کلید ⇒ {fn: "ماژول:تابع" (store, **params ⇒ JSON)، label: برای صف، used: نتیجه را «با هوش مصنوعی» حساب می‌کند؟}
FEATURES: dict[str, dict] = {
    "brandchar.persona": {"fn": "apps.brandchar.persona_ai:deferred_draft", "label": "پیش‌نویسِ شخصیتِ برند", "used": _used_ai_flag},
    "brandchar.concepts": {"fn": "apps.brandchar.concepts:deferred_generate", "label": "ایده‌های شخصیتِ برند", "used": _used_ai_flag},
    "ideabank.generate": {"fn": "apps.ideabank.generator:deferred_generate", "label": "ایده‌های بانکِ ایده", "used": _used_via},
    "thumbs.ideas": {"fn": "apps.thumbs.ideation:deferred_ideas", "label": "ایده‌های تامنیل", "used": _used_via},
    "motion.code": {"fn": "apps.motion.ai:deferred_code_from_idea", "label": "کدِ موشن از توصیف", "used": _always},
    "motion.script": {"fn": "apps.motion.ai:deferred_script_from_idea", "label": "پیش‌نویسِ ویدیوی موشن از توصیف", "used": _used_source_ai},
    "design.deck": {"fn": "apps.design_studio.deck_doc:deferred_deck", "label": "پیش‌نویسِ اسلایدهای طراحی", "used": _used_ai_flag},
    "shoot.plan": {"fn": "apps.shoot.services:deferred_analysis", "label": "برنامهٔ هوشمندِ فیلم‌برداریِ محصول", "used": _used_ai_flag},
    # سطحِ پلتفرم (بی‌فروشگاه): ترجمهٔ فارسیِ متن‌های قطعهٔ 21st در سایت‌ساز (فقط کارکنان)
    "c21.translate": {"fn": "apps.projects.c21_api:deferred_translate", "label": "ترجمهٔ فارسیِ متن‌های قطعهٔ 21st", "used": _used_ai_flag, "platform": True},
    # سطحِ پلتفرم (بی‌فروشگاه): نویسندهٔ پیامِ مشتری‌یاب/کمپین
    "growth.writer": {"fn": "apps.growth_engine.knowledge.services.writer:deferred_run", "label": "پیش‌نویسِ پیامِ مشتری‌یاب با هوش مصنوعی",
                      "used": lambda r: bool(isinstance(r, dict) and r.get("status") == "proposed"), "platform": True},
    # ── دورِ «E*» (۱۴۰۵/۰۸/۲۸، شب): نتیجه روی خودِ رکوردِ ویژگی ذخیره می‌شود؛ صفحه فقط نوارِ «در صف…» را نشان می‌دهد و پس از رسیدن دوباره می‌خواند.
    #     on_end(store, state=failed|cancelled|expired, message=…, **params): نشانهٔ «در صف» روی رکورد را پاک می‌کند اگر درخواست بی‌نتیجه تمام شد.
    "motion.style": {"fn": "apps.motion.custom_ai:deferred_describe", "label": "پیش‌نویسِ سبکِ سفارشیِ موشن از توصیف", "used": _used_source_ai},
    "motion.critique": {"fn": "apps.motion.critique:deferred_run", "label": "نقدِ تصویریِ طرحِ موشن", "used": _always, "on_end": "apps.motion.critique:on_deferred_end"},
    "trends.rank": {"fn": "apps.ai.trends:deferred_rank", "label": "رتبه‌بندیِ ترندها برای فروشگاه با هوش مصنوعی", "used": _always},
    "trends.ideas": {"fn": "apps.ai.trends:deferred_suggest", "label": "ایده‌های محتوا از ترندها", "used": _always},
    "igtrends.brief": {"fn": "apps.igtrends.ideas:deferred_make_idea", "label": "ایدهٔ محتوا از ترندِ اینستاگرام", "used": _always},
    "competitor.confirm": {"fn": "apps.ai.competitor_research:deferred_confirm", "label": "تأییدِ همانندیِ محصولاتِ رقیب با هوش مصنوعی", "used": _always},
    # سطحِ پلتفرم: اپِ موبایل فروشگاهِ تماس را از تنظیماتِ دستگاه برمی‌دارد (notes.resolve_store)
    "mobile.call": {"fn": "apps.mobile.tasks:deferred_process_call", "label": "تبدیل به متن و یادداشتِ تماسِ موبایل", "used": _always, "platform": True,
                    "on_end": "apps.mobile.tasks:on_deferred_end"},
    "shoot.vision": {"fn": "apps.shoot.services:deferred_vision", "label": "بررسیِ «محصول پیداست؟» با هوش مصنوعیِ بینایی", "used": _always,
                     "on_end": "apps.shoot.services:on_vision_end"},
}


def _resolve(path: str):
    mod, _, name = path.partition(":")
    return getattr(importlib.import_module(mod), name)


# ───────────────────────────── فایلِ نتیجه

def _dir() -> Path:
    p = Path(settings.NM_DATA_DIR) / "ai-deferred"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file(uid) -> Path:
    uid = str(uid)
    if not uid.replace("-", "").isalnum():
        raise ValueError("bad uid")
    return _dir() / ("%s.json" % uid)


def _write(uid, doc: dict) -> None:
    p = _file(uid)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)


def _read(uid) -> dict | None:
    try:
        return json.loads(_file(uid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ───────────────────────────── مسیرِ هوش مصنوعی: الان می‌شود امتحان کرد؟

def is_outage(exc) -> bool:
    """خطای مسیریاب «با صبر درست می‌شود» (گره خاموش/شلوغ، متیسِ بی‌اعتبار، مهلت، قطعِ اتصال)؟ کلیدِ نادرست و «مدل نصب نیست» نه.
    زنجیرهٔ علت را هم می‌خواند: ویژگی‌ها خطا را در AIUnavailable ِ خودشان می‌پیچند (`raise AIUnavailable(...) from exc`)."""
    seen: set = set()
    e = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        flag = getattr(e, "parkable", None)
        if flag is True:
            return True
        if flag is False:
            return False                       # ویژگی صریح گفته «با صبر درست نمی‌شود» (کلیدِ نادرست، مدلِ نصب‌نشده، ورودیِ بد)
        failures = getattr(e, "failures", None)
        if isinstance(failures, dict) and failures:
            # AllProvidersFailed: هر مسیر دلیلِ خودش را دارد؛ اگر دست‌کم یکی «با صبر درست می‌شود» (گره خاموش/شلوغ، اعتبار، مهلت …) صف می‌شود،
            # اگر هیچ‌کدام (کلیدِ نادرست + مدلِ نصب‌نشده) باید تنظیم شود و صف فقط وعدهٔ دروغ است
            try:
                from apps.ai_engine.parking import PARK_KINDS

                kinds = {getattr(f, "kind", "") for f in failures.values() if f is not None}
                return bool(kinds & set(PARK_KINDS))
            except Exception:  # noqa: BLE001
                pass
        try:
            from apps.ai_engine import parking

            un = parking.unavailable_from(e)
            if un is not None and un.parkable:
                return True
        except Exception:  # noqa: BLE001
            pass
        e = e.__cause__ or e.__context__
    return False


def ai_ready() -> tuple[bool, str]:
    """(آیا الان ارزش دارد اجرا کنیم، چرا). اول گرهٔ روشن (لوکال)، بعد متیسِ تنظیم‌شده که مدارش باز نیست."""
    if SV.online_nodes("ollama"):
        return True, "local"
    try:
        from services.ai import priority

        if priority.metis_configured() and priority.open_failure(priority.METIS) is None:
            return True, "metis"
    except Exception:  # noqa: BLE001
        pass
    return False, ""


def _worth_queueing() -> bool:
    """کسی هست که روزی جواب بدهد؟ (گرهٔ ثبت‌شده با Ollama، یا متیسِ تنظیم‌شده) — وگرنه صف فقط وعدهٔ دروغ است."""
    if SV.known_nodes("ollama"):
        return True
    try:
        from services.ai import priority

        return bool(priority.metis_configured())
    except Exception:  # noqa: BLE001
        return False


# ───────────────────────────── صف

def _key(feature, store_id, params) -> str:
    import hashlib

    raw = json.dumps([feature, store_id, params], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def pending_rows():
    return [ph for ph in ComputeJob.objects.filter(kind=PARK_KIND, state=ComputeJob.State.QUEUED) if (ph.payload or {}).get("deferred")]


def pending_count() -> int:
    return len(pending_rows())


def recent_done_count(hours: int = 48) -> int:
    since = time.time() - hours * 3600
    n = 0
    try:
        for p in _dir().glob("*.json"):
            if p.stat().st_mtime >= since:
                d = _read(p.stem) or {}
                if d.get("state") == "done":
                    n += 1
    except OSError:
        pass
    return n


def defer(feature: str, store, params: dict, *, user=None, reason: str = "") -> dict | None:
    """درخواست را در صفِ ماندگار می‌گذارد. ⇒ {"uid","feature","label","state":"queued","message"} یا None (در صف نمی‌ماند؛ فراخوان همان پیامِ همیشگی را نشان بدهد).

    None: زیرِ آزمون، ویژگیِ ناشناخته، هیچ سرورِ پردازشِ ثبت‌شده و متیسی نیست، یا صف پر است. درخواستِ همانندِ هنوز در صف دوباره ساخته نمی‌شود."""
    if getattr(settings, "IS_TEST", False) and not getattr(settings, "AI_DEFER_FORCE", False):
        return None
    spec = FEATURES.get(feature)
    if spec is None or (store is None and not spec.get("platform")):
        return None
    try:
        json.dumps(params, default=str)
    except (TypeError, ValueError):
        return None
    if not _worth_queueing():
        return None
    key = _key(feature, getattr(store, "pk", 0), params)
    now = timezone.now()
    try:
        for ph in pending_rows():
            d = (ph.payload or {}).get("deferred") or {}
            if d.get("key") == key:
                return _public(ph)
        if pending_count() >= MAX_PENDING:
            return None
        payload = {"capability": "ollama", "title": spec["label"], "message": (reason or QUEUED_TEXT)[:300],
                   "ref": {"model": "deferred", "id": key},
                   "deferred": {"feature": feature, "key": key, "params": params, "user_id": getattr(user, "pk", None), "attempts": 0,
                                "started_at": None, "created": now.isoformat(), "reason": (reason or "")[:300]}}
        ph = call_with_retry(lambda: ComputeJob.objects.create(
            kind=PARK_KIND, payload=payload, origin="deferred", store=store if store is not None and getattr(store, "pk", None) else None, priority=100,
            state=ComputeJob.State.QUEUED, queued_at=now,
            message=QUEUED_TEXT, request_hash="", timeout_s=0), _what="deferred")
    except Exception as exc:  # noqa: BLE001 — صف نباید خودِ درخواست را بخواباند
        logger.warning("deferred: could not queue %s: %s", feature, exc)
        return None
    logger.info("deferred: %s queued for store %s as %s", feature, getattr(store, "pk", None), ph.uid)
    return _public(ph)


def _public(ph) -> dict:
    d = (ph.payload or {}).get("deferred") or {}
    spec = FEATURES.get(d.get("feature")) or {}
    return {"uid": str(ph.uid), "feature": d.get("feature"), "label": spec.get("label") or (ph.payload or {}).get("title") or "", "state": "queued",
            "message": UI_TEXT, "detail": ph.message or QUEUED_TEXT, "store_id": ph.store_id, "attempts": int(d.get("attempts") or 0),
            "queued_at": (ph.queued_at or ph.created_at).isoformat() if (ph.queued_at or ph.created_at) else ""}


def _row(uid):
    return ComputeJob.objects.filter(uid=uid, kind=PARK_KIND).first()


def _recent(d: dict, now=None) -> bool:
    """به کارگر سپرده شده یا همین الان در حالِ اجراست (کمتر از STALE_RUN_S پیش)."""
    from django.utils.dateparse import parse_datetime

    now = now or timezone.now()
    for key in ("dispatched_at", "started_at"):
        raw = (d or {}).get(key)
        if not raw:
            continue
        try:
            t = parse_datetime(raw)
        except (TypeError, ValueError):
            t = None
        if t is not None and (now - t).total_seconds() < STALE_RUN_S:
            return True
    return False


def status(uid) -> dict | None:
    """⇒ {"state": queued|running|done|failed|cancelled, "message", "result"?, "error"?, …}؛ None = ناشناخته."""
    try:
        done = _read(uid)
    except ValueError:
        return None
    if done:
        return done
    ph = _row(uid)
    if ph is None or not (ph.payload or {}).get("deferred"):
        return None
    base = _public(ph)
    if ph.state == ComputeJob.State.CANCELLED:
        return {**base, "state": "cancelled", "message": "لغو شد."}
    if _recent(ph.payload["deferred"] or {}):
        base.update(state="running", message="در حالِ اجرا روی سرورِ پردازش…")
    return base


def owner_of(uid) -> tuple[bool, int | None]:
    """(درخواست هست؟، شناسهٔ فروشگاهش). فروشگاه None = درخواستِ سطحِ پلتفرم (فقط کارکنان می‌بینند)."""
    d = _read(uid)
    if d:
        return True, d.get("store_id")
    ph = _row(uid)
    if ph is None or not (ph.payload or {}).get("deferred"):
        return False, None
    return True, ph.store_id


def _on_end(ph, state: str, message: str = "") -> None:
    """ویژگی‌ای که نشانهٔ «در صف…» را روی رکوردِ خودش گذاشته (نقدِ موشن، تماسِ موبایل، برداشتِ فیلم‌برداری) وقتی درخواست بی‌نتیجه تمام شد
    (لغو / منقضی / ناموفق) آن را پاک می‌کند. خطای این قلاب هیچ‌وقت صف را نمی‌اندازد."""
    d = (ph.payload or {}).get("deferred") or {}
    spec = FEATURES.get(d.get("feature")) or {}
    path = spec.get("on_end")
    if not path:
        return
    try:
        from apps.stores.models import Store

        store = Store.objects.filter(pk=ph.store_id).first() if ph.store_id else None
        _resolve(path)(store, state=state, message=message, **(d.get("params") or {}))
    except Exception as exc:  # noqa: BLE001
        logger.warning("deferred: on_end of %s failed: %s", d.get("feature"), exc)


def cancel(uid) -> bool:
    ph = _row(uid)
    if ph is None or ph.state != ComputeJob.State.QUEUED or not (ph.payload or {}).get("deferred"):
        return False
    ph.state = ComputeJob.State.CANCELLED
    ph.finished_at = timezone.now()
    ph.message = "لغو شد"
    ph.save(update_fields=["state", "finished_at", "message", "updated_at"])
    on_cancelled(ph)
    return True


def on_cancelled(ph) -> None:
    """از park.on_cancelled: کارِ منتظر در «صفِ پردازش» لغو شد ⇒ فایلِ نتیجه «لغو شد» می‌شود."""
    d = (ph.payload or {}).get("deferred")
    if not d:
        return
    _write(ph.uid, {"uid": str(ph.uid), "feature": d.get("feature"), "state": "cancelled", "message": "لغو شد.", "store_id": ph.store_id,
                    "finished_at": timezone.now().isoformat()})
    _on_end(ph, "cancelled", "لغو شد.")


# ───────────────────────────── اجرا

def _finish(ph, feature, state, **extra) -> None:
    d = (ph.payload or {}).get("deferred") or {}
    doc = {"uid": str(ph.uid), "feature": feature, "state": state, "store_id": ph.store_id, "attempts": int(d.get("attempts") or 0),
           "created": d.get("created"), "finished_at": timezone.now().isoformat(), **extra}
    _write(ph.uid, doc)
    if state == "failed":
        _on_end(ph, "failed", str(extra.get("error") or extra.get("message") or ""))
    call_with_retry(ph.delete)


def _requeue(ph, why: str) -> None:
    payload = dict(ph.payload or {})
    d = dict(payload.get("deferred") or {})
    d["attempts"] = int(d.get("attempts") or 0) + 1
    d["started_at"] = None
    d["dispatched_at"] = None
    d["reason"] = why[:300]
    payload["deferred"] = d
    ph.payload = payload
    ph.message = QUEUED_TEXT
    call_with_retry(ph.save, update_fields=["payload", "message", "updated_at"])


def run(uid) -> str:
    """یک درخواستِ صف‌دار را با هوش مصنوعیِ واقعی اجرا می‌کند. ⇒ done | failed | requeued | skipped."""
    ph = _row(uid)
    if ph is None or ph.state != ComputeJob.State.QUEUED:
        return "skipped"
    payload = dict(ph.payload or {})
    d = dict(payload.get("deferred") or {})
    feature = d.get("feature")
    spec = FEATURES.get(feature)
    if spec is None:
        _finish(ph, feature, "failed", error="این نوعِ درخواست دیگر پشتیبانی نمی‌شود.", message="ناموفق")
        return "failed"
    created = None
    try:
        from django.utils.dateparse import parse_datetime

        created = parse_datetime(d.get("created") or "")
    except Exception:  # noqa: BLE001
        pass
    if created is not None and (timezone.now() - created).total_seconds() > MAX_AGE_S:
        _finish(ph, feature, "failed", error="هوش مصنوعی تا ۷۲ ساعت برنگشت و درخواست رها شد؛ هر وقت برگشت دوباره بفرستید.", message="منقضی شد")
        return "failed"
    d["started_at"] = timezone.now().isoformat()
    payload["deferred"] = d
    ph.payload = payload
    ph.message = "در حالِ اجرا روی سرورِ پردازش…"
    call_with_retry(ph.save, update_fields=["payload", "message", "updated_at"])
    from apps.stores.models import Store

    store = Store.objects.filter(pk=ph.store_id).first() if ph.store_id else None
    if store is None and not spec.get("platform"):
        _finish(ph, feature, "failed", error="فروشگاهِ این درخواست دیگر نیست.", message="ناموفق")
        return "failed"
    token = _IN_RUN.set(True)
    try:
        result = _resolve(spec["fn"])(store, **(d.get("params") or {}), _user_id=d.get("user_id"))
    except Exception as exc:  # noqa: BLE001
        if is_outage(exc) or (exc.__class__.__name__ in ("AIUnavailable", "AllProvidersFailed", "NodeFailed") and getattr(exc, "parkable", True)):
            _requeue(ph, str(exc))
            return "requeued"
        logger.exception("deferred: %s failed for store %s", feature, ph.store_id)
        _finish(ph, feature, "failed", error=str(exc)[:400] or exc.__class__.__name__, message="ناموفق")
        return "failed"
    finally:
        _IN_RUN.reset(token)
    if not spec["used"](result):
        _requeue(ph, ((result or {}).get("ai") or {}).get("reason") or "هوش مصنوعی هنوز در دسترس نیست.")
        return "requeued"
    _finish(ph, feature, "done", result=result, message="آماده شد")
    return "done"


def wake(now=None, limit: int = WAKE_PER_MINUTE) -> int:
    """هر دقیقه: اگر مسیری آماده است و درخواستی در جریان نیست، به‌اندازهٔ `limit` درخواستِ صف را به کارگر می‌سپارد؛ فایل‌های کهنه را هم پاک می‌کند."""
    now = now or timezone.now()
    _sweep_files()
    rows = sorted(pending_rows(), key=lambda p: p.created_at)
    if not rows:
        return 0
    if any(_recent((ph.payload or {}).get("deferred") or {}, now) for ph in rows):
        return 0                          # یکی همین الان اجرا می‌شود؛ گره یک کارت دارد، نوبتِ بعدی دقیقهٔ بعد
    ready, _how = ai_ready()
    if not ready:
        return 0
    n = 0
    for ph in rows[:max(1, int(limit))]:
        payload = dict(ph.payload or {})
        d = dict(payload.get("deferred") or {})
        d["dispatched_at"] = now.isoformat()
        payload["deferred"] = d
        ph.payload = payload
        try:
            call_with_retry(ph.save, update_fields=["payload", "updated_at"])
            from .tasks import run_deferred

            run_deferred.delay(str(ph.uid))
            n += 1
        except Exception as exc:  # noqa: BLE001 — دقیقهٔ بعد دوباره
            logger.warning("deferred: could not dispatch %s: %s", d.get("feature"), exc)
    return n


def _sweep_files() -> None:
    cutoff = time.time() - RESULT_KEEP_S
    try:
        for p in _dir().glob("*.json"):
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
    except OSError:
        pass


def on_expired(ph) -> None:
    """از park.on_expired: سقفِ انتظار تمام شد ⇒ «ناموفق» با پیامِ روشن."""
    d = (ph.payload or {}).get("deferred")
    if not d:
        return
    _write(ph.uid, {"uid": str(ph.uid), "feature": d.get("feature"), "state": "failed", "store_id": ph.store_id, "message": "منقضی شد",
                    "error": "مهلتِ انتظار برای هوش مصنوعی تمام شد؛ هر وقت برگشت دوباره بفرستید.", "finished_at": timezone.now().isoformat()})
    _on_end(ph, "expired", "مهلتِ انتظار برای هوش مصنوعی تمام شد.")
