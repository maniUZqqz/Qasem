"""Give a shop's music library its starter tracks now (the automatic edit does the same by itself the first time it needs music).

    manage.py seed_starter_music --store 34            the six starter tracks (if the library has no ready music) + real tracks asked from the node
    manage.py seed_starter_music --store 34 --no-node  only the starter tracks
    manage.py seed_starter_music --all                 every shop that has uploaded a video
    manage.py seed_starter_music --store 34 --dry-run  only say what would happen

Safe to run again: a library that already has ready music is left alone (nothing is replaced or duplicated).  The tracks are composed and
synthesised by the site itself (services/audio/starter_music.py), so they carry no third-party licence.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.ai.models import AudioAsset
from apps.content.models import UploadedVideo
from apps.stores.models import Store
from services.audio import starter_music


class Command(BaseCommand):
    help = "Add the site's own starter background-music tracks to a shop's audio library (and queue real tracks on the processing node)."

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, action="append", default=[], help="a store id (repeatable)")
        parser.add_argument("--all", action="store_true", help="every store that has uploaded a video")
        parser.add_argument("--no-node", action="store_true", help="do not ask the processing node for generated tracks")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        ids = list(opts["store"])
        if opts["all"]:
            ids += list(UploadedVideo.objects.values_list("store_id", flat=True).distinct())
        ids = sorted(set(ids))
        if not ids:
            raise CommandError("say which shop: --store ID (repeatable) or --all")
        if not starter_music.enabled():
            self.stdout.write("AUTOEDIT_STARTER_MUSIC is off: nothing to do")
            return
        for store in Store.objects.filter(pk__in=ids).order_by("pk"):
            ready = AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY).count()
            if opts["dry_run"]:
                self.stdout.write(f"store {store.pk} «{store.name}»: {ready} ready music track(s) - " + ("would get the six starter tracks" if not ready else "left alone"))
                continue
            res = starter_music.ensure_for_store(store, upgrade_on_node=not opts["no_node"])
            self.stdout.write(f"store {store.pk} «{store.name}»: {res['created']} starter track(s) added ({ready} were there), {res['queued_node']} generated track(s) queued on the node")
