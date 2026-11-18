"""API: برنامه، تصمیمِ مالک، راهنمای آزمون، گزارشِ ایراد (با عکس) و محدودیتِ دسترسی."""
import io
import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APITestCase

from . import planner, runner
from apps.stores.models import Membership

from .models import BugReport, MarketingPlan, PlanItem
from .testkit import make_store


def png_bytes(size=(40, 30)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(b, "PNG")
    return b.getvalue()


class PlanApiTests(APITestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.client.force_authenticate(self.owner)
        self.url = f"/api/v1/stores/{self.store.pk}/marketing-plan/"

    def test_no_plan_yet_returns_facts_and_gaps_and_default_start(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["plan"])
        self.assertEqual(r.data["facts"]["name"], "باشگاه نمونه")
        self.assertIn("default_start", r.data)

    def test_create_then_get_returns_every_item_with_links(self):
        r = self.client.post(self.url, {"action": "create"}, format="json")
        self.assertEqual(r.status_code, 200)
        plan = r.data["plan"]
        self.assertEqual(len(plan["items"]), len(planner.SLOTS))
        self.assertEqual(plan["days"], 14)
        kinds = {i["kind"] for i in plan["items"]}
        self.assertTrue({"reel", "voiceover", "motion", "sms", "email", "finder", "inbox", "landing", "catalog", "deck", "thumbnail"} <= kinds)
        for i in plan["items"]:
            self.assertTrue(i["url"], i["key"])                                  # هر کار به بخشِ سازنده‌اش لینک دارد
        g = self.client.get(self.url)
        self.assertEqual(g.data["plan"]["id"], plan["id"])

    def test_create_run_in_background_produces_drafts_without_publishing_anything(self):
        r = self.client.post(self.url, {"action": "create_run"}, format="json")
        self.assertEqual(r.status_code, 200)
        plan = MarketingPlan.objects.get(store=self.store)
        self.assertTrue(plan.last_run_at)                                        # (زیرِ آزمون Celery همزمان اجرا می‌شود)
        statuses = {i["status"] for i in self.client.get(self.url).data["plan"]["items"]}
        self.assertTrue(statuses & {"DRAFTED", "READY", "NEEDS_YOU", "WAITING_NODE"})
        from apps.campaigns.models import PublishJob

        self.assertEqual(PublishJob.objects.filter(store=self.store).count(), 0)

    def test_run_without_a_plan_is_404_and_bad_action_is_400(self):
        self.assertEqual(self.client.post(self.url, {"action": "run"}, format="json").status_code, 404)
        self.assertEqual(self.client.post(self.url, {"action": "nope"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"action": "create", "start_date": "نه"}, format="json").status_code, 400)

    def test_item_decision_and_draft_edit(self):
        plan, _ = planner.ensure_plan(self.store, self.owner)
        item = plan.items.get(key="d07.email.1")
        url = f"{self.url}items/{item.pk}/"
        self.assertEqual(self.client.patch(url, {"decision": "bad"}, format="json").status_code, 400)
        r = self.client.patch(url, {"decision": "approved"}, format="json")
        self.assertEqual(r.data["item"]["decision"], "approved")
        item.refresh_from_db()
        item.ai_wait = True
        item.save()
        r = self.client.patch(url, {"draft": "متنِ تازه"}, format="json")
        self.assertEqual(r.data["item"]["draft"], "متنِ تازه")
        self.assertFalse(r.data["item"]["ai_wait"])
        r = self.client.patch(url, {"decision": ""}, format="json")
        self.assertEqual(r.data["item"]["decision"], "")

    def test_single_item_run(self):
        plan, _ = planner.ensure_plan(self.store, self.owner)
        item = plan.items.get(key="d09.sms.1")
        r = self.client.post(f"{self.url}items/{item.pk}/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["item"]["status"], "DRAFTED")
        self.assertTrue(r.data["item"]["refs"])

    def test_stranger_cannot_see_or_change_the_plan(self):
        planner.ensure_plan(self.store, self.owner)
        other = User.objects.create_user("stranger", password="x")
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"action": "create"}, format="json").status_code, 404)

    def test_login_required(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))


class GuideAndBugApiTests(APITestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.staff = User.objects.create_user("staffer", password="x", is_staff=True)
        self.client.force_authenticate(self.owner)

    def test_guide_lists_sections_with_plan_chips_and_hides_staff_only_from_members(self):
        planner.ensure_plan(self.store, self.owner)
        r = self.client.get(f"/api/v1/stores/{self.store.pk}/test-guide/")
        self.assertEqual(r.status_code, 200)
        keys = {s["key"] for s in r.data["sections"]}
        self.assertIn("plan", keys)
        self.assertNotIn("node", keys)                                           # فقط کارکنان
        motion = next(s for s in r.data["sections"] if s["key"] == "motion")
        self.assertEqual(motion["url"], f"/stores/{self.store.pk}/motion")
        self.assertGreater(motion["plan"]["total"], 0)
        Membership.objects.create(store=self.store, user=self.staff, role="ADMIN")        # کارمندِ عضو (مثلِ حسابِ admin در فروشگاه)
        self.client.force_authenticate(self.staff)
        keys2 = {s["key"] for s in self.client.get(f"/api/v1/stores/{self.store.pk}/test-guide/").data["sections"]}
        self.assertIn("node", keys2)

    def test_sections_endpoint_for_the_picker(self):
        r = self.client.get("/api/v1/bug-reports/sections/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["sections"][-1]["key"], "other")

    def test_bug_report_with_screenshot_is_stored_and_readable(self):
        shot = SimpleUploadedFile("s.png", png_bytes(), content_type="image/png")
        ctx = {"version": "9.9", "ua": "UA", "errors": ["TypeError: x"], "api_failures": [{"url": "/x", "status": 500}]}
        r = self.client.post("/api/v1/bug-reports/", {"section": "motion", "page_url": f"/stores/{self.store.pk}/motion", "note": "رندر خطا داد", "store": self.store.pk,
                                                       "context": json.dumps(ctx), "screenshot": shot}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        b = BugReport.objects.get(pk=r.data["report"]["id"])
        self.assertEqual(b.section, "motion")
        self.assertEqual(b.section_title, "استودیوی موشن")
        self.assertEqual(b.store_id, self.store.pk)
        self.assertTrue(b.screenshot.name.endswith(".png"))
        self.assertTrue(b.screenshot.storage.exists(b.screenshot.name))
        self.assertEqual(b.context["errors"], ["TypeError: x"])
        lst = self.client.get(f"/api/v1/stores/{self.store.pk}/bug-reports/")
        self.assertEqual(lst.data["results"][0]["id"], b.pk)
        self.assertTrue(lst.data["results"][0]["screenshot"])

    def test_section_is_guessed_from_the_page_key_and_unknown_becomes_other(self):
        r = self.client.post("/api/v1/bug-reports/", {"page_key": "audio_pronunciation", "note": "تلفظ غلط است"}, format="json")
        self.assertEqual(r.data["report"]["section"], "pron")
        r = self.client.post("/api/v1/bug-reports/", {"section": "ساختگی", "note": "یک چیزی"}, format="json")
        self.assertEqual(r.data["report"]["section"], "other")

    def test_bad_input_is_refused(self):
        self.assertEqual(self.client.post("/api/v1/bug-reports/", {"note": "x"}, format="json").status_code, 400)
        fake = SimpleUploadedFile("s.png", b"not an image", content_type="image/png")
        r = self.client.post("/api/v1/bug-reports/", {"note": "یادداشتِ کافی", "screenshot": fake}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(BugReport.objects.count(), 0)

    def test_huge_context_is_cut_down(self):
        r = self.client.post("/api/v1/bug-reports/", {"note": "یادداشتِ کافی", "context": json.dumps({"ua": "U", "errors": ["x" * 100] * 600})}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(BugReport.objects.get().context.get("truncated"))

    def test_member_sees_only_own_reports_but_staff_sees_all_and_can_update(self):
        self.client.post("/api/v1/bug-reports/", {"note": "گزارشِ مالک", "section": "plan"}, format="json")
        self.client.force_authenticate(self.staff)
        self.client.post("/api/v1/bug-reports/", {"note": "گزارشِ کارمند", "section": "plan"}, format="json")
        self.assertEqual(len(self.client.get("/api/v1/bug-reports/").data["results"]), 2)
        bid = BugReport.objects.filter(user=self.owner).get().pk
        r = self.client.patch(f"/api/v1/bug-reports/{bid}/", {"state": "fixed", "response": "رفع شد"}, format="json")
        self.assertEqual(r.data["report"]["state"], "fixed")
        self.client.force_authenticate(self.owner)
        self.assertEqual(len(self.client.get("/api/v1/bug-reports/").data["results"]), 1)
        self.assertEqual(self.client.patch(f"/api/v1/bug-reports/{bid}/", {"state": "new"}, format="json").status_code, 403)

    def test_store_scoped_list_needs_membership(self):
        stranger = User.objects.create_user("zed", password="x")
        self.client.force_authenticate(stranger)
        self.assertEqual(self.client.get(f"/api/v1/stores/{self.store.pk}/bug-reports/").status_code, 404)

    def test_management_command_lists_reports(self):
        from django.core.management import call_command

        self.client.post("/api/v1/bug-reports/", {"note": "برای فرمانِ خواندن", "section": "plan"}, format="json")
        out = io.StringIO()
        call_command("bug_reports", stdout=out)
        self.assertIn("برای فرمانِ خواندن", out.getvalue())
        out = io.StringIO()
        call_command("bug_reports", "--json", stdout=out)
        self.assertEqual(json.loads(out.getvalue())[0]["section"], "plan")
        call_command("bug_reports", "--mark", str(BugReport.objects.get().pk), "fixed", stdout=io.StringIO())
        self.assertEqual(BugReport.objects.get().state, "fixed")


class CommandTests(APITestCase):
    def test_marketing_plan_run_command_is_repeatable(self):
        from django.core.management import call_command

        _owner, store, _p = make_store()
        out = io.StringIO()
        call_command("marketing_plan_run", "--store", str(store.pk), stdout=out)
        self.assertIn("اجرا:", out.getvalue())
        n = PlanItem.objects.filter(plan__store=store).count()
        refs_before = sum(len(i.refs) for i in PlanItem.objects.filter(plan__store=store))
        call_command("marketing_plan_run", "--store", str(store.pk), stdout=io.StringIO())
        self.assertEqual(n, PlanItem.objects.filter(plan__store=store).count())
        self.assertEqual(refs_before, sum(len(i.refs) for i in PlanItem.objects.filter(plan__store=store)), "اجرای دوباره چیزِ تازه‌ای ساخت")
        self.assertEqual(PlanItem.objects.filter(plan__store=store, status="FAILED").count(), 0,
                         [(i.key, i.last_error) for i in PlanItem.objects.filter(plan__store=store, status="FAILED")])
        call_command("marketing_plan_run", "--store", str(store.pk), "--report", stdout=io.StringIO())
        runner.tick()
