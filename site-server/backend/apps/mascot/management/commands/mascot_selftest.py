"""خودآزمونِ قطعیِ ماسکوت (فقط پردازنده): همهٔ ژست‌ها × ۴ اندازه؛ کدِ خروج ۱ اگر چیزی رد شد.

    python manage.py mascot_selftest [--min-px 0.45] [--poses stand,wave]
"""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.mascot import selftest
from apps.mascot.engine import poses


class Command(BaseCommand):
    help = "همهٔ ژست‌های ماسکوت × چهار اندازه را می‌کشد و رنگ‌های امضا را می‌سنجد (بدونِ دیتابیس، GPU و هوش مصنوعی)."

    def add_arguments(self, parser):
        parser.add_argument("--min-px", type=float, default=selftest.MIN_PX)
        parser.add_argument("--poses", default="")

    def handle(self, *args, **o):
        plist = [p for p in o["poses"].split(",") if p] or None
        if plist and any(p not in poses.POSES for p in plist):
            raise CommandError("ژستِ ناشناخته.")
        res = selftest.run(pose_list=plist, min_px=max(0.3, min(1.0, o["min_px"])))
        self.stdout.write(json.dumps({k: res[k] for k in ("ok", "total", "passed", "poses", "sizes", "seconds")}, ensure_ascii=False))
        for f in res["failed"][:10]:
            self.stdout.write(f"  رد: {f['pose']} / {f['size']}: {'؛ '.join(f['notes'])}")
        if not res["ok"]:
            raise CommandError("بررسیِ ثباتِ ماسکوت رد شد.")
