"""Write the database's articles back out as Markdown, so the fallback is real.

The public site reads the blog from the API and falls back to `content/blog/*.md`
when the backend cannot be reached at build time. That fallback is the right
call — the blog is SEO surface, and a build that publishes yesterday's articles
beats one that publishes an empty section.

But a fallback that is never refreshed stops being a fallback and becomes a
fossil. The files were written once by `import_articles`; the moment an article
is edited or added in the admin they disagree with the database, and then a
build with a sick backend quietly ships **stale content as though it were
current** — which is worse than shipping nothing, because nothing is visible
and stale is not.

So: run this before a deploy, and the files on disk are the articles that were
live when you ran it. That is a fallback somebody can reason about.

    python manage.py export_articles
    python manage.py export_articles --check     # CI: fail if they have drifted

Scheduled and draft articles are deliberately not written. A file on disk is a
file the site will publish the moment the backend is unreachable, and an
article scheduled for Saturday must not go out on Thursday because the API
happened to be down.
"""
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.cms.models import Article


def front_matter(article: Article) -> str:
    """The same four flat keys `import_articles` reads back.

    Written by hand rather than with a YAML library, for the same reason the
    importer parses it by hand: it is four keys and a list, and a round-trip
    through a parser is more code and more ways to differ.
    """
    tags = ", ".join(article.clean_tags)
    lines = [
        "---",
        f"title: {article.title}",
        f"description: {article.description}",
        f"date: {article.display_date}",
        f"author: {article.author}",
        f"category: {article.category.name}",
        f"tags: [{tags}]",
    ]
    if article.cover:
        lines.append(f"cover: {article.cover.url}")
    lines.append("---")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Write published articles to website/content/blog/ as Markdown."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(
                Path(__file__).resolve().parents[5] / "website" / "content" / "blog"
            ),
        )
        parser.add_argument(
            "--check", action="store_true",
            help="Change nothing; exit non-zero if the files have drifted.",
        )
        parser.add_argument(
            "--prune", action="store_true",
            help="Also delete files for articles that are no longer published.",
        )

    def handle(self, *args, **options):
        folder = Path(options["path"])
        if not options["check"]:
            folder.mkdir(parents=True, exist_ok=True)
        elif not folder.exists():
            self.stderr.write(f"پوشه پیدا نشد: {folder}")
            return

        live = Article.objects.filter(
            status=Article.Status.PUBLISHED, published_at__lte=timezone.now(),
        ).select_related("category")

        written = unchanged = drifted = 0
        seen = set()

        for article in live:
            target = folder / f"{article.slug}.md"
            seen.add(target.name)
            body = f"{front_matter(article)}\n\n{article.body.strip()}\n"

            current = (
                target.read_text(encoding="utf-8") if target.exists() else None
            )
            if current == body:
                unchanged += 1
                continue

            drifted += 1
            if options["check"]:
                what = "تازه است" if current is None else "فرق دارد"
                self.stdout.write(f"  ≠ {article.slug} ({what})")
                continue

            target.write_text(body, encoding="utf-8")
            written += 1
            self.stdout.write(f"  → {article.slug}")

        # Files with no live article behind them. A draft that was published
        # once and then pulled would otherwise keep going out whenever the
        # backend is unreachable.
        orphans = [
            f for f in folder.glob("*.md") if f.name not in seen
        ] if folder.exists() else []
        for orphan in orphans:
            if options["check"]:
                self.stdout.write(f"  ✗ {orphan.stem} (دیگر منتشر نیست)")
            elif options["prune"]:
                orphan.unlink()
                self.stdout.write(f"  ✗ {orphan.stem} حذف شد")

        if options["check"]:
            if drifted or orphans:
                self.stderr.write(self.style.ERROR(
                    f"\nفایل‌های وبلاگ با دیتابیس هم‌خوان نیستند "
                    f"({drifted} تفاوت، {len(orphans)} اضافه). "
                    "`python manage.py export_articles` را بزنید."
                ))
                raise SystemExit(1)
            self.stdout.write(self.style.SUCCESS(
                f"هم‌خوان است — {unchanged} مقاله."
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"\n{written} نوشته شد، {unchanged} بدون تغییر بود."
        ))
        if orphans and not options["prune"]:
            self.stdout.write(
                f"{len(orphans)} فایل دیگر پشتش مقاله‌ی منتشرشده‌ای نیست. "
                "برای حذفشان: --prune"
            )
        self.stdout.write(
            "\nاین فایل‌ها فقط وقتی استفاده می‌شوند که بک‌اند موقع بیلد سایت "
            "در دسترس نباشد. قبل از هر دیپلوی یک بار این دستور را بزنید تا "
            "نسخه‌ی پشتیبان کهنه نباشد."
        )
