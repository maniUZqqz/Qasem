# -*- coding: utf-8 -*-
"""سایت‌ساز: وقتی هوش مصنوعی در دسترس نیست (متیس ۴۰۲، گرهٔ خاموش) درخواست گم نمی‌شود: پیامِ فارسیِ روشن، صفِ انتظار، و اجرای خودکار با برگشتنِ AI."""
import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.test import override_settings

from apps.ai_engine import parking, services as ai
from apps.ai_engine.models import AiProposal
from apps.projects.models import Page
from apps.projects.tests_builder import Base, MockProvider
from services.ai.routing import AllProvidersFailed


class Down:
    """مسیریابی که هر دو مسیر در آن خراب‌اند."""

    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def complete(self, system, user, json_mode=True):
        self.calls += 1
        raise self.exc


class Parking(Base):
    def setUp(self):
        super().setUp()
        self.data = Path(tempfile.mkdtemp(prefix="nm-parked-"))
        self.ov = override_settings(NM_DATA_DIR=self.data)
        self.ov.enable()
        self.p = self.project("pk1")
        self.page = Page.objects.create(project=self.p, title="صفحه", slug="x", body_html="<p>قدیمی</p>")

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.data, ignore_errors=True)
        super().tearDown()

    def edit(self, provider, instruction="عنوان را عوض کن"):
        with mock.patch("apps.ai_engine.services.get_provider", return_value=provider):
            prop = ai.edit_page(self.page, instruction)
        prop.refresh_from_db()
        return prop

    def test_metis_without_credit_and_node_off_is_parked_with_a_clear_persian_message(self):
        exc = AllProvidersFailed("سرورِ پردازش خاموش است؛ متیس: اعتبار حساب تمام شده است (۴۰۲)")
        prop = self.edit(Down(exc))
        self.assertEqual(prop.status, "failed")
        self.assertIn("در دسترس نیست", prop.error)
        self.assertIn("۴۰۲", prop.error)
        self.assertIn("خودکار اجرا می‌شود", prop.error)
        self.assertNotIn("خطای داخلی", prop.error)
        self.assertNotIn("AllProvidersFailed", prop.error)
        self.assertTrue(parking.is_parked(prop.pk))
        r = self.c.get(f"/api/v1/studio/projects/{self.p.slug}/ai/proposals/{prop.pk}/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["proposal"]["parked"])

    def test_a_bad_key_is_not_parked_but_is_friendly(self):
        prop = self.edit(Down(ai.AiError("کلید (توکن) پذیرفته نشد (401) — در جنگو ادمین کلید را وارسی کن.")))
        self.assertEqual(prop.status, "failed")
        self.assertIn("تنظیمات", prop.error)
        self.assertFalse(parking.is_parked(prop.pk), "waiting cannot fix a wrong key")

    def test_a_logic_error_stays_a_plain_failure(self):
        prop = self.edit(MockProvider(lambda req: "نه JSON"))
        self.assertEqual(prop.status, "failed")
        self.assertFalse(parking.is_parked(prop.pk))

    def good(self, req):
        return {"summary": "عنوان عوض شد", "body_html": "<h1>عنوانِ تازه</h1>", "css": ""}

    def test_resume_runs_when_the_ai_is_back_and_finishes_the_same_proposal(self):
        prop = self.edit(Down(AllProvidersFailed("متیس: اعتبار حساب تمام شده است (۴۰۲)")))
        self.assertTrue(parking.is_parked(prop.pk))
        # هنوز زود است (کمتر از ۵ دقیقه) ⇒ دست نمی‌زند
        self.assertEqual(parking.resume_due(), [])
        t = json.loads((self.data / "ai-parked" / f"{prop.pk}.json").read_text(encoding="utf-8"))
        self.assertEqual(t["fn"], "_do_edit_page")
        self.assertEqual(t["tries"], 1)
        # AI هنوز خراب است ⇒ دوباره پارک (tries بالا می‌رود)، نه ناموفقِ نهایی
        with mock.patch("apps.ai_engine.services.get_provider", return_value=Down(AllProvidersFailed("خاموش"))):
            self.assertEqual(parking.resume_due(now=time.time() + 400), [prop.pk])
        prop.refresh_from_db()
        self.assertEqual(prop.status, "failed")
        self.assertEqual(json.loads((self.data / "ai-parked" / f"{prop.pk}.json").read_text(encoding="utf-8"))["tries"], 2)
        # AI برگشت ⇒ همان پیشنهاد کامل می‌شود و برگه پاک می‌شود
        with mock.patch("apps.ai_engine.services.get_provider", return_value=MockProvider(self.good)):
            self.assertEqual(parking.resume_due(now=time.time() + 900), [prop.pk])
        prop.refresh_from_db()
        self.assertEqual(prop.status, "pending", prop.error)
        self.assertFalse(parking.is_parked(prop.pk))
        self.assertEqual(prop.changes.count() > 0, True)

    def test_retry_now_endpoint(self):
        prop = self.edit(Down(AllProvidersFailed("اتصال برقرار نشد")))
        url = f"/api/v1/studio/projects/{self.p.slug}/ai/proposals/{prop.pk}/retry/"
        with mock.patch("apps.ai_engine.services.get_provider", return_value=MockProvider(self.good)):
            r = self.c.post(url, {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["proposal"]["status"], "pending")
        again = self.c.post(url, {}, format="json")
        self.assertEqual(again.status_code, 400, "nothing is parked any more")

    def test_old_and_exhausted_tickets_are_dropped_with_a_message(self):
        prop = self.edit(Down(AllProvidersFailed("خاموش")))
        p = self.data / "ai-parked" / f"{prop.pk}.json"
        t = json.loads(p.read_text(encoding="utf-8"))
        t["created"] = time.time() - parking.MAX_AGE - 10
        p.write_text(json.dumps(t), encoding="utf-8")
        self.assertEqual(parking.resume_due(now=time.time() + 400), [])
        self.assertFalse(p.exists())
        prop.refresh_from_db()
        self.assertIn("۲۴ ساعت", prop.error)

    def test_a_deleted_page_does_not_crash_the_resume(self):
        prop = self.edit(Down(AllProvidersFailed("خاموش")))
        self.page.delete()
        self.assertEqual(parking.resume_due(now=time.time() + 400), [])
        self.assertFalse(parking.is_parked(prop.pk))
        prop.refresh_from_db()
        self.assertIn("دیگر نیست", prop.error)

    def test_open_circuits_skip_the_attempt(self):
        prop = self.edit(Down(AllProvidersFailed("خاموش")))
        down = Down(AllProvidersFailed("خاموش"))
        with mock.patch("services.ai.priority.open_failure", return_value={"until": "x"}), mock.patch("apps.ai_engine.services.get_provider", return_value=down):
            self.assertEqual(parking.resume_due(now=time.time() + 400), [])
        self.assertEqual(down.calls, 0, "no request is wasted while both routes are known to be down")
        self.assertTrue(parking.is_parked(prop.pk))

    def test_classification(self):
        u = parking.unavailable_from(AllProvidersFailed("متیس: اعتبار حساب تمام شده است (۴۰۲)"))
        self.assertTrue(u.parkable)
        self.assertEqual(u.kind, "no_credit")
        self.assertIsNone(parking.unavailable_from(ValueError("json خراب")))
        self.assertFalse(parking.unavailable_from(RuntimeError("کلید پذیرفته نشد (401)")).parkable)
