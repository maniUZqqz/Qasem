# -*- coding: utf-8 -*-
"""آزمونِ خودکارِ «تصویر به کد» (قراردادِ docs/selftests/img2code.md).

«تصویر به کد» روی CPU ِ سرورِ سایت اجراست و نوعِ کارِ GPU ندارد؛ پس این یک آزمونِ **مجازی** (بی‌گره) است که همراهِ بقیه هر شب و با هر بار روشن‌شدنِ گره اجرا می‌شود:
یک صفحهٔ کوچک ⇒ تبدیل در پردازهٔ جدا ⇒ یک صفحهٔ دارای هیرویِ گرادیان (CSS، نه تصویر) ⇒ یک صفحهٔ فارسیِ ریز (OCR + واژه‌نامه) ⇒ نمایش و سنجش در مرورگر ⇒ سندِ سایت‌ساز. قبول = همهٔ مرحله‌ها. اگر پیش‌نیازی (mv2code، Tesseract، مرورگر) نصب نباشد دلیلِ دقیق
در گزارش می‌آید. اگر اپِ `apps.img2code` در این نسخه نیست، چیزی ثبت نمی‌شود و هیچ خطایی نمی‌آید.
"""
try:  # pragma: no cover — بسته به این‌که وصلهٔ «تصویر به کد» اعمال شده باشد
    from apps.img2code import selftest as _i2c
except Exception:  # noqa: BLE001
    _i2c = None

from . import SelfTest, Verdict, register


def virtual(ctx) -> Verdict:
    res = _i2c.run_engine()
    detail = "؛ ".join("%s: %s" % (s["name"], "قبول" if s["ok"] else "رد (%s)" % s["detail"]) for s in res["steps"])
    if res["ok"]:
        return Verdict.passed("یک صفحهٔ کوچک تا سندِ سایت‌ساز در %s ثانیه روی پردازندهٔ سرور؛ %s" % (res["seconds"], detail), device="cpu")
    bad = next(s for s in res["steps"] if not s["ok"])
    return Verdict.failed("مرحلهٔ «%s» رد شد: %s" % (bad["name"], bad["detail"] or "—"), device="cpu")


if _i2c is not None:
    register(SelfTest(key="img2code_engine", label="تصویر به کد: صفحهٔ کوچک ⇒ HTML/CSS ⇒ سندِ سایت‌ساز", group="system", virtual=virtual, optional=True, order=97,
                      describe="بی‌گره (روی CPU ِ سرورِ سایت): mv2code + Tesseract + مرورگرِ بی‌سر؛ تبدیل در پردازهٔ جدا، خواندنِ یک صفحهٔ فارسیِ ریز (OCR + واژه‌نامهٔ اصلاحِ نقطه‌ها: دست‌کم ۸ از ۱۰ واژه)، یک صفحهٔ دارای هیرویِ گرادیانِ تمام‌عرض (باید CSS شود، نه یک تصویر)، سنجشِ شباهت و ساختِ سندِ سایت‌ساز"))
