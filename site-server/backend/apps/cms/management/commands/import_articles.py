"""Move the Markdown articles into the database, once.

The files stay where they are. This is deliberately not a delete: if the import
gets something wrong — a mangled front-matter date, a category that did not
exist — the originals are still there to re-run against. Deleting them is a
separate decision for after the site is confirmed reading from the database.

Idempotent by slug, so running it twice is safe and running it again after
writing a new file imports only the new one.
"""
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.cms.models import Article, Category


def parse(text: str) -> tuple[dict, str]:
    """Front matter and body, without a YAML dependency.

    The front matter here is four flat keys and a bracket list. Pulling in a
    parser for that would be more code than this, and this cannot fail on
    somebody's clever YAML because it does not support any.
    """
    if not text.startswith("---"):
        return {}, text
    _, _, rest = text.partition("---\n")
    front, _, body = rest.partition("---\n")

    meta = {}
    for line in front.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key] = value
    return meta, body.strip()


class Command(BaseCommand):
    help = "Import content/blog/*.md into the database. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(Path(__file__).resolve().parents[5] / "website" / "content" / "blog"),
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Say what would happen and change nothing.",
        )

    def handle(self, *args, **options):
        folder = Path(options["path"])
        if not folder.exists():
            self.stderr.write(f"پوشه پیدا نشد: {folder}")
            return

        files = sorted(folder.glob("*.md"))
        if not files:
            self.stdout.write("هیچ فایل مارک‌داونی پیدا نشد.")
            return

        made = skipped = 0
        for path in files:
            meta, body = parse(path.read_text(encoding="utf-8"))
            slug = path.stem

            if Article.objects.filter(slug=slug).exists():
                skipped += 1
                self.stdout.write(f"  = {slug} (از قبل هست)")
                continue

            name = meta.get("category") or "عمومی"
            category, _ = Category.objects.get_or_create(name=name)

            if options["dry_run"]:
                self.stdout.write(f"  + {slug} → {name}")
                made += 1
                continue

            Article.objects.create(
                slug=slug,
                title=meta.get("title", slug),
                description=meta.get("description", ""),
                body=body,
                author=meta.get("author", "تیم آپ‌مارکت"),
                category=category,
                tags=meta.get("tags", []),
                status=Article.Status.PUBLISHED,
                published_at=timezone.now(),
                # The Persian date as the author wrote it. Converting it
                # properly needs a calendar library, and a wrong date is worse
                # than the one they typed.
                display_date=meta.get("date", ""),
            )
            made += 1
            self.stdout.write(f"  + {slug} → {name}")

        verb = "منتقل می‌شوند" if options["dry_run"] else "منتقل شدند"
        self.stdout.write(self.style.SUCCESS(
            f"\n{made} مقاله {verb}، {skipped} از قبل بود."
        ))
        if not options["dry_run"] and made:
            self.stdout.write(
                "فایل‌های مارک‌داون پاک نشدند — تا وقتی مطمئن شوی سایت از "
                "دیتابیس درست می‌خواند، همان‌جا بمانند."
            )
