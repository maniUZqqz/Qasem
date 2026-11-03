# -*- coding: utf-8 -*-
"""وضعِ زندهٔ دو مسیرِ هوش مصنوعی (لوکال / متیس) برای پنل و جنگو ادمین، و دکمه‌های «آزمون».

· `snapshot()`   — تنظیم + وضعِ هر مسیر + آخرین پاسخ‌ها. فقط می‌خواند؛ به متیس و گره درخواست نمی‌فرستد.
· `update(data)` — ذخیرهٔ تنظیم (اعتبارسنجی‌شده).
· `run_test(provider, kind)` — «آزمون»: یک درخواستِ کوچکِ واقعی. متیس فقط وقتی مالک دکمه را بزند؛ هیچ آزمونِ خودکاری
  این تابع را صدا نمی‌زند (آزمون‌ها provider ساختگی می‌گذارند).
"""
from __future__ import annotations

import base64
import logging
import time

from . import priority
from .priority import CODE, LOCAL, METIS, TEXT, VISION

logger = logging.getLogger(__name__)

# یک تصویرِ ۱×۱ برای آزمونِ مدلِ بینایی
_PIXEL = base64.b64encode(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)).decode("ascii")


class UpdateError(ValueError):
    def __init__(self, errors):
        super().__init__("؛ ".join(errors.values()))
        self.errors = errors


def _iso(value):
    return value.isoformat() if value else None


def _states():
    try:
        from apps.ai.models import AiProviderState

        return {r.key: r for r in AiProviderState.objects.all()}
    except Exception as exc:  # noqa: BLE001
        logger.info("AI states unavailable: %s", exc)
        return {}


def _worst(rows, now):
    """از چند ردیفِ حالت (مثلاً local و local:qwq:32b) مهم‌ترین را برمی‌گرداند: مدارِ باز، وگرنه تازه‌ترین شکست."""
    open_rows = [r for r in rows if r.open_until and r.open_until > now]
    if open_rows:
        return max(open_rows, key=lambda r: r.open_until)
    failed = [r for r in rows if r.last_fail_at]
    return max(failed, key=lambda r: r.last_fail_at) if failed else None


def _history_metis_error():
    """وقتی هنوز هیچ ثبتی در حالتِ مسیرها نیست: آخرین خطای «حساب/کلید» که در دفترِ AIRequest مانده (بی‌فراخوانیِ تازه)."""
    try:
        from apps.ai.models import AIRequest

        for row in AIRequest.objects.exclude(error="").order_by("-created_at")[:60]:
            f = priority.classify(RuntimeError(row.error), METIS)
            if f.kind in {"no_credit", "bad_key", "rate_limit"}:
                return {"kind": f.kind, "message": f.message, "at": _iso(row.created_at), "from_history": True}
    except Exception as exc:  # noqa: BLE001
        logger.info("AI history unavailable: %s", exc)
    return None


def snapshot() -> dict:
    from django.utils import timezone

    from . import routing

    cfg = priority.config()
    now = timezone.now()
    states = _states()

    kinds = {}
    for kind in priority.KINDS:
        st = routing.node_state(kind)
        kinds[kind] = {
            "label": priority.KIND_LABEL[kind],
            "override": cfg.overrides.get(kind, "") or "",
            "first": cfg.first_for(kind),
            "order": cfg.order(kind),
            "selected_model": cfg.models.get(kind, "") or "",
            "default_model": priority.env_model(kind),
            "model": priority.local_model(kind, cfg),
            "installed": st["has_model"],
            "ready": st["ready"],
            "reason": st["reason"],
            "metis_model": priority.metis_model(kind),
        }

    base = routing.node_state(TEXT)
    local_rows = [r for k, r in states.items() if k == LOCAL or k.startswith(LOCAL + ":")]
    worst_local = _worst(local_rows, now)
    metis_row = states.get(METIS)
    ok_times = [r.last_ok_at for r in local_rows if r.last_ok_at]

    local = {
        "online": base["online"],
        "node": base["node"] or ", ".join(n["name"] for n in base["nodes"] if n["online"]),
        "nodes": [{"name": n["name"], "online": n["online"]} for n in base["nodes"]],
        "known_models": routing.node_models(),
        "reason": "" if base["online"] else base["reason"],
        "last_ok_at": _iso(max(ok_times) if ok_times else None),
        "last_error": ({"kind": worst_local.fail_kind, "message": worst_local.fail_message, "at": _iso(worst_local.last_fail_at)}
                       if worst_local and worst_local.last_fail_at else None),
        "circuit_open_until": _iso(worst_local.open_until) if worst_local and worst_local.open_until and worst_local.open_until > now else None,
        "circuit_minutes_left": priority.minutes_left(worst_local.open_until) if worst_local and worst_local.open_until else 0,
    }

    last_error = None
    if metis_row and metis_row.last_fail_at and (not metis_row.last_ok_at or metis_row.last_fail_at >= metis_row.last_ok_at):
        last_error = {"kind": metis_row.fail_kind, "message": metis_row.fail_message, "at": _iso(metis_row.last_fail_at)}
    elif not (metis_row and metis_row.last_ok_at):
        last_error = _history_metis_error()
    metis = {
        "configured": priority.metis_configured(),
        "host": priority.metis_host(),
        "model_text": priority.metis_model(TEXT),
        "model_vision": priority.metis_model(VISION),
        "last_ok_at": _iso(metis_row.last_ok_at) if metis_row else None,
        "last_error": last_error,
        "circuit_open_until": _iso(metis_row.open_until) if metis_row and metis_row.open_until and metis_row.open_until > now else None,
        "circuit_minutes_left": priority.minutes_left(metis_row.open_until) if metis_row and metis_row.open_until else 0,
    }

    recent = []
    try:
        from apps.ai.models import AIRequest

        for r in AIRequest.objects.order_by("-created_at")[:12]:
            recent.append({
                "id": r.pk, "at": _iso(r.created_at), "prompt_id": r.prompt_id, "task_type": r.task_type,
                "status": r.status, "label": r.answer_label, "via": r.via, "model": r.model,
                "fell_back": r.fell_back, "reason": r.fallback_reason, "latency_ms": r.latency_ms,
                "error": (r.error or "")[:200],
            })
    except Exception as exc:  # noqa: BLE001
        logger.info("AI recent unavailable: %s", exc)

    return {
        "priority": cfg.priority,
        "breaker_minutes": cfg.breaker_minutes,
        "orders": [{"value": priority.LOCAL_FIRST, "label": "اول لوکال (سرورِ پردازش)، متیس پشتیبان"},
                   {"value": priority.METIS_FIRST, "label": "اول متیس، لوکال پشتیبان"}],
        "kinds": kinds,
        "local": local,
        "metis": metis,
        "recent": recent,
    }


def update(data: dict) -> None:
    """ذخیرهٔ تنظیم. کلیدهای ناشناخته نادیده؛ مقدار نادرست ⇒ UpdateError با پیامِ فارسی."""
    from apps.ai.models import AiPriority

    errors: dict[str, str] = {}
    row = AiPriority.get()
    orders = set(priority.ORDERS)

    if "priority" in data:
        if data["priority"] not in orders:
            errors["priority"] = "اولویتِ کلی باید «اول لوکال» یا «اول متیس» باشد."
        else:
            row.priority = data["priority"]
    for kind in priority.KINDS:
        key = "priority_%s" % kind
        if key in data:
            value = data[key] or ""
            if value not in orders | {""}:
                errors[key] = "اولویتِ %s درست نیست." % priority.KIND_LABEL[kind]
            else:
                setattr(row, key, value)
        mkey = "model_%s" % kind
        if mkey in data:
            value = str(data[mkey] or "").strip()
            if len(value) > 120 or any(c.isspace() for c in value):
                errors[mkey] = "نامِ مدلِ %s درست نیست." % priority.KIND_LABEL[kind]
            else:
                setattr(row, mkey, value)
    if "breaker_minutes" in data:
        try:
            minutes = int(data["breaker_minutes"])
            if not 1 <= minutes <= 120:
                raise ValueError
            row.breaker_minutes = minutes
        except (TypeError, ValueError):
            errors["breaker_minutes"] = "مدتِ کنارگذاشتن عددی بین ۱ تا ۱۲۰ دقیقه است."
    if errors:
        raise UpdateError(errors)
    row.save()


def _result(ok: bool, provider: str, kind: str, message: str, **extra) -> dict:
    out = {"ok": ok, "provider": provider, "kind": kind, "message": message}
    out.update(extra)
    return out


def run_test(provider: str, kind: str = TEXT) -> dict:
    """«آزمون» ِ یک مسیر. متیس: یک درخواستِ کوچک (۴ توکن). لوکال: اگر گره آنلاین و مدل نصب است یک درخواستِ کوچک از صف."""
    if kind not in priority.KINDS:
        kind = TEXT
    if provider == METIS:
        return _test_metis(kind)
    if provider == LOCAL:
        return _test_local(kind)
    return _result(False, provider, kind, "مسیرِ ناشناخته.")


def _test_local(kind: str) -> dict:
    from . import routing

    state = routing.node_state(kind)
    model = state["model"]
    if not state["online"]:
        return _result(False, LOCAL, kind, state["reason"] or "سرورِ پردازش خاموش است.", model=model, failure="offline")
    if state["has_model"] is False:
        return _result(False, LOCAL, kind, "مدلِ %s روی سرورِ پردازش نصب نیست." % model, model=model, failure="no_model")
    started = time.monotonic()
    try:
        prov = routing.node_provider(state["node"], kind, claim_s=25, run_s=180)
        images = [_PIXEL] if kind == VISION else None
        prov.generate(model, "Reply with one word: OK", images=images, options={"num_predict": 8, "temperature": 0})
    except Exception as exc:  # noqa: BLE001 — گزارشِ صادقانهٔ علت
        failure = priority.classify(exc, LOCAL, model)
        if failure.kind == "no_model":
            failure.message = "مدلِ %s روی سرورِ پردازش نصب نیست." % model
        priority.trip(LOCAL, failure, model)
        return _result(False, LOCAL, kind, failure.sentence(), model=model, failure=failure.kind)
    seconds = round(time.monotonic() - started, 1)
    priority.ok(LOCAL, model)
    priority.reset(LOCAL)
    return _result(True, LOCAL, kind, "لوکال جواب داد (%s، %s ثانیه)." % (model, seconds), model=model, seconds=seconds)


def _test_metis(kind: str) -> dict:
    from . import factory, providers

    capability = providers.VISION if kind == VISION else providers.TEXT
    api = providers._api_default(capability)
    if api is None or not api.api_key:
        return _result(False, METIS, kind, "متیس تنظیم نشده است (AI_API_BASE_URL و AI_API_KEY).", failure="unconfigured")
    started = time.monotonic()
    try:
        prov = factory.build(api)
        prov.retries = 0
        prov.generate("Reply with one word: OK", model=api.model_name, num_predict=4, timeout=25,
                      images=[_PIXEL] if kind == VISION else None)
    except Exception as exc:  # noqa: BLE001
        failure = priority.classify(exc, METIS, api.model_name)
        priority.trip(METIS, failure, api.model_name)
        return _result(False, METIS, kind, failure.sentence(), model=api.model_name, failure=failure.kind)
    seconds = round(time.monotonic() - started, 1)
    priority.ok(METIS, api.model_name)
    priority.reset(METIS)
    return _result(True, METIS, kind, "متیس جواب داد (%s، %s ثانیه)." % (api.model_name, seconds), model=api.model_name, seconds=seconds)
