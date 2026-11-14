"""The caption prompt's own rules are enforced on the model's answer.

Every string below is a real caption of the Chagher store (33 Instagram
captions were stored when this was written): 12 broke the hashtag cap, 9 the
emoji rule, one printed the prompt's example word in a PRICE, two ended
«… ساخته شود.», one had a medium text that was the long text, and 11 used the
same call to action.
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.jobs.models import Job
from apps.products.models import Product
from apps.stores.models import Store
from services.ai.prompts import captions as prompts
from services.ai.prompts.captions import validate_captions

from . import caption_rules as rules
from .models import Caption
from .tasks import _recent_ctas, generate_captions_task

# ── the real strings ─────────────────────────────────────────────────────────
S19 = "یک برنامه، ۲۵ توکن، ۳۰۰ هزار تومان. 🏋️‍♂️🥗"
M19 = (
    "برنامه ورزشی یا غذایی فقط با هوش مصنوعی — ۲۵ توکن. مربیان، فقط ورزشکار را در کمتر از "
    "یک دقیقه پیش‌نویس می‌کنند. 🧠"
)
L19 = (
    "چغر، دستیار هوش مصنوعی مربیان است. با وارد کردن اطلاعات ورزشکار، یک برنامه ورزشی یا غذایی "
    "در کمتر از یک دقیقه تهیه می‌شود. اگر فقط یکی از برنامه‌ها را نیاز دارید، فقط آن را "
    "ساخته می‌شود. هزینه ۲۵ توکن یا ۳۰۰ هزار تومان است. 🧠🏋️‍♂️🥗"
)
CTA19 = "برنامه خود را با ۲۵ توکن ساخته شود. 📲"
TAGS19 = ["#چغر", "#برنامهورزشی", "#برنامهغذایی", "#هوشمصنوعی", "#مربی", "#ورزشکار"]

S25 = "یک برنامه، ۲۵ توکن، ۳۰۰ هزار تومان. 🏋️‍♂️🥗"
M25 = (
    "چغر، مربیِ شما را از کار تکراری رها می‌کند. فقط یک برنامه ورزشی یا غذایی ساخته "
    "می‌شود. ۲۵ توکن = ۳۰۰ هزار تومان. 🚀"
)
L25_BAD = (
    "مربیان، وقت خود را بازگردانید! چغر، با هوش مصنوعی، برنامه ورزشی یا غذایی را در کمتر از یک "
    "دقیقه پیش‌نویس می‌کند. فقط یکی از دو برنامه را انتخاب کنید، "
    "۲۵ توکن = ۳۰ نیم‌فاصله تومان. 🧠💪"
)
TAGS25 = [
    "چغر", "برنامه ورزشی", "برنامه غذایی", "هوش مصنوعی", "مربی", "چغر", "فروشگاه چغر",
    "توکن", "کمک مربی",
]

M20 = (
    "مربی، وقتت رو صرف مربیگری کن. با چغر، برنامهٔ ورزشی و غذایی ورزشکارت رو در کمتر از یک "
    "دقیقه پیش‌نویس می‌کند. PDFِ حرفه‌ای و قابل‌چاپ، آمادهٔ دادن به "
    "ورزشکار است. 📄"
)
L20 = (
    "مربی، وقتت رو صرف مربیگری کن. با چغر، برنامهٔ ورزشی و غذایی ورزشکارت رو در کمتر از یک "
    "دقیقه پیش‌نویس می‌کند. خروجی یک PDFِ برندشده و قابل‌چاپ است که "
    "می‌تواند به ورزشکارت داده شود. با چغر، چغرتر شو. 📱✨"
)


def item(platform="INSTAGRAM", **over):
    base = {
        "platform": platform, "short": "کوتاه و روشن", "medium": M19, "long": L19,
        "hashtags": ["چغر"], "cta": "همین حالا برنامه‌ات را بساز",
    }
    base.update(over)
    return base


class EmojiRuleTests(SimpleTestCase):
    def test_a_stacked_run_keeps_only_its_first_emoji(self):
        out = rules.limit_emoji(S19, 4)
        self.assertEqual(rules.count_emoji(out), 1)
        self.assertTrue(out.startswith("یک برنامه، ۲۵ توکن، ۳۰۰ هزار تومان."))

    def test_a_zwj_sequence_is_one_emoji(self):
        self.assertEqual(rules.count_emoji("🏋️‍♂️"), 1)
        self.assertEqual(rules.count_emoji("🇮🇷"), 1)

    def test_the_cap_per_platform(self):
        text = "الف 🧠 ب 💪 ج 🚀 د ✨ ه 📲 و 🔥"
        self.assertEqual(rules.count_emoji(rules.limit_emoji(text, 4)), 4)
        self.assertEqual(rules.count_emoji(rules.limit_emoji(text, 2)), 2)
        self.assertEqual(rules.count_emoji(rules.limit_emoji(text, 0)), 0)

    def test_the_hook_keeps_its_emoji_and_the_tail_loses_them(self):
        out = rules.limit_emoji("چرا وقتت را تلف می‌کنی؟ 🧠 برنامه بساز 💪 و برو 🚀", 1)
        self.assertIn("🧠", out)
        self.assertNotIn("🚀", out)

    def test_one_budget_is_shared_by_the_texts_of_a_caption(self):
        """«Instagram 2-4 per caption» means the whole caption, not each text."""
        texts = {
            "short": "الف 🧠 ب 💪", "medium": "ج 🚀", "long": "د ✨ ه 📲", "cta": "همین حالا 🔥",
        }
        counts = lambda out: {k: rules.count_emoji(v) for k, v in out.items()}  # noqa: E731
        # every text keeps its first emoji before any text gets a second one
        self.assertEqual(
            counts(rules.limit_emoji_budget(texts, 4)),
            {"short": 1, "medium": 1, "long": 1, "cta": 1},
        )
        self.assertEqual(
            counts(rules.limit_emoji_budget(texts, 6)),
            {"short": 2, "medium": 1, "long": 2, "cta": 1},
        )
        self.assertEqual(sum(counts(rules.limit_emoji_budget(texts, 2)).values()), 2)
        self.assertEqual(sum(counts(rules.limit_emoji_budget(texts, 0)).values()), 0)

    def test_the_budget_never_adds_emoji_and_never_stacks_them(self):
        out = rules.limit_emoji_budget({"short": S19, "medium": "بدون ایموجی"}, 4)
        self.assertEqual(rules.count_emoji(out["short"]), 1)
        self.assertEqual(out["medium"], "بدون ایموجی")

    def test_text_without_extra_emoji_is_returned_unchanged(self):
        self.assertEqual(rules.limit_emoji(M19, 4), M19)

    def test_removal_leaves_no_double_space_or_orphan_space(self):
        out = rules.limit_emoji("سلام 🧠 🚀 دنیا 🔥 .", 1)
        self.assertNotIn("  ", out)
        self.assertNotIn(" .", out)


class HashtagRuleTests(SimpleTestCase):
    def test_glued_tags_are_split_and_the_hash_dropped(self):
        self.assertEqual(
            rules.clean_hashtags(TAGS19, 8),
            ["چغر", "برنامه_ورزشی", "برنامه_غذایی", "هوش_مصنوعی", "مربی", "ورزشکار"],
        )

    def test_a_tag_repeated_in_any_spelling_is_kept_once(self):
        """#25 repeated «چغر»; Instagram also reads «Fitness» and «fitness» as one."""
        out = rules.clean_hashtags(TAGS25 + ["Fitness", "fitness", "#چغر", "برنامه_ورزشی"], 20)
        self.assertEqual(out.count("چغر"), 1)
        self.assertEqual([t.lower() for t in out].count("fitness"), 1)
        self.assertEqual(sum(t.replace("_", " ") == "برنامه ورزشی" for t in out), 1)

    def test_the_cap_is_eight_and_three_for_linkedin(self):
        tags = [f"تگ{i}" for i in range(12)]
        self.assertEqual(len(rules.clean_hashtags(tags, rules.LIMITS["INSTAGRAM"]["hashtags"])), 8)
        self.assertEqual(len(rules.clean_hashtags(tags, rules.LIMITS["LINKEDIN"]["hashtags"])), 3)

    def test_the_models_own_order_survives(self):
        self.assertEqual(rules.clean_hashtags(["الف", "ب", "الف", "ج"], 8), ["الف", "ب", "ج"])


class InstructionWordTests(SimpleTestCase):
    def test_the_typing_character_name_inside_a_price_is_found(self):
        self.assertTrue(rules.instruction_leaks(L25_BAD))

    def test_ordinary_persian_is_clean(self):
        for text in (S19, M19, L19, M25, M20, L20):
            self.assertEqual(rules.instruction_leaks(text), [], text)

    def test_other_instruction_words_are_found(self):
        for text in ("برنامه ZWNJ دارد", "این یک prompt است", "خروجی JSON", "half-space درست"):
            self.assertTrue(rules.instruction_leaks(text), text)


class PriceRuleTests(SimpleTestCase):
    def test_amounts_are_read_in_toman(self):
        self.assertEqual(rules.amounts_in("۳۰۰ هزار تومان"), [300000])
        self.assertEqual(rules.amounts_in("600,000 تومان"), [600000])
        self.assertEqual(rules.amounts_in("۱٫۵ میلیون"), [])  # no unit word: not a price
        self.assertEqual(rules.amounts_in("۱.۵ میلیون تومان"), [1500000])
        self.assertEqual(rules.amounts_in("۳٬۰۰۰٬۰۰۰ ریال"), [300000])
        self.assertEqual(rules.amounts_in(L25_BAD), [])

    def test_a_price_that_is_not_the_shops_is_found(self):
        self.assertEqual(rules.price_problems(M25, {300000, 600000}), [])
        self.assertEqual(rules.price_problems("فقط ۳۵۰ هزار تومان", {300000, 600000}), [350000])

    def test_a_price_when_the_shop_has_none_is_found(self):
        self.assertEqual(rules.price_problems(M25, set()), [300000])


class CallToActionRuleTests(SimpleTestCase):
    def test_the_real_passive_ctas_are_found(self):
        self.assertIsNotNone(rules.cta_problem(CTA19))
        self.assertIsNotNone(rules.cta_problem("برنامه خود را با ۲۵ توکن ساخته شود. 🔗"))
        self.assertIsNotNone(rules.cta_problem("لینک در بایو است."))

    def test_commands_pass(self):
        for cta in (
            "با چغر، چغرتر شو", "همین حالا برنامه‌ات را بساز 🚀", "برای سفارش پیام بدهید.",
            "روی لینک بایو بزنید", "", "کلیک کنید!",
        ):
            self.assertIsNone(rules.cta_problem(cta), cta)


class SimilarityRuleTests(SimpleTestCase):
    def test_the_real_medium_and_long_that_were_one_paragraph(self):
        self.assertTrue(rules.too_similar(M20, L20))

    def test_texts_that_say_different_things_pass(self):
        self.assertFalse(rules.too_similar(M19, L19))
        self.assertFalse(rules.too_similar(M25, L25_BAD))

    def test_short_texts_are_never_compared(self):
        self.assertFalse(rules.too_similar("برنامه بساز", "برنامه بساز"))


class ValidateCaptionsTests(SimpleTestCase):
    def run_validate(self, caption, **kwargs):
        parsed = {"captions": [caption]}
        ok, problems = validate_captions(parsed, {caption["platform"]}, **kwargs)
        return ok, problems, parsed["captions"][0]

    def test_hashtags_and_emoji_are_fixed_in_place_and_the_answer_stays_valid(self):
        ok, problems, fixed = self.run_validate(
            item(short=S19, long=L19, hashtags=TAGS19 + TAGS25 + ["x1", "x2", "x3"]),
        )
        self.assertTrue(ok, problems)
        self.assertLessEqual(len(fixed["hashtags"]), 8)
        self.assertEqual(fixed["hashtags"].count("چغر"), 1)
        total = sum(rules.count_emoji(fixed[key]) for key in ("short", "medium", "long", "cta"))
        self.assertLessEqual(total, 4)
        self.assertEqual(rules.count_emoji(fixed["long"]), 1)  # 🧠🏋️‍♂️🥗 stacked -> one

    def test_hashtags_sent_as_one_string_are_split_into_tags(self):
        _ok, _p, fixed = self.run_validate(item(hashtags="#چغر #برنامه_ورزشی #چغر"))
        self.assertEqual(fixed["hashtags"], ["چغر", "برنامه_ورزشی"])
        _ok, _p, fixed = self.run_validate(item(hashtags="مربی، ورزشکار"))
        self.assertEqual(fixed["hashtags"], ["مربی", "ورزشکار"])
        _ok, _p, fixed = self.run_validate(item(hashtags=None))
        self.assertEqual(fixed["hashtags"], [])

    def test_linkedin_gets_three_tags_and_no_emoji(self):
        ok, _problems, fixed = self.run_validate(
            item("LINKEDIN", short="خط کوتاه 🚀", hashtags=[f"تگ{i}" for i in range(9)]),
        )
        self.assertTrue(ok)
        self.assertEqual(len(fixed["hashtags"]), 3)
        for key in ("short", "medium", "long", "cta"):
            self.assertEqual(rules.count_emoji(fixed[key]), 0, key)

    def test_telegram_gets_two_emoji_in_all(self):
        _ok, _p, fixed = self.run_validate(item("TELEGRAM", short="الف 🧠 ب 💪 ج 🚀 د ✨"))
        total = sum(rules.count_emoji(fixed[key]) for key in ("short", "medium", "long", "cta"))
        self.assertEqual(total, 2)

    def test_an_instruction_word_in_a_price_sends_the_call_to_the_next_model(self):
        ok, problems, _ = self.run_validate(item(long=L25_BAD))
        self.assertFalse(ok)
        self.assertTrue(any("نیمفاصله" in p and "long" in p for p in problems), problems)

    def test_on_the_last_attempt_the_draft_is_kept(self):
        ok, problems, fixed = self.run_validate(item(long=L25_BAD), strict=False)
        self.assertTrue(ok)
        self.assertEqual(problems, [])
        self.assertIn("نیم‌فاصله", fixed["long"])  # the guard will name it beside the text

    def test_a_passive_cta_is_rejected_strictly(self):
        ok, problems, _ = self.run_validate(item(cta=CTA19))
        self.assertFalse(ok)
        self.assertTrue(any("cta" in p for p in problems))

    def test_medium_equal_to_long_is_rejected_strictly(self):
        ok, problems, _ = self.run_validate(item(medium=M20, long=L20))
        self.assertFalse(ok)
        self.assertTrue(any("same paragraph" in p for p in problems))

    def test_a_length_that_was_missing_is_not_blamed_for_being_a_copy(self):
        """The fallback copies the best text into an empty length by design."""
        ok, problems, fixed = self.run_validate(item(medium=M20, long=""))
        self.assertTrue(ok, problems)
        self.assertEqual(fixed["long"], fixed["medium"])

    def test_without_a_product_the_price_is_not_checked(self):
        ok, _p, _f = self.run_validate(item(short="فقط ۹۹ هزار تومان"))
        self.assertTrue(ok)

    def test_a_clean_answer_is_untouched(self):
        ok, problems, fixed = self.run_validate(item())
        self.assertTrue(ok, problems)
        self.assertEqual(fixed["medium"], M19)
        self.assertEqual(fixed["hashtags"], ["چغر"])


class ValidateWithProductTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("cap-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر آزمون")
        self.single = Product.objects.create(
            store=self.store, name="برنامهٔ تکی", price=300000, currency="IRT",
        )
        Product.objects.create(store=self.store, name="هر دو برنامه", price=600000, currency="IRT")

    def validate(self, caption, **kwargs):
        parsed = {"captions": [caption]}
        ok, problems = validate_captions(parsed, {"INSTAGRAM"}, product=self.single, **kwargs)
        return ok, problems

    def test_the_shops_own_prices_pass(self):
        ok, problems = self.validate(item(short=S19, medium=M25, long="یک برنامه ۳۰۰ هزار تومان، هر دو ۶۰۰ هزار تومان است. "
                                          "برای شروع کافی است اطلاعات ورزشکار را وارد کنید و چند لحظه صبر کنید."))
        self.assertTrue(ok, problems)

    def test_a_price_nobody_set_is_rejected_strictly_and_kept_leniently(self):
        caption = item(short="فقط ۳۵۰ هزار تومان")
        ok, problems = self.validate(caption)
        self.assertFalse(ok)
        self.assertTrue(any("350000" in p for p in problems), problems)
        ok, problems = self.validate(item(short="فقط ۳۵۰ هزار تومان"), strict=False)
        self.assertTrue(ok)

    def test_a_price_quoted_by_the_product_description_is_allowed(self):
        self.single.description = "پکیج ویژه ۴۵۰ هزار تومان برای هفتهٔ اول"
        self.single.save()
        ok, problems = self.validate(item(short="پکیج ویژه ۴۵۰ هزار تومان"))
        self.assertTrue(ok, problems)

    def test_the_price_before_a_discount_and_a_threshold_in_the_store_text_are_real(self):
        self.single.compare_at_price = 400000
        self.single.save()
        self.store.description = "ارسال رایگان برای خرید بالای ۵۰۰ هزار تومان"
        self.store.save()
        ok, problems = self.validate(item(short="قبلاً ۴۰۰ هزار تومان، حالا ۳۰۰ هزار تومان"))
        self.assertTrue(ok, problems)
        ok, problems = self.validate(item(short="ارسال رایگان بالای ۵۰۰ هزار تومان"))
        self.assertTrue(ok, problems)

    def test_an_instruction_word_the_shop_really_uses_is_not_a_leak(self):
        text = "کتابخانهٔ پرامپت برای مربی‌ها"
        ok, _problems = self.validate(item(short=text))
        self.assertFalse(ok)  # this shop sells fitness plans: the word is a slip
        self.single.name = "کتابخانهٔ پرامپت"
        self.single.save()
        ok, problems = self.validate(item(short=text))
        self.assertTrue(ok, problems)

    def test_recent_ctas_are_shown_to_the_prompt_once_each(self):
        for cta in ("همین حالا بساز", "همین حالا بساز", "پیام بدهید", ""):
            Caption.objects.create(
                store=self.store, product=self.single, platform="INSTAGRAM",
                short_text="x", cta=cta,
            )
        self.assertEqual(_recent_ctas(self.store), ["پیام بدهید", "همین حالا بساز"])
        text = prompts.build_captions_prompt(
            self.single, None, ["INSTAGRAM"], "", "", avoid_ctas=["همین حالا بساز"],
        )
        self.assertIn("already used", text)
        self.assertIn("همین حالا بساز", text)
        self.assertNotIn("already used", prompts.build_captions_prompt(
            self.single, None, ["INSTAGRAM"], "", "",
        ))

    def test_the_prompt_no_longer_contains_the_word_that_leaked(self):
        text = prompts.build_captions_prompt(self.single, None, ["INSTAGRAM"], "", "")
        self.assertNotIn("«نیم‌فاصله»", text)
        self.assertNotIn("«نیم‌فاصله»", text)
        self.assertEqual(prompts.CAPTIONS_PROMPT_VERSION, "6")


def _answer(**over):
    return {"captions": [item(**over)]}


class CaptionTaskEnforcementTests(TestCase):
    """The rules inside the real task: retry, then keep the draft with warnings."""

    def setUp(self):
        self.owner = User.objects.create_user("cap-task", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر آزمون ۲")
        self.product = Product.objects.create(
            store=self.store, name="برنامهٔ تکی", price=300000, currency="IRT",
        )

    def run_task(self, answers):
        job = Job.objects.create(store=self.store, type=Job.Type.CAPTION_GENERATION)
        with patch("apps.content.tasks.text_provider") as provider, \
                patch("apps.content.tasks.models_for", return_value=["model-a", "model-b"]), \
                patch("apps.ai.services.gpu.unload_ollama_models"):
            provider.return_value.generate_json.side_effect = [(a, "{}") for a in answers]
            generate_captions_task.apply(args=(job.id, self.product.id, ["INSTAGRAM"], "", ""))
            calls = provider.return_value.generate_json.call_count
        job.refresh_from_db()
        return job, calls

    def test_a_bad_first_answer_is_replaced_by_the_next_models_good_one(self):
        job, calls = self.run_task([_answer(long=L25_BAD), _answer(cta="همین حالا برنامه‌ات را بساز")])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(calls, 2)
        caption = Caption.objects.get()
        self.assertNotIn("نیم‌فاصله", caption.long_text)

    def test_when_every_model_slips_the_owner_still_gets_a_draft_with_warnings(self):
        bad = dict(
            short=S19, medium="فقط ۳۰۰ هزار تومان", long=L25_BAD, cta=CTA19, hashtags=TAGS19 + TAGS25,
        )
        job, calls = self.run_task([_answer(**bad), _answer(**bad)])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(calls, 2)
        caption = Caption.objects.get()
        # fixed in place whatever the attempt
        self.assertLessEqual(len(caption.hashtags), 8)
        self.assertEqual(rules.count_emoji(caption.short_text), 1)
        # and the guard's findings are stored with the job
        warnings = job.result["warnings"]
        self.assertIn(str(caption.id), {str(k) for k in warnings})
        self.assertTrue(list(warnings.values())[0])

    def test_a_clean_answer_has_no_warnings_entry_for_the_caption(self):
        # no price in the text: `caption_guard` (rightly) asks the owner to check any price it finds
        clean = (
            "برنامهٔ ورزشی یا غذایی ورزشکار را فقط با وارد کردن اطلاعاتش بسازید. "
            "خروجی یک فایل آمادهٔ چاپ است و مربی می‌تواند آن را همان لحظه به ورزشکار بدهد."
        )
        job, calls = self.run_task([_answer(medium="برنامه‌ات را در کمتر از یک دقیقه پیش‌نویس کن.", long=clean)])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(calls, 1)
        self.assertEqual(job.result["warnings"], {})

    def test_the_same_opening_line_as_an_earlier_draft_is_warned_at_generation_too(self):
        """The panel's serializer warns about a repeated hook; the stored job result must say the same."""
        Caption.objects.create(
            store=self.store, product=self.product, platform="INSTAGRAM", short_text="کوتاه و روشن!",
        )
        job, _calls = self.run_task([_answer()])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        caption = Caption.objects.order_by("-id").first()
        messages = job.result["warnings"][str(caption.id)] if str(caption.id) in job.result["warnings"]             else job.result["warnings"][caption.id]
        self.assertTrue(any("جملهٔ آغازین" in m for m in messages), messages)
