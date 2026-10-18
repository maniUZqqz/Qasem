"""One adapter per channel, so the inbox does not know what Instagram is.

§9.7 asks for a communication core with an independent adapter per channel.
The reason it matters here specifically: NovinHub caps a token at three
Instagram accounts, Telegram needs a bot the shop creates themselves, and SMS
in Iran goes through a provider that changes. Any of those can be replaced, and
none of that should reach the inbox, the sales agent, or the notification
rules.

So a channel is a small object that answers four questions — can it receive,
can it send, what does it need to be configured, and is it configured — and the
rest of the product talks to `Conversation.channel` as a string.

**What is honest about the current state.** Only the website channel is fully
two-way today. Instagram can *send* through NovinHub but cannot *read* DMs,
because that needs an app review Meta grants to businesses with a track record.
The adapter says `can_receive = False` rather than pretending, and the inbox
shows the shop why a channel is one-way instead of leaving them to notice that
replies never arrive.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Channel:
    key: str
    title: str
    #: Can messages arrive from this channel into our inbox?
    can_receive: bool
    #: Can we send from the inbox to a customer on this channel?
    can_send: bool
    #: Settings keys that must be filled for it to work at all.
    requires: tuple[str, ...] = ()
    #: Settings keys needed **only to receive**. A channel can be perfectly
    #: usable for publishing while its inbound half waits on credentials, and
    #: collapsing the two into `requires` would switch off a working sender.
    receives_with: tuple[str, ...] = ()
    #: Why it is limited, when it is. Shown to the shop rather than logged.
    note: str = ""
    #: Per-message character ceiling, where one exists.
    max_chars: int | None = None


WEBSITE = Channel(
    key="WEB",
    title="چت سایت و پنل",
    can_receive=True,
    can_send=True,
    note="",
)

INSTAGRAM = Channel(
    key="INSTAGRAM",
    title="اینستاگرام",
    # Receiving is built (`apps/customers/webhooks.py`) and turns on with the
    # Meta credentials. Without them it stays off and says so, because a shop
    # waiting three days for a DM that never arrives was hurt by the interface,
    # not by the integration.
    can_receive=True,
    can_send=True,
    requires=("NOVINHUB_TOKEN",),
    receives_with=("META_APP_SECRET", "META_VERIFY_TOKEN"),
    note=(
        "انتشار پست با نوین‌هاب کار می‌کند. خواندن دایرکت هم ساخته شده و "
        "با تأیید اپ در Meta روشن می‌شود — آدرس وب‌هوکش در همین صفحه است."
    ),
)

TELEGRAM = Channel(
    key="TELEGRAM",
    title="تلگرام",
    # Two-way for real since the inbound webhook exists. Until then this said
    # `True` and nothing implemented it — the bot could answer and never heard
    # anything, which reads as a broken integration because it was one.
    can_receive=True,
    can_send=True,
    requires=("TELEGRAM_BOT_TOKEN",),
    note=(
        "ربات را خودتان در @BotFather می‌سازید و توکنش را اینجا می‌گذارید. "
        "برای دریافت پیام، آدرس وب‌هوک همین صفحه را به تلگرام بدهید."
    ),
)

WHATSAPP = Channel(
    key="WHATSAPP",
    title="واتساپ",
    can_receive=True,
    can_send=True,
    requires=("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID"),
    note="نیازمند حساب WhatsApp Business و تأیید شماره.",
)

SMS = Channel(
    key="SMS",
    title="پیامک",
    can_receive=False,
    can_send=True,
    requires=("SMS_API_KEY",),
    max_chars=480,
    note="یک‌طرفه: برای اطلاع‌رسانی سفارش، نه گفتگو.",
)

API = Channel(
    key="API",
    title="از طریق API",
    can_receive=True,
    can_send=True,
    note="وقتی سیستم خودتان پیام‌ها را به آپ‌مارکت می‌دهد.",
)

CHANNELS = [WEBSITE, INSTAGRAM, TELEGRAM, WHATSAPP, SMS, API]
BY_KEY = {c.key: c for c in CHANNELS}


def get(key: str) -> Channel:
    """The channel, or the website one as a safe default.

    Unknown keys happen — an old row, a typo in an API payload — and falling
    back to the most capable, least dangerous channel keeps an inbox working
    rather than raising where a customer is waiting.
    """
    return BY_KEY.get((key or "").upper(), WEBSITE)


def configured(channel: Channel, store) -> bool:
    """Is everything this channel needs actually filled in?

    Per-store settings win over the shared `.env` values, because a shop with
    its own NovinHub account should not be sharing ours.
    """
    if not channel.requires:
        return True

    from django.conf import settings

    profile = getattr(store, "profile", None)
    conf = settings.UPMARKET_AI

    for key in channel.requires:
        if key == "NOVINHUB_TOKEN":
            if (profile and (profile.novinhub_token or "").strip()) or conf.get(key):
                continue
            return False
        if key == "TELEGRAM_BOT_TOKEN":
            if telegram_token(store):
                continue
            return False
        if not conf.get(key):
            return False
    return True


def telegram_token(store) -> str:
    """This shop's own bot token, or the shared one behind it.

    A shop that pastes a token from @BotFather gets a bot of its own; one that
    leaves it empty keeps using the installation's shared bot exactly as
    before. Without this, every shop answered from the same bot — the second
    shop to connect was speaking in the first one's name.
    """
    from django.conf import settings

    profile = getattr(store, "profile", None)
    own = (getattr(profile, "telegram_bot_token", "") or "").strip()
    return own or settings.UPMARKET_AI.get("TELEGRAM_BOT_TOKEN", "")


def status_for(store) -> list[dict]:
    """What the shop can do on each channel right now, and what is missing.

    The `reason` field is the one that earns its place: a channel that is off
    because a token is missing needs a different action from one that is
    one-way by design, and a single "unavailable" badge conflates them.
    """
    rows = []
    from django.conf import settings

    conf = settings.UPMARKET_AI
    for channel in CHANNELS:
        ready = configured(channel, store)
        # Receiving can need its own credentials — Meta's, for Instagram — and
        # not having them must not make the sender look broken.
        inbound_missing = [k for k in channel.receives_with if not conf.get(k)]
        can_receive = channel.can_receive and ready and not inbound_missing

        reason = ""
        if not ready:
            reason = "تنظیم نشده: " + "، ".join(channel.requires)
        elif inbound_missing:
            reason = "فقط ارسال — برای دریافت لازم است: " + "، ".join(inbound_missing)
        elif not channel.can_receive:
            reason = channel.note
        rows.append({
            "key": channel.key,
            "title": channel.title,
            "can_receive": can_receive,
            "can_send": channel.can_send and ready,
            "configured": ready,
            "requires": list(channel.requires),
            "receives_with": list(channel.receives_with),
            "note": channel.note,
            "reason": reason,
        })
    return rows


def send(channel_key: str, store, *, to: str, text: str) -> dict:
    """Deliver one message. Returns what happened, never raises for the caller.

    A failed send is information the shop needs in the conversation, not an
    exception that loses the reply someone typed.
    """
    channel = get(channel_key)

    if not channel.can_send:
        return {"sent": False, "reason": f"{channel.title} ارسال پیام ندارد."}
    if not configured(channel, store):
        return {
            "sent": False,
            "reason": f"{channel.title} تنظیم نشده: " + "، ".join(channel.requires),
        }
    if channel.max_chars and len(text) > channel.max_chars:
        return {
            "sent": False,
            "reason": (
                f"پیام از سقف {channel.max_chars} کاراکترِ {channel.title} بلندتر است."
            ),
        }

    if channel.key == WEBSITE.key or channel.key == API.key:
        # Nothing to deliver: the customer reads it in the same thread, and the
        # message row IS the delivery.
        return {"sent": True, "reason": ""}

    if channel.key == TELEGRAM.key:
        return _send_telegram(store, to, text)

    # Instagram and WhatsApp send through the publishing integration the shop
    # already configured; SMS through its provider. Each is a thin call, and
    # each reports its own failure rather than a generic one.
    return _send_via_integration(channel, store, to, text)


def _send_telegram(store, to: str, text: str) -> dict:
    import requests

    token = telegram_token(store)
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": to, "text": text},
            timeout=15,
        )
    except requests.RequestException as exc:
        return {"sent": False, "reason": f"تلگرام در دسترس نبود: {exc}"[:200]}
    if response.status_code >= 400:
        return {"sent": False, "reason": f"تلگرام پیام را نپذیرفت ({response.status_code})"}
    return {"sent": True, "reason": ""}


def _send_via_integration(channel: Channel, store, to: str, text: str) -> dict:
    """Hand off to the publishing layer, which owns the vendor tokens."""
    try:
        from services.publishing import n8n

        n8n.send_message(store, channel=channel.key, to=to, text=text)
    except Exception as exc:  # noqa: BLE001 — the reply must not be lost
        return {"sent": False, "reason": f"ارسال ممکن نشد: {exc}"[:200]}
    return {"sent": True, "reason": ""}
