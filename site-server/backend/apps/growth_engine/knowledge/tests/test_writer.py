"""The AI message writer, with the AI replaced: zero real AI calls. What is checked is everything AROUND the model - its prompt, its
grounding, the checks on its answer, the versions, and what happens when no model can answer."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.knowledge.models import GeneratedMessage, KnowledgeItem
from apps.growth_engine.knowledge.services import ai, context, seed, versions, writer
from apps.growth_engine.outreach.models import Campaign, Channel, ItemStatus, MessageTemplate, OutreachItem
from apps.growth_engine.outreach.services import approval, campaigns, items, preparing

from apps.growth_engine.outreach.tests.helpers import configure, make_lead, make_template

G = "/api/v1/growth"
ROUTE = {"via": "local", "model": "gemma3:12b", "attempts": [{"via": "local", "ok": True}]}


def answer(**kw):
    base = {
        "subject": "", "message": "سلام؛ از روی عکسِ محصول پوستر و ویدیوی تبلیغاتی می‌سازیم و دو هفته رایگان است.",
        "personalization_reason": "نامِ شهرِ شما را دیدم و فروشگاهتان فروشگاهِ محصولِ فیزیکی است.", "evidence_references": [], "warnings": [],
    }
    base.update(kw)
    return base


class Base(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        seed.restore_defaults()
        self.refs = {k.seed_key: f"K{k.pk}" for k in KnowledgeItem.objects.exclude(seed_key=None)}
        self.template = MessageTemplate.objects.get(seed_key="contact_form")
        self.campaign = campaigns.create_campaign(name="ک", template=self.template, mode=Campaign.Mode.AUTO, user=self.staff)
        self.lead = make_lead("w1.ir", name="فروشگاه رها", city="همدان", category="پوشاک", description="فروشگاهِ لباسِ زنانه")
        self.item = campaigns.add_leads(self.campaign, [self.lead.pk]).added[0]
        self.item.refresh_from_db()

    def run_writer(self, payload, *, instructions="", item=None):
        item = item or self.item
        version, _ = versions.request_version(item, self.staff, instructions)
        with mock.patch.object(ai, "complete_json", return_value=(payload, ROUTE)) as fake:
            writer.run(version.pk)
        version.refresh_from_db()
        self.fake = fake
        return version


class ContextTests(Base):
    def test_the_context_holds_the_knowledge_and_the_leads_own_facts_only(self):
        ctx = context.build(self.item)
        by_label = {f.label: f for f in ctx.facts}
        self.assertEqual(by_label["نامِ کسب‌وکار"].text, "فروشگاه رها")
        self.assertEqual(by_label["شهر"].text, "همدان")
        self.assertEqual(by_label["دسته"].text, "پوشاک")
        self.assertEqual(by_label["توضیحاتِ ثبت‌شده"].text, "فروشگاهِ لباسِ زنانه")
        refs = [f.ref for f in ctx.facts]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertTrue(any(r.startswith("K") for r in refs) and any(r.startswith("F") for r in refs) and "S1" in refs)

    def test_inactive_items_and_an_empty_price_are_not_facts(self):
        ctx = context.build(self.item)
        texts = " ".join(f.text for f in ctx.facts)
        self.assertNotIn("سایت‌ساز", texts)  # seeded inactive
        self.assertFalse(ctx.price_known)
        self.assertNotIn(f"K{KnowledgeItem.objects.get(section='price').pk}", [f.ref for f in ctx.facts])

    def test_a_typed_price_becomes_a_fact_and_its_numbers_become_known(self):
        price = KnowledgeItem.objects.get(section="price")
        price.body = "پلنِ پایه ۴۹۰ هزار تومان در ماه"
        price.save()
        ctx = context.build(self.item)
        self.assertTrue(ctx.price_known)
        self.assertIn("490", ctx.numbers)

    def test_number_words_in_the_knowledge_ground_digits(self):
        ctx = context.build(self.item)
        self.assertIn("2", ctx.numbers)  # «دو هفته رایگان»
        self.assertIn("5", ctx.numbers)  # «۵ ثانیه»
        self.assertNotIn("7", ctx.numbers)

    def test_numbers_in_persian_and_arabic_digits_are_compared_as_plain_digits(self):
        self.assertEqual(context.numbers_in("۱۲ و ٣٤ و 5"), ["12", "34", "5"])
        self.assertEqual(context.numbers_in("۴۹۰,۰۰۰"), ["490000"])


class PromptTests(Base):
    def test_the_prompt_carries_the_rules_the_facts_and_the_channel(self):
        ctx = context.build(self.item)
        system, prompt = writer.build_prompt(self.item, ctx, "کوتاه‌تر بنویس", GrowthSettings.load())
        for rule in ("فقط از «حقایقِ داده‌شده»", "هرگز چیزی از خودت اختراع نکن", "نه قیمت", "امضا", "JSON"):
            self.assertIn(rule, system)
        self.assertIn("فروشگاه رها", prompt)
        self.assertIn("دو هفته", prompt)
        self.assertIn("فرمِ تماسِ سایتِ آن‌ها", prompt)
        self.assertIn("کوتاه‌تر بنویس", prompt)
        self.assertIn("هیچ قیمتی در حقایق نیست", prompt)  # no price typed in

    def test_the_prompt_never_contains_the_leads_contact_details_or_secrets(self):
        lead = make_lead("w2.ir", phone="09125550077", email="secret-person@w2.ir")
        item = campaigns.add_leads(self.campaign, [lead.pk]).added[0]
        _, prompt = writer.build_prompt(item, context.build(item), "", GrowthSettings.load())
        self.assertNotIn("09125550077", prompt)
        self.assertNotIn("secret-person@w2.ir", prompt)

    def test_the_sms_prompt_carries_the_size_that_is_left_after_the_closing_block(self):
        sms_template = MessageTemplate.objects.get(seed_key="sms")
        campaign = campaigns.create_campaign(name="پ", template=sms_template, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        item = campaigns.add_leads(campaign, [make_lead("w3.ir", phone="09125550078").pk]).added[0]
        settings_obj = GrowthSettings.load()
        limit = writer.size_hint(Channel.SMS, settings_obj)
        self.assertLess(limit, 134)
        _, prompt = writer.build_prompt(item, context.build(item), "", settings_obj)
        self.assertIn(f"حداکثرِ طولِ متنِ پیام: {limit} نویسه", prompt)


class RunTests(Base):
    def test_a_good_answer_becomes_a_proposed_version_with_the_sender_block_and_opt_out_added_by_the_system(self):
        version = self.run_writer(answer(subject="معرفیِ پوستر و ویدیو", evidence_references=[self.refs["trial"], self.refs["poster"], "F1"]))
        self.assertEqual((version.status, version.version, version.error), ("proposed", 1, ""))
        self.assertEqual(version.warnings, [])
        self.assertEqual(version.route["via"], "local")
        self.assertTrue(version.text.startswith(version.body))
        self.assertIn("ali@upmarket.ir", version.text)  # the sender block
        self.assertTrue(version.text.endswith("اگر مایل به دریافت پیام نیستید، پاسخ دهید «لغو»."))
        self.assertNotIn("ali@upmarket.ir", version.body)
        self.assertEqual([e["ref"] for e in version.evidence], [self.refs["trial"], self.refs["poster"], "F1"])
        self.assertIn("دو هفته", version.evidence[0]["text"])
        self.assertEqual(len(version.prompt_sha256), 64)
        self.assertEqual(version.personalization_reason, "نامِ شهرِ شما را دیدم و فروشگاهتان فروشگاهِ محصولِ فیزیکی است.")

    def test_the_item_is_not_changed_until_a_person_approves(self):
        before = self.item.rendered_text
        self.run_writer(answer(evidence_references=[self.refs["trial"]]))
        self.item.refresh_from_db()
        self.assertEqual(self.item.rendered_text, before)

    def test_an_invented_number_is_a_blocking_warning(self):
        version = self.run_writer(answer(message="سلام؛ ۳۰ درصد تخفیف می‌دهیم و ۵۰۰ مشتری داریم.", evidence_references=[self.refs["trial"]]))
        codes = {w["code"] for w in version.warnings}
        self.assertIn("ungrounded_number", codes)
        self.assertEqual(len([w for w in version.warnings if w["code"] == "ungrounded_number"]), 2)
        self.assertGreaterEqual(len(version.blocking_warnings), 2)
        self.assertIn("price_mentioned", codes)

    def test_a_price_is_a_blocking_warning_until_a_real_price_exists(self):
        version = self.run_writer(answer(message="سلام؛ ماهی ۹۹۰ هزار تومان.", evidence_references=[self.refs["trial"]]))
        self.assertIn("price_mentioned", {w["code"] for w in version.warnings})
        price = KnowledgeItem.objects.get(section="price")
        price.body = "ماهی ۹۹۰ هزار تومان"
        price.save()
        again = self.run_writer(answer(message="سلام؛ ماهی ۹۹۰ هزار تومان.", evidence_references=[f"K{price.pk}"]))
        self.assertEqual([w for w in again.warnings if w["blocking"]], [])

    def test_unknown_references_and_missing_evidence_are_flagged_but_not_blocking(self):
        version = self.run_writer(answer(evidence_references=["K99999", "Z1"]))
        codes = {w["code"]: w for w in version.warnings}
        self.assertIn("unknown_reference", codes)
        self.assertIn("no_evidence", codes)
        self.assertFalse(codes["no_evidence"]["blocking"])
        self.assertEqual(version.evidence, [])

    def test_absolute_claims_and_non_persian_text_are_flagged(self):
        version = self.run_writer(answer(message="ما بهترین هستیم و نتیجه را تضمین می‌کنیم.", evidence_references=[self.refs["trial"]]))
        claim = next(w for w in version.warnings if w["code"] == "absolute_claim")
        self.assertFalse(claim["blocking"])
        self.assertIn("بهترین", claim["text"])
        english = self.run_writer(answer(message="We make posters and videos for your shop automatically.", evidence_references=[self.refs["poster"]]))
        self.assertIn("not_persian", {w["code"] for w in english.warnings})

    def test_a_copy_of_the_opt_out_line_braces_and_notes_are_cleaned(self):
        opt_out = GrowthSettings.load().opt_out_line
        version = self.run_writer(answer(message=f"سلام {{business_name}} عزیز؛ پوستر می‌سازیم.\n{opt_out}", evidence_references=[self.refs["poster"]], warnings=["مطمئن نیستم"]))
        self.assertNotIn("{", version.text)
        self.assertEqual(version.text.count(opt_out), 1)
        self.assertIn("model_note", {w["code"] for w in version.warnings})

    def test_email_wants_a_subject_and_other_channels_do_not(self):
        email_tpl = MessageTemplate.objects.get(seed_key="email")
        campaign = campaigns.create_campaign(name="ا", template=email_tpl, mode=Campaign.Mode.AUTO, channel=Channel.EMAIL)
        item = campaigns.add_leads(campaign, [make_lead("w4.ir", email="a@w4.ir").pk]).added[0]
        item.refresh_from_db()
        version = self.run_writer(answer(subject="", evidence_references=[self.refs["poster"]]), item=item)
        self.assertEqual(version.subject, item.subject)  # fell back to the template's
        self.assertIn("no_subject", {w["code"] for w in version.warnings})
        with_subject = self.run_writer(answer(subject="معرفیِ پوستر و ویدیو", evidence_references=[self.refs["poster"]]), item=item)
        self.assertEqual(with_subject.subject, "معرفیِ پوستر و ویدیو")
        form = self.run_writer(answer(subject="موضوعِ اضافه", evidence_references=[]), item=campaigns.add_leads(
            campaigns.create_campaign(name="و", template=MessageTemplate.objects.get(seed_key="whatsapp"), mode=Campaign.Mode.MANUAL, channel=Channel.WHATSAPP),
            [make_lead("w5.ir", phone="09125550055").pk]).added[0])
        self.assertEqual(form.subject, "")

    def test_an_sms_that_does_not_fit_its_parts_is_blocked(self):
        sms_template = MessageTemplate.objects.get(seed_key="sms")
        campaign = campaigns.create_campaign(name="پ", template=sms_template, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        item = campaigns.add_leads(campaign, [make_lead("w6.ir", phone="09125550066").pk]).added[0]
        long = self.run_writer(answer(message="س" * 150, evidence_references=[self.refs["trial"]]), item=item)
        self.assertIn("sms_too_long", {w["code"] for w in long.warnings})
        self.assertTrue(long.blocking_warnings)
        short = self.run_writer(answer(message="سلام؛ از روی عکسِ محصول پوستر می‌سازیم.", evidence_references=[self.refs["poster"]]), item=item)
        self.assertEqual([w for w in short.warnings if w["code"] == "sms_too_long"], [])
        self.assertTrue(short.text.endswith("«لغو»."))

    def test_an_empty_or_malformed_answer_fails_in_plain_words(self):
        empty = self.run_writer(answer(message="   "))
        self.assertEqual(empty.status, "failed")
        self.assertIn("پیامی ننوشت", empty.error)

    def test_an_internal_error_is_contained(self):
        version, _ = versions.request_version(self.item, self.staff)
        with mock.patch.object(ai, "complete_json", side_effect=RuntimeError("boom")):
            writer.run(version.pk)
        version.refresh_from_db()
        self.assertEqual(version.status, "failed")
        self.assertIn("RuntimeError", version.error)
        self.assertNotIn("boom", version.error)

    def test_a_finished_version_is_left_alone_by_a_second_run(self):
        version = self.run_writer(answer(evidence_references=[self.refs["trial"]]))
        with mock.patch.object(ai, "complete_json") as fake:
            writer.run(version.pk)
        self.assertFalse(fake.called)


class NoModelAvailableTests(Base):
    """The node is off and Metis has no credit: a clear Persian message, the template text untouched, nothing broken."""

    def failing_gateway(self, message):
        class Provider:
            def generate_json(self, *a, **kw):
                raise RuntimeError(message)

        return mock.patch("services.ai.gateway.text_provider", return_value=Provider())

    def test_both_routes_down_gives_a_plain_message_with_the_way_out(self):
        reason = "هیچ‌کدام از مسیرها جواب ندادند. لوکال: سرورِ پردازش خاموش است. متیس: اعتبار تمام شده (HTTP 402)."
        with self.failing_gateway(reason), self.assertRaises(ai.AiUnavailable) as cm:
            ai.complete_json("s", "p")
        message = cm.exception.message
        self.assertIn("هوش مصنوعی الان در دسترس نیست", message)
        self.assertIn("402", message)
        self.assertIn("سرورِ پردازش خاموش است", message)
        self.assertIn("از قالب بسازید", message)

    def test_a_failed_version_keeps_the_item_and_says_why(self):
        before = (self.item.rendered_text, self.item.subject)
        version, _ = versions.request_version(self.item, self.staff)
        with self.failing_gateway("اعتبار تمام شده (۴۰۲)"):
            writer.run(version.pk)
        version.refresh_from_db()
        self.assertEqual(version.status, "failed")
        self.assertIn("۴۰۲", version.error)
        self.item.refresh_from_db()
        self.assertEqual((self.item.rendered_text, self.item.subject), before)
        self.assertEqual(self.item.status, ItemStatus.PENDING)

    def test_a_policy_block_is_reported_the_same_way(self):
        with mock.patch("services.ai.gateway.text_provider", side_effect=RuntimeError("سیاست اجازه نمی‌دهد")), self.assertRaises(ai.AiUnavailable):
            ai.complete_json("s", "p")

    def test_a_non_object_answer_is_unavailable_not_a_crash(self):
        class Provider:
            def generate_json(self, *a, **kw):
                return ["not", "an", "object"], "raw"

        with mock.patch("services.ai.gateway.text_provider", return_value=Provider()), self.assertRaises(ai.AiUnavailable):
            ai.complete_json("s", "p")

    def test_a_working_route_returns_the_parsed_answer_and_who_gave_it(self):
        class Provider:
            answered_via = "metis"

            def generate_json(self, model, prompt, **kw):
                return {"message": "m"}, '{"message":"m"}'

            def last_model(self):
                return "gpt-x"

        with mock.patch("services.ai.gateway.text_provider", return_value=Provider()):
            parsed, route = ai.complete_json("s", "p")
        self.assertEqual((parsed, route["via"], route["model"]), ({"message": "m"}, "metis", "gpt-x"))

    def test_the_gateway_is_asked_without_a_store_and_for_brand_data(self):
        class Provider:
            def generate_json(self, *a, **kw):
                return {"message": "m"}, ""

        with mock.patch("services.ai.gateway.text_provider", return_value=Provider()) as gw:
            ai.complete_json("s", "p")
        args, kwargs = gw.call_args
        self.assertIsNone(args[0])
        self.assertEqual(args[1], "BRAND")
        self.assertEqual(kwargs.get("kind"), "text")

    def test_the_status_helper_never_raises(self):
        with mock.patch("services.ai.priority.config", side_effect=RuntimeError("x")):
            self.assertFalse(ai.status()["known"])


class VersionFlowTests(Base):
    def test_approving_replaces_the_text_voids_the_send_approval_and_logs_it(self):
        self.item.status = ItemStatus.READY
        self.item.save()
        version = self.run_writer(answer(message="سلام؛ نسخهٔ تازه با دو هفته رایگان.", evidence_references=[self.refs["trial"]]))
        versions.approve(version, self.staff)
        self.item.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(self.item.rendered_text, version.text)
        self.assertTrue(self.item.text_edited)
        self.assertEqual((version.status, version.decided_by_id), ("approved", self.staff.pk))
        activity = self.lead.activities.filter(kind="updated").first()
        self.assertIn("نسخهٔ 1", activity.summary)

    def test_a_blocking_warning_needs_an_explicit_acknowledgement(self):
        version = self.run_writer(answer(message="سلام؛ ۷۷ مشتری داریم.", evidence_references=[self.refs["trial"]]))
        with self.assertRaises(Exception) as cm:
            versions.approve(version, self.staff)
        self.assertIn("با این هشدار می‌پذیرم", str(cm.exception.errors[0]["message"]))
        self.item.refresh_from_db()
        self.assertNotIn("۷۷", self.item.rendered_text)
        versions.approve(version, self.staff, acknowledge_warnings=True)
        self.item.refresh_from_db()
        self.assertIn("۷۷", self.item.rendered_text)
        self.assertTrue(self.lead.activities.filter(kind="updated").first().data["acknowledged_warnings"])

    def test_an_approved_send_approval_is_voided_by_a_new_text(self):
        from apps.growth_engine.outreach.tests.helpers import Site, ready_item

        site = Site().shop("w9.ir")
        campaign = campaigns.create_campaign(name="خودکار", template=make_template(), mode=Campaign.Mode.AUTO)
        item = ready_item(site, campaign, "w9.ir")
        approval.approve_items(campaign, item_ids=[item.pk], actor=self.staff)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.APPROVED)
        version = self.run_writer(answer(message="سلام؛ پوستر می‌سازیم.", evidence_references=[self.refs["poster"]]), item=item)
        versions.approve(version, self.staff)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.READY)
        self.assertIsNone(item.approved_record)

    def test_only_a_proposed_version_can_be_approved_and_a_second_approval_supersedes_the_first(self):
        first = self.run_writer(answer(message="سلام؛ یک.", evidence_references=[self.refs["poster"]]))
        versions.approve(first, self.staff)
        second = self.run_writer(answer(message="سلام؛ دو.", evidence_references=[self.refs["poster"]]))
        versions.approve(second, self.staff)
        first.refresh_from_db()
        self.assertEqual(first.status, "superseded")
        with self.assertRaises(Exception):
            versions.approve(first, self.staff)

    def test_reject_keeps_the_version_and_the_item_text(self):
        version = self.run_writer(answer(evidence_references=[self.refs["trial"]]))
        before = self.item.rendered_text
        versions.reject(version, self.staff)
        version.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(version.status, "rejected")
        self.assertEqual(self.item.rendered_text, before)

    def test_versions_are_numbered_per_item_and_one_runs_at_a_time(self):
        first, created = versions.request_version(self.item, self.staff)
        again, created_again = versions.request_version(self.item, self.staff)
        self.assertEqual((created, created_again, again.pk), (True, False, first.pk))
        GeneratedMessage.objects.filter(pk=first.pk).update(status="proposed")
        second, created = versions.request_version(self.item, self.staff)
        self.assertEqual((second.version, created), (2, True))

    def test_a_version_stuck_writing_is_given_up_after_ten_minutes(self):
        old, _ = versions.request_version(self.item, self.staff)
        GeneratedMessage.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=11))
        fresh, created = versions.request_version(self.item, self.staff)
        old.refresh_from_db()
        self.assertTrue(created)
        self.assertEqual(old.status, "failed")
        self.assertIn("طول کشید", old.error)

    def test_a_finished_item_or_a_closed_campaign_cannot_be_written(self):
        OutreachItem.objects.filter(pk=self.item.pk).update(status=ItemStatus.SENT)
        self.item.refresh_from_db()
        with self.assertRaises(Exception):
            versions.request_version(self.item, self.staff)
        OutreachItem.objects.filter(pk=self.item.pk).update(status=ItemStatus.PENDING)
        Campaign.objects.filter(pk=self.campaign.pk).update(status=Campaign.Status.CANCELLED)
        self.item.refresh_from_db()
        with self.assertRaises(Exception):
            versions.request_version(self.item, self.staff)

    def test_compare_marks_inserted_and_removed_words(self):
        ops = versions.compare("سلام دوست من", "سلام دوست عزیز")
        self.assertEqual([o["op"] for o in ops], ["equal", "delete", "insert"])
        self.assertEqual((ops[1]["a"], ops[2]["b"]), ("من", "عزیز"))
        self.assertEqual("".join(o["a"] or o["b"] for o in versions.compare("a b", "a b")), "a b")


class ApiTests(Base):
    def base(self):
        return f"{G}/outreach/campaigns/{self.campaign.pk}/items/{self.item.pk}"

    def write(self, payload, **body):
        with mock.patch.object(ai, "complete_json", return_value=(payload, ROUTE)), self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"{self.base()}/ai/", body, format="json")

    def test_ask_poll_compare_approve(self):
        response = self.write(answer(message="سلام؛ پوستر و ویدیو می‌سازیم. دو هفته رایگان.", evidence_references=[self.refs["trial"]]), instructions="کوتاه")
        self.assertEqual(response.status_code, 202, response.content)
        listing = self.client.get(f"{self.base()}/versions/").json()
        self.assertEqual(len(listing["versions"]), 1)
        version = listing["versions"][0]
        self.assertEqual((version["status"], version["version"], version["instructions"]), ("proposed", 1, "کوتاه"))
        self.assertEqual(version["route"]["via"], "local")
        compare = self.client.get(f"{self.base()}/versions/compare/?a=current&b={version['id']}").json()
        self.assertEqual(compare["a"]["label"], "متنِ فعلیِ پیام")
        self.assertEqual(compare["b"]["label"], "نسخهٔ 1")
        self.assertTrue(any(op["op"] != "equal" for op in compare["ops"]))
        approved = self.client.post(f"{self.base()}/versions/{version['id']}/approve/", {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(approved.json()["item"]["rendered_text"], version["text"])
        self.assertEqual(self.client.get(f"{self.base()}/versions/").json()["versions"][0]["same_as_current"], True)

    def test_a_failed_write_is_visible_to_the_poll(self):
        with mock.patch.object(ai, "complete_json", side_effect=ai.AiUnavailable("هوش مصنوعی الان در دسترس نیست. اعتبار تمام شده (۴۰۲).")), self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"{self.base()}/ai/", {}, format="json")
        version = self.client.get(f"{self.base()}/versions/").json()["versions"][0]
        self.assertEqual(version["status"], "failed")
        self.assertIn("۴۰۲", version["error"])

    def test_reject_and_the_acknowledge_flag(self):
        self.write(answer(message="سلام؛ ۹۱ مشتری.", evidence_references=[self.refs["trial"]]))
        version = self.client.get(f"{self.base()}/versions/").json()["versions"][0]
        refused = self.client.post(f"{self.base()}/versions/{version['id']}/approve/", {}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("با این هشدار می‌پذیرم", refused.json()["detail"])
        ok = self.client.post(f"{self.base()}/versions/{version['id']}/approve/", {"acknowledge_warnings": True}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.write(answer(message="سلام؛ دیگری.", evidence_references=[self.refs["poster"]]))
        newest = self.client.get(f"{self.base()}/versions/").json()["versions"][0]
        self.assertEqual(self.client.post(f"{self.base()}/versions/{newest['id']}/reject/").json()["status"], "rejected")

    def test_a_second_request_while_one_is_writing_returns_the_same(self):
        version, _ = versions.request_version(self.item, self.staff)
        response = self.client.post(f"{self.base()}/ai/", {}, format="json")
        self.assertEqual((response.status_code, response.json()["created"], response.json()["id"]), (202, False, version.pk))

    def test_bulk_write(self):
        second = campaigns.add_leads(self.campaign, [make_lead("w7.ir").pk]).added[0]
        OutreachItem.objects.filter(pk=second.pk).update(status=ItemStatus.SENT)
        with mock.patch.object(ai, "complete_json", return_value=(answer(evidence_references=[self.refs["trial"]]), ROUTE)), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"{G}/outreach/campaigns/{self.campaign.pk}/ai-write/", {"item_ids": [self.item.pk, second.pk, 999999]}, format="json")
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual([s["item_id"] for s in response.json()["started"]], [self.item.pk])
        self.assertEqual([r["item_id"] for r in response.json()["refused"]], [second.pk])
        self.assertEqual(self.client.post(f"{G}/outreach/campaigns/{self.campaign.pk}/ai-write/", {"item_ids": list(range(1, 40))}, format="json").status_code, 400)

    def test_instructions_are_limited_and_the_item_must_belong_to_the_campaign(self):
        self.assertEqual(self.client.post(f"{self.base()}/ai/", {"instructions": "x" * 2001}, format="json").status_code, 400)
        other = campaigns.create_campaign(name="دیگر", template=self.template, mode=Campaign.Mode.AUTO)
        self.assertEqual(self.client.post(f"{G}/outreach/campaigns/{other.pk}/items/{self.item.pk}/ai/", {}, format="json").status_code, 404)

    def test_compare_input_is_checked(self):
        self.assertEqual(self.client.get(f"{self.base()}/versions/compare/?a=abc&b=current").status_code, 400)
        self.assertEqual(self.client.get(f"{self.base()}/versions/compare/?a=99999&b=current").status_code, 404)

    def test_writer_status_endpoint_and_staff_only(self):
        with mock.patch.object(ai, "status", return_value={"known": True, "order": ["local", "metis"], "first": "local", "local": {"ready": False, "reason": "خاموش"}, "model": "gemma3:12b"}):
            self.assertEqual(self.client.get(f"{G}/knowledge/writer-status/").json()["first"], "local")
        self.assertEqual(client_for().post(f"{self.base()}/ai/", {}, format="json").status_code, 401)
        plain = client_for(make_plain_user("ge-plain-ai"))
        self.assertEqual(plain.post(f"{self.base()}/ai/", {}, format="json").status_code, 403)
        self.assertEqual(plain.get(f"{self.base()}/versions/").status_code, 403)

    def test_the_templates_work_without_any_ai(self):
        # the whole path (prepare, edit by hand, approve) never touches the writer
        configure()
        with mock.patch.object(ai, "complete_json", side_effect=AssertionError("the AI must not be called")):
            built = items.rerender_item(self.item, self.staff)
        self.assertTrue(built.rendered_text)
