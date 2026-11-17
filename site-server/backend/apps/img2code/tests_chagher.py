# -*- coding: utf-8 -*-
"""سنجشِ واقعی با محصولِ مالک، «چغر»: از صفحهٔ فرودِ واقعیِ فارسی عکس بگیر ⇒ تبدیل ⇒ پیش‌نویسِ سایت‌ساز ⇒ بسنج که متنِ فارسی **متنِ واقعی**، **درست‌چسبیده** و **به ترتیبِ درست** آمده است.

فقط برای سنجش است: هیچ تصویر/متنی از صفحه در مخزن ذخیره نمی‌شود (خروجی‌ها فقط در IMG2CODE_SHOTS روی سرور می‌ماند). اجرا:

    cd backend && IMG2CODE_CHAGHER_URL=https://chagher.ir/ IMG2CODE_SHOTS=/root/stage/mv2nm-chagher PLAYWRIGHT_BROWSERS_PATH=/opt/up3d-uitest/browsers \\
        flock -w 3600 /root/nm-heavy.lock ../venv/bin/python -X utf8 manage.py test apps.img2code.tests_chagher --noinput

معیارها (همه از روی خودِ صفحه، نه حدس): خط‌های متنِ DOM (حقیقتِ زمینه) در برابرِ متنِ بلوک‌های پیش‌نویس؛ ترتیبِ خواندن؛ نبودنِ نویسهٔ «شکل‌های نمایشی» (متنِ از قبل چسبانده/وارونه)؛
شباهتِ رندرِ پیش‌نویس به عکسِ اصلی؛ و برای مقایسه، همان عکس با OCR (مسیرِ تصویرِ بارگذاری‌شده) تا کیفیتِ OCR صادقانه گزارش شود.
"""
import difflib
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.projects.models import Design, Page, Project, SiteTheme
from apps.stores.models import Store

from . import services, tasks
from .models import Conversion

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
URL = os.environ.get("IMG2CODE_CHAGHER_URL", "")
SHOTS = os.environ.get("IMG2CODE_SHOTS", "")
PRESENTATION = re.compile(r"[ﭐ-﷿ﹰ-﻿]")
INVISIBLE = re.compile(r"[‌‍‎‏⁦-⁩‪-‮]")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", INVISIBLE.sub("", s or "")).strip()


def squash(s: str) -> str:
    """برای هم‌خوانی: بدونِ فاصله و نیم‌فاصله (mv2code پیش از «تر/ترین/ها» نیم‌فاصله می‌گذارد؛ املا است، نه غلط)."""
    return re.sub(r"[\s\u200c\u200d\u200e\u200f\u2066-\u2069]", "", s or "")


def walk(blocks):
    for b in blocks or []:
        yield b
        yield from walk(b.get("children"))


def block_texts(doc):
    """متنِ بلوک‌ها به ترتیبِ سند (HTML ِ «متن» به متنِ ساده)."""
    import html as H
    out = []
    for b in walk((doc or {}).get("blocks")):
        p = b["props"]
        if b["type"] == "heading":
            out.append(p["text"])
        elif b["type"] == "text":
            out.append(H.unescape(re.sub(r"<[^>]+>", " ", p["html"])))
        elif b["type"] == "button":
            out.append(p["text"])
        elif b["type"] == "site_header":
            out.append(p.get("btn", ""))
    return [norm(x) for x in out if norm(x)]


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


@unittest.skipUnless(URL, "سنجشِ «چغر» فقط با IMG2CODE_CHAGHER_URL")
class ChagherCheck(TestCase):
    databases = {"default", "studio"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-i2c-chagher-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.o = override_settings(NM_DATA_DIR=self.tmp / "data", WORKSPACES_ROOT=self.tmp / "work")
        self.o.enable()
        self.addCleanup(self.o.disable)
        (self.tmp / "work").mkdir(parents=True, exist_ok=True)
        eng = services.engine_status(refresh=True)
        if not (eng["ready"] and eng["compare_ok"]):
            self.skipTest("موتور یا مرورگر آماده نیست: %s" % eng["messages"])
        self.staff = User.objects.create_user("chagher-staff", password="x", is_staff=True)
        self.store = Store.objects.create(owner=self.staff, name="چغر")
        self.client = APIClient()
        self.client.force_authenticate(self.staff)
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)

    def convert(self, **body):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post("/api/v1/stores/%d/image-to-code/" % self.store.pk, body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        conv = Conversion.objects.get(pk=r.json()["item"]["id"])
        self.assertEqual(conv.state, "READY", conv.error)
        return conv

    def render_draft(self, project, page) -> Path:
        """پیش‌نویس با همان رندرکنندهٔ سایت‌ساز ⇒ HTML ِ کامل ⇒ عکس با Chromium."""
        from apps.projects.builder import canvas, theme as theme_mod
        from playwright.sync_api import sync_playwright
        design = Design.objects.get(project=project, page=page)
        theme = SiteTheme.objects.get(project=project).draft
        out = canvas.render_canvas(project, "page", page, design.draft, theme_mod.clean_theme(theme, project), SiteTheme.objects.get(project=project).menu)
        media_dir = Path(project.path) / "static" / "site-media"
        fonts_dir = Path(__file__).resolve().parents[1] / "projects" / "builder" / "assets" / "fonts"
        html = ('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>%s\n%s</style></head><body>%s\n<main>%s</main>%s</body></html>'
                % (out["base_css"], out["page_css"], out["header"], "\n".join(p["html"] for p in out["parts"]), out["footer"]))
        html = html.replace("/api/v1/studio/builder-media/%s/" % project.slug, media_dir.as_uri() + "/").replace("/api/v1/studio/builder-fonts/", fonts_dir.as_uri() + "/")
        f = self.tmp / "draft.html"
        f.write_text(html, encoding="utf-8")
        png = self.tmp / "draft.png"
        with sync_playwright() as pw:
            b = pw.chromium.launch(args=["--no-sandbox", "--allow-file-access-from-files"])
            try:
                pg = b.new_page(viewport={"width": 1280, "height": 900})
                pg.goto(f.as_uri(), wait_until="load")
                pg.evaluate("document.fonts && document.fonts.ready")
                pg.wait_for_timeout(500)
                pg.screenshot(path=str(png), full_page=True)
                self.rendered_text = pg.evaluate("document.body.innerText")
            finally:
                b.close()
        return png

    def test_chagher_landing_page_to_site_builder_draft(self):
        import cv2
        import numpy as np
        from mv2code.refine import ssim_gray
        conv = self.convert(url=URL, mode="responsive", lang="fa", width=1280, dom_text=True, title="چغر — سنجش")
        truth = [norm(x["text"]) for x in json.loads((conv.dir / "lines.json").read_text(encoding="utf-8"))]
        truth = [t for t in truth if t]
        self.assertGreater(len(truth), 20, "متنِ صفحه از DOM خوانده نشد")
        self.assertGreater(sum(1 for t in truth if re.search(r"[؀-ۿ]", t)), 10, "صفحه باید متنِ فارسیِ واقعی داشته باشد")

        r = self.client.post("/api/v1/stores/%d/image-to-code/%d/site-draft/" % (self.store.pk, conv.pk), {}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        out = r.json()
        project = Project.objects.get(slug=out["project_slug"])
        page = Page.objects.get(pk=out["page_id"])
        design = Design.objects.get(project=project, page=page)
        self.assertIsNone(design.published)
        header = Design.objects.get(project=project, target="header")
        footer = Design.objects.get(project=project, target="footer")
        menu = [m["label"] for m in SiteTheme.objects.get(project=project).menu]
        title = norm(project.site_title)
        got = ([title] if title else []) + [norm(m) for m in menu] + block_texts(header.draft) + block_texts(design.draft) + block_texts(footer.draft)

        # ۱) هر خطِ متنِ صفحه، عیناً (به‌جز نشانه‌های جهت) در پیش‌نویس هست
        gotsq = [squash(x) for x in got]
        joined = "|".join(gotsq)
        exact = [t for t in truth if squash(t) in joined]
        coverage = len(exact) / len(truth)
        missing = [t for t in truth if t not in exact]
        # ۲) متنِ فارسی چسبیده/وارونه ذخیره نشده
        pres = [t for t in got if PRESENTATION.search(t)]
        # ۳) ترتیبِ خواندن: ترتیبِ خط‌های صفحه (بالا به پایین، راست به چپ) با ترتیبِ پیش‌نویس
        lines = [x for x in json.loads((conv.dir / "lines.json").read_text(encoding="utf-8")) if norm(x["text"])]
        # متنِ تکراری (منو هم در سربرگ هست هم در پابرگ): k‌امین دفعه‌ای که در صفحه (بالا به پایین) دیده می‌شود با k‌امین جای پیش‌نویس جفت می‌شود
        where = {}
        for i, g in enumerate(gotsq):
            where.setdefault(g, []).append(i)
        seen_count = {}
        matched = []
        for x in sorted(lines, key=lambda x: (round(x["box"][1] / 12.0), -x["box"][0])):
            key = squash(x["text"])
            if key not in where:
                continue
            k = seen_count.get(key, 0)
            seen_count[key] = k + 1
            matched.append((where[key][min(k, len(where[key]) - 1)], x["box"]))
        # (الف) بالا به پایین: بلوکی که در صفحه بالاتر است در پیش‌نویس هم زودتر بیاید
        vp = [(i, y[1]) for i, y in matched]
        pairs_v = bad_v = 0
        for a in range(len(vp)):
            for b in range(a + 1, len(vp)):
                if abs(vp[a][1] - vp[b][1]) > 24:
                    pairs_v += 1
                    first_a = vp[a][0] < vp[b][0]
                    if first_a != (vp[a][1] < vp[b][1]):
                        bad_v += 1
        vertical_order = 1 - bad_v / max(1, pairs_v)
        # (ب) در یک ردیف راست‌به‌چپ: چپ‌تر دیرتر بیاید
        pairs_h = bad_h = 0
        for a in range(len(matched)):
            for b in range(a + 1, len(matched)):
                ba, bb = matched[a][1], matched[b][1]
                if abs((ba[1] + ba[3] / 2) - (bb[1] + bb[3] / 2)) <= 10 and abs(ba[0] - bb[0]) > 20:
                    pairs_h += 1
                    if (matched[a][0] < matched[b][0]) != (ba[0] > bb[0]):
                        bad_h += 1
        row_order = 1 - bad_h / max(1, pairs_h)
        order_score = min(vertical_order, row_order)

        # ۴) رندرِ واقعیِ پیش‌نویس و شباهتش به عکسِ اصلی
        draft_png = self.render_draft(project, page)
        orig = cv2.cvtColor(cv2.imread(str(conv.out_dir / "original.png")), cv2.COLOR_BGR2RGB)
        drafted = cv2.cvtColor(cv2.imread(str(draft_png)), cv2.COLOR_BGR2RGB)
        h = min(orig.shape[0], drafted.shape[0])
        ssim = float(ssim_gray(orig, drafted))
        # ۵) متنِ رندرشده (همان چیزی که بیننده می‌خواند) همهٔ خط‌های فارسی را دارد
        rendered = squash(self.rendered_text)
        in_dom = sum(1 for t in truth if squash(t) in rendered) / len(truth)

        # ۵ب) همین تبدیل در «طراحیِ UI» (استودیوی طراحی): متنِ فارسی همان‌جا هم واقعی و کامل است
        with override_settings(IMG2CODE_UI_DESIGN=True):
            r_ui = self.client.post("/api/v1/stores/%d/image-to-code/%d/ui-design/" % (self.store.pk, conv.pk), {}, format="json")
        self.assertEqual(r_ui.status_code, 201, r_ui.content)
        from apps.design_studio.models import DesignDoc
        ui_doc = DesignDoc.objects.get(pk=r_ui.json()["doc_id"])
        ui_flat = squash(json.dumps(ui_doc.data["frames"][0]["children"], ensure_ascii=False))
        ui_coverage = sum(1 for t in truth if squash(t) in ui_flat) / len(truth)

        # ۶) برای مقایسه: همان عکس از مسیرِ «بارگذاری» (OCR ِ Tesseract)
        with open(conv.dir / "source.png", "rb") as fh:
            from django.core.files.uploadedfile import SimpleUploadedFile
            with self.captureOnCommitCallbacks(execute=True):
                r2 = self.client.post("/api/v1/stores/%d/image-to-code/" % self.store.pk, {"image": SimpleUploadedFile("chagher.png", fh.read(), "image/png"), "lang": "fa"}, format="multipart")
        conv2 = Conversion.objects.get(pk=r2.json()["item"]["id"])
        ocr_tree = json.loads((conv2.out_dir / "tree.json").read_text(encoding="utf-8"))
        ocr_texts = []

        def collect(n):
            if n.get("role") == "text":
                ocr_texts.append(norm(n.get("text", "")))
            for c in n.get("children", []):
                collect(c)
        collect(ocr_tree)
        ocr_clean = [squash(x) for x in ocr_texts if x]
        ocr_char_sim = sum(max([similarity(squash(t), o) for o in ocr_clean] or [0.0]) for t in truth) / len(truth)
        ocr_exact = sum(1 for t in truth if squash(t) in ocr_clean) / len(truth)

        report = {
            "dom_text_lines": len(truth), "exact_coverage": round(coverage, 4), "missing": missing[:12], "presentation_form_lines": len(pres), "reading_order": {"top_to_bottom": round(vertical_order, 4), "right_to_left_in_row": round(row_order, 4), "row_pairs": pairs_h},
            "rendered_text_has_all_lines": round(in_dom, 4), "ui_design_exact_coverage": round(ui_coverage, 4), "draft_vs_original_ssim": round(ssim, 4), "draft_blocks": out["stats"].get("blocks"), "draft_images": out["stats"].get("images"),
            "ocr_path": {"exact_line_match": round(ocr_exact, 4), "char_similarity": round(ocr_char_sim, 4), "note": "تصویرِ بارگذاری‌شده با Tesseract (بدونِ DOM)"},
            "conversion_scores": {s["key"]: s["display"] for s in conv.scores}, "warnings": out["warnings"],
        }
        print("\nCHAGHER-REPORT " + json.dumps(report, ensure_ascii=False))
        if SHOTS:
            shutil.rmtree(Path(SHOTS) / "chagher-conv", ignore_errors=True)
            shutil.copytree(conv.dir, Path(SHOTS) / "chagher-conv")
            (Path(SHOTS) / "chagher-draft-texts.json").write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
            (Path(SHOTS) / "chagher-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            shutil.copy2(conv.out_dir / "original.png", Path(SHOTS) / "chagher-original.png")
            shutil.copy2(draft_png, Path(SHOTS) / "chagher-draft.png")
            for name in ("rendered.png",):
                if (conv.out_dir / name).exists():
                    shutil.copy2(conv.out_dir / name, Path(SHOTS) / "chagher-converted.png")

        self.assertGreaterEqual(coverage, 0.97, "خط‌های گم‌شده: %s" % missing[:8])
        self.assertEqual(pres, [], "متنِ فارسیِ چسبیده/وارونه ذخیره شده")
        self.assertGreaterEqual(vertical_order, 0.95)
        self.assertGreaterEqual(row_order, 0.9)
        self.assertGreaterEqual(in_dom, 0.95)
        self.assertGreaterEqual(ui_coverage, 0.97, "طرحِ UI متنِ صفحه را کم دارد")
        self.assertGreaterEqual(ssim, 0.55)
        _ = (h, np, order_score)
