"""Reading and changing the settings of the discovery providers.

Secrets (API keys) rules:

* stored only in ``ProviderConfig.secrets`` (the database), never in code, fixtures, documents or logs;
* NEVER returned: ``snapshot`` says ``{"is_set": true}`` for a key and nothing else (no length, no last characters);
* the audit trail records WHICH fields changed, never their values.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from django.db import transaction
from django.utils import timezone

from apps.growth_engine.compliance.models import AuditKind
from apps.growth_engine.compliance.services import audit
from apps.growth_engine.core.dbretry import retry_locked
from apps.growth_engine.leads.services.editing import ValidationFailed

from .. import providers
from ..models import ProviderConfig
from ..providers.base import ProviderContext, ProviderError, SearchProvider
from ..providers.nominatim import validate_url
from . import geo

SECRET_MIN, SECRET_MAX = 8, 300
_SECRET_OK = re.compile(r"^[\x21-\x7e]+$")  # printable ASCII without spaces: what API keys look like

#: providers that work without a key are on until the operator turns them off; keyed ones are off until a key is pasted
DEFAULT_ENABLED = {"osm": True}


class UnknownProvider(Exception):
    pass


def provider_or_404(key: str) -> SearchProvider:
    provider = providers.get(key)
    if provider is None:
        raise UnknownProvider(key)
    return provider


def row_for(key: str) -> ProviderConfig | None:
    return ProviderConfig.objects.filter(provider=key).first()


def effective(provider: SearchProvider) -> tuple[bool, dict, dict]:
    """(enabled, settings with defaults filled in, secrets) as they are right now."""
    row = row_for(provider.key)
    enabled = row.enabled if row is not None else DEFAULT_ENABLED.get(provider.key, False)
    stored = {k: v for k, v in ((row.config if row else {}) or {}).items() if not k.startswith("_")}
    return enabled, {**provider.default_settings(), **stored}, dict((row.secrets if row else {}) or {})


def readiness(provider: SearchProvider) -> tuple[bool, str]:
    enabled, settings, secrets = effective(provider)
    return provider.readiness(enabled, settings, secrets)


# --------------------------------------------------------------------------- what the panel sees


def usage_today(row: ProviderConfig | None) -> int:
    usage = ((row.config if row else {}) or {}).get("_usage") or {}
    return int(usage.get("count", 0)) if usage.get("day") == str(timezone.localdate()) else 0


def snapshot(provider: SearchProvider) -> dict:
    enabled, settings, secrets = effective(provider)
    ready, reason = provider.readiness(enabled, settings, secrets)
    row = row_for(provider.key)
    out = {
        "key": provider.key, "label": provider.label, "description": provider.description, "kind": provider.kind,
        "needs_key": provider.needs_key, "enabled": enabled, "ready": ready, "not_ready_reason": "" if ready else reason,
        "attribution": provider.attribution, "attribution_url": provider.attribution_url, "license_note": provider.license_note,
        "max_results_limit": provider.max_results_limit, "categories": provider.categories(),
        "settings_schema": provider.settings_schema(), "settings": settings,
        "secrets": {name: {"label": label, "is_set": bool(secrets.get(name))} for name, label in provider.secret_fields},
        "source_provider": provider.source_provider,
    }
    if provider.needs_key:
        out["usage_today"] = usage_today(row)
        out["daily_cap"] = provider.daily_cap(settings)  # type: ignore[attr-defined]
    return out


def snapshot_all() -> list[dict]:
    return [snapshot(p) for p in providers.all_providers()]


# --------------------------------------------------------------------------- changing them


def _clean_setting(spec: dict, value, errors: list[dict]):
    name, label, kind = spec["name"], spec["label"], spec["type"]
    if kind == "lines":
        items = value if isinstance(value, list) else str(value or "").splitlines()
        items = [str(i).strip() for i in items if str(i).strip()]
        if not items or len(items) > 6:
            errors.append({"field": name, "code": "invalid", "message": f"«{label}»: بین ۱ تا ۶ نشانی لازم است."})
            return None
        try:
            return [validate_url(i) for i in items]
        except ProviderError as exc:
            errors.append({"field": name, "code": exc.code, "message": f"«{label}»: {exc.message}"})
            return None
    if kind == "url":
        try:
            return validate_url(str(value or "").strip())
        except ProviderError as exc:
            errors.append({"field": name, "code": exc.code, "message": f"«{label}»: {exc.message}"})
            return None
    if kind == "int":
        try:
            number = int(value)
        except (TypeError, ValueError):
            errors.append({"field": name, "code": "invalid_number", "message": f"«{label}» باید عدد باشد."})
            return None
        if not 1 <= number <= 1000:
            errors.append({"field": name, "code": "out_of_range", "message": f"«{label}» باید بین ۱ و ۱۰۰۰ باشد."})
            return None
        return number
    return value


def update(provider: SearchProvider, data: Mapping, actor) -> ProviderConfig:
    """Apply ``{"enabled"?, "settings"?: {...}, "secrets"?: {name: value}, "clear_secrets"?: [name]}``. All or nothing."""
    errors: list[dict] = []
    row = row_for(provider.key)
    enabled_now, settings_now, secrets_now = effective(provider)
    new_settings = dict((row.config if row else {}) or {})
    new_secrets = dict(secrets_now)
    changed: list[str] = []

    schema = {s["name"]: s for s in provider.settings_schema()}
    for name, value in (data.get("settings") or {}).items():
        if name not in schema:
            errors.append({"field": name, "code": "unknown_setting", "message": f"تنظیمِ «{name}» وجود ندارد."})
            continue
        cleaned = _clean_setting(schema[name], value, errors)
        if cleaned is not None and cleaned != settings_now.get(name):
            new_settings[name] = cleaned
            changed.append(f"settings.{name}")

    allowed = dict(provider.secret_fields)
    for name, value in (data.get("secrets") or {}).items():
        if name not in allowed:
            errors.append({"field": name, "code": "unknown_secret", "message": f"کلیدِ «{name}» برای این ارائه‌دهنده وجود ندارد."})
            continue
        text = str(value or "").strip()
        if not text:
            continue  # an empty box means "leave it as it is"; clearing is explicit
        if not SECRET_MIN <= len(text) <= SECRET_MAX or not _SECRET_OK.match(text):
            errors.append({"field": name, "code": "invalid_secret", "message": f"«{allowed[name]}» درست نیست (باید فقط حرف و عددِ انگلیسی باشد، بدونِ فاصله)."})
            continue
        new_secrets[name] = text
        changed.append(f"secrets.{name}")
    for name in data.get("clear_secrets") or []:
        if name in allowed and new_secrets.pop(name, None) is not None:
            changed.append(f"secrets.{name}")

    new_enabled = bool(data["enabled"]) if "enabled" in data else enabled_now
    if new_enabled and provider.needs_key:
        missing = [label for name, label in provider.secret_fields if not new_secrets.get(name)]
        # a request that switches it ON without a key is refused; one that merely keeps it on while REMOVING the key (the panel sends
        # the current switch together with the removal) switches it off instead of failing
        removing_key = bool(data.get("clear_secrets")) and enabled_now
        if missing and data.get("enabled") and not removing_key:
            errors.append({"field": "enabled", "code": "key_required", "message": "تا کلید وارد نشده روشن نمی‌شود: " + "، ".join(missing) + "."})
        elif missing:
            new_enabled = False  # its key was removed: it switches itself off rather than staying on without a key
    if errors:
        raise ValidationFailed(errors)
    if new_enabled != enabled_now:
        changed.append("enabled")

    def save() -> ProviderConfig:
        with transaction.atomic():
            obj, _ = ProviderConfig.objects.get_or_create(provider=provider.key)
            obj.enabled, obj.config, obj.secrets = new_enabled, new_settings, new_secrets
            obj.updated_by = actor if getattr(actor, "is_authenticated", False) else None
            obj.save()
            return obj

    obj = retry_locked(save)
    if changed:
        # field NAMES only - a key's value must never reach the audit trail
        audit.log(AuditKind.SETTINGS, actor, f"تنظیمات «{provider.label}» عوض شد: " + "، ".join(changed), {"provider": provider.key, "fields": changed})
    return obj


# --------------------------------------------------------------------------- running a provider


def note_request_factory(provider: SearchProvider):
    """A function that counts one request of ``provider`` today and refuses (``ProviderError``) when the day's cap is used up."""

    def note(_key: str) -> None:
        if not provider.needs_key:
            return

        def count() -> None:
            with transaction.atomic():
                row, _ = ProviderConfig.objects.get_or_create(provider=provider.key)
                settings = dict(row.config or {})
                usage = settings.get("_usage") or {}
                today = str(timezone.localdate())
                done = int(usage.get("count", 0)) if usage.get("day") == today else 0
                cap = provider.daily_cap({**provider.default_settings(), **settings})  # type: ignore[attr-defined]
                if done >= cap:
                    raise ProviderError(
                        "daily_cap",
                        f"سقفِ درخواستِ امروز ({cap}) پر شد؛ فردا ادامه بدهید یا سقف را در تنظیماتِ این ارائه‌دهنده بالاتر ببرید.",
                        retryable=True,
                    )
                settings["_usage"] = {"day": today, "count": done + 1}
                row.config = settings
                row.save(update_fields=["config", "updated_at"])

        retry_locked(count)

    return note


def context_for(provider: SearchProvider, fetcher, cancelled) -> ProviderContext:
    enabled, settings, secrets = effective(provider)
    nominatim_url = settings.get("nominatim_url") or None
    kwargs = {"url": nominatim_url} if nominatim_url else {}
    return ProviderContext(
        fetcher=fetcher, settings=settings, secrets=secrets, cancelled=cancelled,
        geocode=lambda city, country: geo.geocode(fetcher, city, country, **kwargs),
        note_request=note_request_factory(provider),
    )
