"""Where do we send the message? The lead's own contact / ticket page found by extraction."""
from __future__ import annotations

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ContactKind
from apps.growth_engine.leads.models import ContactPoint, Lead

FORM_LABEL = "فرم تماس"
TICKET_LABEL = "تیکت/پشتیبانی"


def _rank(contact: ContactPoint) -> tuple[int, int, int]:
    label = contact.label or ""
    kind_rank = 3 if label.startswith(FORM_LABEL) else 2 if label.startswith(TICKET_LABEL) else 1
    return kind_rank, contact.confidence or 0, -contact.pk


def pick_target(lead: Lead) -> ContactPoint | None:
    """The best contact-form ContactPoint: a real form first, then a ticket page, then by confidence."""
    contacts = list(lead.contacts.filter(kind=ContactKind.CONTACT_FORM))
    return max(contacts, key=_rank) if contacts else None


def target_url(lead: Lead) -> str:
    contact = pick_target(lead)
    return contact.value if contact else ""


def domain_key(lead: Lead) -> str:
    """Identity of the lead's website ("" if none): at most one message per site per campaign."""
    if not lead.website:
        return ""
    try:
        return nz.clean_url(lead.website).identity[:255]
    except nz.NormalizationError:
        return ""
