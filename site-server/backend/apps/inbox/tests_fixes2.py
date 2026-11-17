"""The third round: what the second review of the live inbox found, each with the test that would have caught it.

A survey answer that swallowed a real message («3 نفر هستیم…»), «آدم می‌خواهم» keywords that matched
pieces of ordinary words, a «waiting» number that disagreed with itself, a widget snippet that cannot
work on an https site, webhook URLs readable by a viewer, a mention printed backwards, response time
credited to the wrong person, «دوست عزیز عزیز», a Telegram guide that sent people to a dead end, a
rate limit that every worker counted separately, a list that stopped at 80, a broadcast that gave up on
a person with a working second channel, skills that only matched tags, and a Rubika error that blamed
the token for a bad chat id.
"""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import Client, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.customers.models import Conversation, Customer, Message

from . import (
    bot, broadcast as bc, dispatch, ingest, norm, publicurl, replies, shared, surveys, team, views_channels,
    views_widget,
)
from .adapters import rubika
from .adapters.base import Incoming
from .fakes import FakePlatform
from .models import (
    Broadcast, BroadcastRecipient, Contact, ContactLink, ConversationMeta, InboxSettings, SatisfactionSurvey,
)
from .tests_adapters import Conn
from .tests_base import InboxTestCase


# --------------------------------------------------------------- 1. the survey


class SurveyAnswerShapeTests(InboxTestCase):
    """A digit is only a rating when it *looks* like one."""

    def test_what_is_a_rating_and_what_is_a_sentence(self):
        rating = {
            "5": (5, ""), "۵": (5, ""), "4.": (4, ""), "۳/۵": (3, ""), "۴ از ۵": (4, ""), "5 ستاره": (5, ""),
            "⭐ 5": (5, ""), "4 ممنون": (4, "ممنون"), "۵ - عالی بود": (5, "عالی بود"),
            "2، خیلی دیر جواب دادید": (2, "خیلی دیر جواب دادید"),
        }
        for text, expected in rating.items():
            self.assertEqual(surveys.parse_answer(text), expected, text)
        sentences = [
            "3 نفر هستیم و می‌خوام برای هر سه نفر ثبت‌نام کنم، چطوری؟",
            "۳ نفر هستیم",
            "2 ساعت دیگه می‌رسم",
            "5 تا می‌خوام",
            "1 سؤال دارم؟",
            "4 ماهه که عضو شدم و هنوز برنامه نگرفتم، مشکل از کجاست و چه کار کنم برای اینکه زودتر بگیرم",
            "۲ میلیون تومان شد؟",
            "سلام 5",
            "",
            "6",
            "55",
        ]
        for text in sentences:
            self.assertIsNone(surveys.parse_answer(text), text)


class SurveyDoesNotEatMessagesTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        cfg = team.settings_for(self.store)
        cfg.survey_enabled = True
        cfg.survey_delay_min = 0
        cfg.save()
        self.conn = self.connect("TELEGRAM")  # the one platform whose sender the test base fakes
        self._n = 0

    def incoming(self, text):
        self._n += 1
        return Incoming(external_id=f"s{self._n}", thread_id="700", sender_id="700", name="سارا", text=text)

    def surveyed(self):
        out = ingest.receive(self.conn, self.incoming("سلام، سؤال دارم"))
        conversation = out.conversation
        replies.reply(conversation, self.sara, "بفرمایید")
        replies.close(conversation, self.sara)
        from . import followups

        followups.run_due()
        self.assertEqual(SatisfactionSurvey.objects.filter(conversation=conversation).count(), 1)
        replies.mark_read(conversation)
        return conversation

    def test_a_booking_message_that_starts_with_a_digit_is_a_message(self):
        conversation = self.surveyed()
        out = ingest.receive(self.conn, self.incoming("3 نفر هستیم و می‌خوام برای هر سه نفر ثبت‌نام کنم، چطوری؟"))
        self.assertEqual(out.handled, "")
        conversation.refresh_from_db()
        self.assertNotEqual(conversation.state, Conversation.State.RESOLVED)  # the team is told: it is open again
        meta = ConversationMeta.objects.get(conversation=conversation)
        self.assertEqual((meta.unread_count, meta.reopened_count), (1, 1))
        survey = SatisfactionSurvey.objects.get(conversation=conversation)
        self.assertIsNone(survey.score)  # no false 3-star rating
        self.assertEqual(surveys.summary(self.store)["answered"], 0)
        self.assertFalse(conversation.messages.filter(text__contains="ممنون از صراحتتان").exists())

    def test_once_the_thread_is_open_again_a_digit_belongs_to_it(self):
        conversation = self.surveyed()
        ingest.receive(self.conn, self.incoming("یک سؤال دیگر دارم"))
        conversation.refresh_from_db()
        self.assertNotEqual(conversation.state, Conversation.State.RESOLVED)
        out = ingest.receive(self.conn, self.incoming("۵"))
        self.assertEqual(out.handled, "")  # «۵» is now the answer to a question in this conversation
        self.assertIsNone(SatisfactionSurvey.objects.get(conversation=conversation).score)

    def test_a_short_remark_after_the_digit_is_still_the_rating(self):
        conversation = self.surveyed()
        out = ingest.receive(self.conn, self.incoming("۴ ممنون"))
        self.assertEqual(out.handled, "survey")
        survey = SatisfactionSurvey.objects.get(conversation=conversation)
        self.assertEqual((survey.score, survey.comment), (4, "ممنون"))
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.RESOLVED)


# ------------------------------------------------------------ 2. «آدم می‌خواهم»


class HandoffKeywordTests(InboxTestCase):
    def cfg(self, keywords=None):
        cfg = team.settings_for(self.store)
        cfg.bot_handoff_keywords = keywords or []
        cfg.save()
        return cfg

    def test_ordinary_chagher_questions_are_not_a_request_for_a_person(self):
        cfg = self.cfg()
        for text in (
            "آیا چغر برای مدیریت ورزشکارانم مناسب است؟",
            "مسئولیت برنامه با کیه؟",
            "برنامه‌ی غذایی آدم‌های دیابتی هم می‌سازه؟",
            "درباره صحبت با ورزشکار چه امکاناتی هست؟",
            "the human body plan",
            "پشتیبانی چغر چه ساعتی است؟",
            "مدیر باشگاه می‌تواند گزارش ببیند؟",
            "انسان‌ها چطور تغذیه کنند؟",
            "برنامه تمرینی برای مربی‌ها دارید؟",
        ):
            self.assertEqual(bot.wants_human(cfg, text), "", text)

    def test_real_requests_still_hand_off(self):
        cfg = self.cfg()
        for text in (
            "اپراتور لطفاً",
            "می‌خوام با پشتیبان صحبت کنم",
            "با یه نفر صحبت کنم",
            "ربات نه، آدم واقعی",
            "با پشتیبانی تماس می‌گیرم",
            "I want a real person",
            "operator please",
            "اپراتورها کی جواب میدن؟",
        ):
            self.assertNotEqual(bot.wants_human(cfg, text), "", text)

    def test_the_owners_own_words_are_whole_words_too(self):
        cfg = self.cfg(["مربی"])
        self.assertEqual(bot.wants_human(cfg, "مربی می‌خوام"), "مربی")
        self.assertEqual(bot.wants_human(cfg, "برنامه مربیگری دارید؟"), "")
        self.assertEqual(bot.wants_human(cfg, "برنامه برای مربی‌ها دارید؟"), "مربی")  # a plural is still the word

    def test_the_default_list_has_no_generic_words(self):
        for word in ("مدیر", "آدم", "مسئول", "صحبت با", "human", "agent"):
            self.assertNotIn(word, bot.DEFAULT_KEYWORDS)

    def test_the_widget_question_stays_with_the_bot(self):
        conversation = self.conversation(channel="WEBCHAT", sender="v1", name="بازدیدکننده")
        self.customer_says(conversation, "آیا چغر برای مدیریت ورزشکارانم مناسب است؟")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.AI)


# ------------------------------------------------- 3. one «waiting» everywhere


class WaitingNumbersAgreeTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        self.online(self.sara)

    def asks(self, sender, text="اپراتور"):
        conversation = self.conversation(sender=sender, name=f"مشتری {sender}")
        self.customer_says(conversation, text)
        conversation.refresh_from_db()
        return conversation

    def numbers(self):
        api = self.api(self.sara)
        inbox = api.get(self.url("v2/")).json()
        waiting = api.get(self.url("v2/?state=waiting")).json()["conversations"]
        nobody = api.get(self.url("v2/?assigned=nobody&state=waiting")).json()["conversations"]
        stats = api.get(self.url("stats/")).json()
        page = api.get(self.url("team/")).json()
        return inbox["counts"], waiting, nobody, stats, page

    def test_an_answered_thread_leaves_the_waiting_tab(self):
        waiting_one = self.asks("a")
        answered = self.asks("b")
        replies.reply(answered, self.sara, "بفرمایید")
        counts, waiting, _nobody, stats, _page = self.numbers()
        ids = {row["id"] for row in waiting}
        self.assertIn(waiting_one.pk, ids)
        self.assertNotIn(answered.pk, ids)
        self.assertEqual(counts["waiting"], len(waiting))
        self.assertEqual(counts["waiting"], stats["waiting_for_person"])
        # ...and the customer writing again puts it back
        self.customer_says(answered, "ممنون، یک سؤال دیگر")
        counts, waiting, *_ = self.numbers()
        self.assertIn(answered.pk, {row["id"] for row in waiting})
        self.assertEqual(counts["waiting"], len(waiting))

    def test_the_pill_the_tile_and_the_stats_are_one_number(self):
        for i in range(3):
            self.asks(f"w{i}")
        failed = self.conversation(sender="f1")
        Conversation.objects.filter(pk=failed.pk).update(ai_failed_at=timezone.now())
        done = self.asks("done")
        replies.reply(done, self.sara, "حل شد")
        replies.close(done, self.sara)
        counts, waiting, nobody, stats, page = self.numbers()
        self.assertEqual(counts["waiting"], len(waiting))
        self.assertEqual(counts["waiting"], stats["waiting_for_person"])
        self.assertEqual(counts["unassigned"], len(nobody))
        self.assertEqual(counts["unassigned"], stats["unassigned"])
        self.assertEqual(counts["unassigned"], page["unassigned_open"])

    def test_the_mine_pill_and_the_list_it_opens_agree(self):
        mine_open = self.asks("m1")
        mine_closed = self.asks("m2")
        for conversation in (mine_open, mine_closed):
            conversation.assigned_to = self.sara
            conversation.save()
        replies.close(mine_closed, self.sara)
        api = self.api(self.sara)
        counts = api.get(self.url("v2/")).json()["counts"]
        listed = api.get(self.url("v2/?assigned=me")).json()["conversations"]
        self.assertEqual(counts["mine"], len(listed))
        self.assertEqual({row["id"] for row in listed}, {mine_open.pk})
        # the closed ones are one explicit filter away
        closed = api.get(self.url("v2/?assigned=me&state=RESOLVED")).json()["conversations"]
        self.assertEqual({row["id"] for row in closed}, {mine_closed.pk})


# --------------------------------------------------- 4. the address we hand out


class PublicAddressTests(InboxTestCase):
    def channels(self, user=None):
        return self.api(user or self.admin).get(self.url("channels/")).json()

    def test_nothing_chosen_uses_the_address_the_panel_was_opened_on(self):
        data = self.channels()
        row = {c["kind"]: c for c in data["channels"]}["WEBCHAT"]
        self.assertTrue(row["snippet"].startswith('<script src="http://testserver/api/v1/widget/'))
        self.assertEqual(data["public"]["source"], "request")
        self.assertFalse(data["public"]["secure"])
        self.assertTrue(data["public"]["warning"])  # never silent about it

    def test_an_https_address_builds_the_snippet_and_the_webhooks(self):
        saved = self.api(self.admin).patch(self.url("settings/"), {"public_base_url": "Chat.Example.ir/"}, format="json")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["public_base_url"], "https://chat.example.ir")
        data = self.channels()
        rows = {c["kind"]: c for c in data["channels"]}
        self.assertEqual(data["public"], {
            "url": "https://chat.example.ir", "source": "setting", "secure": True, "warning": "",
            "configured": "https://chat.example.ir",
        })
        self.assertTrue(rows["WEBCHAT"]["snippet"].startswith('<script src="https://chat.example.ir/api/v1/widget/'))
        self.assertTrue(rows["BALE"]["hook_url"].startswith("https://chat.example.ir/api/v1/inbox/hook/bale/"))
        self.assertTrue(rows["TELEGRAM"]["hook_url"].startswith("https://chat.example.ir/api/v1/webhooks/telegram/"))
        docs = self.api(self.admin).get(self.url("dev/docs/")).json()
        self.assertEqual(docs["base"], "https://chat.example.ir/api/v1/inbox-api/")

    def test_a_plain_http_address_on_a_real_host_says_what_will_break(self):
        self.api(self.admin).patch(self.url("settings/"), {"public_base_url": "http://203.0.113.5:8040"}, format="json")
        data = self.channels()
        self.assertFalse(data["public"]["secure"])
        self.assertIn("https", data["public"]["warning"])
        self.assertIn("ویجت", data["public"]["warning"])

    def test_bad_addresses_are_refused_with_a_persian_reason(self):
        for bad in ("ftp://chat.example.ir", "https://chat.example.ir/panel", "https://user:pw@chat.example.ir", "https://", "a b"):
            response = self.api(self.admin).patch(self.url("settings/"), {"public_base_url": bad}, format="json")
            self.assertEqual(response.status_code, 400, bad)
            message = response.json()["error"]["message"]
            self.assertTrue("نشانی" in message or "دامنه" in message, (bad, message))
            self.assertFalse(message.isascii())
        self.assertEqual(team.settings_for(self.store).public_base_url, "")

    def test_only_someone_who_may_change_settings_can_set_it(self):
        response = self.api(self.sara).patch(self.url("settings/"), {"public_base_url": "https://x.example.ir"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_clean_and_resolve_rules(self):
        self.assertEqual(publicurl.clean(""), "")
        self.assertEqual(publicurl.clean("https://A.example.ir:8443/"), "https://a.example.ir:8443")
        self.assertTrue(publicurl.is_secure("https://a.example.ir"))
        self.assertFalse(publicurl.is_secure("https://localhost"))
        self.assertFalse(publicurl.is_secure("http://a.example.ir"))
        self.assertEqual(publicurl.warning_for("https://a.example.ir"), "")
        self.assertTrue(publicurl.warning_for("http://127.0.0.1:8000"))
        request = RequestFactory().get("/", HTTP_HOST="panel.example.ir")
        with override_settings(UPMARKET_PUBLISHING={"PUBLIC_BASE_URL": "https://site.example.ir"}):
            self.assertEqual(publicurl.resolve(request, self.store)["source"], "site")
            self.assertEqual(publicurl.resolve(request, self.store)["url"], "https://site.example.ir")
        with override_settings(UPMARKET_PUBLISHING={"PUBLIC_BASE_URL": "http://localhost:8000"}):
            self.assertEqual(publicurl.resolve(request, self.store)["source"], "request")  # a dev default is not an address
        # the panel is open over https on a real host: that beats an http address left in the .env
        secure = RequestFactory().get("/", secure=True, HTTP_HOST="panel.example.ir")
        with override_settings(UPMARKET_PUBLISHING={"PUBLIC_BASE_URL": "http://203.0.113.5:8040"}):
            found = publicurl.resolve(secure, self.store)
            self.assertEqual((found["url"], found["source"], found["secure"]), ("https://panel.example.ir", "request", True))
            self.assertEqual(publicurl.resolve(request, self.store)["url"], "http://203.0.113.5:8040")  # opened over http: the .env wins

    def test_a_webhook_is_only_registered_automatically_over_https(self):
        request = RequestFactory().get("/", HTTP_HOST="panel.example.ir")
        self.assertFalse(views_channels._public_url(request, self.store))
        cfg = team.settings_for(self.store)
        cfg.public_base_url = "https://chat.example.ir"
        cfg.save()
        self.assertTrue(views_channels._public_url(request, self.store))

    def test_the_guide_tells_the_owner_about_https(self):
        rows = {c["kind"]: c for c in self.channels()["channels"]}
        self.assertTrue(any("https" in step for step in rows["WEBCHAT"]["steps"]))
        self.assertTrue(any("https" in step for step in rows["BALE"]["steps"]))


# ---------------------------------------------- 5. keys are for people who manage


class ChannelSecretsTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        self.connect("WEBCHAT", token="", config={})
        self.connect("WHATSAPP", token="T" * 30, enabled=False, config={
            "phone_number_id": "555", "app_secret": "appsec", "verify_token": "shared-verify-secret"})
        self.connect("BALE")

    def rows(self, user):
        response = self.api(user).get(self.url("channels/"))
        self.assertEqual(response.status_code, 200)
        return {c["kind"]: c for c in response.json()["channels"]}, response.json()

    def test_a_support_agent_and_a_viewer_see_the_state_not_the_keys(self):
        for user in (self.sara, self.viewer):
            rows, data = self.rows(user)
            for kind, row in rows.items():
                self.assertEqual(row["hook_url"], "", (user.username, kind))
                self.assertEqual(row["masked_token"], "", (user.username, kind))
                self.assertNotIn("snippet", row)
                self.assertNotIn("widget_key", row)
                self.assertFalse(row["can_see_keys"])
            self.assertNotIn("shared-verify-secret", json.dumps(data, ensure_ascii=False))
            self.assertNotIn(self.connect("WEBCHAT", token="", config={}).secret, json.dumps(data))
            self.assertEqual(data["public"]["configured"], "")
            self.assertFalse(data["can_manage"])
            self.assertEqual(rows["BALE"]["enabled"], True)  # the state itself is still there
            self.assertTrue(rows["BALE"]["has_token"])

    def test_the_owner_and_an_admin_get_everything(self):
        for user in (self.owner, self.admin):
            rows, data = self.rows(user)
            self.assertIn("/api/v1/inbox/hook/bale/", rows["BALE"]["hook_url"])
            self.assertIn("<script", rows["WEBCHAT"]["snippet"])
            self.assertTrue(rows["WEBCHAT"]["widget_key"])
            self.assertEqual(rows["WHATSAPP"]["config"]["verify_token"], "shared-verify-secret")
            self.assertNotIn("app_secret", rows["WHATSAPP"]["config"])
            self.assertTrue(rows["BALE"]["masked_token"].startswith("••••"))
            self.assertTrue(data["can_manage"])


# ------------------------------------------------------- 6. Telegram, honestly


class TelegramReachabilityTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def telegram(self):
        rows = {c["kind"]: c for c in self.api(self.admin).get(self.url("channels/")).json()["channels"]}
        return rows["TELEGRAM"]

    def test_a_server_that_cannot_reach_telegram_says_so_on_the_card(self):
        row = self.telegram()  # INBOX_API_BASES points Telegram at a closed port
        self.assertFalse(row["network"]["reachable"])
        self.assertIn("دسترسی ندارد", row["network"]["message"])
        self.assertIn("بله، ایتا یا روبیکا", row["network"]["message"])

    def test_it_turns_green_by_itself_when_the_server_can_reach_it(self):
        with FakePlatform({"": {"ok": True}}) as fake, override_settings(INBOX_API_BASES={"TELEGRAM": fake.url}):
            row = self.telegram()
        self.assertTrue(row["network"]["reachable"])
        self.assertEqual(row["network"]["message"], "")

    def test_only_blocked_platforms_are_probed(self):
        self.assertIsNone(dispatch.reachability("BALE"))
        self.assertIsNone(dispatch.reachability("SMS"))
        rows = {c["kind"]: c for c in self.api(self.admin).get(self.url("channels/")).json()["channels"]}
        self.assertNotIn("network", rows["BALE"])

    def test_the_error_names_the_real_cause_instead_of_a_bare_unreachable(self):
        connection = self.connect("TELEGRAM", token="111:TESTTOKENTESTTOKENTESTTOKEN")
        result = dispatch.check_health(connection)
        self.assertFalse(result["ok"])
        self.assertIn("در دسترس نبود", result["detail"])
        self.assertIn("بله، ایتا یا روبیکا", result["detail"])
        self.assertNotIn("TESTTOKEN", result["detail"])

    def test_the_guide_no_longer_promises_polling_fixes_it(self):
        from . import guides

        text = " ".join(guides.GUIDES["TELEGRAM"]["steps"]) + guides.GUIDES["TELEGRAM"]["limits"]
        self.assertNotIn("حالت «پرسش دوره‌ای» را انتخاب کنید", text)
        self.assertIn("بله، ایتا یا روبیکا", text)


# ---------------------------------------------- 7. limits every worker shares


class FakeRedis:
    """The few Redis calls `shared` makes, kept in one dict - what every worker would share."""

    def __init__(self):
        self.data: dict[str, int | str] = {}

    def pipeline(self):
        outer = self

        class Pipe:
            def __init__(self):
                self.key = ""

            def incr(self, key):
                self.key = key
                outer.data[key] = int(outer.data.get(key, 0)) + 1

            def expire(self, key, ttl):
                pass

            def execute(self):
                return [outer.data[self.key], True]

        return Pipe()

    def get(self, key):
        value = self.data.get(key)
        return None if value is None else str(value).encode()

    def set(self, key, value, ex=None):
        self.data[key] = value


class SharedLimitTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        shared._client = None
        shared._failed_at = 0.0

    def test_the_count_survives_a_worker_that_forgot_everything(self):
        redis = FakeRedis()
        with patch.object(shared, "_redis", return_value=redis):
            results = []
            for _ in range(5):
                results.append(views_widget._limited("t", 3, 3600))
                cache.clear()  # the next request is served by another process with an empty local cache
        self.assertEqual(results, [False, False, False, True, True])

    def test_without_redis_it_still_counts_in_the_local_cache(self):
        with patch.object(shared, "_redis", return_value=None):
            results = [views_widget._limited("t2", 2, 3600) for _ in range(4)]
        self.assertEqual(results, [False, False, True, True])

    def test_a_broken_redis_never_takes_the_widget_down(self):
        class Broken(FakeRedis):
            def pipeline(self):
                raise ConnectionError("redis is down")

        with patch.object(shared, "_redis", return_value=Broken()):
            self.assertFalse(views_widget._limited("t3", 5, 3600))
            self.assertEqual(shared.hit("widget:t3", 3600), 2)  # counted locally instead

    def test_new_chats_per_address_are_the_same_limit_in_every_worker(self):
        connection = self.connect("WEBCHAT", token="", config={})
        http = Client()
        base = f"/api/v1/widget/{connection.secret}"
        codes = []
        with patch.object(shared, "_redis", return_value=FakeRedis()), \
                patch("apps.customers.views_webhook._respond_later"):
            for i in range(views_widget.NEW_CHATS_PER_HOUR_IP + 4):
                cache.clear()  # «another worker»
                token = http.post(f"{base}/session/", data="{}", content_type="application/json").json()["token"]
                cache.clear()
                codes.append(http.post(
                    f"{base}/send/", data=json.dumps({"token": token, "text": f"پیام {i}"}), content_type="application/json",
                ).status_code)
        self.assertEqual(codes.count(200), views_widget.NEW_CHATS_PER_HOUR_IP)  # not 2x
        self.assertEqual(codes.count(429), 4)

    def test_flags_round_trip(self):
        redis = FakeRedis()
        with patch.object(shared, "_redis", return_value=redis):
            shared.set_flag("x", '{"a": 1}', 60)
            self.assertEqual(shared.get_flag("x"), '{"a": 1}')
        shared.set_flag("y", "1", 60)
        self.assertEqual(shared.get_flag("y"), "1")


# ---------------------------------------------------- 8. a list that has an end


class InboxListPagingTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        for i in range(30):
            conversation = self.conversation(sender=f"p{i}", name=f"مشتری {i}")
            self.customer_says(conversation, f"سلام {i}")

    def get(self, query=""):
        return self.api(self.sara).get(self.url("v2/" + query)).json()

    def test_pages_walk_through_every_conversation_once(self):
        seen = []
        offset = 0
        while True:
            data = self.get(f"?limit=7&offset={offset}")
            seen += [row["id"] for row in data["conversations"]]
            self.assertEqual(data["total"], 30)
            if not data["has_more"]:
                break
            offset += 7
        self.assertEqual(len(seen), 30)
        self.assertEqual(len(set(seen)), 30)
        self.assertEqual(self.get("?limit=7&offset=28")["conversations"].__len__(), 2)

    def test_the_default_page_has_a_more_button_when_there_is_more(self):
        for i in range(30, 60):
            self.customer_says(self.conversation(sender=f"p{i}"), "سلام")
        data = self.get()
        self.assertEqual(len(data["conversations"]), data["limit"])
        self.assertTrue(data["has_more"])
        everything = self.get("?limit=500")
        self.assertEqual((len(everything["conversations"]), everything["has_more"]), (60, False))

    def test_bad_numbers_are_the_defaults_and_the_page_is_capped(self):
        self.assertEqual(self.get("?limit=abc&offset=-5")["offset"], 0)
        self.assertLessEqual(self.get("?limit=100000")["limit"], 500)

    def test_the_cost_does_not_grow_with_the_rows(self):
        with CaptureQueriesContext(connection) as small:
            self.get("?limit=3")
        with CaptureQueriesContext(connection) as large:
            self.get("?limit=30")
        self.assertLess(len(large), 40)
        self.assertLessEqual(len(large) - len(small), 3)  # not ~3 queries per row as before

    def test_the_rows_keep_their_last_message(self):
        data = self.get("?limit=30")
        texts = {row["last_message"]["text"] for row in data["conversations"]}
        self.assertEqual(texts, {f"سلام {i}" for i in range(30)})


# ------------------------------------------ 9. a person is not lost with a channel


class BroadcastFallbackTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        self.connect("TELEGRAM", token="111:TESTTOKENTESTTOKENTESTTOKEN")
        self.connect("BALE")
        self.contact = Contact.objects.create(store=self.store, name="مریم", phone="09120000001")
        for channel, external in (("telegram", "T1"), ("bale", "B1")):
            customer = Customer.objects.create(store=self.store, name="مریم", channel=channel, external_id=external)
            ContactLink.objects.create(contact=self.contact, customer=customer, matched_by="new")

    def approved(self, **kw) -> Broadcast:
        broadcast = Broadcast.objects.create(
            store=self.store, name="پیشنهاد", text="سلام {name}!", created_by=self.sara,
            channels=["TELEGRAM", "BALE"], **kw,
        )
        bc.submit(broadcast, self.sara)
        bc.approve(broadcast, self.admin)
        return broadcast

    def tick(self):
        with FakePlatform({"sendMessage": {"ok": True, "result": {"message_id": 7}}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}), \
                patch("services.publishing.channels._send_telegram",
                      return_value={"sent": False, "reason": "تلگرام در دسترس نبود"}):
            return bc.send_tick(), fake

    def test_a_person_whose_first_channel_fails_gets_the_next_one(self):
        broadcast = self.approved()
        rows = list(broadcast.recipients.all())
        self.assertEqual([r.channel for r in rows], ["TELEGRAM"])  # one channel per person
        first, _ = self.tick()
        self.assertEqual(first["sent"], 0)
        telegram = BroadcastRecipient.objects.get(broadcast=broadcast, channel="TELEGRAM")
        self.assertEqual((telegram.status, telegram.skip_reason), ("SKIPPED", "fallback"))
        self.assertIn("در دسترس نبود", telegram.error)  # the reason is kept
        bale = BroadcastRecipient.objects.get(broadcast=broadcast, channel="BALE")
        self.assertEqual(bale.status, "QUEUED")
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, Broadcast.Status.SENDING)  # not finished: the Bale message is still due
        second, fake = self.tick()
        self.assertEqual(second["sent"], 1)
        self.assertEqual(len(fake.requests), 1)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, Broadcast.Status.SENT)
        self.assertEqual((broadcast.stats["sent"], broadcast.stats["failed"], broadcast.stats["fallback"]), (1, 0, 1))

    def test_a_person_with_only_the_failing_channel_is_failed_not_looped(self):
        BroadcastRecipient.objects.all().delete()
        ContactLink.objects.filter(customer__channel="bale").delete()
        Customer.objects.filter(channel="bale").delete()
        broadcast = self.approved()
        self.tick()
        row = BroadcastRecipient.objects.get(broadcast=broadcast)
        self.assertEqual(row.status, "FAILED")
        self.assertEqual(BroadcastRecipient.objects.filter(broadcast=broadcast).count(), 1)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, Broadcast.Status.SENT)

    def test_it_never_leaves_what_the_owner_approved(self):
        broadcast = Broadcast.objects.create(
            store=self.store, name="فقط تلگرام", text="سلام", created_by=self.sara, channels=["TELEGRAM"],
        )
        bc.submit(broadcast, self.sara)
        bc.approve(broadcast, self.admin)
        self.tick()
        self.assertFalse(BroadcastRecipient.objects.filter(broadcast=broadcast, channel="BALE").exists())

    def test_an_opt_out_on_the_next_channel_is_respected(self):
        self.contact.opt_out = {"BALE": True}
        self.contact.save()
        broadcast = self.approved()
        self.tick()
        self.assertFalse(BroadcastRecipient.objects.filter(broadcast=broadcast, channel="BALE").exists())
        self.assertEqual(BroadcastRecipient.objects.get(broadcast=broadcast).status, "FAILED")

    def test_when_the_person_gets_every_channel_a_failed_one_is_just_failed(self):
        broadcast = self.approved(dedupe=False)
        self.assertEqual(broadcast.recipients.count(), 2)
        self.tick()
        self.assertEqual(BroadcastRecipient.objects.get(broadcast=broadcast, channel="TELEGRAM").status, "FAILED")
        self.assertEqual(BroadcastRecipient.objects.filter(broadcast=broadcast).count(), 2)

    def test_the_owner_reads_the_new_reason_in_persian(self):
        self.assertIn("fallback", bc.SKIP_REASON_TITLES)
        self.assertFalse(bc.SKIP_REASON_TITLES["fallback"].isascii())


# ------------------------------------------------------- 10. skills by what was said


class SkillRoutingTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect("BALE")
        cfg = team.settings_for(self.store)
        cfg.assignment_mode = InboxSettings.Assignment.BY_SKILL
        cfg.save()
        self.online(self.sara, self.reza)
        profile = team.profile_for(self.store, self.reza)
        profile.skills = ["پرداخت"]
        profile.save()
        self._n = 0

    def write(self, text, sender="900"):
        self._n += 1
        out = ingest.receive(self.conn, Incoming(external_id=f"k{self._n}", thread_id=sender, sender_id=sender, name="علی", text=text))
        out.conversation.refresh_from_db()
        return out.conversation

    def test_what_the_customer_wrote_picks_the_member(self):
        conversation = self.write("اپراتور لطفاً، مشکل پرداخت دارم")
        self.assertEqual(conversation.assigned_to, self.reza)  # sara would win a plain round-robin

    def test_an_ending_on_the_skill_word_still_matches(self):
        conversation = self.write("اپراتور، پرداختم انجام نشد", sender="901")
        self.assertEqual(conversation.assigned_to, self.reza)

    def test_no_skill_word_falls_back_to_the_usual_rule(self):
        conversation = self.write("اپراتور لطفاً", sender="902")
        self.assertEqual(conversation.assigned_to, self.sara)  # least recently assigned, as before

    def test_a_tag_still_works_the_way_it_did(self):
        conversation = self.conversation(channel="BALE", sender="903")
        conversation.tags = ["پرداخت"]
        conversation.save()
        self.customer_says(conversation, "اپراتور")
        conversation.refresh_from_db()
        self.assertEqual(conversation.assigned_to, self.reza)

    def test_a_skill_inside_another_word_does_not_match(self):
        profile = team.profile_for(self.store, self.reza)
        profile.skills = ["مشاور"]
        profile.save()
        conversation = self.write("اپراتور، مشاورهٔ رایگان دارید؟", sender="904")
        self.assertEqual(conversation.assigned_to, self.sara)


# ---------------------------------------------------- 11. credit goes to who answered


class ResponseTimeCreditTests(InboxTestCase):
    def test_the_member_who_answered_gets_the_response_time(self):
        self.online(self.sara, self.reza)
        conversation = self.conversation(sender="c1")
        self.customer_says(conversation, "اپراتور")
        conversation.refresh_from_db()
        conversation.assigned_to = self.reza  # the thread sat in reza's queue...
        conversation.save()
        meta = ConversationMeta.objects.get(conversation=conversation)
        meta.waiting_since = timezone.now() - timedelta(minutes=41)
        meta.sla_breached_at = timezone.now() - timedelta(minutes=20)
        meta.save()
        replies.reply(conversation, self.sara, "بفرمایید")  # ...and sara answered it
        rows = {r["username"]: r for r in team.performance(self.store)}
        self.assertEqual(rows["sara"]["replies"], 1)
        self.assertEqual(rows["sara"]["conversations_answered"], 1)
        self.assertAlmostEqual(rows["sara"]["avg_first_response_seconds"], 41 * 60, delta=15)
        self.assertEqual(rows["reza"]["replies"], 0)
        self.assertEqual(rows["reza"]["conversations_answered"], 0)
        self.assertIsNone(rows["reza"]["avg_first_response_seconds"])
        # a missed SLA is the miss of whoever held the thread
        self.assertEqual(rows["reza"]["sla_breaches"], 1)

    def test_only_the_first_reply_counts_as_the_first_response(self):
        conversation = self.conversation(sender="c2")
        self.customer_says(conversation, "اپراتور")
        replies.reply(conversation, self.sara, "اول")
        replies.reply(conversation, self.reza, "دوم")
        rows = {r["username"]: r for r in team.performance(self.store)}
        self.assertEqual(rows["sara"]["conversations_answered"], 1)
        self.assertEqual(rows["reza"]["conversations_answered"], 0)
        self.assertEqual(rows["reza"]["replies"], 1)


# ------------------------------------------------------------ 12. «{name} عزیز»


class NameWithHonorificTests(InboxTestCase):
    def test_a_stand_in_never_doubles_the_honorific(self):
        cases = {
            "سلام {name} عزیز!": "سلام دوست عزیز!",
            "سلام {name} گرامی": "سلام دوست گرامی",
            "{نام} جان، سلام": "دوست جان، سلام",
            "سلام {name}!": "سلام دوست عزیز!",
            "{name}، {name} عزیز": "دوست عزیز، دوست عزیز",
        }
        for text, expected in cases.items():
            self.assertEqual(replies.render_name(text, ""), expected, text)

    def test_a_known_name_is_used_as_is(self):
        self.assertEqual(replies.render_name("سلام {name} عزیز!", "مریم"), "سلام مریم عزیز!")

    def test_a_reply_to_an_unknown_visitor(self):
        conversation = self.conversation(channel="WEBCHAT", name="بازدیدکنندهٔ سایت", sender="v7")
        replies.reply(conversation, self.sara, "سلام {name} عزیز! خوش آمدید.")
        self.assertEqual(conversation.messages.filter(role=Message.Role.HUMAN).last().text, "سلام دوست عزیز! خوش آمدید.")

    def test_a_broadcast_says_the_same(self):
        stranger = Contact.objects.create(store=self.store, name="09121234567")
        self.assertTrue(bc.render("سلام {name} عزیز", stranger).startswith("سلام دوست عزیز\n"))
        self.assertTrue(bc.render("سلام {name} عزیز", None).startswith("سلام دوست عزیز\n"))
        named = Contact.objects.create(store=self.store, name="مریم رضایی", phone="09120000009")
        self.assertTrue(bc.render("سلام {name} عزیز", named).startswith("سلام مریم عزیز\n"))


# ------------------------------------------------------------ 13. whole words, folded


class WholeWordTests(InboxTestCase):
    def test_phrases_are_whole_words_after_folding_spelling(self):
        self.assertTrue(norm.has_phrase("می‌خوام با اپراتور حرف بزنم", "اپراتور"))
        self.assertTrue(norm.has_phrase("اپراتورها", "اپراتور"))  # a plural is the same word
        self.assertFalse(norm.has_phrase("اپراتوری", "اپراتور"))
        self.assertTrue(norm.has_phrase("كارشناس لطفا", "کارشناس"))  # Arabic kaf
        self.assertTrue(norm.has_phrase("با ي٤ نفر", "با ی4 نفر"))  # Arabic yeh, Arabic digit
        self.assertFalse(norm.has_phrase("با آدم‌های خوب", "با آدم"))  # a phrase needs its words exact
        self.assertFalse(norm.has_phrase("anything", ""))
        self.assertTrue(norm.has_phrase("Operator!", "operator"))


# ------------------------------------------------------------ 14. Rubika errors


class RubikaInvalidInputTests(InboxTestCase):
    def test_a_bad_token_is_said_to_be_the_token_on_every_method(self):
        with FakePlatform({"getMe": (200, {"status": "INVALID_INPUT"}), "sendMessage": (200, {"status": "INVALID_INPUT"})}) as fake, \
                override_settings(INBOX_API_BASES={"RUBIKA": fake.url}):
            result = rubika.RubikaAdapter(Conn(token="123456789:FAKEFAKEFAKEFAKEFAKE")).send("b0abc", "سلام")
        self.assertFalse(result.ok)
        self.assertIn("توکن ربات روبیکا پذیرفته نشد", result.reason)
        self.assertNotIn("INVALID_INPUT", result.reason)

    def test_a_good_token_with_a_bad_chat_id_does_not_blame_the_token(self):
        with FakePlatform({
            "getMe": {"status": "OK", "data": {"bot": {"username": "my_bot"}}},
            "sendMessage": (200, {"status": "INVALID_INPUT"}),
        }) as fake, override_settings(INBOX_API_BASES={"RUBIKA": fake.url}):
            result = rubika.RubikaAdapter(Conn(token="TOKTOKTOKTOKTOKTOKTOK")).send("not-a-chat", "سلام")
        self.assertFalse(result.ok)
        self.assertIn("شناسهٔ گفتگو", result.reason)
        self.assertNotIn("توکن", result.reason)
        self.assertNotIn("INVALID_INPUT", result.reason)

    def test_the_probe_does_not_loop(self):
        with FakePlatform({"getMe": (200, {"status": "INVALID_INPUT"}), "getUpdates": (200, {"status": "INVALID_INPUT"})}) as fake, \
                override_settings(INBOX_API_BASES={"RUBIKA": fake.url}):
            adapter = rubika.RubikaAdapter(Conn(token="TOKTOKTOKTOKTOKTOKTOK"))
            with self.assertRaises(Exception) as caught:
                adapter.poll("")
        self.assertIn("پذیرفته نشد", str(caught.exception))
        self.assertLessEqual(len(fake.requests), 2)  # the failing call, then one getMe - never more


# ------------------------------------------------------------ 15. the mention is isolated


class MentionRenderingSourceTests(InboxTestCase):
    """The panel isolates «@name» so Persian text cannot flip it into «name@» (checked in the browser too)."""

    def test_the_format_helper_and_the_pane_use_it(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "inbox"
        if not root.exists():
            self.skipTest("frontend sources are not next to the backend in this checkout")
        fmt = (root / "format.ts").read_text(encoding="utf-8")
        pane = (root / "ThreadPane.tsx").read_text(encoding="utf-8")
        css = (root / "inbox.css").read_text(encoding="utf-8")
        self.assertIn("export function splitMentions", fmt)
        self.assertIn("<bdi", pane)
        self.assertIn('dir="ltr"', pane)
        self.assertIn(".ib-mention", css)
        self.assertIn("unicode-bidi: isolate", css)
