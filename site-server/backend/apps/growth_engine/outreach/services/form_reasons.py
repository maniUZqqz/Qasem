"""Why a form (or a lead) is not sent automatically: the reason codes and their Persian texts.

Used by form analysis (``form_analysis.analyze_page``) and by the rest of the outreach module
(``no_target_url``, ``robots_blocked``, ``robots_unavailable`` and ``fetch_failed`` are decided
outside the HTML analysis, but their wording lives here so the panel says one consistent thing).
Every text says what is wrong and that a person has to do it by hand - nothing is ever bypassed.
"""
from __future__ import annotations

REASON_TEXTS: dict[str, str] = {
    "captcha": "فرم کپچا (کد امنیتی یا «ربات نیستم») دارد؛ کپچا را فقط یک انسان می‌تواند حل کند، پیام را دستی بفرستید.",
    "honeypot": "فرم فیلدِ نامرئیِ ضدربات (هانی‌پات) دارد؛ ارسالِ خودکار امن نیست، پیام را دستی بفرستید.",
    "login_required": "برای ارسال به این فرم باید با حساب کاربری وارد شد؛ حساب نمی‌سازیم، پیام را دستی بفرستید.",
    "otp_required": "فرم کدِ تأییدِ پیامکی می‌خواهد؛ پیام را دستی بفرستید.",
    "js_only": "این فرم فقط با جاوااسکریپت کار می‌کند؛ پیام را دستی بفرستید.",
    "challenge_page": "سایت صفحهٔ بررسیِ مرورگر (مثل Cloudflare) نشان داد؛ پیام را دستی بفرستید.",
    "file_upload_required": "فرم آپلودِ فایل را اجباری کرده؛ پیام را دستی بفرستید.",
    "required_field_unfillable": "فرم فیلدِ اجباریِ «{label}» دارد که از مشخصاتِ فرستنده یا قالبِ پیام نمی‌شود صادقانه پر کرد؛ پیام را دستی بفرستید.",
    "required_checkbox": "فرم تیکِ اجباریِ «{label}» دارد؛ باید یک انسان تصمیم بگیرد، پیام را دستی بفرستید.",
    "no_message_field": "فرم جایی برای نوشتنِ پیام ندارد؛ پیام را دستی بفرستید.",
    "no_form_found": "در این صفحه فرمِ تماسی که بشود خودکار پر کرد پیدا نشد؛ پیام را دستی بفرستید.",
    "no_target_url": "برای این لید آدرسِ صفحهٔ تماس یا تیکت ثبت نشده؛ اول اطلاعاتِ تماسش را استخراج یا وارد کنید.",
    "robots_blocked": "فایل robots.txt سایت اجازهٔ دسترسی به این صفحه را نمی‌دهد؛ پیام را دستی بفرستید.",
    "robots_unavailable": "فایل robots.txt سایت خوانده نشد؛ برای احتیاط خودکار نمی‌فرستیم، پیام را دستی بفرستید.",
    "fetch_failed": "صفحهٔ تماس باز نشد (خطا یا قطعیِ سایت)؛ بعداً دوباره امتحان کنید یا دستی بفرستید.",
}

REASON_CODES = tuple(REASON_TEXTS)


def text_for(code: str, label: str = "") -> str:
    """The Persian sentence for ``code`` (``label`` fills «{label}» in the two per-field reasons)."""
    template = REASON_TEXTS[code]
    return template.format(label=label or "نامشخص") if "{label}" in template else template
