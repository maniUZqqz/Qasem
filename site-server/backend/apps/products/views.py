from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Category, Product
from .serializers import (
    CategorySerializer,
    ProductAttributeSerializer,
    ProductImageSerializer,
    ProductSerializer,
    ProductVariantSerializer,
)
from apps.stores import access


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer

    def get_queryset(self):
        qs = Category.objects.filter(store__in=access.stores_for(self.request.user))
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = (
            Product.objects.filter(store__in=access.stores_for(self.request.user))
            .select_related("store", "category")
            .prefetch_related("images", "variants", "attributes")
        )
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def images(self, request, pk=None):
        from django.conf import settings

        product = self.get_object()
        upload = request.FILES.get("image")
        if upload is None:
            return Response(
                {"error": {"code": "missing_file", "message": "Field 'image' (file) is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            return Response(
                {
                    "error": {
                        "code": "file_too_large",
                        "message": f"حداکثر حجم مجاز {settings.MAX_UPLOAD_MB} مگابایت است.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
        if (upload.content_type or "") not in allowed_types:
            return Response(
                {
                    "error": {
                        "code": "invalid_type",
                        "message": "فقط تصویر JPEG/PNG/WebP/GIF مجاز است.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # verify the actual bytes are an image (content-type header is untrusted)
        from PIL import Image as PILImage

        try:
            PILImage.open(upload).verify()
            upload.seek(0)
        except Exception:
            return Response(
                {"error": {"code": "invalid_type", "message": "فایل تصویر معتبر نیست."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        image = product.images.create(
            image=upload,
            is_main=str(request.data.get("is_main", "")).lower() in {"1", "true", "yes"},
            alt_text=request.data.get("alt_text", ""),
        )
        return Response(ProductImageSerializer(image).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"images/(?P<image_id>\d+)")
    def delete_image(self, request, pk=None, image_id=None):
        product = self.get_object()
        image = get_object_or_404(product.images, pk=image_id)
        image.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def variants(self, request, pk=None):
        product = self.get_object()
        serializer = ProductVariantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(product=product)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="attributes")
    def add_attribute(self, request, pk=None):
        product = self.get_object()
        serializer = ProductAttributeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(product=product)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
