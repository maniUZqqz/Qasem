"""The public site's content, once it stopped being a TypeScript constant.

Four things are worth a test, and each of them is a bug that shipped:

**Tags are typed as words, not as JSON.** `Article.tags` is a `JSONField`, so
the admin demanded `["a", "b"]` — brackets, quotes and commas — in a
right-to-left box, and refused to save the whole article over a stray bracket.

**The showcase shows one video.** Five five-second files rendered as five
players is a picture of our rendering architecture, not of our work.

**An empty field in the admin does not blank the site.** Somebody who fills in
a phone number and leaves Instagram empty must not lose the Instagram link.

**Nothing here needs a login.** It is the public site.
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .forms import ArticleForm
from .models import (
    CaseStudy,
    Category,
    CustomerLogo,
    FaqItem,
    Resource,
    SeoBullet,
    SeoPage,
    SeoStep,
    ShowcaseItem,
    ShowcaseSegment,
    SiteSettings,
    Testimonial,
)


class TagsFieldTests(TestCase):
    """Nobody writing a blog post should be typing JSON."""

    def setUp(self):
        self.category = Category.objects.create(name="بازاریابی")

    def form(self, tags: str) -> ArticleForm:
        return ArticleForm(data={
            "title": "مقاله", "slug": "", "description": "یک جمله",
            "body": "متن", "author": "تیم", "category": self.category.pk,
            "tags": tags, "status": "DRAFT", "display_date": "",
        })

    def test_comma_separated_words_become_a_list(self):
        form = self.form("سئو، اینستاگرام، فروش")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["tags"], ["سئو", "اینستاگرام", "فروش"],
        )

    def test_english_comma_works_too(self):
        # A Persian keyboard gives «،» and an English one «,». The person
        # typing should not have to know which one the form wants.
        form = self.form("seo, instagram")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["tags"], ["seo", "instagram"])

    def test_empty_is_allowed(self):
        form = self.form("")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["tags"], [])

    def test_duplicates_and_blanks_are_dropped(self):
        form = self.form("سئو، ، سئو،  فروش  ")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["tags"], ["سئو", "فروش"])

    def test_a_stray_bracket_no_longer_fails_the_article(self):
        """The old JSON widget rejected this and lost the whole form."""
        form = self.form("سئو]")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["tags"], ["سئو]"])

    def test_existing_rows_render_as_words(self):
        field = ArticleForm().fields["tags"]
        self.assertEqual(field.prepare_value(["سئو", "فروش"]), "سئو، فروش")


class AdminFormTests(TestCase):
    """The admin page itself, because the bug was in the admin."""

    def setUp(self):
        self.category = Category.objects.create(name="بازاریابی")
        User.objects.create_superuser("admin", "a@b.ir", "pw12345678")
        self.client.login(username="admin", password="pw12345678")

    def test_add_page_has_no_json_textarea_for_tags(self):
        res = self.client.get("/admin/cms/article/add/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        # A JSONField renders as <textarea name="tags">; a word list does not.
        self.assertNotIn('<textarea name="tags"', html)
        self.assertIn('name="tags"', html)


class SiteSettingsTests(TestCase):
    def test_only_one_row_can_exist(self):
        SiteSettings.objects.create(name="یک")
        SiteSettings.objects.create(name="دو")
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(SiteSettings.load().name, "دو")

    def test_load_creates_it(self):
        SiteSettings.objects.all().delete()
        self.assertTrue(SiteSettings.load().pk)

    def test_keywords_split_on_either_comma(self):
        self.assertEqual(SiteSettings.split("a, b ,c"), ["a", "b", "c"])
        self.assertEqual(SiteSettings.split("الف، ب، ج"), ["الف", "ب", "ج"])
        self.assertEqual(SiteSettings.split(""), [])

    def test_endpoint_needs_no_login(self):
        SiteSettings.load()
        res = self.client.get(reverse("site-settings"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("name", res.json())

    def test_empty_fields_come_back_empty_so_the_site_can_fall_back(self):
        row = SiteSettings.load()
        row.instagram = ""
        row.save()
        self.assertEqual(self.client.get(reverse("site-settings")).json()["instagram"], "")


class ShowcaseTests(TestCase):
    def setUp(self):
        self.item = ShowcaseItem.objects.create(
            slug="decor", category="دکوراسیون", product="آباژور", featured=True,
        )

    def test_one_video_field_not_a_list(self):
        res = self.client.get(reverse("site-showcase"))
        self.assertEqual(res.status_code, 200)
        row = res.json()[0]
        self.assertIn("video", row)
        self.assertNotIn("videos", row)

    def test_segment_count_is_reported(self):
        for n in (1, 2, 3):
            ShowcaseSegment.objects.create(
                item=self.item, order=n,
                clip=SimpleUploadedFile(f"s{n}.mp4", b"x"),
            )
        self.assertEqual(self.client.get(reverse("site-showcase")).json()[0]["segmentCount"], 3)

    def test_unpublished_items_are_invisible(self):
        self.item.published = False
        self.item.save()
        self.assertEqual(self.client.get(reverse("site-showcase")).json(), [])

    def test_only_one_item_is_featured(self):
        other = ShowcaseItem.objects.create(
            slug="apparel", category="پوشاک", product="کت", featured=True,
        )
        self.item.refresh_from_db()
        self.assertTrue(other.featured)
        self.assertFalse(self.item.featured)

    def test_media_urls_are_absolute(self):
        """A relative /media/… resolves against the Next.js host, where nothing
        is served — a broken image on the page whose job is proving it is real."""
        self.item.image = SimpleUploadedFile("p.png", b"x")
        self.item.save()
        url = self.client.get(reverse("site-showcase")).json()[0]["image"]
        self.assertTrue(url.startswith("http"), url)


class FaqTests(TestCase):
    def setUp(self):
        FaqItem.objects.create(
            group=FaqItem.Group.PRICING, question="چند؟", answer="اینقدر", on_home=True,
        )
        FaqItem.objects.create(
            group=FaqItem.Group.SECURITY, question="امن؟", answer="بله",
        )
        FaqItem.objects.create(
            group=FaqItem.Group.PRODUCT, question="مخفی", answer="-", published=False,
        )

    def test_unpublished_is_invisible(self):
        rows = self.client.get(reverse("site-faq")).json()
        self.assertEqual(len(rows), 2)

    def test_home_filter(self):
        rows = self.client.get(reverse("site-faq"), {"home": "1"}).json()
        self.assertEqual([r["q"] for r in rows], ["چند؟"])

    def test_group_label_comes_back_readable(self):
        rows = self.client.get(reverse("site-faq")).json()
        self.assertEqual(rows[0]["groupLabel"], "قیمت")

    def test_english_falls_back_to_persian_when_untranslated(self):
        rows = self.client.get(reverse("site-faq")).json()
        self.assertEqual(rows[0]["qEn"], "چند؟")


class SeoPageTests(TestCase):
    """Marketing pages written in the admin instead of deployed.

    The endpoint is deliberately dumb — the merge is the site's job. What has
    to hold here is that a page carries enough to render: its sections grouped
    the way the page renders them, and a meta description even when nobody
    wrote one.
    """

    def setUp(self):
        self.page = SeoPage.objects.create(
            kind=SeoPage.Kind.SOLUTION,
            slug="pet-shops",
            locale="fa",
            title="پت‌شاپ",
            lead="محتوای روزانه برای پت‌شاپ",
        )

    def test_unpublished_is_invisible(self):
        self.page.published = False
        self.page.save()
        self.assertEqual(self.client.get(reverse("site-pages")).json(), [])

    def test_filtered_by_kind_and_locale(self):
        SeoPage.objects.create(
            kind=SeoPage.Kind.COMPARE, slug="x", locale="fa", title="مقایسه",
        )
        rows = self.client.get(reverse("site-pages"), {"kind": "solution"}).json()
        self.assertEqual([r["slug"] for r in rows], ["pet-shops"])
        rows = self.client.get(reverse("site-pages"), {"locale": "en"}).json()
        self.assertEqual(rows, [])

    def test_bullets_come_back_grouped(self):
        SeoBullet.objects.create(page=self.page, group="PROBLEM", order=1, text="الف")
        SeoBullet.objects.create(page=self.page, group="PROBLEM", order=2, text="ب")
        SeoBullet.objects.create(page=self.page, group="OUTPUT", order=1, text="ج")
        bullets = self.client.get(reverse("site-pages")).json()[0]["bullets"]
        self.assertEqual(bullets["PROBLEM"], ["الف", "ب"])
        self.assertEqual(bullets["OUTPUT"], ["ج"])

    def test_steps_keep_their_order_and_soon_flag(self):
        SeoStep.objects.create(page=self.page, order=2, title="دوم")
        SeoStep.objects.create(page=self.page, order=1, title="اول", soon=True)
        steps = self.client.get(reverse("site-pages")).json()[0]["steps"]
        self.assertEqual([s["title"] for s in steps], ["اول", "دوم"])
        self.assertTrue(steps[0]["soon"])

    def test_meta_description_falls_back_to_the_lead(self):
        """A page with no description is a page Google writes a snippet for."""
        row = self.client.get(reverse("site-pages")).json()[0]
        self.assertEqual(row["metaDescription"], "محتوای روزانه برای پت‌شاپ")

    def test_example_is_null_when_neither_half_was_written(self):
        self.assertIsNone(self.client.get(reverse("site-pages")).json()[0]["example"])

    def test_one_page_per_slug_per_language(self):
        with self.assertRaises(IntegrityError):
            SeoPage.objects.create(
                kind=SeoPage.Kind.SOLUTION, slug="pet-shops", locale="fa", title="دوباره",
            )

    def test_same_slug_in_the_other_language_is_fine(self):
        SeoPage.objects.create(
            kind=SeoPage.Kind.SOLUTION, slug="pet-shops", locale="en", title="Pet shops",
        )
        self.assertEqual(SeoPage.objects.count(), 2)

    def test_endpoint_needs_no_login(self):
        self.assertEqual(self.client.get(reverse("site-pages")).status_code, 200)


class ProofTests(TestCase):
    """§11–§13. The consent filter is the point.

    A logo or a quote is a public claim about somebody else's business. Putting
    the filter in the API rather than the site means a front-end that forgets
    it cannot publish one anyway — and nobody finds out from the customer.
    """

    def setUp(self):
        self.customer = CustomerLogo.objects.create(name="فروشگاه الف", consented=True)
        self.case = CaseStudy.objects.create(
            customer=self.customer, title="سه برابر پست در ماه",
            problem="وقت نداشتند", published=True,
        )

    def body(self) -> dict:
        return self.client.get(reverse("site-proof")).json()

    def test_everything_is_empty_before_anything_is_written(self):
        CaseStudy.objects.all().delete()
        CustomerLogo.objects.all().delete()
        body = self.body()
        self.assertEqual(body["caseStudies"], [])
        self.assertEqual(body["customers"], [])
        self.assertEqual(body["testimonials"], [])

    def test_a_customer_without_consent_is_invisible(self):
        self.customer.consented = False
        self.customer.save()
        self.assertEqual(self.body()["customers"], [])

    def test_a_quote_without_consent_is_invisible(self):
        Testimonial.objects.create(quote="خوب بود", name="مهدی", consented=False)
        self.assertEqual(self.body()["testimonials"], [])

    def test_an_unpublished_case_study_is_invisible(self):
        self.case.published = False
        self.case.save()
        self.assertEqual(self.body()["caseStudies"], [])

    def test_a_case_study_carries_the_spec_sections(self):
        row = self.body()["caseStudies"][0]
        for field in ("problem", "before", "solution", "process",
                      "outputs", "results", "conclusion"):
            self.assertIn(field, row)

    def test_customer_name_falls_back_when_there_is_no_customer_row(self):
        case = CaseStudy.objects.create(
            title="بدون ردیف مشتری", customer_name="فروشگاه ب",
            problem="…", published=True,
        )
        self.assertEqual(case.who, "فروشگاه ب")

    def test_a_customer_only_links_to_a_published_study(self):
        self.assertEqual(self.body()["customers"][0]["caseStudy"], self.case.slug)
        self.case.published = False
        self.case.save()
        self.assertIsNone(self.body()["customers"][0]["caseStudy"])

    def test_a_case_study_only_carries_consented_quotes(self):
        Testimonial.objects.create(
            quote="بله", name="الف", case_study=self.case, consented=True,
        )
        Testimonial.objects.create(
            quote="خیر", name="ب", case_study=self.case, consented=False,
        )
        quotes = self.body()["caseStudies"][0]["testimonials"]
        self.assertEqual([q["quote"] for q in quotes], ["بله"])

    def test_slug_is_generated_and_stays_unique(self):
        second = CaseStudy.objects.create(title=self.case.title, problem="…")
        self.assertNotEqual(second.slug, self.case.slug)


class ResourceTests(TestCase):
    def setUp(self):
        Resource.objects.create(
            kind=Resource.Kind.TEMPLATE, title="قالب برنامه‌ی بازاریابی",
            description="یک صفحه", published=True,
        )
        Resource.objects.create(
            kind=Resource.Kind.GUIDE, title="پیش‌نویس", description="-",
        )

    def test_unpublished_is_invisible(self):
        rows = self.client.get(reverse("site-resources")).json()["resources"]
        self.assertEqual([r["title"] for r in rows], ["قالب برنامه‌ی بازاریابی"])

    def test_filtered_by_kind(self):
        rows = self.client.get(
            reverse("site-resources"), {"kind": "guides"},
        ).json()["resources"]
        self.assertEqual(rows, [])

    def test_the_four_sections_the_spec_names(self):
        kinds = self.client.get(reverse("site-resources")).json()["kinds"]
        self.assertEqual(
            [k["value"] for k in kinds],
            ["guides", "templates", "checklists", "ebooks"],
        )
