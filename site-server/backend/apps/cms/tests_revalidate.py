"""Saving something the public site shows must tell the public site.

The bug this guards: an edit in the Django admin appeared on the site up to
two minutes later, so the person who made it refreshed, saw the old text and
reported that the site was not connected to the admin at all.

`captureOnCommitCallbacks` is not decoration — the ping is deliberately fired
`on_commit`, and a test that does not run those callbacks would pass whether
the wiring existed or not.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.billing.models import Plan

from .models import Article, Category, ShowcaseItem, SiteSettings

WIRED = {
    "WEBSITE_URL": "http://testsite.invalid",
    "WEBSITE_REVALIDATE_SECRET": "s3cret",
}


@override_settings(UPMARKET_AI=WIRED)
class RevalidatePingTests(TestCase):
    """`_post` is the last step before the network, so it is what to watch."""

    def setUp(self):
        self.category = Category.objects.create(name="دسته", slug="daste")

    def an_article(self, slug="post-1"):
        return Article.objects.create(
            title="نوشته", slug=slug, description="یک جمله",
            body="متن", category=self.category,
        )

    def pings_for(self, action) -> list[list[str]]:
        """The tag lists handed to the sender while `action` ran."""
        with patch("apps.cms.revalidate._post") as post:
            with self.captureOnCommitCallbacks(execute=True):
                action()
        return [call.args[2] for call in post.call_args_list]

    def test_saving_an_article_refreshes_the_blog(self):
        self.assertIn(["articles"], self.pings_for(self.an_article))

    def test_saving_a_category_refreshes_the_list_and_its_posts(self):
        sent = self.pings_for(
            lambda: Category.objects.create(name="تازه", slug="taze")
        )
        self.assertIn(["articles", "categories"], sent)

    def test_changing_a_price_refreshes_the_pricing_page(self):
        sent = self.pings_for(
            lambda: Plan.objects.create(name="پایه", slug="basic", price_toman=1000)
        )
        self.assertIn(["plans"], sent)

    def test_site_settings_and_showcase_have_their_own_tags(self):
        self.assertIn(
            ["settings"], self.pings_for(lambda: SiteSettings.objects.create())
        )
        self.assertIn(
            ["showcase"],
            self.pings_for(
                lambda: ShowcaseItem.objects.create(
                    slug="nemune", category="پوشاک", product="تی‌شرت"
                )
            ),
        )

    def test_deleting_counts_too(self):
        article = self.an_article(slug="gone")
        self.assertIn(["articles"], self.pings_for(article.delete))

    @override_settings(UPMARKET_AI={"WEBSITE_URL": "", "WEBSITE_REVALIDATE_SECRET": ""})
    def test_nothing_is_sent_when_the_site_is_not_wired_up(self):
        """No key is not an error — the site still catches up on its own."""
        self.assertEqual(self.pings_for(lambda: self.an_article("b")), [])

    def test_a_dead_website_never_breaks_a_save(self):
        import requests

        with patch("requests.post", side_effect=requests.ConnectionError("no route")):
            with self.captureOnCommitCallbacks(execute=True):
                article = self.an_article("p")
        self.assertTrue(Article.objects.filter(pk=article.pk).exists())
