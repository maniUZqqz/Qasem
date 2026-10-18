"""Consent, recordings, and what to say before you dial. صفحه ۷.

Three endpoints, and the shape of them is the argument:

`consent/` comes **first** and the recording upload refuses without it. Not
because an upload form with a checkbox would be hard, but because a checkbox
produces something indistinguishable from consent that was actually obtained.

`recordings/` accepts a file and hands the work to the background. Whisper on a
twenty-minute call is minutes of GPU, and a request that waits for it times out
in front of the person who just uploaded.

`prep/` is the «در ثانیه‌ی تماس کمک می‌کند» part of the spec, built from what
the shop already knows rather than from a live listener: who this is, what was
said last time, what they objected to before, and what this number matches in
the shop's own rows. A person reads it while the phone rings.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from .calls import CallConsent, Recording, match_known_contact
from .outreach import Prospect


class ConsentSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = CallConsent
        exclude = ["prospect"]
        read_only_fields = ["created_at", "updated_at"]


class RecordingSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    audio = serializers.FileField(read_only=True)

    class Meta:
        model = Recording
        exclude = ["store"]
        read_only_fields = [
            "status", "transcript", "summary", "sentiment", "objections",
            "commitments", "suggested_next", "error", "created_at", "updated_at",
        ]


def _prospect(request, store_id, pk) -> Prospect:
    store = access.get_store(request.user, store_id, access.CONVERSATIONS)
    return get_object_or_404(Prospect, pk=pk, store=store)


class ConsentView(APIView):
    """Record, read or revoke permission to record this person."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        prospect = _prospect(request, store_id, pk)
        row = CallConsent.objects.filter(prospect=prospect).first()
        return Response({
            "consent": ConsentSerializer(row).data if row else None,
            "hows": [
                {"value": v, "label": label} for v, label in CallConsent.How.choices
            ],
            # Stated in the response so the panel cannot describe the rule in
            # words that drift from what the code does.
            "rule": (
                "تا رضایت این شخص ثبت نشود، هیچ فایل تماسی ذخیره نمی‌شود. "
                "رضایت را می‌شود پس گرفت؛ ضبط‌های قبلی می‌مانند ولی ضبط تازه‌ای "
                "انجام نمی‌شود."
            ),
        })

    def post(self, request, store_id, pk):
        prospect = _prospect(request, store_id, pk)
        row = CallConsent.objects.filter(prospect=prospect).first()
        serializer = ConsentSerializer(row, data=request.data, partial=bool(row))
        serializer.is_valid(raise_exception=True)
        consent = serializer.save(prospect=prospect)
        try:
            consent.full_clean(exclude=["prospect"])
        except DjangoValidationError as exc:
            consent.delete() if row is None else None
            return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response(ConsentSerializer(consent).data)

    def delete(self, request, store_id, pk):
        """Revoke. The row stays — it is the record that consent once existed,
        which is what makes the recordings already taken defensible."""
        from django.utils import timezone

        prospect = _prospect(request, store_id, pk)
        row = get_object_or_404(CallConsent, prospect=prospect)
        row.revoked_at = timezone.now()
        row.save(update_fields=["revoked_at", "updated_at"])
        return Response(ConsentSerializer(row).data)


class RecordingListView(APIView):
    """List this prospect's calls, or add one."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, store_id, pk):
        prospect = _prospect(request, store_id, pk)
        rows = Recording.objects.filter(prospect=prospect)
        consent = CallConsent.objects.filter(prospect=prospect).first()
        return Response({
            "recordings": RecordingSerializer(rows, many=True).data,
            "may_record": bool(consent and consent.is_active),
        })

    def post(self, request, store_id, pk):
        prospect = _prospect(request, store_id, pk)
        audio = request.FILES.get("audio")
        if not audio:
            return Response(
                {"audio": ["فایل صدا لازم است."]}, status=status.HTTP_400_BAD_REQUEST,
            )

        recording = Recording(
            store=prospect.store, prospect=prospect, audio=audio,
            seconds=int(request.data.get("seconds", 0) or 0),
        )
        try:
            # `save` calls `clean`, which is the consent gate. A refusal here
            # is the whole point of the endpoint, so it answers 403 rather than
            # a generic 400: nothing about the request was malformed.
            recording.save()
        except DjangoValidationError as exc:
            return Response(
                {"error": "; ".join(exc.messages)}, status=status.HTTP_403_FORBIDDEN,
            )

        from .tasks import analyse_call

        analyse_call.delay(recording.pk)
        return Response(
            RecordingSerializer(recording).data, status=status.HTTP_201_CREATED,
        )


class CallPrepView(APIView):
    """What to have in front of you when the phone rings.

    Assembled from the shop's own rows only. The spec also wanted a live
    listener whispering suggestions mid-call; that needs streaming audio off
    the device and is a different consent conversation, so this is the part
    that is honest to ship: everything a person would want to have read.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        prospect = _prospect(request, store_id, pk)
        calls = list(Recording.objects.filter(prospect=prospect)[:5])

        objections: list[str] = []
        commitments: list[str] = []
        for call in calls:
            for item in call.objections or []:
                if item not in objections:
                    objections.append(item)
            for item in call.commitments or []:
                if item not in commitments:
                    commitments.append(item)

        return Response({
            "prospect": {
                "company": prospect.company,
                "person": prospect.person,
                "role": prospect.role,
                "phone": prospect.phone,
                "stage": prospect.get_stage_display(),
                "notes": prospect.notes,
                "last_outcome": prospect.last_outcome,
                "last_contact_at": prospect.last_contact_at,
                "next_action": prospect.next_action,
            },
            # Their own words from previous calls — what to be ready for.
            "objections": objections[:8],
            "commitments": commitments[:8],
            "last_summary": calls[0].summary if calls else "",
            "call_count": len(calls),
            # Only from this shop's own rows. Looking a stranger's number up on
            # a platform is not built and will not be.
            "known": match_known_contact(prospect.store, prospect.phone),
        })
