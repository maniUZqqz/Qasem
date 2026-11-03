# -*- coding: utf-8 -*-
"""Ollama روی سرورِ پردازش: فهرستِ مجازِ دانلودِ مدل (۱۴۰۵/۰۸/۱۲).

    GET /api/v1/compute/ollama/pullable/    (Authorization: Node <token>) ⇒ {"tags": {"gemma3:12b": {"size_mb": 8164}, ...}}

عاملِ گره پیش از هر `ollama.pull` همین فهرست را از سایت می‌پرسد و هر برچسبِ بیرون از آن را نمی‌کشد (حتی اگر کاری با آن برچسب
به او برسد) — پس «گره هیچ‌وقت ورودیِ دلخواه را دانلود نمی‌کند». فهرست در `services/ai/model_catalog.py` است.
"""
from rest_framework.response import Response

from .api import _node, node_api


@node_api("GET")
def pullable(request):
    _node(request)
    from services.ai import model_catalog

    return Response({"tags": {tag: {"size_mb": int(row.get("size_mb") or 0)} for tag, row in model_catalog.pullable().items()}})
