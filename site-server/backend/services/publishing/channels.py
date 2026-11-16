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
    #: Owned by `apps.inbox` (its adapters, its connect page, its health): sending
    #: and "is it configured" are delegated there, so one `send()` still delivers
    #: on every channel and nothing upstream learned a new platform.
    managed: bool = False


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
    max_chars=4096,
    managed=True,
    note="نیازمند حساب رسمی WhatsApp Business؛ به‌طور پیش‌فرض خاموش است.",
)

SMS = Channel(
    key="SMS",
    title="پیامک",
    # Two-way through the owner's paired phones (apps.mobile): the phone sends
    # from its SIM and forwards what it receives. Managed by the unified inbox.
    can_receive=True,
    can_send=True,
    max_chars=480,
    note="با گوشی‌های متصل به سرویس پیامک؛ گفتگوی کوتاه است و هزینهٔ سیم‌کارت دارد.",
    managed=True,
)

BALE = Channel(
    key="BALE", title="بله", can_receive=True, can_send=True, max_chars=4096, managed=True,
    note="ربات بله؛ توکن را در صفحهٔ «کانال‌ها» وارد کنید.",
)
EITAA = Channel(
    key="EITAA", title="ایتا", can_receive=True, can_send=True, max_chars=4096, managed=True,
    note="ربات ایتایار؛ ارسال همیشه، دریافت اگر برای ربات فعال باشد.",
)
RUBIKA = Channel(
    key="RUBIKA", title="روبیکا", can_receive=True, can_send=True, max_chars=4096, managed=True,
    note="ربات روبیکا؛ توکن را در صفحهٔ «کانال‌ها» وارد کنید.",
)
WEBCHAT = Channel(
    key="WEBCHAT", title="چت سایت", can_receive=True, can_send=True, max_chars=4000, managed=True,
    note="ویجت گفتگو روی سایت شما؛ یک تکه کد.",
)

API = Channel(
    key="API",
    title="از طریق API",
    can_receive=True,
    can_send=True,
    note="وقتی سیستم خودتان پیام‌ها را به آپ‌مارکت می‌دهد.",
)

CHANNELS = [WEBSITE, INSTAGRAM, TELEGRAM, BALE, EITAA, RUBIKA, WEBCHAT, WHATSAPP, SMS, API]
BY_KEY = {c.key: c for c in CHANNELS}


def get(key: str) -> Channel:
    """The channel, or the website one as a safe default.

    Unknown keys happen — an old row, a typo in an API payload — and falling
    back to the most capable, least dangerous channel keeps an inbox working
    rather than raising where a customer is waiting.
    """
    return BY_KEY.get((key or "").upper(), WEBSITE)


#: What a missing setting means to the shop — in words, never the setting's own
#: name. `input` is the field on the connections page where the shop can fill
#: it in ("" = not something a shop sets itself: the installation's own account
#: or approval, which the service's administrator arranges).
REQUIREMENT_LABELS: dict[str, tuple[str, str]] = {
    "NOVINHUB_TOKEN": ("توکن نوین‌هاب", "novinhub_token"),
    "TELEGRAM_BOT_TOKEN": ("توکن ربات تلگرام", "telegram_bot_token"),
    "WHATSAPP_TOKEN": ("اتصال به واتساپ بیزینس", ""),
    "WHATSAPP_PHONE_ID": ("شمارهٔ تأییدشدهٔ واتساپ بیزینس", ""),
    "SMS_API_KEY": ("سرویس پیامک", ""),
    "META_APP_SECRET": ("تأیید اپ در Meta", ""),
    "META_VERIFY_TOKEN": ("تأیید اپ در Meta", ""),
}


def describe_missing(keys) -> list[dict]:
    """`[{label, input}]` for these settings keys — de-duplicated, in order."""
    out: list[dict] = []
    for key in keys:
        label, field = REQUIREMENT_LABELS.get(key, ("یک تنظیم این کانال", ""))
        if not any(item["label"] == label for item in out):
            out.append({"label": label, "input": field})
    return out


def _missing_sentence(items: list[dict]) -> str:
    """«توکن نوین‌هاب» / «سرویس پیامک (راه‌اندازی‌اش با مدیر سرویس است)»."""
    parts = [
        i["label"] if i["input"] else f"{i['label']} (راه‌اندازی‌اش با مدیر سرویس است)"
        for i in items
    ]
    return "، ".join(parts)


def shared_value(key: str) -> str:
    """The installation-wide value of a credential, wherever settings keep it.

    `NOVINHUB_TOKEN` lives in `UPMARKET_PUBLISHING`, the channel credentials in
    `UPMARKET_AI`; reading only one of them made a perfectly good shared token
    invisible to the other half of the product.
    """
    from django.conf import settings

    for block in ("UPMARKET_AI", "UPMARKET_PUBLISHING"):
        value = (getattr(settings, block, None) or {}).get(key, "")
        if value:
            return str(value)
    return ""


def configured(channel: Channel, store) -> bool:
    """Is everything this channel needs actually filled in?

    Per-store settings win over the shared `.env` values, because a shop with
    its own NovinHub account should not be sharing ours.
    """
    if channel.managed:
        from apps.inbox import dispatch

        return dispatch.configured(channel.key, store)

    if not channel.requires:
        return True

    profile = getattr(store, "profile", None)

    for key in channel.requires:
        if key == "NOVINHUB_TOKEN":
            if (profile and (profile.novinhub_token or "").strip()) or shared_value(key):
                continue
            return False
        if key == "TELEGRAM_BOT_TOKEN":
            if telegram_token(store):
                continue
            return False
        if not shared_value(key):
            return False
    return True


def telegram_token(store) -> str:
    """This shop's own bot token, or the shared one behind it.

    A shop that pastes a token from @BotFather gets a bot of its own; one that
    leaves it empty keeps using the installation's shared bot exactly as
    before. Without this, every shop answered from the same bot — the second
    shop to connect was speaking in the first one's name.
    """
    profile = getattr(store, "profile", None)
    own = (getattr(profile, "telegram_bot_token", "") or "").strip()
    return own or shared_value("TELEGRAM_BOT_TOKEN")


def status_for(store) -> list[dict]:
    """What the shop can do on each channel right now, and what is missing.

    The `reason` field is the one that earns its place: a channel that is off
    because a token is missing needs a different action from one that is
    one-way by design, and a single "unavailable" badge conflates them.

    `reason` is for people: it names what is missing in words («توکن
    نوین‌هاب»), never a settings key. `missing` is the same thing as data —
    `[{label, input}]`, where `input` is the field on the connections page that
    fixes it (empty when only the service's administrator can).
    """
    rows = []
    for channel in CHANNELS:
        ready = configured(channel, store)
        # Receiving can need its own credentials — Meta's, for Instagram — and
        # not having them must not make the sender look broken.
        inbound_missing = [k for k in channel.receives_with if not shared_value(k)]
        can_receive = channel.can_receive and ready and not inbound_missing

        missing = describe_missing(channel.requires) if not ready else []
        receives_missing = describe_missing(inbound_missing) if ready else []

        reason = ""
        if not ready and channel.managed:
            reason = "هنوز وصل نشده: از صفحهٔ «کانال‌ها» در صندوق پیام وصلش کنید."
        elif not ready:
            reason = "تنظیم نشده: " + _missing_sentence(missing)
        elif inbound_missing:
            reason = "فقط ارسال — برای دریافت لازم است: " + _missing_sentence(receives_missing)
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
            "missing": missing,
            "receives_missing": receives_missing,
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
    if channel.managed:
        from apps.inbox import dispatch

        return dispatch.send(channel.key, store, to=to, text=text)
    if not configured(channel, store):
        return {
            "sent": False,
            "reason": f"{channel.title} تنظیم نشده: "
            + _missing_sentence(describe_missing(channel.requires)),
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
    except requests.RequestException:
        # Not the exception text: a connection error quotes the request URL,
        # and the URL of this call contains the bot's token.
        return {"sent": False, "reason": "تلگرام در دسترس نبود؛ کمی بعد دوباره امتحان کنید."}
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
