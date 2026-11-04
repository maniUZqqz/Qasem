"""The provider framework of automatic discovery (M3).

A *provider* turns a request («فروشگاه‌های پوشاک در همدان») into a list of ``Candidate`` businesses. It never writes to the
database and never decides what happens to a candidate: the discovery job feeds every candidate through the same
pipeline as a CSV row (``LeadDraft`` -> duplicate check -> create / «تکراری» row for a human decision), so deduplication,
merging and provenance are identical for every way a lead can arrive.

Rules every provider follows:

* only sources that PUBLISH an API / data licence for this use (OpenStreetMap's ODbL data through Overpass + Nominatim; the
  documented search APIs of Brave and Google with the operator's own key). Never a scraped result page, never Instagram,
  never a marketplace (Basalam / Digikala / Torob / Divar are on the block list of ``search_api``);
* a low request rate and an honest User-Agent (``SafeFetcher.get_api``);
* what is returned stays what the source said: nothing is invented, a value that does not validate is dropped (and counted).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ContactKind
from apps.growth_engine.leads.services.drafts import normalize_contact


class ProviderError(Exception):
    """A request the provider could not serve. ``code`` is stable, ``message`` is Persian and meant to be read by the operator.

    ``retryable`` = trying again later may well work (the service was busy / unreachable)."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class SearchQuery:
    """What the operator asked for. ``category`` is a preset key (map provider) or the words to search (search providers)."""

    category: str = ""
    city: str = ""
    country: str = "IR"
    max_results: int = 100
    require_contact: bool = True


@dataclass
class Candidate:
    """One business as the source described it (before validation into a ``LeadDraft``)."""

    name: str
    external_id: str = ""
    source_ref: str = ""
    source_url: str = ""
    category: str = ""
    city: str = ""
    address: str = ""
    phone: list[str] = field(default_factory=list)
    email: list[str] = field(default_factory=list)
    website: str = ""
    instagram: str = ""
    whatsapp: list[str] = field(default_factory=list)
    telegram: str = ""
    lat: float | None = None
    lon: float | None = None
    extra: dict = field(default_factory=dict)  # small facts worth keeping (opening hours, the snippet a search showed ...)
    dropped: list[str] = field(default_factory=list)  # values the source gave that did not validate

    @property
    def has_contact(self) -> bool:
        return bool(self.phone or self.email or self.website or self.instagram or self.whatsapp or self.telegram)

    def to_raw(self) -> dict:
        """The ``raw`` mapping ``build_draft`` understands (multi-values joined with ``;``)."""
        raw = {
            "business_name": self.name, "category": self.category, "city": self.city, "address": self.address,
            "phone": "; ".join(self.phone), "email": "; ".join(self.email), "website": self.website,
            "instagram": self.instagram, "whatsapp": "; ".join(self.whatsapp), "telegram": self.telegram,
        }
        return {k: v for k, v in raw.items() if v}

    def to_row(self, provider: str) -> dict:
        """What is stored with the job (and shown in the report): the raw fields + where it came from.
        ``provider`` is the ``SourceProvider`` value."""
        return {
            **self.to_raw(),
            "_source": {"provider": provider, "ref": self.source_ref, "url": self.source_url, "external_id": self.external_id},
            "_extra": self.extra, "_dropped": self.dropped,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Candidate":
        src = row.get("_source") or {}
        split = lambda v: [p.strip() for p in str(v or "").split(";") if p.strip()]  # noqa: E731
        return cls(
            name=row.get("business_name", ""), external_id=src.get("external_id", ""), source_ref=src.get("ref", ""),
            source_url=src.get("url", ""), category=row.get("category", ""), city=row.get("city", ""), address=row.get("address", ""),
            phone=split(row.get("phone")), email=split(row.get("email")), website=row.get("website", ""),
            instagram=row.get("instagram", ""), whatsapp=split(row.get("whatsapp")), telegram=row.get("telegram", ""),
            extra=row.get("_extra") or {}, dropped=row.get("_dropped") or [],
        )


# --------------------------------------------------------------------------- sanitising what a source gave us


def _valid_values(kind: str, values, dropped: list[str]) -> list[str]:
    """Keep the values that validate (normalised), drop the rest and remember what was dropped."""
    out: list[str] = []
    for raw in values:
        raw = nz.normalize_text(str(raw or ""))
        if not raw:
            continue
        try:
            value, key = normalize_contact(kind, raw)
        except nz.NormalizationError:
            dropped.append(raw[:60])
            continue
        if value not in out:
            out.append(value)
    return out


def sanitize(candidate: Candidate) -> Candidate:
    """Make a candidate safe to turn into a draft: invalid phone / e-mail / website / handle values are dropped, not fatal."""
    dropped = candidate.dropped
    candidate.phone = _valid_values(ContactKind.PHONE, candidate.phone, dropped)
    candidate.whatsapp = _valid_values(ContactKind.WHATSAPP, candidate.whatsapp, dropped)
    candidate.email = [e for e in _valid_values(ContactKind.EMAIL, candidate.email, dropped) if not nz.is_placeholder_email(e)]
    for attr, kind in (("website", ContactKind.WEBSITE), ("instagram", ContactKind.INSTAGRAM), ("telegram", ContactKind.TELEGRAM)):
        value = _valid_values(kind, [getattr(candidate, attr)], dropped)
        setattr(candidate, attr, value[0] if value else "")
    candidate.name = nz.normalize_text(candidate.name)[:200]
    return candidate


def split_multi(value) -> list[str]:
    """OpenStreetMap writes several values as ``a;b``; also accept a list."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v]
    return [p.strip() for p in str(value).replace("،", ";").replace(",", ";").split(";") if p.strip()]


# --------------------------------------------------------------------------- what a provider is handed


@dataclass
class ProviderContext:
    """Everything a provider needs from the outside world, injected so tests can replace each piece."""

    fetcher: object  # SafeFetcher
    settings: dict = field(default_factory=dict)
    secrets: dict = field(default_factory=dict)
    cancelled: Callable[[], bool] = lambda: False
    geocode: Callable[[str, str], dict] | None = None  # (city, country) -> place dict, cached
    note_request: Callable[[str], None] = lambda provider: None  # usage counting of keyed providers


class SearchProvider:
    """Base class. Subclasses set the class attributes and implement ``fetch``."""

    key = ""
    label = ""
    description = ""
    kind = "search"  # "map" has fixed category presets; "search" takes free words
    needs_key = False
    secret_fields: tuple[tuple[str, str], ...] = ()  # (name, Persian label) of the secrets this provider needs
    attribution = ""
    attribution_url = ""
    license_note = ""
    max_results_limit = 100
    source_provider = ""  # SourceProvider value

    def settings_schema(self) -> list[dict]:
        """Non-secret settings the panel may edit: ``[{"name", "label", "type", "default", "help"}]``."""
        return []

    def default_settings(self) -> dict:
        return {f["name"]: f.get("default") for f in self.settings_schema()}

    def categories(self) -> list[dict]:
        return []

    def readiness(self, enabled: bool, settings: dict, secrets: dict) -> tuple[bool, str]:
        """(ready, Persian reason when not ready)."""
        for name, label in self.secret_fields:  # a missing key is the first thing to fix, whether it is on or off
            if not (secrets or {}).get(name):
                return False, f"{label} وارد نشده است."
        if not enabled:
            return False, "خاموش است."
        return True, ""

    def fetch(self, query: SearchQuery, ctx: ProviderContext) -> list[Candidate]:  # pragma: no cover - interface
        raise NotImplementedError
