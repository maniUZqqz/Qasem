"""«چغر» — بررسیِ واقعیِ کیفیتِ استودیوی طراحی با محصولِ خودِ مالک: یک کاتالوگ، یک ارائهٔ کوتاه و یک طرحِ UI صفحهٔ فرود که به سایت‌ساز (پیش‌نویس) می‌رود.

⚠ فقط پیش‌نویس است؛ هیچ‌چیز منتشر یا به بیرون فرستاده نمی‌شود. همهٔ جمله‌ها و عددها از ``docs/chagher/brand-facts-fa.md`` (بخش‌های ۲، ۳ و ۴) و محصولاتِ ثبت‌شدهٔ
فروشگاهِ چغر می‌آید؛ آمارِ تأییدنشده («۹۸٪ رضایت»)، نظرِ مشتریِ ساختگی و وعدهٔ پزشکی عمداً نیست. قیمت‌ها همان‌طور که در فروشگاه ثبت شده نوشته می‌شود
(واحدِ «تومان» را مالک تأیید کند؛ بخشِ ۶ سندِ واقعیت‌ها).
"""
from __future__ import annotations

from . import brand, catalog_doc, deck_doc, ui_doc
from .models import DesignDoc

SLUG = "با چغر چغر تر شو"
SOURCE_DOC = "docs/chagher/brand-facts-fa.md"
LANDING_SLUG = "chagher-ui-design"

#: «چهار قدم» — بخشِ ۲ سندِ واقعیت‌ها
STEPS = [
    {"title": "ثبت‌نام", "text": "کمتر از یک دقیقه؛ شروع رایگان و بدونِ کارتِ اعتباری."},
    {"title": "خریدِ توکن", "text": "پرداختِ آنلاین از درگاه‌های معتبر."},
    {"title": "اطلاعاتِ مجموعه", "text": "تجهیزات، غذاها و دستورالعملِ شخصیِ خودت را وارد کن."},
    {"title": "تولیدِ برنامه", "text": "پیش‌نویس را بگیر، ویرایش کن و تحویل بده."},
]
#: آمارِ قابلِ‌اثبات (با منبع) — بخشِ ۲ و ۳
FACTS = [
    {"value": "۱٬۳۰۰+", "label": "حرکتِ فارسی با گیف و عکس در کتابخانه", "source": f"{SOURCE_DOC} — بخش ۲ (از دیتابیسِ خودِ چغر)"},
    {"value": "کمتر از یک دقیقه", "label": "زمانِ پیش‌نویسِ برنامهٔ ورزشی و غذایی", "source": f"{SOURCE_DOC} — بخش ۲ و ۴"},
    {"value": "۵۰ توکن", "label": "هزینهٔ توکنیِ برنامهٔ کاملِ هوش مصنوعی", "source": f"{SOURCE_DOC} — بخش ۳"},
]
CTA = {"title": SLUG, "text": "ثبت‌نام کمتر از یک دقیقه است و شروع رایگان؛ بدونِ نیاز به کارتِ اعتباری.", "button": "panel.chagher.ir", "link": "https://panel.chagher.ir"}
#: برای آزمونِ خودکارِ گره (بی‌دیتابیس): همان محصول‌های ثبت‌شده در فروشگاهِ چغر
ITEMS = [
    {"id": 17, "name": "برنامهٔ ورزشی + غذایی با هوش مصنوعی", "short": "پیش‌نویسِ کاملِ برنامهٔ ورزشی و غذاییِ اختصاصیِ یک ورزشکار در کمتر از یک دقیقه — ۵۰ توکن",
     "desc": "", "price": 600000.0, "currency": "IRT", "images": [], "attrs": [], "tags": [], "category": ""},
    {"id": 18, "name": "برنامهٔ تکی با هوش مصنوعی (فقط ورزشی یا فقط غذایی)", "short": "فقط برنامهٔ ورزشی یا فقط برنامهٔ غذایی — ۲۵ توکن", "desc": "", "price": 300000.0, "currency": "IRT",
     "images": [], "attrs": [], "tags": [], "category": ""},
    {"id": 19, "name": "برنامه‌سازِ دستیِ چغر (بدونِ هوش مصنوعی)", "short": "مربی خودش جلسه‌ها و حرکت‌ها را می‌چیند و PDFِ برندشده می‌گیرد — فعلاً بدونِ هزینهٔ توکن", "desc": "",
     "price": 0.0, "currency": "IRT", "images": [], "attrs": [], "tags": [], "category": ""},
]
#: فقط نشانی‌هایی که در سندِ واقعیت‌ها (بخش ۱) تأییدشده است؛ نامِ کاربریِ شبکه‌ها نامعلوم است ⇒ نیامده
CONTACTS = [{"label": "سایت", "value": "https://chagher.ir", "kind": "website"}, {"label": "پنل", "value": "https://panel.chagher.ir", "kind": "website"}]
ABOUT = ("چغر دستیار هوش مصنوعیِ مربی‌هاست: برنامهٔ ورزشی و غذاییِ اختصاصیِ هر ورزشکار را در کمتر از یک دقیقه پیش‌نویس می‌کند تا وقتِ مربی صرفِ مربیگری شود، نه نوشتنِ برنامه.\n"
         "هدفش جایگزین‌کردنِ مربی نیست؛ برداشتنِ کارِ تکراری و وقت‌گیرِ نوشتنِ برنامه از دوشِ اوست.")


def is_chagher(store) -> bool:
    return "چغر" in (store.name or "")


def _find(items: list[dict], needle: str) -> int | None:
    for p in items:
        if needle in p["name"]:
            return p["id"]
    return None


def _landing_blocks() -> list[dict]:
    from apps.projects.builder import chagher_draft

    nav, page, foot = chagher_draft.blocks()
    return nav + page + foot


def ensure_drafts(store, user=None, *, send_to_site: bool = True, ask=None) -> dict:
    """سه پیش‌نویسِ چغر را می‌سازد (اگر از قبل هست همان را برمی‌گرداند — هیچ‌چیز بازنویسی نمی‌شود). ⇒ {catalog، deck، ui، site}."""
    from . import services

    out: dict = {}
    existing = {d.meta.get("sample"): d for d in DesignDoc.objects.filter(store=store, source=DesignDoc.Source.SAMPLE)}

    def make(key, kind, title, opts):
        if key in existing:
            return existing[key], False
        doc = services.create_doc(store, user, kind, title=title, options={**opts, "sample": True}, ask=ask)
        doc.meta = {**(doc.meta or {}), "sample": key, "source_doc": SOURCE_DOC}
        doc.save(update_fields=["meta"])
        return doc, True

    from . import products as prod

    items = prod.snapshot(store)
    flagship = _find(items, "ورزشی + غذایی")
    single = _find(items, "تکی")
    featured = [i for i in (flagship, single) if i]
    cat, c1 = make("chagher-catalog", "catalog", "کاتالوگِ چغر (پیش‌نویس)", {
        "settings": {"zero_price_label": "فعلاً بدونِ هزینه", "subtitle": "کاتالوگِ بسته‌ها و ابزارها", "tagline": SLUG, "heading_font": "vazirmatn", "body_font": "vazirmatn", "digits": "fa"},
        "featured": featured[:1], "about": [ln for ln in ABOUT.split("\n")], "extra_pages": [{"type": "steps", "title": "چهار قدم تا اولین برنامه", "kicker": "چطور شروع کنیم", "steps": STEPS}],
        "back_text": "پیش‌نویسِ برنامه را چغر می‌سازد و تصمیمِ نهایی همیشه با مربی است.", "layout": "mix", "back_contacts": CONTACTS})
    deck, c2 = make("chagher-deck", "deck", "ارائهٔ کوتاهِ چغر (پیش‌نویس)", {
        "settings": {"template": "bold", "heading_font": "vazirmatn", "body_font": "vazirmatn", "zero_price_label": "فعلاً بدونِ هزینه"},
        "brief": "معرفیِ چغر به مربی‌های باشگاه: چه کاری می‌کند، بسته‌ها و چهار قدمِ شروع.", "featured": featured, "products_count": 2, "steps": STEPS, "steps_title": "چهار قدم", "facts": FACTS, "cta": CTA, "use_ai": False})
    ui, c3 = make("chagher-ui", "ui", "طرحِ صفحهٔ فرودِ چغر (UI/UX)", {
        "settings": {"style": "bento-grid", "brand_color": "#126f85", "font_head": "vazirmatn", "font_body": "vazirmatn", "menu": ["خانه", "امکانات", "چهار قدم", "پرسش‌ها"]},
        "devices": ["desktop", "tablet", "phone"], "template": "landing"})
    if c3:
        blocks = _landing_blocks()
        ui.data = ui_doc.new_doc(services.store_info(store, ui.data["settings"]), settings=ui.data["settings"], devices=("desktop", "tablet", "phone"), blocks=blocks, name="صفحهٔ فرودِ چغر")
        ui.rev += 1
        ui.save(update_fields=["data", "rev", "updated_at"])
    out.update({"catalog": cat.pk, "deck": deck.pk, "ui": ui.pk, "created": {"catalog": c1, "deck": c2, "ui": c3}})
    if send_to_site and not (ui.meta or {}).get("site"):
        from . import bridges

        try:
            site = bridges.create_site(ui, user, {"name": "چغر — طرحِ UI (از استودیوی طراحی)", "slug": LANDING_SLUG})
            out["site"] = site
        except Exception as exc:  # noqa: BLE001 — بدونِ سایت‌ساز هم بقیه ساخته شده است
            out["site_error"] = str(exc)
    elif (ui.meta or {}).get("site"):
        out["site"] = ui.meta["site"]
    return out


def info_offline():
    """StoreInfo ِ چغر بی‌دیتابیس (برای آزمونِ خودکارِ گره)."""
    kit = brand.kit(None, {"colors": ["#126f85", "#163f75", "#dbe6ff", "#f7faff", "#1b2b45"], "heading_font": "vazirmatn", "body_font": "vazirmatn"})
    return catalog_doc.StoreInfo(name="چغر", kit=kit, contacts=[{"label": "پنل", "value": "panel.chagher.ir", "kind": "website"}], has_logo=False,
                                 persona={"about": ABOUT, "audience": "مربی‌های باشگاه و مربی‌های شخصی", "tone": "صمیمی ولی حرفه‌ای، کوتاه، بدون اغراق"})


__all__ = ["ensure_drafts", "is_chagher", "STEPS", "FACTS", "CTA", "ITEMS", "info_offline"]
