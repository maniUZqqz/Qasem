"""The automatic edit's acceptance run on the GPU node (see services/editing/selftest_autoedit.py).

    manage.py autoedit_selftest                  all three checks (render_mix, asr, matte)
    manage.py autoedit_selftest --only render_mix,asr
    manage.py autoedit_selftest --json           the full result as JSON

Exit code: 0 passed · 1 failed · 2 waiting (no processing server online: ask again later).
"""
import json

from django.core.management.base import BaseCommand

from services.editing import selftest_autoedit


class Command(BaseCommand):
    help = "Run the automatic edit's node acceptance checks (a render with the right mix, speech recognition, background removal)."

    def add_arguments(self, parser):
        parser.add_argument("--only", default="", help="comma separated: " + ", ".join(selftest_autoedit.CHECKS))
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **opts):
        only = [x.strip() for x in str(opts["only"]).split(",") if x.strip()]
        result = selftest_autoedit.run(only or None)
        if opts["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=1, default=str))
        else:
            self.stdout.write(f"{selftest_autoedit.KEY}: {result['state']}" + (f" (node {result['node']})" if result.get("node") else ""))
            if result.get("message"):
                self.stdout.write("  " + result["message"])
            for name, res in result["checks"].items():
                mark = {True: "PASS", False: "FAIL", None: "skip"}[res.get("ok")]
                self.stdout.write(f"  [{mark}] {name}")
                for row in res.get("checks", []):
                    self.stdout.write(f"        {'ok ' if row['ok'] else ('-- ' if row['ok'] is None else 'BAD')} {row['key']}: {row['detail']}")
        raise SystemExit({"passed": 0, "failed": 1, "waiting": 2}[result["state"]])
