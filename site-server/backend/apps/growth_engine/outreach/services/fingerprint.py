"""The fingerprint an approval is bound to.

sha256 of the JSON of: lead id, template id, target URL, the message text, the subject, and the form material of the
plan (action URL, method, enctype, sorted (name, value) of every NON-hidden field, sorted NAMES of hidden fields). Hidden
VALUES are left out on purpose (CSRF tokens change on every page load); anything else that changes - the message, the
subject, the target, the action, a new or removed field (a CAPTCHA appearing, say) - changes the fingerprint and so
voids the approval.
"""
from __future__ import annotations

import hashlib
import json

from .form_analysis import FormPlan


def message_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def compute(item, plan: FormPlan | None = None) -> str:
    """Fingerprint of ``item`` as it is now; ``plan`` defaults to the stored one (form items only: other channels bind channel,
    recipient and the channel's own material - sender address, SMS limits - instead of a form)."""
    if getattr(item, "channel", "contact_form") in (None, "", "contact_form") and plan is None and item.plan:
        plan = FormPlan.from_dict(item.plan)
    material = {
        "lead_id": item.lead_id,
        "template_id": item.campaign.template_id,
        "target_url": item.target_url,
        "message": item.rendered_text,
        "subject": item.subject,
        "form": plan.fingerprint_material() if plan is not None else None,
    }
    channel = getattr(item, "channel", "contact_form") or "contact_form"
    if channel != "contact_form":
        material["channel"] = channel
        material["recipient"] = item.recipient
        material["channel_material"] = (item.plan or {}).get("material") or {}
        material["template_id"] = item.template_id or item.campaign.template_id
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False, default=list)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
