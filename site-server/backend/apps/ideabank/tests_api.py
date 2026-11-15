"""API بانکِ ایده: فهرست و فیلتر، ایده‌های خودِ فروشگاه، ستاره/پنهانِ هر فروشگاه، «ایده بساز» (هوش مصنوعی خاموش ⇒ فرمول)، «از این ایده شروع کن»
(استودیو، تقویم، تامنیل)، ذخیره از ترندها، و دسترسیِ نقش‌ها."""
import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.trend_models import Trend, TrendIdea
from apps.campaigns.models import Campaign
from apps.campaigns.tasks_board import CampaignTask
from apps.igtrends.models import IgTrendCluster
from apps.products.models import Product
from apps.stores.models import Membership, Store

from . import bank
from .models import IdeaUse, StoreIdea
from .seeds import BUILTIN_IDEAS

User = get_user_model()


class ApiBase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("ib-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", business_type="نرم‌افزار برای مربیان ورزشی",
                                          target_audience="مربی‌های باشگاه و مربی‌های شخصی که برنامه می‌نویسند؛ و ورزشکاران.")
        self.product = Product.objects.create(store=self.store, name="برنامه‌سازِ هوشمند", price=0)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/ideas"

    def client_for(self, role: str, name: str):
        u = User.objects.create_user(name, password="x")
        Membership.objects.create(store=self.store, user=u, role=role)
        c = APIClient()
        c.force_authenticate(u)
        return c


class ListTests(ApiBase):
    def test_list_has_everything_the_page_needs(self):
        r = self.api.get(f"{self.base}/")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual(b["total"], len(BUILTIN_IDEAS))
        self.assertEqual(len(b["ideas"]), b["shown"])
        self.assertEqual([c["key"] for c in b["categories"]], ["tips", "behind", "product", "faq", "proof", "occasion", "engage", "offer"])
        self.assertEqual({f["key"] for f in b["formats"]}, {"reel", "carousel", "photo", "story"})
        self.assertEqual(b["store"]["name"], "چغر")
        self.assertEqual(b["store"]["values"]["مخاطب"], "مربی‌های باشگاه و مربی‌های شخصی")
        self.assertEqual([p["name"] for p in b["products"]], ["برنامه‌سازِ هوشمند"])
        self.assertEqual(b["campaigns"], [])
        self.assertIn("ok", b["ai"])
        self.assertFalse(b["ai"]["ok"])                                                      # زیرِ آزمون هوش مصنوعی صدا زده نمی‌شود
        first = b["ideas"][0]
        for k in ("key", "title", "filled", "slots", "needs_data", "favorite", "hidden", "uses", "builtin", "format", "channel", "category"):
            self.assertIn(k, first)

    def test_product_fills_the_placeholder(self):
        a = self.api.get(f"{self.base}/?q=معرفیِ محصول در یک ریل").json()["ideas"][0]
        self.assertIn("محصول", a["filled"]["title"])
        self.assertNotIn("{", a["filled"]["title"])
        b = self.api.get(f"{self.base}/?q=معرفیِ&product={self.product.pk}").json()["ideas"]
        self.assertTrue(any("برنامه‌سازِ هوشمند" in i["filled"]["title"] for i in b))
        self.assertTrue(all("{" not in i["filled"]["title"] for i in b))

    def test_filters(self):
        self.assertTrue(all(i["category"] == "occasion" for i in self.api.get(f"{self.base}/?category=occasion").json()["ideas"]))
        self.assertTrue(all(i["format"] == "reel" for i in self.api.get(f"{self.base}/?fmt=reel").json()["ideas"]))
        self.assertTrue(all(i["slots"] for i in self.api.get(f"{self.base}/?needs_data=1").json()["ideas"]))
        self.assertEqual(self.api.get(f"{self.base}/?q=zzzzqqq").json()["shown"], 0)
        self.assertEqual(self.api.get(f"{self.base}/?source=mine").json()["shown"], 0)
        self.assertEqual(self.api.get(f"{self.base}/?source=builtin").json()["shown"], len(BUILTIN_IDEAS))

    def test_random(self):
        r = self.api.get(f"{self.base}/random/?category=offer")
        self.assertEqual((r.status_code, r.json()["category"]), (200, "offer"))
        self.assertEqual(self.api.get(f"{self.base}/random/?category=zzz").status_code, 404)


class WriteTests(ApiBase):
    def test_create_edit_copy_delete(self):
        r = self.api.post(f"{self.base}/", {"title": "ایدهٔ من", "logline": "یک توضیح", "category": "engage", "format": "story"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        key = r.json()["key"]
        self.assertEqual(self.api.get(f"{self.base}/{key}/").json()["title"], "ایدهٔ من")
        e = self.api.patch(f"{self.base}/{key}/", {"title": "ایدهٔ ویرایش‌شده"}, format="json")
        self.assertEqual((e.status_code, e.json()["title"]), (200, "ایدهٔ ویرایش‌شده"))
        d = self.api.post(f"{self.base}/tips_mistake/duplicate/", {}, format="json")
        self.assertEqual((d.status_code, d.json()["origin"]), (201, "duplicate"))
        self.assertEqual(self.api.patch(f"{self.base}/tips_mistake/", {"title": "x"}, format="json").status_code, 409)
        self.assertEqual(self.api.delete(f"{self.base}/tips_mistake/").status_code, 409)
        self.assertEqual(self.api.delete(f"{self.base}/{key}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/{key}/").status_code, 404)
        self.assertEqual(self.api.post(f"{self.base}/", {"title": "فقط عنوان"}, format="json").status_code, 400)

    def test_marks_are_per_store(self):
        other_owner = User.objects.create_user("ib-owner2", password="x")
        other = Store.objects.create(owner=other_owner, name="دیگر")
        r = self.api.post(f"{self.base}/tips_mistake/mark/", {"favorite": True}, format="json")
        self.assertTrue(r.json()["favorite"])
        self.api.post(f"{self.base}/tips_howto/mark/", {"hidden": True}, format="json")
        c = APIClient()
        c.force_authenticate(other_owner)
        theirs = c.get(f"/api/v1/stores/{other.pk}/ideas/").json()["ideas"]
        self.assertFalse(any(i["favorite"] for i in theirs))
        self.assertIn("tips_howto", [i["key"] for i in theirs])
        mine = self.api.get(f"{self.base}/").json()["ideas"]
        self.assertEqual(mine[0]["key"], "tips_mistake")
        self.assertNotIn("tips_howto", [i["key"] for i in mine])
        self.assertIn("tips_howto", [i["key"] for i in self.api.get(f"{self.base}/?hidden=1").json()["ideas"]])
        self.assertEqual(self.api.post(f"{self.base}/no_such/mark/", {"favorite": True}, format="json").status_code, 404)
        self.assertEqual(c.get(f"/api/v1/stores/{other.pk}/ideas/tips_mistake/").json()["favorite"], False)

    def test_generate_with_ai_off_gives_formula_ideas_and_saves_them(self):
        r = self.api.post(f"{self.base}/generate/", {"topic": "برنامهٔ ورزشی", "count": 5, "product": self.product.pk,
                                                      "facts": ["با چغر چغر تر شو"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual(b["via"], "formula")
        self.assertIn("هوش مصنوعی در دسترس نبود", b["message"])
        self.assertEqual(b["saved"], len(b["ideas"]))
        self.assertEqual(StoreIdea.objects.filter(store=self.store).count(), b["saved"])
        self.assertTrue(all(i["origin"] == "generated" for i in b["ideas"]))
        mine = self.api.get(f"{self.base}/?source=mine").json()
        self.assertEqual(mine["shown"], b["saved"])
        again = self.api.post(f"{self.base}/generate/", {"topic": "برنامهٔ ورزشی", "count": 5}, format="json").json()
        self.assertFalse({i["title"] for i in again["ideas"]} & {i["title"] for i in b["ideas"]})

    def test_generate_preview_does_not_save_and_validates(self):
        r = self.api.post(f"{self.base}/generate/", {"topic": "قهوه", "count": 3, "ai": False, "save": False}, format="json")
        self.assertEqual((r.status_code, r.json()["via"]), (200, "formula"))
        self.assertEqual(StoreIdea.objects.count(), 0)
        self.assertIn("خاموش", r.json()["message"])
        self.assertEqual(self.api.post(f"{self.base}/generate/", {"category": "nope"}, format="json").status_code, 400)
        r2 = self.api.post(f"{self.base}/generate/", {"category": "faq", "count": 3, "facts": "یک جمله\nجملهٔ دیگر"}, format="json")
        self.assertTrue(all(i["category"] == "faq" for i in r2.json()["ideas"]))


class StartTests(ApiBase):
    def test_studio_handoff_carries_a_ready_brief_and_the_right_tab(self):
        r = self.api.post(f"{self.base}/tips_mistake/start/", {"target": "studio", "product": self.product.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual((b["target"], b["tab"], b["product_id"]), ("studio", "video", self.product.pk))
        self.assertIn("برنامه‌سازِ هوشمند", b["brief"])                                      # {محصول} پر شده
        self.assertNotIn("{", b["brief"] + b["detail"])
        self.assertLessEqual(len(b["brief"]), 200)                                             # «هدف» یک CharField(200) است
        self.assertLessEqual(len(b["detail"]), 500)
        self.assertIn("چه بگیریم", b["detail"])
        self.assertEqual([t["key"] for t in b["tabs"]], ["video", "image", "caption"])
        self.assertEqual(b["uses"], 1)
        photo = self.api.post(f"{self.base}/product_in_use/start/", {"target": "studio"}, format="json").json()
        self.assertEqual(photo["tab"], "image")
        self.assertEqual(IdeaUse.objects.filter(store=self.store, target="studio").count(), 2)

    def test_thumbnail_handoff_maps_the_format_and_the_channel(self):
        b = self.api.post(f"{self.base}/tips_mistake/start/", {"target": "thumbnail"}, format="json").json()
        self.assertEqual((b["format"], b["kicker"]), ("story", "آموزش و نکتهٔ کاربردی"))
        self.assertEqual(b["title"], "اگر محصول را این‌طور به کار می‌بری")                    # قلاب (تا اولین «،») عنوانِ تامنیل است
        self.assertEqual(b["subtitle"], "اشتباهِ رایج دربارهٔ محصول")                         # عنوانِ ایده زیرعنوان
        self.assertLessEqual(len(b["title"]), 100)
        c = self.api.post(f"{self.base}/tips_howto/start/", {"target": "thumbnail"}, format="json").json()
        self.assertEqual(c["format"], "ig_portrait")
        t = bank.create_idea(self.store, {"title": "خبرِ کانال", "logline": "برای کانال", "channel": "telegram", "format": "photo"})
        self.assertEqual(self.api.post(f"{self.base}/{t['key']}/start/", {"target": "thumbnail"}, format="json").json()["format"], "telegram")

    def test_calendar_handoff_creates_a_planned_content_task(self):
        camp = Campaign.objects.create(store=self.store, product=self.product, name="کمپینِ نمونه")
        r = self.api.post(f"{self.base}/tips_mistake/start/", {"target": "calendar", "campaign": camp.pk, "due": "2026-12-01"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        task = CampaignTask.objects.get(pk=r.json()["task_id"])
        self.assertEqual((task.campaign_id, task.store_id, task.kind), (camp.pk, self.store.pk, "CONTENT"))
        self.assertTrue(task.title and "قلاب" in task.detail and "چه چیزی بگیریم" in task.detail and "ریلز" in task.detail)
        self.assertEqual(timezone.localtime(task.due_at).date().isoformat(), "2026-12-01")
        self.assertEqual(timezone.localtime(task.due_at).hour, 10)
        self.assertIn("از بانکِ ایده", task.because)
        planned = self.api.get(f"/api/v1/stores/{self.store.pk}/planned/").json()                  # همان فهرستی که «تقویم انتشار» نشان می‌دهد
        self.assertEqual([p["id"] for p in planned], [task.pk])
        self.assertEqual(IdeaUse.objects.get(store=self.store, target="calendar").task_id, task.pk)

    def test_calendar_by_product_makes_one_content_plan_campaign(self):
        for key in ("tips_mistake", "tips_howto"):
            r = self.api.post(f"{self.base}/{key}/start/", {"target": "calendar", "product": self.product.pk}, format="json")
            self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Campaign.objects.filter(store=self.store).count(), 1)
        self.assertEqual(CampaignTask.objects.filter(store=self.store).count(), 2)
        tomorrow = timezone.localdate() + dt.timedelta(days=1)
        self.assertEqual(timezone.localtime(CampaignTask.objects.first().due_at).date(), tomorrow)

    def test_occasion_idea_defaults_to_the_date_of_the_occasion(self):
        r = self.api.post(f"{self.base}/occasion_yalda/start/", {"target": "calendar", "product": self.product.pk}, format="json").json()
        task = CampaignTask.objects.get(pk=r["task_id"])
        info = bank.get_idea(self.store, "occasion_yalda")["occasion_next"]
        self.assertEqual(timezone.localtime(task.due_at).date().isoformat(), info["date"])

    def test_calendar_needs_a_campaign_or_a_product_and_real_ones(self):
        self.assertEqual(self.api.post(f"{self.base}/tips_mistake/start/", {"target": "calendar"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/tips_mistake/start/", {"target": "calendar", "campaign": 99999}, format="json").status_code, 404)
        other = Store.objects.create(owner=User.objects.create_user("ib-x", password="x"), name="x")
        foreign = Campaign.objects.create(store=other, product=Product.objects.create(store=other, name="p", price=0), name="دیگری")
        self.assertEqual(self.api.post(f"{self.base}/tips_mistake/start/", {"target": "calendar", "campaign": foreign.pk}, format="json").status_code, 404)
        self.assertEqual(self.api.post(f"{self.base}/tips_mistake/start/", {"target": "calendar", "product": self.product.pk, "due": "نه"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/tips_mistake/start/", {"target": "nope"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/no_such/start/", {"target": "studio"}, format="json").status_code, 404)

    def test_slots_are_reported_so_the_page_can_warn(self):
        b = self.api.post(f"{self.base}/offer_weekly/start/", {"target": "studio"}, format="json").json()
        self.assertTrue(b["needs_data"])
        self.assertIn("[", b["brief"])


class TrendSaveTests(ApiBase):
    def test_save_a_trend_idea(self):
        trend = Trend.objects.create(title="تمرین در خانه", region="IR")
        ti = TrendIdea.objects.create(store=self.store, trend=trend, product=self.product, kind="VIDEO", idea="یک ریلِ کوتاه از تمرینِ بدونِ وسیله بسازید.\n\nمراحل:\n• قلاب\n• نمایش",
                                      why="چون مخاطبِ شما در خانه تمرین می‌کند.", hook="در خانه هم می‌شود تمرین کرد")
        r = self.api.post(f"{self.base}/from-trend/", {"trend_idea": ti.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        idea = r.json()["idea"]
        self.assertEqual((idea["origin"], idea["format"], idea["hook"]), ("trend", "reel", "در خانه هم می‌شود تمرین کرد"))
        self.assertIn("ترند", idea["tags"])
        self.assertIn("قلاب", idea["shoot"])
        again = self.api.post(f"{self.base}/from-trend/", {"trend_idea": ti.pk}, format="json")
        self.assertEqual((again.status_code, again.json()["created"]), (200, False))
        self.assertEqual(StoreIdea.objects.filter(store=self.store).count(), 1)
        self.assertEqual(self.api.post(f"{self.base}/from-trend/", {"trend_idea": 99999}, format="json").status_code, 404)

    def test_save_an_instagram_topic_after_its_brief(self):
        cl = IgTrendCluster.objects.create(store=self.store, key="abc", label="تمرین در خانه · #تمرین", fmt="reel")
        self.assertEqual(self.api.post(f"{self.base}/from-trend/", {"cluster": cl.pk}, format="json").status_code, 409)       # هنوز «ایده بساز» نزده
        cl.brief = {"hook": "این تمرین را در خانه امتحان کن", "idea": "یک ریلِ کوتاه از یک تمرینِ ساده در خانه.", "outline": ["قلاب", "نمایشِ عملی"],
                    "format": "reel", "hashtags": ["#تمرین_در_خانه"]}
        cl.save()
        r = self.api.post(f"{self.base}/from-trend/", {"cluster": cl.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["idea"]["format"], r.json()["idea"]["origin"]), ("reel", "trend"))
        self.assertIn("تمرین_در_خانه", r.json()["idea"]["tags"])
        self.assertEqual(self.api.post(f"{self.base}/from-trend/", {}, format="json").status_code, 400)


class AccessTests(ApiBase):
    def test_stranger_gets_404(self):
        c = APIClient()
        c.force_authenticate(User.objects.create_user("stranger", password="x"))
        self.assertEqual(c.get(f"{self.base}/").status_code, 404)
        self.assertEqual(c.post(f"{self.base}/generate/", {}, format="json").status_code, 404)

    def test_anonymous_is_refused(self):
        self.assertIn(APIClient().get(f"{self.base}/").status_code, (401, 403))

    def test_viewer_reads_but_cannot_write(self):
        v = self.client_for("VIEWER", "ib-viewer")
        self.assertEqual(v.get(f"{self.base}/").status_code, 200)
        self.assertEqual(v.post(f"{self.base}/generate/", {"topic": "x"}, format="json").status_code, 403)
        self.assertEqual(v.post(f"{self.base}/tips_mistake/mark/", {"favorite": True}, format="json").status_code, 403)

    def test_content_manager_can_play_but_cannot_plan_the_calendar(self):
        m = self.client_for("CONTENT", "ib-content")
        self.assertEqual(m.post(f"{self.base}/tips_mistake/mark/", {"favorite": True}, format="json").status_code, 200)
        self.assertEqual(m.post(f"{self.base}/tips_mistake/start/", {"target": "studio"}, format="json").status_code, 200)
        self.assertEqual(m.post(f"{self.base}/tips_mistake/start/", {"target": "calendar", "product": self.product.pk}, format="json").status_code, 403)
        mk = self.client_for("MARKETING", "ib-marketing")
        self.assertEqual(mk.post(f"{self.base}/tips_mistake/start/", {"target": "calendar", "product": self.product.pk}, format="json").status_code, 201)
