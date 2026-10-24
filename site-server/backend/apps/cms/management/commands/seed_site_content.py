"""Put the public site's content into the database, once.

Until now the site's name, its FAQ and its showcase lived in TypeScript files
and a JSON file next to them, which meant that changing a sentence — or
swapping the sample video — was a code edit, a build and a deploy. This moves
them where they can be edited: the admin.

The TypeScript files stay as the fallback, exactly as the Markdown articles
did. A build that cannot reach the backend still renders a complete site; it is
just as fresh as the last deploy rather than as fresh as this morning.

    python manage.py seed_site_content

Idempotent. Run it again after adding a question to the file and only the new
one lands; rows already edited in the admin are left alone, because the whole
point was to stop the file overwriting the person.
"""
import json
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from apps.cms.models import FaqItem, ShowcaseItem, ShowcaseSegment, SiteSettings

#: backend/apps/cms/management/commands/x.py → Code/UpMarket
ROOT = Path(__file__).resolve().parents[5]
WEBSITE = ROOT / "website"

SETTINGS = {
    "name": "آپ‌مارکت",
    "name_en": "UpMarket",
    "tagline": "کارمند فروش و مارکتینگ هوش مصنوعی برای فروشگاه‌های آنلاین",
    "tagline_en": "An AI sales and marketing employee for online shops",
    "one_liner": "اطلاعات محصولت را بده — پوستر، ویدیو، کپشن و پشتیبانی فروشش را تحویل بگیر.",
    "one_liner_en": "Add your product — get the poster, the video, the caption and the sales replies.",
    "email": "hello@nmarketing.ir",
    "instagram": "https://instagram.com/nmarketing.ir",
    "keywords": (
        "بازاریابی هوش مصنوعی، تولید محتوا با هوش مصنوعی، پوستر تبلیغاتی، "
        "ویدیو تبلیغاتی، کپشن اینستاگرام، فروشگاه آنلاین، تحلیل رقبا، "
        "SaaS ایرانی، دستیار فروش"
    ),
    "keywords_en": (
        "AI marketing, AI content generation, ad poster generator, "
        "promotional video AI, Instagram captions, online shop marketing, "
        "competitor analysis, AI sales assistant"
    ),
}

FAQ = [
    ("PRODUCT", True,
     "باید بلد باشم با هوش مصنوعی کار کنم؟",
     "نه. اطلاعات محصول و عکسش را وارد می‌کنید؛ بقیه‌اش خودکار است. پرامپت‌نویسی لازم نیست.",
     "Do I need to know how to use AI?",
     "No. You enter the product and its photo; the rest is automatic. There is no prompt writing."),
    ("AI", True,
     "عکس محصول خودم استفاده می‌شود یا تصویر ساختگی؟",
     "عکس واقعی خودتان. پوستر از روی همان عکس ساخته می‌شود تا مشتری دقیقاً همان چیزی را ببیند که می‌خرد.",
     "Does it use my product photo, or an invented image?",
     "Your real photo. The poster is built on top of it, so the buyer sees exactly what they are buying."),
    ("SALES", True,
     "قیمت و موجودی را چطور به مشتری می‌گوید؟",
     "فقط از روی اطلاعاتی که خودتان ثبت کرده‌اید. سیستم عدد نمی‌سازد و اگر چیزی را نداند می‌گوید نمی‌داند.",
     "How does it tell customers price and stock?",
     "Only from what you entered. It never invents a number, and if it does not know something it says so."),
    ("PRODUCT", True,
     "محتوا به چه زبانی است؟",
     "فارسی، با لحن برند خودتان. نریشن ویدیو هم فارسی یا انگلیسی، به انتخاب شما.",
     "What language is the content in?",
     "Persian, in your brand's tone. Video narration can be Persian or English — your choice."),
    ("PRODUCT", False,
     "چقدر طول می‌کشد؟",
     "کپشن و متن در چند دقیقه آماده است. پوستر و ویدیو رندر می‌خواهند و در صف قرار می‌گیرند — "
     "پیشرفتشان را زنده می‌بینید. در هر حال روزها و هفته‌های یک تیم انسانی نیست.",
     "How long does it take?",
     "Captions and copy are ready in minutes. Posters and video need rendering and go into a "
     "queue — you watch the progress live. Either way it is not the days and weeks a human team takes."),
    ("AI", False,
     "اگر خروجی را نپسندم؟",
     "دوباره تولید می‌کنید. تا وقتی تأیید نکنید چیزی منتشر نمی‌شود.",
     "What if I do not like the output?",
     "You generate it again. Nothing is published until you approve it."),
    ("PRICING", False,
     "سهمیه‌ی ماهانه یعنی چه؟",
     "هر پلن مقدار مشخصی ثانیه ویدیو، تصویر و کپشن در ماه دارد. مصرف را در پنل زنده می‌بینید "
     "و اگر رندری خطا بدهد سهمیه‌اش برمی‌گردد.",
     "What does the monthly quota mean?",
     "Each plan includes a set number of video seconds, images and captions per month. You see "
     "usage live in the panel, and a failed render returns its quota."),
    ("PRICING", False,
     "پرداخت چطور است؟",
     "ماهانه. دوره‌ی آزمایشی دو هفته‌ای بدون کارت بانکی شروع می‌شود و خودکار تمدید نمی‌شود.",
     "How does payment work?",
     "Monthly. The two-week trial starts without a card and does not auto-renew."),
    ("SALES", False,
     "به اینستاگرام من وصل می‌شود؟",
     "بله. با اتصال حساب، محتوای تأییدشده مستقیم منتشر می‌شود. اگر ترجیح بدهید می‌توانید خودتان دستی منتشر کنید.",
     "Does it connect to my Instagram?",
     "Yes. Connect the account and approved content publishes directly. If you prefer, you can still publish manually."),
    ("SECURITY", False,
     "اطلاعات فروشگاه من امن است؟",
     "هر فروشگاه کاملاً جدا است و فقط صاحبش به داده‌هایش دسترسی دارد. تولید تصویر و ویدیو روی "
     "سرور خودمان انجام می‌شود؛ صداگذاری و جستجوی قیمت رقبا به سرویس بیرونی وصل می‌شوند و این "
     "را در سیاست حریم خصوصی نوشته‌ایم.",
     "Is my shop's data safe?",
     "Each shop is fully isolated and only its owner can reach its data. Image and video "
     "generation runs on our own servers; voice-over and competitor price lookups use outside "
     "services, and our privacy policy says exactly which."),
]

#: English product names, which the JSON has no room for.
EN = {
    "apparel": ("Apparel", "Oversized cream coat"),
    "accessory": ("Accessory", "Minimal necklace"),
    "decor": ("Decor", "Minimal floor lamp"),
}


class Command(BaseCommand):
    help = "محتوای سایت عمومی (تنظیمات، سؤالات متداول، نمونه‌کارها) را وارد دیتابیس می‌کند"

    def handle(self, *args, **options):
        self._settings()
        self._faq()
        self._showcase()
        self.stdout.write(
            "\nحالا همه‌چیز از پنل ادمین قابل ویرایش است: /admin/cms/"
        )

    # ------------------------------------------------------------- settings
    def _settings(self):
        row = SiteSettings.load()
        # Only fills what is still empty. Somebody who already changed the
        # tagline in the admin did it on purpose.
        touched = []
        for field, value in SETTINGS.items():
            if not getattr(row, field):
                setattr(row, field, value)
                touched.append(field)
        if touched:
            row.save()
        self.stdout.write(
            f"تنظیمات سایت: {len(touched)} فیلد پر شد" if touched
            else "تنظیمات سایت: از قبل پر بود"
        )

    # ------------------------------------------------------------------ faq
    def _faq(self):
        made = 0
        for order, (group, on_home, q, a, q_en, a_en) in enumerate(FAQ, start=1):
            _, created = FaqItem.objects.get_or_create(
                question=q,
                defaults={
                    "group": group,
                    "answer": a,
                    "question_en": q_en,
                    "answer_en": a_en,
                    "on_home": on_home,
                    "order": order * 10,
                },
            )
            made += created
        self.stdout.write(f"سؤالات متداول: {made} تازه · {FaqItem.objects.count()} کل")

    # ------------------------------------------------------------- showcase
    def _showcase(self):
        source = WEBSITE / "content" / "showcase" / "works.json"
        if not source.exists():
            self.stderr.write(self.style.WARNING(f"! {source} نیست — نمونه‌کار وارد نشد"))
            return

        works = json.loads(source.read_text(encoding="utf-8"))
        public = WEBSITE / "public"
        made = 0

        for order, work in enumerate(works, start=1):
            slug = work["id"]
            if ShowcaseItem.objects.filter(slug=slug).exists():
                continue

            cat_en, product_en = EN.get(slug, ("", ""))
            item = ShowcaseItem.objects.create(
                slug=slug,
                category=work.get("category", ""),
                category_en=cat_en,
                product=work.get("product", ""),
                product_en=product_en,
                caption=work.get("caption", "").replace("\r\n", "\n"),
                order=order * 10,
                # The one with video is the one the home page can honestly use
                # for "one product, three outputs".
                featured=bool(work.get("videos")),
            )

            image = public / work.get("image", "").lstrip("/")
            if image.exists():
                with image.open("rb") as fh:
                    item.image.save(image.name, File(fh), save=True)

            for n, rel in enumerate(work.get("videos") or [], start=1):
                clip = public / rel.lstrip("/")
                if not clip.exists():
                    continue
                segment = ShowcaseSegment(item=item, order=n)
                with clip.open("rb") as fh:
                    segment.clip.save(clip.name, File(fh), save=True)

            made += 1

        self.stdout.write(
            f"نمونه‌کارها: {made} تازه · {ShowcaseItem.objects.count()} کل"
        )
        if ShowcaseSegment.objects.exists():
            self.stdout.write(
                "  بعدی: python manage.py stitch_showcase "
                "— قطعه‌های ۵ ثانیه‌ای را به یک ویدیو تبدیل می‌کند"
            )
