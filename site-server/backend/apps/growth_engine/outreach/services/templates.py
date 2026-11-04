"""Message templates: validation, preview, deleting."""
from __future__ import annotations

from collections.abc import Mapping

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.services.editing import ValidationFailed

from ..models import ANY, Channel, MessageTemplate
from . import generators, rendering

MAX_BODY = 3000


def validate(data: Mapping, *, partial: bool = False) -> dict:
    """Cleaned values for a template, or ``ValidationFailed`` (Persian messages, nothing saved)."""
    errors: list[dict] = []
    clean: dict = {}

    def err(field: str, code: str, message: str) -> None:
        errors.append({"field": field, "code": code, "message": message})

    if "name" in data or not partial:
        name = nz.normalize_text(str(data.get("name") or ""))
        if not name:
            err("name", "required", "نامِ قالب را بنویسید.")
        elif len(name) > 120:
            err("name", "too_long", "نامِ قالب از ۱۲۰ نویسه بلندتر است.")
        clean["name"] = name
    if "body" in data or not partial:
        body = nz.normalize_text(str(data.get("body") or ""), multiline=True)
        if not body:
            err("body", "required", "متنِ پیام را بنویسید.")
        elif len(body) > MAX_BODY:
            err("body", "too_long", f"متنِ پیام از {MAX_BODY} نویسه بلندتر است.")
        clean["body"] = body
    if "subject" in data:
        subject = nz.normalize_text(str(data.get("subject") or ""))
        if len(subject) > 200:
            err("subject", "too_long", "موضوع از ۲۰۰ نویسه بلندتر است.")
        clean["subject"] = subject
    if "language" in data:
        if data["language"] not in dict(MessageTemplate.LANGUAGES):
            err("language", "invalid", "زبان باید فارسی یا انگلیسی باشد.")
        else:
            clean["language"] = data["language"]
    if "channel" in data:
        if data["channel"] not in (ANY, *Channel.values):
            err("channel", "invalid", "کانالِ قالب معتبر نیست.")
        else:
            clean["channel"] = data["channel"]
    if "generator" in data:
        if data["generator"] not in generators.names():
            err("generator", "invalid", "روشِ ساختِ متن شناخته نشد.")
        else:
            clean["generator"] = data["generator"]
    if "is_active" in data:
        clean["is_active"] = bool(data["is_active"])
    unknown = rendering.unknown_placeholders(clean.get("body", ""), clean.get("subject", ""))
    if unknown:
        err("body", "unknown_placeholder", "جاگذارِ ناشناخته: " + "، ".join("{" + k + "}" for k in unknown) + ". از دکمه‌های جاگذار استفاده کنید.")
    if errors:
        raise ValidationFailed(errors)
    return clean


def create(data: Mapping, user=None) -> MessageTemplate:
    clean = validate(data)
    return MessageTemplate.objects.create(created_by=user if getattr(user, "is_authenticated", False) else None, **clean)


def update(template: MessageTemplate, data: Mapping) -> MessageTemplate:
    clean = validate(data, partial=True)
    for key, value in clean.items():
        setattr(template, key, value)
    template.save()
    return template


def delete(template: MessageTemplate) -> None:
    """A template used by any campaign is kept (archive it instead): its campaigns and their history refer to it."""
    if template.campaigns.exists() or template.items.exists():
        raise ValidationFailed([{"field": "template", "code": "in_use", "message": "این قالب در کمپین استفاده شده؛ به‌جای حذف، بایگانی‌اش کنید (فعال را بردارید)."}])
    template.delete()


def preview(body: str, subject: str, lead=None, channel: str | None = None) -> dict:
    """What a message would look like. Without a lead the placeholders show as ‹label› markers (nothing is made up)."""
    unknown = rendering.unknown_placeholders(body, subject)
    values = rendering.lead_values(lead, GrowthSettings.load()) if lead is not None else {k: f"‹{label}›" for k, label in rendering.LABELS.items()}
    body_result = rendering.render(body, values)
    subject_result = rendering.render(subject, values)
    channel = channel if channel in Channel.values else None
    built = rendering.compose(body_result.text, subject_result.text, GrowthSettings.load(), channel=channel)
    warnings = list(body_result.warnings) + [w for w in subject_result.warnings if w not in body_result.warnings]
    out = {"text": built.text, "subject": built.subject, "warnings": warnings if lead is not None else [w for w in warnings if "جاگذارِ ناشناخته" in w], "unknown_placeholders": unknown}
    if channel == Channel.SMS:
        from ..channels import sms
        from . import channel_config

        seg = sms.segments(built.text)
        out["sms"] = {**seg, "max_parts": channel_config.sms_max_parts(), "fits": seg["parts"] <= channel_config.sms_max_parts()}
    return out
