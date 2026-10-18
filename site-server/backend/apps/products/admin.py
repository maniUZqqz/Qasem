from django.contrib import admin

from .models import Category, Product, ProductAttribute, ProductImage, ProductVariant


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


class ProductAttributeInline(admin.TabularInline):
    model = ProductAttribute
    extra = 0


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    name_en = "Products"
    description = (
        "محصولات فروشگاه‌ها. همه‌ی تولید محتوا از روی یک ردیف همین جدول شروع می‌شود."
    )
    list_display = ["name", "store", "price", "stock_status", "is_available", "created_at"]
    list_filter = ["stock_status", "is_available"]
    search_fields = ["name", "store__name", "sku"]
    inlines = [ProductImageInline, ProductAttributeInline, ProductVariantInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    name_en = "Product categories"
    description = (
        "دسته‌بندی محصولات، به تفکیک هر فروشگاه."
    )
    list_display = ["name", "store", "parent"]
