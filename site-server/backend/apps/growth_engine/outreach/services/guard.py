"""The guard: the six validations every outgoing message must pass, at approval time and again right before every send.

    1 contact eligibility          a target page and a plan whose verdict is "eligible"
    2 channel permission           automatic sending switched on, identity complete, no emergency stop, an "auto" campaign,
                                   the opt-out line still in the message
    3 suppression                  the lead (any of its identifiers) is not on the do-not-contact list
    4 duplicate communication      never the same lead + template twice (any campaign), one send per site per campaign,
                                   never a second attempt for the same item
    5 campaign status              "active" when sending; not closed when approving
    6 human approval               a valid, un-voided approval bound to the current fingerprint (sending only)

``check_item`` returns the FIRST failing validation as ``(ok, code, text)``; every code has its own Persian text.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core import normalization as nz

from ..models import CONTACTED_STATUSES, Campaign, ItemStatus, OutreachItem, SendAttempt
from . import fingerprint
from .form_analysis import FormPlan

# --- the codes (stable strings; the UI shows the text) -------------------------------------------------------------
NOT_READY = "not_ready"
NOT_PREPARED = "not_prepared"
NO_TARGET_URL = "no_target_url"
FORM_NOT_ELIGIBLE = "form_not_eligible"
MANUAL_CAMPAIGN = "manual_campaign"
SENDING_DISABLED = "sending_disabled"
IDENTITY_INCOMPLETE = "identity_incomplete"
EMERGENCY_STOP = "emergency_stop"
OPT_OUT_MISSING = "opt_out_missing"
SUPPRESSED = "suppressed"
ALREADY_CONTACTED = "already_contacted"
DOMAIN_ALREADY_CONTACTED = "domain_already_contacted"
ALREADY_ATTEMPTED = "already_attempted"
CAMPAIGN_NOT_ACTIVE = "campaign_not_active"
CAMPAIGN_CLOSED = "campaign_closed"
NO_APPROVAL = "no_approval"
APPROVAL_INVALID = "approval_invalid"

TEXTS = {
    NOT_READY: "فقط موردِ «آمادهٔ تأیید» را می‌شود تأیید کرد.",
    NOT_PREPARED: "هنوز صفحهٔ فرمِ این لید بررسی نشده است؛ اول «آماده‌سازی» را بزنید.",
    NO_TARGET_URL: "آدرسِ صفحهٔ تماسِ این لید معلوم نیست.",
    FORM_NOT_ELIGIBLE: "این فرم را نمی‌شود خودکار فرستاد.",
    MANUAL_CAMPAIGN: "این کمپین «صفِ دستی» است؛ ارسالِ خودکار ندارد.",
    SENDING_DISABLED: "ارسالِ خودکار در «تنظیماتِ جذب مشتری» خاموش است.",
    IDENTITY_INCOMPLETE: "مشخصاتِ فرستنده (نام، شرکت، تلفن، ایمیل، جملهٔ لغو) در تنظیمات کامل نیست.",
    EMERGENCY_STOP: "توقفِ اضطراری فعال است.",
    OPT_OUT_MISSING: "جملهٔ لغو عضویت در متنِ پیام نیست؛ هر پیام باید با آن تمام شود.",
    SUPPRESSED: "این لید در فهرستِ «تماس نگیر» است.",
    ALREADY_CONTACTED: "با همین قالب قبلاً برای این لید پیام رفته (یا تلاشِ ارسال شده) است.",
    DOMAIN_ALREADY_CONTACTED: "برای همین سایت در این کمپین قبلاً ارسال شده است.",
    ALREADY_ATTEMPTED: "برای این مورد قبلاً ارسال انجام شده؛ هیچ‌وقت دوباره تلاش نمی‌شود.",
    CAMPAIGN_NOT_ACTIVE: "کمپین فعال نیست.",
    CAMPAIGN_CLOSED: "کمپین بسته شده است.",
    NO_APPROVAL: "این مورد تأیید نشده است.",
    APPROVAL_INVALID: "تأیید باطل شده است: پیام، صفحه یا فرم عوض شده. دوباره بررسی و تأیید کنید.",
}

APPROVE, SEND = "approve", "send"


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    code: str = ""
    text: str = ""

    def __iter__(self):  # (ok, code, text) unpacking
        return iter((self.ok, self.code, self.text))


OK = GuardResult(True)


def _fail(code: str, text: str | None = None) -> GuardResult:
    return GuardResult(False, code, text or TEXTS[code])


def contacted_elsewhere(item: OutreachItem) -> bool:
    """Another item for the same lead + template, in any campaign, that was sent / is sending / failed / was sent by hand."""
    return (
        OutreachItem.objects.filter(lead_id=item.lead_id, campaign__template_id=item.campaign.template_id, status__in=CONTACTED_STATUSES)
        .exclude(pk=item.pk)
        .exists()
    )


def domain_contacted(item: OutreachItem) -> bool:
    if not item.domain:
        return False
    return (
        OutreachItem.objects.filter(campaign_id=item.campaign_id, domain=item.domain, status__in=CONTACTED_STATUSES)
        .exclude(pk=item.pk)
        .exists()
    )


def check_item(item: OutreachItem, *, phase: str = SEND, settings_obj: GrowthSettings | None = None) -> GuardResult:
    """Run the validations. ``phase`` is ``"approve"`` (before a human approves) or ``"send"`` (right before posting)."""
    settings_obj = settings_obj or GrowthSettings.load()
    campaign: Campaign = item.campaign

    if phase == APPROVE and item.status != ItemStatus.READY:
        return _fail(NOT_READY)

    # 1 contact eligibility
    if not item.target_url:
        return _fail(NO_TARGET_URL)
    if not item.plan:
        return _fail(NOT_PREPARED)
    plan = FormPlan.from_dict(item.plan)
    if not plan.eligible:
        reason = plan.reasons[0].text if plan.reasons else ""
        return _fail(FORM_NOT_ELIGIBLE, f"{TEXTS[FORM_NOT_ELIGIBLE]} {reason}".strip())

    # 2 channel permission
    if campaign.mode != Campaign.Mode.AUTO:
        return _fail(MANUAL_CAMPAIGN)
    if not settings_obj.sending_enabled:
        return _fail(SENDING_DISABLED)
    if settings_obj.identity_problems():
        return _fail(IDENTITY_INCOMPLETE, f"{TEXTS[IDENTITY_INCOMPLETE]} " + " ".join(settings_obj.identity_problems()))
    if settings_obj.emergency_stop:
        return _fail(EMERGENCY_STOP)
    opt_out = nz.normalize_text(settings_obj.opt_out_line, multiline=True)
    if opt_out and opt_out not in nz.normalize_text(item.rendered_text, multiline=True):
        return _fail(OPT_OUT_MISSING)

    # 3 suppression
    if suppression.matches_for_lead(item.lead):
        return _fail(SUPPRESSED)

    # 4 duplicate communication
    if contacted_elsewhere(item):
        return _fail(ALREADY_CONTACTED)
    if domain_contacted(item):
        return _fail(DOMAIN_ALREADY_CONTACTED)
    if SendAttempt.objects.filter(item_id=item.pk).exists():
        return _fail(ALREADY_ATTEMPTED)

    # 5 campaign status
    if phase == SEND and campaign.status != Campaign.Status.ACTIVE:
        return _fail(CAMPAIGN_NOT_ACTIVE)
    if phase == APPROVE and campaign.status in (Campaign.Status.COMPLETED, Campaign.Status.CANCELLED):
        return _fail(CAMPAIGN_CLOSED)

    # 6 human approval (only when about to send)
    if phase == SEND:
        record = item.approved_record
        if record is None:
            return _fail(NO_APPROVAL)
        if record.item_id != item.pk or record.fingerprint != item.fingerprint or item.fingerprint != fingerprint.compute(item, plan):
            return _fail(APPROVAL_INVALID)
    return OK
