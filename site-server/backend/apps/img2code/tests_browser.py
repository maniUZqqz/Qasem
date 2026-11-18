# -*- coding: utf-8 -*-
"""«تصویر به کد» — آزمونِ مرورگرِ واقعی (Playwright) روی دسکتاپ و گوشی؛ فقط وقتی اجرا می‌شود که ``IMG2CODE_BROWSER=1`` باشد (ساختِ vite سنگین است).

صفحهٔ واقعیِ React با CSSِ واقعیِ پنل (Tailwind) در Chromium اجرا می‌شود (frontend/tests/browser/img2code)؛ axios به یک تابعِ پایتونی وصل است که با viewهای واقعیِ جنگو و
**تبدیلِ واقعی** (runner + mv2code + Tesseract) جواب می‌دهد. بدونِ سرورِ جداگانه و بدونِ دست‌زدن به دادهٔ زنده (پایگاهِ آزمون).

اجرا (روی سرور، زیرِ قفلِ سنگین):
    cd backend && IMG2CODE_BROWSER=1 IMG2CODE_SHOTS=/root/stage/i2c-shots PLAYWRIGHT_BROWSERS_PATH=/opt/up3d-uitest/browsers \\
        flock -w 3600 /root/nm-heavy.lock ../venv/bin/python -X utf8 manage.py test apps.img2code.tests_browser --noinput
"""
import base64
import functools
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.brandchar.models import SiteBinding
from apps.projects.models import Design, Project
from apps.stores.models import Store

from . import services, tasks
from .models import Conversion

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")        # callbackهای Playwright داخلِ حلقهٔ رویداد ORM صدا می‌زنند
os.environ.setdefault("MV2CODE_RESCAN_BUDGET", "15")              # نگاهِ دومِ OCR در آزمون کوتاه بماند (در تولید تا ۷۵ ثانیه است)؛ روی سرورِ پرکار تبدیل نباید از سقفِ انتظارِ مرورگر بگذرد
FRONT = Path(__file__).resolve().parents[3] / "frontend"
SHOTS = os.environ.get("IMG2CODE_SHOTS", "")

PAGE_HTML = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>
@font-face{font-family:V;font-weight:400;src:url(%(f400)s)}@font-face{font-family:V;font-weight:700;src:url(%(f700)s)}
*{box-sizing:border-box}body{margin:0;font-family:V,sans-serif;background:#f4f8ff;color:#163f75;width:1100px}
header{display:flex;justify-content:space-between;align-items:center;padding:22px 60px;background:#fff}header b{font-size:26px;color:#126f85}
nav span{margin-inline-start:26px;font-size:17px;color:#444}.hero{text-align:center;padding:70px 0 50px}.hero h1{font-size:46px;margin:0 0 14px}
.hero p{font-size:20px;color:#5c5c74;margin:0 0 28px}.btn{display:inline-block;background:#126f85;color:#fff;border-radius:14px;padding:14px 34px;font-size:19px;margin:0 8px}
.cards{display:flex;gap:24px;padding:10px 60px 60px}.card{flex:1;background:#fff;border-radius:18px;padding:28px 22px;text-align:center}.card h3{margin:0 0 10px;font-size:24px}
.card p{margin:0;color:#5a5a5a;font-size:17px;line-height:1.9}footer{background:#163f75;color:#cdd8ea;text-align:center;padding:28px;font-size:16px}
</style></head><body><header><b>فروشگاه نمونه</b><nav><span>خانه</span><span>امکانات</span><span>تماس با ما</span></nav></header>
<section class="hero"><h1>همه‌چیز برای شروعِ کار</h1><p>ابزارهایی که کارِ روزانه را سریع‌تر و دقیق‌تر می‌کنند</p><span class="btn">شروع کنید</span><span class="btn" style="background:#fff;color:#126f85;border:2px solid #126f85">بیشتر بدانید</span></section>
<section class="cards"><div class="card"><h3>سریع</h3><p>کار را در کمترین زمان انجام می‌دهد.</p></div><div class="card"><h3>دقیق</h3><p>هر مرحله را با دقت بررسی می‌کند.</p></div><div class="card"><h3>ساده</h3><p>برای همه قابلِ استفاده است.</p></div></section>
<footer>همهٔ حقوق محفوظ است.</footer></body></html>"""


@unittest.skipUnless(os.environ.get("IMG2CODE_BROWSER"), "آزمونِ مرورگری فقط با IMG2CODE_BROWSER=1")
class BrowserTests(TransactionTestCase):
    # TransactionTestCase، نه TestCase: callbackهای Playwright در نخِ دیگری اجرا می‌شوند و دادهٔ یک تراکنشِ بازِ TestCase را نمی‌بینند (فهرستِ فروشگاه‌ها خالی می‌آمد)
    databases = {"default", "studio"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp(prefix="nm-i2c-browser-"))
        eng = services.engine_status(refresh=True)
        if not (eng["ready"] and eng["ocr"] and eng["compare_ok"]):
            raise unittest.SkipTest("موتور/Tesseract/مرورگر آماده نیست: %s" % eng["messages"])
        out = cls.tmp / "harness"
        env = dict(os.environ, I2C_HARNESS_OUT=str(out))
        r = subprocess.run(["node", "node_modules/.bin/vite", "build", "--config", "tests/browser/img2code/vite.config.ts", "--logLevel", "error"], cwd=str(FRONT), env=env,
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise AssertionError("ساختِ harness شکست خورد:\n" + (r.stdout + r.stderr)[-2000:])
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
        handler.log_message = lambda *a, **k: None       # type: ignore[attr-defined]
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d/index.html" % cls.httpd.server_address[1]
        import mv2code
        fonts = Path(mv2code.__file__).parent / "fonts"
        html = PAGE_HTML % {"f400": (fonts / "vazirmatn-arabic-400-normal.woff2").as_uri(), "f700": (fonts / "vazirmatn-arabic-700-normal.woff2").as_uri()}
        (cls.tmp / "page.html").write_text(html, encoding="utf-8")
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
        cls.png = cls.render_png()           # پیش از هر آزمون: Playwright ِ هم‌گام را نمی‌شود داخلِ یک sync_playwright ِ دیگر باز کرد

    @classmethod
    def tearDownClass(cls):
        try:
            cls.httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.data = override_settings(NM_DATA_DIR=self.tmp / "data", WORKSPACES_ROOT=self.tmp / "work")
        self.data.enable()
        self.addCleanup(self.data.disable)
        self.ui_off = override_settings(IMG2CODE_UI_DESIGN=False)            # «باز کردن در طراحیِ UI» فقط در آزمونِ خودش روشن می‌شود
        self.ui_off.enable()
        self.addCleanup(self.ui_off.disable)
        (self.tmp / "work").mkdir(parents=True, exist_ok=True)
        self.staff = User.objects.create_user("i2c-b-staff", password="x", is_staff=True)
        self.plain = User.objects.create_user("i2c-b-plain", password="x")
        self.store = Store.objects.create(owner=self.staff, name="فروشگاهِ آزمونِ مرورگر")
        self.plain_store = Store.objects.create(owner=self.plain, name="فروشگاهِ ساده")
        # هر تبدیل همان‌جا (هم‌گام) اجرا شود؛ در تولید celery این کار را می‌کند
        p = mock.patch.object(services, "_enqueue", side_effect=lambda conv: tasks.run_conversion(conv.pk))
        p.start()
        self.addCleanup(p.stop)

    @classmethod
    def render_png(cls) -> bytes:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(args=["--no-sandbox"])
            try:
                pg = b.new_page(viewport={"width": 1100, "height": 800})
                pg.goto((cls.tmp / "page.html").as_uri(), wait_until="load")
                pg.wait_for_timeout(300)
                return pg.screenshot(full_page=True)
            finally:
                b.close()

    def page_png(self) -> bytes:
        return self.png

    # --------------------------------------------------------------------------- مرورگر
    def mock_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        seen = []

        def mock_api(method, url, params, data):
            try:
                out = mock_api_inner(method, url, params, data)
                if os.environ.get("IMG2CODE_DEBUG"):
                    import threading
                    print("MOCK %s %s -> %s %s [%s]" % (method, url, out.get("status"), json.dumps(out.get("data"), ensure_ascii=False)[:260], threading.current_thread().name))
                return out
            except Exception as exc:  # noqa: BLE001 — خطای پایتون در مرورگر «خطای ناشناخته» می‌شد؛ این‌جا چاپ می‌شود
                import traceback
                traceback.print_exc()
                return {"status": 500, "data": {"error": {"code": "harness", "message": "%s: %s" % (type(exc).__name__, exc)}}}

        def mock_api_inner(method, url, params, data):
            path = url
            if params:
                from urllib.parse import urlencode
                path += "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})
            seen.append((method, url))
            fn = getattr(client, method)
            if isinstance(data, dict) and data.get("__multipart"):
                payload = dict(data["fields"])
                for k, f in data["files"].items():
                    payload[k] = SimpleUploadedFile(f["name"], base64.b64decode(f["b64"]), content_type=f["type"])
                r = fn(path, payload, format="multipart")
            elif method in ("post", "put", "patch"):
                r = fn(path, data, format="json")
            else:
                r = fn(path)
            ctype = r.get("Content-Type", "")
            if getattr(r, "streaming", False):
                return {"status": r.status_code, "data": None, "b64": base64.b64encode(b"".join(r.streaming_content)).decode(), "ctype": ctype}
            if ctype.startswith("application/json"):
                return {"status": r.status_code, "data": r.json()}
            if r.status_code == 204 or not r.content:
                return {"status": r.status_code, "data": None}
            return {"status": r.status_code, "data": None, "b64": base64.b64encode(r.content).decode(), "ctype": ctype}
        return mock_api, seen

    def open_page(self, pw, user, store, width, height, theme="light"):
        b = pw.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": width, "height": height}, locale="fa-IR", accept_downloads=True, has_touch=width < 600)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
        page.on("console", lambda m: errors.append("console: " + m.text[:200]) if m.type == "error" and "favicon" not in m.text else None)
        api, seen = self.mock_for(user)
        page.expose_function("mock_api", api)
        page.goto("%s?store=%d&theme=%s" % (self.base, store.pk, theme))
        page.wait_for_selector("[data-testid=img2code-page]", timeout=30000)
        try:
            page.wait_for_selector("[data-testid=i2c-form]", timeout=30000)
        except Exception:                                    # noqa: BLE001 — به‌جای «Timeout» ِ گنگ، متنِ صفحه و خطاها را نشان بده
            raise AssertionError("فرم در صفحه نیامد.\nمتنِ صفحه: %s\nخطاها: %s\nدرخواست‌ها: %s" % (page.inner_text("body")[:600], errors, seen[-8:]))
        return b, page, errors, seen

    def shot(self, page, name):
        if SHOTS:
            page.screenshot(path=os.path.join(SHOTS, name), full_page=True)

    def no_overflow(self, page, what):
        over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        self.assertLessEqual(over, 2, "%s: اسکرولِ افقی %s" % (what, over))

    def assert_opaque(self, page, selector, what):
        """پنجره‌ها نباید شفاف باشند: توکنِ --surface شیشه است (۴٪ سفید در تیره) و متنِ پشتِ پنجره را نشان می‌داد."""
        bg = page.evaluate("(s) => getComputedStyle(document.querySelector(s)).backgroundColor", selector)
        self.assertTrue(bg.startswith("rgb(") or bg.endswith(", 1)"), "%s: پس‌زمینه شفاف است: %s" % (what, bg))

    REVIEW = [
        {"box": [60, 30, 220, 34], "text": "تمامی حقوق محقوظ است", "conf": 0.52, "why": ["conf", "unknown"]},
        {"box": [300, 120, 260, 40], "text": "ابزارهایی که کار روزانه", "conf": 0.71, "why": ["conf"]},
    ]

    def with_review(self):
        """تبدیلِ واقعی؛ فقط گزارشش «دو خطِ مشکوک» دارد تا نمایشِ کادرهای زرد و فهرست بدونِ تکیه بر نتیجهٔ OCR آزموده شود."""
        orig = services._slim_report
        return mock.patch.object(services, "_slim_report", side_effect=lambda rep: orig(dict(rep, review_lines=len(self.REVIEW), review=self.REVIEW)))

    def convert_through_ui(self, page):
        page.set_input_files("[data-testid=i2c-file]", {"name": "landing.png", "mimeType": "image/png", "buffer": self.page_png()})
        page.wait_for_selector("[data-testid=i2c-drop] img", timeout=10000)
        page.click("[data-testid=i2c-mode-exact]")
        page.click("[data-testid=i2c-mode-responsive]")
        page.select_option("[data-testid=i2c-lang]", "fa")
        page.fill("[data-testid=i2c-title]", "صفحهٔ فرودِ آزمون")
        page.click("[data-testid=i2c-submit]")
        page.wait_for_selector("[data-testid=i2c-result]", timeout=300000)

    def test_desktop_full_flow(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b, page, errors, seen = self.open_page(pw, self.staff, self.store, 1280, 900)
            try:
                self.assertIn("تصویر به کد", page.inner_text("h1"))
                self.assertEqual(page.locator("[data-testid=i2c-store]").count(), 0)        # یک فروشگاه ⇒ انتخابگر لازم نیست
                self.assertIn("نشانیِ صفحه را بدهید", page.inner_text("[data-testid=i2c-url-hint]"))        # برای متنِ دقیق، نشانی بدهید
                page.click("[data-testid=i2c-hint-url-btn]")
                page.wait_for_selector("[data-testid=i2c-url]")
                self.assertEqual(page.locator("[data-testid=i2c-url-hint]").count(), 0)
                page.click("[data-testid=i2c-tab-upload]")
                self.shot(page, "desktop-1-empty.png")
                self.convert_through_ui(page)
                self.shot(page, "desktop-2-result.png")
                res = page.locator("[data-testid=i2c-result]")
                self.assertIn("صفحهٔ فرودِ آزمون", res.inner_text())
                self.assertIn("آماده", res.inner_text())
                self.assertIn("واکنش‌گرا", res.inner_text())
                # مقایسه: دو تصویرِ واقعی کنارِ هم
                page.wait_for_function("document.querySelectorAll('[data-testid=i2c-compare-side] img').length === 2 && [...document.querySelectorAll('[data-testid=i2c-compare-side] img')].every(i => i.complete && i.naturalWidth > 100)", timeout=30000)
                self.no_overflow(page, "desktop result")
                # مقایسه با پیش‌نمایشِ سبکِ WebP (نه PNGِ کامل) بارگذاری شد
                files = [u for _m, u in seen if "/files/" in u]
                self.assertTrue(any(u.endswith("original.preview.webp") for u in files), files)
                self.assertTrue(any(u.endswith("rendered.preview.webp") for u in files), files)
                self.assertFalse(any(u.endswith("original.png") or u.endswith("rendered.png") for u in files), files)
                # سرِ کارتِ نتیجه: عنوان پهن است (نه ستونِ باریکِ یک‌کلمه‌ای) و دکمه‌ها زیرِ عنوان و برچسب‌ها می‌آیند
                title = page.locator("[data-testid=i2c-result] h2").bounding_box()
                chips = page.locator("[data-testid=i2c-result] .i2c-chips").bounding_box()
                actions = page.locator("[data-testid=i2c-result] .i2c-result-actions").bounding_box()
                self.assertGreaterEqual(title["width"], 500, title)
                self.assertGreaterEqual(actions["y"], chips["y"] + chips["height"] - 1, (chips, actions))
                self.assertGreaterEqual(chips["width"], 400, chips)
                # لغزنده
                page.click("[data-testid=i2c-view-slider]")
                page.wait_for_selector("[data-testid=i2c-compare-slider] .i2c-slider-top")
                clip_before = page.get_attribute("[data-testid=i2c-compare-slider] .i2c-slider-top", "style")
                page.fill("[data-testid=i2c-slider-range]", "25")
                clip_after = page.get_attribute("[data-testid=i2c-compare-slider] .i2c-slider-top", "style")
                self.assertNotEqual(clip_before, clip_after)
                self.assertIn("75%", clip_after)
                self.shot(page, "desktop-3-slider.png")
                # امتیازها به فارسیِ ساده
                page.click("[data-testid=i2c-tab-scores]")
                page.wait_for_selector("[data-testid=i2c-score]")
                labels = page.locator("[data-testid=i2c-score] .i2c-score-label").all_inner_texts()
                self.assertTrue(any("شباهتِ ظاهر" in x for x in labels), labels)
                self.assertTrue(any("قابل‌ویرایش" in x for x in labels), labels)
                self.assertTrue(any("روشِ خواندنِ متن" in x for x in labels), labels)
                self.assertRegex(page.locator("[data-testid=i2c-score][data-key=ssim] .i2c-score-value").inner_text(), r"[۰-۹]+٪")
                self.shot(page, "desktop-4-scores.png")
                # کد
                page.click("[data-testid=i2c-tab-code]")
                page.wait_for_selector("[data-testid=i2c-pre]")
                self.assertIn("<html", page.inner_text("[data-testid=i2c-pre]"))
                page.click("[data-testid=i2c-code-css]")
                page.click("[data-testid=i2c-code-tree]")
                self.assertIn('"role"', page.inner_text("[data-testid=i2c-pre]"))
                self.no_overflow(page, "desktop code")
                self.shot(page, "desktop-5-code.png")
                # ZIP
                with page.expect_download() as dl:
                    page.click("[data-testid=i2c-zip]")
                conv = Conversion.objects.get(store=self.store)
                self.assertEqual(dl.value.suggested_filename, "img2code-%d.zip" % conv.pk)
                # ساختِ پیش‌نویس در سایت‌ساز (کارمند)
                page.click("[data-testid=i2c-draft-btn]")
                page.wait_for_selector("[data-testid=i2c-draft-modal]")
                self.assert_opaque(page, "[data-testid=i2c-draft-modal]", "desktop روشن")
                self.shot(page, "desktop-6-draft-dialog.png")
                page.click("[data-testid=i2c-draft-confirm]")
                page.wait_for_selector("[data-testid=i2c-draft-done]", timeout=60000)
                href = page.get_attribute("[data-testid=i2c-open-builder]", "href")
                self.assertRegex(href, r"^/tools/studio/p/[\w-]+/builder/page/\d+$")
                self.shot(page, "desktop-7-draft-done.png")
                project = Project.objects.get(slug=href.split("/")[4])
                self.assertTrue(SiteBinding.objects.filter(project_slug=project.slug, store=self.store).exists())
                design = Design.objects.get(project=project, target="page")
                self.assertIsNone(design.published)                                           # فقط پیش‌نویس
                self.assertTrue(design.draft["blocks"])
                # نامِ برندِ سربرگِ تصویر ⇒ «نامِ سایت» ِ پروژه (بلوکِ سربرگ آن را از همان می‌خواند، نه از متنِ بلوک) و منو ⇒ منوی پوسته
                self.assertEqual(project.site_title, "فروشگاه نمونه")
                self.assertEqual([b["type"] for b in Design.objects.get(project=project, target="header").draft["blocks"]], ["site_header"])
                # دکمهٔ «باز کردن در طراحیِ UI» وقتی استودیوی طراحی خاموش است نیست (آزمونِ جدا روشنش می‌کند)
                self.assertEqual(page.locator("[data-testid=i2c-ui-design]").count(), 0)
                # تاریخچه + حذف
                page.wait_for_selector("[data-testid=i2c-history-item]")
                self.assertIn("پیش‌نویس در سایت‌ساز", page.inner_text("[data-testid=i2c-history]"))
                page.once("dialog", lambda d: d.accept())
                page.click("[data-testid=i2c-delete]")
                page.wait_for_function("document.querySelectorAll('[data-testid=i2c-history-item]').length === 0", timeout=15000)
                self.assertFalse(Conversion.objects.filter(store=self.store).exists())
                self.assertTrue(Project.objects.filter(pk=project.pk).exists())               # پیش‌نویسِ سایت‌ساز با حذفِ تاریخچه نمی‌رود
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_ui_design_button_creates_a_studio_doc_and_opens_it(self):
        """استودیوی طراحی روشن است ⇒ «باز کردن در طراحیِ UI» (برای هر عضوِ نویسنده، نه فقط کارکنان) سندِ UI می‌سازد و پنل را به همان می‌برد."""
        from playwright.sync_api import sync_playwright

        from apps.design_studio.models import DesignDoc
        with override_settings(IMG2CODE_UI_DESIGN=True), sync_playwright() as pw:
            b, page, errors, _seen = self.open_page(pw, self.plain, self.plain_store, 1280, 900)
            try:
                self.convert_through_ui(page)
                btn = page.locator("[data-testid=i2c-ui-design]")
                self.assertIn("باز کردن در طراحیِ UI", btn.inner_text())
                self.assertFalse(btn.is_disabled())
                self.shot(page, "desktop-ui-design-button.png")
                btn.click()
                page.wait_for_function("(document.querySelector('[data-testid=routed]') || {innerText: ''}).innerText.includes('/design/ui/')", timeout=60000)
                doc = DesignDoc.objects.get(store=self.plain_store, kind="ui")
                self.assertEqual(page.inner_text("[data-testid=routed]"), "/stores/%d/design/ui/%d" % (self.plain_store.pk, doc.pk))
                self.assertTrue(doc.data["frames"][0]["children"])
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_doubtful_lines_are_marked_on_the_images_and_listed(self):
        from playwright.sync_api import sync_playwright
        with self.with_review(), sync_playwright() as pw:
            b, page, errors, _seen = self.open_page(pw, self.staff, self.store, 1280, 900, theme="dark")
            try:
                self.convert_through_ui(page)
                page.wait_for_selector("[data-testid=i2c-review]", timeout=20000)
                self.assertEqual(page.locator("[data-testid=i2c-review-row]").count(), 2)
                self.assertIn("این خط را بررسی کن", page.inner_text("[data-testid=i2c-review]"))
                self.assertIn("تمامی حقوق محقوظ است", page.inner_text("[data-testid=i2c-review]"))
                # روی هر دو تصویر (اصلی و نتیجه) کادرِ زرد هست
                page.wait_for_function("document.querySelectorAll('[data-testid=i2c-compare-side] [data-testid=i2c-flag]').length === 4", timeout=20000)
                flag = page.locator("[data-testid=i2c-compare-side] [data-testid=i2c-flag]").first
                self.assertEqual(flag.get_attribute("title"), "این خط را بررسی کن")
                img = page.locator("[data-testid=i2c-compare-side] .i2c-imgwrap").first.bounding_box()
                fb = flag.bounding_box()
                conv = Conversion.objects.get(store=self.store)
                w, h = conv.size_w, conv.size_h
                self.assertAlmostEqual((fb["x"] - img["x"]) / img["width"], 60 / w, delta=0.02)
                self.assertAlmostEqual((fb["y"] - img["y"]) / img["height"], 30 / h, delta=0.02)
                self.shot(page, "desktop-review.png")
                # با کلیک روی یک ردیف همان کادر پررنگ می‌شود؛ خاموش‌کردنِ کادرها آن‌ها را برمی‌دارد
                page.click("[data-testid=i2c-review-row][data-idx='1']")
                page.wait_for_selector("[data-testid=i2c-flag][data-idx='1'].is-focus")
                page.click("[data-testid=i2c-flags-toggle]")
                page.wait_for_function("document.querySelectorAll('[data-testid=i2c-flag]').length === 0")
                page.click("[data-testid=i2c-flags-toggle]")
                page.click("[data-testid=i2c-view-slider]")
                page.wait_for_function("document.querySelectorAll('[data-testid=i2c-compare-slider] [data-testid=i2c-flag]').length === 2")
                # فهرستِ امتیازها هم از «خط‌های نیازمندِ بررسی» می‌گوید
                page.click("[data-testid=i2c-tab-scores]")
                page.wait_for_selector("[data-testid=i2c-score][data-key=review]")
                self.assertRegex(page.locator("[data-testid=i2c-score][data-key=review] .i2c-score-value").inner_text(), r"^۲ از [۰-۹]+ خط$")
                self.no_overflow(page, "desktop review")
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_phone_review_list_fits_the_screen(self):
        from playwright.sync_api import sync_playwright
        with self.with_review(), sync_playwright() as pw:
            b, page, errors, _seen = self.open_page(pw, self.staff, self.store, 390, 844, theme="dark")
            try:
                self.convert_through_ui(page)
                page.wait_for_selector("[data-testid=i2c-review]", timeout=20000)
                self.no_overflow(page, "phone review")
                box = page.locator("[data-testid=i2c-review]").bounding_box()
                self.assertLessEqual(box["x"] + box["width"], 391)
                self.shot(page, "phone-review.png")
                self.assertEqual(errors, [])
            finally:
                b.close()

    def with_picture(self, share=0.82):
        """تبدیلِ واقعی؛ فقط «سهمِ تصویرِ چسبانده» ۸۲٪ اعلام می‌شود تا هشدارِ قرمز بدونِ تکیه بر نتیجهٔ موتور آزموده شود."""
        return mock.patch.object(services, "measure_image_share", return_value=share)

    def test_a_page_that_became_one_picture_shows_a_red_alert_in_the_result_and_in_the_draft_dialog(self):
        from playwright.sync_api import sync_playwright
        with self.with_picture(), sync_playwright() as pw:
            b, page, errors, _seen = self.open_page(pw, self.staff, self.store, 1280, 900, theme="dark")
            try:
                self.convert_through_ui(page)
                alert = page.locator("[data-testid=i2c-alert]")
                alert.wait_for(timeout=20000)
                self.assertEqual(alert.get_attribute("data-level"), "bad")
                self.assertIn("عملاً یک تصویر", alert.inner_text())
                self.assertIn("۸۲٪", alert.inner_text())
                self.shot(page, "desktop-picture-alert.png")
                page.click("[data-testid=i2c-tab-scores]")
                page.wait_for_selector("[data-testid=i2c-score][data-key=image_share]")
                self.assertEqual(page.locator("[data-testid=i2c-score][data-key=image_share] .i2c-score-value").inner_text(), "۸۲٪")
                page.click("[data-testid=i2c-draft-btn]")
                page.wait_for_selector("[data-testid=i2c-draft-modal]")
                self.assertEqual(page.locator("[data-testid=i2c-draft-alert]").get_attribute("data-level"), "bad")
                self.assertIn("عملاً یک تصویر", page.inner_text("[data-testid=i2c-draft-alert]"))
                self.assert_opaque(page, "[data-testid=i2c-draft-modal]", "هشدار + پنجره")
                self.shot(page, "desktop-picture-alert-dialog.png")
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_phone_picture_alert_fits_the_screen_and_a_healthy_page_has_none(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            with self.with_picture():
                b, page, errors, _seen = self.open_page(pw, self.staff, self.store, 390, 844, theme="dark")
                try:
                    self.convert_through_ui(page)
                    page.wait_for_selector("[data-testid=i2c-alert]", timeout=20000)
                    self.no_overflow(page, "phone alert")
                    box = page.locator("[data-testid=i2c-alert]").bounding_box()
                    self.assertLessEqual(box["x"] + box["width"], 391)
                    self.shot(page, "phone-picture-alert.png")
                    self.assertEqual(errors, [])
                finally:
                    b.close()
            b, page, errors, _seen = self.open_page(pw, self.plain, self.plain_store, 390, 844, theme="light")
            try:
                self.convert_through_ui(page)
                self.assertEqual(page.locator("[data-testid=i2c-alert]").count(), 0)          # صفحهٔ سالم: بدونِ هشدار
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_url_form_refuses_internal_addresses_in_persian(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b, page, errors, _seen = self.open_page(pw, self.staff, self.store, 1280, 900)
            try:
                page.click("[data-testid=i2c-tab-url]")
                page.fill("[data-testid=i2c-url]", "http://127.0.0.1:8041/admin/")
                page.click("[data-testid=i2c-submit]")
                page.wait_for_selector("text=شبکهٔ داخلی", timeout=15000)
                self.shot(page, "desktop-url-refused.png")
                self.assertFalse(Conversion.objects.exists())
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_phone_flow_dark_theme_has_no_horizontal_scroll(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b, page, errors, _seen = self.open_page(pw, self.staff, self.store, 390, 844, theme="dark")
            try:
                self.no_overflow(page, "phone empty")
                self.shot(page, "phone-1-empty.png")
                self.convert_through_ui(page)
                page.wait_for_function("document.querySelectorAll('[data-testid=i2c-compare-side] img').length === 2 && [...document.querySelectorAll('[data-testid=i2c-compare-side] img')].every(i => i.complete && i.naturalWidth > 100)", timeout=30000)
                self.no_overflow(page, "phone result")
                self.shot(page, "phone-2-result.png")
                page.click("[data-testid=i2c-view-slider]")
                page.wait_for_selector("[data-testid=i2c-compare-slider] .i2c-slider-top")
                self.no_overflow(page, "phone slider")
                self.shot(page, "phone-3-slider.png")
                page.click("[data-testid=i2c-tab-scores]")
                page.wait_for_selector("[data-testid=i2c-score]")
                self.no_overflow(page, "phone scores")
                self.shot(page, "phone-4-scores.png")
                page.click("[data-testid=i2c-tab-code]")
                page.wait_for_selector("[data-testid=i2c-pre]")
                self.no_overflow(page, "phone code")
                page.click("[data-testid=i2c-draft-btn]")
                page.wait_for_selector("[data-testid=i2c-draft-modal]")
                self.assert_opaque(page, "[data-testid=i2c-draft-modal]", "گوشی تیره")
                box = page.locator("[data-testid=i2c-draft-modal]").bounding_box()
                self.assertLessEqual(box["x"] + box["width"], 391)
                self.assertGreaterEqual(box["x"], -1)
                self.shot(page, "phone-5-draft-dialog.png")
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_non_staff_sees_the_draft_button_disabled_and_the_api_agrees(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b, page, errors, seen = self.open_page(pw, self.plain, self.plain_store, 1280, 900)
            try:
                self.convert_through_ui(page)
                btn = page.locator("[data-testid=i2c-draft-btn]")
                self.assertTrue(btn.is_disabled())
                self.assertIn("فقط کارکنان", btn.inner_text())
                self.shot(page, "desktop-nonstaff.png")
                self.assertFalse(any("site-draft" in u for _m, u in seen))
                self.assertEqual(errors, [])
            finally:
                b.close()
