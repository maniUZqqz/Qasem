"""خودآزمونِ بانکِ ایده — دو بخش، بی‌هیچ کلیکی (قرارداد: ``docs/selftests/ideabank.md``).

* **آفلاین** (``run_offline``): ایده‌های آماده، پرکردنِ جای‌گیرها، فرمول‌های فارسی و مسیرِ هوش مصنوعی با **جوابِ ساختگی** (بدونِ شبکه و بدونِ گره).
  همیشه و همین‌جا اجرا می‌شود؛ بانکِ آماده هرگز منتظرِ هوش مصنوعی نمی‌ماند.
* **زنده** (``node_spec`` / ``node_check``): همان پرسشِ ایده‌ساز با مدلِ متنیِ خودِ مالک روی گره (``ollama.generate``)؛ جواب با همان وارسیِ تولید سنجیده می‌شود
  (قالبِ درست، بدونِ عدد/قیمت/آمار، فارسی، دست‌کم یک ایدهٔ معتبر). ``apps/compute/selftests/ideabank.py`` این‌ها را به آزمونِ خودکارِ سرورِ پردازش
  وصل می‌کند: به‌محضِ روشن‌شدنِ گره اجرا می‌شود و تا آن موقع «منتظرِ گره» می‌ماند، نه «رد».
"""
from __future__ import annotations

import json
import re

from . import bank, demo, fill, generator, guard
from .catalog import CATEGORIES
from .seeds import BUILTIN_IDEAS

CHECK_TIMEOUT_S = 1800
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
_PERSIAN = re.compile("[؀-ۿ]")


# ───────────────────────────── آفلاین

def _fake_ai(store, prompt: str, system: str):
    """جوابِ ساختگیِ مدل: دو ایدهٔ درست، یک ایدهٔ با قیمتِ ساختگی، یک ایده با قالبِ ناشناخته (باید دور ریخته شوند)."""
    assert "JSON" in prompt and "existing_titles" in prompt
    return ({"ideas": [
        {"title": "برنامهٔ ورزشی را از کجا شروع کنیم؟", "logline": "راهنمای شروعِ برنامهٔ ورزشی برای مربیِ تازه‌کار با چند اسلایدِ ساده.",
         "hook": "تازه سراغِ برنامه‌نویسی برای ورزشکار آمده‌ای؟", "category": "tips", "shoot": "هر گام یک اسلاید با نوشتهٔ کوتاه.", "cta": "ذخیره کن", "format": "carousel", "channel": "both"},
        {"title": "پشتِ صحنهٔ نوشتنِ یک پیش‌نویس", "logline": "نشان بدهید یک پیش‌نویسِ برنامه چطور مرحله‌به‌مرحله آماده می‌شود.",
         "hook": "پیش‌نویس این‌طور شکل می‌گیرد.", "category": "behind", "shoot": "صفحه‌نمایش و دستِ مربی.", "cta": "نظرت را بنویس", "format": "reel", "channel": "instagram"},
        {"title": "پنجاه درصد تخفیفِ ویژه", "logline": "یک پیشنهادِ ساختگی که باید دور ریخته شود.", "hook": "همین حالا بخر", "format": "photo"},
        {"title": "یک ایدهٔ بدونِ قالبِ شناخته‌شده", "logline": "قالبش وجود ندارد و دور ریخته می‌شود.", "hook": "این را نمی‌شناسیم", "format": "hologram"},
    ]}, {"label": "ساختگیِ آزمون"})


def _unavailable(store, prompt: str, system: str):
    raise generator.ai.AIUnavailable("اعتبارِ سرویسِ ابری (متیس) تمام شده است (۴۰۲)")


def run_offline() -> dict:
    """⇒ {ok, checks:[{key, ok, detail}]}. هیچ‌چیز ذخیره نمی‌شود و به شبکه/گره/دیتابیسِ فروشگاه نیازی نیست."""
    checks: list[dict] = []

    def check(key: str, ok: bool, detail: str):
        checks.append({"key": key, "ok": bool(ok), "detail": detail})

    # ۱) ایده‌های آماده
    per = {c: sum(1 for i in BUILTIN_IDEAS.values() if i["category"] == c) for c in CATEGORIES}
    dirty = [k for k, i in BUILTIN_IDEAS.items() if guard.problems(" ".join(str(i[f]) for f in bank.TEXT_FIELDS))]
    check("seeds", 80 <= len(BUILTIN_IDEAS) <= 120 and min(per.values()) >= 8 and not dirty,
          f"{len(BUILTIN_IDEAS)} ایده در {len(per)} دسته؛ ایدهٔ دارای ادعای ساختگی: {len(dirty)}")

    # ۲) جای‌گیرها از پروفایلِ چغر
    store = demo.stand_in()
    ctx = fill.context(store)
    filled = fill.fill_text("{فروشگاه} برای {مخاطب}", ctx)
    check("fill", "چغر" in filled and "مربی" in filled and "{" not in filled, filled)

    # ۳) مسیرِ بدونِ هوش مصنوعی (فرمول‌ها) با دلیلِ فارسی
    r = generator.generate(store, count=6, topic=demo.CHAGHER_TOPIC, facts=demo.CHAGHER_FACTS, use_ai=True, ask=_unavailable, ctx=ctx)
    bad = [i["title"] for i in r["ideas"] if guard.problems(" ".join(i[f] for f in bank.TEXT_FIELDS), " ".join(demo.CHAGHER_FACTS) + " " + demo.CHAGHER_TOPIC)]
    check("formulas_without_ai", r["via"] == "formula" and len(r["ideas"]) >= 4 and "۴۰۲" in r["message"] and not bad,
          f"via={r['via']} · {len(r['ideas'])} ایده · {r['message'][:80]}")

    # ۴) مسیرِ هوش مصنوعی با جوابِ ساختگی: ایده‌های بد دور ریخته می‌شوند
    r2 = generator.generate(store, count=4, topic=demo.CHAGHER_TOPIC, facts=demo.CHAGHER_FACTS, use_ai=True, ask=_fake_ai, ctx=ctx)
    titles = [i["title"] for i in r2["ideas"]]
    ai_titles = [i for i in r2["ideas"] if i.get("formula") == "ai"]
    check("ai_path_validated", len(ai_titles) == 2 and not any("تخفیف" in t or "hologram" in t for t in titles) and r2["ai"]["ok"],
          f"از ۴ ایدهٔ مدل {len(ai_titles)} پذیرفته شد؛ via={r2['via']}")

    # ۵) «وقتی هوش مصنوعی برگردد دوباره کار می‌کند»: بعد از شکست، همان درخواست با مدلِ سالم می‌شود via=ai/mixed
    again = generator.generate(store, count=4, topic=demo.CHAGHER_TOPIC, use_ai=True, ask=_fake_ai, ctx=ctx)
    check("ai_back_again", again["via"] in ("ai", "mixed") and r["via"] == "formula", f"قبل: {r['via']} ⇒ بعد: {again['via']}")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# ───────────────────────────── زنده (روی گره، با مدلِ متنیِ مالک)

def node_prompt() -> tuple[str, str]:
    """(prompt, system) — همان پرسشِ واقعیِ ایده‌ساز برای چغر، بدونِ هیچ قیمت یا آماری."""
    store = demo.stand_in()
    prompt = generator.build_prompt(store=store, product=None, category="", count=4, topic=demo.CHAGHER_TOPIC, instruction=demo.CHAGHER_INSTRUCTION, facts=demo.CHAGHER_FACTS,
                                    liked=[], existing_titles=[i["title"] for i in list(BUILTIN_IDEAS.values())[:12]])
    return prompt, generator.SYSTEM


def node_spec(model: str) -> dict:
    """بارِ کارِ ``ollama.generate`` برای آزمونِ پذیرشِ سرورِ پردازش."""
    prompt, system = node_prompt()
    return {"kind": "ollama.generate", "payload": {"model": model, "system": system, "prompt": prompt, "stream": False, "think": False, "format": "json",
                                                   "options": {"num_predict": 1600, "temperature": 0.4}}, "timeout_s": CHECK_TIMEOUT_S}


def parse_json(text: str):
    t = _FENCE.sub("", str(text or "").strip())
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def node_check(text: str) -> tuple[bool, str]:
    """جوابِ مدل ⇒ (قبول؟، پیامِ فارسی). قبول = دست‌کم یک ایدهٔ معتبر (قالبِ درست، بدونِ عدد/قیمت/آمار) و فارسی."""
    parsed = parse_json(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("ideas"), list):
        return False, "مدل JSON با کلیدِ «ideas» نداد."
    source = " ".join([demo.CHAGHER_TOPIC, demo.CHAGHER_INSTRUCTION, *demo.CHAGHER_FACTS, demo.CHAGHER_PROFILE["business_type"], demo.CHAGHER_PROFILE["target_audience"]])
    ideas = generator.clean_ai_ideas(parsed, category="", source=source, taken=set(), limit=8)
    raw = len(parsed["ideas"])
    if not ideas:
        return False, f"از {raw} ایدهٔ مدل هیچ‌کدام وارسی را نگذراند (قالب، ادعای ساختگی یا متنِ کوتاه)."
    letters = sum(len(_PERSIAN.findall(i["title"] + i["logline"])) for i in ideas)
    if letters < 20:
        return False, "ایده‌های مدل فارسی نیستند."
    return True, f"{len(ideas)} ایدهٔ معتبر از {raw} ایدهٔ مدل؛ نمونه: «{ideas[0]['title']}»"
