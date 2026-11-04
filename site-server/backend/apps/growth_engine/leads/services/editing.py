"""Manual editing of a lead: fields, contact points, notes, tags, status, archive.

All of it writes to the lead's history; every changed field is stamped as coming from
``manual`` (field-level provenance). Identifier changes (website, Instagram, phone, e-mail)
are checked against the registry first: taking a value that belongs to another lead raises
``DuplicateError`` and changes nothing.
"""
from __future__ import annotations

from collections.abc import Mapping

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.sources import provenance

from ..choices import IDENTIFIER_KINDS, ActivityKind, BusinessType, ContactKind, LeadStatus
from ..models import BusinessProfile, ContactPoint, Lead, LeadNote
from . import history
from .dedupe import find_duplicates
from .drafts import LIMITS, FieldErrors, normalize_contact
from .intake import DuplicateError
from .tags import resolve_tags


class ValidationFailed(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("validation failed")
        self.errors = errors


def _actor(actor):
    return actor if actor is not None and getattr(actor, "is_authenticated", False) else None


# --------------------------------------------------------------------------- lead fields


def update_lead(lead: Lead, data: Mapping, actor=None) -> list[str]:
    """Apply a partial edit. Returns the names of the fields that actually changed."""
    actor = _actor(actor)
    actor_id = actor.pk if actor else None
    errors = FieldErrors()
    new_values: dict = {}

    for name in ("business_name", "category", "description", "city"):
        if name in data:
            value = nz.normalize_text(str(data[name] or ""), multiline=(name == "description"))
            if len(value) > LIMITS[name]:
                errors.add(name, "too_long", f"از {LIMITS[name]} نویسه بلندتر است.")
            new_values[name] = value
    if "country" in data:
        try:
            new_values["country"] = nz.normalize_country(str(data["country"] or ""))
        except nz.NormalizationError as exc:
            errors.add("country", exc.code, exc.message)
    if "status" in data:
        if data["status"] not in LeadStatus.values:
            errors.add("status", "invalid_status", "وضعیت معتبر نیست.")
        else:
            new_values["status"] = data["status"]
    if "is_archived" in data:
        new_values["is_archived"] = bool(data["is_archived"])

    identifier_changes: dict[str, tuple[str, str] | None] = {}
    for key, kind, attr in (("website", ContactKind.WEBSITE, "website"), ("instagram_url", ContactKind.INSTAGRAM, "instagram_url")):
        if key in data or (key == "instagram_url" and "instagram" in data):
            raw = data.get(key, data.get("instagram")) or ""
            if not str(raw).strip():
                identifier_changes[attr] = None
            else:
                try:
                    identifier_changes[attr] = normalize_contact(kind, str(raw))
                except nz.NormalizationError as exc:
                    errors.add(key, exc.code, exc.message)

    profile_data = data.get("profile") if isinstance(data.get("profile"), Mapping) else None
    profile_values = _validate_profile(profile_data, errors) if profile_data is not None else {}
    tag_names = None
    if "tags" in data:
        tag_names = [nz.normalize_text(t)[:50] for t in nz.split_multi(data["tags"])]
        if len(tag_names) > 20:
            errors.add("tags", "too_many_tags", "حداکثر ۲۰ برچسب مجاز است.")
    if errors:
        raise ValidationFailed(list(errors))

    # identifiers must not belong to another lead
    for attr, pair in identifier_changes.items():
        if pair is None:
            continue
        kind = ContactKind.WEBSITE if attr == "website" else ContactKind.INSTAGRAM
        matches = find_duplicates([(kind, pair[1])], exclude_lead_id=lead.pk)
        if matches:
            raise DuplicateError(matches)

    changed: list[str] = []
    with transaction.atomic():
        lead = Lead.objects.get(pk=lead.pk)
        prov = dict(lead.provenance or {})
        changes: dict[str, dict] = {}
        old_status, old_archived = lead.status, lead.is_archived

        for name, value in new_values.items():
            old = getattr(lead, name)
            if old == value:
                continue
            setattr(lead, name, value)
            changed.append(name)
            if name not in ("status", "is_archived"):
                changes[name] = {"old": history.short(old), "new": history.short(value)}
                provenance.stamp(prov, name, provenance.MANUAL, actor_id)

        for attr, pair in identifier_changes.items():
            kind = ContactKind.WEBSITE if attr == "website" else ContactKind.INSTAGRAM
            old = getattr(lead, attr)
            new_value = pair[0] if pair else ""
            if old == new_value:
                continue
            _swap_primary_identifier(lead, kind, old, pair, actor)
            setattr(lead, attr, new_value)
            changed.append(attr)
            changes[attr] = {"old": old, "new": new_value}
            provenance.stamp(prov, attr, provenance.MANUAL, actor_id)

        if profile_values:
            profile_changes = _apply_profile(lead, profile_values, actor_id)
            for name, change in profile_changes.items():
                changed.append(f"profile.{name}")
                changes[f"profile.{name}"] = change

        field_changes = {k: v for k, v in changes.items()}
        if field_changes:
            history.log_activity(
                lead, ActivityKind.UPDATED, actor=actor, source_ref=provenance.MANUAL,
                summary="ویرایش: " + "، ".join(_label(k) for k in field_changes), data={"changes": field_changes},
            )
        if lead.status != old_status:
            history.log_activity(
                lead, ActivityKind.STATUS_CHANGED, actor=actor,
                summary=f"{LeadStatus(old_status).label} ← {LeadStatus(lead.status).label}",
                data={"old": old_status, "new": lead.status},
            )
        if lead.is_archived != old_archived:
            history.log_activity(lead, ActivityKind.ARCHIVED if lead.is_archived else ActivityKind.UNARCHIVED, actor=actor)
        if tag_names is not None:
            changed += _set_tags(lead, tag_names, actor)
        if changed:
            lead.provenance = prov
            lead.save()
    return changed


_LABELS = {
    "business_name": "نام", "category": "دسته", "description": "توضیحات", "city": "شهر", "country": "کشور",
    "website": "وب‌سایت", "instagram_url": "اینستاگرام",
    "profile.language": "زبان", "profile.business_type": "نوع کسب‌وکار", "profile.address": "نشانی",
    "profile.product_categories": "دسته‌های محصول", "profile.product_names": "نام محصولات",
}


def _label(key: str) -> str:
    return _LABELS.get(key, key)


def _validate_profile(data: Mapping, errors: FieldErrors) -> dict:
    values: dict = {}
    if "language" in data:
        language = nz.normalize_text(str(data["language"] or "")).lower()
        if language and not (2 <= len(language) <= 3 and language.isalpha() and language.isascii()):
            errors.add("profile.language", "invalid_language", "زبان باید کد کوتاهی مثل fa یا en باشد.")
        values["language"] = language
    if "business_type" in data:
        if data["business_type"] not in BusinessType.values:
            errors.add("profile.business_type", "invalid_business_type", "نوعِ کسب‌وکار معتبر نیست.")
        else:
            values["business_type"] = data["business_type"]
    if "address" in data:
        address = nz.normalize_text(str(data["address"] or ""))
        if len(address) > LIMITS["address"]:
            errors.add("profile.address", "too_long", f"از {LIMITS['address']} نویسه بلندتر است.")
        values["address"] = address
    for key in ("product_categories", "product_names"):
        if key in data:
            items = [nz.normalize_text(v)[:120] for v in nz.split_multi(data[key])]
            values[key] = [v for v in items if v][:50]
    return values


def _apply_profile(lead: Lead, values: dict, actor_id) -> dict:
    profile, _ = BusinessProfile.objects.get_or_create(lead=lead)
    prov = dict(profile.provenance or {})
    changes: dict = {}
    for name, value in values.items():
        old = getattr(profile, name)
        if old == value:
            continue
        setattr(profile, name, value)
        provenance.stamp(prov, name, provenance.MANUAL, actor_id)
        changes[name] = {"old": history.short(old), "new": history.short(value)}
    if changes:
        profile.provenance = prov
        profile.save()
    return changes


def _swap_primary_identifier(lead: Lead, kind: str, old_value: str, new: tuple[str, str] | None, actor) -> None:
    """Make the lead's website / Instagram field and its contact registry agree after an edit."""
    contacts = lead.contacts.filter(kind=kind)
    old_contact = next((c for c in contacts if c.value == old_value), None) if old_value else None
    if new is None:
        if old_contact:
            old_contact.delete()
        return
    value, key = new
    existing = next((c for c in contacts if c.normalized == key), None)
    if existing:
        if old_contact and old_contact.pk != existing.pk:
            old_contact.delete()
        if existing.value != value:
            existing.value = value
            existing.save(update_fields=["value", "updated_at"])
        return
    if old_contact:
        old_contact.value, old_contact.normalized = value, key
        old_contact.source_ref, old_contact.source_url, old_contact.evidence, old_contact.confidence = provenance.MANUAL, "", "", None
        old_contact.save()
        return
    ContactPoint.objects.create(lead=lead, kind=kind, value=value, normalized=key, is_primary=not contacts.exists(), source_ref=provenance.MANUAL)


def _set_tags(lead: Lead, names: list[str], actor) -> list[str]:
    wanted = resolve_tags(names)
    have = {t.pk: t for t in lead.tags.all()}
    wanted_ids = {t.pk for t in wanted}
    added = [t for t in wanted if t.pk not in have]
    removed = [t for pk, t in have.items() if pk not in wanted_ids]
    if added:
        lead.tags.add(*added)
        history.log_activity(lead, ActivityKind.TAG_ADDED, actor=actor, summary="، ".join(t.name for t in added), data={"tags": [t.name for t in added]})
    if removed:
        lead.tags.remove(*removed)
        history.log_activity(lead, ActivityKind.TAG_REMOVED, actor=actor, summary="، ".join(t.name for t in removed), data={"tags": [t.name for t in removed]})
    return ["tags"] if (added or removed) else []


# --------------------------------------------------------------------------- contact points


def add_contact(lead: Lead, kind: str, raw_value: str, *, label: str = "", actor=None) -> ContactPoint:
    actor = _actor(actor)
    if kind not in ContactKind.values:
        raise ValidationFailed([{"field": "kind", "code": "invalid_kind", "message": "نوعِ راه تماس معتبر نیست."}])
    try:
        value, key = normalize_contact(kind, raw_value)
    except nz.NormalizationError as exc:
        raise ValidationFailed([{"field": "value", "code": exc.code, "message": exc.message}]) from exc
    if kind in IDENTIFIER_KINDS:
        matches = find_duplicates([(kind, key)], exclude_lead_id=lead.pk)
        if matches:
            raise DuplicateError(matches)
        if lead.contacts.filter(kind=kind, normalized=key).exists():
            raise ValidationFailed([{"field": "value", "code": "already_exists", "message": "این راه تماس از قبل برای همین لید ثبت شده است."}])
    elif key and lead.contacts.filter(kind=kind, normalized=key).exists():
        raise ValidationFailed([{"field": "value", "code": "already_exists", "message": "این راه تماس از قبل برای همین لید ثبت شده است."}])
    label = nz.normalize_text(label)[:80]
    try:
        with transaction.atomic():
            contact = ContactPoint.objects.create(
                lead=lead, kind=kind, value=value, normalized=key, label=label,
                is_primary=not lead.contacts.filter(kind=kind, is_primary=True).exists(), source_ref=provenance.MANUAL,
            )
            _sync_lead_field(lead, kind)
            history.log_activity(
                lead, ActivityKind.CONTACT_ADDED, actor=actor, source_ref=provenance.MANUAL,
                summary=f"{ContactKind(kind).label}: {value}", data={"kind": kind, "value": value},
            )
    except IntegrityError:
        raise DuplicateError(find_duplicates([(kind, key)], exclude_lead_id=lead.pk)) from None
    return contact


def update_contact(contact: ContactPoint, data: Mapping, actor=None) -> ContactPoint:
    actor = _actor(actor)
    lead = contact.lead
    old_value = contact.value
    with transaction.atomic():
        if "value" in data and str(data["value"]).strip() != contact.value:
            try:
                value, key = normalize_contact(contact.kind, str(data["value"]))
            except nz.NormalizationError as exc:
                raise ValidationFailed([{"field": "value", "code": exc.code, "message": exc.message}]) from exc
            if contact.kind in IDENTIFIER_KINDS:
                matches = find_duplicates([(contact.kind, key)], exclude_lead_id=lead.pk)
                if matches:
                    raise DuplicateError(matches)
            if key and lead.contacts.filter(kind=contact.kind, normalized=key).exclude(pk=contact.pk).exists():
                raise ValidationFailed([{"field": "value", "code": "already_exists", "message": "این راه تماس از قبل برای همین لید ثبت شده است."}])
            contact.value, contact.normalized = value, key
            contact.source_ref, contact.source_url, contact.evidence, contact.confidence = provenance.MANUAL, "", "", None
        if "label" in data:
            contact.label = nz.normalize_text(str(data["label"] or ""))[:80]
        if data.get("is_primary") is True and not contact.is_primary:
            lead.contacts.filter(kind=contact.kind, is_primary=True).update(is_primary=False)
            contact.is_primary = True
        try:
            contact.save()
        except IntegrityError:
            raise DuplicateError(find_duplicates([(contact.kind, contact.normalized)], exclude_lead_id=lead.pk)) from None
        if contact.kind in (ContactKind.WEBSITE, ContactKind.INSTAGRAM):
            attr = "website" if contact.kind == ContactKind.WEBSITE else "instagram_url"
            if getattr(lead, attr) == old_value and old_value != contact.value:
                setattr(lead, attr, contact.value)
                lead.save(update_fields=[attr, "updated_at"])
        history.log_activity(
            lead, ActivityKind.CONTACT_UPDATED, actor=actor, source_ref=provenance.MANUAL,
            summary=f"{ContactKind(contact.kind).label}: {contact.value}",
            data={"kind": contact.kind, "old": old_value, "new": contact.value},
        )
    return contact


def remove_contact(contact: ContactPoint, actor=None) -> None:
    actor = _actor(actor)
    lead = contact.lead
    kind, value, was_primary = contact.kind, contact.value, contact.is_primary
    with transaction.atomic():
        contact.delete()
        if was_primary:
            nxt = lead.contacts.filter(kind=kind).order_by("id").first()
            if nxt:
                nxt.is_primary = True
                nxt.save(update_fields=["is_primary", "updated_at"])
        _sync_lead_field(lead, kind, removed_value=value)
        history.log_activity(
            lead, ActivityKind.CONTACT_REMOVED, actor=actor, summary=f"{ContactKind(kind).label}: {value}", data={"kind": kind, "value": value}
        )


def _sync_lead_field(lead: Lead, kind: str, removed_value: str | None = None) -> None:
    """Keep ``Lead.website`` / ``Lead.instagram_url`` equal to a real contact of that kind."""
    if kind not in (ContactKind.WEBSITE, ContactKind.INSTAGRAM):
        return
    attr = "website" if kind == ContactKind.WEBSITE else "instagram_url"
    current = getattr(lead, attr)
    contacts = list(lead.contacts.filter(kind=kind).order_by("-is_primary", "id"))
    if current and any(c.value == current for c in contacts):
        return
    if not current and not contacts:
        return
    replacement = contacts[0].value if contacts else ""
    if replacement != current:
        setattr(lead, attr, replacement)
        lead.save(update_fields=[attr, "updated_at"])


# --------------------------------------------------------------------------- notes


def add_note(lead: Lead, body: str, actor=None) -> LeadNote:
    actor = _actor(actor)
    body = nz.normalize_text(body, multiline=True)
    if not body:
        raise ValidationFailed([{"field": "body", "code": "empty", "message": "متنِ یادداشت خالی است."}])
    if len(body) > LIMITS["note"]:
        raise ValidationFailed([{"field": "body", "code": "too_long", "message": f"یادداشت از {LIMITS['note']} نویسه بلندتر است."}])
    with transaction.atomic():
        note = LeadNote.objects.create(lead=lead, author=actor, body=body)
        history.log_activity(lead, ActivityKind.NOTE_ADDED, actor=actor, summary=history.short(body, 120), data={"note_id": note.pk})
        Lead.objects.filter(pk=lead.pk).update(updated_at=timezone.now())
    return note


def edit_note(note: LeadNote, body: str, actor=None) -> LeadNote:
    actor = _actor(actor)
    body = nz.normalize_text(body, multiline=True)
    if not body:
        raise ValidationFailed([{"field": "body", "code": "empty", "message": "متنِ یادداشت خالی است."}])
    old = note.body
    note.body = body[: LIMITS["note"]]
    with transaction.atomic():
        note.save()
        history.log_activity(
            note.lead, ActivityKind.NOTE_EDITED, actor=actor, summary=history.short(body, 120),
            data={"note_id": note.pk, "old": history.short(old, 300)},
        )
    return note


def delete_note(note: LeadNote, actor=None) -> None:
    actor = _actor(actor)
    with transaction.atomic():
        history.log_activity(
            note.lead, ActivityKind.NOTE_DELETED, actor=actor, summary=history.short(note.body, 120),
            data={"note_id": note.pk, "body": history.short(note.body, 500)},
        )
        note.delete()
