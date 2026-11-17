"""Clean up what earlier runs of the finder left behind (wrong-city leads, filler / personal contact values, city spellings).

    python manage.py crawl_repair              # a dry run: only says what it would do
    python manage.py crawl_repair --apply      # does it

Only leads the finder made are deleted, and only when nobody has worked on them (see ``services/repair.py``). Nothing is sent anywhere.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.growth_engine.crawler.services import repair


class Command(BaseCommand):
    help = "Repair the leads of earlier finder runs (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="write the changes (default: only report)")
        parser.add_argument("--limit", type=int, help="look at the first N leads only")

    def handle(self, *args, **opts):
        out = repair.run(apply=bool(opts["apply"]), limit=opts.get("limit"))
        self.stdout.write(("APPLIED" if out["applied"] else "DRY RUN") + "\n" + json.dumps(out, ensure_ascii=False, indent=2))
