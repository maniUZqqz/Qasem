"""نمونهٔ «چغر» برای بانکِ ایده: فقط از ``docs/chagher/brand-facts-fa.md`` (شعار، سرعتِ ساختِ پیش‌نویس، لحنِ برند). هیچ قیمت و آماری ساخته نمی‌شود.

محصولِ خودِ مالک (فروشگاهِ ۳۴، اپِ مربیانِ ورزشی) آزمونِ واقعیِ کیفیتِ این ویژگی است: ایده‌ها باید برای «مربی‌های باشگاه و مربی‌های شخصی» خوانا و بی‌ادعا
باشند. ``run()`` ایده‌ها را می‌سازد و برمی‌گرداند؛ ذخیره نمی‌کند مگر ``save=True``. آزمون: ``tests_chagher``.
"""
from __future__ import annotations

from types import SimpleNamespace

from . import fill, generator

#: جمله‌های تأییدشدهٔ برند — هر کدام عیناً در docs/chagher/brand-facts-fa.md هست (آزمونِ tests_chagher این را می‌سنجد)
CHAGHER_FACTS = [
    "با چغر چغر تر شو",
    "پیش‌نویسِ برنامهٔ ورزشی و غذاییِ اختصاصیِ هر ورزشکار در کمتر از یک دقیقه",
    "تصمیمِ نهایی با مربی است",
]
#: دستورِ لحن برای هوش مصنوعی — از §۴ همان سند («لحنِ برند»): همیشه «پیش‌نویس» بگو، هرگز «جایگزینِ مربی». عمداً بدونِ واژهٔ «تضمین» نوشته شده
#: (واژه‌هایی که در متنِ کاربر باشند «ادعای ساختگی» حساب نمی‌شوند؛ نمی‌خواهیم نگهبان به‌خاطرِ همین دستور برای چغر سست شود).
CHAGHER_INSTRUCTION = ("لحن: صمیمی ولی حرفه‌ای، کوتاه و بدونِ اغراق؛ مثلِ همکارِ مربی. «پیش‌نویس» را همیشه بگو؛ تصمیمِ نهایی با مربی است. "
                       "بدونِ وعدهٔ پزشکی، بدونِ وعدهٔ نتیجه، بدونِ «جایگزینِ مربی»، بدونِ نظرِ مشتریِ ساختگی.")
#: لحنِ برند (§۴ همان سند)
CHAGHER_TONE = "صمیمی ولی حرفه‌ای، کوتاه و بدونِ اغراق؛ مثلِ همکارِ مربی"
CHAGHER_PROFILE = {
    "name": "چغر", "business_type": "نرم‌افزار و خدمات دیجیتال برای مربیان ورزشی",
    "target_audience": "مربی‌های باشگاه و مربی‌های شخصی که برای ورزشکارانشان برنامهٔ ورزشی و غذایی می‌نویسند؛ و ورزشکارانی که خودشان برنامهٔ مناسبِ محیطِ تمرین (خانه یا باشگاه) می‌خواهند.",
    "description": "", "tone": CHAGHER_TONE,
}
CHAGHER_TOPIC = "برنامهٔ ورزشی"


def stand_in(profile: dict | None = None):
    """یک «فروشگاه»ِ ذخیره‌نشده با مشخصاتِ چغر (برای آزمونِ بی‌دیتابیس و خودآزمونِ گره)."""
    p = profile or CHAGHER_PROFILE
    return SimpleNamespace(pk=0, name=p["name"], business_type=p["business_type"], target_audience=p["target_audience"], description=p.get("description", ""),
                           profile=SimpleNamespace(tone=p.get("tone", ""), brand_voice=""))


def run(store=None, *, count: int = 8, use_ai: bool = False, ask=None, save: bool = False, topic: str = CHAGHER_TOPIC, product=None) -> dict:
    """ایده‌های نمونه برای چغر. ``store=None`` ⇒ فروشگاهِ ساختگیِ بالا (بدونِ پایگاه‌داده؛ ذخیره ممکن نیست)."""
    store = store or stand_in()
    if save and not getattr(store, "pk", 0):
        raise ValueError("برای ذخیره‌کردن یک فروشگاهِ واقعی لازم است.")
    kw = dict(category="", count=count, topic=topic, instruction=CHAGHER_INSTRUCTION, facts=CHAGHER_FACTS, product=product, use_ai=use_ai, ask=ask, ctx=fill.context(store, product))
    if save:
        return generator.generate_and_save(store, **kw)
    return generator.generate(store, **kw)
