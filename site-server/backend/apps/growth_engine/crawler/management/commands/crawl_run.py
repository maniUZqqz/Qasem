"""Run a finder mission from the command line (for a real run on the server, or a repeat run by hand).

    python manage.py crawl_run --preset chagher_gyms_tehran
    python manage.py crawl_run --mission 3 --resume-run 12
    python manage.py crawl_run --preset cafes_isfahan --max-seconds 600 --max-sites 20

Nothing is sent anywhere: a run only reads public pages and writes leads. The diary is printed as it goes.
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from apps.growth_engine.crawler import presets
from apps.growth_engine.crawler.engine import runner
from apps.growth_engine.crawler.models import CrawlLog, CrawlMission, CrawlRun
from apps.growth_engine.crawler.services import missions
from apps.growth_engine.leads.services.editing import ValidationFailed


class Command(BaseCommand):
    help = "Create (or reuse) a mission from a preset and run it here, printing the diary."

    def add_arguments(self, parser):
        parser.add_argument("--preset", help="preset key: " + ", ".join(presets.PRESETS))
        parser.add_argument("--mission", type=int, help="run an existing mission")
        parser.add_argument("--resume-run", type=int, help="continue an unfinished run")
        parser.add_argument("--max-seconds", type=int)
        parser.add_argument("--max-sites", type=int)
        parser.add_argument("--max-requests", type=int)
        parser.add_argument("--no-instagram", action="store_true")
        parser.add_argument("--list", action="store_true", help="list presets and exit")

    def handle(self, *args, **opts):
        if opts["list"]:
            for p in presets.preset_listing():
                self.stdout.write(f"{p['key']:28} {p['name']}")
            return
        try:
            if opts["resume_run"]:
                run = CrawlRun.objects.get(pk=opts["resume_run"])
                missions.resume_run(run, dispatch=False)
            else:
                mission = self._mission(opts)
                run = missions.start_run(mission, None, trigger=CrawlRun.Trigger.PRESET, dispatch=False)
        except (CrawlRun.DoesNotExist, CrawlMission.DoesNotExist) as exc:
            raise CommandError("not found") from exc
        except ValidationFailed as exc:
            raise CommandError(exc.errors[0]["message"]) from exc
        self.stdout.write(f"mission #{run.mission_id} run #{run.pk}")
        last = 0
        while True:
            status = runner.run_crawl(run.pk)
            for row in CrawlLog.objects.filter(run=run, id__gt=last).order_by("id"):
                self.stdout.write(f"[{row.level}] {row.message}")
                last = row.id
            self.stdout.flush()
            if status != "parked":
                break
            run.refresh_from_db()
            until = (run.usage or {}).get("parked_until")
            self.stdout.write(f"parked until {until}; waiting")
            time.sleep(60)
            CrawlRun.objects.filter(pk=run.pk).update(usage={**(run.usage or {}), "parked_until": ""})
        run.refresh_from_db()
        self.stdout.write(
            f"DONE status={run.status} stage={run.stage} found={run.found_count} unique={run.unique_count} created={run.created_count} merged={run.merged_count} "
            f"skipped={run.skipped_count} pages={run.pages_fetched} cache_hits={run.cache_hits} waiting_node={run.tasks_waiting} tasks={run.tasks_total} failed={run.tasks_failed}"
        )

    def _mission(self, opts) -> CrawlMission:
        if opts["mission"]:
            return CrawlMission.objects.get(pk=opts["mission"])
        key = opts["preset"]
        if key not in presets.PRESETS:
            raise CommandError("--preset or --mission is required (see --list)")
        mission = CrawlMission.objects.filter(preset_key=key, is_archived=False).first() or missions.create_from_preset(key)
        spec = dict(mission.spec)
        budget = dict(spec.get("budget") or {})
        for opt, name in (("max_seconds", "max_seconds"), ("max_sites", "max_sites"), ("max_requests", "max_requests")):
            if opts.get(opt):
                budget[name] = opts[opt]
        spec["budget"] = budget
        if opts["no_instagram"]:
            spec["sources"] = {**spec.get("sources", {}), "instagram": False}
        return missions.update_mission(mission, {"spec": spec})
