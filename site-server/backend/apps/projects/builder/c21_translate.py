# -*- coding: utf-8 -*-
"""فارسی‌کردنِ متن‌های نمونهٔ قطعه‌های 21st.dev (همه انگلیسی‌اند؛ بازبینیِ ۱۱/۱۷: «all text is English»).

دو لایه، هر دو بی‌خطر:

1. **فرهنگ‌لغتِ رابط** (``fa_text``): عبارت‌های رایجِ دکمه/منو/قیمت/پرسش («Get started» ⇒ «شروع کنید»، «Pricing» ⇒ «قیمت‌ها»، «/ mo» ⇒ «/ ماه»، «3 projects» ⇒ «۳ پروژه»).
   دقیق و بی‌AI؛ ۲۰٪ تا ۴۰٪ از متن‌های یک قطعهٔ معمولی را می‌پوشاند. نامِ برند، کد، اعداد و نمادها دست نمی‌خورند. هیچ قیمت/آمارِ ساختگی اضافه نمی‌شود: فقط ترجمه، نه محتوا.
2. **ترجمهٔ AI** (``ai_translate``، اختیاری و با دکمه): بقیهٔ متن‌های انگلیسی (حداکثر ۴۰ متن، ۳۰۰۰ نویسه) در یک درخواست به همان مسیریابِ AI ِ سایت‌ساز (Ollama روی گره ⇐ متیس) می‌روند.
   متیس بی‌اعتبار (۴۰۲) یا گره خاموش ⇒ جملهٔ فارسیِ روشن و همان ترجمهٔ فرهنگ‌لغت می‌ماند؛ وقتی AI برگشت همان دکمه کار می‌کند.

مالک همیشه می‌تواند متن را روی بوم ویرایش کند؛ هشدارِ «متن‌های این قطعه هنوز نمونه‌اند» تا وقتی متن عوض نشده می‌ماند.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_AI_TEXTS = 40
MAX_AI_CHARS = 3000

#: انگلیسی (حروفِ کوچک، بی‌نقطه‌گذاریِ انتها) ⇒ فارسی
_FA = {
    # قیمت و پلن
    "pricing": "قیمت‌ها", "plans": "پلن‌ها", "plan": "پلن", "starter": "شروع", "pro": "حرفه‌ای", "enterprise": "سازمانی", "free": "رایگان", "basic": "پایه", "premium": "ویژه",
    "popular": "محبوب", "most popular": "محبوب‌ترین", "custom": "سفارشی", "team": "تیم", "teams": "تیم‌ها", "monthly": "ماهانه", "yearly": "سالانه", "annual": "سالانه",
    "annually": "سالانه", "billed monthly": "پرداخت ماهانه", "billed yearly": "پرداخت سالانه", "/ mo": "/ ماه", "/mo": "/ ماه", "/ month": "/ ماه", "/ yr": "/ سال", "/ year": "/ سال",
    "per month": "در ماه", "per year": "در سال", "per user": "برای هر کاربر", "per seat": "برای هر کاربر", "save 20%": "۲۰٪ تخفیف", "total": "جمع کل", "subtotal": "جمع جزء",
    "unlimited projects": "پروژهٔ نامحدود", "community support": "پشتیبانی جامعه", "priority support": "پشتیبانی اولویت‌دار", "dedicated support": "پشتیبانی اختصاصی",
    "basic analytics": "تحلیلِ پایه", "advanced analytics": "تحلیلِ پیشرفته", "team collaboration": "همکاری تیمی", "custom contracts": "قراردادهای سفارشی",
    "email support": "پشتیبانی ایمیلی", "everything in free": "همهٔ امکاناتِ رایگان", "everything in pro": "همهٔ امکاناتِ حرفه‌ای", "unlimited": "نامحدود", "upgrade": "ارتقا",
    # دکمه و عمل
    "get started": "شروع کنید", "get started for free": "رایگان شروع کنید", "start free trial": "شروع دورهٔ آزمایشیِ رایگان", "start for free": "رایگان شروع کنید", "contact sales": "تماس با فروش",
    "contact us": "تماس با ما", "contact": "تماس", "contact support": "تماس با پشتیبانی", "learn more": "بیشتر بدانید", "read more": "ادامهٔ مطلب", "see more": "دیدنِ بیشتر",
    "view all": "دیدنِ همه", "view more": "دیدنِ بیشتر", "sign up": "ثبت‌نام", "sign in": "ورود", "log in": "ورود", "login": "ورود", "log out": "خروج", "logout": "خروج",
    "subscribe": "اشتراک", "notify me": "به من خبر بده", "launching soon": "به‌زودی", "coming soon": "به‌زودی", "try again": "دوباره تلاش کنید", "try it now": "همین حالا امتحان کنید",
    "try for free": "رایگان امتحان کنید", "try it free": "رایگان امتحان کنید", "buy now": "همین حالا بخرید", "add to cart": "افزودن به سبد", "checkout": "پرداخت",
    "download": "دانلود", "upload": "بارگذاری", "submit": "ارسال", "send": "ارسال", "send message": "ارسال پیام", "cancel": "انصراف", "save": "ذخیره", "edit": "ویرایش", "delete": "حذف",
    "duplicate": "تکثیر", "copy": "کپی", "copy link": "کپی پیوند", "share": "اشتراک‌گذاری", "search": "جست‌وجو", "apply": "اعمال", "confirm": "تأیید", "continue": "ادامه",
    "book now": "همین حالا رزرو کنید", "book a demo": "درخواست دمو", "request a demo": "درخواست دمو", "watch demo": "دیدنِ نمایش", "join now": "همین حالا بپیوندید",
    "join the waitlist": "به فهرستِ انتظار بپیوندید", "open": "باز", "close": "بستن", "create": "ساخت", "navigate": "پیمایش", "select": "انتخاب", "show": "نمایش", "hide": "پنهان",
    # ناوبری و صفحه
    "home": "خانه", "about": "دربارهٔ ما", "about us": "دربارهٔ ما", "features": "ویژگی‌ها", "docs": "مستندات", "documentation": "مستندات", "blog": "وبلاگ", "support": "پشتیبانی",
    "help": "راهنما", "faq": "پرسش‌های متداول", "faqs": "پرسش‌های متداول", "menu": "منو", "products": "محصولات", "product": "محصول", "services": "خدمات", "resources": "منابع",
    "company": "شرکت", "careers": "فرصت‌های شغلی", "privacy": "حریم خصوصی", "terms": "شرایط", "privacy policy": "سیاست حریم خصوصی", "terms of service": "شرایط استفاده",
    "customers": "مشتریان", "testimonials": "نظرها", "reviews": "بازخوردها", "gallery": "گالری", "portfolio": "نمونه‌کارها", "pricing plans": "پلن‌های قیمت", "newsletter": "خبرنامه",
    "follow us": "ما را دنبال کنید", "all rights reserved": "همهٔ حقوق محفوظ است", "quick links": "پیوندهای سریع", "categories": "دسته‌ها", "new": "جدید", "next": "بعدی",
    "previous": "قبلی", "back": "بازگشت", "skip": "رد کردن", "see all": "دیدنِ همه",
    # فرم
    "email": "ایمیل", "email address": "نشانی ایمیل", "name": "نام", "full name": "نام کامل", "message": "پیام", "password": "رمز عبور", "phone": "تلفن", "phone number": "شمارهٔ تلفن",
    "address": "نشانی", "city": "شهر", "subject": "موضوع", "your name": "نام شما", "your email": "ایمیل شما", "enter your email": "ایمیلتان را وارد کنید", "type a message": "پیامی بنویسید",
    # وضعیت و واحد
    "settings": "تنظیمات", "profile": "نمایه", "account": "حساب کاربری", "dashboard": "داشبورد", "overview": "نمای کلی", "status": "وضعیت", "active": "فعال", "inactive": "غیرفعال",
    "pending": "در انتظار", "completed": "انجام‌شده", "failed": "ناموفق", "success": "موفق", "error": "خطا", "warning": "هشدار", "loading": "در حال بارگذاری", "loading...": "در حال بارگذاری…",
    "today": "امروز", "yesterday": "دیروز", "tomorrow": "فردا", "day": "روز", "days": "روز", "week": "هفته", "weeks": "هفته", "month": "ماه", "year": "سال", "hour": "ساعت", "minute": "دقیقه",
    "theme": "پوسته", "light": "روشن", "dark": "تیره", "primary": "اصلی", "secondary": "ثانویه", "destructive": "هشدار", "default": "پیش‌فرض", "compact": "فشرده", "button": "دکمه",
    "input": "ورودی", "output": "خروجی", "owners only": "فقط مالکان", "popover": "پنجرهٔ شناور", "open popover": "بازکردنِ پنجرهٔ شناور", "thinking": "در حال فکر کردن",
    # پرسش‌های رایج
    "what is your return policy?": "سیاستِ بازگشتِ کالا چیست؟", "how long does shipping take?": "ارسال چقدر طول می‌کشد؟", "is it accessible?": "آیا دسترس‌پذیر است؟",
    "how do i get started?": "چطور شروع کنم؟", "can i cancel anytime?": "آیا هر وقت بخواهم می‌توانم لغو کنم؟", "do you offer refunds?": "آیا بازپرداخت دارید؟",
    "how does it work?": "چطور کار می‌کند؟", "who is this for?": "برای چه کسانی است؟", "what's included?": "چه چیزهایی شامل است؟", "is there a free trial?": "آیا دورهٔ آزمایشیِ رایگان دارید؟",
    "frequently asked questions": "پرسش‌های متداول", "how it works": "چطور کار می‌کند", "why choose us": "چرا ما؟", "our features": "ویژگی‌های ما", "our services": "خدماتِ ما",
    "what our customers say": "مشتریانِ ما چه می‌گویند", "get in touch": "با ما در تماس باشید", "let's talk": "صحبت کنیم", "our team": "تیمِ ما", "meet the team": "با تیم آشنا شوید",
}
_NUM_WORD = {"project": "پروژه", "projects": "پروژه", "user": "کاربر", "users": "کاربر", "seat": "کاربر", "seats": "کاربر", "member": "عضو", "members": "عضو", "day": "روز", "days": "روز",
             "week": "هفته", "weeks": "هفته", "month": "ماه", "months": "ماه", "year": "سال", "years": "سال", "gb": "گیگابایت", "mb": "مگابایت", "item": "مورد", "items": "مورد",
             "task": "کار", "tasks": "کار", "review": "نظر", "reviews": "نظر", "step": "گام", "steps": "گام"}
_RE_NUM_WORD = re.compile(r"^\s*(\d[\d,.]*)\s+([A-Za-z]+)\s*$")
_RE_LATIN = re.compile(r"[A-Za-z]{3,}")
_RE_CODEISH = re.compile(r"https?:|\w+@\w+\.|\.(?:tsx?|jsx?|css|json|png|jpe?g|svg)\b|^[\w.-]+/[\w./-]+$")      # نشانی، ایمیل، نامِ فایل، مسیر: ترجمه نمی‌شود
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower().rstrip(".!:؛").replace("’", "'")


def fa_text(text: str) -> str | None:
    """یک متنِ انگلیسی ⇒ فارسی از فرهنگ‌لغت؛ نبود ⇒ None (متن دست نمی‌خورد). «3 projects» ⇒ «۳ پروژه»."""
    k = _key(text)
    if not k:
        return None
    if k in _FA:
        out = _FA[k]
    else:
        m = _RE_NUM_WORD.match(text or "")
        w = _NUM_WORD.get(m.group(2).lower()) if m else None
        if not w:
            return None
        out = "%s %s" % (m.group(1).translate(_FA_DIGITS), w)
    return out


def apply_dictionary(texts: list[str]) -> tuple[list[str], int]:
    """⇒ (متن‌های تازه، چند تا فارسی شد). متنی که در فرهنگ‌لغت نیست همان می‌ماند."""
    out, n = [], 0
    for t in texts or []:
        fa = fa_text(str(t))
        if fa is None:
            out.append(t)
        else:
            out.append(fa)
            n += 1
    return out, n


def needs_ai(texts: list[str]) -> list[int]:
    """اندیسِ متن‌هایی که هنوز انگلیسی‌اند (سه حرفِ لاتین یا بیشتر) و ارزشِ ترجمه دارند."""
    return [i for i, t in enumerate(texts or []) if _RE_LATIN.search(str(t)) and not _RE_CODEISH.search(str(t))]


SYSTEM_FA = ("تو مترجمِ متنِ رابطِ کاربری هستی. هر متنِ انگلیسیِ ورودی را به فارسیِ روان و کوتاه ترجمه کن. نام برند، نامِ فنی، کد، اعداد، علامت‌ها و ایموجی را همان بگذار. "
             "چیزی اضافه نکن (قیمت، آمار، ادعا). خروجی فقط JSON به شکلِ {\"t\": [\"...\", ...]} با همان تعداد و همان ترتیب باشد.")


def ai_translate(texts: list[str], *, complete=None) -> tuple[list[str], dict]:
    """متن‌های انگلیسیِ مانده را با AI فارسی می‌کند. ⇒ (متن‌های تازه، {ok, translated, message}). هر شکستی ⇒ همان متن‌ها + پیامِ فارسی (هرگز استثنا نمی‌دهد).

    complete(system, user_json) ⇒ متنِ خام؛ پیش‌فرض ``ai_engine.providers.get_provider().complete`` (همان مسیرِ سایت‌ساز)."""
    idx = needs_ai(texts)[:MAX_AI_TEXTS]
    total = 0
    pick = []
    for i in idx:
        total += len(str(texts[i]))
        if total > MAX_AI_CHARS:
            break
        pick.append(i)
    if not pick:
        return list(texts), {"ok": True, "translated": 0, "message": "متنِ انگلیسیِ دیگری برای ترجمه نمانده است."}
    payload = {"task": "translate-ui-strings-to-persian", "t": [str(texts[i])[:300] for i in pick]}
    try:
        if complete is None:
            from django.conf import settings
            if getattr(settings, "IS_TEST", False):                     # زیرِ آزمون هرگز AI ِ واقعی صدا زده نمی‌شود
                return list(texts), {"ok": False, "translated": 0, "message": "ترجمهٔ هوش مصنوعی زیرِ آزمون اجرا نمی‌شود."}
            from apps.ai_engine.providers import get_provider
            complete = get_provider().complete
        raw = complete(SYSTEM_FA, json.dumps(payload, ensure_ascii=False))
        from apps.ai_engine.providers import extract_json
        data = extract_json(raw)
        got = data.get("t") if isinstance(data, dict) else None
        if not isinstance(got, list) or len(got) != len(pick):
            raise ValueError("پاسخِ مدل به همان تعداد نبود")
    except Exception as exc:  # noqa: BLE001 - AI «در دسترس نیست» (۴۰۲، گره خاموش، مهلت …) نباید درجِ قطعه را خراب کند
        msg = ""
        try:
            from apps.ai_engine import parking
            un = parking.unavailable_from(exc)
            msg = str(un) if un is not None else ""
        except Exception:                          # noqa: BLE001
            msg = ""
        logger.info("c21 translate: AI unavailable: %s", exc)
        return list(texts), {"ok": False, "translated": 0, "message": msg or ("ترجمهٔ هوش مصنوعی ممکن نشد: %s" % str(exc)[:160])}
    out = list(texts)
    n = 0
    for i, v in zip(pick, got):
        if isinstance(v, str) and v.strip():
            out[i] = v.strip()[:400]
            n += 1
    return out, {"ok": True, "translated": n, "message": "%d متن با هوش مصنوعی فارسی شد؛ پیش از انتشار بخوانید." % n}
