from rest_framework import serializers

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["slug", "created_at", "updated_at"]
