"""ساز و کارِ بانک: نرمال‌سازی، جست‌وجو و فیلتر، ستاره/پنهانِ **جدا برای هر فروشگاه**، ایده‌های خودِ فروشگاه، کپی، پرکردنِ جای‌گیرها از پروفایل.

SOURCE: آزمون‌ها از InstAI:tests/test_idea_bank.py @ 2f8aa90 گرفته و برای فروشگاه بازنویسی شده (normalise، فیلتر، علامت‌ها، کپی، فقط‌خواندنیِ آماده‌ها)."""
import datetime as dt

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.products.models import Product
from apps.stores.models import Store, StoreProfile

from . import bank, fill
from .models import IdeaMark, IdeaUse, StoreIdea
from .seeds import BUILTIN_IDEAS

User = get_user_model()
TODAY = dt.date(2026, 11, 14)


def make_store(name="چغر", owner="bank-owner", **kw):
    user = User.objects.create_user(owner, password="x")
    store = Store.objects.create(owner=user, name=name, business_type=kw.pop("business_type", "نرم‌افزار و خدمات دیجیتال برای مربیان ورزشی"),
                                 target_audience=kw.pop("target_audience", "مربی‌های باشگاه و مربی‌های شخصی که برنامه می‌نویسند؛ و ورزشکاران."), **kw)
    return user, store


class FoldAndNormalizeTests(SimpleTestCase):
    def test_fold_unifies_persian_spellings(self):
        self.assertEqual(bank.fold("مربيِ ورزشی ۱۲۳ ك"), bank.fold("مربیِ ورزشی 123 ک"))
        self.assertEqual(bank.fold("مربی‌های   باشگاه"), "مربی های باشگاه")
        self.assertEqual(bank.fold("ABC"), "abc")

    def test_normalize_clamps_everything(self):
        n = bank.normalize({"category": "nope", "format": "nope", "channel": "nope", "tags": "الف, ب،الف\nج", "title": "  عنوان  ", "logline": "x" * 900,
                            "occasion": {"month": 13, "day": 1}, "evil": "drop me"})
        self.assertEqual((n["category"], n["format"], n["channel"]), ("tips", "photo", "instagram"))
        self.assertEqual(n["tags"], ["الف", "ب", "ج"])
        self.assertEqual(n["title"], "عنوان")
        self.assertEqual(len(n["logline"]), bank.LIMITS["logline"])
        self.assertIsNone(n["occasion"])
        self.assertNotIn("evil", n)
        self.assertEqual(bank.normalize({"occasion": {"month": 9, "day": 30, "name": "یلدا"}})["occasion"], {"month": 9, "day": 30, "name": "یلدا"})

    def test_validate_needs_title_and_logline(self):
        with self.assertRaises(bank.BankError):
            bank.validate({"logline": "x"})
        with self.assertRaises(bank.BankError):
            bank.validate({"title": "x"})
        self.assertEqual(bank.validate({"title": "الف", "logline": "ب"})["title"], "الف")


class HookTitleTests(SimpleTestCase):
    def test_hook_becomes_a_short_thumbnail_title(self):
        from .handoff import hook_title

        self.assertEqual(hook_title("اگر مطمئن نیستی، پیش از خرید این را ببین.", "عنوان"), "اگر مطمئن نیستی")
        self.assertEqual(hook_title("کدام را بیشتر دوست داری؟", "عنوان"), "کدام را بیشتر دوست داری؟")        # «؟» می‌ماند
        self.assertEqual(hook_title("", "اشتباهِ رایج دربارهٔ محصول"), "اشتباهِ رایج دربارهٔ محصول")
        long_hook = "این یک قلابِ خیلی خیلی خیلی خیلی خیلی خیلی خیلی خیلی بلند بدونِ هیچ ویرگول است برای آزمون"
        out = hook_title(long_hook, "عنوان")
        self.assertLessEqual(len(out.split()), 10)
        self.assertNotIn(out.split()[-1], ("از", "به", "در", "با", "را", "و", "که"))


class FillTests(TestCase):
    def test_placeholders_come_from_the_profile_and_the_chosen_product(self):
        _, store = make_store()
        StoreProfile.objects.filter(store=store).update(tone="صمیمی ولی حرفه‌ای")
        store = Store.objects.get(pk=store.pk)
        product = Product.objects.create(store=store, name="برنامه‌سازِ هوشمند", price=0)
        ctx = fill.context(store, product)
        self.assertEqual(ctx["values"]["فروشگاه"], "چغر")
        self.assertEqual(ctx["values"]["مخاطب"], "مربی‌های باشگاه و مربی‌های شخصی")
        self.assertEqual(ctx["values"]["حوزه"], "نرم‌افزار و خدمات دیجیتال")                  # حداکثر ۵ واژه و نه روی «برای»
        self.assertEqual(ctx["values"]["محصول"], "برنامه‌سازِ هوشمند")
        self.assertEqual(ctx["tone"], "صمیمی ولی حرفه‌ای")
        self.assertEqual(fill.fill_text("{محصول} برای {مخاطب} از {فروشگاه}", ctx), "برنامه‌سازِ هوشمند برای مربی‌های باشگاه و مربی‌های شخصی از چغر")
        self.assertTrue(all(ctx["known"].values()))

    def test_nothing_is_invented_when_the_profile_is_empty(self):
        _, store = make_store(name="فروشگاهِ خالی", owner="empty", business_type="", target_audience="")
        ctx = fill.context(store)
        self.assertEqual(ctx["values"]["محصول"], fill.FALLBACK["محصول"])
        self.assertEqual(ctx["values"]["مخاطب"], fill.FALLBACK["مخاطب"])
        self.assertFalse(ctx["known"]["مخاطب"] or ctx["known"]["محصول"] or ctx["known"]["حوزه"])
        self.assertEqual(ctx["tone"], "")
        # جای‌گیرِ ناشناخته دست نمی‌خورد
        self.assertEqual(fill.fill_text("{چیز}", ctx), "{چیز}")

    def test_clip_never_ends_on_a_dangling_word(self):
        out = fill.clip_phrase("برنامهٔ ورزشی برای مربی‌های باشگاه و هر", 5, 40)
        self.assertNotIn(out.split(" ")[-1], fill._DANGLING)
        self.assertEqual(fill.audience_phrase("مربی‌ها، ورزشکارها"), "مربی‌ها")


class BankTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store()
        self.ctx = fill.context(self.store)

    def test_list_has_all_seeds_filled_and_sorted_by_category(self):
        rows = bank.list_ideas(self.store, ctx=self.ctx, today=TODAY)
        self.assertEqual(len(rows), len(BUILTIN_IDEAS))
        first = rows[0]
        self.assertNotIn("{", first["filled"]["title"])
        cats = [r["category"] for r in rows]
        order = ["tips", "behind", "product", "faq", "proof", "occasion", "engage", "offer"]
        self.assertEqual([c for i, c in enumerate(cats) if i == 0 or c != cats[i - 1]], order)
        occ = [r for r in rows if r["category"] == "occasion"]
        self.assertEqual([r["occasion_next"]["days"] for r in occ], sorted(r["occasion_next"]["days"] for r in occ))   # نزدیک‌ترین مناسبت اول
        self.assertTrue(all(r["occasion_next"]["days"] >= 0 for r in occ))

    def test_search_filters_and_facets(self):
        r = bank.list_ideas(self.store, q="یلدا", ctx=self.ctx, today=TODAY)
        self.assertTrue(r and r[0]["category"] == "occasion" and "یلدا" in r[0]["occasion"]["name"])
        self.assertTrue(bank.list_ideas(self.store, q="مربيِ", ctx=self.ctx))                 # ي عربی ⇒ همان «مربی»
        self.assertEqual(bank.list_ideas(self.store, q="zzzzqqq", ctx=self.ctx), [])
        multi = bank.list_ideas(self.store, q="قدم‌به‌قدم محصول", ctx=self.ctx)
        self.assertTrue(multi)
        self.assertTrue(all(i["category"] == "faq" for i in bank.list_ideas(self.store, category="faq", ctx=self.ctx)))
        self.assertTrue(all(i["format"] == "story" for i in bank.list_ideas(self.store, fmt="story", ctx=self.ctx)))
        tele = bank.list_ideas(self.store, channel="telegram", ctx=self.ctx)
        self.assertTrue(tele and all(i["channel"] in ("telegram", "both") for i in tele))
        tag = bank.list_ideas(self.store, tag="چک‌لیست", ctx=self.ctx)
        self.assertTrue(tag and all("چک‌لیست" in i["tags"] for i in tag))
        needs = bank.list_ideas(self.store, needs_data=True, ctx=self.ctx)
        self.assertTrue(needs and all(i["slots"] for i in needs))
        self.assertTrue(all(not i["slots"] for i in bank.list_ideas(self.store, needs_data=False, ctx=self.ctx)))
        f = bank.facets(bank.all_ideas(self.store, self.ctx))
        self.assertEqual([c["key"] for c in f["categories"]], ["tips", "behind", "product", "faq", "proof", "occasion", "engage", "offer"])
        self.assertEqual(f["total"], len(BUILTIN_IDEAS))
        self.assertEqual({x["key"] for x in f["formats"]}, {"reel", "carousel", "photo", "story"})
        self.assertGreater(f["needs_data"], 20)

    def test_search_sees_the_filled_text_too(self):
        _, store = make_store(name="گل‌فروشیِ نمونه", owner="gul", business_type="گل و گیاه")
        rows = bank.list_ideas(store, q="گل‌فروشیِ نمونه", ctx=fill.context(store))
        self.assertTrue(rows)                                                              # {فروشگاه} پر شده و جست‌وجو آن را می‌بیند

    def test_marks_are_per_store(self):
        _, other = make_store(name="فروشگاهِ دیگر", owner="other")
        key = "tips_mistake"
        bank.set_mark(self.store, key, favorite=True)
        bank.set_mark(self.store, "tips_howto", hidden=True)
        mine = {i["key"]: i for i in bank.all_ideas(self.store)}
        theirs = {i["key"]: i for i in bank.all_ideas(other)}
        self.assertTrue(mine[key]["favorite"] and mine["tips_howto"]["hidden"])
        self.assertFalse(theirs[key]["favorite"] or theirs["tips_howto"]["hidden"])
        self.assertNotIn("tips_howto", [i["key"] for i in bank.list_ideas(self.store)])
        self.assertIn("tips_howto", [i["key"] for i in bank.list_ideas(self.store, include_hidden=True)])
        self.assertIn("tips_howto", [i["key"] for i in bank.list_ideas(other)])
        self.assertEqual([i["key"] for i in bank.list_ideas(self.store, favorite=True)], [key])
        self.assertEqual(bank.list_ideas(self.store)[0]["key"], key)                       # ستاره‌دارها اول
        bank.set_mark(self.store, key, favorite=False)
        self.assertFalse(bank.get_idea(self.store, key)["favorite"])
        self.assertEqual(IdeaMark.objects.filter(store=other).count(), 0)
        with self.assertRaises(bank.BankError) as cm:
            bank.set_mark(self.store, "no_such_idea", favorite=True)
        self.assertEqual(cm.exception.status, 404)

    def test_own_ideas_crud_and_builtins_are_read_only(self):
        made = bank.create_idea(self.store, {"title": "ایدهٔ من", "logline": "یک توضیح", "category": "engage", "format": "story", "tags": "الف،ب"})
        self.assertTrue(made["key"].startswith("u_") and not made["builtin"] and made["origin"] == "user")
        self.assertEqual(made["tags"], ["الف", "ب"])
        edited = bank.update_idea(self.store, made["key"], {"title": "عنوانِ تازه", "format": "reel"})
        self.assertEqual((edited["title"], edited["format"], edited["logline"]), ("عنوانِ تازه", "reel", "یک توضیح"))
        with self.assertRaises(bank.BankError) as cm:
            bank.update_idea(self.store, "tips_mistake", {"title": "x"})
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(bank.BankError) as cm:
            bank.delete_idea(self.store, "tips_mistake")
        self.assertEqual(cm.exception.status, 409)
        _, other = make_store(name="دیگری", owner="o2")
        self.assertIsNone(bank.get_idea(other, made["key"]))                                # ایدهٔ یک فروشگاه به فروشگاهِ دیگر نمی‌رسد
        with self.assertRaises(bank.BankError):
            bank.update_idea(other, made["key"], {"title": "x"})
        bank.set_mark(self.store, made["key"], favorite=True)
        bank.record_use(self.store, made["key"], "studio")
        bank.delete_idea(self.store, made["key"])
        self.assertFalse(StoreIdea.objects.filter(key=made["key"]).exists() or IdeaMark.objects.filter(key=made["key"]).exists()
                         or IdeaUse.objects.filter(key=made["key"]).exists())
        with self.assertRaises(bank.BankError) as cm:
            bank.delete_idea(self.store, made["key"])
        self.assertEqual(cm.exception.status, 404)

    def test_duplicate_keeps_the_template_and_is_editable(self):
        dup = bank.duplicate_idea(self.store, "product_intro", ctx=self.ctx)
        self.assertEqual((dup["origin"], dup["based_on"]), ("duplicate", "product_intro"))
        self.assertTrue(dup["title"].endswith("(کپی)"))
        self.assertIn("{محصول}", dup["title"])                                               # قالب می‌ماند، پرشده نمی‌شود
        self.assertNotIn("{", dup["filled"]["title"])
        again = bank.duplicate_idea(self.store, "product_intro", {"title": "عنوانِ دیگر"})
        self.assertEqual(again["title"], "عنوانِ دیگر")

    def test_uses_counter(self):
        bank.record_use(self.store, "tips_mistake", "studio")
        bank.record_use(self.store, "tips_mistake", "thumbnail")
        self.assertEqual(bank.get_idea(self.store, "tips_mistake")["uses"], 2)
        _, other = make_store(name="دیگری", owner="o3")
        self.assertEqual(bank.get_idea(other, "tips_mistake")["uses"], 0)

    def test_add_generated_skips_duplicate_titles_and_unfinished_ideas(self):
        items = [{"title": "عنوانِ یکتا", "logline": "توضیح", "category": "tips"}, {"title": "عنوانِ یکتا", "logline": "توضیح"},
                 {"title": "بدونِ توضیح"}, {"title": bank.get_idea(self.store, "tips_howto")["filled"]["title"], "logline": "تکراریِ آماده"}]
        made = bank.add_generated(self.store, items, ctx=self.ctx)
        self.assertEqual([m["title"] for m in made], ["عنوانِ یکتا"])
        self.assertEqual(made[0]["origin"], "generated")

    def test_random_idea(self):
        self.assertTrue(bank.random_idea(self.store))
        r = bank.random_idea(self.store, "offer")
        self.assertEqual(r["category"], "offer")
        self.assertIsNone(bank.random_idea(self.store, "no-such"))

    def test_unsaved_store_has_no_rows_but_still_lists_seeds(self):
        from . import demo

        rows = bank.all_ideas(demo.stand_in(), fill.context(demo.stand_in()))
        self.assertEqual(len(rows), len(BUILTIN_IDEAS))
        self.assertFalse(any(r["favorite"] or r["hidden"] for r in rows))
