"""Articles written in the admin instead of in a git commit.

Three properties carry this, and each of them is a bug the file-based blog
could not have:

**A draft is invisible and a scheduled article stays invisible until its
moment.** The filter lives in one place, because a front-end that forgets it
publishes next week's article today and nobody finds out until a customer says
so.

**The slug does not follow the title.** Somebody fixing a typo in a headline
must not 404 every link to the article — and they would have no idea they did.

**Changing a slug on purpose leaves a redirect behind.** Same failure, taken
deliberately instead of by accident, and the traffic the article was written
for is exactly the traffic that breaks.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Article, Category, Redirect


class SlugTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="بازاریابی")

    def _article(self, title, **kwargs):
        return Article.objects.create(
            title=title, description="x", body="متن",
            category=self.category, **kwargs,
        )

    def test_a_slug_is_made_from_the_title(self):
        self.assertEqual(self._article("سئوی فروشگاه").slug, "سئوی-فروشگاه")

    def test_the_slug_does_not_follow_a_retitle(self):
        """Fixing a typo in a headline must not 404 every link to the article,
        and the person fixing it would never know."""
        article = self._article("سئوی فروشگاه")
        original = article.slug
        article.title = "سئوی فروشگاه اینترنتی"
        article.save()
        self.assertEqual(article.slug, original)

    def test_two_articles_with_the_same_title_get_different_slugs(self):
        first = self._article("راهنما")
        second = self._article("راهنما")
        self.assertNotEqual(first.slug, second.slug)

    def test_a_category_slug_is_made_from_its_name(self):
        self.assertEqual(Category.objects.create(name="تولید محتوا").slug, "تولید-محتوا")


class PublishingTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="بازاریابی")

    def _article(self, **kwargs):
        return Article.objects.create(
            title=kwargs.pop("title", "مقاله"), description="x", body="متن",
            category=self.category, **kwargs,
        )

    def test_publishing_without_a_date_stamps_one(self):
        """An article published with no date is invisible on a page that filters
        by date — which looks exactly like a bug to whoever pressed publish."""
        article = self._article(status=Article.Status.PUBLISHED)
        self.assertIsNotNone(article.published_at)
        self.assertTrue(article.is_live)

    def test_a_future_date_means_scheduled_not_live(self):
        article = self._article(
            status=Article.Status.PUBLISHED,
            published_at=timezone.now() + timedelta(days=2),
        )
        self.assertTrue(article.is_scheduled)
        self.assertFalse(article.is_live)

    def test_a_draft_is_never_live(self):
        self.assertFalse(self._article(status=Article.Status.DRAFT).is_live)

    def test_reading_time_is_at_least_a_minute(self):
        self.assertGreaterEqual(self._article(title="کوتاه").reading_minutes, 1)

    def test_rubbish_tags_are_cleaned_not_rendered(self):
        article = self._article()
        article.tags = ["  سئو  ", "سئو", "", "x" * 200]
        self.assertEqual(len(article.clean_tags), 2)
        self.assertEqual(article.clean_tags[0], "سئو")

    def test_a_category_counts_only_its_live_articles(self):
        """A category page listing three articles under a heading that says five
        is a page that looks broken."""
        self._article(status=Article.Status.PUBLISHED)
        self._article(status=Article.Status.DRAFT)
        self._article(
            status=Article.Status.PUBLISHED,
            published_at=timezone.now() + timedelta(days=1),
        )
        self.assertEqual(self.category.live_count, 1)


class PublicAPITests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="بازاریابی")
        self.live = Article.objects.create(
            title="زنده", description="x", body="# متن", category=self.category,
            status=Article.Status.PUBLISHED, tags=["سئو"],
        )
        Article.objects.create(
            title="پیش‌نویس", description="x", body="متن", category=self.category,
            status=Article.Status.DRAFT,
        )
        Article.objects.create(
            title="آینده", description="x", body="متن", category=self.category,
            status=Article.Status.PUBLISHED,
            published_at=timezone.now() + timedelta(days=3),
        )

    def test_the_list_shows_only_live_articles(self):
        rows = self.client.get("/api/v1/blog/articles/").json()
        self.assertEqual([r["title"] for r in rows], ["زنده"])

    def test_a_draft_is_not_reachable_by_its_slug(self):
        draft = Article.objects.get(title="پیش‌نویس")
        self.assertEqual(
            self.client.get(f"/api/v1/blog/articles/{draft.slug}/").status_code, 404,
        )

    def test_a_scheduled_article_is_not_reachable_yet(self):
        future = Article.objects.get(title="آینده")
        self.assertEqual(
            self.client.get(f"/api/v1/blog/articles/{future.slug}/").status_code, 404,
        )

    def test_the_detail_carries_the_markdown_body(self):
        body = self.client.get(f"/api/v1/blog/articles/{self.live.slug}/").json()
        self.assertEqual(body["body"], "# متن")

    def test_the_list_does_not_carry_bodies(self):
        """Seven articles' worth of Markdown on an index page is bytes nobody
        reads."""
        rows = self.client.get("/api/v1/blog/articles/").json()
        self.assertNotIn("body", rows[0])

    def test_filtering_by_category(self):
        other = Category.objects.create(name="فروش")
        Article.objects.create(
            title="دیگر", description="x", body="متن", category=other,
            status=Article.Status.PUBLISHED,
        )
        rows = self.client.get(
            f"/api/v1/blog/articles/?category={other.slug}",
        ).json()
        self.assertEqual([r["title"] for r in rows], ["دیگر"])

    def test_filtering_by_tag(self):
        rows = self.client.get("/api/v1/blog/articles/?tag=سئو").json()
        self.assertEqual(len(rows), 1)

    def test_empty_categories_are_not_listed(self):
        """An empty category page in the sitemap is a 404 Google has already
        indexed."""
        Category.objects.create(name="خالی")
        names = [c["name"] for c in self.client.get("/api/v1/blog/categories/").json()]
        self.assertNotIn("خالی", names)

    def test_the_public_blog_needs_no_login(self):
        """Requiring auth would mean the site holding a credential it has no
        other use for — which is a credential that leaks."""
        for path in ("/api/v1/blog/articles/", "/api/v1/blog/categories/",
                     "/api/v1/blog/redirects/"):
            self.assertEqual(self.client.get(path).status_code, 200, path)


class RedirectTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            "cms-staff", "s@x.ir", "x" * 12,
        )
        self.client.force_login(self.staff)
        self.category = Category.objects.create(name="بازاریابی")
        self.article = Article.objects.create(
            title="مقاله", description="x", body="متن", category=self.category,
            status=Article.Status.PUBLISHED,
        )

    def test_changing_a_slug_in_the_admin_leaves_a_redirect(self):
        """Otherwise every link anyone shared, and every result Google indexed,
        404s — and the person who changed it has no idea."""
        self.client.post(
            f"/admin/cms/article/{self.article.pk}/change/",
            {
                "title": self.article.title,
                "slug": "آدرس-تازه",
                "description": "x",
                "body": "متن",
                "category": self.category.pk,
                "tags": "[]",
                "author": "تیم",
                "status": Article.Status.PUBLISHED,
                "published_at_0": "2026-01-01",
                "published_at_1": "10:00:00",
                "display_date": "",
            },
            follow=True,
        )
        self.article.refresh_from_db()
        self.assertEqual(self.article.slug, "آدرس-تازه")
        self.assertTrue(Redirect.objects.filter(new_path="/blog/آدرس-تازه").exists())

    def test_redirects_are_served_to_the_site(self):
        Redirect.objects.create(old_path="/blog/قدیم", new_path="/blog/جدید")
        self.client.logout()
        rows = self.client.get("/api/v1/blog/redirects/").json()
        self.assertEqual(rows, [{"from": "/blog/قدیم", "to": "/blog/جدید"}])


class ImportTests(TestCase):
    def test_front_matter_parses_without_a_yaml_library(self):
        from apps.cms.management.commands.import_articles import parse

        meta, body = parse(
            "---\n"
            "title: سلام\n"
            "category: بازاریابی\n"
            "tags: [سئو, فروش]\n"
            "---\n"
            "متن مقاله\n"
        )
        self.assertEqual(meta["title"], "سلام")
        self.assertEqual(meta["tags"], ["سئو", "فروش"])
        self.assertEqual(body, "متن مقاله")

    def test_a_file_with_no_front_matter_is_all_body(self):
        from apps.cms.management.commands.import_articles import parse

        meta, body = parse("فقط متن")
        self.assertEqual(meta, {})
        self.assertEqual(body, "فقط متن")


class TagFilterPortabilityTests(TestCase):
    """The bug that only shows up on one database.

    `tags__contains=[tag]` is the obvious spelling and only works on
    PostgreSQL — on SQLite it raises. And the obvious fix, `icontains`, matches
    nothing on SQLite for Persian, because Django writes JSON with
    `ensure_ascii=True` and «سئو» is stored as `\u0633\u0626\u0648`.

    So this is a filter that works in production and fails in development, or
    the reverse, depending on which one you wrote it against.
    """

    def setUp(self):
        self.category = Category.objects.create(name="بازاریابی")
        self.tagged = Article.objects.create(
            title="با برچسب", description="x", body="متن", category=self.category,
            status=Article.Status.PUBLISHED, tags=["سئو", "فروش"],
        )
        Article.objects.create(
            title="بدون برچسب", description="x", body="متن", category=self.category,
            status=Article.Status.PUBLISHED, tags=["دیگر"],
        )

    def test_a_persian_tag_matches_on_this_database(self):
        rows = self.client.get("/api/v1/blog/articles/?tag=سئو").json()
        self.assertEqual([r["title"] for r in rows], ["با برچسب"])

    def test_a_prefix_of_a_tag_does_not_match_it(self):
        """«سئو» must not match «سئوکار» — the LIKE narrows, Python decides."""
        Article.objects.create(
            title="شبیه", description="x", body="متن", category=self.category,
            status=Article.Status.PUBLISHED, tags=["سئوکار"],
        )
        rows = self.client.get("/api/v1/blog/articles/?tag=سئو").json()
        self.assertEqual([r["title"] for r in rows], ["با برچسب"])

    def test_an_unknown_tag_matches_nothing(self):
        self.assertEqual(self.client.get("/api/v1/blog/articles/?tag=هیچ").json(), [])

    def test_an_empty_tag_filters_nothing_out(self):
        rows = self.client.get("/api/v1/blog/articles/?tag=").json()
        self.assertEqual(len(rows), 2)

    def test_an_ascii_tag_works_too(self):
        self.tagged.tags = ["seo"]
        self.tagged.save()
        rows = self.client.get("/api/v1/blog/articles/?tag=seo").json()
        self.assertEqual(len(rows), 1)
