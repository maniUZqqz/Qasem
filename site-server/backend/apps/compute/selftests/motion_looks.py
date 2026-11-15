"""آزمونِ «سبک‌هایِ تازهٔ موشن (از InstAI)» — یک رندرِ واقعیِ ۳ ثانیه‌ای (۵۴۰×۹۶۰) با سبکِ «موزاییک و کاشی» که از یکی از هشت «نوعِ» تازهٔ موتور (`mosaic`) استفاده می‌کند.

چرا لازم است: گرهٔ ویندوزی موتورِ Remotion را از «بستهٔ موشنِ» سایت می‌گیرد (`nm-motion-pack-<نسخه>.zip`). اگر بسته‌ای قدیمی بماند، موتورِ گره نوعِ پس‌زمینهٔ تازه را
نمی‌شناسد و بی‌سروصدا زمینهٔ ساده می‌کشد — رندر «موفق» است ولی سبک غلط است. این آزمون سه چیز را می‌سنجد (نه حدسِ پیکسلی):
  ۱) ویدیو ۹۰ فریمِ ۵۴۰×۹۶۰ و ۳ ثانیه است (همان سنجشِ `apps.motion.selftest.check`) و `device` غیرِ cpu؛
  ۲) نسخهٔ بسته‌ای که گره با آن رندر کرده (`meta.pack`) همان نسخهٔ آخرین بستهٔ سایت (`nm-motion-pack.json`) است؛
  ۳) بستهٔ خودِ سایت موتورِ تازه را دارد (نشانهٔ `nm-seigaiha` که فقط `looks.tsx` می‌نویسد در فایل‌هایِ bundle هست).
گرهٔ قدیمی که `meta.pack` نمی‌دهد «رد» نمی‌شود، با یادداشت قبول می‌شود (فقط ۱ و ۳ سنجیده شد). نه نوعِ کارِ تازه‌ای هست و نه نصبِ تازه‌ای روی گره.
قراردادِ هم‌ارزِ بدونِ کد: docs/selftests/motion-looks.md."""
import json
from pathlib import Path

from . import SelfTest, Spec, Verdict, register

KIND = "motion.render"
KEY = "studio_motion_looks"
STYLE = "mosaic-tiles"
SPEC = {
    "version": 1, "style": STYLE, "aspect": "9:16", "fps": 30, "lang": "fa", "digits": "auto",
    "brand": {"use_brand_colors": False, "show_logo": False},
    "scenes": [{"type": "title", "duration": 3, "kicker": "سبکِ تازه", "title": "با چغر چغر تر شو", "subtitle": "آزمونِ سبک‌هایِ تازهٔ موشن"}],
}
PAYLOAD = {"composition": "Template", "props": {"spec": SPEC}, "scale": 0.5, "crf": 23, "max_seconds": 10, "title": "motion looks selftest", "style": STYLE,
           "mode": "template", "selftest": True}
#: رشته‌ای که فقط motion/remotion/src/looks.tsx (پس‌زمینهٔ `waves`) می‌نویسد؛ در bundleِ ساخته‌شده به‌صورتِ متن می‌ماند
ENGINE_MARKER = "nm-seigaiha"


def _available(node):
    caps = node.capabilities or {}
    kinds = caps.get("kinds")
    if not isinstance(kinds, list) or KIND not in kinds:
        return False, "عاملِ این سرور نوعِ «%s» را اعلام نکرده است (به‌روزرسانیِ نرم‌افزارِ سرورِ پردازش لازم است)" % KIND
    if not caps.get("motion_render"):
        return False, "ابزارِ موشن روی این سرور خاموش است (NM_MOTION=0)"
    return True, ""


def site_engine_has_new_kinds(bundle_dir) -> bool | None:
    """بستهٔ رندرِ سایت موتورِ تازه را دارد؟ None = bundle هنوز ساخته نشده (نمی‌شود سنجید)."""
    d = Path(bundle_dir) if bundle_dir else None
    if not d or not d.is_dir():
        return None
    files = sorted(d.glob("*.js"))
    if not files:
        return None
    for p in files:
        try:
            if ENGINE_MARKER in p.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def site_pack_version(manifest_path) -> str:
    """نسخهٔ آخرین بستهٔ موشنِ سایت از nm-motion-pack.json ('' اگر نیست)."""
    try:
        return str(json.loads(Path(manifest_path).read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def build(ctx):
    return Spec(KIND, dict(PAYLOAD), timeout_s=1200)


def check(ctx, job):
    from apps.motion import buildlib, runner, selftest

    meta = ctx.meta(job)
    device = str(meta.get("device") or "")
    ok, why = selftest.check(job)
    if not ok:
        return Verdict.failed(why, device=device)
    has = site_engine_has_new_kinds(runner.bundle_dir())
    if has is False:
        return Verdict.failed("بستهٔ رندرِ خودِ سایت موتورِ تازه (نوعِ mosaic و هم‌خانواده‌ها) را ندارد؛ روی سایت `manage.py motion_build` را اجرا کنید تا بسته و `nm-motion-pack.json` تازه شود "
                              "و گره در به‌روزرسانیِ بعدی آن را بگیرد", device=device)
    want = site_pack_version(buildlib.downloads_dir() / buildlib.MANIFEST_NAME)
    got = str(meta.get("pack") or "")
    note = ""
    if want and got and got != want:
        return Verdict.failed("گره با بستهٔ موشنِ قدیمی (%s) رندر کرد ولی آخرین بستهٔ سایت %s است؛ تا گره بستهٔ تازه را نگیرد سبک‌هایِ تازه درست نمی‌آیند "
                              "(به‌روزرسانیِ خودکارِ ابزارِ موشن هر ۳۰ دقیقه manifest را می‌خواند)" % (got, want), device=device)
    if not got:
        note = " · عاملِ قدیمی نسخهٔ بسته را نمی‌گوید"
    if has is None:
        note += " · bundleِ سایت ساخته نشده بود"
    return Verdict.passed("۹۰ فریم · ۵۴۰×۹۶۰ · بستهٔ گره با بستهٔ سایت یکی است (%s)%s" % (got or "؟", note), device=device)


register(SelfTest(key=KEY, label="استودیوی موشن: سبک‌هایِ تازه (موزاییک و کاشی)", group="video", kind=KIND, build=build, check=check,
                  available=_available, gpu_required=True, order=162, requeue={"kinds": (KIND,)},
                  describe="رندرِ ۳ ثانیه‌ایِ سبکِ «موزاییک و کاشی»؛ قبول = گره با آخرین بستهٔ موشنِ سایت (که موتورِ تازه را دارد) رندر کرده است"))
