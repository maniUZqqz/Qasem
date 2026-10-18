"""Create the sellable plans, matching the pitch deck's data.json.

    python manage.py seed_plans

Safe to re-run: plans are matched by slug and updated in place, so editing a
price here does not orphan the subscriptions pointing at it.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.billing.models import Plan

# دیتا/1-داده/data.json — the pitch deck's single source of truth
DATA = Path(__file__).resolve().parents[7] / "دیتا" / "0-منبع" / "data.json"

FALLBACK = [
    {"id": "start", "name": "استارت", "price": 690000, "video_sec": 15, "posters": 5, "captions": 5},
    {"id": "pro", "name": "حرفه‌ای", "price": 1490000, "video_sec": 45, "posters": 15, "captions": 15},
    {"id": "unlimited", "name": "بی‌نهایت", "price": 3490000, "video_sec": 120, "posters": 40, "captions": 40},
]

TRIAL = {
    "slug": "trial", "name": "دوره آزمایشی", "price_toman": 0,
    "description": "دو هفته رایگان — بدون کارت بانکی",
    "video_seconds": 15, "images": 5, "captions": 5,
    "is_trial": True, "trial_days": 14, "is_public": False, "sort_order": 0,
    "max_products": 10, "allows_publishing": False, "allows_sales_agent": True,
}


class Command(BaseCommand):
    help = "پلن‌های فروش را از data.json می‌سازد یا به‌روز می‌کند"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DATA), help="مسیر data.json")

    def handle(self, *args, **options):
        packages = self._packages(Path(options["file"]))

        plan, created = Plan.objects.update_or_create(slug=TRIAL["slug"], defaults=TRIAL)
        self.stdout.write(f"  {'+' if created else '~'} {plan.name}")

        for order, pkg in enumerate(packages, start=1):
            plan, created = Plan.objects.update_or_create(
                slug=pkg["id"],
                defaults={
                    "name": pkg["name"],
                    "price_toman": pkg["price"],
                    "video_seconds": pkg["video_sec"],
                    "images": pkg["posters"],
                    "captions": pkg["captions"],
                    "sort_order": order,
                    "is_public": True,
                    "is_trial": False,
                    "max_products": 0,
                    "allows_publishing": True,
                    "allows_sales_agent": True,
                    "description": (
                        f"{pkg['video_sec']} ثانیه ویدیو · {pkg['posters']} تصویر · "
                        f"{pkg['captions']} کپشن در ماه"
                    ),
                },
            )
            self.stdout.write(f"  {'+' if created else '~'} {plan.name} — {plan.price_toman:,}")

        self.stdout.write(self.style.SUCCESS(f"{Plan.objects.count()} پلن آماده است."))

    def _packages(self, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            packages = data["packages"]
            self.stdout.write(f"از {path.name} خوانده شد.")
            return packages
        except Exception as exc:  # noqa: BLE001 — the deck may not be shipped
            self.stdout.write(
                self.style.WARNING(f"data.json خوانده نشد ({exc}); از مقادیر پیش‌فرض استفاده می‌شود.")
            )
            return FALLBACK
