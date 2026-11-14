"""python manage.py node_readiness [--node NAME] [--json]

«آمادگیِ صبحِ مالک»: بسته، آینهٔ فایل‌ها، تنظیمِ دانلود، خودکارها، آزمون‌ها، هر گره و صفِ منتظر را فقط می‌خواند و گزارش می‌دهد.
خروجیِ ۰ = هیچ ردیفِ «fail» نیست؛ ۱ = دست‌کم یک fail. هیچ‌چیز را عوض نمی‌کند و به گره دستوری نمی‌فرستد."""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.compute import readiness
from apps.compute.models import ComputeNode

MARK = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]", "info": "[info]"}


class Command(BaseCommand):
    help = "Read-only report: is everything ready for the GPU node to be switched on (package, mirror files, automations, tests, queue)?"

    def add_arguments(self, parser):
        parser.add_argument("--node", default="", help="only this node (name)")
        parser.add_argument("--json", action="store_true", help="print the report as JSON")

    def handle(self, *args, **opts):
        node = None
        if opts["node"]:
            node = ComputeNode.objects.filter(name=opts["node"]).first()
            if node is None:
                raise CommandError("no node named %r" % opts["node"])
        rep = readiness.report(node)
        if opts["json"]:
            self.stdout.write(json.dumps(rep, ensure_ascii=False, indent=1))
        else:
            for row in rep["checks"]:
                self.stdout.write("%s %s%s — %s" % (MARK.get(row["state"], "[?]   "), ("%s: " % row["node"]) if row.get("node") else "", row["label"], row["detail"]))
            self.stdout.write("\n%s  (%s)" % ("READY" if rep["ok"] else "NOT READY", ", ".join("%s %d" % kv for kv in sorted(rep["summary"].items()))))
        if not rep["ok"]:
            raise SystemExit(1)
