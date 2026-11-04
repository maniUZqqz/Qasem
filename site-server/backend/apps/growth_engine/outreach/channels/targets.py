"""Where does a message go on a given channel? The best matching contact point of the lead, or nothing (with the reason)."""
from __future__ import annotations

from dataclasses import dataclass

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ContactKind
from apps.growth_engine.leads.models import ContactPoint, Lead

from ..models import Channel
from . import SPECS


@dataclass
class Target:
    channel: str
    recipient: str  # normalised: form URL / e-mail / 09xxxxxxxxx / the messenger page address
    label: str  # shown to the team
    note: str = ""  # a caution ("this number may have no WhatsApp")
    contact_id: int | None = None


#: why a lead has no target on a channel (stable code, Persian text)
NO_TARGET = {
    Channel.CONTACT_FORM: ("no_target_url", "آدرسِ صفحهٔ تماس ندارد (اول «استخراج اطلاعاتِ تماس» را اجرا کنید)."),
    Channel.EMAIL: ("no_email", "ایمیلِ معتبر ندارد."),
    Channel.SMS: ("no_mobile", "شمارهٔ موبایل ندارد (تلفنِ ثابت پیامک نمی‌گیرد)."),
    Channel.WHATSAPP: ("no_whatsapp", "واتساپ یا شمارهٔ موبایل ندارد."),
    Channel.TELEGRAM: ("no_telegram", "تلگرام ندارد."),
    Channel.EITAA: ("no_eitaa", "ایتا ندارد."),
    Channel.BALE: ("no_bale", "بله ندارد."),
    Channel.RUBIKA: ("no_rubika", "روبیکا ندارد."),
    Channel.PHONE_CALL: ("no_phone", "تلفن ندارد."),
}
NO_CHANNEL = ("no_channel", "هیچ راهِ تماسِ فعالی برای این لید پیدا نشد (کانال‌های روشن را در «کانال‌ها» ببینید).")


def _rank(contact: ContactPoint) -> tuple[int, int, int]:
    return (1 if contact.is_primary else 0, contact.confidence or 0, -contact.pk)


def _best(contacts) -> ContactPoint | None:
    contacts = list(contacts)
    return max(contacts, key=_rank) if contacts else None


def _mobile(contact: ContactPoint) -> bool:
    try:
        return nz.normalize_phone(contact.value).kind == "mobile"
    except nz.NormalizationError:
        return False


def resolve(lead: Lead, channel: str) -> Target | None:
    """The target of ``lead`` on ``channel`` (None = this channel cannot reach the lead)."""
    contacts = list(lead.contacts.all())
    by_kind: dict[str, list[ContactPoint]] = {}
    for c in contacts:
        by_kind.setdefault(c.kind, []).append(c)

    if channel == Channel.CONTACT_FORM:
        from ..services import targets as form_targets

        contact = form_targets.pick_target(lead)
        return Target(channel, contact.value, contact.value, contact_id=contact.pk) if contact else None
    if channel == Channel.EMAIL:
        good = [c for c in by_kind.get(ContactKind.EMAIL, []) if c.value and not nz.is_placeholder_email(c.value)]
        contact = _best(good)
        return Target(channel, contact.value.lower(), contact.value.lower(), contact_id=contact.pk) if contact else None
    if channel == Channel.SMS:
        contact = _best(c for c in by_kind.get(ContactKind.PHONE, []) if _mobile(c))
        return Target(channel, contact.value, nz.format_phone_display(contact.value), contact_id=contact.pk) if contact else None
    if channel == Channel.WHATSAPP:
        contact = _best(by_kind.get(ContactKind.WHATSAPP, []))
        if contact:
            return Target(channel, contact.value, nz.format_phone_display(contact.value), contact_id=contact.pk)
        fallback = _best(c for c in by_kind.get(ContactKind.PHONE, []) if _mobile(c))
        if fallback:
            return Target(channel, fallback.value, nz.format_phone_display(fallback.value), "فقط شمارهٔ موبایل داریم؛ ممکن است واتساپ نداشته باشد.", fallback.pk)
        return None
    if channel in (Channel.TELEGRAM, Channel.EITAA, Channel.BALE, Channel.RUBIKA):
        contact = _best(by_kind.get(SPECS[channel].contact_kinds[0], []))
        return Target(channel, contact.value, contact.value, contact_id=contact.pk) if contact else None
    if channel == Channel.PHONE_CALL:
        contact = _best(by_kind.get(ContactKind.PHONE, []))
        return Target(channel, contact.value, nz.format_phone_display(contact.value), contact_id=contact.pk) if contact else None
    return None


def no_target(channel: str) -> tuple[str, str]:
    return NO_TARGET.get(channel, NO_CHANNEL)


def choose_for_auto(lead: Lead, order: list[str]) -> Target | None:
    """The first channel of ``order`` (the operator's priority, enabled ones only) that can reach the lead."""
    for channel in order:
        target = resolve(lead, channel)
        if target is not None:
            return target
    return None
