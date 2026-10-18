"""Adding a colleague to a store, and taking the access away again.

Kept deliberately small. There is no email invitation flow: Iranian shops run
on people who already know each other, and a half-finished invite system would
mean tokens in inboxes with no way to revoke them. The owner adds an existing
account by username or email, which is a real workflow they can complete today.
"""
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access, agent_settings, onboarding
from .agent_settings import SalesAgentSettings
from .models import Membership


class MembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "username", "email", "role", "role_label", "is_active", "created_at"]


def _people(store) -> list[dict]:
    """Everyone with access, owner first.

    The owner has no Membership row, so they are added here rather than left
    off a list whose whole purpose is "who can get into my shop".
    """
    rows = [{
        "id": None,
        "username": store.owner.username,
        "email": store.owner.email,
        "role": Membership.Role.OWNER,
        "role_label": "مالک",
        "is_active": True,
        "is_owner": True,
    }]
    for row in store.memberships.filter(is_active=True).select_related("user"):
        data = MembershipSerializer(row).data
        data["is_owner"] = False
        rows.append(data)
    return rows


class StoreMembersView(APIView):
    """List the people in a store, or add one."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        store = access.get_store(request.user, pk, access.MEMBERS, write=False)
        return Response({
            "members": _people(store),
            "roles": [{"value": v, "label": l} for v, l in Membership.Role.choices],
            "your_role": access.role_of(request.user, store),
        })

    def post(self, request, pk):
        store = access.get_store(request.user, pk, access.MEMBERS)

        identifier = str(request.data.get("user", "")).strip()
        role = request.data.get("role", Membership.Role.VIEWER)

        if not identifier:
            return Response(
                {"error": {"code": "user_required", "message": "نام کاربری یا ایمیل لازم است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if role not in Membership.Role.values:
            return Response(
                {"error": {"code": "bad_role", "message": "نقش نامعتبر است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        person = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).first()
        if person is None:
            # Deliberately explicit. A vague "could not add" would have the
            # owner retrying a typo forever.
            return Response(
                {"error": {
                    "code": "no_such_user",
                    "message": "کاربری با این نام یا ایمیل ثبت‌نام نکرده است. "
                               "اول از او بخواهید حساب بسازد.",
                }},
                status=status.HTTP_404_NOT_FOUND,
            )
        if person.pk == store.owner_id:
            return Response(
                {"error": {"code": "already_owner", "message": "این شخص مالک فروشگاه است."}},
                status=status.HTTP_409_CONFLICT,
            )

        row, created = Membership.objects.update_or_create(
            store=store, user=person,
            defaults={
                "role": role,
                "is_active": True,
                "removed_at": None,
                "invited_by": request.user,
            },
        )
        data = MembershipSerializer(row).data
        data["is_owner"] = False
        return Response(
            {"member": data, "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class StoreMemberView(APIView):
    """Change one person's role, or remove their access."""

    permission_classes = [IsAuthenticated]

    def _row(self, request, pk, member_id):
        store = access.get_store(request.user, pk, access.MEMBERS)
        row = store.memberships.filter(pk=member_id).select_related("user").first()
        if row is None:
            from django.http import Http404

            raise Http404("این عضو در فروشگاه نیست.")
        return store, row

    def patch(self, request, pk, member_id):
        _store, row = self._row(request, pk, member_id)
        role = request.data.get("role")
        if role not in Membership.Role.values:
            return Response(
                {"error": {"code": "bad_role", "message": "نقش نامعتبر است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row.role = role
        row.save(update_fields=["role", "updated_at"])
        return Response(MembershipSerializer(row).data)

    def delete(self, request, pk, member_id):
        _store, row = self._row(request, pk, member_id)
        # Deactivated, not deleted: "who removed me, and when?" has to have an
        # answer, and re-adding someone should restore rather than duplicate.
        row.is_active = False
        row.removed_at = timezone.now()
        row.save(update_fields=["is_active", "removed_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class SalesAgentSettingsSerializer(serializers.ModelSerializer):
    tone_label = serializers.CharField(source="get_tone_display", read_only=True)
    #: What the model is actually told, so the owner can see the effect of the
    #: dropdown rather than trust it.
    tone_instruction = serializers.CharField(read_only=True)

    class Meta:
        model = SalesAgentSettings
        fields = [
            "tone", "tone_label", "tone_instruction", "custom_tone",
            "always_say", "never_say", "sale_terms", "limits",
            "can_offer_discount", "discount_policy", "escalate_on_complaint",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        tone = attrs.get("tone", getattr(self.instance, "tone", None))
        custom = attrs.get("custom_tone", getattr(self.instance, "custom_tone", ""))
        if tone == SalesAgentSettings.Tone.CUSTOM and not (custom or "").strip():
            raise serializers.ValidationError({
                "custom_tone": "لحن سفارشی را انتخاب کرده‌ای ولی توضیحی ننوشته‌ای.",
            })
        return attrs


class StoreAgentSettingsView(APIView):
    """Read or change how the sales agent talks for this store."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        store = access.get_store(request.user, pk, access.SETTINGS, write=False)
        row = agent_settings.settings_for(store)
        return Response({
            "settings": SalesAgentSettingsSerializer(row).data,
            "tones": [{"value": v, "label": l} for v, l in SalesAgentSettings.Tone.choices],
            # Stated in the response, not only in the docs: an owner about to
            # write "always say the payment went through" should see why it
            # will not happen before they type it.
            "unbreakable": [
                "قیمت و موجودی همیشه از دیتابیس خوانده می‌شود، نه از این تنظیمات.",
                "تأیید دریافت پرداخت همیشه با یک آدم است — ایجنت هرگز تأیید نمی‌کند.",
                "ایجنت چیزی را که در داده‌ها نیست قول نمی‌دهد.",
            ],
        })

    def patch(self, request, pk):
        store = access.get_store(request.user, pk, access.SETTINGS)
        row = agent_settings.settings_for(store)
        serializer = SalesAgentSettingsSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class StoreOnboardingView(APIView):
    """What this store still needs, answered from its own rows."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        # Any member may see the checklist: a content manager who cannot tell
        # that the brand voice is still empty will keep generating copy the
        # owner throws away.
        store = access.get_store(request.user, pk)
        return Response(onboarding.summary(store))
