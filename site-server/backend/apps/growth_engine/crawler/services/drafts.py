"""Outreach drafts in the brand's own voice: SMS, e-mail, the site's contact form, and Instagram / WhatsApp / Telegram messages.

Writing a draft sends nothing and reaches nobody. The chain is:

    draft written (here)  ->  a person approves the TEXT  ->  for SMS / e-mail / site form it is put into the mission's campaign as an
    item; that campaign still needs the Growth Engine's own approval, the daily cap, the quiet hours, the do-not-contact list, the
    sender-identity check and the master «ارسال خودکار» switch (off by default) before anything leaves  ->  for Instagram DM / WhatsApp /
    Telegram the person copies the text and sends it by hand.

Voice: the words come ONLY from the mission's pitch (what the product is, why this kind of business would care, the one ask) plus the lead's
own stored facts (its name, its city). Nothing is invented: no prices, no percentages, no «۹۸٪ رضایت»; the pitch's ``avoid`` list is checked
and a draft that contains such a word is flagged. The system appends the sender block and the opt-out sentence itself (``rendering.compose``),
exactly as for every other Growth Engine message. If the owner wants the AI to rewrite a draft, that goes through the existing AI writer
on the campaign item - and when the AI is out of credit or off, the plain Persian message of that writer is shown and the draft stays as it is.
"""
from __future__ import annotations

import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ActivityKind
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services import history
from apps.growth_engine.leads.services.editing import ValidationFailed
from apps.growth_engine.outreach.channels import sms as sms_channel
from apps.growth_engine.outreach.channels import targets as channel_targets
from apps.growth_engine.outreach.models import ANY, AUTO_CHANNELS, Campaign, Channel, MessageTemplate
from apps.growth_engine.outreach.services import campaigns, channel_config, generators, items, rendering

from .. import presets
from ..models import CrawlMission, OutreachDraft

DM = "instagram_dm"
CHANNELS = {
    Channel.SMS: "پیامک (از گوشیِ شما)", Channel.EMAIL: "ایمیل", Channel.CONTACT_FORM: "فرمِ تماسِ سایت", DM: "دایرکتِ اینستاگرام (دستی)",
    Channel.WHATSAPP: "واتساپ (دستی)", Channel.TELEGRAM: "تلگرام (دستی)",
}
MANUAL = (DM, Channel.WHATSAPP, Channel.TELEGRAM)
MAX_PER_CALL = 200


# --------------------------------------------------------------------------- the pitch


def pitch_of(mission: CrawlMission) -> dict:
    """What the sender says: the mission's own pitch, else the preset's, else built from the store's own description. Raises when there is nothing true to say."""
    spec_pitch = dict((mission.spec or {}).get("pitch") or {})
    if not spec_pitch.get("what"):
        preset = presets.pitch_for(mission.preset_key)
        if preset is not None:
            spec_pitch = {"brand": preset.brand, "what": preset.what, "benefit": preset.benefit, "cta": preset.cta, "voice": preset.voice, **spec_pitch}
    if not spec_pitch.get("what") and mission.store is not None:
        store = mission.store
        sentence = re.split(r"(?<=[.!؟?])\s", nz.normalize_text(store.description or "", multiline=False))[0] if store.description else ""
        if sentence:
            spec_pitch = {"brand": store.name, "what": f"{store.name}: {sentence}", "benefit": (f"برای {store.target_audience}" if store.target_audience else ""), **spec_pitch}
    if not spec_pitch.get("what"):
        raise ValidationFailed([{"field": "pitch", "code": "no_pitch", "message": "برای نوشتنِ پیام، «معرفی کوتاهِ محصول» را در تنظیماتِ مأموریت بنویسید (چیزی از خودمان نمی‌سازیم)."}])
    spec_pitch.setdefault("brand", mission.store.name if mission.store else "ما")
    spec_pitch.setdefault("benefit", "")
    spec_pitch.setdefault("cta", "اگر مایلید همین‌جا پاسخ بدهید تا بیشتر توضیح بدهم.")
    return spec_pitch


def _short(text: str, n: int) -> str:
    text = nz.normalize_text(text)
    first = re.split(r"(?<=[.!؟?])\s", text)[0]
    return first if len(first) <= n else first[: n - 1].rstrip() + "…"


SMS_PART = 67  # UCS-2 (Persian): 70 characters in one part, 67 in each part of a longer message
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(n) -> str:
    return str(n).translate(_FA)


def sms_budget(settings_obj) -> int:
    """How many characters the BODY of an SMS may take so that body + sender line + opt-out sentence still fit the allowed number of parts.
    While the sender's company / name is not written in the settings yet, room for it is kept (the final text gets longer by that line)."""
    parts = channel_config.sms_max_parts()
    total = 70 if parts <= 1 else SMS_PART * parts
    closing = rendering.closing_block(settings_obj, Channel.SMS)
    reserve = 0 if (settings_obj.sender_company.strip() or settings_obj.sender_name.strip()) else 20
    used = (sms_channel.segments(closing)["length"] + 1 if closing else 0) + reserve
    return max(30, total - used - 2)


def fit_sms(brand: str, line: str, budget: int) -> str:
    """The longest greeting that still fits ``budget`` characters; the line is cut at a word (with «…») only when nothing else fits."""
    units = lambda text: sms_channel.segments(text)["length"]  # noqa: E731
    for text in (f"سلام، از تیمِ «{brand}». {line}", f"«{brand}»: {line}", line):
        if units(text) <= budget:
            return text
    out = f"«{brand}»:"
    for word in line.split():
        if units(f"{out} {word}…") > budget:
            break
        out = f"{out} {word}"
    return out + "…" if out != f"«{brand}»:" else line[:max(10, budget - 1)].rstrip() + "…"


def template_text(pitch: dict, channel: str, sms_chars: int | None = None) -> tuple[str, str]:
    """(subject, body with {placeholders}) for a channel. ``sms_chars``: the room an SMS body has (``sms_budget``)."""
    brand, what, benefit, cta = pitch["brand"], pitch["what"], pitch.get("benefit", ""), pitch["cta"]
    place = "دیدم {business_name} در {city|شهرِ شما} فعالیت می‌کند"
    if channel == Channel.SMS:
        line = pitch.get("sms") or _short(what, 45)
        return "", fit_sms(brand, line, sms_chars) if sms_chars else f"سلام، از تیمِ «{brand}». {line}"
    if channel == Channel.EMAIL:
        subject = f"{brand}: پیشنهادی برای {{business_name}}"
        body = f"سلام، وقتتان بخیر.\nمن از تیمِ «{brand}» پیام می‌دهم. {what}\n{place}" + (f"؛ {benefit}" if benefit else ".") + f"\n{cta}"
        return subject, body
    if channel == Channel.CONTACT_FORM:
        body = f"سلام، وقتتان بخیر.\nاز تیمِ «{brand}» پیام می‌دهم. {what}\n{place}" + (f"؛ {benefit}" if benefit else ".") + f"\n{cta}"
        return "", body
    # DM / WhatsApp / Telegram: friendlier and shorter
    body = f"سلام {{business_name}} عزیز، وقتتان بخیر.\nمن از تیمِ «{brand}» هستم. {what}\n" + (f"{benefit}\n" if benefit else "") + cta
    return "", body


def ensure_template(mission: CrawlMission, channel: str, pitch: dict) -> MessageTemplate:
    subject, body = template_text(pitch, channel, sms_budget(GrowthSettings.load()) if channel == Channel.SMS else None)
    seed = f"crawler:{mission.pk}:{channel}"[:60]
    tpl_channel = channel if channel in (Channel.SMS, Channel.EMAIL, Channel.CONTACT_FORM, Channel.WHATSAPP, Channel.TELEGRAM) else ANY
    tpl, _ = MessageTemplate.objects.update_or_create(
        seed_key=seed,
        defaults={"name": f"مشتری‌یاب · {nz.normalize_text(mission.name)[:50]} · {CHANNELS.get(channel, channel)}"[:120], "subject": subject, "body": body, "channel": tpl_channel,
                  "language": "fa", "generator": "placeholder", "is_active": True},
    )
    return tpl


# --------------------------------------------------------------------------- writing drafts


def _recipient(lead: Lead, channel: str):
    """(recipient text, reason code, reason text)"""
    if channel == DM:
        if not lead.instagram_url:
            return "", "no_instagram", "پیجِ اینستاگرام ندارد."
        return lead.instagram_url, "", ""
    target = channel_targets.resolve(lead, channel)
    if target is None:
        code, text = channel_targets.NO_TARGET.get(channel, ("no_target", "راهِ تماس برای این کانال ندارد."))
        return "", code, text
    return target.recipient, "", ""


def _warnings(pitch: dict, channel: str, text: str) -> list[str]:
    out: list[str] = []
    for word in pitch.get("avoid") or ():
        if word and word in text:
            out.append(f"کلمهٔ «{word}» که قرار بود در پیام نیاید دیده شد.")
    if re.search(r"\d+\s*(?:٪|%|درصد|تومان|ریال|هزار|میلیون)", nz.to_ascii_digits(text)):
        out.append("پیام عدد/قیمت/درصد دارد؛ مطمئن شوید راست و تأییدشده است.")
    if channel == Channel.SMS:
        seg = sms_channel.segments(text)
        allowed = channel_config.sms_max_parts()
        if seg["parts"] > allowed:
            out.append(f"پیامک {_fa(seg['parts'])} بخش می‌شود و حداکثرِ مجاز {_fa(allowed)} بخش است؛ کوتاه‌ترش کنید.")
    return out


def generate(mission: CrawlMission, lead_ids: list[int], channels: list[str], user=None) -> dict:
    """Write (or refresh) a draft for each lead on each channel. Returns ``{"created", "updated", "skipped": [{lead_id, channel, reason, text}]}``."""
    pitch = pitch_of(mission)
    bad = [c for c in channels if c not in CHANNELS]
    if bad or not channels:
        raise ValidationFailed([{"field": "channels", "code": "invalid", "message": "کانالِ معتبر انتخاب کنید."}])
    ids = list(dict.fromkeys(int(i) for i in lead_ids))[:MAX_PER_CALL]
    if not ids:
        raise ValidationFailed([{"field": "lead_ids", "code": "required", "message": "دست‌کم یک لید را انتخاب کنید."}])
    leads = {lead.pk: lead for lead in Lead.objects.filter(pk__in=ids, is_archived=False).prefetch_related("contacts")}
    blocked = suppression.suppressed_lead_ids(list(leads))
    settings_obj = GrowthSettings.load()
    out = {"created": 0, "updated": 0, "skipped": [], "blocked": 0}
    for channel in channels:
        template = ensure_template(mission, channel, pitch)
        build_channel = Channel.WHATSAPP if channel == DM else channel
        for lead_id in ids:
            lead = leads.get(lead_id)
            if lead is None:
                out["skipped"].append({"lead_id": lead_id, "channel": channel, "reason": "missing", "text": "لید پیدا نشد یا بایگانی است."})
                continue
            recipient, code, text = _recipient(lead, channel)
            if not recipient:
                out["skipped"].append({"lead_id": lead_id, "channel": channel, "reason": code, "text": text})
                continue
            built = generators.build_message(template, lead, settings_obj, build_channel)
            status, reason = OutreachDraft.Status.DRAFT, ""
            if lead_id in blocked:
                status, reason = OutreachDraft.Status.BLOCKED, "در فهرستِ «تماس نگیر» است؛ هیچ پیامی برایش نوشته یا فرستاده نمی‌شود."
            elif channel == Channel.SMS and sms_channel.is_opted_out(recipient):
                status, reason = OutreachDraft.Status.BLOCKED, "این شماره پیامک‌گرفتن را رد کرده است (فهرستِ لغو عضویتِ NM-Mobile)."
            warnings = [*built.warnings, *_warnings(pitch, channel, built.text)]
            existing = OutreachDraft.objects.filter(mission=mission, lead=lead, channel=channel).first()
            if existing is not None and existing.status in (OutreachDraft.Status.QUEUED, OutreachDraft.Status.SENT_MANUAL):
                out["skipped"].append({"lead_id": lead_id, "channel": channel, "reason": "already_used", "text": "برای این لید و کانال قبلاً پیامی در کمپین گذاشته یا دستی فرستاده شده."})
                continue
            if status == OutreachDraft.Status.BLOCKED:
                out["blocked"] += 1
            defaults = {"recipient": recipient[:500], "subject": built.subject, "body": built.text, "warnings": warnings, "status": status, "block_reason": reason,
                        "approved_by": None, "approved_at": None}
            _, created = OutreachDraft.objects.update_or_create(mission=mission, lead=lead, channel=channel, defaults=defaults)
            out["created" if created else "updated"] += 1
    return out


# --------------------------------------------------------------------------- reviewing

EDITABLE = (OutreachDraft.Status.DRAFT, OutreachDraft.Status.APPROVED, OutreachDraft.Status.REJECTED)


def edit(draft: OutreachDraft, *, body: str | None = None, subject: str | None = None) -> OutreachDraft:
    if draft.status not in EDITABLE:
        raise ValidationFailed([{"field": "status", "code": "not_editable", "message": "این پیش‌نویس دیگر قابل ویرایش نیست."}])
    errors = []
    if body is not None:
        text = nz.normalize_text(body, multiline=True)
        opt_out = nz.normalize_text(GrowthSettings.load().opt_out_line, multiline=True)
        if not text:
            errors.append({"field": "body", "code": "empty", "message": "متنِ پیام خالی است."})
        elif len(text) > 5000:
            errors.append({"field": "body", "code": "too_long", "message": "متن از ۵۰۰۰ نویسه بلندتر است."})
        elif opt_out and opt_out not in text:
            errors.append({"field": "body", "code": "opt_out_missing", "message": "جملهٔ لغو عضویت را از انتهای پیام حذف نکنید؛ هر پیام باید با آن تمام شود."})
        else:
            draft.body = text
    if subject is not None:
        draft.subject = nz.normalize_text(subject)[:300]
    if errors:
        raise ValidationFailed(errors)
    if draft.status == OutreachDraft.Status.APPROVED:
        draft.status, draft.approved_by, draft.approved_at = OutreachDraft.Status.DRAFT, None, None  # a changed text needs a new approval
    draft.warnings = _warnings(pitch_of(draft.mission), draft.channel, draft.body)
    draft.save()
    return draft


def approve(draft: OutreachDraft, user=None) -> OutreachDraft:
    if draft.status == OutreachDraft.Status.BLOCKED:
        raise ValidationFailed([{"field": "status", "code": "blocked", "message": draft.block_reason or "این پیش‌نویس مسدود است."}])
    if draft.status in (OutreachDraft.Status.QUEUED, OutreachDraft.Status.SENT_MANUAL):
        raise ValidationFailed([{"field": "status", "code": "used", "message": "این پیش‌نویس قبلاً استفاده شده است."}])
    if suppression.suppressed_lead_ids([draft.lead_id]):
        OutreachDraft.objects.filter(pk=draft.pk).update(status=OutreachDraft.Status.BLOCKED, block_reason="در فهرستِ «تماس نگیر» است.")
        raise ValidationFailed([{"field": "status", "code": "suppressed", "message": "این لید در فهرستِ «تماس نگیر» است."}])
    draft.status, draft.approved_by, draft.approved_at = OutreachDraft.Status.APPROVED, user if getattr(user, "is_authenticated", False) else None, timezone.now()
    draft.save()
    history.log_activity(draft.lead, ActivityKind.UPDATED, actor=user, summary=f"متنِ پیامِ {CHANNELS.get(draft.channel, draft.channel)} تأیید شد (هنوز چیزی فرستاده نشده)",
                         data={"draft": draft.pk, "channel": draft.channel})
    return draft


def reject(draft: OutreachDraft, user=None) -> OutreachDraft:
    if draft.status in (OutreachDraft.Status.QUEUED, OutreachDraft.Status.SENT_MANUAL):
        raise ValidationFailed([{"field": "status", "code": "used", "message": "این پیش‌نویس قبلاً استفاده شده است."}])
    draft.status, draft.approved_by, draft.approved_at = OutreachDraft.Status.REJECTED, None, None
    draft.save()
    return draft


def mark_sent_manually(draft: OutreachDraft, user=None) -> OutreachDraft:
    """The person sent a manual-channel message by hand: record it (history + lead status «تماس گرفته‌شد» if it was earlier in the pipeline)."""
    if draft.channel not in MANUAL:
        raise ValidationFailed([{"field": "channel", "code": "not_manual", "message": "این کانال را سامانه می‌فرستد، نه دست."}])
    if draft.status != OutreachDraft.Status.APPROVED:
        raise ValidationFailed([{"field": "status", "code": "not_approved", "message": "اول متنِ پیام را تأیید کنید."}])
    draft.status = OutreachDraft.Status.SENT_MANUAL
    draft.save()
    lead = draft.lead
    history.log_activity(lead, ActivityKind.QUEUE_OUTCOME, actor=user, summary=f"پیامِ {CHANNELS.get(draft.channel, draft.channel)} دستی فرستاده شد", data={"draft": draft.pk, "channel": draft.channel})
    from . import pipeline

    if pipeline.stage_of(lead.status) in ("new", "researched"):
        pipeline.move(lead, "contacted", user)
    return draft


def queue(draft: OutreachDraft, user=None) -> OutreachDraft:
    """Put an APPROVED draft of an automatic channel into the mission's campaign as an item. Nothing is sent: the campaign has its own gates."""
    if draft.channel in MANUAL:
        raise ValidationFailed([{"field": "channel", "code": "manual", "message": "این کانال دستی است؛ متن را کپی کنید و خودتان بفرستید."}])
    if draft.status != OutreachDraft.Status.APPROVED:
        raise ValidationFailed([{"field": "status", "code": "not_approved", "message": "اول متنِ پیام را تأیید کنید."}])
    mission = draft.mission
    campaign = _campaign_for(mission, draft.channel, user)
    result = campaigns.add_leads(campaign, [draft.lead_id], user=user)
    if not result.added:
        reason = result.skipped[0]["reason_text"] if result.skipped else "به کمپین اضافه نشد."
        raise ValidationFailed([{"field": "lead", "code": "not_added", "message": reason}])
    item = result.added[0]
    items.edit_item(item, text=draft.body, subject=draft.subject if draft.subject else None, actor=user)
    with transaction.atomic():
        draft.item, draft.status = item, OutreachDraft.Status.QUEUED
        draft.save()
    history.log_activity(draft.lead, ActivityKind.UPDATED, actor=user, summary=f"پیام در کمپینِ «{campaign.name}» گذاشته شد (هنوز ارسال نشده؛ تأییدِ کمپین لازم است)",
                         data={"draft": draft.pk, "campaign": campaign.pk, "item": item.pk})
    return draft


def _campaign_for(mission: CrawlMission, channel: str, user=None) -> Campaign:
    key = str(channel)
    cid = (mission.outreach or {}).get(key)
    campaign = Campaign.objects.filter(pk=cid).exclude(status__in=[Campaign.Status.COMPLETED, Campaign.Status.CANCELLED]).first() if cid else None
    if campaign is not None:
        return campaign
    template = ensure_template(mission, channel, pitch_of(mission))
    mode = Campaign.Mode.AUTO if channel in AUTO_CHANNELS else Campaign.Mode.MANUAL
    campaign = campaigns.create_campaign(name=f"مشتری‌یاب · {nz.normalize_text(mission.name)[:60]} · {CHANNELS.get(channel, channel)}", template=template, mode=mode, user=user,
                                         channel=channel, product=mission.product or "nm")
    CrawlMission.objects.filter(pk=mission.pk).update(outreach={**(mission.outreach or {}), key: campaign.pk})
    mission.outreach = {**(mission.outreach or {}), key: campaign.pk}
    return campaign


def draft_dict(d: OutreachDraft) -> dict:
    return {
        "id": d.pk, "mission_id": d.mission_id, "lead_id": d.lead_id, "lead_name": d.lead.display_name, "city": d.lead.city, "channel": d.channel,
        "channel_label": CHANNELS.get(d.channel, d.channel), "manual": d.channel in MANUAL, "recipient": d.recipient, "subject": d.subject, "body": d.body, "warnings": d.warnings,
        "status": d.status, "status_label": d.get_status_display(), "block_reason": d.block_reason, "item_id": d.item_id,
        "campaign_id": d.item.campaign_id if d.item_id and d.item else None, "approved_at": d.approved_at, "updated_at": d.updated_at,
        "sms": sms_channel.segments(d.body) if d.channel == Channel.SMS else None,
    }
