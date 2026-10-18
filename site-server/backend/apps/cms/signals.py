"""Which model, when saved, makes which part of the public site stale.

Wired here rather than in each model's `save()` so that a bulk import, a
management command and the admin all behave the same — `post_save` fires for
every path that writes a row.

`Plan` lives in billing, not here, but the pricing page is a CMS surface as
far as a visitor is concerned, so it is listened to from here too.
"""
from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import revalidate
from .models import (
    Article,
    Category,
    CaseStudy,
    CustomerLogo,
    FaqItem,
    Redirect,
    Resource,
    SeoBullet,
    SeoPage,
    SeoRow,
    SeoStep,
    ShowcaseItem,
    ShowcaseSegment,
    SiteSettings,
    Testimonial,
)

#: model → the website tags that go stale with it (website/lib/*.ts).
TAGS = {
    Article: ("articles",),
    Category: ("categories", "articles"),
    Redirect: ("articles",),
    SiteSettings: ("settings",),
    FaqItem: ("settings",),
    SeoPage: ("settings",),
    SeoBullet: ("settings",),
    SeoStep: ("settings",),
    SeoRow: ("settings",),
    ShowcaseItem: ("showcase",),
    ShowcaseSegment: ("showcase",),
    CaseStudy: ("showcase",),
    CustomerLogo: ("showcase",),
    Testimonial: ("showcase",),
    Resource: ("showcase",),
}


def _refresh(sender, **kwargs):
    tags = TAGS.get(sender)
    if tags:
        revalidate.ping(*tags)


def connect() -> None:
    """Called from `CmsConfig.ready()`."""
    for model in TAGS:
        post_save.connect(_refresh, sender=model, dispatch_uid=f"cms-revalidate-{model.__name__}")
        post_delete.connect(
            _refresh, sender=model, dispatch_uid=f"cms-revalidate-del-{model.__name__}"
        )

    from apps.billing.models import Plan

    @receiver(
        [post_save, post_delete], sender=Plan, dispatch_uid="cms-revalidate-plan",
        weak=False,
    )
    def _plan_changed(sender, **kwargs):
        # A price the site shows one way and bills another is the worst
        # possible staleness, so this one is wired even though it is not a
        # CMS model.
        revalidate.ping("plans")
