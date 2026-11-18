"""سندِ «راهنمای آزمونِ بخش‌ها» را از ``apps/mktplan/guide.py`` می‌سازد.

    python manage.py mktplan_guide_md --out ../docs/chagher/test-guide-fa.md --store 34
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from apps.mktplan import guide
from apps.stores.models import Store


class Command(BaseCommand):
    help = "نوشتنِ docs/chagher/test-guide-fa.md از دادهٔ راهنما"

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True)
        parser.add_argument("--store", type=int, default=0)

    def handle(self, *args, **o):
        store = Store.objects.filter(pk=o["store"]).first() if o["store"] else None
        text = guide.render_markdown(store.name if store else "فروشگاه", store.pk if store else None)
        out = Path(o["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        self.stdout.write(f"{out} ({len(text)} نویسه، {len(guide.GUIDE)} بخش)")
