from django.core.management.base import BaseCommand, CommandError

from apps.motion import catalog, styleaudit
from apps.stores.models import Store


class Command(BaseCommand):
    help = ("استودیوی موشن: هر سبکِ کاتالوگ را در ۹:۱۶ و ۱۶:۹ با یک طرحِ واقعی رندر و با QA می‌سنجد و برگه‌های تماس می‌سازد (سنگین: زیرِ flock /root/nm-heavy.lock اجرا کنید). "
            "نمونه: manage.py motion_style_audit --store 34 --plan chagher --out /tmp/audit")

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, required=True, help="شناسهٔ فروشگاه (متن، رنگ و لوگوی برند از آن می‌آید)")
        parser.add_argument("--styles", default="all", help="شناسه‌ها با ویرگول، یا all")
        parser.add_argument("--aspects", default="9:16,16:9")
        parser.add_argument("--plan", choices=("chagher", "store"), default="store", help="chagher = جمله‌های تأییدشدهٔ چغر؛ store = متنِ خودِ فروشگاه")
        parser.add_argument("--frames", type=int, choices=(1, 2), default=1, help="۱ = یک فریم برای هر صحنه؛ ۲ = ورود + پایانِ صحنه")
        parser.add_argument("--out", default="", help="پوشهٔ خروجی")
        parser.add_argument("--no-brand", action="store_true", help="با پالتِ خودِ سبک، نه رنگِ برند")
        parser.add_argument("--as-draft", action="store_true", help="سبک را همراهِ طرح (style_def) بفرست: ویرایشِ catalog.py بدونِ ساختنِ دوبارهٔ بسته دیده می‌شود")
        parser.add_argument("--resume", action="store_true", help="سبک/اندازه‌ای که نتیجه دارد را رد کن")
        parser.add_argument("--sheets-only", action="store_true", help="فقط برگه‌ها را از نتیجه‌های موجود بساز")

    def handle(self, *args, **o):
        store = Store.objects.filter(pk=o["store"]).first()
        if store is None:
            raise CommandError("فروشگاه پیدا نشد")
        all_ids = [s["id"] for s in catalog.STYLES]
        ids = all_ids if o["styles"] == "all" else [x for x in o["styles"].split(",") if x]
        bad = [x for x in ids if x not in all_ids]
        if bad:
            raise CommandError("سبکِ ناشناخته: " + ", ".join(bad))
        aspects = [a for a in o["aspects"].split(",") if a]
        out = styleaudit.default_out() if not o["out"] else __import__("pathlib").Path(o["out"])
        self.stdout.write(f"خروجی: {out}")
        if not o["sheets_only"]:
            rows = styleaudit.run(store, ids, aspects, out, plan=o["plan"], frames=o["frames"], brand=not o["no_brand"], as_draft=o["as_draft"], resume=o["resume"], say=self.stdout.write)
            failed = [r for r in rows if r.get("failure")]
            if failed:
                self.stderr.write(f"{len(failed)} سبک رندر نشد: " + ", ".join(f"{r['style']}@{r['aspect']}" for r in failed[:10]))
        made = styleaudit.sheets(out, all_ids if o["styles"] == "all" else ids)
        self.stdout.write(f"برگه‌های تماس: {made}؛ فهرستِ یافته‌ها: {out}/findings.txt")
