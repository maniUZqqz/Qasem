"""اصلاح‌های بازبینیِ «اجرای واقعی برای چغر»: متنِ گوینده، قیمتِ تأییدنشده در ارائه/کاتالوگ/ویدیو، پیوندِ هم‌موضوع/هم‌قابِ رسانه‌ها، رندرِ سه‌بعدیِ خودکار،
موسیقیِ ACE-Step. همه با فروشگاهِ ساختگی؛ هیچ دادهٔ واقعی‌ای این‌جا نیست."""
import datetime as dt
import uuid
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.ai.models import AudioAsset
from apps.compute.models import ComputeJob
from apps.design_studio import deck_slides
from apps.design_studio.models import DesignDoc, DesignExport
from apps.motion.models import MotionRender
from apps.products.models import Product
from apps.thumbs.models import Thumbnail

from . import clock, drafts, facts as facts_mod, planner, producers, refs, runner
from .models import PlanItem
from .testkit import make_store, old_campaigns

S = PlanItem.Status

#: جمله‌هایی که «دستورِ نویسنده»اند و هرگز نباید به صدا برسند
WRITER_ONLY = ("بدونِ مقایسه با رقیب", "ننویسید", "از مخاطب بپرسید", "نظرسنجی", "جعبهٔ سؤال", "پیش‌نویس را پیش‌نویس بگو", "نگرانی را با زبانِ خودِ مخاطب", "پاسخِ صادقانه")


def _ctx(plan, store, owner):
    return producers.Ctx(plan=plan, store=store, user=owner, f=facts_mod.store_facts(store))


def _job(store, state=ComputeJob.State.QUEUED, kind="voice.tts"):
    return ComputeJob.objects.create(uid=uuid.uuid4(), kind=kind, state=state, store=store)


class NarrationTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.plan, _ = planner.ensure_plan(self.store, self.owner)
        self.f = dict(facts_mod.store_facts(self.store), site="https://panel.example.test/", values=["شفافیت، پیش‌نویس را پیش‌نویس بگو."])

    def test_reel_script_never_speaks_writer_instructions_a_bare_scheme_or_a_placeholder(self):
        for pillar in ("intro", "how", "objection", "faq", "offer", "behind", "process", "series"):
            text = drafts.reel_script(self.f, pillar)
            self.assertTrue(text.strip(), pillar)
            for bad in WRITER_ONLY:
                self.assertNotIn(bad, text, f"{pillar}: دستورِ نویسنده به صدا رسید")
            for bad in ("//", "https", "http", "[", "]"):
                self.assertNotIn(bad, text, f"{pillar}: «{bad}» به صدا رسید")
        self.assertIn("panel.example.test", drafts.reel_script(self.f, "intro"))
        self.assertIn("panel.example.test", drafts.reel_script(self.f, "offer"))

    def test_motion_spec_shows_only_readable_lines_and_respects_a_missing_logo(self):
        for pillar in ("intro", "how", "objection", "faq", "offer", "behind", "process", "series"):
            spec = drafts.motion_spec(self.f, pillar)
            flat = " ".join(" ".join(map(str, v)) if isinstance(v, list) else str(v) for sc in spec["scenes"] for v in sc.values())
            for bad in WRITER_ONLY + ("https", "[", "//"):
                self.assertNotIn(bad, flat, f"{pillar}: «{bad}» روی صفحهٔ ویدیو آمد")
            self.assertTrue(spec["scenes"][1]["items"], pillar)
            self.assertFalse(spec["brand"]["show_logo"])                 # فروشگاهِ بی‌لوگو ⇒ رندرِ «فروشگاه لوگو ندارد» نمی‌شود
            self.assertNotIn("logo", spec["brand"])
        with_logo = drafts.motion_spec(dict(self.f, has_logo=True), "intro")
        self.assertTrue(with_logo["brand"]["show_logo"])
        self.assertEqual(with_logo["brand"]["logo"], "store-logo")

    def test_the_site_is_spoken_as_people_say_it(self):
        self.assertEqual(drafts.spoken("از کجا شروع کنم؟ https://panel.chagher.ir"), "از کجا شروع کنم؟ panel.chagher.ir")
        self.assertEqual(drafts.spoken("شروع: https://panel.chagher.ir"), "شروع، panel.chagher.ir")
        self.assertEqual(drafts.spoken("برنامهٔ ورزشی + غذایی"), "برنامهٔ ورزشی و غذایی")

    def test_narration_is_taken_from_the_reels_own_spoken_text(self):
        said = "مربی‌ای؟ وقتت باید صرفِ مربیگری شود، نه نوشتنِ برنامه. همین حالا شروع کن."
        self.assertEqual(drafts.narration_from_draft(f"نوع: ریلز\nمتنِ گویندگی (پیشنهادی): {said}\nکپشن: x"), said)
        beats = "ویدیو: ۳ صحنه\n  • نریشن: نوشتنِ برنامه وقتِ مربی را می‌گیرد.\n  • نریشن: چغر پیش‌نویس می‌دهد.\n  • نریشن: بازبینی با توست."
        self.assertEqual(drafts.narration_from_draft(beats), "نوشتنِ برنامه وقتِ مربی را می‌گیرد. چغر پیش‌نویس می‌دهد. بازبینی با توست.")
        self.assertEqual(drafts.narration_from_draft("بدونِ هیچ خطِ گویندگی"), "")

    def test_voiceover_reads_the_companion_reel_even_if_it_was_saved_after_the_context_was_built(self):
        """ریشهٔ خطا: همخوانیِ کارهای هم‌پلن یک بار خوانده و نگه داشته می‌شد؛ گویندهٔ ریلزِ ۲ و ۳ پیش‌نویسِ خالیِ ریلز را می‌دید."""
        ctx = _ctx(self.plan, self.store, self.owner)
        reel = self.plan.items.get(key="d08.reel.2")
        voice = self.plan.items.get(key="d08.voiceover.reel2")
        self.assertIsNotNone(ctx.sibling(reel.key))                 # پیش از آن‌که ریلز پیش‌نویسی داشته باشد یک بار خوانده شد
        said = "نوشتنِ برنامه وقتِ مربی را می‌گیرد. چغر پیش‌نویسِ برنامه را در کمتر از یک دقیقه می‌دهد."
        PlanItem.objects.filter(pk=reel.pk).update(draft="نوع: ریلز\n  • نریشن: نوشتنِ برنامه وقتِ مربی را می‌گیرد.\n  • نریشن: چغر پیش‌نویسِ برنامه را در کمتر از یک دقیقه می‌دهد.")
        self.assertEqual(producers._script_for(ctx, voice), said)


class VoiceoverRepairTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.plan, _ = planner.ensure_plan(self.store, self.owner)
        self.item = self.plan.items.get(key="d08.voiceover.reel2")
        self.reel = self.plan.items.get(key="d08.reel.2")
        PlanItem.objects.filter(pk=self.reel.pk).update(draft="  • نریشن: نوشتنِ برنامه وقتِ مربی را می‌گیرد.\n  • نریشن: بازبینی با توست.")
        self.good = "نوشتنِ برنامه وقتِ مربی را می‌گیرد. بازبینی با توست."
        self.bad = "یک نگرانیِ رایج. شفافیت: پیش‌نویس را پیش‌نویس بگو. بدونِ مقایسه با رقیب و بدونِ تضمین."

    def _pending(self, text):
        job = _job(self.store)
        asset = AudioAsset.objects.create(store=self.store, kind=AudioAsset.Kind.SPEECH, status=AudioAsset.Status.PENDING, title="صدا", text=text, engine="moss-fa", job_uid=job.uid)
        return asset, job

    def _fake_create(self, made):
        def create_speech(store, user, *, text, voice_id, speed=1.0, title="", seed=None):
            job = _job(store)
            a = AudioAsset.objects.create(store=store, kind=AudioAsset.Kind.SPEECH, status=AudioAsset.Status.PENDING, title=title, text=text, engine="moss-fa", job_uid=job.uid)
            made.append(a)
            return a
        return create_speech

    def _run(self, made):
        with mock.patch("services.audio.studio.voices", return_value=[{"id": "moss:mana", "engine": "moss-fa"}]), \
                mock.patch("services.audio.studio.create_speech", side_effect=self._fake_create(made)):
            return producers.run_one(_ctx(self.plan, self.store, self.owner), self.item)

    def test_a_pending_voice_with_a_wrong_text_is_replaced_by_the_right_one(self):
        old, job = self._pending(self.bad)
        self.item.draft = self.bad
        refs.add(self.item, refs.make("audio_asset", old.pk, "صدا"))
        self.item.save()
        made = []
        res = self._run(made)
        self.assertTrue(res["ok"], res)
        self.assertFalse(AudioAsset.objects.filter(pk=old.pk).exists(), "صدای قدیمی باید پاک شود")
        job.refresh_from_db()
        self.assertEqual(job.state, ComputeJob.State.CANCELLED)
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].text, self.good)
        self.assertEqual(self.item.draft, self.good)
        self.assertEqual([r["id"] for r in refs.of_type(self.item, "audio_asset")], [made[0].pk])
        for bad in WRITER_ONLY:
            self.assertNotIn(bad, made[0].text)

    def test_a_pending_voice_that_already_has_the_right_text_is_left_alone(self):
        old, job = self._pending(self.good)
        self.item.draft = self.good
        self.item.meta = {**self.item.meta, "auto_script": self.good}
        refs.add(self.item, refs.make("audio_asset", old.pk, "صدا"))
        self.item.save()
        made = []
        self._run(made)
        self.assertEqual(made, [])
        self.assertTrue(AudioAsset.objects.filter(pk=old.pk).exists())
        job.refresh_from_db()
        self.assertEqual(job.state, ComputeJob.State.QUEUED)

    def test_a_voice_that_is_already_made_is_never_redone(self):
        old, _job_ = self._pending(self.bad)
        AudioAsset.objects.filter(pk=old.pk).update(status=AudioAsset.Status.READY)
        refs.add(self.item, refs.make("audio_asset", old.pk, "صدا"))
        self.item.save()
        made = []
        self._run(made)
        self.assertEqual(made, [])
        self.assertTrue(AudioAsset.objects.filter(pk=old.pk).exists())

    def test_text_the_owner_edited_by_hand_is_kept(self):
        mine = "متنِ خودمان برای این ریلز."
        self.item.draft = mine
        self.item.meta = {**self.item.meta, "auto_script": self.good}
        self.item.save()
        made = []
        self._run(made)
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].text, mine)
        self.assertEqual(self.item.draft, mine)


class PriceHoldTests(TestCase):
    NOTE = "۶۰۰٬۰۰۰ تومان (محاسبه‌شده از قیمتِ بستهٔ توکن؛ جداگانه منتشر نشده)"

    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        Product.objects.filter(pk=self.prod.pk).update(price=600000)
        self.attr = self.prod.attributes.create(key="معادلِ تومانی", value=self.NOTE)
        self.plan, _ = planner.ensure_plan(self.store, self.owner)
        snap = {"id": self.prod.pk, "name": self.prod.name, "sku": "", "short": "کوتاه", "desc": "", "price": 600000.0, "compare_at": None, "currency": "IRT",
                "category": "", "category_id": 0, "images": [], "attrs": [["هزینه", "۵۰ توکن"], ["معادلِ تومانی", self.NOTE]], "tags": [], "brand": ""}
        self.deck = DesignDoc.objects.create(store=self.store, kind="deck", title="ارائه", data={
            "v": 1, "kind": "deck", "settings": {}, "products": [snap], "brief": "", "facts": [], "slides": [
                {"type": "product", "product": self.prod.pk, "id": "s1", "notes": "توضیح\nقیمتِ ثبت‌شده: ۶۰۰٬۰۰۰ تومان"},
                {"type": "comparison", "title": "مقایسه", "id": "s2", "items": [
                    {"product": self.prod.pk, "points": ["هزینه: ۵۰ توکن", "معادلِ تومانی: " + self.NOTE]}]},
            ]})
        self.item = self.plan.items.get(kind="deck")

    def _run(self, item=None):
        return producers.run_one(_ctx(self.plan, self.store, self.owner), item or self.item)

    def test_flagged_price_is_listed_in_the_facts_and_a_normal_price_is_not(self):
        f = facts_mod.store_facts(self.store)
        self.assertEqual([p["id"] for p in f["price_review"]], [self.prod.pk])
        Product.objects.create(store=self.store, name="بدونِ علامت", price=100000)
        self.assertEqual(len(facts_mod.store_facts(self.store)["price_review"]), 1)

    def test_deck_hides_the_unconfirmed_price_everywhere_and_warns(self):
        res = self._run()
        self.assertTrue(res["ok"], res)
        self.deck.refresh_from_db()
        p = self.deck.data["products"][0]
        self.assertIsNone(p["price"])
        self.assertEqual(p["attrs"], [["هزینه", "۵۰ توکن"]])
        flat = str(self.deck.data["slides"])
        self.assertNotIn("محاسبه‌شده", flat)
        self.assertNotIn("۶۰۰٬۰۰۰", flat)
        self.assertIn("هزینه: ۵۰ توکن", flat)                      # بندِ تأییدشده می‌ماند
        self.assertEqual(self.deck.rev, 2)
        self.assertEqual(self.deck.meta["price_hold"], [self.prod.name])
        self.assertTrue(any("تأیید نشده" in c for c in self.item.meta["checks"]), self.item.meta)
        self.assertEqual(Product.objects.get(pk=self.prod.pk).price, 600000)         # خودِ محصول دست‌نخورده
        self._run()
        self.deck.refresh_from_db()
        self.assertEqual(self.deck.rev, 2, "اجرای دوباره نباید سند را دوباره عوض کند")

    def test_after_the_owner_confirms_the_warning_goes_away(self):
        self._run()
        self.attr.delete()
        Product.objects.filter(pk=self.prod.pk).update(short_description="", description="")
        self._run()
        self.assertFalse(self.item.meta.get("checks"))
        self.assertNotIn("price_hold", self.item.meta)

    def test_catalog_gets_the_same_treatment(self):
        cat = DesignDoc.objects.create(store=self.store, kind="catalog", title="کاتالوگ", data={
            "v": 1, "kind": "catalog", "settings": {}, "pages": [], "products": [dict(self.deck.data["products"][0])]})
        item = self.plan.items.get(kind="catalog")
        self._run(item)
        cat.refresh_from_db()
        self.assertIsNone(cat.data["products"][0]["price"])
        self.assertTrue(item.meta["checks"])

    def test_a_queued_video_with_old_slides_is_replaced_by_one_with_the_current_slides(self):
        self._run()                                              # قیمت کنار رفت ⇒ rev=2
        deck_item = self.plan.items.get(kind="deck")
        vid = self.plan.items.get(kind="video_edit")
        job = _job(self.store, kind="edit.slides_mp4")
        old = DesignExport.objects.create(doc=self.deck, kind="mp4", state=DesignExport.State.RUNNING, doc_rev=1, info={"job": str(job.uid)})
        refs.add(vid, refs.make("design_export", old.pk, "ویدیو از ارائه"))
        vid.meta = {**vid.meta, "for": deck_item.key}
        vid.save()
        new_job = _job(self.store, kind="edit.slides_mp4")

        def fake(doc, user, params=None):
            return DesignExport.objects.create(doc=doc, kind="mp4", state=DesignExport.State.RUNNING, doc_rev=doc.rev, info={"job": str(new_job.uid)})

        with mock.patch("apps.design_studio.bridges.deck_to_video", side_effect=fake):
            res = producers.run_one(_ctx(self.plan, self.store, self.owner), vid)
        self.assertTrue(res["ok"], res)
        job.refresh_from_db()
        self.assertEqual(job.state, ComputeJob.State.CANCELLED)
        self.assertFalse(DesignExport.objects.filter(pk=old.pk).exists())
        ids = [r["id"] for r in refs.of_type(vid, "design_export")]
        self.assertEqual(len(ids), 1)
        self.assertEqual(DesignExport.objects.get(pk=ids[0]).doc_rev, 2)
        self.assertTrue(any("بدونِ قیمتِ تأییدنشده" in c for c in vid.meta["checks"]))

    def test_a_video_already_running_on_the_node_is_not_touched(self):
        self._run()
        vid = self.plan.items.get(kind="video_edit")
        job = _job(self.store, state=ComputeJob.State.RUNNING, kind="edit.slides_mp4")
        old = DesignExport.objects.create(doc=self.deck, kind="mp4", state=DesignExport.State.RUNNING, doc_rev=1, info={"job": str(job.uid)})
        refs.add(vid, refs.make("design_export", old.pk, "ویدیو از ارائه"))
        vid.meta = {**vid.meta, "for": self.plan.items.get(kind="deck").key}
        vid.save()
        producers.run_one(_ctx(self.plan, self.store, self.owner), vid)
        self.assertTrue(DesignExport.objects.filter(pk=old.pk).exists())
        job.refresh_from_db()
        self.assertEqual(job.state, ComputeJob.State.RUNNING)

    def test_internal_file_paths_are_not_printed_under_a_slide_statistic(self):
        self.assertEqual(deck_slides.public_source("docs/chagher/brand-facts-fa.md — بخش ۲ (از دیتابیسِ خودِ چغر)"), "")
        self.assertEqual(deck_slides.public_source("brand-facts-fa.md"), "")
        self.assertEqual(deck_slides.public_source("فهرستِ محصولاتِ فروشگاه (پنل)"), "فهرستِ محصولاتِ فروشگاه (پنل)")
        self.assertEqual(deck_slides.public_source("قیمتِ ثبت‌شدهٔ «برنامه»"), "قیمتِ ثبت‌شدهٔ «برنامه»")


class MediaLinkTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.plan, _ = planner.ensure_plan(self.store, self.owner)
        self.before = self.plan.created_at - dt.timedelta(days=2)

    def _old(self, model, **kw):
        row = model.objects.create(store=self.store, **kw)
        model.objects.filter(pk=row.pk).update(created_at=self.before)
        return model.objects.get(pk=row.pk)

    def test_motion_does_not_adopt_a_render_of_another_frame_or_topic(self):
        item = self.plan.items.get(key="d08.motion.reel2")
        wrong = self._old(MotionRender, title="چغر — موشن: ایزومتریک (چهار قدم)", style="isometric", aspect="4:5", state=MotionRender.State.WAITING_NODE)
        refs.add(item, refs.make("motion_render", wrong.pk, wrong.title))                   # پیوندِ قدیمیِ ناهم‌قاب
        item.save()
        made = []

        def create(store, user, **kw):
            r = MotionRender.objects.create(store=store, title=kw["title"], style="glassmorphism", aspect=kw["spec"]["aspect"], spec=kw["spec"], state=MotionRender.State.WAITING_NODE)
            made.append(r)
            return r

        with mock.patch("apps.motion.services.create", side_effect=create), mock.patch("apps.motion.services.start", side_effect=lambda r: r):
            res = producers.run_one(_ctx(self.plan, self.store, self.owner), item)
        self.assertTrue(res["ok"], res)
        self.assertEqual([r["id"] for r in refs.of_type(item, "motion_render")], [made[0].pk])
        self.assertEqual(made[0].aspect, "9:16")
        self.assertTrue(MotionRender.objects.filter(pk=wrong.pk).exists(), "رندرِ قدیمی پاک نمی‌شود، فقط از این کار جدا می‌شود")

    def test_motion_adopts_a_render_of_the_same_frame_and_topic(self):
        item = self.plan.items.get(key="d08.motion.reel2")
        right = self._old(MotionRender, title="چغر — موشن: پاسخ به نگرانیِ رایج", style="kinetic-typography", aspect="9:16", state=MotionRender.State.WAITING_NODE)
        with mock.patch("apps.motion.services.create", side_effect=AssertionError("نباید ساخته شود")):
            res = producers.run_one(_ctx(self.plan, self.store, self.owner), item)
        self.assertTrue(res["ok"], res)
        self.assertEqual([r["id"] for r in refs.of_type(item, "motion_render")], [right.pk])

    def test_a_reel_cover_never_takes_a_portrait_thumbnail(self):
        item = self.plan.items.get(key="d02.thumbnail.reel1")
        portrait = self._old(Thumbnail, title="چغر — جلد مجله", format="ig_portrait", style="magazine_cover", state=Thumbnail.State.WAITING_BG)
        refs.add(item, refs.make("thumbnail", portrait.pk, portrait.title))
        item.save()
        story = self._old(Thumbnail, title="چغر — کاور", format="story", style="question_hook", state=Thumbnail.State.WAITING_BG)
        producers.run_one(_ctx(self.plan, self.store, self.owner), item)
        ids = [r["id"] for r in refs.of_type(item, "thumbnail")]
        self.assertNotIn(portrait.pk, ids)
        self.assertIn(story.pk, ids)                                                         # قابِ ۹:۱۶ همان‌جا که هست وصل می‌شود

    def test_music_links_the_ace_step_asset_and_keeps_the_starter_only_as_a_preview(self):
        item = self.plan.items.get(key="d01.music.bed")
        starter = AudioAsset.objects.create(store=self.store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY, engine="starter", license="CC0", title="آرامش — پیانوی ملایم")
        ace = AudioAsset.objects.create(store=self.store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.PENDING, engine="acestep", license="MIT", title="موسیقی: شاد و پرانرژی")
        refs.add(item, refs.make("audio_asset", starter.pk, starter.title))
        item.save()
        res = producers.run_one(_ctx(self.plan, self.store, self.owner), item)
        self.assertTrue(res["ok"], res)
        self.assertEqual(sorted(r["id"] for r in refs.of_type(item, "audio_asset")), sorted([starter.pk, ace.pk]))
        self.assertIn("ACE-Step", item.draft)
        runner.sync_item(item)
        self.assertEqual(item.status, S.WAITING_NODE)                                        # آماده‌شدنِ نمونهٔ CC0 «موسیقیِ ACE-Step» را آماده حساب نمی‌کند
        again = producers.run_one(_ctx(self.plan, self.store, self.owner), item)
        self.assertTrue(again["ok"])
        self.assertEqual(len(refs.of_type(item, "audio_asset")), 2)

    def test_music_without_any_ace_asset_asks_the_studio_for_one(self):
        item = self.plan.items.get(key="d01.music.bed")
        starter = AudioAsset.objects.create(store=self.store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY, engine="starter", license="CC0", title="آرامش")
        refs.add(item, refs.make("audio_asset", starter.pk, starter.title))
        item.save()

        def make(store, user, *, style, seconds, title):
            return AudioAsset.objects.create(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.PENDING, engine="acestep", title=title)

        with mock.patch("services.audio.studio.create_music", side_effect=make) as m:
            producers.run_one(_ctx(self.plan, self.store, self.owner), item)
        self.assertEqual(m.call_count, 1)

    def test_profile_title_uses_persian_digits(self):
        old_campaigns(self.store, self.prod)
        # کارِ «پروفایل» با کمپینِ «پروفایل» ⇒ عنوان با عددِ فارسی
        item = self.plan.items.get(kind="profile")
        producers.run_one(_ctx(self.plan, self.store, self.owner), item)
        self.assertIn("کارِ آماده", item.title)
        self.assertFalse(any(ch in "0123456789" for ch in item.title), item.title)


class CharacterPosesTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.plan, _ = planner.ensure_plan(self.store, self.owner)

    def test_more_poses_never_queue_the_standing_pose_again(self):
        from apps.brandchar import services as BS
        from apps.brandchar.models import CharacterAIJob

        char = BS.create(self.store, self.owner)
        item = self.plan.items.get(key="d10.character.poses")
        job = _job(self.store, kind="brandchar.render")
        dup = CharacterAIJob.objects.create(character=char, store=self.store, compute_uid=str(job.uid), pose="stand", state=CharacterAIJob.State.QUEUED)
        wave_job = _job(self.store, kind="brandchar.render")
        wave = CharacterAIJob.objects.create(character=char, store=self.store, compute_uid=str(wave_job.uid), pose="wave", state=CharacterAIJob.State.QUEUED)
        for j in (dup, wave):
            refs.add(item, refs.make("character_job", j.pk, "x"))
        item.save()
        started = []

        def start(c, user, *, mode="illustrated", look="", extra="", pose="stand", expression="happy", seed=None):
            j = _job(self.store, kind="brandchar.render")
            row = CharacterAIJob.objects.create(character=c, store=c.store, compute_uid=str(j.uid), pose=pose, mode=mode, state=CharacterAIJob.State.QUEUED)
            started.append(pose)
            return row

        with mock.patch("apps.brandchar.ai_render.start", side_effect=start), mock.patch("apps.brandchar.services.ensure_cover", return_value=None):
            res = producers.run_one(_ctx(self.plan, self.store, self.owner), item)
        self.assertTrue(res["ok"], res)
        self.assertEqual(sorted(started), ["cheer", "think"])
        dup.refresh_from_db()
        self.assertEqual(dup.state, CharacterAIJob.State.FAILED)
        job.refresh_from_db()
        self.assertEqual(job.state, ComputeJob.State.CANCELLED)
        poses = sorted(CharacterAIJob.objects.get(pk=r["id"]).pose for r in refs.of_type(item, "character_job"))
        self.assertEqual(poses, ["cheer", "think", "wave"])


class Up3dRenderTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.plan, _ = planner.ensure_plan(self.store, self.owner)
        self.item = self.plan.items.get(kind="up3d")

    def _run(self):
        return producers.run_one(_ctx(self.plan, self.store, self.owner), self.item)

    def test_the_final_render_is_queued_by_itself_and_the_item_waits_for_the_node(self):
        from apps.up3d import services as U
        from apps.up3d.models import Job

        res = self._run()                                        # پروژه ساخته می‌شود ولی هنوز صحنه ندارد
        self.assertTrue(res["ok"], res)
        self.assertTrue(self.item.meta.get("retry_soon"))
        self.assertTrue(runner._needs_rerun(self.item, node_on=False), "تیکِ بعد حتی با گرهٔ خاموش دوباره امتحان می‌کند")
        proj_ref = refs.of_type(self.item, "up3d_project")[0]
        plan_job = Job.objects.get(project_id=proj_ref["id"], kind="plan")
        U.process_plan(plan_job)                                 # کارِ هماهنگ‌کننده: برنامه‌ریزیِ قالبی
        self._run()
        self.assertFalse(self.item.meta.get("retry_soon"))
        jobs = refs.of_type(self.item, "up3d_job")
        self.assertEqual(len(jobs), 1)
        job = Job.objects.get(pk=jobs[0]["id"])
        self.assertEqual((job.kind, job.profile), ("render", producers.RENDER_PROFILE))
        self.assertTrue(job.params.get("silent_fallback"), "بدونِ اعتبارِ سرویسِ صدا رندر نباید از همان اول بشکند")
        runner.sync_item(self.item)
        self.assertEqual(self.item.status, S.WAITING_NODE)
        self._run()
        self.assertEqual(Job.objects.filter(project_id=proj_ref["id"], kind="render").count(), 1, "اجرای دوباره رندرِ دوم نمی‌سازد")
        self.assertTrue(self.item.needs_node)

    def test_a_failed_render_is_requested_again_but_only_a_few_times(self):
        from apps.up3d import services as U
        from apps.up3d.models import Job

        self._run()
        proj_id = refs.of_type(self.item, "up3d_project")[0]["id"]
        U.process_plan(Job.objects.get(project_id=proj_id, kind="plan"))
        self._run()
        for n in range(1, producers.MAX_RENDER_FAILS + 1):
            job = Job.objects.filter(project_id=proj_id, kind="render").exclude(state="FAILED").get()
            Job.objects.filter(pk=job.pk).update(state="FAILED", message="سرویسِ صدا خطا داد")
            res = self._run()
            if n < producers.MAX_RENDER_FAILS:
                self.assertTrue(res["ok"], res)
                ids = [r["id"] for r in refs.of_type(self.item, "up3d_job")]
                self.assertEqual(len(ids), 1, "پیوندِ رندرِ ناموفق باید کنار برود")
                self.assertNotEqual(ids[0], job.pk)
                self.assertTrue(Job.objects.get(pk=ids[0]).params.get("silent_fallback"))
        self.assertFalse(res["ok"])                                   # بعد از سه بار ناموفق: خطا به کارت می‌رسد و رندرِ تازه ساخته نمی‌شود
        self.assertIn("ناموفق", self.item.last_error)
        self.assertEqual(Job.objects.filter(project_id=proj_id, kind="render").count(), producers.MAX_RENDER_FAILS)
