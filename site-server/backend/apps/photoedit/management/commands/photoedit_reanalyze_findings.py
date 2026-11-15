"""هشدارهای «کیفیتِ عکس» را برای عکس‌های موجودِ کتابخانه دوباره حساب می‌کند (بازبینیِ ۱۴ آبان).

قبلاً همهٔ اسلایدهای طراحی‌شده (زمینهٔ تختِ سرمه‌ای با متنِ درشتِ سفید) برچسبِ «تیره / کم‌کنتراست» می‌خوردند، چون عکس فرض
می‌شدند. حالا ``ops.measure`` طرحِ گرافیکی را می‌شناسد (facts["graphic"]) و ``ops.findings`` برایش هشدارِ عکس نمی‌دهد.
این دستور اصلِ هر عکس را می‌خواند، همان اندازه‌گیری را دوباره انجام می‌دهد و فقط اگر چیزی عوض شده باشد ذخیره می‌کند.

    manage.py photoedit_reanalyze_findings --dry-run     # فقط بشمار، چیزی ننویس
    manage.py photoedit_reanalyze_findings               # ذخیره (ایدمپوتنت؛ بارِ دوم هیچ‌چیز عوض نمی‌کند)
    manage.py photoedit_reanalyze_findings --store 34    # فقط یک فروشگاه

فقط ``facts["graphic"]`` و ``findings`` عوض می‌شوند؛ فایل‌ها، نسخه‌ها و تحلیلِ کیت دست‌نخورده می‌مانند.
"""
from django.core.management.base import BaseCommand

from apps.photoedit import ops, services
from apps.photoedit.models import PhotoAsset


class Command(BaseCommand):
    help = "هشدارهای کیفیتِ عکسِ کتابخانه را با تشخیصِ «طرحِ گرافیکی» دوباره حساب می‌کند."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش بده، چیزی ننویس")
        parser.add_argument("--store", type=int, default=0, help="فقط عکس‌های این فروشگاه")

    def handle(self, *args, **opts):
        dry = bool(opts.get("dry_run"))
        qs = PhotoAsset.objects.order_by("pk")
        if opts.get("store"):
            qs = qs.filter(store_id=opts["store"])
        total = changed = graphic = missing = failed = cleared = 0
        for a in qs.iterator():
            total += 1
            path = services.abs_path(a.original) if a.original and a.original != "-" else None
            if path is None or not path.is_file():
                missing += 1
                continue
            try:
                img = ops.load(path)
                facts = dict(a.facts or {})
                facts.update(ops.measure(img))      # اندازه‌ها همان‌اند؛ فقط «graphic» تازه است
            except Exception as exc:  # noqa: BLE001 — یک فایلِ خراب بقیه را متوقف نکند
                failed += 1
                self.stdout.write(self.style.WARNING(f"  عکس {a.pk}: خوانده نشد — {exc}"))
                continue
            new = ops.findings(facts)
            if facts.get("graphic"):
                graphic += 1
            if new == (a.findings or []) and bool(facts.get("graphic")) == bool((a.facts or {}).get("graphic")):
                continue
            changed += 1
            cleared += max(0, len(a.findings or []) - len(new))
            self.stdout.write(f"  عکس {a.pk} «{(a.title or '')[:40]}»: {len(a.findings or [])} ⇐ {len(new)} هشدار"
                              f"{' (طرحِ گرافیکی)' if facts.get('graphic') else ''}")
            if not dry:
                a.facts, a.findings = facts, new
                a.save(update_fields=["facts", "findings", "updated_at"])
        self.stdout.write(self.style.SUCCESS(
            f"{'[آزمایشی] ' if dry else ''}کل {total}، طرحِ گرافیکی {graphic}، تغییر{' می‌کند' if dry else ' کرد'} {changed}، "
            f"هشدارِ برداشته‌شده {cleared}، بی‌فایل {missing}، خراب {failed}."))
