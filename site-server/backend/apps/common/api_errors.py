"""One place where an API error is turned into words a person can read.

Django's `get_object_or_404` and DRF's `NotFound` answer in English
(«No AudioAsset matches the given query.») and that sentence reached the
owner's screen when a retry button pointed at a take that no longer existed.
Only the stock English 404 texts are replaced: a view that raised
`Http404("فایلِ این صدا آماده نیست.")` keeps its own words.
"""
from __future__ import annotations

import re

from rest_framework.views import exception_handler as drf_exception_handler

NOT_FOUND_FA = "موردِ خواسته‌شده پیدا نشد؛ شاید پاک شده یا مالِ این فروشگاه نیست."

_STOCK_404 = re.compile(r"^(?:Not found\.?|No .+ matches the given query\.?|Page not found.*)$", re.I)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None and response.status_code == 404 and isinstance(response.data, dict):
        detail = response.data.get("detail")
        if detail is not None and _STOCK_404.match(str(detail).strip()):
            response.data = {
                "detail": NOT_FOUND_FA,
                "error": {"code": "not_found", "message": NOT_FOUND_FA},
            }
    return response
