"""بازبینیِ کیفیتِ ۱۴ آبان — ادیتورِ عکس:
 - هشدارهای «کیفیتِ عکس» روی طرحِ گرافیکی (اسلاید) نمی‌افتد، روی عکسِ واقعی همچنان می‌افتد؛
 - دستورِ مدیریتیِ بازحسابِ هشدارها ایدمپوتنت است؛
 - خروجیِ «قالبِ دیگر» وقتی از ۱۲۸۰ پیکسل کوچک‌تر شده این را صادقانه می‌گوید؛
 - مثال‌های دستورِ طراحِ خودکار از فروشگاه ساخته می‌شود و هیچ قیمت یا تخفیفی ندارد.
"""
import io
from io import StringIO
from urllib.parse import unquote

import numpy as np
from django.core.management import call_command
from django.test import SimpleTestCase
from PIL import Image, ImageDraw, ImageFont

from apps.products.models import Product

from . import examples, ops, services
from .models import PhotoAsset
from .tests import ApiTestBase, photo


def slide(w=1080, h=1350, top=(12, 28, 60), bottom=(17, 36, 72)) -> Image.Image:
    """اسلایدِ طراحی‌شده: گرادیانِ ملایمِ سرمه‌ای + متنِ درشتِ سفید + یک کادرِ رنگی (بی نویز، مثلِ خروجیِ رندرِ طراح)."""
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    a = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
    img = Image.fromarray(np.repeat(a, w, axis=1).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.load_default(size=max(24, w // 9))
    except TypeError:    # Pillow قدیمی
        f = ImageFont.load_default()
    d.text((w * 0.1, h * 0.3), "CHAGHER", fill=(255, 255, 255), font=f)
    d.text((w * 0.1, h * 0.45), "PLAN IN ONE MINUTE", fill=(255, 255, 255), font=f)
    d.rounded_rectangle([w * 0.1, h * 0.75, w * 0.55, h * 0.83], radius=18, fill=(30, 200, 190))
    return img


class GraphicDetectionTests(SimpleTestCase):
    def kinds(self, img):
        return {f["what"] for f in ops.findings(ops.measure(img))}

    def test_designed_slide_is_graphic_and_gets_no_photo_warnings(self):
        s = slide()
        m = ops.measure(s)
        self.assertTrue(m["graphic"], m)
        self.assertLess(m["p50"], 80, "این اسلاید واقعاً تیره‌ی عددی است؛ قبلاً «تیره» می‌خورد")
        self.assertEqual(self.kinds(s), set())

    def test_flat_background_upload_is_graphic(self):
        flat = Image.new("RGB", (1440, 1920), (20, 150, 160))
        self.assertTrue(ops.measure(flat)["graphic"])
        self.assertEqual(self.kinds(flat), set())

    def test_graphic_keeps_size_warnings(self):
        small = slide(600, 600)
        k = self.kinds(small)
        self.assertEqual(k, {"small"})

    def test_real_photo_still_gets_its_warnings(self):
        dark = photo(dark=True)
        m = ops.measure(dark)
        self.assertFalse(m["graphic"], m)
        self.assertIn("dark", self.kinds(dark))

    def test_noisy_photo_on_white_background_is_not_graphic(self):
        studio = photo(plain=True)             # زمینهٔ سفید + نویزِ حسگر
        m = ops.measure(studio)
        self.assertFalse(m["graphic"], m)
        self.assertIn("plain_bg", self.kinds(studio))

    def test_photo_like_gradient_with_texture_is_not_graphic(self):
        rng = np.random.default_rng(7)
        h, w = 900, 1200
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        base = 110 + 60 * np.sin(xx / 61) * np.cos(yy / 47)
        rgb = np.stack([base, base * 0.8 + 20, base * 0.6 + 40], axis=2) + rng.normal(0, 6, (h, w, 3))
        img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
        self.assertFalse(ops.measure(img)["graphic"])

    def test_transparent_cutout_is_judged_on_opaque_pixels(self):
        cut = photo(alpha=True)
        self.assertFalse(ops.measure(cut)["graphic"])
        empty = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        self.assertFalse(ops.graphic_like(empty))


class FindingsStoredTests(ApiTestBase):
    def test_upload_of_slide_stores_graphic_and_no_findings_but_photo_keeps_them(self):
        s_id, p_id = self.upload(slide(), photo(dark=True))
        s, p = PhotoAsset.objects.get(pk=s_id), PhotoAsset.objects.get(pk=p_id)
        self.assertTrue(s.facts["graphic"])
        self.assertEqual(s.findings, [])
        self.assertFalse(p.facts["graphic"])
        self.assertIn("dark", {f["what"] for f in p.findings})
        body = self.api.get(f"{self.base}/").json()
        by_id = {a["id"]: a for a in body["assets"]}
        self.assertEqual(by_id[s_id]["findings"], [])

    def test_suggest_plan_for_a_slide_does_not_try_to_fix_it(self):
        (aid,) = self.upload(slide())
        r = self.api.post(f"{self.base}/plan/", {"asset": aid, "recipe": "suggest"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        tools = [o["tool"] for o in r.json()["operations"]]
        self.assertNotIn("auto_tone", tools)
        self.assertNotIn("kit_auto", tools)


class ReanalyzeCommandTests(ApiTestBase):
    def stale(self):
        (aid,) = self.upload(slide())
        a = PhotoAsset.objects.get(pk=aid)
        # حالتِ قدیمی: facts بی‌«graphic» و هشدارهای تیره/کم‌کنتراست
        facts = {k: v for k, v in a.facts.items() if k != "graphic"}
        a.facts = facts
        a.findings = [{"what": "dark", "note": "عکس تیره است", "value": 40}, {"what": "flat", "note": "کم‌کنتراست", "value": 20}]
        a.save()
        return a

    def run_cmd(self, *args):
        out = StringIO()
        call_command("photoedit_reanalyze_findings", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing_then_real_run_clears_and_is_idempotent(self):
        a = self.stale()
        text = self.run_cmd("--dry-run")
        self.assertIn("تغییر می‌کند 1", text)
        a.refresh_from_db()
        self.assertEqual(len(a.findings), 2)
        text = self.run_cmd()
        self.assertIn("تغییر کرد 1", text)
        a.refresh_from_db()
        self.assertEqual(a.findings, [])
        self.assertTrue(a.facts["graphic"])
        self.assertIn("تغییر کرد 0", self.run_cmd())

    def test_real_photos_keep_their_findings_and_missing_files_are_skipped(self):
        (pid,) = self.upload(photo(dark=True))
        before = list(PhotoAsset.objects.get(pk=pid).findings)
        ghost = PhotoAsset.objects.create(store=self.store, title="بی‌فایل", original="photoedit/none.jpg")
        self.assertIn("بی‌فایل 1", self.run_cmd())
        self.assertEqual(PhotoAsset.objects.get(pk=pid).findings, before)
        self.assertEqual(PhotoAsset.objects.get(pk=ghost.pk).findings, [])


class ExportCapNoteTests(ApiTestBase):
    def make_project(self, w, h):
        (aid,) = self.upload(photo(w, h))
        r = self.api.post(f"{self.base}/projects/", {"asset": aid, "title": "پروژه", "data": {"layers": []}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["project"]["id"]

    def test_big_source_export_says_it_is_capped_in_the_note_and_header(self):
        pid = self.make_project(1700, 1300)
        for fmt in ("tiff", "pdf", "png"):
            r = self.api.get(f"{self.base}/projects/{pid}/export/?fmt={fmt}")
            self.assertEqual(r.status_code, 200, (fmt, r.content[:200]))
            note = unquote(r["X-Export-Notes"])
            self.assertIn(services.EXPORT_CAP_NOTE, note, fmt)
        self.assertIn("۱۲۸۰", services.EXPORT_CAP_NOTE)
        self.assertIn("ساخت و ذخیره", services.EXPORT_CAP_NOTE)

    def test_small_source_export_has_no_cap_note(self):
        pid = self.make_project(800, 600)
        r = self.api.get(f"{self.base}/projects/{pid}/export/?fmt=tiff")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(services.EXPORT_CAP_NOTE, unquote(r["X-Export-Notes"]))

    def test_export_project_direct_note_is_first(self):
        from .models import PhotoProject

        pid = self.make_project(2000, 1500)
        _data, _mime, _name, notes = services.export_project(PhotoProject.objects.get(pk=pid), "tiff")
        self.assertEqual(notes[0], services.EXPORT_CAP_NOTE)
        with Image.open(io.BytesIO(_data)) as im:
            self.assertEqual(max(im.size), 1280)


BAD = ("تومان", "ریال", "تخفیف", "درصد", "٪", "%", "قیمت")


def has_digit(text: str) -> bool:
    return any(c.isdigit() for c in text)


class ExampleChipsTests(ApiTestBase):
    def test_examples_come_from_the_store_and_carry_no_price_or_number(self):
        Product.objects.all().delete()
        for name, price in (("بستهٔ توکنِ «عادی» — ۵۰ توکن", 600_000), ("برنامهٔ تکی با هوش مصنوعی (فقط ورزشی یا فقط غذایی)", 300_000),
                            ("کتابخانهٔ حرکت‌ها و اسکنِ دستگاه", 0), ("پکیجِ ۳۰٪ تخفیف", 1)):
            Product.objects.create(store=self.store, name=name, price=price, is_available=True)
        out = examples.design_examples(self.store)
        joined = " | ".join(out)
        self.assertLessEqual(len(out), 5)
        self.assertGreaterEqual(len(out), 3)
        for chip in out:
            self.assertFalse(has_digit(chip), chip)
            for w in BAD:
                self.assertNotIn(w, chip)
        self.assertIn("«کتابخانهٔ حرکت‌ها و اسکنِ دستگاه»", joined)
        self.assertIn("بستهٔ توکنِ «عادی»", joined)           # بعد از « — » بریده می‌شود
        self.assertNotIn("فقط ورزشی", joined)                 # پرانتز حذف می‌شود
        self.assertNotIn("پکیجِ", joined)                      # نامِ دارای «تخفیف» و عدد کنار گذاشته می‌شود
        self.assertNotIn("کفش", joined)

    def test_store_without_products_gets_generic_priceless_chips(self):
        Product.objects.all().delete()
        out = examples.design_examples(self.store)
        self.assertGreaterEqual(len(out), 3)
        self.assertTrue(any("فروشگاهِ آزمون" in c for c in out))
        for chip in out:
            self.assertFalse(has_digit(chip), chip)
            for w in BAD:
                self.assertNotIn(w, chip)

    def test_clean_name_rules(self):
        self.assertEqual(examples.clean_name("قهوهٔ ترک"), "قهوهٔ ترک")
        self.assertEqual(examples.clean_name("اشتراک ماهانه — ۱۲۰ هزار تومان"), "اشتراک ماهانه")
        self.assertEqual(examples.clean_name("پکیج ۳ ماهه"), "")
        self.assertEqual(examples.clean_name("x" * 80), "")
        self.assertEqual(examples.clean_name(""), "")

    def test_overview_endpoint_includes_examples(self):
        body = self.api.get(f"{self.base}/").json()
        self.assertIn("design", body["examples"])
        self.assertTrue(all(not has_digit(c) for c in body["examples"]["design"]))
        self.assertTrue(any("قهوهٔ ترک" in c for c in body["examples"]["design"]))
