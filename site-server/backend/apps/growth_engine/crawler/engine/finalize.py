"""From candidates to leads: the last step of a run (and of every late enrichment).

For each candidate:  clean the directory boilerplate -> ``LeadDraft`` -> duplicate check on the Growth Engine's identifiers
(phone / e-mail / website / Instagram) AND on name + place -> create a lead, or **merge fill-only into the existing one** (a value that
differs is never overwritten) -> the lead's map position / hours / rating (``LeadInsight``) -> the fit score for this mission
(``CrawlFinding``) -> the lead's history.

Everything is written through the Growth Engine's own services (``create_from_draft``, ``merge_draft_into``), so provenance, the
unique identifier registry and the activity log behave exactly as for a lead typed in by hand.
"""
from __future__ import annotations

import logging
from collections import Counter

from django.db import transaction

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.core.dbretry import retry_locked
from apps.growth_engine.leads.choices import ActivityKind, ContactKind, LeadOrigin
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services import history
from apps.growth_engine.leads.services.dedupe import find_duplicates_for_draft
from apps.growth_engine.leads.services.drafts import ContactDraft, build_draft
from apps.growth_engine.leads.services.intake import DuplicateError, SourceInfo, create_from_draft, merge_draft_into

from .. import presets
from ..models import CrawlCandidate, CrawlFinding, CrawlMission, CrawlRun, LeadInsight
from . import scoring, textnorm

logger = logging.getLogger(__name__)

PROVIDER_OF = {"osm": "crawl_osm", "directory": "crawl_directory", "search": "crawl_search", "website": "crawl_site", "instagram": "crawl_instagram", "neshan": "crawl_neshan"}
CONFIDENCE_OF = {"osm": 80, "directory": 75, "search": 55, "website": 70, "instagram": 70, "neshan": 70}
BOILERPLATE_MIN = 4  # a contact value on this many candidates of ONE directory is the directory's own


def strip_boilerplate(run: CrawlRun) -> dict:
    """A directory's footer phone / e-mail / social link is on every page it has: remove such values from its candidates."""
    counts: dict[tuple[str, str, str], int] = Counter()
    rows = list(CrawlCandidate.objects.filter(run=run).only("id", "phones", "emails", "instagram", "telegram", "sources", "signals"))
    host_of = {}
    for c in rows:
        d = (c.signals or {}).get("dir_host") or ""
        only_dir = bool(c.sources) and all(s.get("source") == "directory" for s in c.sources)
        if d and only_dir:
            host_of[c.pk] = d
            for kind, values in (("p", c.phones), ("e", c.emails), ("i", [c.instagram]), ("t", [c.telegram])):
                for v in values:
                    if v:
                        counts[(d, kind, v)] += 1
    bad = {k for k, n in counts.items() if n >= BOILERPLATE_MIN}
    if not bad:
        return {"removed": 0}
    removed = 0
    for c in rows:
        d = host_of.get(c.pk)
        if not d:
            continue
        phones = [p for p in c.phones if (d, "p", p) not in bad]
        emails = [e for e in c.emails if (d, "e", e) not in bad]
        ig = "" if (d, "i", c.instagram) in bad else c.instagram
        tg = "" if (d, "t", c.telegram) in bad else c.telegram
        if (phones, emails, ig, tg) != (c.phones, c.emails, c.instagram, c.telegram):
            removed += (len(c.phones) - len(phones)) + (len(c.emails) - len(emails)) + (1 if ig != c.instagram else 0) + (1 if tg != c.telegram else 0)
            CrawlCandidate.objects.filter(pk=c.pk).update(phones=phones, emails=emails, instagram=ig, telegram=tg)
    return {"removed": removed}


def has_contact(c) -> bool:
    return bool(c.phones or c.emails or c.website or c.instagram or c.telegram or c.whatsapp or c.contact_form)


def _raw_for(c: CrawlCandidate, tags: list[str]) -> dict:
    raw = {
        "business_name": c.name, "category": c.category, "city": c.city, "address": c.address, "website": c.website, "instagram": c.instagram,
        "phone": "; ".join(c.phones), "email": "; ".join(c.emails), "whatsapp": "; ".join(c.whatsapp), "telegram": c.telegram, "tags": tags,
        "country": "IR",
    }
    return {k: v for k, v in raw.items() if v}


def clean_tag(text: str) -> str:
    """A tag name: no list separators (the draft builder splits on them), at most 50 characters."""
    for ch in "،,;؛|\n":
        text = text.replace(ch, " ")
    return nz.normalize_text(text)[:50]


def _tags_for(mission: CrawlMission, c: CrawlCandidate) -> list[str]:
    tags = ["مشتری‌یاب", clean_tag(str((mission.spec or {}).get("tag") or "")) or f"مأموریت {mission.pk}"]
    for t in (c.types or [])[:2]:
        bt = presets.get_type(t)
        if bt:
            tags.append(clean_tag(bt.fa))
    return list(dict.fromkeys(t for t in tags if t))


def near_duplicate(c: CrawlCandidate) -> Lead | None:
    """An existing lead with the same name in the same place (no identifier in common, which is why the identifier check missed it)."""
    key = nz.search_key(c.name)
    core = textnorm.name_core(c.name)
    if len(core) < 3:
        return None
    pool = Lead.objects.filter(name_key=key) if key else Lead.objects.none()
    seen = {lead.pk: lead for lead in pool[:20]}
    if len(core) >= 5:
        for lead in Lead.objects.filter(name_key__contains=core)[:30]:
            seen.setdefault(lead.pk, lead)
    for lead in seen.values():
        if textnorm.similar(core, textnorm.name_core(lead.business_name)) < 0.95:
            continue
        try:
            ins = lead.insight
        except LeadInsight.DoesNotExist:
            ins = None
        if textnorm.valid_geo(c.lat, c.lon) and ins is not None and textnorm.valid_geo(ins.lat, ins.lon):
            if textnorm.haversine_m(c.lat, c.lon, ins.lat, ins.lon) <= 350:
                return lead
            continue
        if not c.city or not lead.city or nz.search_key(c.city) == nz.search_key(lead.city):
            return lead
    return None


def _contact_meta(draft, c: CrawlCandidate) -> None:
    src = (c.sources or [{}])[0]
    source = src.get("source", "")
    for cd in draft.contacts:
        cd.source_url = cd.source_url or (src.get("url") or "")[:500]
        cd.evidence = cd.evidence or "کشف‌شده توسط مشتری‌یاب"
        cd.confidence = cd.confidence or CONFIDENCE_OF.get(source, 60)
    if c.contact_form:
        try:
            clean = nz.clean_url(c.contact_form)
            draft.contacts.append(ContactDraft(kind=ContactKind.CONTACT_FORM, value=clean.url, normalized=clean.identity, source_ref=f"crawl:{c.run_id}",
                                               source_url=clean.url[:500], evidence="فرمِ تماسِ سایت", confidence=70))
        except nz.NormalizationError:
            pass


def upsert_insight(lead: Lead, c: CrawlCandidate) -> None:
    ins, _ = LeadInsight.objects.get_or_create(lead=lead)
    changed = False
    if ins.lat is None and textnorm.valid_geo(c.lat, c.lon):
        ins.lat, ins.lon = c.lat, c.lon
        ins.geo_source = (c.sources or [{}])[0].get("source", "")[:20]
        changed = True
    if not ins.hours and c.hours:
        ins.hours, changed = c.hours, True
    if ins.rating is None and c.rating:
        ins.rating, changed = c.rating, True
    types = list(dict.fromkeys([*ins.types, *(c.types or [])]))[:8]
    if types != ins.types:
        ins.types, changed = types, True
    sig = dict(ins.signals or {})
    site, ig = (c.signals or {}).get("site"), (c.signals or {}).get("ig")
    if site:
        sig["site"] = {k: site.get(k) for k in ("title", "lang", "words", "fit_words", "js_shell") if site.get(k) not in (None, "", [])}
    if ig:
        sig["ig"] = {k: ig.get(k) for k in ("followers", "is_business", "category", "verified") if ig.get(k) not in (None, "")}
    if sig != ins.signals:
        ins.signals, changed = sig, True
    if changed:
        ins.save()


def upsert_finding(mission: CrawlMission, run: CrawlRun, lead: Lead, c: CrawlCandidate, result: dict, *, is_new_lead: bool) -> CrawlFinding:
    finding, created = CrawlFinding.objects.get_or_create(
        mission=mission, lead=lead, defaults={"first_run": run, "last_run": run, "score": result["value"], "level": result["level"], "reasons": result["reasons"], "matched": result["matched"]},
    )
    if not created:
        # a later run can only make the picture better: keep the higher-scoring explanation
        if finding.last_run_id != run.pk:
            finding.seen_count = min(finding.seen_count + 1, 250)
        finding.last_run = run
        if result["value"] >= finding.score:
            finding.score, finding.level, finding.reasons, finding.matched = result["value"], result["level"], result["reasons"], result["matched"]
        finding.save()
    return finding


def source_info(c: CrawlCandidate, run: CrawlRun) -> SourceInfo:
    first = (c.sources or [{}])[0]
    return SourceInfo(
        provider=PROVIDER_OF.get(first.get("source", ""), "crawl_search"), source_ref=(first.get("ref") or f"crawl:{run.pk}")[:255], source_url=(first.get("url") or "")[:500],
        job=None, raw_data={"crawl_run": run.pk, "mission": run.mission_id, "sources": c.sources, "types": c.types, "score_inputs": {"signals": {k: v for k, v in (c.signals or {}).items() if k in ("serp", "site", "ig", "directory")}}},
    )


def finalize_candidate(run: CrawlRun, c: CrawlCandidate, spec: dict, mission: CrawlMission, result: dict | None = None) -> str:
    """Create / merge the lead of one candidate. Returns ``created | merged | skipped:<reason>``."""
    result = result or scoring.score(c, spec)

    def skip(reason: str) -> str:
        c.state = CrawlCandidate.State.SKIPPED
        c.score = result["value"]
        c.save(update_fields=["state", "score"])
        return f"skipped:{reason}"

    if spec.get("require_contact", True) and not has_contact(c):
        return skip("no_contact")
    if textnorm.text_has_any(c.name, spec.get("exclude_words") or []):
        return skip("excluded_word")
    if int(spec.get("min_score") or 0) and result["value"] < int(spec["min_score"]):
        return skip("low_score")
    draft, errors = build_draft(_raw_for(c, _tags_for(mission, c)), source_ref=f"crawl:{run.pk}", default_country="IR", default_city=c.city)
    if errors:
        # a single bad value must not lose a business: drop the contact fields that failed and try once more
        bad = {e["field"] for e in errors}
        raw = {k: v for k, v in _raw_for(c, _tags_for(mission, c)).items() if k not in bad}
        draft, errors = build_draft(raw, source_ref=f"crawl:{run.pk}", default_country="IR", default_city=c.city)
        if errors:
            return skip("invalid")
    if c.address:
        draft.profile["address"] = c.address[:400]
    draft.profile.setdefault("business_type", "service" if not c.website and not c.instagram else "physical_store")
    _contact_meta(draft, c)
    info = source_info(c, run)
    matches = find_duplicates_for_draft(draft)
    lead = matches[0].lead if matches else near_duplicate(c)
    outcome = "merged"
    if lead is not None:
        merge_draft_into(lead, draft, info, None)
    else:
        try:
            lead = create_from_draft(draft, info, None)
            outcome = "created"
        except DuplicateError as dup:
            lead = dup.matches[0].lead
            merge_draft_into(lead, draft, info, None)
    if lead.origin != LeadOrigin.SEARCH and outcome == "created":
        Lead.objects.filter(pk=lead.pk).update(origin=LeadOrigin.SEARCH)
    upsert_insight(lead, c)
    upsert_finding(mission, run, lead, c, result, is_new_lead=outcome == "created")
    c.lead = lead
    c.score = result["value"]
    c.state = CrawlCandidate.State.CREATED if outcome == "created" else CrawlCandidate.State.MERGED
    c.save(update_fields=["lead", "score", "state"])
    history.log_activity(
        lead, ActivityKind.EXTRACTION, summary=f"مشتری‌یاب «{mission.name}»: امتیازِ تناسب {result['value']} ({result['label']})",
        data={"mission": mission.pk, "run": run.pk, "score": result["value"], "outcome": outcome}, source_ref=f"crawl:{run.pk}",
    )
    return outcome


def finalize_run(run: CrawlRun, spec: dict, *, stop=None, log=lambda level, msg: None) -> dict:
    """Write every NEW candidate of the run into the lead tables. Safe to call again (only ``new`` candidates are touched)."""
    mission = run.mission
    log("info", "یکی‌کردنِ نامزدها و ساختنِ لیدها شروع شد.")
    stripped = strip_boilerplate(run)
    if stripped["removed"]:
        log("info", f"{stripped['removed']} راهِ تماسِ تکراریِ خودِ فهرست‌ها (پایین صفحه) کنار گذاشته شد.")
    counts = Counter()
    # the best-fitting businesses first: if a mission caps the number of results, the cap cuts the weakest ones
    scored = [(scoring.score(c, spec), c) for c in CrawlCandidate.objects.filter(run=run, state=CrawlCandidate.State.NEW)]
    scored.sort(key=lambda pair: (-pair[0]["value"], pair[1].pk))
    limit = int(spec.get("max_results") or 0) or None
    made = 0
    for result, c in scored:
        if stop and stop():
            break
        if limit is not None and made >= limit:
            CrawlCandidate.objects.filter(pk=c.pk).update(state=CrawlCandidate.State.SKIPPED, score=result["value"])
            counts["skipped:limit"] += 1
            continue

        def work(c=c, result=result) -> str:
            with transaction.atomic():
                return finalize_candidate(run, c, spec, mission, result)

        try:
            outcome = retry_locked(work)
            counts[outcome] += 1
            if outcome in ("created", "merged"):
                made += 1
        except Exception as exc:  # noqa: BLE001 - one bad business never stops the run
            logger.exception("crawler: finalize of candidate %s failed", c.pk)
            counts["skipped:error"] += 1
            log("warn", f"«{c.name[:50]}» ثبت نشد ({type(exc).__name__}).")
    skipped = sum(n for k, n in counts.items() if k.startswith("skipped"))
    out = {"created": counts["created"], "merged": counts["merged"], "skipped": skipped, "skipped_detail": {k: v for k, v in counts.items() if k.startswith("skipped")}}
    log("info", f"لیدها: {out['created']} تازه، {out['merged']} ادغام در لیدِ موجود، {skipped} ردشده (بی‌راهِ تماس یا نامعتبر).")
    return out


def refresh_lead_from_candidate(c: CrawlCandidate, spec: dict) -> None:
    """A late answer (the node read a site / an Instagram page after the run ended) improves a candidate that already has a lead:
    push the new contacts into the lead (fill-only), refresh the insight and the score."""
    if c.lead_id is None:
        return
    run, mission, lead = c.run, c.run.mission, c.lead
    draft, errors = build_draft(_raw_for(c, _tags_for(mission, c)), source_ref=f"crawl:{run.pk}", default_country="IR", default_city=c.city)
    if not errors:
        _contact_meta(draft, c)
        merge_draft_into(lead, draft, source_info(c, run), None)
    result = scoring.score(c, spec)
    upsert_insight(lead, c)
    upsert_finding(mission, run, lead, c, result, is_new_lead=False)
    c.score = result["value"]
    c.save(update_fields=["score"])
