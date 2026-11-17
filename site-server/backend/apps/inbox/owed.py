"""«Who is waiting for an answer?» - one definition, used by every number on screen.

The inbox's «منتظر پاسخ» tab, the «بدون مسئول» tab, the Team page tiles and
`stats/` all answered this question in their own way (a thread stayed «waiting»
until somebody closed it, even after the team had answered; the Team tile and the
tab disagreed by tens). They now all use the filters below, so the number on a
tab is the length of the list it opens.

A conversation is **owed an answer** when

* a person has it (HUMAN / ESCALATED) **and** either the SLA clock is running
  (`ConversationMeta.waiting_since`: set when a person starts owing an answer,
  cleared when the team replies), or - a thread from before the clock existed -
  no team member has written after the customer's last message; or
* the bot has it, tried to answer and could not (`ai_failed_at`).

A thread the team has already answered is **not** waiting: it is simply open.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.db.models import DateTimeField, Exists, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from apps.customers.models import Conversation, Message

PERSON_STATES = (Conversation.State.HUMAN, Conversation.State.ESCALATED)
OPEN_STATES = (Conversation.State.AI, Conversation.State.HUMAN, Conversation.State.ESCALATED)

_EPOCH = Value(datetime(1970, 1, 1, tzinfo=dt_timezone.utc), output_field=DateTimeField())
#: When the customer last wrote - read from the messages themselves, so a code path
#: that forgot to bump `Conversation.last_customer_at` cannot make a thread look answered.
_CUSTOMER_LAST = Subquery(
    Message.objects.filter(conversation=OuterRef(OuterRef("pk")), role=Message.Role.CUSTOMER)
    .order_by("-created_at", "-id").values("created_at")[:1]
)
#: A person on the team wrote at or after the customer's last message. (The bot's own
#: hand-off line is not an answer - the person it promised is still owed.)
_ANSWERED = Exists(
    Message.objects.filter(
        conversation=OuterRef("pk"), role=Message.Role.HUMAN,
        created_at__gte=Coalesce(_CUSTOMER_LAST, _EPOCH),
    )
)

OWED_BY_PERSON = Q(state__in=PERSON_STATES) & (Q(inbox_meta__waiting_since__isnull=False) | ~_ANSWERED)
OWED_BY_AI = Q(state=Conversation.State.AI, ai_failed_at__isnull=False)
OWED = OWED_BY_PERSON | OWED_BY_AI
