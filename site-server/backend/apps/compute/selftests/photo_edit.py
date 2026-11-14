"""آزمونِ «ویرایشگرِ عکس» (photo.edit / photo.analyze روی سرویسِ عکسِ گره) — ۱۴۰۵/۰۸/۲۳.

ویرایشگرهای عکسِ پنل (ویرایشِ خودکار، ویرایشِ هوشمند، تحلیل) همه از همین دو نوع کار می‌گذرند و تا امروز هیچ آزمونِ پذیرشی نداشتند؛ کارهایِ
منتظرِ مالک (photo.edit / photo.analyze در صف) هم با قبول شدنِ این آزمون خودشان راه می‌افتند (requeue برای شکست‌های ناشی از گره).

  * photo_edit    — ویرایشِ خودکارِ کیت روی یک عکسِ ساختگی (سوژه روی زمینه)؛ خروجی باید تصویرِ سالم، نه خالی و نه تک‌رنگ باشد.
  * photo_analyze — تحلیلِ همان عکس؛ analyze.json باید یک شیءِ پُر باشد (اختیاری: ساختارش به کیت بستگی دارد).
سرویسِ عکس را اگر خاموش باشد و سوئیچِ خودکار روشن باشد خودِ عامل بالا می‌آورد (caps_ok)."""
import io

from . import SelfTest, Spec, Verdict, caps_ok, png, register

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _available(node):
    return caps_ok(node, "photo", why="سرویسِ ویرایشگرِ عکس روی این سرور نیست")


def build_edit(ctx):
    return Spec("photo.edit", {"image": "selftest.png", "auto": True, "recipe": {"output": {"format": "png"}}},
                files={"selftest.png": png("subject", 320)}, timeout_s=600)


def check_edit(ctx, job):
    outs = [o for o in job.outputs() if str(o.get("name", "")).lower().endswith(IMAGE_EXT)]
    if not outs:
        return Verdict.failed("هیچ تصویری از ویرایشگرِ عکس نرسید (خروجی‌ها: %s)" % (", ".join(str(o.get("name")) for o in job.outputs()) or "هیچ"))
    raw = ctx.read_output(job, outs[0]["name"])
    if not raw:
        return Verdict.failed("فایلِ %s خالی است" % outs[0]["name"])
    try:
        from PIL import Image, ImageStat

        im = Image.open(io.BytesIO(raw))
        im.load()
        w, h = im.size
        spread = max(ImageStat.Stat(im.convert("L")).stddev)
    except Exception as exc:  # noqa: BLE001
        return Verdict.failed("تصویرِ خروجی خوانده نشد: %s" % exc)
    if w < 64 or h < 64:
        return Verdict.failed("تصویرِ خروجی خیلی کوچک است (%d×%d)" % (w, h))
    if spread < 2:
        return Verdict.failed("تصویرِ خروجی تک‌رنگ است (انحراف %.1f)؛ ویرایش چیزی نساخته" % spread)
    return Verdict.passed("تصویرِ %d×%d سالم · %s ثانیه" % (w, h, job.run_s if job.run_s is not None else "؟"))


def build_analyze(ctx):
    return Spec("photo.analyze", {"image": "selftest.png"}, files={"selftest.png": png("subject", 320)}, timeout_s=600)


def check_analyze(ctx, job):
    data = ctx.read_json(job, "analyze.json")
    if not isinstance(data, dict) or not data:
        return Verdict.failed("analyze.json خالی است یا خوانده نشد")
    return Verdict.passed("تحلیل رسید (%d کلید: %s)" % (len(data), "، ".join(list(data)[:6])))


register(SelfTest(key="photo_edit", label="ویرایشگرِ عکس: ویرایشِ خودکار", group="image", kind="photo.edit", build=build_edit, check=check_edit,
                  available=_available, order=52, requeue={"kinds": ("photo.edit",)},
                  describe="عکسِ ساختگی (دایرهٔ آبی روی زمینهٔ نارنجی) با ویرایشِ خودکارِ کیتِ عکس"))
register(SelfTest(key="photo_analyze", label="ویرایشگرِ عکس: تحلیلِ تصویر", group="image", kind="photo.analyze", build=build_analyze, check=check_analyze,
                  available=_available, optional=True, order=53, requeue={"kinds": ("photo.analyze",)},
                  describe="همان عکس؛ analyze.json باید یک شیءِ پُر باشد"))
