"""دورِ دومِ آزمونِ چغر: پیش‌نویسِ بی‌هوش‌مصنوعیِ «حالتِ هوش مصنوعی» از ایدهٔ فارسیِ واقعی.

ایدهٔ واقعی: «معرفیِ چغر برای مربی‌های باشگاه؛ سه مزیت: …، …، و کتابخانهٔ بیش از ۱۳۰۰ حرکت. در پایان دعوت به ثبت‌نام.»
پیش‌تر: یک بندِ فهرست وسطِ «بیش از» بریده می‌شد، جملهٔ دستوریِ «در پایان دعوت به ثبت‌نام» روی صفحه می‌آمد و پیامِ خطا دوبار تکرار و ناتمام بود.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from . import ai, services, specs

IDEA = ("معرفیِ چغر برای مربی‌های باشگاه؛ سه مزیت: پیش‌نویسِ برنامهٔ ورزشی و غذایی در کمتر از یک دقیقه، خروجیِ PDF برندشده، "
        "و کتابخانهٔ بیش از ۱۳۰۰ حرکت. در پایان دعوت به ثبت‌نام.")


class RulesDraftTests(SimpleTestCase):
    def test_real_chagher_idea_becomes_title_list_and_cta(self):
        sc = ai.rules_scenes(IDEA)
        self.assertEqual([s["type"] for s in sc], ["title", "list", "cta"])
        self.assertEqual(sc[0]["title"], "معرفیِ چغر برای مربی‌های باشگاه")
        self.assertEqual(sc[1]["title"], "سه مزیت")
        self.assertEqual(sc[1]["items"], ["پیش‌نویسِ برنامهٔ ورزشی و غذایی در کمتر از یک دقیقه", "خروجیِ PDF برندشده", "کتابخانهٔ بیش از ۱۳۰۰ حرکت"])
        self.assertEqual((sc[2]["title"], sc[2]["button"]), ("همین حالا ثبت‌نام کنید", "ثبت‌نام"))
        specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "scenes": sc})          # معتبر است

    def test_no_item_ends_on_a_dangling_word_and_no_instruction_reaches_the_screen(self):
        for idea in (IDEA, "سه مزیت: " + "، ".join(["کتابخانهٔ بیش از ۱۳۰۰ حرکت با نامِ فارسی و گیف و عکس برای هر ورزشکار و مربی"] * 3)):
            for s in ai.rules_scenes(idea):
                for item in s.get("items", []):
                    self.assertFalse(item.split()[-1] in ("از", "و", "با", "برای", "بیش"), item)
                self.assertNotIn("در پایان", s.get("title", ""))
                self.assertNotIn("دعوت به", s.get("title", ""))

    def test_numbered_steps_without_commas_before_and(self):
        sc = ai.rules_scenes("چهار قدم تا اولین برنامه: ثبت‌نام، خریدِ توکن، واردکردنِ اطلاعاتِ مجموعه و تولیدِ برنامه.")
        self.assertEqual(sc[0]["title"], "چهار قدم تا اولین برنامه")
        self.assertEqual(sc[1]["items"], ["ثبت‌نام", "خریدِ توکن", "واردکردنِ اطلاعاتِ مجموعه", "تولیدِ برنامه"])

    def test_compound_with_and_is_not_split(self):
        sc = ai.rules_scenes("سه مزیت: برنامهٔ ورزشی و غذایی، خروجیِ PDF، کتابخانهٔ حرکت‌ها")
        lst = next(x for x in sc if x["type"] == "list")
        self.assertEqual(lst["items"][0], "برنامهٔ ورزشی و غذایی")

    def test_english_idea(self):
        sc = ai.rules_scenes("Intro to the app; three benefits: fast plans, branded PDF, and a big move library. At the end invite to sign up.", "en")
        self.assertEqual(sc[1]["items"], ["fast plans", "branded PDF", "a big move library"])
        self.assertEqual(sc[2]["button"], "Sign up")

    def test_plain_one_liner_still_works(self):
        sc = ai.rules_scenes("یک ویدیوی کوتاه از چغر")
        self.assertEqual([s["type"] for s in sc], ["title", "cta"])


class ReasonTests(SimpleTestCase):
    def test_unavailable_message_is_short_and_not_repeated(self):
        from services.ai.priority import Failure
        from services.ai.routing import AllProvidersFailed

        exc = AllProvidersFailed(
            "هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — لوکال: سرورِ پردازش خاموش است.؛ متیس: سیاستِ داده‌ی این فروشگاه اجازه‌ی فرستادنِ این داده به "
            "سرویسِ بیرونی (متیس) را نمی‌دهد. (کلیدِ پیش‌فرض .env) " * 2,
            failures={"local": Failure("offline", "سرورِ پردازش خاموش است.", provider="local"),
                      "metis": Failure("policy", "سیاستِ داده‌ی این فروشگاه اجازه‌ی فرستادنِ این داده را نمی‌دهد.", provider="metis")})

        class Store:
            name, description = "چغر", ""

        class Prov:
            def generate(self, *a, **k):
                raise exc

        out = ai.script_from_idea(Store(), IDEA, style="flat-vector", provider=Prov(), brand={})
        self.assertEqual(out["source"], "rules")
        self.assertLess(len(out["message"]), 330, out["message"])
        self.assertEqual(out["message"].count("متیس"), 1, out["message"])
        self.assertNotIn("(کلیدِ پیش", out["message"])
        self.assertEqual([s["type"] for s in out["spec"]["scenes"]], ["title", "list", "cta"])


class BrandDefaultsTests(SimpleTestCase):
    STORE = SimpleNamespace(name="چغر", colors={"primary": "#126F85", "secondary": "#163F75", "soft": "#DBE6FF"}, logo=None)

    def test_missing_brand_takes_the_shops_colours_and_name(self):
        b = services.brand_with_defaults(self.STORE, {"use_brand_colors": True, "show_logo": True, "colors": []})
        self.assertEqual(b["colors"], ["#126F85", "#163F75", "#DBE6FF"])
        self.assertEqual(b["name"], "چغر")
        self.assertNotIn("logo", b)                       # فروشگاهِ بی‌لوگو: چیزی ساخته نمی‌شود

    def test_explicit_choices_stay(self):
        mine = services.brand_with_defaults(self.STORE, {"colors": ["#112233"], "name": "نام من"})
        self.assertEqual((mine["colors"], mine["name"]), (["#112233"], "نام من"))
        off = services.brand_with_defaults(self.STORE, {"use_brand_colors": False, "colors": []})
        self.assertEqual(off["colors"], [])
        self.assertEqual(services.brand_with_defaults(self.STORE, None)["name"], "چغر")
