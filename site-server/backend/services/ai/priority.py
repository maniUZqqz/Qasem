# -*- coding: utf-8 -*-
"""اولویتِ هوش مصنوعی: «اول لوکال» یا «اول متیس» (تصمیمِ مالک، ۱۴۰۵/۰۸/۱۲).

هر کارِ هوش مصنوعی در NM باید با هر دو مسیر بتواند انجام شود:

  · لوکال = Ollama روی سرورِ پردازشِ مالک (از صفِ apps.compute) با مدل‌های gemma3:12b (متنِ روزمره) / qwq:32b (پژوهش) /
    qwen3-coder (کد) / qwen3-vl (بینایی)؛ اگر مدلِ انتخابی نصب نبود، مدلِ مناسبِ بعدیِ نصب‌شده (model_catalog.CHAINS)
  · متیس  = API ِ ابری (سازگار با OpenAI)

یک تنظیم (apps.ai.AiPriority) می‌گوید کدام اول باشد؛ اگر اولی در دسترس نبود (گره خاموش، مدل نصب‌نشده، مهلت،
HTTP ۴۰۲، ۴۰۱/۴۰۳، ۵xx، قطعِ اتصال) همان لحظه دومی جواب می‌دهد. این ماژول سه کار می‌کند:

  ۱. خواندنِ تنظیم (`config()`)، مدلِ لوکالِ هر نوعِ کار (`local_model(kind)`)
  ۲. دسته‌بندیِ خطا (`classify`) به جمله‌ای فارسی که مالک بفهمد («اعتبار تمام شده (۴۰۲)»، «سرورِ پردازش خاموش است»)
  ۳. «کلیدِ مدار» (circuit breaker): شکستِ تازه چند دقیقه یادش می‌ماند تا هر درخواست منتظرِ مهلتِ یک سرویسِ مرده نماند.
     حالت در دیتابیس است (AiProviderState) چون وب و celery چند پردازه‌اند.

هیچ‌جای این ماژول به متیس یا گره درخواست نمی‌فرستد؛ فقط تصمیم و ثبت.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

LOCAL = "local"
METIS = "metis"
PROVIDERS = (LOCAL, METIS)
PROVIDER_LABEL = {LOCAL: "لوکال", METIS: "متیس"}

CODE = "code"
TEXT = "text"
RESEARCH = "research"
VISION = "vision"
#: متنِ روزمره (سریع) / پژوهش و استدلالِ عمیق (کند و دقیق) / کد / بینایی — ۱۴۰۵/۰۸/۱۲: متن از پژوهش جدا شد
KINDS = (TEXT, RESEARCH, CODE, VISION)
KIND_LABEL = {TEXT: "متنِ روزمره (محتوا، کپشن، چت)", RESEARCH: "پژوهش و استدلالِ عمیق",
              CODE: "کد و سایت‌ساز", VISION: "بینایی (تصویر)"}

LOCAL_FIRST = "local_first"
METIS_FIRST = "metis_first"
ORDERS = (LOCAL_FIRST, METIS_FIRST)

#: services.ai.router task type → نوعِ کار (REASONING = متنِ روزمره؛ RESEARCH = پژوهش)
TASK_KIND = {"REASONING": TEXT, "RESEARCH": RESEARCH, "CODE": CODE, "VISION": VISION}


def kind_of_task(task_type: str) -> str:
    return TASK_KIND.get(task_type, TEXT)


# ───────────────────────────── تنظیم

@dataclass(frozen=True)
class Config:
    priority: str = LOCAL_FIRST
    overrides: dict = field(default_factory=dict)      # kind -> '' | local_first | metis_first
    models: dict = field(default_factory=dict)         # kind -> '' | نامِ مدلِ لوکال
    breaker_minutes: int = 5

    def first_for(self, kind: str) -> str:
        chosen = (self.overrides or {}).get(kind) or self.priority
        return METIS if chosen == METIS_FIRST else LOCAL

    def order(self, kind: str) -> list[str]:
        return [METIS, LOCAL] if self.first_for(kind) == METIS else [LOCAL, METIS]


def config() -> Config:
    """تنظیمِ فعلی؛ اگر جدول هنوز نیست (پیش از مهاجرت) پیش‌فرض: اول لوکال."""
    try:
        from apps.ai.models import AiPriority

        row = AiPriority.get()
    except Exception as exc:  # noqa: BLE001 — پیش از مهاجرت / بی‌دیتابیس
        logger.info("AI priority unavailable (%s) — default local_first", exc)
        return Config()
    return Config(
        priority=row.priority if row.priority in ORDERS else LOCAL_FIRST,
        overrides={CODE: row.priority_code, TEXT: row.priority_text, VISION: row.priority_vision,
                   RESEARCH: getattr(row, "priority_research", "") or ""},
        models={CODE: (row.model_code or "").strip(), TEXT: (row.model_text or "").strip(),
                VISION: (row.model_vision or "").strip(),
                RESEARCH: (getattr(row, "model_research", "") or "").strip()},
        breaker_minutes=max(1, int(row.breaker_minutes or 5)),
    )


#: نگاشتِ پیش‌فرضِ نوعِ کار ⇒ مدلِ لوکال (۱۴۰۵/۰۸/۱۲؛ مهاجرتِ ai 0020 همین‌ها را ذخیره می‌کند مگر مالک دستی عوض کرده باشد).
#: متنِ روزمره Gemma 3 12B (سریع و فارسیِ خوب، کاملاً روی ۱۲ گیگابایت)؛ پژوهش QwQ 32B؛ کد Qwen3 Coder؛ بینایی Qwen3 VL.
DEFAULT_MODELS = {TEXT: "gemma3:12b", RESEARCH: "qwq:32b", CODE: "qwen3-coder:30b", VISION: "qwen3-vl:30b"}

#: کلیدِ .env هر نوع (متنِ روزمره MODEL_TEXT ندارد مگر در .env گذاشته شود؛ پژوهش همان MODEL_REASONING ِ قدیمی است)
_ENV_KEY = {CODE: "MODEL_CODER", TEXT: "MODEL_TEXT", RESEARCH: "MODEL_REASONING", VISION: "MODEL_VISION"}


def env_model(kind: str) -> str:
    """مدلِ پیش‌فرضِ لوکال برای این نوعِ کار — از .env (MODEL_TEXT / MODEL_REASONING / MODEL_CODER / MODEL_VISION)، وگرنه DEFAULT_MODELS."""
    conf = settings.UPMARKET_AI
    return conf.get(_ENV_KEY.get(kind, "MODEL_TEXT"), "") or DEFAULT_MODELS.get(kind, "")


def local_model(kind: str, cfg: Config | None = None) -> str:
    """مدلِ لوکالِ این نوعِ کار: انتخابِ مالک، وگرنه پیش‌فرضِ .env."""
    cfg = cfg or config()
    return (cfg.models or {}).get(kind) or env_model(kind)


def local_chain(kind: str, cfg: Config | None = None) -> list[str]:
    """مدلِ لوکالِ این نوعِ کار + مدل‌های مناسبِ بعدی (services.ai.model_catalog.CHAINS). اگر اولی روی گره نصب نبود،
    اولین نصب‌شده جواب می‌دهد — پیش از آن‌که کار به متیس برود."""
    from . import model_catalog

    return model_catalog.chain_for(kind, local_model(kind, cfg))


def metis_model(kind: str) -> str:
    conf = settings.UPMARKET_AI
    return conf.get("AI_API_MODEL_VISION" if kind == VISION else "AI_API_MODEL_TEXT", "") or ""


def metis_configured() -> bool:
    conf = settings.UPMARKET_AI
    return bool(conf.get("AI_API_BASE_URL") and conf.get("AI_API_KEY"))


def metis_host() -> str:
    from urllib.parse import urlparse

    url = settings.UPMARKET_AI.get("AI_API_BASE_URL") or ""
    return urlparse(url).hostname or url


# ───────────────────────────── برچسبِ پاسخ

def answer_label(via: str, model: str = "", fell_back: bool = False) -> str:
    """«لوکال (qwq:32b)» · «متیس (gpt-4o-mini)» · «متیس (پشتیبان)» · «لوکال (پشتیبان: qwq:32b)»"""
    if via == LOCAL:
        if fell_back:
            return "لوکال (پشتیبان: %s)" % model if model else "لوکال (پشتیبان)"
        return "لوکال (%s)" % model if model else "لوکال"
    if via == METIS:
        if fell_back:
            return "متیس (پشتیبان)"
        return "متیس (%s)" % model if model else "متیس"
    return ""


# ───────────────────────────── دسته‌بندیِ خطا

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

#: نوعِ شکست → جمله‌ای که مالک می‌فهمد
LABELS = {
    "no_credit": "اعتبار حساب تمام شده است (۴۰۲)",
    "bad_key": "کلید پذیرفته نشد یا دسترسی رد شد (۴۰۱/۴۰۳)",
    "rate_limit": "سهمیه یا سقفِ درخواست تمام شده است (۴۲۹)",
    "server": "سرویس خطای سروری داد (۵xx)",
    "timeout": "در مهلتِ مقرر جواب نداد",
    "connection": "اتصال برقرار نشد",
    "offline": "سرورِ پردازش خاموش است",
    "busy": "سرورِ پردازش کار را برنداشت",
    "no_model": "مدل نصب نیست",
    "bad_output": "خروجیِ قابل‌استفاده نداد",
    "unconfigured": "تنظیم نشده است",
    "policy": "سیاستِ داده اجازه نمی‌دهد",
    "error": "خطا داد",
}

#: کدام شکست‌ها «کلیدِ مدار» را باز می‌کنند (سرویس خراب است، نه این یک درخواست)
_TRIPS = {
    METIS: {"no_credit", "bad_key", "rate_limit", "server", "timeout", "connection"},
    LOCAL: {"timeout", "busy", "connection", "offline", "server", "error", "no_model"},
}
#: این شکست‌های لوکال مالِ همان مدل‌اند؛ بقیه مالِ کلِ گره
_MODEL_SCOPED = {"timeout", "server", "error", "no_model"}


@dataclass
class Failure:
    kind: str
    message: str                 # جملهٔ فارسی برای مالک
    provider: str = ""
    model: str = ""
    raw: str = ""
    code: int | None = None

    @property
    def trips(self) -> bool:
        return self.kind in _TRIPS.get(self.provider, set())

    @property
    def key(self) -> str:
        if self.provider == LOCAL and self.kind in _MODEL_SCOPED and self.model:
            return "%s:%s" % (LOCAL, self.model)
        return self.provider

    def sentence(self) -> str:
        """برای پیامِ ترکیبی: جمله + (متنِ خامِ کوتاه، اگر چیزِ بیشتری می‌گوید)."""
        text = self.message
        raw = (self.raw or "").strip()
        if raw and raw not in text and self.kind in {"no_credit", "bad_key", "rate_limit", "server", "error", "bad_output"}:
            text = "%s — %s" % (text, raw[:160])
        return text


def _status_code(text: str) -> int | None:
    m = re.search(r"(?:خطای سرویس|سرویس خطای|http|status(?:_code)?|code|error)\D{0,6}?(\d{3})(?!\d)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\((\d{3})\)", text)
    return int(m.group(1)) if m else None


def classify(exc: Exception, provider: str = "", model: str = "") -> Failure:
    """هر خطای یک مسیر ⇒ Failure با نوعِ شناخته‌شده.

    نوعِ استثنا اول (Timeout / Malformed)، بعد کدِ HTTP در متن (۴۰۲، ۴۰۱، ۴۰۳، ۴۲۹، ۵xx)، بعد واژه‌ها.
    """
    from .ollama import OllamaMalformedOutput, OllamaTimeout, OllamaUnavailable

    raw = (str(exc) or exc.__class__.__name__).strip()
    text = raw.translate(_DIGITS)
    low = text.lower()
    code = _status_code(text)
    node_failed = exc.__class__.__name__ == "NodeFailed"

    def make(kind, message=None):
        return Failure(kind=kind, message=message or LABELS[kind], provider=provider, model=model, raw=raw[:400], code=code)

    if isinstance(exc, OllamaMalformedOutput) and not code:
        return make("bad_output")
    if code == 402 or "payment required" in low or "insufficient" in low or "no credit" in low:
        return make("no_credit")
    if code in (401, 403) or "unauthorized" in low or "invalid api key" in low or "کلید api پذیرفته" in low:
        return make("bad_key")
    if code == 429 or "rate limit" in low or "too many requests" in low or "سهمیه" in text:
        return make("rate_limit")
    if code is not None and code >= 500:
        return make("server", "سرویس خطای سروری داد (%d)" % code)
    if node_failed:
        if "برنداشت" in text:
            return make("busy", text)
        if "قطع شد" in text or "خاموش" in text or "آماده نیست" in text or "ثبت نشده" in text:
            return make("offline", text)
        if "نصب نیست" in text:
            return make("no_model", text)
        if "جواب" in text or "مهلت" in text:
            return make("timeout", text)
    if isinstance(exc, OllamaTimeout) or "timed out" in low or "timeout" in low or "جواب نداد" in text or "مهلت" in text:
        return make("timeout")
    if "not found" in low or code == 404 or "نصب نیست" in text or "model_not_supported" in low or "does not exist" in low:
        return make("no_model", "مدل پیدا نشد یا نصب نیست")
    if isinstance(exc, OllamaUnavailable) or "اتصال" in text or "connection" in low or "refused" in low or "unreachable" in low:
        if provider == LOCAL:
            return make("offline", "سرورِ پردازش (Ollama) در دسترس نیست")
        return make("connection")
    if isinstance(exc, OllamaMalformedOutput):
        return make("bad_output")
    return make("error", "خطا داد: %s" % raw[:160])


# ───────────────────────────── کلیدِ مدار

def _state_model():
    from apps.ai.models import AiProviderState

    return AiProviderState


def _keys(provider: str, model: str = "") -> list[str]:
    keys = [provider]
    if provider == LOCAL and model:
        keys.append("%s:%s" % (LOCAL, model))
    return keys


def trip(provider: str, failure: Failure, model: str = "", minutes: int | None = None) -> None:
    """شکست را ثبت می‌کند؛ اگر از نوعِ «سرویس خراب است» باشد مدار را چند دقیقه باز می‌کند."""
    failure.provider = failure.provider or provider
    failure.model = failure.model or model
    try:
        State = _state_model()
        now = timezone.now()
        row, _ = State.objects.get_or_create(key=failure.key)
        row.last_fail_at = now
        row.fail_kind = failure.kind
        row.fail_message = (failure.sentence() or "")[:500]
        row.fails = (row.fails or 0) + 1
        if failure.trips:
            mins = minutes if minutes is not None else config().breaker_minutes
            row.open_until = now + timedelta(minutes=mins)
        row.save()
    except Exception as exc:  # noqa: BLE001 — ثبت نباید کار را بخواباند
        logger.info("AI breaker write failed: %s", exc)


def ok(provider: str, model: str = "") -> None:
    """یک جوابِ موفق: مدار بسته می‌شود."""
    try:
        State = _state_model()
        now = timezone.now()
        for key in _keys(provider, model):
            State.objects.filter(key=key).update(last_ok_at=now, open_until=None)
        if not State.objects.filter(key=provider).exists():
            State.objects.create(key=provider, last_ok_at=now)
    except Exception as exc:  # noqa: BLE001
        logger.info("AI breaker write failed: %s", exc)


def open_failure(provider: str, model: str = "") -> dict | None:
    """اگر مدارِ این مسیر باز است: {kind, message, until}؛ وگرنه None."""
    try:
        now = timezone.now()
        rows = list(_state_model().objects.filter(key__in=_keys(provider, model), open_until__gt=now).order_by("-open_until"))
    except Exception as exc:  # noqa: BLE001
        logger.info("AI breaker read failed: %s", exc)
        return None
    if not rows:
        return None
    row = rows[0]
    return {"kind": row.fail_kind, "message": row.fail_message, "until": row.open_until, "key": row.key}


def blocked_models(models) -> set:
    """کدام مدل‌های لوکال را خودِ گره تازه گفته «نصب نیست» (فهرستِ مدل‌ها کهنه بود) و هنوز مدتِ کنارگذاشتن نگذشته؟
    فقط شکستِ «مدل نیست»؛ مهلت و خطای دیگر کلِ مسیرِ لوکال را جابه‌جا می‌کند، نه مدل را."""
    names = [m for m in models if m]
    if not names:
        return set()
    try:
        keys = {"%s:%s" % (LOCAL, m): m for m in names}
        rows = _state_model().objects.filter(key__in=list(keys), fail_kind="no_model", open_until__gt=timezone.now())
        return {keys[k] for k in rows.values_list("key", flat=True)}
    except Exception as exc:  # noqa: BLE001
        logger.info("AI breaker read failed: %s", exc)
        return set()


def model_blocked(model: str) -> bool:
    return model in blocked_models([model])


def clear_model(model: str) -> None:
    """مدلی که تازه نصب شد: «مدل نیست»ِ قبلی‌اش فراموش شود."""
    try:
        _state_model().objects.filter(key="%s:%s" % (LOCAL, model)).update(open_until=None)
    except Exception as exc:  # noqa: BLE001
        logger.info("AI breaker reset failed: %s", exc)


def reset(provider: str | None = None) -> int:
    """مدارها را می‌بندد (دکمهٔ «آزمون» اگر موفق بود، یا مالک)."""
    try:
        qs = _state_model().objects.all()
        if provider:
            qs = qs.filter(key__startswith=provider)
        return qs.update(open_until=None)
    except Exception as exc:  # noqa: BLE001
        logger.info("AI breaker reset failed: %s", exc)
        return 0


def minutes_left(until) -> int:
    if not until:
        return 0
    secs = (until - timezone.now()).total_seconds()
    return max(1, int(secs // 60) + (1 if secs % 60 else 0)) if secs > 0 else 0
