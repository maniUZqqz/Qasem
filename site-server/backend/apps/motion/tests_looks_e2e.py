"""آزمونِ واقعیِ سی سبکِ تازه از InstAI روی همین سرور (بدونِ ابزارِ ساخته‌شده خودش را رد می‌کند، مثلِ tests_e2e2):

  هر سبک × سه نسبت (۹:۱۶، ۱:۱، ۱۶:۹) × سه صحنه (عنوان، فهرست، دعوت به اقدام) با متنِ واقعیِ «چغر» (docs/chagher/brand-facts-fa.md) فریمِ واقعی می‌دهد
  و از کنترلِ کیفیتِ هندسی/کنتراستِ qa.py **پیش از حلقهٔ اصلاحِ خودکار** بدونِ هیچ خطایی می‌گذرد: یعنی خودِ سبک (پالت، قلم، پس‌زمینه، کارت) درست است،
  نه اینکه اصلاحِ خودکار آن را پنهان کند. هشدارها (warn/info) ثبت می‌شوند و شمرده می‌شوند.

  پیش‌فرض: یک نمونه از هر «نوعِ تازه» (۴ سبک) تا اجرای عادیِ آزمون‌ها سنگین نشود؛  NM_LOOKS_E2E=all ⇒ هر سی سبک؛  NM_LOOKS_IDS=a,b,c ⇒ همین سبک‌ها (هر شناسهٔ کاتالوگ، حتی از ۶۶ تای قدیمی، برای مقایسه)؛
  NM_LOOKS_OUT=<پوشه> ⇒ تصویرها و گزارشِ looks-qa.json آنجا می‌ماند (جدولِ «اندازه‌گیریِ واقعی»ِ سندِ looks-from-instai-fa.md از همین گزارش‌ها ساخته می‌شود:
  python backend/tools/gen_instai_looks.py --update-qa <سند> <پوشه>...).

  اجرا (سنگین است: زیرِ `flock -w 3600 /root/nm-heavy.lock`؛ هر سبک حدودِ ۲ دقیقه):
    cd backend && NM_DATA_DIR=<دادهٔ سایت> MEDIA_ROOT=<رسانهٔ سایت> NM_LOOKS_IDS=manga-ink,tilt-shift NM_LOOKS_OUT=/root/stage/looks-qa ../venv/bin/python -X utf8 manage.py test apps.motion.tests_looks_e2e
  ⚠ تنظیماتِ پروژه زیرِ `manage.py test` «بسته» است (پوشهٔ دادهٔ موقت)؛ بدونِ `NM_DATA_DIR` و `MEDIA_ROOT` صادرشده، بستهٔ رندر پیدا نمی‌شود و آزمون بی‌صدا «رد» می‌شود (skipped).
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.stores.models import Store

from . import catalog, catalog_looks, runner, specs

try:                                    # the geometry / contrast QA is motion v2: a tree without it skips this module (nothing breaks)
    from . import qa, qa_browser
except ImportError:                     # pragma: no cover
    qa = qa_browser = None

User = get_user_model()
OUT = os.environ.get("NM_LOOKS_OUT", "")
MODE = os.environ.get("NM_LOOKS_E2E", "")
ONLY = [x for x in os.environ.get("NM_LOOKS_IDS", "").split(",") if x]
SAMPLE = ("mosaic-tiles", "tilt-shift", "kawaii-pastel", "art-nouveau")        # mosaic, tiltshift, kawaii, ornament

TITLE = {"type": "title", "duration": 3.5, "kicker": "معرفی", "title": "چغر", "subtitle": "دستیارِ هوش مصنوعیِ مربی‌ها؛ پیش‌نویسِ برنامهٔ ورزشی و غذایی در کمتر از یک دقیقه"}
LIST = {"type": "list", "duration": 6, "title": "چهار قدم", "items": ["ثبت‌نام در کمتر از یک دقیقه", "خریدِ توکن", "واردکردنِ اطلاعاتِ مجموعه", "تولیدِ برنامه"], "numbered": True}
CTA = {"type": "cta", "duration": 4, "title": "با چغر چغر تر شو", "button": "شروع رایگان", "note": "بدونِ کارتِ اعتباری"}


def ready() -> bool:
    return runner.site_status()["ready"] and (runner.tools_dir() / "qa.mjs").is_file()


def plan(style: str, aspect: str) -> dict:
    return specs.normalize_spec({"style": style, "aspect": aspect, "fps": 30, "lang": "fa", "platform": "reels" if aspect == "9:16" else "",
                                 "brand": {"use_brand_colors": False, "show_logo": False}, "scenes": [dict(TITLE), dict(LIST), dict(CTA)]})


class NewStylesRender(TestCase):
    def setUp(self):
        if qa is None or qa_browser is None:
            self.skipTest("motion v2 (qa.py / qa_browser.py) is not in this tree")
        if not ready():
            self.skipTest("motion toolchain (bundle + browser + qa.mjs) is not built on this machine (manage.py motion_build)")
        self.media = tempfile.mkdtemp(prefix="nmmotion-looks-")
        self.ov = override_settings(MEDIA_ROOT=self.media)
        self.ov.enable()
        self.owner = User.objects.create_user("motion-looks", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", description="دستیار هوش مصنوعیِ مربی‌ها", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.work = Path(tempfile.mkdtemp(prefix="nmmotion-looks-work-"))

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def test_every_new_style_renders_in_three_aspects_and_the_style_itself_passes_qa(self):
        ids = ONLY or (list(catalog_looks.IDS) if MODE == "all" else list(SAMPLE))
        errors, warns, shots_total, per_style, findings = [], [], 0, {}, []
        lock = runner.SiteLock()
        lock.acquire()
        try:
            for sid in ids:
                row = {"errors": 0, "warnings": 0}
                for aspect in ("9:16", "1:1", "16:9"):
                    spec = plan(sid, aspect)
                    out_dir = Path(OUT) / "qa" / aspect.replace(":", "x") if OUT else None
                    measure = qa_browser.make_measure(self.store, workdir=self.work / f"{sid}-{aspect[0]}", media_dir=out_dir, prefix=sid)
                    shots = measure(spec)
                    shots_total += len(shots)
                    self.assertEqual(len(shots), 2 * len(spec["scenes"]), f"{sid} {aspect}")
                    for s in shots:
                        texts = [b for b in s["boxes"] if b["kind"] == "text" and b["scene"] == s["scene"]]
                        if not texts:
                            errors.append(f"{sid} {aspect} scene {s['scene']}: no text was drawn")
                    for f in qa.geometry_findings(spec, shots):
                        label = f"{sid} {aspect} {spec['scenes'][f['scene']]['type']}: {f['code']} - {f['message']}"
                        findings.append({"style": sid, "aspect": aspect, "scene": spec["scenes"][f["scene"]]["type"], "code": f["code"], "severity": f["severity"], "ratio": f.get("ratio")})
                        if f["severity"] == "error":
                            errors.append(label)
                            row["errors"] += 1
                        else:
                            warns.append(label)
                            row["warnings"] += 1
                per_style[sid] = row
        finally:
            lock.release()
        if OUT:
            Path(OUT).mkdir(parents=True, exist_ok=True)
            (Path(OUT) / "looks-qa.json").write_text(json.dumps({"styles": len(ids), "ids": ids, "shots": shots_total, "errors": errors, "warnings": warns, "per_style": per_style, "findings": findings},
                                                                ensure_ascii=False, indent=1), encoding="utf-8")
        self.assertEqual(errors, [], "\n".join(errors))
        self.assertEqual(shots_total, len(ids) * 3 * 6)
