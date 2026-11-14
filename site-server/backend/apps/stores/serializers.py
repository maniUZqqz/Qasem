from rest_framework import serializers

from . import access
from .models import Store, StoreProfile


class StoreProfileSerializer(serializers.ModelSerializer):
    """The brand profile, as every member of the store may read it.

    Two fields are credentials and never leave through here, in either
    direction: `novinhub_token` (publishing to the shop's Instagram) and
    `webhook_secret` (anyone holding it can run the sales agent on the shop's
    quota). The connections page reads and writes them — write-only, with a
    has_token flag — for the roles allowed to.

    Three have their own validated endpoints and are read-only here, so a raw
    PATCH cannot store what those endpoints would refuse: `voice_profile` and
    `pronunciations` (/stores/{id}/voice/), `novinhub_account_ids`
    (/stores/{id}/connections/).
    """

    class Meta:
        model = StoreProfile
        exclude = ["id", "store", "novinhub_token", "webhook_secret"]
        read_only_fields = ["voice_profile", "pronunciations", "novinhub_account_ids"]


class StoreSerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(source="products.count", read_only=True)
    # What the CALLER may do here. The panel asks once instead of trying and
    # getting 403s: the sidebar meter used to call /usage/ on every page for
    # roles that cannot see billing. None when serialized without a request.
    my_role = serializers.SerializerMethodField()
    can_view_billing = serializers.SerializerMethodField()
    can_manage_billing = serializers.SerializerMethodField()

    def _user(self):
        request = self.context.get("request")
        return getattr(request, "user", None) if request is not None else None

    def get_my_role(self, obj):
        user = self._user()
        return access.role_of(user, obj) if user is not None else None

    def get_can_view_billing(self, obj):
        user = self._user()
        return access.can(user, obj, access.BILLING, write=False) if user is not None else None

    def get_can_manage_billing(self, obj):
        user = self._user()
        return access.can(user, obj, access.BILLING) if user is not None else None

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "slug",
            "business_type",
            "description",
            "target_audience",
            "contact",
            "logo",
            "colors",
            "social_links",
            "is_active",
            "product_count",
            "my_role",
            "can_view_billing",
            "can_manage_billing",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["slug", "created_at", "updated_at"]
