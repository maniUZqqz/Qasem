"""Rewrite one caption by hand.

The AI writes drafts; now and then a draft has a broken price («۶۰۰٬۰۰ نتومان»),
a sentence cut in half, or an instruction to the image model printed as copy.
The panel flags these (caption_guard) but until now the only way to fix one was
to generate a whole new set. This is the missing «ویرایش».

Nothing here calls a model and nothing is published.
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from . import hashtags as hashtag_tools
from .models import Caption
from .serializers import CaptionSerializer
from .views import _owned_product

TEXT_MAX = 8000
CTA_MAX = 300  # the model column
TAGS_MAX = 40


def _error(code: str, message: str) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status.HTTP_400_BAD_REQUEST)


class CaptionDetailView(APIView):
    """PATCH products/<id>/captions/<id>/ with any of short_text, medium_text,
    long_text, cta, hashtags (a list, or text like «#چغر #برنامه_ورزشی»)."""

    def patch(self, request, pk, caption_id):
        product = _owned_product(request, pk)
        caption = get_object_or_404(Caption, pk=caption_id, product=product)

        changed = []
        for field in ("short_text", "medium_text", "long_text"):
            if field in request.data:
                value = str(request.data.get(field) or "").strip()
                if len(value) > TEXT_MAX:
                    return _error("too_long", f"متن بیش از {TEXT_MAX} نویسه نمی‌شود.")
                setattr(caption, field, value)
                changed.append(field)
        if "cta" in request.data:
            value = str(request.data.get("cta") or "").strip()
            if len(value) > CTA_MAX:
                return _error("cta_too_long", f"دعوت به اقدام بیش از {CTA_MAX} نویسه نمی‌شود.")
            caption.cta = value
            changed.append("cta")
        if "hashtags" in request.data:
            tags = []
            for tag in hashtag_tools.repair_all(request.data.get("hashtags")):
                word = hashtag_tools.clean(tag)
                if word and word not in tags:
                    tags.append(word)
            if len(tags) > TAGS_MAX:
                return _error("too_many_tags", f"بیش از {TAGS_MAX} هشتگ نمی‌شود.")
            caption.hashtags = tags
            changed.append("hashtags")

        if not changed:
            return _error("nothing_to_change", "چیزی برای تغییر فرستاده نشد.")
        if not (caption.short_text or caption.medium_text or caption.long_text):
            return _error("empty_caption", "کپشن نباید یکسره خالی بماند.")

        caption.save(update_fields=changed + ["updated_at"])
        return Response(CaptionSerializer(caption, context={"request": request}).data)
