"""Keeping the Markdown fallback honest. §2 (website)

The site falls back to `content/blog/*.md` when the backend cannot be reached
at build time, which is the right call — a blog is SEO surface, and shipping
yesterday's articles beats shipping an empty section.

But a fallback nobody refreshes stops being a fallback and becomes a fossil.
The files were written once by the import; the moment an article is edited in
the admin they disagree with the database, and a build with a sick backend then
quietly ships **stale content as though it were current**. That is worse than
shipping nothing, because nothing is visible and stale is not.

So the properties that matter are: the export round-trips faithfully, the check
actually detects drift (a checker that always says "fine" is worse than none),
and **nothing unpublished ever reaches the disk** — a file on disk is a file
the site will publish the moment the backend is unreachable, so an article
scheduled for Saturday must not go out on Thursday because the API was down.
"""
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .models import Article, Category


class ExportTests(TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.folder = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)
        self.category = Category.objects.create(name="بازاریابی")

    def _article(self, **kwargs):
        kwargs.setdefault("title", "مقاله")
        kwargs.setdefault("description", "توضیح")
        kwargs.setdefault("body", "متن مقاله")
        kwargs.setdefault("status", Article.Status.PUBLISHED)
        return Article.objects.create(category=self.category, **kwargs)

    def _export(self, **options):
        call_command("export_articles", path=str(self.folder), **options)

    def _files(self):
        return sorted(f.name for f in self.folder.glob("*.md"))

    # ------------------------------------------------------------ writing

    def test_a_published_article_is_written(self):
        article = self._article()
        self._export()
        self.assertEqual(self._files(), [f"{article.slug}.md"])

    def test_the_body_survives_the_round_trip(self):
        article = self._article(body="# تیتر\n\nپاراگراف اول.")
        self._export()
        written = (self.folder / f"{article.slug}.md").read_text(encoding="utf-8")
        self.assertIn("# تیتر", written)
        self.assertIn("پاراگراف اول.", written)

    def test_the_front_matter_is_what_the_importer_reads_back(self):
        """Export and import have to agree, or the fallback renders with no
        title and no category."""
        from apps.cms.management.commands.import_articles import parse

        article = self._article(
            title="سئوی فروشگاه", tags=["سئو", "فروش"], author="مهدی",
            display_date="۱۴۰۴/۰۶/۱۵",
        )
        self._export()
        meta, body = parse(
            (self.folder / f"{article.slug}.md").read_text(encoding="utf-8")
        )
        self.assertEqual(meta["title"], "سئوی فروشگاه")
        self.assertEqual(meta["category"], "بازاریابی")
        self.assertEqual(meta["tags"], ["سئو", "فروش"])
        self.assertEqual(meta["author"], "مهدی")
        self.assertEqual(meta["date"], "۱۴۰۴/۰۶/۱۵")
        self.assertEqual(body, "متن مقاله")

    def test_exporting_twice_changes_nothing_the_second_time(self):
        """If it did, every deploy would show a diff nobody made."""
        self._article()
        self._export()
        first = (self.folder / self._files()[0]).read_text(encoding="utf-8")
        self._export()
        self.assertEqual(
            (self.folder / self._files()[0]).read_text(encoding="utf-8"), first,
        )

    # ------------------------------------------------- what must not leak

    def test_a_draft_never_reaches_the_disk(self):
        """A file on disk is a file the site publishes the moment the backend
        is unreachable."""
        self._article(title="پیش‌نویس", status=Article.Status.DRAFT)
        self._export()
        self.assertEqual(self._files(), [])

    def test_a_scheduled_article_never_reaches_the_disk(self):
        """Saturday's article must not go out on Thursday because the API
        happened to be down."""
        self._article(
            title="شنبه", published_at=timezone.now() + timedelta(days=3),
        )
        self._export()
        self.assertEqual(self._files(), [])

    def test_an_archived_article_never_reaches_the_disk(self):
        self._article(title="بایگانی", status=Article.Status.ARCHIVED)
        self._export()
        self.assertEqual(self._files(), [])

    # -------------------------------------------------------------- check

    def test_the_check_passes_when_the_files_match(self):
        self._article()
        self._export()
        self._export(check=True)  # must not raise

    def test_the_check_catches_an_edited_article(self):
        """A checker that always says "fine" is worse than no checker."""
        article = self._article()
        self._export()
        article.title = "عنوان تازه"
        article.save()
        with self.assertRaises(SystemExit):
            self._export(check=True)

    def test_the_check_catches_a_new_article(self):
        self._article()
        self._export()
        self._article(title="مقاله‌ی دوم")
        with self.assertRaises(SystemExit):
            self._export(check=True)

    def test_the_check_catches_a_file_with_no_article_behind_it(self):
        """An article that was published once and then pulled would otherwise
        keep going out whenever the backend is unreachable."""
        self._article()
        self._export()
        Article.objects.all().delete()
        with self.assertRaises(SystemExit):
            self._export(check=True)

    def test_the_check_writes_nothing_even_when_it_finds_drift(self):
        """Reporting a problem and fixing it are separate commands, so a CI
        run that only checks cannot leave a modified tree behind."""
        self._article()
        with self.assertRaises(SystemExit):
            self._export(check=True)
        self.assertEqual(self._files(), [])

    # -------------------------------------------------------------- prune

    def test_pruning_removes_a_file_whose_article_is_gone(self):
        article = self._article()
        self._export()
        Article.objects.filter(pk=article.pk).delete()
        self._export(prune=True)
        self.assertEqual(self._files(), [])

    def test_without_prune_an_orphan_is_left_alone(self):
        """Deleting somebody's file is not something a plain export should do
        on its own."""
        article = self._article()
        self._export()
        Article.objects.filter(pk=article.pk).delete()
        self._export()
        self.assertEqual(self._files(), [f"{article.slug}.md"])

    def test_an_empty_database_writes_nothing_and_does_not_crash(self):
        self._export()
        self.assertEqual(self._files(), [])
