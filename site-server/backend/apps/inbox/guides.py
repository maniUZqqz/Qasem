"""The connect pages' content: what each channel needs, step by step, in Persian.

Kept as data (not hard-coded in the React page) for two reasons: the same text
feeds the docs (`docs/inbox/channels-fa.md` is generated from it by hand-check),
and the API can return exactly what the page shows so a test can assert that
every channel has steps, fields and a health story.

`fields` describe the inputs the page renders. A field named `token` is the
secret credential - stored on the connection and never sent back (only its
masked tail); anything else lands in `connection.config`.
"""
from __future__ import annotations

#: Order is the order of the cards on the page.
CHANNEL_ORDER = ["TELEGRAM", "BALE", "EITAA", "RUBIKA", "WEBCHAT", "SMS", "INSTAGRAM", "WHATSAPP"]

GUIDES: dict[str, dict] = {
    "TELEGRAM": {
        "title": "تلگرام",
        "summary": "ربات تلگرام شما پیام‌های مشتری را به صندوق می‌آورد و پاسخ‌ها از همان ربات می‌روند.",
        "mode": "webhook / polling",
        "fields": [
            {"key": "token", "label": "توکن ربات", "secret": True,
             "placeholder": "123456789:AAH…", "help": "همان متنی که @BotFather بعد از ساخت ربات می‌دهد."},
        ],
        "steps": [
            "در تلگرام به ⁦@BotFather⁩ پیام بدهید و دستور ⁦/newbot⁩ را بفرستید.",
            "یک نام و یک نام‌کاربری (که به bot ختم شود) برای ربات انتخاب کنید.",
            "توکنی که BotFather می‌دهد را در کادر «توکن ربات» بگذارید و «ذخیره و بررسی» را بزنید.",
            "دکمهٔ «ثبت وب‌هوک» را بزنید؛ اگر سرور شما به تلگرام دسترسی مستقیم ندارد، حالت «پرسش دوره‌ای» را انتخاب کنید.",
            "از یک حساب دیگر به ربات پیام بدهید؛ پیام باید ظرف چند ثانیه در صندوق دیده شود.",
        ],
        "limits": "تلگرام برای مشتریان ایرانی معمولاً فیلتر است؛ اگر مشتری شما از آن استفاده می‌کند، بله یا ایتا را هم وصل کنید.",
        "docs": "https://core.telegram.org/bots#how-do-i-create-a-bot",
        "needs_owner_account": False,
    },
    "BALE": {
        "title": "بله",
        "summary": "ربات بله با API شبیه تلگرام کار می‌کند؛ پیام مشتری‌های بله مستقیم به صندوق می‌رسد.",
        "mode": "webhook / polling",
        "fields": [
            {"key": "token", "label": "توکن ربات", "secret": True,
             "placeholder": "123456789:…", "help": "توکنی که «پدر بات‌ها» (BotFather) در بله می‌دهد."},
        ],
        "steps": [
            "در پیام‌رسان بله، حساب «⁦botfather⁩» را پیدا کنید و /start را بفرستید.",
            "گزینهٔ ساخت ربات را بزنید و نام و شناسهٔ ربات را بدهید.",
            "توکن را کپی کنید، در کادر «توکن ربات» بگذارید و «ذخیره و بررسی» را بزنید.",
            "«ثبت وب‌هوک» را بزنید (یا پرسش دوره‌ای را انتخاب کنید) و کانال را روشن کنید.",
            "از یک حساب دیگر به ربات پیام بدهید و در صندوق ببینید.",
        ],
        "limits": "ربات‌های پیام‌رسان معمولاً فقط می‌توانند به کسانی پیام بدهند که قبلاً با ربات حرف زده‌اند؛ ارسال گروهی هم فقط به همین مشتریان می‌رسد.",
        "docs": "https://docs.bale.ai/",
        "needs_owner_account": False,
    },
    "EITAA": {
        "title": "ایتا",
        "summary": "ربات ایتا از سرویس «ایتایار» می‌آید؛ ارسال پیام همیشه کار می‌کند و دریافت پیام به فعال‌بودن آن برای ربات شما بستگی دارد.",
        "mode": "webhook / polling",
        "fields": [
            {"key": "token", "label": "توکن ایتایار", "secret": True,
             "placeholder": "bot123456:…", "help": "توکنی که در پنل ایتایار برای ربات شما ساخته می‌شود."},
            {"key": "message_title", "label": "عنوان پیام‌ها", "secret": False,
             "placeholder": "پاسخ پشتیبانی", "help": "ایتا بالای هر پیام یک عنوان نشان می‌دهد."},
        ],
        "steps": [
            "در سایت ایتایار (⁦eitaayar.ir⁩) با حساب ایتای خود وارد شوید و یک ربات بسازید.",
            "توکن ربات را کپی کنید و در کادر «توکن ایتایار» بگذارید.",
            "«ذخیره و بررسی» را بزنید. اگر پیام «ارسال فعال است؛ دریافت فعال نیست» دیدید، دریافت پیام را در پنل ایتایار برای ربات روشن کنید و دوباره بررسی کنید.",
            "کانال را روشن کنید و از یک حساب دیگر به ربات پیام بدهید.",
        ],
        "limits": "اگر دریافت پیام برای ربات شما در ایتایار فعال نباشد، این کانال فقط ارسال دارد و صندوق چیزی از مشتری نمی‌گیرد؛ وضعیت همین‌جا به‌روشنی نوشته می‌شود.",
        "docs": "https://eitaayar.ir/",
        "needs_owner_account": False,
    },
    "RUBIKA": {
        "title": "روبیکا",
        "summary": "ربات روبیکا پیام‌ها را با وب‌هوک یا پرسش دوره‌ای می‌آورد.",
        "mode": "webhook / polling",
        "fields": [
            {"key": "token", "label": "توکن ربات", "secret": True,
             "placeholder": "توکن بات روبیکا", "help": "توکنی که «بات‌فادر» روبیکا بعد از ساخت ربات می‌دهد."},
        ],
        "steps": [
            "در روبیکا حساب «⁦botfather⁩» را باز کنید و ساخت ربات جدید را بزنید.",
            "توکن را کپی کنید و در کادر «توکن ربات» بگذارید.",
            "«ذخیره و بررسی» را بزنید و بعد «ثبت وب‌هوک» (یا پرسش دوره‌ای).",
            "کانال را روشن کنید و از یک حساب دیگر به ربات پیام بدهید.",
        ],
        "limits": "روبیکا نام کاربر را به ربات نمی‌دهد؛ مشتری با یک شناسه دیده می‌شود تا شمارهٔ موبایلش را بنویسد.",
        "docs": "https://rubika.ir/botapi",
        "needs_owner_account": False,
    },
    "WEBCHAT": {
        "title": "چت سایت",
        "summary": "یک تکه کد کوتاه؛ دکمهٔ گفتگو روی هر سایتی (از جمله سایت‌های ساخته‌شده با سایت‌ساز) ظاهر می‌شود.",
        "mode": "widget",
        "fields": [
            {"key": "allowed_origins", "label": "سایت‌های مجاز", "secret": False, "kind": "list",
             "placeholder": "https://example.ir", "help": "خالی = هر سایتی که کد را بگذارد. برای امنیت بیشتر نشانی سایتتان را بنویسید."},
        ],
        "steps": [
            "کانال را روشن کنید و رنگ، عنوان و پیام خوش‌آمد را در بخش «ظاهر ویجت» تنظیم کنید.",
            "کد زیر را درست پیش از بستن برچسب ⁦</body>⁩ صفحه‌هایتان بگذارید.",
            "اگر سایتتان را با سایت‌ساز نیم‌مارکتینگ ساخته‌اید: در ویرایشگر یک بخشِ «کدِ سفارشی» به صفحه اضافه کنید و همین کد را در آن بگذارید؛ در سایتِ منتشرشده عیناً اجرا می‌شود.",
            "صفحه را باز کنید؛ دکمهٔ گفتگو پایین صفحه دیده می‌شود. یک پیام آزمایشی بفرستید و در صندوق ببینید.",
        ],
        "limits": "هر بازدیدکننده یک گفتگوی جدا دارد و با نشانهٔ مرورگرش دوباره پیدا می‌شود؛ اگر شمارهٔ موبایلش را بنویسد با سایر کانال‌ها یکی می‌شود.",
        "docs": "",
        "needs_owner_account": False,
    },
    "SMS": {
        "title": "پیامک",
        "summary": "پیامک از طریق گوشی‌های متصل به سرویس پیامک نیم‌مارکتینگ ارسال و دریافت می‌شود.",
        "mode": "gateway",
        "fields": [
            {"key": "accept_unknown", "label": "پیامک از شماره‌های ناشناس هم پذیرفته شود", "secret": False, "kind": "bool",
             "help": "خاموش (پیشنهادی): فقط پیامِ مخاطب‌های ثبت‌شده یا کسانی که قبلاً به آن‌ها پیامک داده‌اید وارد صندوق می‌شود؛ پیامک‌های شخصی و کدهای بانکی گوشی وارد نمی‌شود."},
        ],
        "steps": [
            "برنامهٔ موبایل پیامک نیم‌مارکتینگ را روی گوشی که سیم‌کارت دارد نصب و وارد حساب کنید.",
            "در صفحهٔ «اپ‌های پیامک» مطمئن شوید گوشی «آنلاین» است.",
            "همین‌جا کانال پیامک را روشن کنید.",
            "از گوشی دیگری به شمارهٔ آن سیم‌کارت پیامک بزنید؛ پیام در صندوق دیده می‌شود.",
        ],
        "limits": "پیامک گفتگوی کوتاه است (حداکثر ۴۸۰ نویسه برای هر پاسخ) و هزینهٔ سیم‌کارت دارد؛ در ارسال گروهی آخرین انتخاب است.",
        "docs": "",
        "needs_owner_account": False,
    },
    "INSTAGRAM": {
        "title": "اینستاگرام",
        "summary": "دایرکت اینستاگرام با تأیید اپ در Meta به صندوق می‌آید؛ تا آن روز فقط ارسال پست کار می‌کند.",
        "mode": "webhook",
        "fields": [],
        "steps": [
            "توکن نوین‌هاب را در صفحهٔ «اتصال‌ها» وارد کنید (برای ارسال).",
            "برای دریافت دایرکت، اپ Meta خود را بسازید و تأیید بگیرید؛ مدیر سرویس کلیدهای آن را در تنظیمات می‌گذارد.",
            "نشانی وب‌هوک پایین را در تنظیمات وب‌هوک اپ Meta وارد کنید.",
        ],
        "limits": "تا زمانی که Meta اپ را تأیید نکند، دایرکت دریافت نمی‌شود. این محدودیت از Meta است، نه از نیم‌مارکتینگ.",
        "docs": "https://developers.facebook.com/docs/messenger-platform/instagram",
        "needs_owner_account": True,
    },
    "WHATSAPP": {
        "title": "واتساپ",
        "summary": "فقط با حساب رسمی WhatsApp Business (Cloud API) کار می‌کند و به‌طور پیش‌فرض خاموش است.",
        "mode": "webhook",
        "fields": [
            {"key": "token", "label": "توکن دائمی دسترسی", "secret": True,
             "placeholder": "EAAG…", "help": "از بخش System Users در Meta Business."},
            {"key": "phone_number_id", "label": "شناسهٔ شمارهٔ واتساپ (Phone number ID)", "secret": False, "placeholder": "1234567890"},
            {"key": "app_secret", "label": "App Secret", "secret": True, "config": True, "placeholder": "کلید محرمانهٔ اپ"},
            {"key": "verify_token", "label": "رمز تأیید وب‌هوک", "secret": False, "placeholder": "یک متن دلخواه"},
        ],
        "steps": [
            "یک حساب WhatsApp Business و یک اپ در ⁦developers.facebook.com⁩ بسازید و شمارهٔ خود را تأیید کنید.",
            "توکن دائمی، شناسهٔ شماره و App Secret را در کادرهای بالا بگذارید و «ذخیره و بررسی» را بزنید.",
            "در تنظیمات وب‌هوک اپ Meta، نشانی وب‌هوک پایین و همان «رمز تأیید» را وارد و «messages» را مشترک شوید.",
            "کانال را روشن کنید.",
        ],
        "limits": "واتساپ بدون حساب رسمی قابل اتصال نیست و اتصال‌های غیررسمی خطر مسدود شدن شمارهٔ شما را دارند؛ ما چنین اتصالی نمی‌سازیم. پاسخ آزاد فقط تا ۲۴ ساعت پس از پیام مشتری مجاز است.",
        "docs": "https://developers.facebook.com/docs/whatsapp/cloud-api",
        "needs_owner_account": True,
    },
}


def guide_for(kind: str) -> dict:
    return GUIDES.get(kind, {})
