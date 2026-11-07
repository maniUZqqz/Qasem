"""«کارگردان» drafts housekeeping.

    manage.py director_drafts stats                       counts + disk the director uses
    manage.py director_drafts purge [--store ID]          delete expired UNOPENED drafts (this also runs by itself on every listing / run)
    manage.py director_drafts migrate [--dry-run] [--backup FILE.json]
                                                          turn old, never-touched director-made PROJECTS into drafts (after writing them to FILE)

`migrate` only moves projects that look untouched: made by the director, state DRAFT, never rendered, never snapshotted, and
saved at most 90 seconds after they were made (every edit in the editor autosaves, which moves `updated_at`).
A project the owner edited, rendered or snapshotted is never touched.
"""
import json
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.content.models import DirectorDraft, VideoProject
from services.editing.director import drafts as drafts_mod
from services.editing.director import projectops as ops


def du(path: Path) -> int:
    total = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def untouched_director_projects():
    root = drafts_mod.editing_root()
    out = []
    for p in VideoProject.objects.all().order_by("pk"):
        d = (p.data or {}).get("director")
        if not isinstance(d, dict):
            continue
        folder = root / f"project_{p.pk}"
        if (p.updated_at - p.created_at).total_seconds() >= 90 or p.state != VideoProject.State.DRAFT or p.output or p.render_info or folder.exists():
            continue
        out.append(p)
    return out


class Command(BaseCommand):
    help = "Director drafts: stats, purge, migrate old untouched director projects to drafts."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["stats", "purge", "migrate"])
        parser.add_argument("--store", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--backup", default="")

    def handle(self, *args, action, store, dry_run, backup, **opts):
        out = self.stdout.write
        root = drafts_mod.editing_root()
        if action == "stats":
            out(f"projects={VideoProject.objects.count()} director_made={sum(1 for p in VideoProject.objects.all() if (p.data or {}).get('director'))} "
                f"untouched={len(untouched_director_projects())} drafts={DirectorDraft.objects.count()} "
                f"editing_dir_bytes={du(root) if root.exists() else 0} director_previews_bytes={sum(du(d) for d in root.glob('director_*')) if root.exists() else 0}")
            return
        if action == "purge":
            from apps.stores.models import Store

            target = Store.objects.get(pk=store) if store else None
            out(json.dumps(drafts_mod.purge(target)))
            return
        # ---- migrate
        rows = untouched_director_projects()
        if store:
            rows = [p for p in rows if p.store_id == store]
        before = {"projects": VideoProject.objects.count(), "drafts": DirectorDraft.objects.count(),
                  "json_bytes": sum(len(json.dumps(p.data, ensure_ascii=False)) for p in rows)}
        out(f"candidates: {len(rows)} untouched director-made projects (of {before['projects']} projects)")
        if dry_run or not rows:
            out("dry run" if dry_run else "nothing to do")
            return
        if not backup:
            raise CommandError("--backup FILE.json is required (the projects are written there before anything is changed)")
        path = Path(backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"id": p.pk, "store_id": p.store_id, "title": p.title, "state": p.state, "data": p.data, "created_at": p.created_at.isoformat(),
                    "updated_at": p.updated_at.isoformat()} for p in rows]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        if json.loads(path.read_text(encoding="utf-8"))[-1]["id"] != rows[-1].pk:
            raise CommandError("the backup file could not be verified; nothing was changed")
        made = 0
        for p in rows:
            d = p.data.get("director") or {}
            DirectorDraft.objects.create(
                store=p.store, run=str(d.get("run") or f"m{p.pk}")[:16], job_id=None, key=str(d.get("variant") or "a")[:4], title=p.title, data=p.data,
                score=int((d.get("critique") or {}).get("score") or 0), length=round(ops.project_length(p.data), 1) if p.data.get("tracks") else 0,
                expires_at=timezone.now() + timedelta(days=drafts_mod.get_settings(p.store)["draft_days"]))
            p.delete()
            made += 1
        out(f"moved {made} projects to drafts (backup: {path}); projects {before['projects']} -> {VideoProject.objects.count()}, drafts {before['drafts']} -> {DirectorDraft.objects.count()}")
