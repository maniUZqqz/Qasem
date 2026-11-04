from django.test import TestCase

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.core.testing import NoNetworkMixin
from apps.growth_engine.leads.services.editing import ValidationFailed
from apps.growth_engine.outreach.models import MessageTemplate
from apps.growth_engine.outreach.services import generators, rendering, templates

from .helpers import IDENTITY, configure, make_lead, make_template

CLOSING = "علی رضایی | آپ‌مارکت\n0912 123 4567 · ali@upmarket.ir\n\nاگر مایل به دریافت پیام نیستید، پاسخ دهید «لغو»."


class PlaceholderTests(NoNetworkMixin, TestCase):
    def test_values_come_only_from_the_lead(self):
        lead = make_lead("shop-a.ir", name="گل‌سرخ", city="شیراز", category="گل", instagram="@golsorkh", country="ایران")
        v = rendering.lead_values(lead)
        self.assertEqual((v["business_name"], v["city"], v["country"], v["category"]), ("گل‌سرخ", "شیراز", "ایران", "گل"))
        self.assertEqual((v["domain"], v["instagram"], v["website"]), ("shop-a.ir", "@golsorkh", "https://shop-a.ir"))

    def test_an_unknown_value_is_empty_with_a_warning_never_invented(self):
        lead = make_lead(None, name="بی‌شهر", city="", form=False)
        result = rendering.render("سلام {business_name} از {city}", rendering.lead_values(lead))
        self.assertEqual(result.text, "سلام بی‌شهر از")
        self.assertEqual(result.warnings, ["«شهر» برای این لید خالی است و در متن جا افتاد."])

    def test_author_written_fallback(self):
        lead = make_lead(None, name="بی‌شهر", city="", form=False)
        result = rendering.render("برای {city|شهر شما} پیشنهاد داریم", rendering.lead_values(lead))
        self.assertEqual((result.text, result.warnings), ("برای شهر شما پیشنهاد داریم", []))

    def test_unknown_placeholders_are_found_and_left_alone(self):
        self.assertEqual(rendering.unknown_placeholders("{city} {foo} {bar|x} {foo}", "{baz}"), ["foo", "bar", "baz"])
        result = rendering.render("سلام {foo}", {})
        self.assertEqual((result.text, result.unknown), ("سلام {foo}", ["foo"]))
        self.assertTrue(any("foo" in w for w in result.warnings))

    def test_blank_runs_are_tidied(self):
        result = rendering.render("الف  {city}   ب\n\n{city}\nج", {"city": ""})
        self.assertEqual(result.text, "الف ب\n\n\nج")


class ClosingBlockTests(NoNetworkMixin, TestCase):
    def test_sender_block_and_opt_out_line(self):
        configure()
        built = generators.build_message(make_template(body="سلام {business_name}", subject="موضوع"), make_lead(None, name="گل", form=False), GrowthSettings.load())
        self.assertEqual(built.text, "سلام گل\n\n" + CLOSING)
        self.assertEqual(built.subject, "موضوع")

    def test_only_the_filled_parts_appear(self):
        configure(sender_phone="", sender_website="")
        text = rendering.closing_block(GrowthSettings.load())
        self.assertEqual(text, "علی رضایی | آپ‌مارکت\nali@upmarket.ir\n\nاگر مایل به دریافت پیام نیستید، پاسخ دهید «لغو».")

    def test_a_generator_cannot_drop_the_identity_or_the_opt_out_line(self):
        class Rude:
            name, label = "rude", "x"

            def generate(self, template, lead):
                return generators.Generated(body="فقط یک جمله، بدونِ امضا")

        generators.register(Rude())
        try:
            configure()
            template = make_template(generator="rude")
            built = generators.build_message(template, make_lead(None, form=False), GrowthSettings.load())
        finally:
            generators._REGISTRY.pop("rude", None)
        self.assertEqual(built.text, "فقط یک جمله، بدونِ امضا\n\n" + CLOSING)

    def test_unknown_generator_falls_back_to_the_placeholder_one(self):
        self.assertEqual(generators.get("no-such-writer").name, "placeholder")
        self.assertIn("placeholder", generators.names())


class TemplateTests(NoNetworkMixin, TestCase):
    def test_validation(self):
        for bad, field in [({"name": "", "body": "x"}, "name"), ({"name": "n", "body": " "}, "body"), ({"name": "n", "body": "{nope}"}, "body"),
                           ({"name": "n", "body": "x", "subject": "{nope2}"}, "body"), ({"name": "n", "body": "x", "language": "de"}, "language"),
                           ({"name": "n", "body": "x", "generator": "ai"}, "generator"), ({"name": "n", "body": "x" * 4000}, "body")]:
            with self.subTest(bad=bad), self.assertRaises(ValidationFailed) as ctx:
                templates.create(bad)
            self.assertEqual(ctx.exception.errors[0]["field"], field)
        self.assertEqual(MessageTemplate.objects.count(), 0)

    def test_create_update_and_a_used_template_is_archived_not_deleted(self):
        template = templates.create({"name": " معرفی ", "body": "سلام {business_name}", "subject": "س"})
        self.assertEqual(template.name, "معرفی")
        templates.update(template, {"body": "درود {business_name}", "is_active": False})
        template.refresh_from_db()
        self.assertEqual((template.body, template.is_active), ("درود {business_name}", False))
        with self.assertRaises(ValidationFailed):
            templates.update(template, {"body": "{bad}"})
        from .helpers import make_campaign

        used = make_template(name="مصرف‌شده")
        make_campaign(used)
        with self.assertRaises(ValidationFailed) as ctx:
            templates.delete(used)
        self.assertEqual(ctx.exception.errors[0]["code"], "in_use")
        templates.delete(template)
        self.assertFalse(MessageTemplate.objects.filter(pk=template.pk).exists())

    def test_preview_without_a_lead_shows_markers_not_invented_text(self):
        configure()
        out = templates.preview("سلام {business_name} از {city}", "موضوع {city}")
        self.assertIn("سلام ‹نامِ کسب‌وکار› از ‹شهر›", out["text"])
        self.assertTrue(out["text"].endswith("«لغو»."))
        self.assertEqual((out["subject"], out["warnings"], out["unknown_placeholders"]), ("موضوع ‹شهر›", [], []))

    def test_preview_with_a_lead_warns_about_missing_values_and_unknown_placeholders(self):
        configure()
        lead = make_lead(None, name="گل", city="", form=False)
        out = templates.preview("سلام {business_name} از {city} {zzz}", "", lead)
        self.assertTrue(out["text"].startswith("سلام گل از {zzz}"))
        self.assertEqual(out["unknown_placeholders"], ["zzz"])
        self.assertTrue(any("شهر" in w for w in out["warnings"]))

    def test_the_identity_in_a_preview_is_the_real_one(self):
        configure()
        self.assertIn(IDENTITY["sender_name"], templates.preview("x", "")["text"])
