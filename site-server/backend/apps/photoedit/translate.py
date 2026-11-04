"""ترجمهٔ توضیحِ «پرکردنِ هوشمند» از فارسی به انگلیسیِ کوتاه و تحت‌اللفظی (FLUX فارسی را خوب نمی‌فهمد).

قرارداد (تصمیمِ مالک: «انگلیسی بشه بد نیست فقط باید درست ترجمه بشه»):

* توضیحِ بی حرفِ فارسی (انگلیسی یا خالی) ⇐ هیچ ترجمه‌ای انجام نمی‌شود؛ خالی هنوز یعنی «حذف و پر کردن با پس‌زمینه».
* فارسی یا ترکیبی ⇐ از همان مسیریابیِ متنِ پروژه (``services.ai.gateway.text_provider``: لوکال ⇄ متیس، ترتیب = «اولویتِ
  هوش مصنوعی»، با زنجیرهٔ جایگزینِ مدل‌های لوکال) با یک دستورِ ثابتِ «فقط ترجمه کن»، دمای پایین، وارسیِ خروجی و یک بار
  تلاشِ دوباره؛ جوابِ خوب در فایل کَش می‌شود (به‌ازای فروشگاه).
* مترجم الان در دسترس نیست (سرورِ پردازش خاموش و متیس ۴۰۲/بی‌کلید) ⇐ ``Unavailable`` با جملهٔ فارسیِ دلیل؛ کارِ پرکردن
  گم نمی‌شود: services.genfill_request آن را «منتظرِ ترجمه» نگه می‌دارد (نگاه کنید به GENFILL_HOLD).

بدونِ Django مگر در ``get_provider`` / ``cache_root``؛ مترجم و پوشهٔ کَش تزریق‌پذیرند تا آزمون هرگز به هوشِ مصنوعیِ واقعی
نرسد (``translate(text, provider=fake)``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: با عوض‌شدنِ دستور یا قاعده‌های وارسی کَشِ قبلی باطل می‌شود
VERSION = "1"
MAX_SRC = 500                    # بیشترین طولِ متنِ فارسی (مثلِ inpaint.MAX_PROMPT)
MAX_OUT = 400                    # بیشترین طولِ ترجمه
TEMPERATURE = 0.1
NUM_PREDICT = 160
CALL_TIMEOUT = 60                # ثانیه، برای هر تلاش
CACHE_MAX_FILES = 400            # به‌ازای فروشگاه

PENDING_TTL = 150                # ثانیه — «در حالِ ترجمه» ِ پیش‌نمایش بعد از این کهنه حساب می‌شود
UNAVAILABLE_TTL = 15             # جوابِ «مترجم نیست» چند ثانیه نگه داشته می‌شود (تا دکمه پشتِ هم نرود)
FAILED_TTL = 30

_ARABIC = re.compile("[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_ASCII_LETTER = re.compile("[A-Za-z]")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_META = re.compile(r"^\s*(sure\b|certainly\b|of course\b|okay\b|ok[,.:!]|here is\b|here's\b|here are\b|i'm sorry\b|i am sorry\b|"
                   r"i cannot\b|i can't\b|i can not\b|as an ai\b|the translation\b|note:)", re.I)
_LABEL = re.compile(r"^\s*(english(\s+translation)?|translation)\s*[:：\-–]\s*", re.I)

#: دستورِ ثابت: فقط ترجمه، چیزی اضافه نشود. مثال‌ها فقط قالب را نشان می‌دهند (وارسی جلوی نشتِ آن‌ها را می‌گیرد).
EXAMPLES = (
    ("یک گلدانِ شیشه‌ای آبی روی میزِ چوبی", "a blue glass vase on a wooden table"),
    ("سه سیبِ قرمز کنارِ پنجره", "three red apples next to the window"),
    ("آسمانِ آبی با ابرهای سفید", "blue sky with white clouds"),
)
SYSTEM = (
    "You are a literal translator for image-generation prompts. Translate the user's Persian text into English.\n"
    "Rules:\n"
    "- Translate only. Keep every object, colour, material, count, size, position and style word exactly as given.\n"
    "- Do not add, remove, explain, improve or embellish anything. Add no adjectives, no lighting, no quality words.\n"
    "- Words that are already English stay unchanged. Write numbers as digits.\n"
    "- Reply with the English translation only: one short line, no quotes, no notes, no Persian.\n"
    "Examples:\n" + "\n".join(f"Persian: {fa}\nEnglish: {en}" for fa, en in EXAMPLES)
)
RETRY_HINT = ("\n\nYour previous reply was not a plain English translation. "
              "Reply with the English translation only, on one line, with no explanation.")

MSG_UNAVAILABLE = "الان هیچ مترجمی در دسترس نیست"
MSG_FAILED = ("ترجمهٔ خودکار درست درنیامد (مترجم دو بار خروجیِ قابل‌استفاده نداد). توضیح را ساده‌تر بنویسید یا همین‌جا "
              "انگلیسی بنویسید.")


class TranslateError(Exception):
    """متنش برای کاربر است (فارسی)."""


class Unavailable(TranslateError):
    """هیچ مترجمی الان جواب نمی‌دهد (گره خاموش، متیس بی‌اعتبار/بی‌کلید، سیاستِ داده…)؛ بعداً دوباره امتحان می‌شود."""

    @property
    def reason(self) -> str:
        """فقط علت («سرورِ پردازش خاموش است؛ …»)، بی پیشوندِ «الان هیچ مترجمی…»."""
        s, prefix = str(self), MSG_UNAVAILABLE + ": "
        if s.startswith(prefix):
            return s[len(prefix):]
        return "" if s == MSG_UNAVAILABLE else s


class Failed(TranslateError):
    """مترجم جواب داد ولی دو بار خروجیِ بی‌مصرف بود."""


@dataclass
class Translation:
    fa: str
    en: str
    source: str = "auto"          # auto (مترجم) | cache | user
    via: str = ""                 # local | metis | ""
    model: str = ""
    label: str = ""               # «لوکال (gemma3:12b)»
    cached: bool = False

    def as_dict(self) -> dict:
        return {"fa": self.fa, "en": self.en, "source": self.source, "via": self.via, "model": self.model,
                "label": self.label, "cached": self.cached}


# ───────────────────────────── متن

def normalize(text) -> str:
    """فاصله‌ها یکی، ی/ک عربی ⇐ فارسی، کشیده حذف؛ ارقامِ فارسی/عربی سرِ جایشان می‌مانند (به مدل ASCII می‌رود: ``for_model``)."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = t.replace("ي", "ی").replace("ك", "ک").replace("ـ", "")
    return " ".join(t.split())[:MAX_SRC]


def for_model(text: str) -> str:
    return normalize(text).translate(_DIGITS)


def needs_translation(text) -> bool:
    """حرفِ فارسی/عربی دارد؟ (انگلیسیِ خالص و خالی ⇒ نه)"""
    return bool(_ARABIC.search(str(text or "")))


def key_for(text) -> str:
    """کلیدِ کَش: نیم‌فاصله ≡ فاصله، ارقام یکسان، حروفِ لاتین بی‌حساس به بزرگ‌وکوچک."""
    t = normalize(text).translate(_DIGITS).replace("‌", " ")
    t = " ".join(t.split()).lower()
    return hashlib.sha256(f"{VERSION}\n{t}".encode("utf-8")).hexdigest()[:32]


def valid_english(text, *, max_len: int = MAX_SRC) -> bool:
    """متنِ انگلیسیِ قابل‌استفاده برای FLUX: حرفِ فارسی ندارد، دست‌کم دو حرفِ لاتین دارد، طولش معقول است (بی‌خطِ جدید)."""
    t = " ".join(str(text or "").split())
    if not t or len(t) > max_len or _ARABIC.search(t):
        return False
    return len(_ASCII_LETTER.findall(t)) >= 2


def clean_english(text: str) -> str:
    """نشانه‌های اضافهٔ مدل (برچسبِ «English:»، نقل‌قول، پرچینِ کد) برداشته می‌شود؛ محتوا دست نمی‌خورد."""
    t = str(text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t).strip()
    t = _LABEL.sub("", t)
    t = t.strip(" \t\r\n\"'`“”‘’«»")
    return t


def check_output(out, src) -> tuple[bool, str]:
    """⇒ (درست؟، ترجمهٔ پاک‌شده یا دلیلِ ردّ). لاتین، طولِ معقول، تک‌خطی، نه پژواکِ ورودی، نه جملهٔ مدل، نه نشتِ مثال."""
    t = clean_english(out)
    if not t:
        return False, "خالی"
    if "\n" in t.strip():
        return False, "چند خط"
    if _ARABIC.search(t):
        return False, "حرفِ فارسی دارد"
    if _META.match(t):
        return False, "جملهٔ مدل، نه ترجمه"
    letters = len(_ASCII_LETTER.findall(t))
    if letters < 2 or letters / max(1, len(t.replace(" ", ""))) < 0.5:
        return False, "لاتین نیست"
    if len(t) > MAX_OUT or len(t.split()) > 70 or len(t) > 4 * len(str(src or "")) + 40:
        return False, "درازتر از حدِ معقول"
    if normalize(t).lower() == normalize(src).lower():
        return False, "پژواکِ ورودی"
    words = _words(src)
    for fa, en in EXAMPLES:
        # جوابی که عینِ ترجمهٔ یکی از مثال‌هاست ولی ورودی به آن مثال شبیه نیست ⇒ مدل مثال را بازگو کرده
        if t.lower().rstrip(". ") == en and len(words & _words(fa)) / max(1, len(words)) < 0.5:
            return False, "نشتِ مثالِ دستور"
    return True, t


def _words(text) -> set:
    return set(normalize(text).replace("‌", " ").split())


# ───────────────────────────── کَش (فایل؛ وب و celery هر دو می‌بینند)

def cache_root():
    from django.conf import settings

    base = getattr(settings, "NM_DATA_DIR", None) or Path(settings.MEDIA_ROOT).parent
    return Path(base) / "photoedit" / "translations"


def _dir(store) -> Path:
    d = cache_root() / f"s{getattr(store, 'pk', store) or 0}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def cache_get(store, text) -> Translation | None:
    rec = _read(_dir(store) / f"{key_for(text)}.json")
    if not rec or rec.get("v") != VERSION or not valid_english(rec.get("en")):
        return None
    return Translation(fa=normalize(text), en=str(rec["en"]), source="cache", via=str(rec.get("via") or ""),
                       model=str(rec.get("model") or ""), label=str(rec.get("label") or ""), cached=True)


def cache_put(store, text, tr: Translation) -> None:
    try:
        d = _dir(store)
        _write(d / f"{key_for(text)}.json", {"v": VERSION, "fa": normalize(text), "en": tr.en, "via": tr.via, "model": tr.model,
                                             "label": tr.label, "source": tr.source, "t": int(time.time())})
        files = sorted((p for p in d.glob("*.json") if not p.name.startswith("state-")), key=lambda p: p.stat().st_mtime)
        for old in files[:-CACHE_MAX_FILES]:
            old.unlink(missing_ok=True)
    except OSError as exc:      # کَش نباید کار را بخواباند
        logger.info("photoedit.translate: cache write failed: %s", exc)


def remember_user(store, text, en) -> None:
    """ترجمهٔ ویرایش‌شدهٔ مالک (اصلاحِ ترجمهٔ خودکار) هم کَش می‌شود تا دفعهٔ بعد همین بیاید."""
    if valid_english(en):
        cache_put(store, text, Translation(fa=normalize(text), en=" ".join(str(en).split()), source="user"))


def state_get(store, text) -> dict | None:
    return _read(_dir(store) / f"state-{key_for(text)}.json")


def state_put(store, text, data: dict) -> None:
    try:
        _write(_dir(store) / f"state-{key_for(text)}.json", {**data, "t": time.time()})
    except OSError:
        pass


def state_clear(store, text) -> None:
    try:
        (_dir(store) / f"state-{key_for(text)}.json").unlink(missing_ok=True)
    except OSError:
        pass


# ───────────────────────────── مترجم

def get_provider(store):
    """مسیریابِ متنِ پروژه (لوکال ⇄ متیس، به ترتیبِ تنظیمِ مالک). زیرِ آزمون، بی جایگزینِ ساختگی، هیچ‌وقت به شبکه نمی‌رسد."""
    from django.conf import settings

    from services.ai import gateway

    fn = gateway.text_provider
    if getattr(settings, "IS_TEST", False) and getattr(fn, "__module__", "") == gateway.__name__:
        raise RuntimeError("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")
    return fn(store)


def explain(exc: Exception) -> str:
    """دلیلِ شکست به فارسی؛ AllProvidersFailed خودش دلیلِ هر دو مسیر را می‌گوید."""
    text = str(exc or "").strip()
    if exc.__class__.__name__ in ("AllProvidersFailed", "PolicyBlocked") and text:
        return text[:500]
    try:
        from services.ai import priority

        return priority.classify(exc).sentence()[:500]
    except Exception:  # noqa: BLE001
        return (text or exc.__class__.__name__)[:300]


def _describe(provider) -> dict:
    fn = getattr(provider, "describe", None)
    if callable(fn):
        try:
            got = fn()
            return got if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _ask(provider, src: str, retry: bool) -> str:
    prompt = f"Persian: {for_model(src)}\nEnglish:" + (RETRY_HINT if retry else "")
    out = provider.generate(prompt, system=SYSTEM, temperature=TEMPERATURE, num_predict=NUM_PREDICT, timeout=CALL_TIMEOUT)
    return out if isinstance(out, str) else str(out or "")


def translate(text, *, store=None, provider=None, use_cache: bool = True) -> Translation:
    """متنِ فارسی (یا ترکیبی) ⇒ ``Translation``. انگلیسیِ خالص/خالی ⇒ همان متن (بی مترجم، ``source="none"``).

    ``Unavailable``: مترجمی نیست (متنِ دلیل فارسی)؛ ``Failed``: مترجم دو بار خروجیِ بی‌مصرف داد.
    ``provider`` تزریق‌پذیر است (آزمون)؛ وگرنه ``get_provider(store)``.
    """
    fa = normalize(text)
    if not needs_translation(fa):
        return Translation(fa=fa, en=fa, source="none")
    if use_cache:
        hit = cache_get(store, fa)
        if hit:
            return hit
    try:
        prov = provider if provider is not None else get_provider(store)
    except Exception as exc:  # noqa: BLE001 — سیاستِ داده، تنظیم‌نبودن، آزمون
        raise Unavailable(explain(exc)) from exc
    avail = getattr(prov, "availability", None)
    if callable(avail):
        try:
            ok, why = avail()
        except Exception:  # noqa: BLE001
            ok, why = True, ""
        if not ok:
            raise Unavailable(f"{MSG_UNAVAILABLE}: {why}" if why else MSG_UNAVAILABLE)
    last = ""
    for attempt in (0, 1):
        try:
            raw = _ask(prov, fa, retry=bool(attempt))
        except Exception as exc:  # noqa: BLE001 — هر شکستِ مسیر ⇒ «مترجم نیست»
            raise Unavailable(f"{MSG_UNAVAILABLE}: {explain(exc)}") from exc
        ok, res = check_output(raw, fa)
        if ok:
            info = _describe(prov)
            tr = Translation(fa=fa, en=res, source="auto", via=str(info.get("via") or ""), model=str(info.get("model") or ""),
                             label=str(info.get("label") or ""))
            cache_put(store, fa, tr)
            return tr
        last = res
        logger.info("photoedit.translate: bad output (%s) on attempt %d", res, attempt + 1)
    raise Failed(f"{MSG_FAILED} ({last})")


# ───────────────────────────── پیش‌نمایشِ بی‌انتظار (پنل)

def _preview_dict(fa: str, state: str, **extra) -> dict:
    return {"fa": fa, **extra, "state": state, "needed": state != "none"}


def preview_request(store, text, dispatch) -> dict:
    """جوابِ فوریِ پنل: ``state`` = none | ok | pending | unavailable | failed.

    ترجمه روی celery انجام می‌شود (``dispatch(store_id, fa)``) تا درخواستِ وب منتظرِ گره/متیس نماند؛ پنل تا پایانِ
    ``pending`` همین را دوباره می‌پرسد. زیرِ آزمون (celery eager) همان‌جا تمام می‌شود."""
    fa = normalize(text)
    if not needs_translation(fa):
        return _preview_dict(fa, "none", en=fa)
    hit = cache_get(store, fa)
    if hit:
        return _preview_dict(fa, "ok", **{k: v for k, v in hit.as_dict().items() if k != "fa"})
    st = state_get(store, fa)
    now = time.time()
    if st:
        age = now - float(st.get("t") or 0)
        ttl = {"pending": PENDING_TTL, "unavailable": UNAVAILABLE_TTL, "failed": FAILED_TTL}.get(st.get("state"), 0)
        if age < ttl:
            return _preview_dict(fa, st["state"], message=st.get("message", ""))
    state_put(store, fa, {"state": "pending"})
    dispatch(getattr(store, "pk", store), fa)
    hit = cache_get(store, fa)
    if hit:
        return _preview_dict(fa, "ok", **{k: v for k, v in hit.as_dict().items() if k != "fa"})
    st = state_get(store, fa) or {"state": "pending"}
    return _preview_dict(fa, st.get("state", "pending"), message=st.get("message", ""))


def run_preview(store, text) -> None:
    """بدنهٔ کارِ celery برای پیش‌نمایش: نتیجه یا دلیلِ شکست را در فایلِ وضعیت می‌گذارد."""
    fa = normalize(text)
    try:
        translate(fa, store=store)
        state_clear(store, fa)
    except Unavailable as exc:
        state_put(store, fa, {"state": "unavailable", "message": str(exc)})
    except Failed as exc:
        state_put(store, fa, {"state": "failed", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        logger.exception("photoedit.translate: preview failed")
        state_put(store, fa, {"state": "unavailable", "message": f"{MSG_UNAVAILABLE}: {explain(exc)}"})
