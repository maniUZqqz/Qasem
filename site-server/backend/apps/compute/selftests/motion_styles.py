"""آزمونِ «سبکِ تازه‌ی موشن» (سبکِ شخصیِ کاربر) — یک رندرِ واقعیِ ۳ ثانیه‌ای (۵۴۰×۹۶۰) با یک سبکِ ساختگیِ بنفشِ تک‌رنگ که همراهِ خودِ طرح (`spec.style_def`) می‌رود.

چرا لازم است: سبکِ شخصی در کاتالوگِ بستهٔ گره نیست؛ موتور آن را از خودِ طرح می‌خواند. اگر بستهٔ موشنِ گره قدیمی بماند، موتور `style_def` را نمی‌شناسد و بی‌سروصدا
سبکِ پیش‌فرض را می‌کشد — رندر «موفق» است ولی سبک غلط است (و کاربر ویدیویی می‌گیرد که سبکش نیست). این آزمون چهار چیز را می‌سنجد (نه حدسِ پیکسلی):
  ۱) ویدیو ۹۰ فریمِ ۵۴۰×۹۶۰ و ۳ ثانیه است و `device` غیرِ cpu (همان سنجشِ `apps.motion.selftest.check`)؛
  ۲) **پیکسلِ گوشهٔ ویدیو همان رنگِ زمینهٔ سبکِ ساختگی است** (بنفشِ #6a1b9a؛ هیچ سبکِ کاتالوگ چنین زمینه‌ای ندارد) ⇒ موتورِ گره واقعاً سبکِ شخصی را کشیده؛
  ۳) نسخهٔ بسته‌ای که گره با آن رندر کرده (`meta.pack`) همان نسخهٔ آخرین بستهٔ سایت (`nm-motion-pack.json`) است و `meta.pack_features` شاملِ `style_def` است؛
  ۴) بستهٔ خودِ سایت موتورِ تازه را دارد (نشانهٔ `data-nm-style-def` در فایل‌هایِ bundle).
گرهٔ قدیمی (عاملی که `pack_features` نمی‌دهد) «رد» نمی‌شود، با یادداشت قبول می‌شود، به شرطِ اینکه ۱ و ۲ درست باشند. نه نوعِ کارِ تازه‌ای هست و نه نصبِ تازه‌ای روی گره:
بستهٔ موشن خودکار به‌روز می‌شود و کارِ سبکِ شخصی روی بستهٔ قدیمی رد و دوباره امتحان می‌شود (processing/motion_jobs.py).
قراردادِ هم‌ارزِ بدونِ کد: docs/selftests/motion-styles.md."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import SelfTest, Spec, Verdict, register

KIND = "motion.render"
KEY = "studio_motion_styles"
STYLE_ID = "u0-selftest"
BG = "#6a1b9a"                                   # purple: no catalogue style draws this background
STYLE_DEF = {
    "id": STYLE_ID, "name_fa": "آزمون", "name_en": "Selftest", "inspired": None, "group": "custom", "about": "",
    "palette": {"bg": BG, "bg2": "#4a148c", "ink": "#ffffff", "paper": "#ffffff", "accent": "#ffd54f", "accent2": "#80deea", "accent3": "#ff8a80", "muted": "#e1bee7"},
    "font": {"latin": "vazirmatn", "fa": "vazirmatn", "weight": 700, "body_latin": None, "body_fa": None, "case": "none", "track": 0, "lh": 1.3},
    "bg": {"kind": "solid", "c": "bg"}, "bg2": None, "tex": [], "decor": [], "text": {"fx": "plain"},
    "shape": {"radius": 16, "border": 0, "shadow": "none", "fill": "paper"},
    "motion": {"enter": "fade", "spring": [30, 120, 1.0], "stagger": 6, "stepFps": None, "wobble": 0, "cam": None, "ease": "out-expo"},
    "trans": {"kind": "fade", "frames": 12}, "fx": {},
}
SPEC = {
    "version": 2, "style": STYLE_ID, "style_def": STYLE_DEF, "aspect": "9:16", "fps": 30, "lang": "fa", "digits": "auto",
    "brand": {"use_brand_colors": False, "show_logo": False},
    "scenes": [{"type": "title", "duration": 3, "kicker": "سبکِ شخصی", "title": "با چغر چغر تر شو", "subtitle": "آزمونِ سبکِ تازه"}],
}
PAYLOAD = {"composition": "Template", "props": {"spec": SPEC}, "scale": 0.5, "crf": 23, "max_seconds": 10, "title": "motion style selftest", "style": STYLE_ID,
           "mode": "template", "selftest": True}
#: رشته‌ای که فقط Template.tsx (برای سبکِ دارای style_def) می‌نویسد؛ در bundleِ ساخته‌شده به‌صورتِ متن می‌ماند
ENGINE_MARKER = "data-nm-style-def"


def _available(node):
    caps = node.capabilities or {}
    kinds = caps.get("kinds")
    if not isinstance(kinds, list) or KIND not in kinds:
        return False, "عاملِ این سرور نوعِ «%s» را اعلام نکرده است (به‌روزرسانیِ نرم‌افزارِ سرورِ پردازش لازم است)" % KIND
    if not caps.get("motion_render"):
        return False, "ابزارِ موشن روی این سرور خاموش است (NM_MOTION=0)"
    return True, ""


def site_engine_has_style_def(bundle_dir) -> bool | None:
    """بستهٔ رندرِ سایت سبکِ شخصی را می‌شناسد؟ None = bundle هنوز ساخته نشده."""
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
    try:
        return str(json.loads(Path(manifest_path).read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def corner_pixel(video: Path, at: float = 1.5):
    """رنگِ پیکسلِ نزدیکِ گوشهٔ بالا-راستِ ویدیو در لحظهٔ `at` (برچسبِ لوگو بالا-چپ است؛ گوشهٔ دیگر همیشه زمینه است). ⇒ (r, g, b) یا None."""
    ff = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
    try:
        p = subprocess.run([ff, "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-vf", "crop=8:8:500:12", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    raw = p.stdout
    if len(raw) < 8 * 8 * 3:
        return None
    px = [raw[i:i + 3] for i in range(0, 8 * 8 * 3, 3)]
    return tuple(sum(c[k] for c in px) // len(px) for k in range(3))


def _near(a, b, tol=22) -> bool:
    return a is not None and all(abs(int(a[k]) - int(b[k])) <= tol for k in range(3))


def build(ctx):
    return Spec(KIND, json.loads(json.dumps(PAYLOAD)), timeout_s=1200)


def check(ctx, job):
    from apps.compute import services as CS
    from apps.motion import buildlib, runner, selftest

    meta = ctx.meta(job)
    device = str(meta.get("device") or "")
    ok, why = selftest.check(job)
    if not ok:
        return Verdict.failed(why, device=device)
    want = tuple(int(BG[i:i + 2], 16) for i in (1, 3, 5))
    try:
        got = corner_pixel(CS.output_path(job, "out.mp4"))
    except Exception:  # noqa: BLE001
        got = None
    if got is None:
        return Verdict.failed("فریمِ ویدیو خوانده نشد؛ نمی‌شود دید سبکِ شخصی کشیده شده یا نه", device=device)
    if not _near(got, want):
        return Verdict.failed("پیکسلِ زمینهٔ ویدیو %s است ولی سبکِ آزمون زمینهٔ %s (بنفش) دارد: موتورِ گره سبکِ شخصی (style_def) را نکشیده و سبکِ پیش‌فرض را کشیده؛ "
                              "بستهٔ موشنِ گره قدیمی است. روی سایت `manage.py motion_build` را اجرا کنید تا بستهٔ تازه بیاید و گره در به‌روزرسانیِ بعدی آن را بگیرد"
                              % ("#%02x%02x%02x" % got, BG), device=device)
    has = site_engine_has_style_def(runner.bundle_dir())
    if has is False:
        return Verdict.failed("بستهٔ رندرِ خودِ سایت سبکِ شخصی را نمی‌شناسد؛ روی سایت `manage.py motion_build` را اجرا کنید تا بسته و `nm-motion-pack.json` تازه شود", device=device)
    wantv = site_pack_version(buildlib.downloads_dir() / buildlib.MANIFEST_NAME)
    gotv = str(meta.get("pack") or "")
    note = ""
    if wantv and gotv and gotv != wantv:
        return Verdict.failed("گره با بستهٔ موشنِ قدیمی (%s) رندر کرد ولی آخرین بستهٔ سایت %s است؛ تا گره بستهٔ تازه را نگیرد سبک‌های شخصی ممکن است درست نیایند" % (gotv, wantv), device=device)
    feats = meta.get("pack_features")
    if feats is None:
        note = " · عاملِ قدیمی ویژگی‌های بسته را نمی‌گوید"
    elif "style_def" not in feats:
        return Verdict.failed("بستهٔ گره ویژگیِ style_def را اعلام نکرده است", device=device)
    if has is None:
        note += " · bundleِ سایت ساخته نشده بود"
    return Verdict.passed("۹۰ فریم · ۵۴۰×۹۶۰ · زمینهٔ بنفشِ سبکِ شخصی روی پیکسل‌ها دیده شد · بسته %s%s" % (gotv or "؟", note), device=device)


register(SelfTest(key=KEY, label="استودیوی موشن: سبکِ تازهٔ شخصی (style_def)", group="video", kind=KIND, build=build, check=check,
                  available=_available, gpu_required=True, order=163, requeue={"kinds": (KIND,)},
                  describe="رندرِ ۳ ثانیه‌ایِ یک سبکِ ساختگیِ بنفش که همراهِ طرح می‌رود؛ قبول = زمینهٔ بنفش روی پیکسل‌های ویدیو دیده شد (موتورِ گره سبکِ شخصی را می‌کشد)"))
