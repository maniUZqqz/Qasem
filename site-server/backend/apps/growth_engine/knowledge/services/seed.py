"""Putting the default knowledge and the default templates in place (idempotent: what exists is never changed)."""
from __future__ import annotations

import logging

from django.db import connection

from . import seed_data

logger = logging.getLogger(__name__)


def seed_knowledge() -> int:
    """Add the default knowledge items that are missing (matched by ``seed_key``). Returns how many were added."""
    from ..models import KnowledgeItem

    added = 0
    for seed_key, section, title, body, url, active, note, order in seed_data.KNOWLEDGE:
        _, created = KnowledgeItem.objects.get_or_create(
            seed_key=seed_key, defaults={"section": section, "title": title, "body": body, "url": url, "is_active": active, "note": note, "sort_order": order},
        )
        added += int(created)
    return added


def seed_templates() -> int:
    """Add the default message templates that are missing (matched by ``seed_key``). Returns how many were added."""
    from apps.growth_engine.outreach.models import MessageTemplate

    added = 0
    for seed_key, channel, name, subject, body in seed_data.TEMPLATES:
        _, created = MessageTemplate.objects.get_or_create(
            seed_key=seed_key, defaults={"channel": channel, "name": name, "subject": subject, "body": body, "language": "fa", "is_active": True},
        )
        added += int(created)
    return added


def restore_defaults() -> dict:
    return {"knowledge": seed_knowledge(), "templates": seed_templates()}


def seed_after_migrate(sender=None, **kwargs) -> None:
    """``post_migrate``: the defaults are there after every migrate. Never breaks a migrate (tables may be missing on a rollback,
    and the test database is left empty on purpose: tests seed explicitly)."""
    from django.conf import settings

    if getattr(settings, "IS_TEST", False):
        return
    try:
        tables = set(connection.introspection.table_names())
        if not {"growth_knowledge_knowledgeitem", "growth_outreach_messagetemplate"} <= tables:
            return
        if any(backwards for _migration, backwards in (kwargs.get("plan") or [])):
            return
        added = restore_defaults()
        if any(added.values()):
            logger.info("growth defaults seeded: %s", added)
    except Exception:  # noqa: BLE001 - a seeding problem must never fail a migration
        logger.exception("growth defaults could not be seeded")
