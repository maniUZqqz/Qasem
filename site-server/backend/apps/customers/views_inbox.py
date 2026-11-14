"""One inbox for every channel. §9.7.

The sort order is the design decision worth naming: **longest-waiting first**,
measured from when the *customer* last wrote — not from `updated_at`. Sorting by
`updated_at` puts the conversations we just answered at the top and buries the
person who has been waiting since this morning, which is exactly backwards for
a queue whose whole purpose is "who needs us next".

"Waiting" is not only «a person owes an answer» (HUMAN / ESCALATED). A customer
whose message the **AI failed to answer** is waiting too — `ai_failed_at` marks
those (see `ai_retry`) — and they sort with the longest waits and carry the
«AI جواب نداد» badge. Counting only the first kind is how the inbox once said
«۰ نفر منتظر» while two customers had heard nothing.
"""
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access
from services.publishing import channels

from . import ai_retry
from .models import Conversation, Message
from apps.common.utils import with_tag

#: A person owes the answer here.
OWED_BY_PERSON = Q(state=Conversation.State.HUMAN) | Q(state=Conversation.State.ESCALATED)
#: The AI owes the answer here and could not give it.
OWED_BY_AI = Q(state=Conversation.State.AI, ai_failed_at__isnull=False)


class InboxConversationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    assigned_username = serializers.CharField(
        source="assigned_to.username", read_only=True, default=None,
    )
    channel_title = serializers.SerializerMethodField()
    waiting_minutes = serializers.IntegerField(read_only=True)
    last_message = serializers.SerializerMethodField()
    #: False when this channel cannot deliver a reply. The inbox shows it so a
    #: colleague does not type an answer that goes nowhere.
    can_reply = serializers.SerializerMethodField()
    #: The AI was asked and did not answer (state AI, `ai_failed_at` set).
    ai_failed = serializers.BooleanField(read_only=True)
    #: Started from the panel's test chat — never retried automatically.
    is_test = serializers.BooleanField(read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id", "customer", "customer_name", "state", "channel", "channel_title",
            "assigned_to", "assigned_username", "tags", "waiting_minutes",
            "last_message", "can_reply", "last_customer_at", "updated_at",
            "ai_failed", "ai_failed_reason", "ai_retries", "is_test",
        ]

    def get_channel_title(self, obj) -> str:
        return channels.get(obj.channel).title

    def get_last_message(self, obj) -> dict | None:
        # Look through our own «پیام شما رسید»: the customer's words are what
        # the person scanning the inbox needs to see.
        message = ai_retry.last_visible_message(obj)
        if message is None:
            return None
        return {
            "role": message.role,
            "text": (message.text or "")[:160],
            "at": message.created_at,
        }

    def get_can_reply(self, obj) -> bool:
        channel = channels.get(obj.channel)
        return channel.can_send and channels.configured(channel, obj.store)


class InboxView(APIView):
    """Every conversation in one place, longest-waiting first."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS, write=False)

        everything = Conversation.objects.filter(store=store)
        rows = everything.select_related("customer", "assigned_to", "store")

        state = request.query_params.get("state")
        if state:
            rows = rows.filter(state=state)

        if request.query_params.get("ai_failed") in ("1", "true"):
            rows = rows.filter(OWED_BY_AI)

        channel = request.query_params.get("channel")
        if channel:
            rows = rows.filter(channel=channel.upper())

        assigned = request.query_params.get("assigned")
        if assigned == "me":
            rows = rows.filter(assigned_to=request.user)
        elif assigned == "nobody":
            # A real state worth seeing in a shared inbox, not a gap to fill.
            rows = rows.filter(assigned_to__isnull=True)

        tag = request.query_params.get("tag")
        if tag:
            rows = with_tag(rows, tag)

        # Longest-waiting first among those a person owes an answer to; then
        # everything else by recency.
        #
        # «Waiting» includes the customers the AI could not answer: they have
        # heard nothing, which is exactly what the queue exists to surface.
        owed = OWED_BY_PERSON | OWED_BY_AI
        waiting = rows.filter(owed).order_by("last_customer_at", "id")
        rest = rows.exclude(owed).order_by("-updated_at")

        ordered = list(waiting) + list(rest[: max(0, 100 - waiting.count())])

        return Response({
            "conversations": InboxConversationSerializer(ordered, many=True).data,
            "channels": channels.status_for(store),
            # How long a failed thread is retried before it goes to a person.
            "ai_retry_hours": ai_retry.config()["WINDOW_HOURS"],
            # Over the whole inbox, not the filtered view: the numbers sit on
            # the filter's own options, and «بدون مسئول (۰)» after choosing
            # «مال من» is a lie about the other filter.
            "counts": {
                "waiting": everything.filter(owed).count(),
                "ai_failed": everything.filter(OWED_BY_AI).count(),
                "unassigned": everything.filter(assigned_to__isnull=True).count(),
                "mine": everything.filter(assigned_to=request.user).count(),
            },
        })


class ConversationAssignView(APIView):
    """Take a conversation, hand it to someone, or put it back."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        conversation = get_object_or_404(Conversation, pk=pk, store=store)

        username = request.data.get("username")
        if username in (None, "", "me"):
            conversation.assigned_to = request.user if username == "me" else None
        else:
            person = User.objects.filter(username=username).first()
            if person is None or not access.role_of(person, store):
                return Response(
                    {"error": {
                        "code": "not_a_member",
                        "message": "این شخص عضو این فروشگاه نیست.",
                    }},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            conversation.assigned_to = person

        conversation.save(update_fields=["assigned_to", "updated_at"])
        return Response(InboxConversationSerializer(conversation).data)


class ConversationTagsView(APIView):
    """Labels the shop puts on a conversation."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        conversation = get_object_or_404(Conversation, pk=pk, store=store)

        tags = request.data.get("tags")
        if not isinstance(tags, list):
            return Response(
                {"error": {"code": "bad_tags", "message": "برچسب‌ها باید فهرست باشند."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cleaned = []
        for tag in tags[:12]:
            text = str(tag).strip()[:40]
            if text and text not in cleaned:
                cleaned.append(text)

        conversation.tags = cleaned
        conversation.save(update_fields=["tags", "updated_at"])
        return Response(InboxConversationSerializer(conversation).data)


class InboxReplyView(APIView):
    """Send a human reply out on whatever channel this conversation came in on."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        conversation = get_object_or_404(
            Conversation.objects.select_related("customer"), pk=pk, store=store,
        )

        text = str(request.data.get("text", "")).strip()
        if not text:
            return Response(
                {"error": {"code": "empty", "message": "متن پیام خالی است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        outcome = channels.send(
            conversation.channel, store,
            to=conversation.external_id or str(conversation.customer_id),
            text=text,
        )

        # The message is recorded either way. A reply that failed to deliver is
        # still something a colleague wrote and the next person needs to see —
        # losing it would mean two people writing the same answer.
        message = Message.objects.create(
            conversation=conversation,
            role=Message.Role.HUMAN,
            text=text,
        )
        # A human answered, so the AI should not jump back in on top of them.
        conversation.state = Conversation.State.HUMAN
        conversation.assigned_to = conversation.assigned_to or request.user
        # A person answered, so the AI no longer owes this customer anything.
        ai_retry.clear_failed(conversation)
        conversation.save(update_fields=[
            "state", "assigned_to", "updated_at", *ai_retry.CLEAR_FIELDS,
        ])

        return Response({
            "message": {"id": message.pk, "text": message.text, "at": message.created_at},
            "delivered": outcome["sent"],
            "reason": outcome["reason"],
        })


class ConversationRetryView(APIView):
    """«دوباره امتحان کن» — ask the AI again for one waiting conversation.

    The beat does this by itself when the AI is back; this is for the owner who
    has just fixed something (switched the node on, topped up the API) and does
    not want to wait for the next tick. Queued, not run in the request: a local
    model can take minutes and the inbox must stay responsive.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        conversation = get_object_or_404(
            Conversation.objects.select_related("customer"), pk=pk, store=store,
        )
        if not conversation.ai_failed:
            return Response(
                {"error": {
                    "code": "not_waiting_for_ai",
                    "message": "این گفتگو منتظر جواب AI نیست.",
                }},
                status=status.HTTP_409_CONFLICT,
            )
        ok, why = ai_retry.ai_available(store)
        if not ok:
            return Response(
                {"error": {
                    "code": "ai_unavailable",
                    "message": f"هنوز هیچ مسیری برای هوش مصنوعی آماده نیست — {why}",
                }},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        from .tasks import retry_conversation

        if not ai_retry._claim(conversation, timezone.now()):
            return Response(
                {"queued": False, "message": "همین الان در حال امتحان است."},
                status=status.HTTP_202_ACCEPTED,
            )
        retry_conversation.delay(conversation.pk)
        return Response(
            {"queued": True, "message": "دوباره امتحان می‌شود؛ چند لحظه بعد صندوق را تازه کنید."},
            status=status.HTTP_202_ACCEPTED,
        )


class ConversationResolveView(APIView):
    """Close a conversation nobody needs to answer (a test, a duplicate, spam)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        conversation = get_object_or_404(
            Conversation.objects.select_related("customer", "assigned_to"), pk=pk, store=store,
        )
        conversation.state = Conversation.State.RESOLVED
        ai_retry.clear_failed(conversation)
        conversation.save(update_fields=["state", "updated_at", *ai_retry.CLEAR_FIELDS])
        return Response(InboxConversationSerializer(conversation).data)
