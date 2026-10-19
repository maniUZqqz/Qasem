from rest_framework import serializers

from apps.stores.models import Store

from .models import Category, Product, ProductAttribute, ProductImage, ProductVariant
from apps.stores import access


class OwnedStoreField(serializers.PrimaryKeyRelatedField):
    """Store FK restricted to stores owned by the requesting user."""

    def get_queryset(self):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return Store.objects.none()
        return access.stores_for(request.user)


class OwnedCategoryField(serializers.PrimaryKeyRelatedField):
    """Category FK restricted to categories of stores owned by the requesting user."""

    def get_queryset(self):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return Category.objects.none()
        return Category.objects.filter(store__in=access.stores_for(request.user))


class CategorySerializer(serializers.ModelSerializer):
    store = OwnedStoreField()
    # `default=None` is load-bearing: Category has a UniqueConstraint on
    # (store, name, parent), which DRF turns into a UniqueTogetherValidator,
    # and that validator makes every field it covers mandatory unless it has a
    # default. Without this, creating a TOP-LEVEL category (the normal case)
    # was rejected with {"parent": ["This field is required."]}.
    parent = OwnedCategoryField(required=False, allow_null=True, default=None)

    class Meta:
        model = Category
        fields = ["id", "store", "name", "parent"]

    def validate(self, attrs):
        parent = attrs.get("parent")
        store = attrs.get("store") or (self.instance.store if self.instance else None)
        if parent and store and parent.store_id != store.id:
            raise serializers.ValidationError({"parent": "Parent category must belong to the same store."})
        return attrs


class ProductAttributeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductAttribute
        fields = ["id", "key", "value"]


class ProductImageSerializer(serializers.ModelSerializer):
    # A path ("/media/products/images/…"), never an absolute URL. DRF builds
    # the absolute form from the request's Host header, and behind the
    # port-8040 nginx that header arrives without the port
    # (proxy_set_header Host $host), so the list/detail API answered
    # "http://87.107.160.17/media/…" — port 80, where nothing serves /media/
    # (404) — and the panel showed a broken image for every product photo.
    # The panel is served from the same origin as the API, so a path resolves
    # to the right host and port on its own; the upload response
    # (views.images) already returned a path, so the two now agree.
    image = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ["id", "image", "is_main", "alt_text", "order", "created_at"]

    def get_image(self, obj):
        return obj.image.url if obj.image else ""


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = [
            "id", "name", "attributes", "price_override", "stock_quantity",
            "reserved_quantity", "available_quantity", "sku",
        ]
        read_only_fields = ["reserved_quantity", "available_quantity"]


class ProductSerializer(serializers.ModelSerializer):
    store = OwnedStoreField()
    category = OwnedCategoryField(required=False, allow_null=True)
    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    attributes = ProductAttributeSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "store",
            "category",
            "name",
            "slug",
            "sku",
            "description",
            "short_description",
            "brand",
            "price",
            "compare_at_price",
            "cost_price",
            "unit_profit",
            "margin_percent",
            "currency",
            "stock_quantity",
            "reserved_quantity",
            "available_quantity",
            "stock_status",
            "tags",
            "shipping_info",
            "marketing_notes",
            "is_available",
            "images",
            "variants",
            "attributes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "slug", "unit_profit", "margin_percent",
            # Written only by the order lifecycle (apps/customers/stock.py);
            # typing a number here by hand would lose a live reservation.
            "reserved_quantity", "available_quantity",
            "created_at", "updated_at",
        ]

    def validate(self, attrs):
        category = attrs.get("category")
        store = attrs.get("store") or (self.instance.store if self.instance else None)
        if category and store and category.store_id != store.id:
            raise serializers.ValidationError({"category": "Category must belong to the same store."})
        return attrs
