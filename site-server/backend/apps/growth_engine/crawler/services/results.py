"""The results list, the map points and the CSV: one query, three shapes.

A result is a ``CrawlFinding`` (a lead seen by a mission, with that mission's fit score and Persian reasons). Filters are plain
query parameters so a view can be linked: ``?mission=3&min_score=60&has_phone=1&city=تهران&q=آرمان&ordering=-score``.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping

from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.growth_engine.core import csvio
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.models import ContactPoint
from apps.growth_engine.sources.models import LeadSource

from ..models import CrawlFinding, LeadReminder
from . import pipeline

ORDERINGS = {
    "-score": ("-score", "-id"), "score": ("score", "id"), "name": ("lead__name_key", "id"), "-created": ("-created_at", "-id"), "-updated": ("-lead__updated_at", "-id"),
    "city": ("lead__city", "-score"),
}
EXPORT_MAX_ROWS = 20_000
MAP_MAX_POINTS = 3000


def _csv(value) -> list[str]:
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def _has(kind: str):
    return Exists(ContactPoint.objects.filter(lead=OuterRef("lead_id"), kind=kind))


def base_queryset() -> QuerySet[CrawlFinding]:
    return CrawlFinding.objects.select_related("lead", "mission").filter(lead__is_archived=False)


def filter_findings(qs: QuerySet[CrawlFinding], params: Mapping) -> QuerySet[CrawlFinding]:
    if params.get("mission"):
        qs = qs.filter(mission_id=int(params["mission"])) if str(params["mission"]).isdigit() else qs.none()
    if str(params.get("lead") or "").isdigit():
        qs = qs.filter(lead_id=int(params["lead"]))
    q = nz.normalize_text(str(params.get("q") or ""))
    if q:
        key = nz.search_key(q)
        qs = qs.filter(Q(lead__name_key__contains=key) | Q(lead__city__icontains=q) | Q(lead__category__icontains=q) | Q(lead__website__icontains=q) | Q(lead__instagram_url__icontains=q))
    if params.get("min_score"):
        try:
            qs = qs.filter(score__gte=int(params["min_score"]))
        except ValueError:
            pass
    if params.get("level") in ("high", "medium", "low"):
        qs = qs.filter(level=params["level"])
    stage = params.get("stage")
    if stage:
        wanted = [s for st in pipeline.STAGES if st["key"] in _csv(stage) for s in st["statuses"]]
        qs = qs.filter(lead__status__in=wanted) if wanted else qs.none()
    if params.get("city"):
        qs = qs.filter(lead__city__icontains=nz.normalize_text(str(params["city"])))
    tags = _csv(params.get("tag"))
    for tag in tags:
        qs = qs.filter(lead__tags__name_key=nz.search_key(tag)[:60])
    for flag, kind in (("has_phone", "phone"), ("has_email", "email"), ("has_telegram", "telegram"), ("has_whatsapp", "whatsapp")):
        if str(params.get(flag)) in ("1", "true"):
            qs = qs.filter(_has(kind))
        elif str(params.get(flag)) == "0":
            qs = qs.exclude(_has(kind))
    if str(params.get("has_website")) in ("1", "true"):
        qs = qs.exclude(lead__website="")
    if str(params.get("has_instagram")) in ("1", "true"):
        qs = qs.exclude(lead__instagram_url="")
    if str(params.get("has_geo")) in ("1", "true"):
        qs = qs.filter(lead__insight__lat__isnull=False)
    if params.get("source"):
        qs = qs.filter(Exists(LeadSource.objects.filter(lead=OuterRef("lead_id"), provider=f"crawl_{params['source']}")))
    if params.get("bbox"):
        try:
            south, west, north, east = (float(x) for x in str(params["bbox"]).split(","))
            qs = qs.filter(lead__insight__lat__gte=south, lead__insight__lat__lte=north, lead__insight__lon__gte=west, lead__insight__lon__lte=east)
        except ValueError:
            pass
    if str(params.get("due")) in ("1", "true"):
        qs = qs.filter(Exists(LeadReminder.objects.filter(lead=OuterRef("lead_id"), done_at__isnull=True, due_at__lte=timezone.now())))
    return qs.distinct() if tags else qs


def order(qs: QuerySet[CrawlFinding], ordering: str | None) -> QuerySet[CrawlFinding]:
    return qs.order_by(*ORDERINGS.get(ordering or "-score", ORDERINGS["-score"]))


def with_prefetch(qs: QuerySet[CrawlFinding]) -> QuerySet[CrawlFinding]:
    return qs.prefetch_related("lead__contacts", "lead__tags", "lead__sources").select_related("lead__insight")


# --------------------------------------------------------------------------- shapes


def _insight(lead):
    try:
        return lead.insight
    except Exception:  # noqa: BLE001 - RelatedObjectDoesNotExist
        return None


def phones_of(lead) -> list[dict]:
    out = []
    for c in lead.contacts.all():
        if c.kind == "phone":
            try:
                mobile = nz.normalize_phone(c.value).kind == "mobile"
            except nz.NormalizationError:
                mobile = False
            out.append({"value": c.value, "display": nz.format_phone_display(c.value), "mobile": mobile, "primary": c.is_primary})
    return sorted(out, key=lambda p: (not p["mobile"], not p["primary"]))


def contacts_of(lead, kind: str) -> list[str]:
    return [c.value for c in lead.contacts.all() if c.kind == kind]


def result_dict(f: CrawlFinding) -> dict:
    lead = f.lead
    ins = _insight(lead)
    sources = sorted({s.provider.replace("crawl_", "") for s in lead.sources.all() if s.provider.startswith("crawl_")})
    return {
        "id": f.pk, "lead_id": lead.pk, "mission_id": f.mission_id, "name": lead.display_name, "city": lead.city, "category": lead.category, "status": lead.status,
        "status_label": lead.get_status_display(), "stage": pipeline.stage_of(lead.status), "score": f.score, "level": f.level, "reasons": f.reasons, "matched": f.matched,
        "phones": phones_of(lead), "emails": contacts_of(lead, "email"), "website": lead.website, "instagram": lead.instagram_url, "telegram": (contacts_of(lead, "telegram") or [""])[0],
        "whatsapp": (contacts_of(lead, "whatsapp") or [""])[0], "address": address_of(lead),
        "lat": ins.lat if ins else None, "lon": ins.lon if ins else None, "hours": ins.hours if ins else "", "rating": ins.rating if ins else None,
        "tags": [t.name for t in lead.tags.all()], "sources": sources, "seen_count": f.seen_count, "first_seen": f.created_at, "updated_at": lead.updated_at,
    }


def address_of(lead) -> str:
    try:
        return lead.profile.address
    except Exception:  # noqa: BLE001
        return ""


def map_points(qs: QuerySet[CrawlFinding]) -> dict:
    rows = qs.filter(lead__insight__lat__isnull=False).values_list("pk", "lead_id", "lead__business_name", "score", "lead__status", "lead__insight__lat", "lead__insight__lon", "lead__city")
    total = rows.count()
    points = [{"id": pk, "lead_id": lead_id, "name": name or "—", "score": score, "stage": pipeline.stage_of(status), "lat": lat, "lon": lon, "city": city}
              for pk, lead_id, name, score, status, lat, lon, city in rows[:MAP_MAX_POINTS]]
    return {"points": points, "total": total, "shown": len(points)}


# --------------------------------------------------------------------------- CSV

HEADER = ["نام", "شهر", "نشانی", "دسته", "امتیاز تناسب", "سطح", "دلیل‌ها", "مرحله", "موبایل", "تلفن", "ایمیل", "وب‌سایت", "اینستاگرام", "تلگرام", "عرض جغرافیایی",
          "طول جغرافیایی", "ساعت کاری", "امتیاز در نقشه/فهرست", "برچسب‌ها", "منبع‌ها", "تاریخ کشف"]


def export_rows(qs: QuerySet[CrawlFinding]) -> Iterator[list[object]]:
    for f in with_prefetch(qs)[:EXPORT_MAX_ROWS]:
        d = result_dict(f)
        mobiles = [p["value"] for p in d["phones"] if p["mobile"]]
        others = [p["value"] for p in d["phones"] if not p["mobile"]]
        yield [
            d["name"], d["city"], address_of(f.lead), d["category"], d["score"], {"high": "مناسب", "medium": "متوسط", "low": "کم"}.get(d["level"], d["level"]),
            "؛ ".join(r["text"] for r in d["reasons"] if r["points"] > 0), pipeline.stage_label(d["stage"]), " | ".join(mobiles), " | ".join(others), " | ".join(d["emails"]),
            d["website"], d["instagram"], d["telegram"], d["lat"] if d["lat"] is not None else "", d["lon"] if d["lon"] is not None else "", d["hours"],
            d["rating"] if d["rating"] is not None else "", "، ".join(d["tags"]), "، ".join(d["sources"]), f.created_at.strftime("%Y-%m-%d"),
        ]


def stream_csv(qs: QuerySet[CrawlFinding]) -> Iterator[bytes]:
    return csvio.stream_csv(HEADER, export_rows(qs))
