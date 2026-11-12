"""فهرستِ اولیهٔ دسته‌ها، صفحه‌ها و قابلیت‌های پنل (کلیدها با frontend/src/features/panel/registry.ts یکی‌اند).

هر بار migrate (و `manage.py panel_seed`) ردیف‌های تازه را اضافه می‌کند؛ وضعیتِ «فعال» ِ ردیف‌های موجود دست نمی‌خورد.
"""

# (key, title, staff_only, description, pages)
# pages: (key, title, path, description, features)   features: (key, title, description)
SECTIONS = [
    ("home", "خانه", False, "داشبورد و فهرستِ فروشگاه‌ها", [
        ("dashboard", "داشبورد", "/", "فهرستِ فروشگاه‌های کاربر", [
            ("dashboard.new_store", "دکمهٔ «فروشگاه جدید»", "ساختنِ فروشگاهِ تازه از داشبورد"),
        ]),
    ]),
    ("store", "فروشگاه", False, "همه‌چیزِ یک فروشگاه: محصول، برند، ایجنت، اعضا", [
        ("products", "محصولات", "/stores/:id", "فهرست و افزودنِ محصول", [
            ("products.onboarding", "کارتِ «قدم‌های بعدی»", "راهنمای گام‌به‌گامِ راه‌اندازیِ فروشگاه"),
            ("products.add", "افزودنِ محصول", "فرمِ محصولِ تازه"),
            ("products.camera", "ساخت و عکس‌برداری با دوربین", "بعد از ساختنِ محصول، زاویه‌به‌زاویه با دوربین عکس بگیر"),
            ("store.chat_button", "دکمهٔ «چت فروش (آزمایشی)»", "در سربرگِ فروشگاه"),
        ]),
        ("analytics", "آمار", "/stores/:id/analytics", "آمارِ فروشگاه", []),
        ("brand", "پروفایل برند", "/stores/:id/brand", "لحن و هویتِ برند", []),
        ("voice", "صدا و گوینده", "/stores/:id/voice", "گویندهٔ ویدیوها", []),
        ("voice_clone", "کلونِ صدا", "/stores/:id/voice/clone",
         "صدای اختصاصی از روی چند جملهٔ خوانده‌شده (فقط با رضایتِ صاحبِ صدا)", []),
        ("agent", "ایجنت فروش", "/stores/:id/agent", "قوانینِ ایجنتِ فروش", []),
        ("connections", "اتصال شبکه‌ها", "/stores/:id/connections", "اتصال به شبکه‌های اجتماعی", []),
        ("team", "اعضا و دسترسی", "/stores/:id/team", "اعضای فروشگاه", []),
        ("data", "سیاست داده", "/stores/:id/data", "محلی یا بیرونی بودنِ پردازش", []),
    ]),
    ("market", "بازار", False, "رقبا، فرصت‌ها و ترندها", [
        ("competitors", "رقبا", "/stores/:id/competitors", "", []),
        ("opportunities", "فرصت‌های فروش", "/stores/:id/opportunities", "", []),
        ("trends", "ترندها", "/stores/:id/trends", "", []),
    ]),
    ("sales", "فروش و پشتیبانی", False, "سفارش، رسید، تیکت، پیام، چت و تماس", [
        ("sales", "نمای فروش", "/stores/:id/sales", "", []),
        ("orders", "سفارش‌ها", "/stores/:id/sales/orders", "", []),
        ("receipts", "رسیدها", "/stores/:id/sales/receipts", "", []),
        ("tickets", "تیکت‌ها", "/stores/:id/sales/tickets", "", []),
        ("inbox", "صندوق پیام", "/stores/:id/inbox", "", []),
        ("chat", "چت آزمایشی", "/stores/:id/chat", "گفت‌وگوی آزمایشی با ایجنت", []),
        ("outreach", "بازاریابی تلفنی", "/stores/:id/outreach", "", []),
    ]),
    ("content", "محتوا", False, "تولیدِ محتوا، کمپین‌ها و انتشار", [
        ("studio", "تولید محتوا", "/stores/:id/studio", "استودیوی محتوا", [
            ("studio.video", "زبانهٔ ویدیو", ""),
            ("studio.image", "زبانهٔ عکس و پوستر", ""),
            ("studio.caption", "زبانهٔ کپشن", ""),
            ("studio.advanced", "زبانهٔ پیشرفته", ""),
            ("studio.automation", "زبانهٔ اتوماسیون و زمان‌بندی", ""),
        ]),
        ("campaigns", "کمپین‌ها", "/stores/:id/campaigns", "", []),
        ("calendar", "تقویم انتشار", "/stores/:id/campaigns/calendar", "", []),
        ("publish_queue", "صف انتشار", "/stores/:id/campaigns/queue", "", []),
        ("performance", "چه چیزی جواب داد", "/stores/:id/campaigns/performance", "", []),
        ("production_queue", "صف تولید", "/stores/:id/queue", "", []),
        ("editor", "ادیتور ویدیو", "/stores/:id/editor", "", []),
        ("photo_editor", "ادیتور عکس", "/stores/:id/photo-editor",
         "عکس‌ها را خودکار برای اینستاگرام، استوری و فروشگاه آماده می‌کند (برش، نور و رنگ، پس‌زمینه، متن، لوگو)", []),
        ("guided_shoot", "فیلم‌برداریِ هدایت‌شده", "/stores/:id/shoot",
         "محصول را تحلیل می‌کند، پیش و حینِ ضبط می‌گوید از چه زاویه‌ای و چطور عکس و فیلم بگیری، بعد خودکار "
         "تدوین می‌کند و ویدیو و پوسترِ تبلیغاتی می‌سازد", [
            ("shoot.live", "حالتِ دوربینِ زنده", "راهنما روی تصویرِ دوربین و حینِ ضبط (فقط روی https یا localhost)"),
            ("shoot.video", "ویدیوی تبلیغاتی", "تدوینِ خودکارِ برداشت‌ها با متن، موسیقی و گوینده"),
            ("shoot.poster", "پوسترِ تبلیغاتی", "پوستر با متن، قیمت، دعوت به خرید و لوگو"),
        ]),
        ("multiangle", "چندزاویه", "/stores/:id/multiangle",
         "از یک فیلم که با یک دوربین گرفته‌ای چند زاویه می‌سازد (نمای باز، متوسط، نزدیک، دو نفره) با حرکتِ طبیعیِ دوربین و برشِ خودکار؛ و از یک نما حرکتِ دوربینِ ۲٫۵بعدی (به جلو، کنار، جرثقیل، چرخش) می‌سازد", [
            ("multiangle.virtual", "زاویه‌های مجازی", "چند زاویه و مولتی‌کمِ خودکار از یک فیلم"),
            ("multiangle.move", "حرکتِ دوربینِ ۲٫۵بعدی", "پارالاکس با نقشهٔ عمق از یک عکس یا فیلم"),
        ]),
        ("piece_regen", "بازسازیِ یک تکه", "/stores/:id/regen",
         "یک بازه از وسطِ هر ویدیو دوباره ساخته و بی‌درز جایگزین می‌شود (نسخه‌ها، قبل/بعد، نمرهٔ درز)", []),
    ]),
    ("audio", "صدا", False, "گفتار، کلونِ صدا، صدای محیط، موسیقیِ زمینه و کتابخانهٔ صداها", [
        ("audio_speech", "گفتار", "/stores/:id/audio", "متن به گفتار با صداهای آماده یا صدای کلون‌شده", []),
        ("audio_clone", "کلونِ صدا", "/stores/:id/audio/clone", "صدای اختصاصی، فقط با رضایتِ صاحبِ صدا", []),
        ("audio_sfx", "صدای محیط و افکت", "/stores/:id/audio/sfx", "صدای محیط و افکت از روی توضیح", []),
        ("audio_music", "موسیقیِ زمینه", "/stores/:id/audio/music", "موسیقیِ بی‌کلام برای زیرِ ویدیو", []),
        ("audio_library", "کتابخانهٔ صداها", "/stores/:id/audio/library", "همهٔ صداهای ساخته‌شدهٔ فروشگاه", []),
    ]),
    ("settings", "تنظیمات", False, "پلن و کلیدهای API", [
        ("plan", "پلن و مصرف", "/stores/:id/plan", "", []),
        ("api_keys", "کلیدهای API", "/stores/:id/api", "", []),
    ]),
    ("product", "صفحهٔ محصول", False, "زبانه‌های صفحهٔ هر محصول", [
        ("product", "مشخصات", "/products/:id", "", [
            ("product.camera", "عکس‌برداری با دوربین", "عکس‌های محصول زاویه‌به‌زاویه با راهنما و بررسیِ کیفیت"),
        ]),
        ("product_intelligence", "هوش محصول", "/products/:id/intelligence", "", []),
        ("product_market", "تحلیل بازار", "/products/:id/market", "", []),
        ("product_images", "استودیو تصویر", "/products/:id/images", "", []),
        ("product_captions", "کپشن", "/products/:id/captions", "", []),
        ("product_video", "استودیو ویدیو", "/products/:id/video", "", []),
        ("product_advanced", "حالت پیشرفته", "/products/:id/advanced", "", []),
    ]),
    ("growth", "جذب مشتری", True, "پیدا کردنِ مشتری برای آپ‌مارکت: کشف، لیدها، استخراجِ اطلاعاتِ تماس و پیام‌رسانی", [
        ("growth_dashboard", "داشبورد جذب مشتری", "/growth", "اعدادِ واقعیِ لیدها، ورودی‌ها و پیام‌ها", []),
        ("growth_discovery", "کشف مشتری", "/growth/discovery", "ثبتِ دستی (آدرس سایت، پیج اینستاگرام، نام) و ورود از فایل CSV", []),
        ("growth_leads", "دیتابیس لیدها", "/growth/leads", "جست‌وجو، فیلتر، ویرایش، برچسب و خروجی CSV", []),
        ("growth_lead", "جزئیات لید", "/growth/leads/:id", "اطلاعات، راه‌های تماس، یادداشت و تاریخچهٔ یک لید", []),
        ("growth_outreach", "پیام‌رسانی", "/growth/outreach", "کمپین‌های پیام، تأییدِ دسته‌ای و صفِ دستی", []),
        ("growth_templates", "قالب‌های پیام", "/growth/templates", "متنِ پیام‌ها با جاگذارها", []),
        ("growth_channels", "کانال‌های ارسال", "/growth/channels", "کدام راهِ تماس فعال باشد، اولویت، سقف و فاصله؛ ایمیل، پیامک، پیام‌رسان‌ها و تماس", []),
        ("growth_knowledge", "دانشِ محصول", "/growth/knowledge", "آنچه NM دارد و می‌تواند؛ پایهٔ متنِ پیام‌ها و نویسندهٔ هوشمند", []),
        ("growth_suppression", "فهرست «تماس نگیر»", "/growth/do-not-contact", "کسانی که نباید پیام بگیرند", []),
        ("growth_settings", "تنظیماتِ جذب مشتری", "/growth/settings", "هویتِ فرستنده، سقفِ ارسال و توقفِ اضطراری", []),
    ]),
    ("admin", "ادمین", True, "ابزارهای کارکنان", [
        ("crm", "CRM", "/admin", "", []),
        ("marketing_report", "گزارش بازاریابی", "/admin/marketing", "", []),
        ("rewards", "پاداش‌ها", "/admin/rewards", "", []),
        ("providers", "موتورهای AI", "/admin/providers", "", []),
    ]),
    ("tools", "ابزارها", True, "سایت‌ساز، ویدیوی سه‌بعدی، سرورهای پردازش", [
        ("studio_builder", "سایت‌ساز", "/tools/studio", "", []),
        ("video3d", "ویدیوی سه‌بعدی", "/tools/3d", "", []),
        ("compute", "سرورهای پردازش", "/tools/compute", "", []),
        ("compute_queue", "صفِ پردازش", "/tools/compute/queue",
         "کارهای منتظر، در حال اجرا و تمام‌شدهٔ سرورهای پردازش؛ با لغو و تلاشِ دوباره", []),
        ("compute_report", "گزارشِ سرورهای پردازش", "/tools/compute/report",
         "وضعیتِ روشن/خاموش، منابع، آمارِ کارها، خطاها و دانلودها؛ با خروجیِ CSV", []),
        ("mobile", "دستگاه‌های موبایل", "/tools/mobile", "گوشی‌های جفت‌شده، پیامک، تماس، قیمتِ پایین، شناساییِ تماس‌گیرنده", []),
        ("django_admin", "ادمینِ جنگو", "/admin/", "", []),
    ]),
]


def seed() -> dict:
    """ردیف‌های تازه را می‌سازد؛ هرچه هست (با وضعیتِ فعال/غیرفعالش) دست نمی‌خورد."""
    from .models import PanelFeature, PanelPage, PanelSection

    made = {"sections": 0, "pages": 0, "features": 0}
    for s_order, (s_key, s_title, s_staff, s_desc, pages) in enumerate(SECTIONS, 1):
        section, created = PanelSection.objects.get_or_create(
            key=s_key, defaults={"title": s_title, "order": s_order * 10, "staff_only": s_staff, "description": s_desc})
        made["sections"] += int(created)
        for p_order, (p_key, p_title, p_path, p_desc, features) in enumerate(pages, 1):
            page, created = PanelPage.objects.get_or_create(
                key=p_key, defaults={"section": section, "title": p_title, "path": p_path, "order": p_order * 10,
                                     "staff_only": s_staff, "description": p_desc})
            made["pages"] += int(created)
            for f_key, f_title, f_desc in features:
                _, created = PanelFeature.objects.get_or_create(
                    key=f_key, defaults={"page": page, "title": f_title, "description": f_desc})
                made["features"] += int(created)
    return made
