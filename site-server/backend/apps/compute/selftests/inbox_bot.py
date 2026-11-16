"""آزمونِ ربات پاسخ‌گوی صندوق پیام: یک پرسشِ واقعیِ مشتریِ «چغر» با مدلِ خودِ مالک روی کارت.

هیچ نوعِ کارِ تازه‌ای روی گره لازم نیست: صندوق پیام از همان `ollama.generate` استفاده می‌کند که ایجنتِ فروش هم با آن جواب می‌دهد. این آزمون
می‌سنجد که مدلِ متنیِ نصب‌شده با «دانشِ برند» جواب فارسی و مؤدبانه بدهد، عدد و قیمت از خودش درنیاورد، و وعدهٔ «جایگزینِ مربی» ندهد.
با روشن‌شدنِ گره خودکار اجرا می‌شود؛ نتیجه در «آزمونِ خودکارِ سرورِ پردازش» دیده می‌شود.

واقعیت‌ها فقط از docs/chagher/brand-facts-fa.md آمده‌اند.
"""
from . import SelfTest, Spec, Verdict, register
from .ollama import _configured, _text_available, persian_letters, pick_text

FACTS = (
    "«چغر» دستیار هوش مصنوعیِ مربی‌های ورزشی است و برنامهٔ ورزشی و غذاییِ هر ورزشکار را پیش‌نویس می‌کند؛ "
    "تصمیمِ نهایی همیشه با مربی است و چغر جایگزینِ مربی نیست. ثبت‌نام کمتر از یک دقیقه طول می‌کشد و شروعِ آن رایگان است و کارتِ اعتباری نمی‌خواهد."
)

PROMPT = (
    "تو دستیارِ پاسخ‌گوی فروشگاهِ چغر هستی و در پیام‌رسان با مشتری حرف می‌زنی. فقط از این واقعیت‌ها استفاده کن و چیزی از خودت اضافه نکن:\n"
    f"{FACTS}\n"
    "اگر چیزی در واقعیت‌ها نیست (مثل قیمت)، عدد نگو و بگو یکی از همکاران پاسخ می‌دهد.\n\n"
    "پیامِ مشتری: «چغر دقیقاً چیه؟ آیا جای مربی رو می‌گیره؟»\n"
    "یک پاسخِ فارسیِ کوتاه و صمیمی (حداکثر سه جمله) بنویس."
)

DIGITS = set("0123456789۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩")


def build(ctx):
    model = pick_text(ctx.installed_ollama(), _configured("text"))
    return Spec(
        "ollama.generate",
        {"model": model, "prompt": PROMPT, "stream": False, "think": False, "options": {"num_predict": 220, "temperature": 0.2}},
        timeout_s=1500,
    )


def check(ctx, job):
    data = ctx.read_json(job, "ollama.json")
    if not isinstance(data, dict):
        return Verdict.failed("جوابِ ollama.json نرسید.")
    text = str(data.get("response") or (data.get("message") or {}).get("content") or "").strip()
    meta = ctx.meta(job)
    device = meta.get("device", "")
    if persian_letters(text) < 25:
        return Verdict.failed("پاسخِ ربات فارسیِ کافی نبود: «%s»" % text[:80], device=device)
    if any(ch in DIGITS for ch in text):
        return Verdict.failed("ربات عدد آورد (قیمت و آمار نباید از خودِ مدل بیاید): «%s»" % text[:80], device=device)
    if "مربی" not in text:
        return Verdict.failed("پاسخ به پرسش دربارهٔ مربی جواب نداد: «%s»" % text[:80], device=device)
    if "جایگزین" in text and "نیست" not in text and "نمی" not in text:
        return Verdict.failed("ربات وعدهٔ «جایگزینِ مربی» داد: «%s»" % text[:80], device=device)
    return Verdict.passed("«%s» · %s" % ((job.payload or {}).get("model"), text[:90].replace("\n", " ")))


register(SelfTest(
    key="inbox_bot", label="ربات صندوق پیام: پاسخِ فارسی از دانشِ برند", group="text", kind="ollama.generate",
    build=build, check=check, available=_text_available, gpu_required=True, order=32,
    requeue={"kinds": ("ollama.generate", "ollama.chat")},
    describe="یک پرسشِ مشتریِ چغر؛ باید فارسی و کوتاه جواب بدهد، عدد از خودش نیاورد و جایگزینِ مربی نشود",
))
