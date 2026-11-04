"""Campaigns: creating them, putting leads in (with every reason a lead can be refused), and their status changes."""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.growth_engine.compliance.models import AuditKind, GrowthSettings
from apps.growth_engine.compliance.services import audit, limits, suppression
from apps.growth_engine.core import conf
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.models import Lead

from django.db.models import Q

from ..channels import targets as channel_targets
from ..models import (
    ANY, AUTO, AUTO_CHANNELS, CONTACTED_STATUSES, MANUAL_CHANNELS, OPEN_STATUSES, Campaign, Channel, ItemStatus, MessageTemplate, OutreachItem, OutreachJob,
)
from . import channel_config, fingerprint, generators, targets


class CampaignError(Exception):
    """A request the campaign cannot honour. ``code`` is stable, ``message`` is Persian."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


SKIP_TEXTS = {
    "lead_missing": "این لید پیدا نشد.",
    "already_in_campaign": "قبلاً در همین کمپین است.",
    "already_contacted": "با همین قالب قبلاً برای این لید پیام رفته (یا تلاشِ ارسال شده) است.",
    "suppressed": "در فهرستِ «تماس نگیر» است.",
    "archived": "بایگانی شده است.",
    "duplicate_domain": "از همین سایت قبلاً یک لید در این کمپین هست (هر سایت یک پیام).",
    "no_target_url": "آدرسِ صفحهٔ تماس ندارد (اول «استخراج اطلاعاتِ تماس» را اجرا کنید).",
    "limit": "کمپین به سقفِ تعدادِ موردها رسیده است.",
    # channel-specific reasons ("no_email", "no_mobile", ...) come with their text from channels/targets.py
}


@dataclass
class AddResult:
    added: list[OutreachItem] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- create


def create_campaign(*, name: str, template: MessageTemplate, mode: str, user=None, channel: str = Channel.CONTACT_FORM) -> Campaign:
    name = nz.normalize_text(name)
    if not name:
        raise CampaignError("name_required", "نامِ کمپین را بنویسید.")
    if len(name) > 150:
        raise CampaignError("name_too_long", "نامِ کمپین از ۱۵۰ نویسه بلندتر است.")
    if mode not in Campaign.Mode.values:
        raise CampaignError("invalid_mode", "حالتِ کمپین معتبر نیست.")
    if not template.is_active:
        raise CampaignError("template_inactive", "این قالب بایگانی شده؛ قالبِ فعالی انتخاب کنید.")
    if channel != AUTO and channel not in Channel.values:
        raise CampaignError("invalid_channel", "کانالِ کمپین معتبر نیست.")
    if channel in MANUAL_CHANNELS and mode != Campaign.Mode.MANUAL:
        raise CampaignError("manual_channel_mode", f"کانالِ «{Channel(channel).label}» را خودتان می‌فرستید؛ حالتِ «صفِ دستی» را انتخاب کنید.")
    if channel != AUTO and template.channel not in (ANY, channel):
        raise CampaignError("template_channel", "این قالب برای کانالِ دیگری نوشته شده؛ قالبِ همین کانال را انتخاب کنید.")
    campaign = Campaign.objects.create(
        name=name, template=template, mode=mode, channel=channel, created_by=user if getattr(user, "is_authenticated", False) else None
    )
    _audit(campaign, user, f"کمپین «{campaign.name}» ساخته شد ({campaign.get_mode_display()}، {campaign.get_channel_display()})")
    return campaign


def _audit(campaign: Campaign, actor, summary: str) -> None:
    audit.log(AuditKind.CAMPAIGN, actor, summary, {"campaign_id": campaign.pk, "status": campaign.status})


# --------------------------------------------------------------------------- add leads


def add_leads(campaign: Campaign, lead_ids: list[int], *, user=None, force: bool = False) -> AddResult:
    """Put leads into a campaign. A refused lead is reported with a reason code and a Persian text, never silently dropped.

    ``force`` only means something for ``manual`` campaigns: it lets a lead that already received this template be queued
    again. An automatic campaign never re-sends (the guard says so again at send time)."""
    if campaign.status in (Campaign.Status.COMPLETED, Campaign.Status.CANCELLED):
        raise CampaignError("campaign_closed", "این کمپین بسته شده؛ به آن لید اضافه نمی‌شود.")
    ids = list(dict.fromkeys(int(i) for i in lead_ids))
    result = AddResult()
    if not ids:
        return result
    leads = {lead.pk: lead for lead in Lead.objects.filter(pk__in=ids)}
    in_campaign = set(campaign.items.values_list("lead_id", flat=True))
    domains = set(campaign.items.exclude(domain="").values_list("domain", flat=True))
    blocked = suppression.suppressed_lead_ids(ids)
    contacted_cache: dict[int, set[int]] = {}

    def contacted_with(template_id: int) -> set[int]:
        """Leads (of ``ids``) that already got a message from this template in ANOTHER campaign."""
        if template_id not in contacted_cache:
            contacted_cache[template_id] = set(
                OutreachItem.objects.filter(lead_id__in=ids, status__in=CONTACTED_STATUSES)
                .filter(Q(template_id=template_id) | Q(template__isnull=True, campaign__template_id=template_id))
                .exclude(campaign_id=campaign.pk).values_list("lead_id", flat=True)
            )
        return contacted_cache[template_id]

    auto_order = channel_config.ordered_enabled() if campaign.channel == AUTO else []
    settings_obj = GrowthSettings.load()
    limit = int(conf.get("SEND_MAX_ITEMS_PER_CAMPAIGN"))
    count = len(in_campaign)
    manual = campaign.mode == Campaign.Mode.MANUAL

    def skip(lead_id: int, reason: str) -> None:
        lead = leads.get(lead_id)
        result.skipped.append({"lead_id": lead_id, "lead_name": lead.display_name if lead else "", "reason": reason, "reason_text": SKIP_TEXTS[reason]})

    for lead_id in ids:
        lead = leads.get(lead_id)
        if lead is None:
            skip(lead_id, "lead_missing")
            continue
        if lead_id in in_campaign:
            skip(lead_id, "already_in_campaign")
            continue
        if lead.is_archived:
            skip(lead_id, "archived")
            continue
        if lead_id in blocked:
            skip(lead_id, "suppressed")
            continue
        # which channel, which recipient, which template
        if campaign.channel == AUTO:
            target = channel_targets.choose_for_auto(lead, auto_order)
            channel = target.channel if target else Channel.CONTACT_FORM
            template = (channel_config.default_template(channel) if target else None) or campaign.template
        else:
            channel = campaign.channel
            target = channel_targets.resolve(lead, channel)
            template = campaign.template
        was_contacted = lead_id in contacted_with(template.pk)
        if was_contacted and not (manual and force):
            skip(lead_id, "already_contacted")
            continue
        domain = targets.domain_key(lead)
        if domain and domain in domains:
            skip(lead_id, "duplicate_domain")
            continue
        url = target.recipient if target and channel == Channel.CONTACT_FORM else ""
        # a manual form queue may hold leads whose form is not known yet (a person looks it up); every other channel needs a recipient
        if target is None and not (manual and campaign.channel == Channel.CONTACT_FORM):
            code, text = channel_targets.NO_CHANNEL if campaign.channel == AUTO else channel_targets.no_target(channel)
            result.skipped.append({"lead_id": lead_id, "lead_name": lead.display_name, "reason": code, "reason_text": text})
            continue
        if count >= limit:
            skip(lead_id, "limit")
            continue
        built = generators.build_message(template, lead, settings_obj, channel)
        item = OutreachItem(
            campaign=campaign, lead=lead, domain=domain, target_url=url, channel=channel, recipient=target.recipient if target else "",
            template=template, subject=built.subject, rendered_text=built.text,
            status=ItemStatus.PENDING, forced=bool(was_contacted and manual and force),
        )
        item.fingerprint = fingerprint.compute(item)
        try:
            with transaction.atomic():
                item.save()
        except IntegrityError:  # a concurrent add took the lead or the site a moment ago
            skip(lead_id, "already_in_campaign")
            continue
        in_campaign.add(lead_id)
        if domain:
            domains.add(domain)
        count += 1
        result.added.append(item)
    if result.added:
        _audit(campaign, user, f"{len(result.added)} لید به کمپین «{campaign.name}» اضافه شد")
    return result


NOT_REMOVABLE = (ItemStatus.SENDING, ItemStatus.SENT, ItemStatus.FAILED, ItemStatus.MANUAL_SENT, ItemStatus.HANDED_OFF, ItemStatus.UNREACHABLE)


def remove_items(campaign: Campaign, item_ids: list[int], user=None) -> dict:
    """Delete items that were never sent. Sent / failed / sending ones stay: they are the record that stops a second message."""
    items = list(campaign.items.filter(pk__in=item_ids))
    removable = [i for i in items if i.status not in NOT_REMOVABLE]
    OutreachItem.objects.filter(pk__in=[i.pk for i in removable]).delete()
    refused = [{"item_id": i.pk, "reason": "not_removable", "reason_text": "ارسال شده یا تلاش شده؛ از کمپین پاک نمی‌شود."} for i in items if i.status in NOT_REMOVABLE]
    if removable:
        _audit(campaign, user, f"{len(removable)} مورد از کمپین «{campaign.name}» حذف شد")
        maybe_complete(campaign)
    return {"removed": len(removable), "refused": refused}


# --------------------------------------------------------------------------- status changes


def start_problems(campaign: Campaign) -> list[str]:
    """Why an automatic campaign cannot send right now (empty = it can)."""
    settings_obj = GrowthSettings.load()
    problems = []
    if not settings_obj.sending_enabled:
        problems.append("ارسالِ خودکار در «تنظیماتِ جذب مشتری» خاموش است.")
    problems += settings_obj.identity_problems()
    if settings_obj.emergency_stop:
        problems.append("توقفِ اضطراری فعال است.")
    if limits.cap_remaining(settings_obj) <= 0:
        problems.append(f"سقفِ روزانه ({settings_obj.daily_cap}) پر شده؛ فردا ادامه بدهید.")
    if campaign.channel in AUTO_CHANNELS:
        if not channel_config.is_enabled(campaign.channel):
            problems.append(f"کانالِ «{Channel(campaign.channel).label}» در «کانال‌ها» خاموش است.")
        elif channel_config.cap_remaining(campaign.channel) == 0:
            problems.append(f"سقفِ روزانهٔ کانالِ «{Channel(campaign.channel).label}» پر شده؛ فردا ادامه بدهید.")
    return problems


def start(campaign: Campaign, user=None) -> tuple[Campaign, OutreachJob | None, bool]:
    """draft/paused -> active, and (automatic campaigns) start a send job when there are approved items.

    Returns ``(campaign, job, created)``: ``created`` is True when a NEW job row was made (the caller enqueues it).
    Calling it on an active campaign starts a new send job if none is running (that is «ادامهٔ ارسال»)."""
    if campaign.status in (Campaign.Status.COMPLETED, Campaign.Status.CANCELLED):
        raise CampaignError("campaign_closed", "این کمپین بسته شده و دوباره شروع نمی‌شود.")
    if campaign.mode == Campaign.Mode.MANUAL:
        _activate(campaign, user)
        return campaign, None, False
    problems = start_problems(campaign)
    if problems:
        raise CampaignError("not_ready", " ".join(problems))
    approved = campaign.items.filter(status=ItemStatus.APPROVED).count()
    running = campaign.jobs.filter(kind=OutreachJob.Kind.SEND, status__in=[OutreachJob.Status.QUEUED, OutreachJob.Status.RUNNING]).first()
    if running and not running.is_stalled:
        _activate(campaign, user)
        return campaign, running, False
    if approved == 0:
        raise CampaignError("nothing_approved", "هیچ موردِ تأییدشده‌ای برای ارسال نیست.")
    _activate(campaign, user)
    job = OutreachJob.objects.create(
        campaign=campaign, kind=OutreachJob.Kind.SEND, total_items=approved, created_by=user if getattr(user, "is_authenticated", False) else None
    )
    return campaign, job, True


def _activate(campaign: Campaign, user) -> None:
    if campaign.status != Campaign.Status.ACTIVE:
        campaign.status = Campaign.Status.ACTIVE
        campaign.started_at = campaign.started_at or timezone.now()
        campaign.save(update_fields=["status", "started_at", "updated_at"])
        _audit(campaign, user, f"کمپین «{campaign.name}» فعال شد")


def pause(campaign: Campaign, user=None) -> Campaign:
    if campaign.status != Campaign.Status.ACTIVE:
        raise CampaignError("not_active", "فقط کمپینِ فعال را می‌شود متوقف کرد.")
    campaign.status = Campaign.Status.PAUSED
    campaign.save(update_fields=["status", "updated_at"])
    OutreachJob.objects.filter(campaign=campaign, kind=OutreachJob.Kind.SEND, status__in=[OutreachJob.Status.QUEUED, OutreachJob.Status.RUNNING]).update(cancel_requested=True)
    _audit(campaign, user, f"کمپین «{campaign.name}» متوقف شد")
    _recall_phone_queue(campaign)
    return campaign


def cancel(campaign: Campaign, user=None) -> Campaign:
    """Cancel the campaign: items that were not sent become ``cancelled``; one being sent right now finishes."""
    if campaign.status in (Campaign.Status.COMPLETED, Campaign.Status.CANCELLED):
        raise CampaignError("campaign_closed", "این کمپین بسته شده است.")
    with transaction.atomic():
        campaign.status = Campaign.Status.CANCELLED
        campaign.finished_at = timezone.now()
        campaign.save(update_fields=["status", "finished_at", "updated_at"])
        campaign.items.filter(status__in=[ItemStatus.PENDING, ItemStatus.READY, ItemStatus.APPROVED, ItemStatus.NEEDS_MANUAL]).update(
            status=ItemStatus.CANCELLED, approved_record=None, updated_at=timezone.now()
        )
        OutreachJob.objects.filter(campaign=campaign, status__in=[OutreachJob.Status.QUEUED, OutreachJob.Status.RUNNING]).update(cancel_requested=True)
        _audit(campaign, user, f"کمپین «{campaign.name}» لغو شد")
    _recall_phone_queue(campaign)
    return campaign


def _recall_phone_queue(campaign: Campaign) -> None:
    """Pausing or cancelling a campaign also takes its not-yet-sent SMS back from the phone's queue."""
    if campaign.channel in (Channel.SMS, AUTO):
        from ..channels import sms

        try:
            sms.revoke_pending(campaign.pk)
        except Exception:  # noqa: BLE001 - the campaign is already paused; a gateway hiccup must not undo that
            import logging

            logging.getLogger(__name__).exception("could not recall the phone queue of campaign %s", campaign.pk)


def maybe_complete(campaign: Campaign) -> bool:
    """An active campaign with nothing left to do becomes ``completed``."""
    campaign.refresh_from_db(fields=["status"])
    if campaign.status != Campaign.Status.ACTIVE:
        return False
    if not campaign.items.exists() or campaign.items.filter(status__in=OPEN_STATUSES).exists():
        return False
    campaign.status = Campaign.Status.COMPLETED
    campaign.finished_at = timezone.now()
    campaign.save(update_fields=["status", "finished_at", "updated_at"])
    _audit(campaign, None, f"کمپین «{campaign.name}» تمام شد")
    return True


def counts(campaign_ids: list[int]) -> dict[int, dict[str, int]]:
    """{campaign id: {status: n}} for several campaigns in one query."""
    from django.db.models import Count

    out: dict[int, dict[str, int]] = {cid: {} for cid in campaign_ids}
    for cid, status, n in OutreachItem.objects.filter(campaign_id__in=campaign_ids).values_list("campaign_id", "status").annotate(n=Count("id")):
        out[cid][status] = n
    return out
