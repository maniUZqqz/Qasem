"""What the AI writer is allowed to know: the active product knowledge + what we really have on the lead.

Every fact gets a short reference (``K12`` for a knowledge item, ``F3`` for a fact about the lead, ``S1`` for the sender). The writer
must cite the references it used; a number that appears in its text but in none of the facts is flagged (see ``writer.check``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.core import normalization as nz

from ..models import KnowledgeItem

KB_CHAR_BUDGET = 7000
DESCRIPTION_CHARS = 500

_DIGITS = re.compile(r"[0-9]+(?:[.,٫][0-9]+)?")
#: Persian number words the product's own texts use ("دو هفته"): a "2" in a message is grounded if the facts say "دو"
_WORDS = {
    "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "هفت": 7, "هشت": 8, "نه": 9, "ده": 10, "یازده": 11, "دوازده": 12,
    "پانزده": 15, "بیست": 20, "سی": 30, "چهل": 40, "پنجاه": 50, "صد": 100, "هزار": 1000,
}
_WORD = re.compile(r"(?<![\w‌])(" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")(?![\w‌])")


@dataclass
class Fact:
    ref: str
    label: str
    text: str
    kind: str  # kb | lead | sender


@dataclass
class Context:
    facts: list[Fact] = field(default_factory=list)
    price_known: bool = False
    numbers: set[str] = field(default_factory=set)

    def by_ref(self) -> dict[str, Fact]:
        return {f.ref: f for f in self.facts}


def numbers_in(text: str) -> list[str]:
    """The numbers written in ``text`` as plain ASCII digits (Persian and Arabic digits are converted; separators dropped)."""
    out = []
    for raw in _DIGITS.findall(nz.to_ascii_digits(text or "")):
        out.append(re.sub(r"[.,٫]", "", raw).lstrip("0") or "0")
    return out


def numbers_known(texts: list[str]) -> set[str]:
    known: set[str] = set()
    for text in texts:
        known.update(numbers_in(text))
        known.update(str(_WORDS[w]) for w in _WORD.findall(text or ""))
    return known


def build(item) -> Context:
    ctx = Context()
    used = 0
    for k in KnowledgeItem.objects.filter(is_active=True).order_by("section", "sort_order", "id"):
        if k.needs_value:
            continue  # a price nobody typed in: not a fact
        body = k.body.strip()
        if not body:
            continue
        text = body + (f" ({k.url})" if k.url else "")
        if used + len(text) > KB_CHAR_BUDGET:
            continue
        used += len(text)
        ctx.facts.append(Fact(f"K{k.pk}", f"{k.get_section_display()}: {k.title}", text, "kb"))
        if k.section == KnowledgeItem.Section.PRICE:
            ctx.price_known = True

    lead = item.lead
    n = 0

    def add(label: str, value: str) -> None:
        nonlocal n
        value = nz.normalize_text(str(value or ""))
        if value:
            n += 1
            ctx.facts.append(Fact(f"F{n}", label, value, "lead"))

    add("نامِ کسب‌وکار", lead.business_name)
    add("دسته", lead.category)
    add("شهر", lead.city)
    if lead.country:
        add("کشور", nz.country_name_fa(lead.country))
    if lead.website:
        try:
            add("وب‌سایت", nz.clean_url(lead.website).host)
        except nz.NormalizationError:
            pass
    if lead.instagram_url:
        try:
            add("اینستاگرام", "@" + nz.parse_instagram(lead.instagram_url).handle)
        except nz.NormalizationError:
            pass
    add("توضیحاتِ ثبت‌شده", (lead.description or "")[:DESCRIPTION_CHARS])
    try:
        profile = lead.profile
    except Exception:  # noqa: BLE001 - a lead without a profile row
        profile = None
    if profile is not None:
        if profile.business_type and profile.business_type != "unknown":
            add("نوعِ کسب‌وکار", profile.get_business_type_display())
        if profile.product_categories:
            add("دسته‌های محصولی که می‌فروشد", "، ".join(profile.product_categories[:12]))
        if profile.product_names:
            add("نمونه‌ای از محصولاتش", "، ".join(profile.product_names[:12]))
        add("نشانی", profile.address)
    tags = [t.name for t in lead.tags.all()[:8]]
    if tags:
        add("برچسب‌ها", "، ".join(tags))

    settings_obj = GrowthSettings.load()
    sender = " | ".join(p for p in (settings_obj.sender_name.strip(), settings_obj.sender_company.strip()) if p)
    if sender:
        ctx.facts.append(Fact("S1", "فرستنده (خودِ ما)", sender, "sender"))

    ctx.numbers = numbers_known([f.text for f in ctx.facts])
    return ctx
