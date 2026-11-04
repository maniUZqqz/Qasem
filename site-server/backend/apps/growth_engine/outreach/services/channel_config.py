"""Reading and changing the settings of the channels (enabled, priority, caps, spacing, default template, SMTP).

Secret rules (the SMTP password): stored only in ``ChannelConfig.secrets`` (the database) or, as the default, in the server's
``EMAIL_HOST_PASSWORD`` (``.env``); never in code, fixtures or documents; NEVER returned (the panel is told only that one is
set); the audit trail names the changed fields, never their values.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from django.conf import settings as django_settings
from django.db import transaction

from apps.growth_engine.compliance.models import AuditKind, GrowthSettings
from apps.growth_engine.compliance.services import audit
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.core.dbretry import retry_locked
from apps.growth_engine.leads.services.editing import ValidationFailed

from .. import channels as channel_registry
from ..models import ANY, AUTO_CHANNELS, Channel, ChannelConfig, MessageTemplate, OutreachItem, SendAttempt

_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
SECRET_MAX = 300


class UnknownChannel(Exception):
    pass


def spec_or_404(key: str):
    if key not in channel_registry.SPECS:
        raise UnknownChannel(key)
    return channel_registry.SPECS[key]


@dataclass
class Effective:
    channel: str
    enabled: bool
    priority: int
    daily_cap: int | None
    spacing_min: int | None
    spacing_max: int | None
    default_template_id: int | None
    config: dict = field(default_factory=dict)  # only what the operator set (blank = "use the server's value")
    secrets: dict = field(default_factory=dict)
    has_row: bool = False


def effective(channel: str) -> Effective:
    spec = channel_registry.spec(channel)
    row = ChannelConfig.objects.filter(channel=channel).first()
    if row is None:
        return Effective(channel, spec.default_enabled, spec.default_priority, None, None, None, None)
    return Effective(
        channel, row.enabled, row.priority, row.daily_cap, row.spacing_min_seconds, row.spacing_max_seconds, row.default_template_id,
        dict(row.config or {}), dict(row.secrets or {}), has_row=True,
    )


def all_effective() -> list[Effective]:
    rows = {r.channel: r for r in ChannelConfig.objects.all()}
    out = []
    for key, spec in channel_registry.SPECS.items():
        row = rows.get(key)
        out.append(
            Effective(key, row.enabled, row.priority, row.daily_cap, row.spacing_min_seconds, row.spacing_max_seconds, row.default_template_id,
                      dict(row.config or {}), dict(row.secrets or {}), True)
            if row else Effective(key, spec.default_enabled, spec.default_priority, None, None, None, None)
        )
    return sorted(out, key=lambda e: (e.priority, channel_registry.spec(e.channel).default_priority))


def is_enabled(channel: str) -> bool:
    return effective(channel).enabled


def ordered_enabled() -> list[str]:
    """The enabled channels, first choice first."""
    return [e.channel for e in all_effective() if e.enabled]


# --------------------------------------------------------------------------- the email account as it will be used


def smtp_settings(eff: Effective | None = None) -> dict:
    """The SMTP account in force: the operator's values where set, the server's ``EMAIL_*`` settings for the rest."""
    eff = eff or effective(Channel.EMAIL)
    c = eff.config
    server_security = "ssl" if getattr(django_settings, "EMAIL_USE_SSL", False) else "starttls" if getattr(django_settings, "EMAIL_USE_TLS", False) else "none"
    growth = GrowthSettings.load()
    from_email = (c.get("from_email") or getattr(django_settings, "DEFAULT_FROM_EMAIL", "") or "").strip()
    return {
        "host": (c.get("host") or getattr(django_settings, "EMAIL_HOST", "") or "").strip(),
        "port": int(c.get("port") or getattr(django_settings, "EMAIL_PORT", 587) or 587),
        "security": c.get("security") or server_security,
        "username": (c.get("username") or getattr(django_settings, "EMAIL_HOST_USER", "") or "").strip(),
        "password": eff.secrets.get("smtp_password") or getattr(django_settings, "EMAIL_HOST_PASSWORD", "") or "",
        "from_email": from_email,
        "from_name": (c.get("from_name") or growth.sender_company or growth.sender_name or "").strip(),
        "reply_to": (c.get("reply_to") or growth.sender_email or "").strip(),
        "timeout": int(c.get("timeout") or getattr(django_settings, "EMAIL_TIMEOUT", 20) or 20),
    }


def email_problems(eff: Effective | None = None) -> list[str]:
    cfg = smtp_settings(eff)
    problems = []
    if not cfg["host"]:
        problems.append("سرورِ ایمیل (SMTP) وارد نشده است.")
    if not cfg["from_email"]:
        problems.append("ایمیلِ فرستنده (From) وارد نشده است.")
    else:
        try:
            nz.normalize_email(cfg["from_email"])
        except nz.NormalizationError:
            problems.append("ایمیلِ فرستنده درست نیست.")
    if cfg["username"] and not cfg["password"]:
        problems.append("رمزِ ایمیل وارد نشده است.")
    if not cfg["reply_to"]:
        problems.append("ایمیلِ فرستنده در «تنظیماتِ جذب مشتری» پر نشده؛ پاسخ‌ها به جایی نمی‌رسد.")
    return problems


# --------------------------------------------------------------------------- readiness


def sms_availability() -> tuple[bool, str, dict]:
    from ..channels import sms

    return sms.availability()


def readiness(channel: str) -> tuple[bool, str]:
    """(ready to be used, Persian reason when not)."""
    if channel == Channel.EMAIL:
        problems = email_problems()
        return (not problems, " ".join(problems))
    if channel == Channel.SMS:
        ok, reason, _ = sms_availability()
        return ok, reason
    return True, ""


# --------------------------------------------------------------------------- the day's counters (for the panel and the send job)


def sent_today(channel: str) -> int:
    from django.utils import timezone

    return SendAttempt.objects.filter(channel=channel, attempted_at__date=timezone.localdate()).count()


def cap_remaining(channel: str) -> int | None:
    """How many more attempts this channel may make today (None = no per-channel cap)."""
    cap = effective(channel).daily_cap
    return None if cap is None else max(0, cap - sent_today(channel))


def spacing_for(channel: str, growth: GrowthSettings | None = None) -> tuple[int, int]:
    """(min, max) seconds between two sends on this channel: its own setting, else the global one."""
    growth = growth or GrowthSettings.load()
    eff = effective(channel)
    lo = eff.spacing_min if eff.spacing_min is not None else growth.spacing_min_seconds
    hi = eff.spacing_max if eff.spacing_max is not None else growth.spacing_max_seconds
    return lo, max(lo, hi)


def capped_channels() -> set[str]:
    """Channels whose own daily cap is used up right now."""
    return {c for c in AUTO_CHANNELS if cap_remaining(c) == 0}


# --------------------------------------------------------------------------- what the panel sees


def view_config(channel: str, eff: Effective) -> dict:
    """The non-secret values for the form: what the operator set, plus (email) what is in force and whether it comes from the server."""
    out = {"set": dict(eff.config)}
    if channel == Channel.EMAIL:
        cfg = smtp_settings(eff)
        out["in_force"] = {k: v for k, v in cfg.items() if k != "password"}
        out["from_server"] = [k for k in ("host", "port", "security", "username", "from_email") if not eff.config.get(k)]
        out["password_from_server"] = bool(not eff.secrets.get("smtp_password") and getattr(django_settings, "EMAIL_HOST_PASSWORD", ""))
    elif channel == Channel.SMS:
        out["in_force"] = {"max_parts": sms_max_parts(eff)}
    return out


def sms_max_parts(eff: Effective | None = None) -> int:
    eff = eff or effective(Channel.SMS)
    try:
        return max(1, min(3, int(eff.config.get("max_parts") or 2)))
    except (TypeError, ValueError):
        return 2


def snapshot(channel: str) -> dict:
    spec = channel_registry.spec(channel)
    eff = effective(channel)
    ready, reason = readiness(channel)
    secrets = {}
    for name, label in spec.secret_fields:
        server = bool(name == "smtp_password" and getattr(django_settings, "EMAIL_HOST_PASSWORD", ""))
        secrets[name] = {"label": label, "is_set": bool(eff.secrets.get(name)), "server_default": server}
    template = MessageTemplate.objects.filter(pk=eff.default_template_id).first() if eff.default_template_id else None
    return {
        "key": channel, "label": spec.label, "kind": spec.kind, "description": spec.description, "hint": spec.hint,
        "enabled": eff.enabled, "priority": eff.priority, "daily_cap": eff.daily_cap,
        "spacing_min_seconds": eff.spacing_min, "spacing_max_seconds": eff.spacing_max,
        "default_template": {"id": template.pk, "name": template.name} if template else None,
        "ready": ready, "not_ready_reason": "" if ready else reason,
        "config_schema": list(spec.config_schema), "config": view_config(channel, eff), "secrets": secrets,
        "sent_today": sent_today(channel) if spec.kind == "auto" else None, "cap_remaining": cap_remaining(channel) if spec.kind == "auto" else None,
        "needs_app": channel == Channel.SMS and not ready and "NM-Mobile" in reason,
    }


def snapshot_all() -> list[dict]:
    order = {e.channel: i for i, e in enumerate(all_effective())}
    return sorted((snapshot(c) for c in channel_registry.SPECS), key=lambda s: order[s["key"]])


# --------------------------------------------------------------------------- changing them


def _int(value, low, high, label, field_name, errors, *, allow_none=False):
    if value in (None, "") and allow_none:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append({"field": field_name, "code": "invalid_number", "message": f"«{label}» باید عدد باشد."})
        return None
    if not low <= number <= high:
        errors.append({"field": field_name, "code": "out_of_range", "message": f"«{label}» باید بین {low} و {high} باشد."})
        return None
    return number


def _clean_config(channel: str, values: Mapping, errors: list[dict]) -> dict:
    spec = channel_registry.spec(channel)
    schema = {s["name"]: s for s in spec.config_schema}
    out: dict = {}
    for name, value in values.items():
        item = schema.get(name)
        if item is None:
            errors.append({"field": name, "code": "unknown_setting", "message": f"تنظیمِ «{name}» برای این کانال وجود ندارد."})
            continue
        label, kind = item["label"], item["type"]
        if value in (None, ""):
            out[name] = ""  # back to "use the server's value"
            continue
        if kind == "int":
            number = _int(value, item.get("min", 0), item.get("max", 10**6), label, name, errors)
            if number is not None:
                out[name] = number
        elif kind == "choice":
            if str(value) not in {c[0] for c in item["choices"]}:
                errors.append({"field": name, "code": "invalid_choice", "message": f"«{label}» یکی از گزینه‌های فهرست باشد."})
            else:
                out[name] = str(value)
        elif kind == "email":
            try:
                out[name] = nz.normalize_email(str(value))
            except nz.NormalizationError as exc:
                errors.append({"field": name, "code": exc.code, "message": f"«{label}»: {exc.message}"})
        else:
            text = nz.normalize_text(str(value))
            if name == "host" and not _HOST.match(text):
                errors.append({"field": name, "code": "invalid_host", "message": "نامِ سرور درست نیست (مثلاً smtp.example.com)."})
            elif len(text) > 200:
                errors.append({"field": name, "code": "too_long", "message": f"«{label}» از ۲۰۰ نویسه بلندتر است."})
            else:
                out[name] = text
    return out


def update(channel: str, data: Mapping, actor) -> ChannelConfig:
    """Apply ``{"enabled"?, "priority"?, "daily_cap"?, "spacing_min_seconds"?, "spacing_max_seconds"?, "default_template_id"?,
    "config"?: {...}, "secrets"?: {...}, "clear_secrets"?: [...]}``. All or nothing."""
    spec = spec_or_404(channel)
    errors: list[dict] = []
    eff = effective(channel)
    changed: list[str] = []
    new: dict = {}

    if "priority" in data:
        value = _int(data["priority"], 1, 1000, "اولویت", "priority", errors)
        if value is not None:
            new["priority"] = value
    if "daily_cap" in data:
        if spec.kind != "auto":
            errors.append({"field": "daily_cap", "code": "not_applicable", "message": "این کانال را خودتان می‌فرستید؛ سقفِ روزانه ندارد."})
        else:
            new["daily_cap"] = _int(data["daily_cap"], 1, 500, "سقفِ روزانه", "daily_cap", errors, allow_none=True)
    lo = eff.spacing_min
    hi = eff.spacing_max
    if "spacing_min_seconds" in data or "spacing_max_seconds" in data:
        if spec.kind != "auto":
            errors.append({"field": "spacing_min_seconds", "code": "not_applicable", "message": "این کانال را خودتان می‌فرستید؛ فاصله ندارد."})
        else:
            if "spacing_min_seconds" in data:
                lo = _int(data["spacing_min_seconds"], 10, 3600, "حداقل فاصله", "spacing_min_seconds", errors, allow_none=True)
                new["spacing_min_seconds"] = lo
            if "spacing_max_seconds" in data:
                hi = _int(data["spacing_max_seconds"], 10, 3600, "حداکثر فاصله", "spacing_max_seconds", errors, allow_none=True)
                new["spacing_max_seconds"] = hi
            if (lo is None) != (hi is None):
                errors.append({"field": "spacing_max_seconds", "code": "both_or_neither", "message": "حداقل و حداکثرِ فاصله را با هم پر کنید (یا هر دو را خالی بگذارید)."})
            elif lo is not None and hi is not None and lo > hi:
                errors.append({"field": "spacing_max_seconds", "code": "range", "message": "حداکثرِ فاصله نباید از حداقل کمتر باشد."})
    if "default_template_id" in data:
        tid = data["default_template_id"]
        if tid in (None, ""):
            new["default_template_id"] = None
        else:
            template = MessageTemplate.objects.filter(pk=tid, is_active=True).first()
            if template is None or template.channel not in (ANY, channel):
                errors.append({"field": "default_template_id", "code": "bad_template", "message": "قالبِ انتخابی فعال نیست یا برای این کانال نوشته نشده."})
            else:
                new["default_template_id"] = template.pk

    config = dict(eff.config)
    if data.get("config"):
        cleaned = _clean_config(channel, data["config"], errors)
        for key, value in cleaned.items():
            if value == "":
                config.pop(key, None)
            else:
                config[key] = value
    secrets = dict(eff.secrets)
    allowed = dict(spec.secret_fields)
    for name, value in (data.get("secrets") or {}).items():
        if name not in allowed:
            errors.append({"field": name, "code": "unknown_secret", "message": f"کلیدِ «{name}» برای این کانال وجود ندارد."})
            continue
        text = str(value or "")
        if not text:
            continue  # an empty box keeps the stored one
        if len(text) > SECRET_MAX or re.search(r"[\x00-\x1f\x7f]", text):
            errors.append({"field": name, "code": "invalid_secret", "message": f"«{allowed[name]}» درست نیست."})
            continue
        secrets[name] = text
        changed.append(f"secrets.{name}")
    for name in data.get("clear_secrets") or []:
        if name in allowed and secrets.pop(name, None) is not None:
            changed.append(f"secrets.{name}")

    enabled = bool(data["enabled"]) if "enabled" in data else eff.enabled
    if errors:
        raise ValidationFailed(errors)
    if enabled and spec.kind == "auto" and channel != Channel.CONTACT_FORM:
        preview = Effective(channel, True, new.get("priority", eff.priority), None, None, None, None, config, secrets)
        if channel == Channel.EMAIL:
            problems = email_problems(preview)
            if problems:
                raise ValidationFailed([{"field": "enabled", "code": "not_ready", "message": "ایمیل تا وقتی ناقص است روشن نمی‌شود: " + " ".join(problems)}])
        else:
            ready, reason = readiness(channel)
            if not ready:
                raise ValidationFailed([{"field": "enabled", "code": "not_ready", "message": f"این کانال هنوز آماده نیست: {reason}"}])

    for key in ("priority", "daily_cap", "spacing_min_seconds", "spacing_max_seconds", "default_template_id"):
        if key in new:
            current = {"priority": eff.priority, "daily_cap": eff.daily_cap, "spacing_min_seconds": eff.spacing_min,
                       "spacing_max_seconds": eff.spacing_max, "default_template_id": eff.default_template_id}[key]
            if new[key] != current:
                changed.append(key)
    if config != eff.config:
        changed += [f"config.{k}" for k in sorted(set(config) ^ set(eff.config) | {k for k in config if config.get(k) != eff.config.get(k)})]
    if enabled != eff.enabled:
        changed.append("enabled")

    def save() -> ChannelConfig:
        with transaction.atomic():
            row, _ = ChannelConfig.objects.get_or_create(channel=channel, defaults={"priority": spec.default_priority, "enabled": spec.default_enabled})
            row.enabled = enabled
            row.config, row.secrets = config, secrets
            if "priority" in new:
                row.priority = new["priority"]
            if "daily_cap" in new:
                row.daily_cap = new["daily_cap"]
            if "spacing_min_seconds" in new:
                row.spacing_min_seconds = new["spacing_min_seconds"]
            if "spacing_max_seconds" in new:
                row.spacing_max_seconds = new["spacing_max_seconds"]
            if "default_template_id" in new:
                row.default_template_id = new["default_template_id"]
            row.updated_by = actor if getattr(actor, "is_authenticated", False) else None
            row.save()
            return row

    row = retry_locked(save)
    if changed:
        # field NAMES only - the SMTP password must never reach the audit trail
        audit.log(AuditKind.SETTINGS, actor, f"کانالِ «{spec.label}» عوض شد: " + "، ".join(sorted(set(changed))), {"channel": channel, "fields": sorted(set(changed))})
    return row


def reorder(order: list[str], actor) -> None:
    """Set the priority of every channel from a list of keys (first = tried first). Channels not listed keep their relative place after."""
    if len(set(order)) != len(order) or any(k not in channel_registry.SPECS for k in order):
        raise ValidationFailed([{"field": "order", "code": "invalid", "message": "فهرستِ اولویت درست نیست."}])
    rest = [e.channel for e in all_effective() if e.channel not in order]
    final = [*order, *rest]

    def save() -> None:
        with transaction.atomic():
            for position, key in enumerate(final, 1):
                spec = channel_registry.spec(key)
                row, _ = ChannelConfig.objects.get_or_create(channel=key, defaults={"enabled": spec.default_enabled})
                row.priority = position * 10
                row.save(update_fields=["priority", "updated_at"])

    retry_locked(save)
    audit.log(AuditKind.SETTINGS, actor, "اولویتِ کانال‌ها عوض شد: " + "، ".join(final), {"order": final})


def default_template(channel: str) -> MessageTemplate | None:
    """The template a channel falls back to when a campaign does not name one (auto campaigns)."""
    eff = effective(channel)
    if eff.default_template_id:
        template = MessageTemplate.objects.filter(pk=eff.default_template_id, is_active=True).first()
        if template:
            return template
    return MessageTemplate.objects.filter(channel=channel, is_active=True).order_by("id").first()


def in_use_count(channel: str) -> int:
    return OutreachItem.objects.filter(channel=channel).count()
