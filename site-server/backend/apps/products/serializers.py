from decimal import Decimal

from rest_framework import serializers
from rest_framework.fields import empty

from apps.common.numbers import fa_money, normalize_number_text
from apps.stores.models import Store

from .models import Category, Product, ProductAttribute, ProductImage, ProductVariant
from apps.stores import access


class MoneyField(serializers.DecimalField):
    """A price in tomans, the way an Iranian shop owner types it.

    - «۳۰۰٬۰۰۰», «٣٠٠٬٠٠٠», «300,000» and «300000» are the same number.
    - Never negative: the API used to store a price of -5000 and a margin
      computed from it.
    - An error says what is wrong *with this field*, in Persian — the stock
      English «A valid number is required.» sat under a field called `price`.
    - `allow_null=True` fields also treat an emptied box ("") as «not set».
    """

    def __init__(self, label_fa: str = "قیمت", **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("min_value", Decimal("0"))
        kwargs["error_messages"] = {
            "invalid": f"{label_fa} باید عدد باشد؛ مثلاً ۳۰۰۰۰۰ (ارقام فارسی و جداکننده هم اشکال ندارد).",
            "min_value": f"{label_fa} نمی‌تواند منفی باشد.",
            "max_digits": f"{label_fa} خیلی بزرگ است؛ حداکثر ۱۲ رقم صحیح.",
            "max_whole_digits": f"{label_fa} خیلی بزرگ است؛ حداکثر ۱۲ رقم صحیح.",
            "max_decimal_places": f"{label_fa} حداکثر دو رقم اعشار دارد.",
            "max_string_length": "عدد خیلی طولانی است.",
            "null": f"{label_fa} را خالی نفرستید؛ یا عدد بدهید یا فیلد را حذف کنید.",
            **kwargs.get("error_messages", {}),
        }
        super().__init__(**kwargs)

    def run_validation(self, data=empty):
        if isinstance(data, str) and not data.strip() and self.allow_null:
            data = None
        return super().run_validation(data)

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = normalize_number_text(data)
        return super().to_internal_value(data)


class CountField(serializers.IntegerField):
    """A whole number of items (stock), typed in any digits, never negative."""

    def __init__(self, label_fa: str = "موجودی", **kwargs):
        kwargs.setdefault("min_value", 0)
        kwargs.setdefault("max_value", 2_000_000_000)
        kwargs["error_messages"] = {
            "invalid": f"{label_fa} باید عدد صحیح باشد؛ مثلاً ۱۲ (ارقام فارسی هم اشکال ندارد).",
            "min_value": f"{label_fa} نمی‌تواند منفی باشد.",
            "max_value": f"{label_fa} خیلی بزرگ است.",
            "max_string_length": "عدد خیلی طولانی است.",
            **kwargs.get("error_messages", {}),
        }
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = normalize_number_text(data)
        return super().to_internal_value(data)


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
    price_override = MoneyField(
        label_fa="قیمتِ این گونه", required=False, allow_null=True,
    )
    stock_quantity = CountField(label_fa="موجودیِ این گونه", required=False)

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
    # A service with no stock count (stored as 9999 = "unlimited"): the panel shows
    # «سرویس دیجیتال», not «۹۹۹۹ قابل فروش» (apps.products.digital).
    is_digital = serializers.SerializerMethodField()
    # Money and counts accept what a Persian keyboard produces (۳۰۰٬۰۰۰) and
    # refuse what makes no sense (a negative price, a compare-at price below
    # the selling price) with a sentence about *that field*.
    price = MoneyField(label_fa="قیمت", required=False)
    compare_at_price = MoneyField(
        label_fa="قیمت قبل از تخفیف", required=False, allow_null=True,
    )
    cost_price = MoneyField(label_fa="قیمت تمام‌شده", required=False, allow_null=True)
    stock_quantity = CountField(label_fa="موجودی", required=False)

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
            "is_digital",
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

    def get_is_digital(self, obj):
        from .digital import is_digital, store_is_digital

        # one policy lookup per store per request, not per product
        cache = self.context.setdefault("_store_digital", {})
        if obj.store_id not in cache:
            cache[obj.store_id] = store_is_digital(obj.store)
        return is_digital(obj, cache[obj.store_id])

    def validate(self, attrs):
        category = attrs.get("category")
        store = attrs.get("store") or (self.instance.store if self.instance else None)
        if category and store and category.store_id != store.id:
            raise serializers.ValidationError({"category": "Category must belong to the same store."})

        # «قیمت قبل از تخفیف» is the crossed-out price: it only means something
        # when it is *higher* than what the product sells for. Checked whenever
        # either side is being CHANGED, against the stored value of the other —
        # a form that re-sends an unchanged price must not start failing on a
        # product whose old data already disagreed.
        def changed(name):
            if name not in attrs:
                return False
            return self.instance is None or attrs[name] != getattr(self.instance, name)

        if changed("compare_at_price") or changed("price"):
            price = attrs.get("price", self.instance.price if self.instance else Decimal("0"))
            compare = attrs.get(
                "compare_at_price", self.instance.compare_at_price if self.instance else None,
            )
            if compare and compare <= price:
                if changed("compare_at_price"):
                    raise serializers.ValidationError({
                        "compare_at_price": (
                            f"قیمت قبل از تخفیف باید از قیمت فروش ({fa_money(price)} تومان) "
                            "بیشتر باشد؛ وگرنه تخفیفی در کار نیست. بیشترش کنید یا خالی بگذارید."
                        )
                    })
                raise serializers.ValidationError({
                    "price": (
                        f"قیمت فروش از «قیمت قبل از تخفیف» ({fa_money(compare)} تومان) "
                        "بالاتر یا برابر شد؛ اول آن را اصلاح یا پاک کنید."
                    )
                })
        return attrs
