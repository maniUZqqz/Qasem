"""Serializers of the leads module.

Output serializers only read what the view has already prefetched (see
``services.queries.with_list_prefetch``) so a page of leads costs a fixed number of queries.
Input serializers check types only; normalisation and business rules live in ``services``.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.sources import provenance

from .choices import ActivityKind, BusinessType, ContactKind, LeadOrigin, LeadStatus
from .models import BusinessProfile, ContactPoint, Lead, LeadActivity, LeadNote, LeadTag
from .services import scoring


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadTag
        fields = ["id", "name", "color"]


class ContactSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    source = serializers.SerializerMethodField()

    class Meta:
        model = ContactPoint
        fields = [
            "id", "kind", "kind_label", "value", "label", "is_primary", "source_ref", "source", "source_url",
            "evidence", "confidence", "created_at",
        ]

    def get_source(self, obj):
        return provenance.parse_ref(obj.source_ref)


def _primary(contacts, kind: str) -> str:
    return next((c.value for c in contacts if c.kind == kind), "")


class LeadListSerializer(serializers.ModelSerializer):
    """One row of the lead table."""

    display_name = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    origin_label = serializers.CharField(source="get_origin_display", read_only=True)
    country_name = serializers.SerializerMethodField()
    tags = TagSerializer(many=True, read_only=True)
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    do_not_contact = serializers.SerializerMethodField()
    reach = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            "id", "display_name", "business_name", "website", "instagram_url", "category", "city", "country",
            "country_name", "status", "status_label", "origin", "origin_label", "is_archived", "tags", "phone",
            "email", "created_at", "updated_at", "do_not_contact", "reach",
        ]

    def get_reach(self, obj):
        """The rule-based reachability score with its reasons (see ``services/scoring``)."""
        return scoring.score(obj, self._all_contacts(obj), suppressed=obj.pk in self.context.get("suppressed_ids", ()))

    def _all_contacts(self, obj):
        cached = getattr(obj, "list_contacts", None)
        return cached if cached is not None else list(obj.contacts.all())

    def get_do_not_contact(self, obj):
        """True when the compliance module's list blocks this lead. The view passes the page's ids in the context."""
        return obj.pk in self.context.get("suppressed_ids", ())

    def get_country_name(self, obj):
        return nz.country_name_fa(obj.country) if obj.country else ""

    def _contacts(self, obj):
        cached = getattr(obj, "list_contacts", None)
        return cached if cached is not None else list(obj.contacts.filter(kind__in=[ContactKind.PHONE, ContactKind.EMAIL]))

    def get_phone(self, obj):
        return _primary(self._contacts(obj), ContactKind.PHONE)

    def get_email(self, obj):
        return _primary(self._contacts(obj), ContactKind.EMAIL)


class ProfileSerializer(serializers.ModelSerializer):
    business_type_label = serializers.CharField(source="get_business_type_display", read_only=True)

    class Meta:
        model = BusinessProfile
        fields = ["language", "business_type", "business_type_label", "product_categories", "product_names", "address", "provenance"]


class SourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    provider = serializers.CharField()
    provider_label = serializers.CharField(source="get_provider_display")
    source_ref = serializers.CharField()
    source = serializers.SerializerMethodField()
    source_url = serializers.CharField()
    discovered_at = serializers.DateTimeField()
    job_id = serializers.IntegerField(allow_null=True)
    created_by = serializers.SerializerMethodField()

    def get_source(self, obj):
        return provenance.parse_ref(obj.source_ref)

    def get_created_by(self, obj):
        return obj.created_by.username if obj.created_by_id else ""


class LeadDetailSerializer(LeadListSerializer):
    profile = serializers.SerializerMethodField()
    contacts = ContactSerializer(many=True, read_only=True)
    sources = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    notes_count = serializers.SerializerMethodField()

    class Meta(LeadListSerializer.Meta):
        fields = LeadListSerializer.Meta.fields + [
            "description", "provenance", "profile", "contacts", "sources", "created_by_name", "notes_count",
        ]

    def get_profile(self, obj):
        try:
            profile = obj.profile
        except BusinessProfile.DoesNotExist:
            return {
                "language": "", "business_type": BusinessType.UNKNOWN.value,
                "business_type_label": BusinessType.UNKNOWN.label, "product_categories": [], "product_names": [],
                "address": "", "provenance": {},
            }
        return ProfileSerializer(profile).data

    def get_sources(self, obj):
        return SourceSerializer(list(obj.sources.all()), many=True).data

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by_id else ""

    def get_notes_count(self, obj):
        return obj.notes.count()

    def _contacts(self, obj):
        return list(obj.contacts.all())


class NoteSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = LeadNote
        fields = ["id", "body", "author", "author_name", "created_at", "updated_at"]

    def get_author_name(self, obj):
        return obj.author.username if obj.author_id else ""


class ActivitySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    actor_name = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    class Meta:
        model = LeadActivity
        fields = ["id", "kind", "kind_label", "actor", "actor_name", "summary", "data", "source_ref", "source", "created_at"]

    def get_actor_name(self, obj):
        return obj.actor.username if obj.actor_id else ""

    def get_source(self, obj):
        return provenance.parse_ref(obj.source_ref) if obj.source_ref else None


# --------------------------------------------------------------------------- input


class ProfileInputSerializer(serializers.Serializer):
    language = serializers.CharField(required=False, allow_blank=True, max_length=8)
    business_type = serializers.CharField(required=False, allow_blank=True, max_length=24)
    address = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    product_categories = serializers.ListField(child=serializers.CharField(allow_blank=True), required=False)
    product_names = serializers.ListField(child=serializers.CharField(allow_blank=True), required=False)


class LeadUpdateSerializer(serializers.Serializer):
    business_name = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    website = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    instagram_url = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    category = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    description = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100)
    city = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    status = serializers.ChoiceField(required=False, choices=LeadStatus.choices)
    is_archived = serializers.BooleanField(required=False)
    tags = serializers.ListField(child=serializers.CharField(allow_blank=True, max_length=200), required=False, max_length=100)
    profile = ProfileInputSerializer(required=False)


class ContactInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ContactKind.choices)
    value = serializers.CharField(max_length=2000)
    label = serializers.CharField(required=False, allow_blank=True, max_length=200)


class ContactUpdateSerializer(serializers.Serializer):
    value = serializers.CharField(required=False, max_length=2000)
    label = serializers.CharField(required=False, allow_blank=True, max_length=200)
    is_primary = serializers.BooleanField(required=False)


class NoteInputSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000, allow_blank=True)


class BulkInputSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True, max_length=5000)
    action = serializers.CharField(max_length=30)
    status = serializers.CharField(required=False, allow_blank=True, max_length=24)
    tag = serializers.CharField(required=False, allow_blank=True, max_length=200)
    confirm = serializers.BooleanField(required=False)


def choices_payload() -> dict:
    """Vocabulary for the front end - one source of truth (the Python choices)."""
    return {
        "statuses": [{"value": v, "label": label} for v, label in LeadStatus.choices],
        "origins": [{"value": v, "label": label} for v, label in LeadOrigin.choices],
        "contact_kinds": [{"value": v, "label": label} for v, label in ContactKind.choices],
        "business_types": [{"value": v, "label": label} for v, label in BusinessType.choices],
        "activity_kinds": [{"value": v, "label": label} for v, label in ActivityKind.choices],
        "countries": [{"code": c, "name": names[0]} for c, names in nz.COUNTRIES.items()],
    }
