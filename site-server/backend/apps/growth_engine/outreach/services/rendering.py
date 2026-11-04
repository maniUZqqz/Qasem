"""Turning a template into the final message: placeholders, fallbacks, warnings, the sender block and the opt-out line.

Rules (never invent anything):

* ``{business_name}`` ... take the lead's own stored values. A missing value renders as empty and produces a warning;
  ``{city|شهر شما}`` gives an author-written fallback instead.
* An unknown placeholder is a validation error when a template is saved, and is left as written (with a warning) if one
  slips through.
* The closing block is added by the SYSTEM after whatever the generator wrote, so no generator (including a future AI
  writer) can drop the truthful sender identity or the opt-out line: ``name | company``, ``phone · email``, blank line,
  the opt-out sentence from Growth Settings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.growth_engine.core import normalization as nz

#: (key, Persian label, where the value comes from) - also served by ``GET /outreach/placeholders/``
PLACEHOLDERS = [
    ("business_name", "نامِ کسب‌وکار", "نامی که برای لید ثبت شده"),
    ("city", "شهر", "شهرِ ثبت‌شدهٔ لید"),
    ("country", "کشور", "کشورِ ثبت‌شدهٔ لید"),
    ("category", "دسته", "دستهٔ کسب‌وکار"),
    ("website", "وب‌سایت", "آدرسِ وب‌سایتِ لید"),
    ("domain", "دامنه", "نامِ دامنهٔ وب‌سایتِ لید"),
    ("instagram", "اینستاگرام", "نامِ کاربریِ اینستاگرامِ لید"),
]
LABELS = {key: label for key, label, _ in PLACEHOLDERS}
KEYS = tuple(LABELS)

_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?:\|([^{}\n]*))?\}")


@dataclass
class RenderResult:
    text: str
    warnings: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def lead_values(lead) -> dict[str, str]:
    """The placeholder values of a lead: stored facts only, "" when we do not know."""
    values = {key: "" for key in KEYS}
    values["business_name"] = lead.business_name or ""
    values["city"] = lead.city or ""
    values["country"] = nz.country_name_fa(lead.country) if lead.country else ""
    values["category"] = lead.category or ""
    values["website"] = lead.website or ""
    if lead.website:
        try:
            values["domain"] = nz.clean_url(lead.website).host
        except nz.NormalizationError:
            pass
    if lead.instagram_url:
        try:
            values["instagram"] = "@" + nz.parse_instagram(lead.instagram_url).handle
        except nz.NormalizationError:
            pass
    return values


def unknown_placeholders(*texts: str) -> list[str]:
    """Placeholder names used in ``texts`` that do not exist (in order, without repeats)."""
    seen: list[str] = []
    for text in texts:
        for match in _TOKEN.finditer(text or ""):
            key = match.group(1)
            if key not in LABELS and key not in seen:
                seen.append(key)
    return seen


def used_placeholders(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) for m in _TOKEN.finditer(text or "") if m.group(1) in LABELS))


def render(text: str, values: dict[str, str]) -> RenderResult:
    """Fill the placeholders of ``text``."""
    warnings: list[str] = []
    unknown: list[str] = []

    def fill(match: re.Match) -> str:
        key, fallback = match.group(1), match.group(2)
        if key not in LABELS:
            if key not in unknown:
                unknown.append(key)
            return match.group(0)
        value = (values.get(key) or "").strip()
        if value:
            return value
        if fallback is not None and fallback.strip():
            return fallback.strip()
        warning = f"«{LABELS[key]}» برای این لید خالی است و در متن جا افتاد."
        if warning not in warnings:
            warnings.append(warning)
        return ""

    out = _TOKEN.sub(fill, text or "")
    out = "\n".join(re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in out.splitlines())
    warnings += [f"جاگذارِ ناشناختهٔ {{{k}}} همان‌طور که نوشته شده ماند." for k in unknown]
    return RenderResult(text=out.strip(), warnings=warnings, unknown=unknown)


def closing_block(settings_obj) -> str:
    """Sender block + opt-out line, from Growth Settings (only the parts that are filled in)."""
    who = " | ".join(p for p in (settings_obj.sender_name.strip(), settings_obj.sender_company.strip()) if p)
    how = " · ".join(p for p in (settings_obj.sender_phone.strip(), settings_obj.sender_email.strip()) if p)
    sender = "\n".join(p for p in (who, how) if p)
    opt_out = settings_obj.opt_out_line.strip()
    return "\n\n".join(p for p in (sender, opt_out) if p)


@dataclass
class BuiltMessage:
    text: str
    subject: str
    warnings: list[str] = field(default_factory=list)


def compose(body_text: str, subject: str, settings_obj, warnings: list[str] | None = None) -> BuiltMessage:
    """Append the closing block to an already-rendered body."""
    closing = closing_block(settings_obj)
    text = body_text.strip() + (f"\n\n{closing}" if closing else "")
    return BuiltMessage(text=text, subject=subject.strip(), warnings=list(warnings or []))
