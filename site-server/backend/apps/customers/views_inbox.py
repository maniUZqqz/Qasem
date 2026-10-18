"""One inbox for every channel. §9.7.

The sort order is the design decision worth naming: **longest-waiting first**,
measured from when the *customer* last wrote — not from `updated_at`. Sorting by
`updated_at` puts the conversations we just answered at the top and buries the
person who has been waiting since this morning, which is exactly backwards for
a queue whose whole purpose is "who needs us next".
"""
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access
from services.publishing import channels

from .models import Conversation, Message
from apps.common.utils import with_tag


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

    class Meta:
        model = Conversation
        fields = [
            "id", "customer", "customer_name", "state", "channel", "channel_title",
            "assigned_to", "assigned_username", "tags", "waiting_minutes",
            "last_message", "can_reply", "last_customer_at", "updated_at",
        ]

    def get_channel_title(self, obj) -> str:
        return channels.get(obj.channel).title

    def get_last_message(self, obj) -> dict | None:
        message = obj.messages.order_by("-created_at").first()
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

        rows = (
            Conversation.objects
            .filter(store=store)
            .select_related("customer", "assigned_to")
            .prefetch_related("messages")
        )

        state = request.query_params.get("state")
        if state:
            rows = rows.filter(state=state)

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
        waiting = rows.filter(
            Q(state=Conversation.State.HUMAN) | Q(state=Conversation.State.ESCALATED)
        ).order_by("last_customer_at")
        rest = rows.exclude(
            Q(state=Conversation.State.HUMAN) | Q(state=Conversation.State.ESCALATED)
        ).order_by("-updated_at")

        ordered = list(waiting) + list(rest[: max(0, 100 - waiting.count())])

        return Response({
            "conversations": InboxConversationSerializer(ordered, many=True).data,
            "channels": channels.status_for(store),
            "counts": {
                "waiting": waiting.count(),
                "unassigned": rows.filter(assigned_to__isnull=True).count(),
                "mine": rows.filter(assigned_to=request.user).count(),
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
        conversation.save(update_fields=["state", "assigned_to", "updated_at"])

        return Response({
            "message": {"id": message.pk, "text": message.text, "at": message.created_at},
            "delivered": outcome["sent"],
            "reason": outcome["reason"],
        })
