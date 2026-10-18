from rest_framework import serializers

from apps.content.models import Caption, GeneratedImage, VideoScript
from apps.content.serializers import CaptionSerializer, GeneratedImageSerializer
from apps.products.models import Product

from .models import Campaign, PublishJob
from apps.stores import access


class OwnedProductField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return Product.objects.none()
        return Product.objects.filter(store__in=access.stores_for(request.user))


class _OwnedStoreScopedField(serializers.PrimaryKeyRelatedField):
    """PK field limited to objects of stores the requesting user owns."""

    model = None

    def get_queryset(self):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return self.model.objects.none()
        return self.model.objects.filter(store__in=access.stores_for(request.user))


class OwnedGeneratedImageField(_OwnedStoreScopedField):
    model = GeneratedImage


class OwnedCaptionField(_OwnedStoreScopedField):
    model = Caption


class OwnedVideoScriptField(_OwnedStoreScopedField):
    model = VideoScript


class PublishJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = PublishJob
        fields = [
            "id",
            "platform",
            "status",
            "attempts",
            "last_error",
            "published_at",
            "created_at",
        ]


class VideoScriptBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoScript
        fields = ["id", "status", "total_duration", "final_video", "final_video_voiced"]


class CampaignSerializer(serializers.ModelSerializer):
    product = OwnedProductField()
    poster = OwnedGeneratedImageField(required=False, allow_null=True)
    product_image = OwnedGeneratedImageField(required=False, allow_null=True)
    caption = OwnedCaptionField(required=False, allow_null=True)
    video_script = OwnedVideoScriptField(required=False, allow_null=True)
    poster_detail = GeneratedImageSerializer(source="poster", read_only=True)
    product_image_detail = GeneratedImageSerializer(source="product_image", read_only=True)
    caption_detail = CaptionSerializer(source="caption", read_only=True)
    video_script_detail = VideoScriptBriefSerializer(source="video_script", read_only=True)
    publish_jobs = PublishJobSerializer(many=True, read_only=True)

    class Meta:
        model = Campaign
        fields = [
            "id",
            "product",
            "name",
            "goal",
            "audience",
            "notes",
            "poster",
            "product_image",
            "caption",
            "video_script",
            "poster_detail",
            "product_image_detail",
            "caption_detail",
            "video_script_detail",
            "approval_state",
            "publish_jobs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["approval_state", "created_at", "updated_at"]

    def validate(self, attrs):
        product = attrs.get("product") or (self.instance.product if self.instance else None)
        if product is None:
            return attrs
        for field in ["poster", "product_image", "caption", "video_script"]:
            linked = attrs.get(field)
            if linked is not None and linked.product_id != product.id:
                raise serializers.ValidationError(
                    {field: "این آیتم متعلق به همین محصول نیست."}
                )
        return attrs
