"""`manage.py benchmark` — the phase 0.5 report, from measured rows.

Phase 0.5's DoD asks for four things: a report with real numbers, `data.json`
`render` replaced and its `source` changed from `owner` to `measured`, the
capacity model carrying LLM and swap time, and the customer-facing "چند دقیقه"
claim replaced with a real figure.

This command produces the first and prints the exact JSON for the second, so
the numbers move from the machine that measured them into the file that plans
the business without anyone retyping a decimal point.

    python manage.py benchmark                  # report
    python manage.py benchmark --json           # the data.json render block
    python manage.py benchmark --kind VIDEO_SEGMENT

It reports what has been measured. On a machine with no GPU that is nothing,
and it says so rather than printing zeros that look like findings.
"""
import json

from django.core.management.base import BaseCommand

from apps.jobs.metrics import RenderMetric, summarise
from services import hardware


class Command(BaseCommand):
    help = "گزارش زمان واقعی رندر از روی اندازه‌گیری‌های ثبت‌شده (فاز ۰.۵)"

    def add_arguments(self, parser):
        parser.add_argument("--kind", default=None, help="فقط یک نوع: VIDEO_SEGMENT، IMAGE، …")
        parser.add_argument("--hardware", default=None, help="فقط یک ماشین")
        parser.add_argument(
            "--json", action="store_true",
            help="بلوک render برای دیتا/0-منبع/data.json را چاپ کن",
        )

    def handle(self, *args, **options):
        rows = summarise(kind=options["kind"], hardware=options["hardware"])

        if not rows:
            self.stdout.write(self.style.WARNING(
                "هیچ اندازه‌گیری‌ای ثبت نشده است.\n\n"
                "این طبیعی است تا وقتی رندر واقعی روی سیستمی با کارت گرافیک اجرا شود.\n"
                "هر قطعه‌ی ویدیو که تولید شود، خودش اینجا ثبت می‌شود — لازم نیست\n"
                "کسی چیزی یادداشت کند."
            ))
            self.stdout.write(f"\nاین ماشین: {hardware.fingerprint()}")
            profile = hardware.profile()
            if not profile["has_gpu"]:
                self.stdout.write(self.style.WARNING(
                    "کارت گرافیک NVIDIA پیدا نشد، پس بنچمارک اینجا اجرا نمی‌شود."
                ))
            return

        if options["json"]:
            self.stdout.write(json.dumps(self._data_json_block(rows), ensure_ascii=False, indent=2))
            return

        self._report(rows)

    # ------------------------------------------------------------------

    def _report(self, rows):
        profile = hardware.profile()
        self.stdout.write(self.style.MIGRATE_HEADING("سخت‌افزار"))
        self.stdout.write(f"  {profile['fingerprint']}")
        for card in profile["gpus"]:
            self.stdout.write(
                f"  GPU {card['index']}: {card['name']} · "
                f"{card['vram_total_mb']} MB · {card['temperature_c']}°C"
            )
        if profile["ram_total_mb"]:
            self.stdout.write(f"  RAM: {profile['ram_total_mb']} MB")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("اندازه‌گیری‌ها"))
        for row in rows:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"  {row['kind']} · {row['engine']}"))
            self.stdout.write(f"    ماشین          : {row['hardware']}")
            self.stdout.write(
                f"    اجرا           : {row['runs']} بار، "
                f"{row['succeeded']} موفق ({(row['success_rate'] or 0) * 100:.0f}٪)"
            )
            if row["minutes_per_unit_median"] is not None:
                self.stdout.write(
                    f"    دقیقه بر واحد  : کمینه {row['minutes_per_unit_min']} · "
                    f"میانه {row['minutes_per_unit_median']} · "
                    f"بیشینه {row['minutes_per_unit_max']}"
                )
            if row["effective_minutes_per_unit"] is not None:
                self.stdout.write(self.style.WARNING(
                    f"    هزینه‌ی واقعی   : {row['effective_minutes_per_unit']} دقیقه "
                    "بر هر واحد قابل‌استفاده (با شکست‌ها)"
                ))
            if row["load_s_median"] is not None:
                self.stdout.write(f"    بار کردن مدل   : میانه {row['load_s_median']} ثانیه")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("چرا «هزینه‌ی واقعی» عدد مهم‌تری است"))
        self.stdout.write(
            "  خطی که ۴ دقیقه طول می‌کشد ولی یک‌سوم مواقع شکست می‌خورد، در عمل\n"
            "  ۶ دقیقه برای هر خروجی قابل‌استفاده هزینه دارد. مدل ظرفیت باید\n"
            "  همین عدد را بگیرد، نه میانه‌ی موفق‌ها را."
        )

        video = [r for r in rows if r["kind"] == RenderMetric.Kind.VIDEO_SEGMENT]
        if video:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING("قدم بعدی"))
            self.stdout.write(
                "  python manage.py benchmark --json\n"
                "  و خروجی را در دیتا/0-منبع/data.json بخش render بگذار.\n"
                "  یادت باشد source را از owner به measured عوض کنی."
            )

    def _data_json_block(self, rows) -> dict:
        """The `render` block for data.json, in the shape that file uses."""
        video = [r for r in rows if r["kind"] == RenderMetric.Kind.VIDEO_SEGMENT]
        block: dict = {
            "source": "measured",
            "measured_on": [r["hardware"] for r in video] or [hardware.fingerprint()],
        }
        if video:
            best = min(r["minutes_per_unit_min"] or 0 for r in video)
            median = sorted(r["minutes_per_unit_median"] or 0 for r in video)[len(video) // 2]
            worst = max(r["minutes_per_unit_max"] or 0 for r in video)
            effective = [r["effective_minutes_per_unit"] for r in video if r["effective_minutes_per_unit"]]
            block["video_gpu_min_per_second_range"] = {
                "fast": round(best, 2),
                "typical": round(median, 2),
                "slow": round(worst, 2),
            }
            if effective:
                block["video_gpu_min_per_second_effective"] = round(max(effective), 2)
                block["_note_effective"] = (
                    "این عدد شکست‌ها را هم حساب می‌کند — همان که مدل ظرفیت باید بگیرد."
                )
            block["runs"] = sum(r["runs"] for r in video)
            block["success_rate"] = min(r["success_rate"] or 0 for r in video)

        swap = [r for r in rows if r["kind"] == RenderMetric.Kind.MODEL_SWAP]
        if swap:
            block["model_swap_seconds"] = max(r["minutes_per_unit_median"] or 0 for r in swap) * 60

        llm = [r for r in rows if r["kind"] in (RenderMetric.Kind.TEXT, RenderMetric.Kind.VISION)]
        if llm:
            block["llm_seconds_median"] = round(
                max((r["minutes_per_unit_median"] or 0) * 60 for r in llm), 1
            )
        return block
