"""ایده‌های آماده: تعداد و دسته‌ها، کامل‌بودن، فارسی‌بودن، و مهم‌تر از همه **هیچ عدد/قیمت/آمار/ادعای ساختگی** در هیچ‌کدام (سنجشِ هر ایده)."""
import datetime as dt
import re

from django.test import SimpleTestCase

from . import bank, fill, guard, jalali
from .catalog import CATEGORIES, CHANNELS, FORMATS
from .seeds import BUILTIN_IDEAS

PERSIAN = re.compile("[؀-ۿ]")
ANY_DIGIT = re.compile("[0-9۰-۹٠-٩]")
LUNAR = ("محرم", "عاشورا", "تاسوعا", "رمضان", "فطر", "قربان", "غدیر", "میلاد", "ولادت", "شهادت", "شعبان", "رجب", "عرفه", "نیمه شعبان", "بعثت")


def text_of(idea: dict) -> str:
    return " ".join(str(idea[f]) for f in bank.TEXT_FIELDS)


class SeedBankTests(SimpleTestCase):
    def test_size_and_eight_categories(self):
        self.assertGreaterEqual(len(BUILTIN_IDEAS), 80)
        self.assertLessEqual(len(BUILTIN_IDEAS), 120)
        self.assertEqual(len(CATEGORIES), 8)
        per = {c: sum(1 for i in BUILTIN_IDEAS.values() if i["category"] == c) for c in CATEGORIES}
        self.assertEqual(set(per), set(CATEGORIES))
        self.assertGreaterEqual(min(per.values()), 8, per)

    def test_every_idea_is_complete_persian_and_unique(self):
        titles = set()
        for key, i in BUILTIN_IDEAS.items():
            self.assertTrue(key.startswith(i["category"] + "_"), key)
            for f in bank.TEXT_FIELDS:
                self.assertTrue(i[f].strip(), f"{key}: {f} خالی است")
                self.assertTrue(PERSIAN.search(i[f]), f"{key}: {f} فارسی نیست")
                self.assertLessEqual(len(i[f]), bank.LIMITS[f], f"{key}: {f} بلند است")
            self.assertIn(i["format"], FORMATS, key)
            self.assertIn(i["channel"], CHANNELS, key)
            self.assertTrue(i["tags"], key)
            self.assertNotIn(i["title"], titles, f"{key}: عنوانِ تکراری")
            titles.add(i["title"])
            # normalize هیچ‌چیز را عوض نمی‌کند (ایدهٔ آماده از قبل تمیز است)
            self.assertEqual(bank.normalize(i)["title"], i["title"], key)

    def test_all_formats_are_used(self):
        used = {i["format"] for i in BUILTIN_IDEAS.values()}
        self.assertEqual(used, set(FORMATS))

    def test_no_digit_claim_price_word_or_statistic_in_any_seed(self):
        """قاعدهٔ اصلیِ این دسته: هیچ عدد (فارسی/لاتین/عربی)، قیمت، درصد، تخفیف، آمار یا برتریِ بی‌سندی در ایده‌ها نیست."""
        for key, i in BUILTIN_IDEAS.items():
            txt = text_of(i)
            self.assertIsNone(ANY_DIGIT.search(txt), f"{key}: رقم دارد: {txt}")
            self.assertEqual(guard.problems(txt), [], f"{key}: {guard.problems(txt)}")
            for w in guard.ALL_RISKY:
                self.assertNotIn(w, txt, f"{key}: «{w}»")

    def test_guard_covers_the_thumbnail_risky_words(self):
        """فهرستِ نگهبان از ``thumbs.ideation.RISKY`` کم‌تر نشود؛ و هر واژه‌اش روی تک‌تکِ ایده‌ها سنجیده شود."""
        try:
            from apps.thumbs.ideation import RISKY
        except Exception:  # noqa: BLE001 — اپِ تامنیل‌ساز در این نسخه نباشد
            self.skipTest("apps.thumbs نیست")
        self.assertTrue(set(RISKY) <= set(guard.ALL_RISKY), set(RISKY) - set(guard.ALL_RISKY))
        for key, i in BUILTIN_IDEAS.items():
            txt = text_of(i)
            for w in RISKY:
                self.assertNotIn(w, txt, f"{key}: «{w}»")

    def test_guard_itself(self):
        self.assertTrue(guard.problems("۵۰٪ تخفیفِ ویژه"))
        self.assertTrue(guard.problems("فقط ۹۹۰۰۰ تومان"))
        self.assertTrue(guard.problems("بیشتر از ۳ برابر"))
        self.assertTrue(guard.problems("بهترین قیمتِ بازار"))
        self.assertTrue(guard.problems("عالی 😀"))
        self.assertEqual(guard.problems("یک نکتهٔ ساده دربارهٔ برنامهٔ ورزشی"), [])
        # واژه یا عددی که خودِ کاربر نوشته ادعای ساختگی نیست
        self.assertEqual(guard.problems("پیشنهادِ ۲۰ درصدی", "پیشنهادِ ۲۰ درصدی برای نوروز"), [])
        self.assertTrue(guard.problems("پیشنهادِ ۳۰ درصدی", "پیشنهادِ ۲۰ درصدی"))
        self.assertEqual(guard.digit_runs("۱۲ و 13 و ٤"), ["12", "13", "4"])

    def test_placeholders_are_only_the_known_ones_and_get_filled(self):
        from .catalog import PLACEHOLDERS

        ctx = fill.context(type("S", (), {"name": "فروشگاهِ نمونه", "target_audience": "", "business_type": "", "profile": None})())
        for key, i in BUILTIN_IDEAS.items():
            txt = text_of(i)
            self.assertTrue(set(guard.PLACEHOLDER.findall(txt)) <= set(PLACEHOLDERS), f"{key}: جای‌گیرِ ناشناخته")
            self.assertNotIn("{", fill.fill_text(txt, ctx), key)
            self.assertNotIn("}", fill.fill_text(txt, ctx), key)

    def test_social_proof_ideas_are_empty_templates_that_need_real_data(self):
        proof = {k: i for k, i in BUILTIN_IDEAS.items() if i["category"] == "proof"}
        self.assertGreaterEqual(len(proof), 8)
        slotted = [k for k, i in proof.items() if guard.slots(text_of(i))]
        self.assertGreaterEqual(len(slotted), 8, "اثباتِ اجتماعی باید قالبِ خالی باشد: " + str(sorted(set(proof) - set(slotted))))
        for k, i in proof.items():
            # هیچ نقل‌قولِ پرشده‌ای (متنِ بینِ « ») بدونِ جایِ خالی در اثباتِ اجتماعی نیست: نظرِ مشتری ساخته نمی‌شود
            for quoted in re.findall("«([^»]*)»", text_of(i)):
                self.assertTrue(guard.SLOT.search(quoted), f"{k}: نقل‌قولِ پرشده «{quoted}»")

    def test_offer_ideas_leave_the_real_offer_to_the_shop(self):
        offers = [i for i in BUILTIN_IDEAS.values() if i["category"] == "offer"]
        self.assertGreaterEqual(sum(1 for i in offers if guard.slots(text_of(i))), 8)

    def test_occasions_are_fixed_jalali_dates_only(self):
        occ = {k: i for k, i in BUILTIN_IDEAS.items() if i["category"] == "occasion"}
        self.assertGreaterEqual(len(occ), 12)
        for k, i in occ.items():
            o = i["occasion"]
            self.assertTrue(o and 1 <= o["month"] <= 12 and 1 <= o["day"] <= jalali.month_length(1404, o["month"]), k)
            self.assertTrue(o["name"], k)
            for w in LUNAR:
                self.assertNotIn(w, o["name"] + text_of(i), f"{k}: مناسبتِ قمری «{w}»")
        names = " ".join(i["occasion"]["name"] for i in occ.values())
        for must in ("نوروز", "سیزده‌به‌در", "یلدا"):
            self.assertIn(must, names)
        self.assertTrue(all(not i.get("occasion") for i in BUILTIN_IDEAS.values() if i["category"] != "occasion"))


class JalaliTests(SimpleTestCase):
    def test_known_dates(self):
        self.assertEqual(jalali.jalali_to_gregorian(1405, 1, 1), dt.date(2026, 3, 21))
        self.assertEqual(jalali.jalali_to_gregorian(1405, 8, 23), dt.date(2026, 11, 14))       # امروزِ این پروژه
        self.assertEqual(jalali.jalali_to_gregorian(1404, 12, 29), dt.date(2026, 3, 20))
        self.assertTrue(jalali.is_leap(1403))
        self.assertFalse(jalali.is_leap(1404))
        self.assertEqual((jalali.month_length(1403, 12), jalali.month_length(1404, 12), jalali.month_length(1404, 1), jalali.month_length(1404, 9)), (30, 29, 31, 30))

    def test_round_trip_against_the_projects_own_converter(self):
        from apps.common.versioning import gregorian_to_jalali

        for y in range(1395, 1415):
            for m in range(1, 13):
                for d in (1, 15, jalali.month_length(y, m)):
                    g = jalali.jalali_to_gregorian(y, m, d)
                    self.assertEqual(gregorian_to_jalali(g.year, g.month, g.day), (y, m, d))

    def test_next_occurrence(self):
        today = dt.date(2026, 11, 14)                                   # ۲۳ آبان ۱۴۰۵
        self.assertEqual(jalali.next_occurrence(9, 30, today), dt.date(2026, 12, 21))   # یلدا
        self.assertEqual(jalali.next_occurrence(1, 1, today), dt.date(2027, 3, 21))     # نوروز بعدی
        self.assertEqual(jalali.next_occurrence(8, 23, today), today)                     # امروز هم «پیش‌رو» است
        self.assertEqual(jalali.next_occurrence(12, 30, dt.date(2026, 3, 1)), dt.date(2026, 3, 20))   # ۳۰ اسفندِ سالِ غیرکبیسه ⇒ آخرِ ماه
        self.assertEqual(jalali.label(9, 30), "۳۰ آذر")
        self.assertEqual(jalali.label(12), "اسفندماه")

    def test_every_seed_occasion_has_an_upcoming_date(self):
        today = dt.date(2026, 11, 14)
        for k, i in BUILTIN_IDEAS.items():
            if i.get("occasion"):
                info = bank.occasion_info(i["occasion"], today)
                self.assertTrue(0 <= info["days"] <= 366, k)
