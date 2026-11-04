"""The channels of outreach: what each one is, what it needs, who it can reach.

Three channels are SENT BY THE SYSTEM after a human approval (every round-1 guardrail applies to each of them):

* ``contact_form`` - the lead's own contact / ticket form (``form_analysis`` decides whether it may be submitted);
* ``email``        - SMTP, with the operator's own mail account (``channels/email.py``);
* ``sms``          - queued for the operator's phone (NM-Mobile app): the phone sends it from its own SIM (``channels/sms.py``).

The rest are DONE BY A PERSON: the panel gives a ready link (``deeplinks.py``) and the text to paste, the person sends it and
records the result. No messenger account is ever automated, and no bot logs in anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.growth_engine.leads.choices import ContactKind

from ..models import AUTO_CHANNELS, MANUAL_CHANNELS, Channel

__all__ = ["ChannelSpec", "SPECS", "spec", "is_auto", "is_manual", "AUTO_CHANNELS", "MANUAL_CHANNELS"]


@dataclass(frozen=True)
class ChannelSpec:
    key: str
    label: str
    kind: str  # "auto" | "manual"
    description: str
    contact_kinds: tuple[str, ...]  # the ContactPoint kinds that can serve as this channel's recipient, best first
    default_priority: int
    default_enabled: bool
    secret_fields: tuple[tuple[str, str], ...] = ()
    config_schema: tuple[dict, ...] = field(default_factory=tuple)
    needs_subject: bool = False
    hint: str = ""


_EMAIL_SCHEMA = (
    {"name": "host", "label": "سرورِ ایمیل (SMTP)", "type": "text", "help": "خالی = همان مقدارِ تنظیمِ سرور (EMAIL_HOST)"},
    {"name": "port", "label": "پورت", "type": "int", "min": 1, "max": 65535, "help": "معمولاً ۵۸۷ (STARTTLS) یا ۴۶۵ (SSL)"},
    {"name": "security", "label": "نوعِ رمزگذاری", "type": "choice", "choices": [["starttls", "STARTTLS (۵۸۷)"], ["ssl", "SSL/TLS (۴۶۵)"], ["none", "بدونِ رمزگذاری (پیشنهاد نمی‌شود)"]]},
    {"name": "username", "label": "نامِ کاربری", "type": "text", "help": "خالی = بدون ورود"},
    {"name": "from_email", "label": "ایمیلِ فرستنده (From)", "type": "email", "help": "باید نشانیِ مجازِ همین سرورِ ایمیل باشد"},
    {"name": "from_name", "label": "نامِ نمایشیِ فرستنده", "type": "text", "help": "خالی = نامِ شرکت در «تنظیماتِ جذب مشتری»"},
    {"name": "reply_to", "label": "پاسخ به (Reply-To)", "type": "email", "help": "خالی = ایمیلِ فرستنده در «تنظیماتِ جذب مشتری»؛ پاسخ‌ها به اینجا می‌آیند"},
    {"name": "timeout", "label": "مهلتِ اتصال (ثانیه)", "type": "int", "min": 5, "max": 60},
)
_SMS_SCHEMA = (
    {"name": "max_parts", "label": "حداکثرِ تعدادِ بخشِ هر پیامک", "type": "int", "min": 1, "max": 3, "default": 2,
     "help": "فارسی: بخشِ اول ۷۰ نویسه، بعد از آن هر بخش ۶۷ نویسه. جملهٔ لغو هم جزوِ شمارش است."},
)

SPECS: dict[str, ChannelSpec] = {
    Channel.CONTACT_FORM: ChannelSpec(
        Channel.CONTACT_FORM, "فرمِ تماسِ سایت", "auto",
        "پیام در فرمِ تماس یا تیکتِ خودِ سایتِ کسب‌وکار ثبت می‌شود (فقط فرم‌هایی که کپچا و ورود ندارند).",
        (ContactKind.CONTACT_FORM,), 1, True,
    ),
    Channel.EMAIL: ChannelSpec(
        Channel.EMAIL, "ایمیل", "auto",
        "ایمیل با حسابِ SMTP خودِ شما فرستاده می‌شود؛ هر ایمیل جملهٔ لغو و هدرِ List-Unsubscribe دارد و پاسخ‌ها به ایمیلِ شما می‌آید.",
        (ContactKind.EMAIL,), 2, False, secret_fields=(("smtp_password", "رمزِ ایمیل"),), config_schema=_EMAIL_SCHEMA, needs_subject=True,
    ),
    Channel.SMS: ChannelSpec(
        Channel.SMS, "پیامک (از گوشیِ شما)", "auto",
        "پیامک در صفِ اپِ NM-Mobile می‌رود و گوشیِ شما با سیم‌کارتِ خودش می‌فرستد؛ ساعتِ سکوت و سقفِ ساعتی را خودِ اپ رعایت می‌کند.",
        (ContactKind.PHONE,), 3, False, config_schema=_SMS_SCHEMA,
        hint="فقط شمارهٔ موبایل؛ تلفنِ ثابت پیامک نمی‌گیرد.",
    ),
    Channel.WHATSAPP: ChannelSpec(
        Channel.WHATSAPP, "واتساپ", "manual", "لینکِ آمادهٔ چت با متنِ پیام؛ شما می‌فرستید و نتیجه را ثبت می‌کنید. هیچ حسابی خودکار نمی‌شود.",
        (ContactKind.WHATSAPP, ContactKind.PHONE), 4, True,
        hint="اگر فقط شمارهٔ موبایل داریم، ممکن است آن شماره واتساپ نداشته باشد.",
    ),
    Channel.TELEGRAM: ChannelSpec(
        Channel.TELEGRAM, "تلگرام", "manual", "لینکِ باز کردنِ چت و متنِ آماده برای چسباندن؛ شما می‌فرستید و نتیجه را ثبت می‌کنید.",
        (ContactKind.TELEGRAM,), 5, True,
    ),
    Channel.EITAA: ChannelSpec(
        Channel.EITAA, "ایتا", "manual", "لینکِ باز کردنِ چت و متنِ آماده برای چسباندن؛ شما می‌فرستید و نتیجه را ثبت می‌کنید.",
        (ContactKind.EITAA,), 6, True,
    ),
    Channel.BALE: ChannelSpec(
        Channel.BALE, "بله", "manual", "لینکِ باز کردنِ چت و متنِ آماده برای چسباندن؛ شما می‌فرستید و نتیجه را ثبت می‌کنید.",
        (ContactKind.BALE,), 7, True,
    ),
    Channel.RUBIKA: ChannelSpec(
        Channel.RUBIKA, "روبیکا", "manual", "لینکِ باز کردنِ چت و متنِ آماده برای چسباندن؛ شما می‌فرستید و نتیجه را ثبت می‌کنید.",
        (ContactKind.RUBIKA,), 8, True,
    ),
    Channel.PHONE_CALL: ChannelSpec(
        Channel.PHONE_CALL, "تماس تلفنی", "manual", "یک کارِ دستی برای تماس: شماره، متنِ پیشنهادیِ گفتگو و ثبتِ نتیجه.",
        (ContactKind.PHONE,), 9, True,
    ),
}


def spec(channel: str) -> ChannelSpec:
    return SPECS[channel]


def is_auto(channel: str) -> bool:
    return channel in AUTO_CHANNELS


def is_manual(channel: str) -> bool:
    return channel in MANUAL_CHANNELS
