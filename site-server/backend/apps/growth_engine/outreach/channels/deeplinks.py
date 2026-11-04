"""Ready-made links for the channels a person works by hand. A link is built only from a validated recipient; the only schemes
are https and tel. Nothing here logs in anywhere or talks to a messenger: the person opens the link, pastes / sends, and records
what happened.
"""
from __future__ import annotations

from urllib.parse import quote, urlsplit

from apps.growth_engine.core import normalization as nz

from ..models import Channel

#: messenger page hosts we accept in a link (what ``normalize_contact`` produces)
_HOSTS = {
    Channel.TELEGRAM: ("t.me",), Channel.EITAA: ("eitaa.com",), Channel.BALE: ("ble.ir",), Channel.RUBIKA: ("rubika.ir",),
}
_STEPS = {
    Channel.WHATSAPP: "چت باز می‌شود و متن آماده است؛ فقط «ارسال» را بزنید.",
    Channel.TELEGRAM: "چت باز می‌شود؛ متن را کپی کنید و بچسبانید.",
    Channel.EITAA: "چت باز می‌شود؛ متن را کپی کنید و بچسبانید.",
    Channel.BALE: "چت باز می‌شود؛ متن را کپی کنید و بچسبانید.",
    Channel.RUBIKA: "چت باز می‌شود؛ متن را کپی کنید و بچسبانید.",
    Channel.PHONE_CALL: "شماره را بگیرید و متنِ پیشنهادی را راهنما بگیرید؛ بعد نتیجه را ثبت کنید.",
}


def build(channel: str, recipient: str, text: str = "") -> dict:
    """``{"link", "link_kind", "label", "steps", "copy_text"}`` for a manual channel; ``link`` is "" when none can be made."""
    out = {"link": "", "link_kind": "", "label": "", "steps": _STEPS.get(channel, ""), "copy_text": bool(text)}
    try:
        if channel == Channel.WHATSAPP:
            digits = nz.normalize_phone(recipient).e164.lstrip("+")
            suffix = f"?text={quote(text, safe='')}" if text else ""
            out.update(link=f"https://wa.me/{digits}{suffix}", link_kind="https", label="باز کردنِ چتِ واتساپ")
        elif channel in _HOSTS:
            parts = urlsplit(recipient)
            if parts.scheme == "https" and (parts.hostname or "") in _HOSTS[channel]:
                out.update(link=recipient, link_kind="https", label=f"باز کردنِ چتِ {Channel(channel).label}")
        elif channel == Channel.PHONE_CALL:
            out.update(link=f"tel:{nz.normalize_phone(recipient).e164}", link_kind="tel", label="گرفتنِ تماس")
    except nz.NormalizationError:
        pass
    return out
