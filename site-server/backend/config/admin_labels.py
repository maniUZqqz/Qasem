# -*- coding: utf-8 -*-
"""واژه‌نامه‌ی فارسیِ نام فیلدها.

چرا یک فایل، و نه `verbose_name=` کنار تک‌تک فیلدها
====================================================

۵۱۲ برچسب فیلدِ انگلیسی مانده بود. نوشتنشان کنار خود فیلد
کارِ قراردادیِ جنگوست و اگر تعدادشان ده تا بود همان را می‌کردیم؛ در این
مقیاس دو مشکل دارد:

  ۱. ۵۱۲ ویرایش در ۱۲ فایل مدل، و یک مهاجرتِ `AlterField` به ازای هرکدام
     — برای چیزی که یک بایت از دیتابیس را عوض نمی‌کند.
  ۲. مهم‌تر: `created_at` در چهل مدل تکرار شده. چهل بار نوشتن «زمان ساخت»
     یعنی چهل جا که می‌توانند با هم فرق کنند، و بعد از مدتی می‌کنند.

یک جدول واحد، هم کوتاه‌تر است و هم قابل بازبینی: می‌شود یک‌بار نگاهش کرد
و دید چه چیزی ترجمه نشده. `report()` پایین همین فایل دقیقاً همین را
می‌گوید.

ترتیب اولویت: `MODEL_FIELDS` بر `FIELDS` می‌چربد، و هر فیلدی که خودش در
مدل `verbose_name` فارسی دارد اصلاً دست نمی‌خورد — یعنی هر جا کسی عمداً
چیزی نوشته، همان می‌ماند.
"""
import re

PERSIAN = re.compile(r"[\u0600-\u06FF]")

# ---------------------------------------------------------------- فیلدهای عمومی
# اسم‌هایی که در چند مدل تکرار می‌شوند و همه‌جا یک معنی دارند.
FIELDS = {
    "id": "شناسه",
    "created_at": "زمان ساخت",
    "updated_at": "آخرین تغییر",
    "store": "فروشگاه",
    "product": "محصول",
    "customer": "مشتری",
    "conversation": "گفتگو",
    "campaign": "کمپین",
    "job": "کار",
    "owner": "مالک",
    "actor": "انجام‌دهنده",
    "payment": "پرداخت",
    "name": "نام",
    "title": "عنوان",
    "slug": "نشانی یکتا",
    "description": "توضیح",
    "short_description": "توضیح کوتاه",
    "summary": "خلاصه",
    "body": "متن",
    "order": "ترتیب",
    "sort_order": "ترتیب نمایش",
    "status": "وضعیت",
    "state": "وضعیت",
    "stage": "مرحله",
    "kind": "نوع",
    "type": "نوع",
    "category": "دسته",
    "parent": "والد",
    "tags": "برچسب‌ها",
    "published": "منتشرشده",
    "featured": "شاخص",
    "is_active": "فعال",
    "is_public": "عمومی",
    "is_read": "خوانده‌شده",
    "is_available": "موجود برای فروش",
    "error": "خطا",
    "last_error": "آخرین خطا",
    "context": "زمینه",
    "result": "نتیجه",
    "payload": "بسته‌ی ارسالی",
    "response": "پاسخ",
    "attempts": "تعداد تلاش",
    "attempt": "شماره‌ی تلاش",
    "phone": "تلفن",
    "email": "ایمیل",
    "address": "نشانی",
    "link": "پیوند",
    "icon": "آیکن",
    "image": "تصویر",
    "photo": "عکس",
    "cover": "تصویر روی جلد",
    "file": "فایل",
    "video": "ویدیو",
    "audio": "فایل صدا",
    "music": "موسیقی",
    "role": "سِمَت",
    "business": "کسب‌وکار",
    "industry": "صنف",
    "source_request": "درخواست منبع",
    "external_id": "شناسه‌ی بیرونی",
    "channel": "کانال",
    "session": "نشست",
    "path": "مسیر",
    "props": "ویژگی‌ها",
    "lead": "جمله‌ی آغازین",
    "cta": "دعوت به اقدام",
    "concept": "ایده‌ی کلی",
    "caption": "کپشن",
    "poster": "پوستر",
    "price": "قیمت",
    "total": "جمع کل",
    "quantity": "تعداد",
    "detail": "جزئیات",
    "metric": "سنجه",
    "reference": "کد پیگیری",
    "provider": "درگاه",
    "token": "توکن",
    "preview": "پیش‌نمایش",
    "plan": "پلن",
    "subscription": "اشتراک",
    "prospect": "سرنخ فروش",
    "objective": "هدف محتوا",
    "objections": "اعتراض‌های احتمالی",
    "target_audience": "مخاطب هدف",
    "metadata": "داده‌ی همراه",
    "subject": "موضوع",
    "website": "وب‌سایت",
    "note": "یادداشت",
    "notes": "یادداشت",
    "platform": "پلتفرم",
    "published_at": "زمان انتشار",
    "period_start": "شروع دوره",
    "priority": "اولویت",
    "mode": "حالت",
    "logo": "لوگو",
    "locale": "زبان",
    "referrer": "صفحه‌ی ارجاع‌دهنده",
    "utm": "پارامترهای UTM",
}

# ---------------------------------------------------------------- وابسته به مدل
# اسم‌هایی که معنیشان به مدل بستگی دارد، یا فقط یک‌جا هستند.
MODEL_FIELDS = {
    "stores.Store": {
        "business_type": "نوع کسب‌وکار", "target_audience": "مخاطب هدف",
        "contact": "راه‌های تماس", "logo": "لوگو", "colors": "رنگ‌های برند",
        "social_links": "شبکه‌های اجتماعی",
    },
    "products.Product": {
        "sku": "کد کالا", "brand": "برند", "compare_at_price": "قیمت پیش از تخفیف",
        "cost_price": "قیمت تمام‌شده", "currency": "واحد پول",
        "stock_quantity": "موجودی", "stock_status": "وضعیت موجودی",
        "shipping_info": "اطلاعات ارسال", "marketing_notes": "یادداشت‌های بازاریابی",
    },
    "jobs.Job": {
        "progress_step": "گام فعلی", "total_steps": "کل گام‌ها",
        "current_step_label": "شرح گام فعلی", "retry_count": "دفعات تلاش مجدد",
        "celery_task_id": "شناسه‌ی تسک", "mode": "حالت اجرا",
        "cancel_requested": "درخواست لغو",
    },
    "ai.AIRequest": {
        "task_type": "نوع وظیفه", "model": "مدل", "latency_ms": "زمان پاسخ (میلی‌ثانیه)",
        "prompt_id": "شناسه‌ی پرامپت", "prompt_version": "نسخه‌ی پرامپت",
    },
    "ai.ModelProvider": {
        "capability": "قابلیت", "base_url": "آدرس سرویس", "api_key": "کلید API",
        "model_name": "نام مدل", "options": "تنظیمات", "timeout_s": "مهلت (ثانیه)",
        "is_healthy": "سالم", "checked_at": "زمان آخرین بررسی",
    },
    "ai.ProductIntelligence": {
        "positioning": "جایگاه محصول", "recommended_tone": "لحن پیشنهادی",
        "selling_points": "نقاط فروش", "weaknesses": "نقاط ضعف",
        "use_cases": "موارد استفاده", "marketing_angles": "زاویه‌های تبلیغاتی",
        "content_ideas": "ایده‌های محتوا", "visual_analysis": "تحلیل تصویری",
    },
    "ai.MarketResearch": {
        "research_inputs": "ورودی‌های پژوهش", "observations": "مشاهده‌ها",
        "conclusions": "نتیجه‌گیری‌ها", "web_results": "نتایج وب", "confidence": "میزان اطمینان",
    },
    "ai.StoreAIPolicy": {
        "acknowledged_at": "زمان تأیید", "acknowledged_by": "تأییدکننده",
    },
    "content.Caption": {
        "platform": "پلتفرم", "tone": "لحن", "short_text": "متن کوتاه",
        "medium_text": "متن متوسط", "long_text": "متن بلند", "hashtags": "هشتگ‌ها",
        "about_image": "درباره‌ی تصویر", "about_video": "درباره‌ی ویدیو",
    },
    "content.GeneratedImage": {
        "instructions": "دستور کاربر", "prompt_en": "پرامپت انگلیسی",
        "negative_en": "پرامپت منفی", "style": "سبک", "source_image": "تصویر مبدأ",
        "workflow_version": "نسخه‌ی ورک‌فلو",
    },
    "content.VideoScript": {
        "raw": "خروجی خام", "total_duration": "مدت کل (ثانیه)",
        "final_video": "ویدیوی نهایی", "final_video_voiced": "ویدیوی نهایی با صدا",
        "final_video_music": "ویدیوی نهایی با موسیقی", "final_video_real": "ویدیوی نهایی واقعی",
        "voice_audio": "فایل گویندگی", "narration_language": "زبان گویندگی",
        "subtitles": "فایل زیرنویس", "subtitles_enabled": "زیرنویس فعال",
        "subtitles_burned": "زیرنویس سوخته روی ویدیو",
        "music_source": "منبع موسیقی", "music_licence": "مجوز موسیقی",
        "music_attribution": "اعتبار موسیقی", "music_level_db": "بلندی موسیقی (دسیبل)",
    },
    "customers.Conversation": {
        "assigned_to": "واگذارشده به", "last_customer_at": "آخرین پیام مشتری",
    },
    "customers.Notification": {"read_at": "زمان خواندن"},
    "customers.SupportTicket": {
        "priority": "اولویت", "resolution_note": "یادداشت حل مشکل",
        "resolved_at": "زمان حل شدن",
    },
    "customers.Prospect": {
        "social": "شبکه‌ی اجتماعی", "last_contact_at": "آخرین تماس",
        "next_action_at": "اقدام بعدی",
    },
    "customers.CallConsent": {
        "how": "چطور گرفته شد", "obtained_at": "زمان گرفتن", "revoked_at": "زمان پس‌گرفتن",
    },
    "customers.Recording": {
        "happened_at": "زمان تماس", "seconds": "مدت (ثانیه)", "transcript": "متن پیاده‌شده",
        "commitments": "تعهدها", "suggested_next": "اقدام پیشنهادی بعدی",
    },
    "campaigns.Campaign": {
        "goal": "هدف", "audience": "مخاطب", "notes": "یادداشت",
        "approval_state": "وضعیت تأیید", "product_image": "تصویر محصول",
        "video_script": "سناریوی ویدیو",
    },
    "campaigns.PublishJob": {"scheduled_for": "زمان‌بندی‌شده برای"},
    "billing.Plan": {
        "price_toman": "قیمت (تومان)", "video_seconds": "ثانیه ویدیو",
        "images": "تعداد تصویر", "captions": "تعداد کپشن",
        "max_products": "حداکثر محصول", "max_stores": "حداکثر فروشگاه",
        "trial_days": "روزهای آزمایشی", "is_trial": "پلن آزمایشی",
        "allows_publishing": "اجازه‌ی انتشار", "allows_sales_agent": "اجازه‌ی ایجنت فروش",
    },
    "billing.Subscription": {
        "period_end": "پایان دوره", "cancel_at_period_end": "لغو در پایان دوره",
        "bonus_video_seconds": "ثانیه ویدیوی هدیه", "bonus_images": "تصویر هدیه",
        "bonus_captions": "کپشن هدیه",
    },
    "billing.Usage": {
        "external": "از سرویس بیرونی", "retry_of": "تلاش مجدد برای",
        "quality_source": "منبع کیفیت", "quality_reason": "دلیل کیفیت",
    },
    "billing.Payment": {
        "amount_toman": "مبلغ (تومان)", "invoice_number": "شماره‌ی فاکتور",
        "gateway_response": "پاسخ درگاه", "paid_at": "زمان پرداخت",
        "confirmed_by": "تأییدکننده", "refunded_at": "زمان بازگشت وجه",
        "refund_reason": "دلیل بازگشت وجه",
    },
    "cms.Article": {"author": "نویسنده", "display_date": "تاریخ نمایشی"},
    "cms.Redirect": {"old_path": "نشانی قدیمی", "new_path": "نشانی جدید"},
    "cms.SiteSettings": {
        "name_en": "نام (انگلیسی)", "tagline": "شعار", "tagline_en": "شعار (انگلیسی)",
        "one_liner": "معرفی یک‌خطی", "one_liner_en": "معرفی یک‌خطی (انگلیسی)",
        "keywords": "کلیدواژه‌ها", "keywords_en": "کلیدواژه‌ها (انگلیسی)",
        "instagram": "اینستاگرام", "telegram": "تلگرام",
    },
    "cms.ShowcaseItem": {
        "product_en": "محصول (انگلیسی)", "category_en": "دسته (انگلیسی)",
        "caption_en": "کپشن (انگلیسی)", "video_poster": "تصویر پوستر ویدیو",
    },
    "cms.FaqItem": {
        "question": "پرسش", "question_en": "پرسش (انگلیسی)",
        "answer": "پاسخ", "answer_en": "پاسخ (انگلیسی)", "group": "گروه",
    },
    "cms.SeoPage": {"meta_description": "توضیح متا", "locale": "زبان"},
    "cms.CaseStudy": {"customer_name": "نام مشتری"},
    "cms.Testimonial": {"case_study": "مطالعه‌ی موردی مرتبط"},
    "marketing.Lead": {
        "message": "پیام", "source_path": "صفحه‌ی مبدأ",
        "ip": "نشانی IP", "user_agent": "مرورگر",
    },
}

# ---------------------------------------------------------------- گزینه‌ها
# برچسب گزینه‌ها (choices) این‌جا نیست، و نباید باشد.
#
# اول همین‌جا بود و `apply()` مقدار `field.choices` را در زمان اجرا عوض
# می‌کرد. نتیجه: `makemigrations` برای ۱۶ فیلد مهاجرتِ جعلی می‌خواست بسازد.
# دلیلش فرقی است که به چشم نمی‌آید — جنگو برای مهاجرت‌ها `verbose_name` را
# از مقدارِ اولیه‌ی سازنده می‌خواند (`_verbose_name`)، پس عوض کردنش در زمان
# اجرا نامرئی است؛ ولی `choices` را مستقیم از خودِ فیلد می‌خواند، پس هر
# تغییری در آن «تغییر مدل» به حساب می‌آید.
#
# برای همین برچسب گزینه‌ها به جای درستشان رفتند: خودِ `TextChoices` در
# مدل‌ها. `report()` پایین همچنان می‌گوید کدام گزینه هنوز فارسی نیست.

def apply():
    """برچسب‌ها را روی مدل‌های ثبت‌شده در ادمین می‌نشاند.

    هرچه از قبل فارسی است دست نمی‌خورد — این جدول فقط جای خالی را پر
    می‌کند، نه اینکه تصمیم کسی را بازنویسی کند.
    """
    from django.contrib import admin

    for model in list(admin.site._registry):
        key = "%s.%s" % (model._meta.app_label, model.__name__)
        per_model = MODEL_FIELDS.get(key, {})
        for field in model._meta.fields:
            if not PERSIAN.search(str(field.verbose_name)):
                label = per_model.get(field.name) or FIELDS.get(field.name)
                if label:
                    field.verbose_name = label


def report():
    """چه چیزی هنوز ترجمه نشده — برای وقتی مدل جدیدی اضافه می‌شود."""
    from django.contrib import admin

    missing_fields, missing_choices = [], []
    for model in admin.site._registry:
        if model._meta.app_label in ("auth", "contenttypes"):
            continue
        key = "%s.%s" % (model._meta.app_label, model.__name__)
        for field in model._meta.fields:
            if not PERSIAN.search(str(field.verbose_name)):
                missing_fields.append("%s.%s" % (key, field.name))
            for value, label in field.choices or []:
                if not PERSIAN.search(str(label)):
                    missing_choices.append("%s.%s=%s" % (key, field.name, value))
    return missing_fields, missing_choices


# ---------------------------------------------------------------- ابزارهای یکپارچه (NMarketing)
# سرورهای پردازش، ویدیوی سه‌بعدی و سایت‌ساز — همان قاعده: فقط جای خالی پر می‌شود.
MODEL_FIELDS.update({
    "compute.ComputeNode": {
        "capabilities": "توانایی‌ها (گزارشِ خودِ سرور)", "stats": "زمانِ معمولِ هر کار", "last_seen": "آخرین تماس",
        "jobs_done": "کارهای انجام‌شده", "notes": "یادداشت",
    },
    "compute.ComputeJob": {
        "uid": "شناسهٔ کار", "inputs": "فایل‌های ورودی", "node": "سرورِ پردازش", "node_wanted": "فقط این سرور",
        "request_hash": "اثرِ انگشتِ درخواست", "dedupe_of": "تکرارِ کارِ", "origin": "مبدأ (پنل/ComfyUI/…)",
        "max_attempts": "حداکثر تلاش", "timeout_s": "مهلت (ثانیه)", "lease_s": "مهلتِ بی‌خبری (ثانیه)",
        "progress": "پیشرفت", "message": "پیام", "cancel_requested": "درخواستِ لغو", "claimed_at": "زمانِ گرفتن",
        "heartbeat_at": "آخرین گزارشِ پیشرفت", "finished_at": "زمانِ پایان", "payload": "پارامترها", "kind": "نوعِ کار",
        "state": "وضعیت", "priority": "اولویت", "attempts": "تعداد تلاش", "result": "نتیجه", "error": "خطا",
    },
    "up3d.AiSettings": {"base_url": "نشانیِ پایه (Base URL)", "updated": "آخرین تغییر"},
    "up3d.Project": {"uid": "شناسه", "current": "نسخهٔ فعلیِ صحنه", "created": "زمان ساخت", "updated": "آخرین تغییر",
                     "poster": "پوستر", "brief": "خلاصهٔ کار", "title": "عنوان", "owner": "مالک"},
    "up3d.SceneVersion": {"project": "پروژه", "number": "شمارهٔ نسخه", "document": "سندِ صحنه (JSON)", "source": "منبعِ تغییر",
                          "valid": "معتبر", "report": "گزارشِ وارسی", "created": "زمان ساخت", "note": "یادداشت"},
    "up3d.Job": {"uid": "شناسهٔ کار", "project": "پروژه", "version": "نسخهٔ صحنه", "profile": "کیفیت (پروفایل)",
                 "params": "پارامترها", "worker": "کارگرِ رندر", "progress": "پیشرفت", "frames_done": "فریم‌های رندرشده",
                 "frames_total": "کلِ فریم‌ها", "sec_per_frame": "ثانیه بر فریم", "message": "پیام", "log": "گزارشِ اجرا (log)",
                 "qc": "کنترلِ کیفیت", "report": "گزارشِ موتور", "files": "فایل‌های خروجی", "estimate_seconds": "تخمینِ زمان (ثانیه)",
                 "cancel_requested": "درخواستِ لغو", "created": "زمان ساخت", "started": "شروع", "claimed": "زمانِ گرفتن",
                 "finished": "پایان", "kind": "نوعِ کار", "state": "وضعیت", "owner": "سفارش‌دهنده", "error": "خطا"},
    "up3d.Worker": {"capabilities": "توانایی‌ها", "stats": "سرعتِ اندازه‌گیری‌شده", "last_seen": "آخرین تماس",
                    "jobs_done": "کارهای انجام‌شده", "created": "زمان ساخت", "token": "توکن"},
    "up3d.Upload": {"uid": "شناسه", "size": "اندازه (بایت)", "created": "زمان بارگذاری", "kind": "نوع", "name": "نام",
                    "path": "مسیر", "owner": "بارگذارنده"},
    "projects.Project": {"allowed_hosts": "میزبان‌های مجاز (ALLOWED_HOSTS)"},
    "ai_engine.AiProposal": {"applied_at": "زمانِ اعمال"},
    "project_importer.ImportReport": {"project": "پروژه"},
})
