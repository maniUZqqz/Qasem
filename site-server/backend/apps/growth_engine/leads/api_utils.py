"""Response helpers shared by the leads and discovery views."""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from .serializers import LeadListSerializer
from .services.dedupe import DuplicateMatch
from .services.drafts import LeadDraft
from .services.editing import ValidationFailed
from .services.intake import DuplicateError, MergePlan, plan_merge


def validation_response(exc: ValidationFailed) -> Response:
    first = exc.errors[0]["message"] if exc.errors else "ورودی معتبر نیست."
    return Response({"code": "validation", "detail": first, "errors": exc.errors}, status=status.HTTP_400_BAD_REQUEST)


def describe_plan(plan: MergePlan) -> dict:
    """The merge plan in plain data, for the "merge or skip" dialog."""
    return {
        "fields": [
            {"field": d.field, "label": d.label, "existing": d.existing, "incoming": d.incoming, "state": d.state}
            for d in plan.decisions
        ],
        "contacts_new": [{"kind": c.kind, "value": c.value} for c in plan.new_contacts],
        "contacts_known": [{"kind": c.kind, "value": c.value} for c in plan.known_contacts],
        "contacts_elsewhere": [{"kind": c.kind, "value": c.value, "lead_id": lead_id} for c, lead_id in plan.foreign_contacts],
        "tags_new": plan.new_tags,
    }


def duplicate_payload(matches: list[DuplicateMatch], draft: LeadDraft | None = None) -> list[dict]:
    out = []
    for match in matches:
        item = {
            "lead": LeadListSerializer(match.lead).data,
            "matched_on": match.matched_on,
        }
        if draft is not None:
            item["merge_preview"] = describe_plan(plan_merge(match.lead, draft))
        out.append(item)
    return out


def duplicate_response(exc: DuplicateError, draft: LeadDraft | None = None) -> Response:
    return Response(
        {
            "code": "duplicate",
            "detail": "این کسب‌وکار از قبل در دیتابیس هست. ادغام کنید یا رد شوید.",
            "duplicates": duplicate_payload(exc.matches, draft),
        },
        status=status.HTTP_409_CONFLICT,
    )
