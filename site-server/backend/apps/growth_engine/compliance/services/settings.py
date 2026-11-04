"""Reading and changing Growth Settings (validated, audited)."""
from __future__ import annotations

from collections.abc import Mapping

from apps.growth_engine.core import normalization as nz

from ..models import AuditKind, GrowthSettings
from . import audit, limits


class SettingsInvalid(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("invalid settings")
        self.errors = errors


def get_settings() -> GrowthSettings:
    return GrowthSettings.load()


def snapshot(obj: GrowthSettings | None = None) -> dict:
    """Everything the Settings page shows, in one dict."""
    obj = obj or get_settings()
    return {
        "sending_enabled": obj.sending_enabled,
        "emergency_stop": obj.emergency_stop,
        "sender_name": obj.sender_name,
        "sender_company": obj.sender_company,
        "sender_phone": obj.sender_phone,
        "sender_email": obj.sender_email,
        "sender_website": obj.sender_website,
        "opt_out_line": obj.opt_out_line,
        "daily_cap": obj.daily_cap,
        "spacing_min_seconds": obj.spacing_min_seconds,
        "spacing_max_seconds": obj.spacing_max_seconds,
        "updated_at": obj.updated_at,
        "ready": obj.readiness(),
        "sent_today": limits.sent_today(),
        "cap_remaining": limits.cap_remaining(obj),
    }


def update_settings(data: Mapping, actor) -> GrowthSettings:
    """Apply a partial update. Raises ``SettingsInvalid`` (nothing is saved) when any value is wrong."""
    current = get_settings()
    errors: list[dict] = []
    new: dict = {}

    def err(field: str, code: str, message: str) -> None:
        errors.append({"field": field, "code": code, "message": message})

    for field, limit, label in (("sender_name", 100, "نام"), ("sender_company", 120, "نام شرکت")):
        if field in data:
            value = nz.normalize_text(str(data[field] or ""))
            if len(value) > limit:
                err(field, "too_long", f"«{label}» از {limit} نویسه بلندتر است.")
            new[field] = value
    if "sender_phone" in data:
        raw = nz.normalize_text(str(data["sender_phone"] or ""))
        if raw:
            try:
                nz.normalize_phone(raw)
            except nz.NormalizationError as exc:
                err("sender_phone", exc.code, exc.message)
        new["sender_phone"] = raw
    if "sender_email" in data:
        raw = str(data["sender_email"] or "").strip()
        if raw:
            try:
                raw = nz.normalize_email(raw)
            except nz.NormalizationError as exc:
                err("sender_email", exc.code, exc.message)
        new["sender_email"] = raw
    if "sender_website" in data:
        raw = str(data["sender_website"] or "").strip()
        if raw:
            try:
                raw = nz.clean_url(raw).url
            except nz.NormalizationError as exc:
                err("sender_website", exc.code, exc.message)
        new["sender_website"] = raw
    if "opt_out_line" in data:
        line = nz.normalize_text(str(data["opt_out_line"] or ""))
        if not line:
            err("opt_out_line", "required", "جملهٔ لغو عضویت لازم است و نباید خالی باشد.")
        elif len(line) > 300:
            err("opt_out_line", "too_long", "جملهٔ لغو عضویت از ۳۰۰ نویسه بلندتر است.")
        new["opt_out_line"] = line
    for field, low, high, label in (
        ("daily_cap", 1, 500, "سقفِ روزانه"), ("spacing_min_seconds", 10, 3600, "حداقل فاصله"), ("spacing_max_seconds", 10, 3600, "حداکثر فاصله"),
    ):
        if field in data:
            try:
                value = int(data[field])
            except (TypeError, ValueError):
                err(field, "invalid_number", f"«{label}» باید عدد باشد.")
                continue
            if not low <= value <= high:
                err(field, "out_of_range", f"«{label}» باید بین {low} و {high} باشد.")
            new[field] = value
    if "sending_enabled" in data:
        new["sending_enabled"] = bool(data["sending_enabled"])

    lo = new.get("spacing_min_seconds", current.spacing_min_seconds)
    hi = new.get("spacing_max_seconds", current.spacing_max_seconds)
    if lo > hi and not any(e["field"].startswith("spacing") for e in errors):
        err("spacing_max_seconds", "range", "حداکثر فاصله نباید از حداقل کمتر باشد.")

    if new.get("sending_enabled") and not errors:
        preview = GrowthSettings(**{**snapshot_fields(current), **new})
        problems = preview.identity_problems()
        if problems:
            err("sending_enabled", "identity_incomplete", "تا مشخصاتِ فرستنده کامل نشده، ارسالِ خودکار روشن نمی‌شود: " + " ".join(problems))
    if errors:
        raise SettingsInvalid(errors)

    changes = {k: {"old": getattr(current, k), "new": v} for k, v in new.items() if getattr(current, k) != v}
    for key, value in new.items():
        setattr(current, key, value)
    current.updated_by = actor if getattr(actor, "is_authenticated", False) else None
    current.save()
    if changes:
        audit.log(AuditKind.SETTINGS, actor, "تنظیمات عوض شد: " + "، ".join(changes), {"changes": changes})
    return current


def snapshot_fields(obj: GrowthSettings) -> dict:
    return {
        f: getattr(obj, f)
        for f in (
            "sending_enabled", "emergency_stop", "sender_name", "sender_company", "sender_phone", "sender_email", "sender_website",
            "opt_out_line", "daily_cap", "spacing_min_seconds", "spacing_max_seconds",
        )
    }


def set_emergency_stop(stop: bool, actor) -> GrowthSettings:
    current = get_settings()
    if current.emergency_stop != stop:
        current.emergency_stop = stop
        current.updated_by = actor if getattr(actor, "is_authenticated", False) else None
        current.save()
        audit.log(AuditKind.STOP if stop else AuditKind.RESUME, actor, "توقفِ اضطراری فعال شد" if stop else "توقفِ اضطراری برداشته شد")
    return current
