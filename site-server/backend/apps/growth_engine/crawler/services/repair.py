"""Cleaning up what EARLIER runs of the finder left in the lead tables (before the place / contact rules existed).

Run through ``python manage.py crawl_repair`` (a dry run that only reports; ``--apply`` writes). It touches only leads that the finder made or
enriched (every source of the lead is a ``crawl_*`` provider) and never what a person has worked on:

* **city names** are made canonical («شهر تهران» / «tehran» / «Tehran» -> «تهران»);
* **contact values that are not a business's own** are removed: filler numbers (09123456789), a developer's free-mail address, a directory's own
  Instagram page, free-mail addresses next to the business's own-domain address, mobile numbers beyond the first three of one lead;
* a lead whose OWN data (address, map position, landline area code) says it is in another city than the mission that found it asked for:
  its finding for that mission is removed and its city is corrected (it stays a lead of its real city, with its contacts); when nobody
  has worked on it and it has no other mission, it is deleted - it was never what was asked for;
* a lead whose address and map position contradict each other (two businesses of two cities merged into one by the old dedupe) is deleted
  when untouched (its phones cannot be told apart any more);
* an untouched finder lead with no way to reach it is deleted (it only crowded the list);
* a landline of another province than the lead's own address (a web agency's or a template's line), an Instagram / Telegram placeholder («instagram.com/0») are removed;
* a gym that wears the trainer type's tag only because a badanfit.ir gym list was mapped onto it loses that tag; a lead that is no longer a result of a
  mission loses the mission's tag; the activity line «امتیازِ تناسب 59» gets Persian digits;
* the preset missions get the current preset (budgets, «require_contact», online coaches ...), keeping their tag, pitch and hand-set limits.

«Touched by a person» = a status other than «جدید»، a note, a reminder, an approved / queued / sent draft, a campaign item, or an activity with a
person as its actor. Such a lead is only repaired (city, contacts, finding), never deleted.
"""
from __future__ import annotations

from collections import Counter

from django.db import transaction

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ActivityKind, ContactKind, LeadStatus
from apps.growth_engine.leads.models import ContactPoint, Lead

from .. import presets
from ..engine import contactrules, finalize, place, textnorm
from ..models import CrawlFinding, CrawlMission, LeadInsight, LeadReminder, OutreachDraft

MOBILE_CAP = 3
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
TRAINER_WORDS = ("مربی", "کوچ", "coach", "trainer", "pt")


def is_finder_lead(lead: Lead) -> bool:
    providers = [s.provider for s in lead.sources.all()]
    return bool(providers) and all(p.startswith("crawl_") for p in providers)


def touched_by_person(lead: Lead) -> bool:
    if lead.status != LeadStatus.NEW:
        return True
    if lead.notes.exists() or LeadReminder.objects.filter(lead=lead).exists():
        return True
    if OutreachDraft.objects.filter(lead=lead, status__in=[OutreachDraft.Status.APPROVED, OutreachDraft.Status.QUEUED, OutreachDraft.Status.SENT_MANUAL]).exists():
        return True
    if lead.activities.filter(actor__isnull=False).exists():
        return True
    try:
        from apps.growth_engine.outreach.models import OutreachItem

        if OutreachItem.objects.filter(lead=lead).exists():
            return True
    except Exception:  # noqa: BLE001 - the outreach module is optional here
        pass
    return False


def _directory_hosts(lead: Lead) -> list[str]:
    from urllib.parse import urlsplit

    hosts = []
    for s in lead.sources.all():
        if s.provider == "crawl_directory" and s.source_url:
            h = urlsplit(s.source_url).hostname or ""
            if h and h not in hosts:
                hosts.append(h)
    return hosts


def bad_contacts(lead: Lead, *, touched: bool = False) -> list[tuple[ContactPoint, str]]:
    """The contact points of a finder lead that are not the business's own, each with the reason."""
    points = list(lead.contacts.all().order_by("id"))
    out: list[tuple[ContactPoint, str]] = []
    dir_hosts = _directory_hosts(lead)
    emails = [c for c in points if c.kind == ContactKind.EMAIL]
    business_mail = [c for c in emails if not contactrules.is_free_mail(c.value)]
    free_kept = 0
    for c in points:
        if c.kind in (ContactKind.PHONE, ContactKind.WHATSAPP) and contactrules.is_placeholder_phone(c.value):
            out.append((c, "شمارهٔ نمونه/ساختگی"))
        elif c.kind == ContactKind.EMAIL and contactrules.looks_like_agency_mail(c.value) and contactrules.is_free_mail(c.value):
            out.append((c, "ایمیلِ طراح/توسعه‌دهندهٔ سایت"))
        elif c.kind == ContactKind.EMAIL and contactrules.is_free_mail(c.value):
            if business_mail:
                out.append((c, "ایمیلِ شخصی کنارِ ایمیلِ خودِ کسب‌وکار"))
            else:
                free_kept += 1
                if free_kept > 1:
                    out.append((c, "بیش از یک ایمیلِ شخصی"))
        elif c.kind in (ContactKind.INSTAGRAM, ContactKind.TELEGRAM) and any(contactrules.own_social(c.value, h) for h in dir_hosts):
            out.append((c, "پیجِ خودِ فهرست، نه کسب‌وکار"))
        elif c.kind in (ContactKind.INSTAGRAM, ContactKind.TELEGRAM) and contactrules.is_placeholder_handle(c.value, c.kind):
            out.append((c, "نشانیِ شبکهٔ اجتماعیِ نمونه/ساختگی"))
    if not touched:
        # a landline of ANOTHER province than the lead's own address is the web agency's / template's line, not the business's
        home = {place.CITY_PROVINCE[x] for x in place.address_cities(_address_of(lead)) if x in place.CITY_PROVINCE}
        for c in points:
            if home and c.kind == ContactKind.PHONE and not contactrules.is_mobile(c.value):
                provs = place.phone_provinces([c.normalized or c.value])
                if provs and not (provs & home):
                    out.append((c, "تلفنِ ثابتِ استانِ دیگر"))
    mobiles = [c for c in points if c.kind == ContactKind.PHONE and contactrules.is_mobile(c.value) and not contactrules.is_placeholder_phone(c.value)]
    for c in mobiles[MOBILE_CAP:]:
        if not c.is_primary:
            out.append((c, f"بیش از {MOBILE_CAP} موبایل برای یک لید"))
    seen: set[int] = set()
    unique = []
    for c, why in out:
        if c.pk not in seen:
            seen.add(c.pk)
            unique.append((c, why))
    return unique


def _address_of(lead: Lead) -> str:
    try:
        return lead.profile.address or ""
    except Exception:  # noqa: BLE001
        return ""


def _insight_of(lead: Lead):
    try:
        return lead.insight
    except LeadInsight.DoesNotExist:
        return None


def has_reach(lead: Lead) -> bool:
    return bool(lead.website or lead.instagram_url or lead.contacts.exists())


def geo_contradicts_address(lead: Lead) -> bool:
    """The map position is in one known city and the address names another: two businesses were merged into one."""
    ins = _insight_of(lead)
    if ins is None or not textnorm.valid_geo(ins.lat, ins.lon):
        return False
    named = [c for c in place.address_cities(_address_of(lead)) if c in place.CITY_CENTERS]  # only the big cities: a suburb's name next to Tehran's position is no contradiction
    here = place.geo_city(ins.lat, ins.lon)
    return bool(named and here and here not in named)


def verdict_for(lead: Lead, mission: CrawlMission):
    ins = _insight_of(lead)
    phones = [c.normalized or c.value for c in lead.contacts.all() if c.kind == ContactKind.PHONE]
    return place.verdict(
        (mission.spec or {}).get("cities") or [], address=_address_of(lead), cities_ev=[], lat=ins.lat if ins else None, lon=ins.lon if ins else None, phones=phones,
        mapped=False,
    )


def mission_tag(mission: CrawlMission) -> str:
    return finalize.clean_tag(str((mission.spec or {}).get("tag") or "")) or f"مأموریت {mission.pk}"


def drop_mission_tags(lead: Lead, missions) -> None:
    """A lead that is no longer a result of a mission loses that mission's tag («چغر · تهران» on an Isfahan gym), unless another finding still carries the same tag."""
    still = {mission_tag(f.mission) for f in lead.crawl_findings.select_related("mission")}
    for name in {mission_tag(m) for m in missions} - still:
        tag = lead.tags.filter(name_key=nz.search_key(name)[:60]).first()
        if tag is not None:
            lead.tags.remove(tag)


def trainer_tag_is_wrong(lead: Lead) -> bool:
    """The lead wears the trainer type's tag only because a gym list of badanfit.ir was mapped onto it: no coach directory read it and its name says nothing about a trainer."""
    tag = finalize.clean_tag(presets.get_type("personal_trainer").fa)
    if not lead.tags.filter(name_key=nz.search_key(tag)[:60]).exists():
        return False
    hosts = _directory_hosts(lead)
    return "badanfit.ir" in hosts and "morabiyab.com" not in hosts and not textnorm.name_has_word(lead.business_name, TRAINER_WORDS)


def repair_lead(lead: Lead, *, apply: bool, report: Counter, notes: list[str]) -> None:
    finder = is_finder_lead(lead)
    touched = touched_by_person(lead)
    # 1. a lead whose address and position contradict each other
    if finder and not touched and geo_contradicts_address(lead):
        report["deleted_mixed_city"] += 1
        if apply:
            lead.delete()
        return
    # 2. wrong-city findings
    findings = list(lead.crawl_findings.select_related("mission"))
    out = [(f, verdict_for(lead, f.mission)) for f in findings]
    out_findings = [(f, v) for f, v in out if v.state == "out"]
    if out_findings and len(out_findings) == len(findings) and finder and not touched:
        report["deleted_other_city"] += 1
        if len(notes) < 12:
            notes.append(f"{lead.business_name} ← {out_findings[0][1].reason}")
        if apply:
            lead.delete()
        return
    if out_findings:
        report["findings_removed_other_city"] += len(out_findings)
        if apply:
            for f, v in out_findings:
                CrawlFinding.objects.filter(pk=f.pk).delete()
            drop_mission_tags(lead, [f.mission for f, _ in out_findings])
            new_city = next((v.city for _, v in out_findings if v.city), "")
            if new_city and lead.city != new_city:
                Lead.objects.filter(pk=lead.pk).update(city=new_city)
                lead.city = new_city
    # 3. nobody can reach it
    if finder and not touched and not has_reach(lead):
        report["deleted_no_contact"] += 1
        if apply:
            lead.delete()
        return
    # 4. contact values that are not the business's own
    if finder:
        for c, why in bad_contacts(lead, touched=touched):
            report[f"contact_removed:{why}"] += 1
            if apply:
                if c.kind == ContactKind.INSTAGRAM and lead.instagram_url == c.value:
                    Lead.objects.filter(pk=lead.pk).update(instagram_url="")
                    lead.instagram_url = ""
                c.delete()
    # 5. the city's spelling
    canon = place.canonical_city(lead.city)
    if canon and canon != lead.city:
        report["city_normalised"] += 1
        if apply:
            Lead.objects.filter(pk=lead.pk).update(city=canon)
    # 6b. the finder's activity line «امتیازِ تناسب 59» was written with ASCII digits
    if finder:
        for act in lead.activities.filter(kind=ActivityKind.EXTRACTION, summary__startswith="مشتری‌یاب"):
            fixed = act.summary.translate(_FA_DIGITS)
            if fixed != act.summary:
                report["activity_digits_fixed"] += 1
                if apply:
                    type(act).objects.filter(pk=act.pk).update(summary=fixed)
    # 6a. a gym of badanfit.ir's «bodybuilding» list was tagged «مربی شخصی» (the old type mapping): a gym is not a trainer
    if finder and trainer_tag_is_wrong(lead):
        report["trainer_tag_removed_from_gym"] += 1
        if apply:
            lead.tags.remove(*lead.tags.filter(name_key=nz.search_key(finalize.clean_tag(presets.get_type("personal_trainer").fa))[:60]))


def resync_presets(*, apply: bool, report: Counter) -> None:
    keep = ("tag", "pitch", "exclude_words", "min_score")
    for mission in CrawlMission.objects.exclude(preset_key=""):
        preset = presets.PRESETS.get(mission.preset_key)
        if preset is None:
            continue
        spec = {**mission.spec, **{k: v for k, v in preset.spec.items() if k not in keep}}
        if spec != mission.spec:
            report["missions_resynced"] += 1
            if apply:
                from . import missions

                CrawlMission.objects.filter(pk=mission.pk).update(spec=missions.validate_spec(spec))


def run(*, apply: bool = False, limit: int | None = None) -> dict:
    report: Counter = Counter()
    notes: list[str] = []
    resync_presets(apply=apply, report=report)
    qs = Lead.objects.filter(crawl_findings__isnull=False).distinct().order_by("id")
    ids = list(qs.values_list("id", flat=True))[: limit or None]
    for lead_id in ids:
        lead = Lead.objects.filter(pk=lead_id).first()
        if lead is None:
            continue
        report["leads_looked_at"] += 1
        with transaction.atomic():
            repair_lead(lead, apply=apply, report=report, notes=notes)
    return {"applied": apply, "report": dict(report), "examples": notes}
