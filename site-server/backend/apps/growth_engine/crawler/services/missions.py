"""Missions and runs: validating the brief, starting / pausing / resuming / cancelling a run, the schedule."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.knowledge import products
from apps.growth_engine.leads.services.editing import ValidationFailed

from .. import presets
from ..models import CrawlMission, CrawlRun

logger = logging.getLogger(__name__)

SOURCE_KEYS = ("osm", "search", "directory", "website", "instagram", "neshan")
SOURCE_LABELS = {
    "osm": "نقشهٔ آزاد (OpenStreetMap)", "search": "جست‌وجوی وب (Brave / Bing / DuckDuckGo / Mojeek)", "directory": "فهرست‌های عمومیِ کسب‌وکار",
    "website": "سایتِ خودِ کسب‌وکار (تماس، درباره، ساعتِ کاری)", "instagram": "پیج‌های اینستاگرام (هشتگ و مکان؛ خواندنِ پیج با آباگرام)", "neshan": "نشان (فقط با کلیدِ API)",
}
BUDGET_LIMITS = {
    "max_requests": (20, 3000), "max_sites": (0, 300), "max_pages_per_site": (1, 10), "max_seconds": (60, 7200), "max_bytes": (1_000_000, 400_000_000),
    "max_search_queries": (0, 20), "max_directory_pages": (0, 60), "max_ig_accounts": (0, 200), "server_sites": (0, 300), "max_directory_details": (0, 400), "max_ig_queries": (0, 20),
}
ACTIVE = (CrawlRun.Status.QUEUED, CrawlRun.Status.RUNNING)


def _err(errors: list[dict], field: str, code: str, message: str) -> None:
    errors.append({"field": field, "code": code, "message": message})


def _strings(raw, field: str, errors: list[dict], *, limit: int, max_len: int, label: str) -> list[str]:
    out: list[str] = []
    for item in raw if isinstance(raw, (list, tuple)) else nz.split_multi(raw):
        text = nz.normalize_text(str(item))
        if not text:
            continue
        if len(text) > max_len:
            _err(errors, field, "too_long", f"هر مورد از «{label}» حداکثر {max_len} نویسه است.")
            continue
        if text not in out:
            out.append(text)
    if len(out) > limit:
        _err(errors, field, "too_many", f"«{label}» حداکثر {limit} مورد می‌تواند باشد.")
        out = out[:limit]
    return out


def validate_spec(data: dict) -> dict:
    """The cleaned spec of a mission, or ``ValidationFailed`` (Persian messages). Nothing is saved or fetched."""
    errors: list[dict] = []
    spec: dict = {}
    types = [t for t in (data.get("business_types") or []) if isinstance(t, str)]
    bad = [t for t in types if presets.get_type(t) is None]
    if bad:
        _err(errors, "business_types", "unknown_type", "نوعِ کسب‌وکارِ ناشناخته: " + "، ".join(bad[:3]))
    types = [t for t in dict.fromkeys(types) if presets.get_type(t)]
    keywords = _strings(data.get("keywords"), "keywords", errors, limit=12, max_len=60, label="کلیدواژه‌ها")
    if not types and not keywords:
        _err(errors, "business_types", "required", "دست‌کم یک نوعِ کسب‌وکار یا یک کلیدواژه بدهید.")
    cities = _strings(data.get("cities"), "cities", errors, limit=8, max_len=60, label="شهرها")
    if not cities:
        _err(errors, "cities", "required", "دست‌کم یک شهر بنویسید.")
    language = str(data.get("language") or "fa")
    if language not in ("fa", "en", "any"):
        _err(errors, "language", "invalid", "زبان باید fa، en یا any باشد.")
        language = "fa"
    sources_in = data.get("sources") if isinstance(data.get("sources"), dict) else {}
    sources = {k: bool(sources_in.get(k, k in ("osm", "search", "directory", "website"))) for k in SOURCE_KEYS}
    if not any(sources.values()):
        _err(errors, "sources", "required", "دست‌کم یک منبع را روشن کنید.")
    budget_in = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    budget: dict = {}
    for name, (lo, hi) in BUDGET_LIMITS.items():
        if name in budget_in:
            try:
                value = int(budget_in[name])
            except (TypeError, ValueError):
                _err(errors, "budget", "invalid_number", f"«{name}» باید عدد باشد.")
                continue
            if not lo <= value <= hi:
                _err(errors, "budget", "out_of_range", f"«{name}» باید بین {lo} و {hi} باشد.")
                continue
            budget[name] = value
    if "domain_delay" in budget_in:
        try:
            delay = float(budget_in["domain_delay"])
            if not 1.0 <= delay <= 30.0:
                raise ValueError
            budget["domain_delay"] = delay
        except (TypeError, ValueError):
            _err(errors, "budget", "invalid_number", "«فاصلهٔ درخواست‌ها به یک سایت» باید بین ۱ تا ۳۰ ثانیه باشد.")
    urls: list[str] = []
    for raw in data.get("directory_urls") or []:
        try:
            urls.append(nz.clean_url(str(raw)).url)
        except nz.NormalizationError:
            _err(errors, "directory_urls", "invalid_url", f"نشانیِ فهرست معتبر نیست: {str(raw)[:60]}")
    execution = str(data.get("execution") or "auto")
    if execution not in ("auto", "server", "node"):
        _err(errors, "execution", "invalid", "محلِ اجرا باید auto، server یا node باشد.")
        execution = "auto"
    size = str(data.get("size") or "any")
    if size not in ("any", "small", "large"):
        _err(errors, "size", "invalid", "اندازه باید any، small یا large باشد.")
        size = "any"
    try:
        max_results = int(data.get("max_results") or 300)
        min_score = int(data.get("min_score") or 0)
        if not 10 <= max_results <= 2000 or not 0 <= min_score <= 100:
            raise ValueError
    except (TypeError, ValueError):
        _err(errors, "max_results", "out_of_range", "«حداکثر نتیجه» باید ۱۰ تا ۲۰۰۰ و «حداقل امتیاز» ۰ تا ۱۰۰ باشد.")
        max_results, min_score = 300, 0
    pitch_in = data.get("pitch") if isinstance(data.get("pitch"), dict) else {}
    pitch = {k: nz.normalize_text(str(pitch_in.get(k) or ""), multiline=True)[:600] for k in ("brand", "what", "benefit", "cta", "voice", "sms") if pitch_in.get(k)}
    if errors:
        raise ValidationFailed(errors)
    spec.update(
        business_types=types, keywords=keywords, cities=cities, language=language, sources=sources, budget=budget, directory_urls=urls, execution=execution, size=size,
        require_contact=bool(data.get("require_contact", True)), include_online=bool(data.get("include_online", False)), max_results=max_results, min_score=min_score,
        exclude_words=_strings(data.get("exclude_words"), "exclude_words", [], limit=20, max_len=40, label="کلمه‌های ردکننده"),
        tag=nz.normalize_text(str(data.get("tag") or ""))[:40], pitch=pitch,
        ig_hashtags=_strings(data.get("ig_hashtags"), "ig_hashtags", [], limit=12, max_len=60, label="هشتگ‌ها"),
        ig_locations=_strings(data.get("ig_locations"), "ig_locations", [], limit=12, max_len=60, label="مکان‌ها"),
        include_individuals=bool(data.get("include_individuals", True)),
    )
    if data.get("search_engines"):
        spec["search_engines"] = [e for e in data["search_engines"] if e in ("brave", "bing", "duckduckgo", "mojeek")]
    return spec


def _store_of(store_id):
    if not store_id:
        return None
    from apps.stores.models import Store

    return Store.objects.filter(pk=store_id).first()


def create_mission(data: dict, user=None) -> CrawlMission:
    name = nz.normalize_text(str(data.get("name") or ""))
    errors: list[dict] = []
    if not name:
        _err(errors, "name", "required", "نامِ مأموریت را بنویسید.")
    elif len(name) > 150:
        _err(errors, "name", "too_long", "نام از ۱۵۰ نویسه بلندتر است.")
    product = str(data.get("product") or "nm")
    if not products.valid(product):
        _err(errors, "product", "invalid", "محصولِ معتبر نیست.")
    store = _store_of(data.get("store_id"))
    if data.get("store_id") and store is None:
        _err(errors, "store_id", "not_found", "فروشگاه پیدا نشد.")
    try:
        days = int(data.get("schedule_days") or 0)
        if not 0 <= days <= 365:
            raise ValueError
    except (TypeError, ValueError):
        _err(errors, "schedule_days", "out_of_range", "تکرار باید ۰ تا ۳۶۵ روز باشد.")
        days = 0
    if errors:
        raise ValidationFailed(errors)
    try:
        spec = validate_spec(data.get("spec") if isinstance(data.get("spec"), dict) else data)
    except ValidationFailed as exc:
        raise ValidationFailed([*errors, *exc.errors]) from exc
    mission = CrawlMission.objects.create(
        name=name, preset_key=str(data.get("preset_key") or "")[:60], store=store, product=products.normalize(product), spec=spec, schedule_days=days,
        enabled=bool(data.get("enabled", True)), notes=nz.normalize_text(str(data.get("notes") or ""), multiline=True)[:2000],
        next_run_at=(timezone.now() + timedelta(days=days)) if days else None, created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    return mission


def update_mission(mission: CrawlMission, data: dict) -> CrawlMission:
    if "name" in data:
        name = nz.normalize_text(str(data["name"]))
        if not name:
            raise ValidationFailed([{"field": "name", "code": "required", "message": "نامِ مأموریت را بنویسید."}])
        mission.name = name[:150]
    if "spec" in data and isinstance(data["spec"], dict):
        mission.spec = validate_spec({**mission.spec, **data["spec"]})
    if "schedule_days" in data:
        try:
            days = int(data["schedule_days"] or 0)
            if not 0 <= days <= 365:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValidationFailed([{"field": "schedule_days", "code": "out_of_range", "message": "تکرار باید ۰ تا ۳۶۵ روز باشد."}]) from exc
        mission.schedule_days = days
        mission.next_run_at = (timezone.now() + timedelta(days=days)) if days and mission.enabled else None
    if "enabled" in data:
        mission.enabled = bool(data["enabled"])
        if mission.enabled and mission.schedule_days and not mission.next_run_at:
            mission.next_run_at = timezone.now() + timedelta(days=mission.schedule_days)
        if not mission.enabled:
            mission.next_run_at = None
    for field in ("notes", "is_archived"):
        if field in data:
            setattr(mission, field, data[field] if field == "is_archived" else nz.normalize_text(str(data[field]), multiline=True)[:2000])
    mission.save()
    return mission


def create_from_preset(key: str, user=None, overrides: dict | None = None) -> CrawlMission:
    preset = presets.PRESETS.get(key)
    if preset is None:
        raise ValidationFailed([{"field": "preset", "code": "unknown", "message": "پیش‌تنظیم پیدا نشد."}])
    overrides = overrides or {}
    spec = {**preset.spec, **(overrides.get("spec") or {})}
    spec.setdefault("tag", _default_tag(preset))
    if preset.pitch is not None:
        p = preset.pitch
        spec.setdefault("pitch", {"brand": p.brand, "what": p.what, "benefit": p.benefit, "cta": p.cta, "voice": p.voice, "sms": p.sms})
    store = _store_of(preset.store_id)
    return create_mission(
        {"name": overrides.get("name") or preset.name, "preset_key": preset.key, "product": preset.product, "store_id": store.pk if store else None,
         "spec": spec, "schedule_days": overrides.get("schedule_days", 0), "notes": preset.description},
        user,
    )


def _default_tag(preset: presets.Preset) -> str:
    return {"chagher_gyms_tehran": "چغر · تهران", "chagher_coaches_instagram": "چغر · اینستاگرام", "cafes_isfahan": "کافه · اصفهان", "clothing_shops_hamedan": "پوشاک · همدان",
            "dental_clinics_mashhad": "دندانپزشکی · مشهد"}.get(preset.key, "")


# --------------------------------------------------------------------------- runs


def active_run(mission: CrawlMission) -> CrawlRun | None:
    return CrawlRun.objects.filter(mission=mission, status__in=ACTIVE).first()


def start_run(mission: CrawlMission, user=None, *, trigger: str = CrawlRun.Trigger.MANUAL, dispatch: bool = True) -> CrawlRun:
    if mission.is_archived:
        raise ValidationFailed([{"field": "mission", "code": "archived", "message": "این مأموریت بایگانی شده است."}])
    running = active_run(mission)
    if running is not None:
        raise ValidationFailed([{"field": "mission", "code": "already_running", "message": f"اجرای #{running.pk} هنوز در جریان است؛ اول آن را متوقف یا لغو کنید."}])
    run = CrawlRun.objects.create(
        mission=mission, trigger=trigger, spec=mission.spec, created_by=user if getattr(user, "is_authenticated", False) else None, message="در صف",
    )
    if dispatch:
        from .. import tasks

        tasks.enqueue_run(run.pk)
    return run


def pause_run(run: CrawlRun) -> CrawlRun:
    if run.is_finished:
        raise ValidationFailed([{"field": "run", "code": "finished", "message": "این اجرا تمام شده است."}])
    if run.status == CrawlRun.Status.QUEUED and not run.paused and not run.celery_task_id:
        CrawlRun.objects.filter(pk=run.pk).update(paused=True, message="متوقفِ موقت")
    else:
        CrawlRun.objects.filter(pk=run.pk).update(pause_requested=True)
    run.refresh_from_db()
    return run


def resume_run(run: CrawlRun, *, dispatch: bool = True) -> CrawlRun:
    if run.status == CrawlRun.Status.CANCELLED:
        raise ValidationFailed([{"field": "run", "code": "cancelled", "message": "اجرای لغوشده ادامه پیدا نمی‌کند؛ یک اجرای تازه شروع کنید."}])
    if run.status == CrawlRun.Status.COMPLETED:
        raise ValidationFailed([{"field": "run", "code": "finished", "message": "این اجرا تمام شده است."}])
    if run.status == CrawlRun.Status.RUNNING and not run.is_stalled and not run.pause_requested:
        raise ValidationFailed([{"field": "run", "code": "running", "message": "این اجرا همین حالا در حال کار است."}])
    CrawlRun.objects.filter(pk=run.pk).update(status=CrawlRun.Status.QUEUED, paused=False, pause_requested=False, cancel_requested=False, queued_at=timezone.now(), error="", message="در صف",
                                              finished_at=None, usage={**(run.usage or {}), "parked_until": ""})
    run.refresh_from_db()
    if dispatch:
        from .. import tasks

        tasks.enqueue_run(run.pk)
    return run


def cancel_run(run: CrawlRun) -> CrawlRun:
    if run.is_finished:
        raise ValidationFailed([{"field": "run", "code": "finished", "message": "این اجرا تمام شده است."}])
    CrawlRun.objects.filter(pk=run.pk).update(cancel_requested=True)
    run.refresh_from_db()
    if run.status == CrawlRun.Status.QUEUED:  # nobody is running it: finish it here
        from ..engine import runner

        runner._on_interrupt(run, "cancel")
        run.refresh_from_db()
    return run


# --------------------------------------------------------------------------- the schedule


def due_missions(now=None):
    now = now or timezone.now()
    return CrawlMission.objects.filter(is_archived=False, enabled=True, schedule_days__gt=0, next_run_at__lte=now)


def tick_schedule(now=None) -> list[int]:
    """Start a run for every mission whose time has come (and that has no active run). Returns the run ids."""
    started: list[int] = []
    for mission in due_missions(now):
        if active_run(mission) is not None:
            CrawlMission.objects.filter(pk=mission.pk).update(next_run_at=timezone.now() + timedelta(hours=6))
            continue
        try:
            with transaction.atomic():
                run = start_run(mission, None, trigger=CrawlRun.Trigger.SCHEDULE)
                CrawlMission.objects.filter(pk=mission.pk).update(next_run_at=timezone.now() + timedelta(days=mission.schedule_days))
            started.append(run.pk)
        except Exception:  # noqa: BLE001 - one broken mission never stops the others
            logger.exception("crawler: scheduled start of mission %s failed", mission.pk)
    return started
