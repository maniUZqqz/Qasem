"""Serializers of the outreach module. Output shapes are what the panel pages read (see frontend/outreach/types.ts)."""
from __future__ import annotations

from rest_framework import serializers

from .models import Campaign, ItemStatus, MessageTemplate, OutreachItem, OutreachJob, SendAttempt


def template_json(template: MessageTemplate, used_by: int | None = None) -> dict:
    used = used_by if used_by is not None else template.campaigns.count()
    return {
        "id": template.pk, "name": template.name, "subject": template.subject, "body": template.body, "language": template.language,
        "generator": template.generator, "is_active": template.is_active, "used_by": used, "campaigns_count": used,
        "created_by_name": template.created_by.username if template.created_by_id else "",
        "created_at": template.created_at, "updated_at": template.updated_at,
    }


def job_json(job: OutreachJob | None) -> dict | None:
    if job is None:
        return None
    return {
        "id": job.pk, "campaign_id": job.campaign_id, "kind": job.kind, "kind_label": job.get_kind_display(), "status": job.status,
        "status_label": job.get_status_display(), "progress": job.progress, "total_items": job.total_items,
        "processed_items": job.processed_items, "items_sent": job.items_sent, "items_failed": job.items_failed,
        "items_blocked": job.items_blocked, "error": job.error, "note": job.note, "stalled": job.is_stalled,
        "can_resume": job.status == OutreachJob.Status.FAILED or job.is_stalled, "attempts": job.attempts,
        "queued_at": job.queued_at, "started_at": job.started_at, "finished_at": job.finished_at,
    }


def campaign_json(campaign: Campaign, counts: dict[str, int] | None = None) -> dict:
    counts = counts or {}
    return {
        "id": campaign.pk, "name": campaign.name, "template": {"id": campaign.template_id, "name": campaign.template.name},
        "mode": campaign.mode, "mode_label": campaign.get_mode_display(), "status": campaign.status, "status_label": campaign.get_status_display(),
        "counts": counts, "items_total": sum(counts.values()),
        "created_by_name": campaign.created_by.username if campaign.created_by_id else "",
        "started_at": campaign.started_at, "finished_at": campaign.finished_at, "created_at": campaign.created_at,
    }


def attempt_json(attempt: SendAttempt) -> dict:
    return {
        "attempted_at": attempt.attempted_at, "url": attempt.url, "method": attempt.method, "payload": attempt.payload,
        "status_code": attempt.status_code, "response_snippet": attempt.response_snippet, "success_guess": attempt.success_guess,
        "success_guess_label": attempt.get_success_guess_display(), "outcome": attempt.outcome, "error": attempt.error, "elapsed_ms": attempt.elapsed_ms,
    }


def approval_json(item: OutreachItem) -> dict | None:
    """``valid`` is true only for an approved item whose fingerprint still equals the approval's (so a changed item reads invalid)."""
    record = item.approved_record
    if record is None:
        return None
    valid = item.status == ItemStatus.APPROVED and record.fingerprint == item.fingerprint
    return {"valid": valid, "by": record.approved_by.username if record.approved_by_id else "", "at": record.approved_at}


def item_json(item: OutreachItem) -> dict:
    """One item with everything the review dialog needs: lead summary, the dry run (``plan``), approval, the attempt."""
    lead = item.lead
    try:
        attempt = item.attempt
    except SendAttempt.DoesNotExist:
        attempt = None
    return {
        "id": item.pk, "campaign_id": item.campaign_id,
        "lead": {"id": lead.pk, "display_name": lead.display_name, "business_name": lead.business_name, "website": lead.website, "city": lead.city},
        "lead_id": lead.pk, "lead_name": lead.display_name, "domain": item.domain, "target_url": item.target_url, "subject": item.subject,
        "rendered_text": item.rendered_text, "text_edited": item.text_edited, "status": item.status, "status_label": item.get_status_display(),
        "skip_reason": item.skip_reason, "skip_reason_text": item.skip_reason_text, "manual_note": item.manual_note, "forced": item.forced,
        "plan": item.plan or None, "plan_checked_at": item.plan_checked_at, "approval": approval_json(item),
        "attempt": attempt_json(attempt) if attempt else None, "created_at": item.created_at, "updated_at": item.updated_at,
    }


# --------------------------------------------------------------------------- input


class TemplateInputSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    subject = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    body = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    language = serializers.CharField(required=False, max_length=10)
    generator = serializers.CharField(required=False, max_length=40)
    is_active = serializers.BooleanField(required=False)


class PreviewSerializer(serializers.Serializer):
    body = serializers.CharField(allow_blank=True, max_length=20000)
    subject = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    lead_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class CampaignCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=2000, allow_blank=True)
    template_id = serializers.IntegerField(min_value=1)
    mode = serializers.ChoiceField(choices=Campaign.Mode.choices, default=Campaign.Mode.AUTO)
    lead_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, max_length=5000)
    force = serializers.BooleanField(required=False)


class CampaignPatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=2000)


class AddLeadsSerializer(serializers.Serializer):
    lead_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=5000)
    force = serializers.BooleanField(required=False)


class ItemIdsSerializer(serializers.Serializer):
    item_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, max_length=5000)
    all_ready = serializers.BooleanField(required=False)


class ItemPatchSerializer(serializers.Serializer):
    rendered_text = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    subject = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class OutcomeSerializer(serializers.Serializer):
    outcome = serializers.CharField(max_length=20)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")

