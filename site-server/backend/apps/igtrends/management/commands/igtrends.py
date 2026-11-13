"""python manage.py igtrends import <store_id> file.json [file2.json ...]   - Abagram «abagram-page» export(s)
   python manage.py igtrends rebuild <store_id>                          - rescore + rebuild the topic clusters
   python manage.py igtrends scan <store_id>                             - queue a node scan now
   python manage.py igtrends status                                      - what the node reports
"""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.igtrends import dispatch, engine, ingest, normalize, status
from apps.igtrends.models import IgAccount
from apps.stores.models import Store


class Command(BaseCommand):
    help = "Instagram trends: import / rebuild / scan / status"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["import", "rebuild", "scan", "status"])
        parser.add_argument("store_id", nargs="?", type=int)
        parser.add_argument("files", nargs="*")

    def handle(self, *args, action, store_id, files, **opts):
        if action == "status":
            st = status.node_status()
            self.stdout.write(json.dumps({"ready": st["ready"], "problem": st["problem"], "message": st["message"]}, ensure_ascii=False, indent=1))
            return
        if not store_id:
            raise CommandError("store_id لازم است")
        store = Store.objects.filter(pk=store_id).first()
        if store is None:
            raise CommandError("فروشگاه پیدا نشد")
        if action == "import":
            batches = []
            for path in files:
                with open(path, encoding="utf-8-sig") as fh:
                    batches.append(normalize.from_abagram_page(json.load(fh)))
            out = ingest.apply_batch(store, normalize.merge_batches(batches))
            self.stdout.write("accounts=%(accounts)s posts=%(posts)s new=%(new)s updated=%(updated)s" % out)
        elif action == "rebuild":
            engine.rescore_accounts(IgAccount.objects.all())
            self.stdout.write(str(engine.rebuild_store(store)))
        elif action == "scan":
            try:
                run = dispatch.request_scan(store)
            except dispatch.ScanRefused as exc:
                raise CommandError(str(exc))
            self.stdout.write("run %s queued: %s" % (run.pk, ", ".join(run.accounts)))
