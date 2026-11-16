"""Unified social inbox - the parts `apps.customers` does not have.

`apps.customers` owns the conversation itself (Customer, Conversation,
Message, Order, Notification) and other work is landing there, so this app
**wraps it and never edits its tables**: everything the inbox adds - who is on
the team, how fast they answer, which channel is connected, who may be
messaged, what was sent to whom - lives here and points back with foreign keys.
The one-to-one "meta" rows (`ConversationMeta`, `MessageMeta`) are the pattern:
a conversation row stays exactly what it was, and the inbox's bookkeeping hangs
off it.
"""
from __future__ import annotations

import secrets

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.stores.models import Store

# --------------------------------------------------------------- channels


class ChannelConnection(TimeStampedModel):
    """One platform account a store has plugged into the inbox."""

    class Kind(models.TextChoices):
        TELEGRAM = "TELEGRAM", "تلگرام"
        BALE = "BALE", "بله"
        EITAA = "EITAA", "ایتا"
        RUBIKA = "RUBIKA", "روبیکا"
        WEBCHAT = "WEBCHAT", "چت سایت"
        SMS = "SMS", "پیامک"
        WHATSAPP = "WHATSAPP", "واتساپ"
        INSTAGRAM = "INSTAGRAM", "اینستاگرام"

    class Mode(models.TextChoices):
        AUTO = "AUTO", "خودکار"
        WEBHOOK = "WEBHOOK", "وب‌هوک"
        POLLING = "POLLING", "پرسش دوره‌ای"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="inbox_channels")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=80, blank=True)
    #: Bot token / API key. Never returned by the API - only a masked tail.
    token = models.CharField(max_length=400, blank=True)
    #: Random, in the webhook URL (a bearer credential, like `webhook_secret`).
    secret = models.CharField(max_length=64, blank=True, db_index=True)
    config = models.JSONField(default=dict, blank=True)
    #: Off until the owner switches it on - a connection row exists the moment a
    #: store opens its guide, long before there is anything to listen to.
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.AUTO)

    poll_cursor = models.CharField(max_length=120, blank=True)
    poll_claimed_at = models.DateTimeField(null=True, blank=True)
    last_poll_at = models.DateTimeField(null=True, blank=True)

    health_ok = models.BooleanField(null=True, blank=True)
    health_detail = models.CharField(max_length=300, blank=True)
    health_checked_at = models.DateTimeField(null=True, blank=True)
    account_label = models.CharField(max_length=120, blank=True)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    last_outbound_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    inbound_count = models.PositiveIntegerField(default=0)
    outbound_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "اتصال کانال"
        verbose_name_plural = "اتصال‌های کانال"
        constraints = [
            models.UniqueConstraint(fields=["store", "kind"], name="inbox_one_connection_per_kind"),
        ]

    def save(self, *args, **kwargs):
        if not self.secret:
            self.secret = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    @property
    def masked_token(self) -> str:
        token = (self.token or "").strip()
        if not token:
            return ""
        return "••••" + token[-4:] if len(token) > 8 else "••••"

    def __str__(self):
        return f"{self.get_kind_display()} · {self.store_id}"


# ------------------------------------------------------------------ team


class InboxSettings(TimeStampedModel):
    """Everything about how a store's inbox behaves, in one row."""

    class Assignment(models.TextChoices):
        MANUAL = "MANUAL", "دستی"
        ROUND_ROBIN = "ROUND_ROBIN", "نوبتی"
        BY_CHANNEL = "BY_CHANNEL", "بر اساس کانال"
        BY_SKILL = "BY_SKILL", "بر اساس مهارت"

    class AssignWhen(models.TextChoices):
        HANDOFF = "HANDOFF", "وقتی نوبت آدم شد"
        ALWAYS = "ALWAYS", "از اولین پیام"

    class OffHours(models.TextChoices):
        BOT = "BOT", "ربات جواب بدهد"
        MESSAGE = "MESSAGE", "پیام خارج از ساعت + صف برای فردا"
        QUEUE = "QUEUE", "فقط صف (بی‌پاسخ خودکار)"

    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name="inbox_settings")

    # -- assignment & SLA ---------------------------------------------
    assignment_mode = models.CharField(max_length=12, choices=Assignment.choices, default=Assignment.MANUAL)
    assign_when = models.CharField(max_length=8, choices=AssignWhen.choices, default=AssignWhen.HANDOFF)
    assign_only_online = models.BooleanField(default=True)
    sla_first_response_min = models.PositiveIntegerField(default=15)
    sla_warn_percent = models.PositiveSmallIntegerField(default=80)
    sla_pause_off_hours = models.BooleanField(default=True)

    # -- working hours ------------------------------------------------
    #: {"days": [5,6,0,1,2,3], "start": "09:00", "end": "18:00"} - python weekday
    #: numbers (Mon=0 ... Sun=6), Tehran time. Empty = always open.
    working_hours = models.JSONField(default=dict, blank=True)

    # -- AI bot -------------------------------------------------------
    bot_enabled = models.BooleanField(default=True)
    bot_min_confidence = models.FloatField(default=0.55)
    bot_handoff_keywords = models.JSONField(default=list, blank=True)
    bot_offhours = models.CharField(max_length=8, choices=OffHours.choices, default=OffHours.BOT)
    offhours_message = models.TextField(blank=True)
    greeting_message = models.TextField(blank=True)

    # -- survey -------------------------------------------------------
    survey_enabled = models.BooleanField(default=False)
    survey_text = models.TextField(blank=True)
    survey_delay_min = models.PositiveIntegerField(default=10)

    # -- payment reminders --------------------------------------------
    payment_reminder_enabled = models.BooleanField(default=False)
    payment_reminder_hours = models.PositiveIntegerField(default=24)
    payment_reminder_max = models.PositiveSmallIntegerField(default=2)
    payment_reminder_text = models.TextField(blank=True)

    # -- broadcast ----------------------------------------------------
    #: Messages per minute per channel. A broadcast that goes faster than a
    #: platform tolerates gets the bot banned - which is the shop's whole line
    #: to its customers, so the defaults are conservative.
    rate_limits = models.JSONField(default=dict, blank=True)
    merge_by_username = models.BooleanField(default=True)

    # -- web chat widget ----------------------------------------------
    widget = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "تنظیمات صندوق"
        verbose_name_plural = "تنظیمات صندوق"

    def __str__(self):
        return f"InboxSettings · store {self.store_id}"


class AgentProfile(TimeStampedModel):
    """A team member as the inbox sees them."""

    class Status(models.TextChoices):
        ONLINE = "ONLINE", "آنلاین"
        BUSY = "BUSY", "مشغول"
        OFFLINE = "OFFLINE", "آفلاین"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="inbox_agents")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="inbox_profiles")
    display_name = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OFFLINE)
    status_note = models.CharField(max_length=120, blank=True)
    #: Last time the panel told us this person is looking at the inbox.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_assigned_at = models.DateTimeField(null=True, blank=True)
    accepts_chats = models.BooleanField(default=True)
    #: Channel keys this person covers; empty = every channel.
    channels = models.JSONField(default=list, blank=True)
    skills = models.JSONField(default=list, blank=True)
    max_open = models.PositiveSmallIntegerField(default=12)

    class Meta:
        verbose_name = "عضو تیم صندوق"
        verbose_name_plural = "اعضای تیم صندوق"
        constraints = [
            models.UniqueConstraint(fields=["store", "user"], name="inbox_one_profile_per_member"),
        ]

    #: A person who has not touched the panel for this long is not "online",
    #: whatever they last clicked - closing the laptop never sets a status.
    PRESENCE_TTL_SECONDS = 5 * 60

    @property
    def effective_status(self) -> str:
        if self.status == self.Status.OFFLINE:
            return self.Status.OFFLINE
        if not self.last_seen_at:
            return self.Status.OFFLINE
        if (timezone.now() - self.last_seen_at).total_seconds() > self.PRESENCE_TTL_SECONDS:
            return self.Status.OFFLINE
        return self.status

    @property
    def name(self) -> str:
        return self.display_name or self.user.get_full_name() or self.user.username

    def __str__(self):
        return f"{self.name} @ store {self.store_id}"


# ------------------------------------------------------- conversation meta


class ConversationMeta(models.Model):
    """The inbox's bookkeeping for one `customers.Conversation`."""

    conversation = models.OneToOneField(
        "customers.Conversation", on_delete=models.CASCADE, related_name="inbox_meta",
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="+")
    #: Customer messages nobody on the team has looked at yet.
    unread_count = models.PositiveIntegerField(default=0)
    last_read_at = models.DateTimeField(null=True, blank=True)
    #: Since when a *person* owes the customer an answer (None while the AI is
    #: working or nothing is owed). The SLA clock and the waiting-time sort.
    waiting_since = models.DateTimeField(null=True, blank=True)
    sla_due_at = models.DateTimeField(null=True, blank=True)
    sla_warned_at = models.DateTimeField(null=True, blank=True)
    sla_breached_at = models.DateTimeField(null=True, blank=True)
    first_human_reply_at = models.DateTimeField(null=True, blank=True)
    first_response_seconds = models.PositiveIntegerField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    reopened_count = models.PositiveSmallIntegerField(default=0)
    handoff_reason = models.CharField(max_length=200, blank=True)
    bot_confidence = models.FloatField(null=True, blank=True)
    priority = models.PositiveSmallIntegerField(default=0)
    is_test = models.BooleanField(default=False)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    survey_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["store", "waiting_since"])]

    def __str__(self):
        return f"meta of conversation {self.conversation_id}"


class MessageMeta(models.Model):
    """Who wrote an outgoing message, how fast, and whether it arrived."""

    class Kind(models.TextChoices):
        REPLY = "REPLY", "پاسخ تیم"
        BOT = "BOT", "ربات"
        BROADCAST = "BROADCAST", "ارسال گروهی"
        FOLLOWUP = "FOLLOWUP", "پیگیری"
        PAYMENT = "PAYMENT", "یادآوری پرداخت"
        SURVEY = "SURVEY", "نظرسنجی"
        SYSTEM = "SYSTEM", "سیستم"

    message = models.OneToOneField(
        "customers.Message", on_delete=models.CASCADE, related_name="inbox_meta",
    )
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.REPLY)
    delivered = models.BooleanField(null=True, blank=True)
    delivery_error = models.CharField(max_length=300, blank=True)
    platform_message_id = models.CharField(max_length=120, blank=True)
    #: Seconds between when the customer started waiting and this reply.
    response_seconds = models.PositiveIntegerField(null=True, blank=True)
    canned_reply = models.ForeignKey(
        "inbox.CannedReply", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )


class InternalNote(TimeStampedModel):
    """A note only the team sees. Never sent, never read by the AI."""

    conversation = models.ForeignKey(
        "customers.Conversation", on_delete=models.CASCADE, related_name="inbox_notes",
    )
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    text = models.TextField()
    #: Usernames mentioned with @ - each gets a notification.
    mentions = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["created_at"]


class CannedReply(TimeStampedModel):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="canned_replies")
    title = models.CharField(max_length=80)
    shortcut = models.CharField(max_length=30, blank=True)
    text = models.TextField()
    #: Channel keys it applies to; empty = all.
    channels = models.JSONField(default=list, blank=True)
    use_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["title"]


# --------------------------------------------------------------- contacts


class Contact(TimeStampedModel):
    """One real person, however many channels they wrote from."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=200, blank=True)
    #: Normalised: 09123456789 form for Iranian mobiles, digits only otherwise.
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    usernames = models.JSONField(default=list, blank=True)
    email = models.CharField(max_length=200, blank=True)
    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    #: {"ALL": true} or {"TELEGRAM": true}. Marketing only: a person who opted
    #: out of broadcasts still gets the answer to the question they just asked.
    opt_out = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=40, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    is_test = models.BooleanField(default=False)
    #: Cached from orders by `contacts.refresh_stats` - segments filter on them.
    orders_count = models.PositiveIntegerField(default=0)
    total_spent = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    last_purchase_at = models.DateTimeField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "مخاطب"
        verbose_name_plural = "مخاطبان"
        ordering = ["-last_activity_at", "-id"]
        indexes = [models.Index(fields=["store", "phone"])]

    def __str__(self):
        return self.name or self.phone or f"Contact #{self.pk}"

    def opted_out_of(self, channel: str) -> bool:
        flags = self.opt_out or {}
        return bool(flags.get("ALL") or flags.get((channel or "").upper()))


class ContactLink(models.Model):
    """Which `customers.Customer` rows are this contact (one per channel)."""

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="links")
    customer = models.OneToOneField(
        "customers.Customer", on_delete=models.CASCADE, related_name="inbox_link",
    )
    matched_by = models.CharField(max_length=20, blank=True)  # phone / username / manual / new
    created_at = models.DateTimeField(default=timezone.now)


class Segment(TimeStampedModel):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="inbox_segments")
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True)
    #: {"match": "all"|"any", "rules": [{"field", "op", "value"}]}
    rules = models.JSONField(default=dict, blank=True)
    builtin_key = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "builtin_key"], condition=~models.Q(builtin_key=""),
                name="inbox_one_builtin_segment",
            ),
        ]


# ------------------------------------------------------------- broadcast


class Broadcast(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "پیش‌نویس"
        PENDING = "PENDING", "منتظر تأیید مالک"
        APPROVED = "APPROVED", "تأییدشده"
        SENDING = "SENDING", "در حال ارسال"
        SENT = "SENT", "ارسال‌شده"
        REJECTED = "REJECTED", "ردشده"
        CANCELLED = "CANCELLED", "لغوشده"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="broadcasts")
    name = models.CharField(max_length=120)
    text = models.TextField()
    channels = models.JSONField(default=list, blank=True)
    segment = models.ForeignKey(Segment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=300, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    #: A demo/draft broadcast: recipients are listed but nothing is ever sent.
    is_test = models.BooleanField(default=False)
    #: One message per person (their best channel) rather than one per channel.
    dedupe = models.BooleanField(default=True)
    stats = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]


class BroadcastRecipient(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        SENT = "SENT", "فرستاده شد"
        FAILED = "FAILED", "ناموفق"
        SKIPPED = "SKIPPED", "رد شد"

    broadcast = models.ForeignKey(Broadcast, on_delete=models.CASCADE, related_name="recipients")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="+")
    channel = models.CharField(max_length=12)
    to = models.CharField(max_length=120)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED)
    skip_reason = models.CharField(max_length=40, blank=True)
    error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["broadcast", "contact", "channel"], name="inbox_one_recipient"),
        ]
        indexes = [models.Index(fields=["broadcast", "status"])]


# ---------------------------------------------------------- follow-ups etc


class FollowUp(TimeStampedModel):
    class Kind(models.TextChoices):
        FOLLOWUP = "FOLLOWUP", "پیگیری"
        PAYMENT = "PAYMENT", "یادآوری پرداخت"
        SURVEY = "SURVEY", "نظرسنجی"

    class Status(models.TextChoices):
        PENDING = "PENDING", "در انتظار"
        SENT = "SENT", "انجام شد"
        CANCELLED = "CANCELLED", "لغو شد"
        FAILED = "FAILED", "ناموفق"

    class Target(models.TextChoices):
        CUSTOMER = "CUSTOMER", "پیام به مشتری"
        AGENT = "AGENT", "یادآوری به همکار"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="inbox_followups")
    conversation = models.ForeignKey(
        "customers.Conversation", on_delete=models.CASCADE, null=True, blank=True, related_name="followups",
    )
    order = models.ForeignKey(
        "customers.Order", on_delete=models.CASCADE, null=True, blank=True, related_name="+",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FOLLOWUP)
    target = models.CharField(max_length=10, choices=Target.choices, default=Target.CUSTOMER)
    text = models.TextField(blank=True)
    due_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    is_test = models.BooleanField(default=False)

    class Meta:
        ordering = ["due_at"]
        indexes = [models.Index(fields=["status", "due_at"])]


class SatisfactionSurvey(TimeStampedModel):
    conversation = models.ForeignKey(
        "customers.Conversation", on_delete=models.CASCADE, related_name="surveys",
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="+")
    sent_at = models.DateTimeField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.CharField(max_length=500, blank=True)
    #: Who handled the conversation when it closed - the survey is about them.
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")


# ------------------------------------------------------------- outgoing hooks
#
# API keys are NOT here: a store's keys already live in `apps.api_platform` (hashed,
# scoped, metered, with a panel page) and the inbox API uses those - see views_dev.



class WebhookEndpoint(TimeStampedModel):
    """Where we POST inbox events (message.received, conversation.closed ...)."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="inbox_webhooks")
    url = models.URLField(max_length=500)
    secret = models.CharField(max_length=64)
    events = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    failure_count = models.PositiveIntegerField(default=0)
    last_status = models.CharField(max_length=60, blank=True)
    last_delivery_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.secret:
            self.secret = secrets.token_hex(24)
        super().save(*args, **kwargs)


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "در صف"
        OK = "OK", "رسید"
        FAILED = "FAILED", "ناموفق"

    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=40)
    event_id = models.CharField(max_length=40, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]


# ------------------------------------------------------------- web widget


class WidgetSession(models.Model):
    """One browser tab talking to the site-chat widget."""

    connection = models.ForeignKey(ChannelConnection, on_delete=models.CASCADE, related_name="sessions")
    token = models.CharField(max_length=64, unique=True)
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="+")
    conversation = models.ForeignKey("customers.Conversation", on_delete=models.CASCADE, related_name="+")
    origin = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)
