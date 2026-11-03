# -*- coding: utf-8 -*-
"""«اولویتِ هوش مصنوعی: لوکال / متیس» — API ِ پنل (ادمین ⇐ موتورهای AI). فقط کارمندان.

GET  /api/v1/ai/priority/         تنظیم + وضعِ زندهٔ هر مسیر + آخرین پاسخ‌ها (بی‌فراخوانیِ شبکه)
PATCH|POST /api/v1/ai/priority/   ذخیرهٔ تنظیم: priority، priority_text/research/code/vision، model_text/research/code/vision، breaker_minutes
POST /api/v1/ai/priority/test/    {provider: "local"|"metis", kind?: "text"|"research"|"code"|"vision"} — «آزمون» ِ یک درخواستِ کوچک
POST /api/v1/ai/priority/reset/   مدارِ باز (مسیرهای کنارگذاشته) را می‌بندد
POST /api/v1/ai/models/pull/      {tag, node?} «دانلود مدل» (کارِ ollama.pull؛ فقط فهرستِ مجاز) ⇒ وضعِ زنده + pull
POST /api/v1/ai/models/pull/cancel/  {uid} لغوِ دانلود
"""
from rest_framework import status as http
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from services.ai import priority, status


class AIPriorityView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(status.snapshot())

    def post(self, request):
        try:
            status.update(request.data)
        except status.UpdateError as exc:
            return Response({"error": str(exc), "errors": exc.errors}, status=http.HTTP_400_BAD_REQUEST)
        data = status.snapshot()
        data["message"] = "اولویتِ هوش مصنوعی ذخیره شد."
        return Response(data)

    patch = post


class AIPriorityTestView(APIView):
    """یک درخواستِ کوچکِ واقعی. فقط وقتی مالک دکمه را می‌زند؛ هیچ زمان‌بندی‌ای این را صدا نمی‌زند."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        provider = request.data.get("provider")
        if provider not in priority.PROVIDERS:
            return Response({"error": "provider باید local یا metis باشد."}, status=http.HTTP_400_BAD_REQUEST)
        result = status.run_test(provider, request.data.get("kind") or priority.TEXT)
        result["status"] = status.snapshot()
        return Response(result)


class AIModelPullView(APIView):
    """«دانلود مدل»: کارِ `ollama.pull` را در صفِ سرورِ پردازش می‌گذارد. فقط برچسب‌های فهرستِ مجازِ سایت.

    POST {tag, node?} ⇒ وضعِ زنده + {pull: <کارِ دانلود>}. گرهٔ خاموش هم می‌شود (در صف می‌ماند). عاملِ قدیمی ⇒ ۴۰۹ با پیامِ
    «Update.bat».
    """

    permission_classes = [IsAdminUser]

    def post(self, request):
        from services.ai import model_pull

        try:
            job = model_pull.start_pull(str(request.data.get("tag") or ""), str(request.data.get("node") or ""))
        except model_pull.PullError as exc:
            return Response({"error": str(exc)}, status=exc.status)
        data = status.snapshot()
        data["pull"] = model_pull.job_view(job)
        data["message"] = data["pull"]["text"]
        return Response(data)


class AIModelPullCancelView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        from services.ai import model_pull

        try:
            job = model_pull.cancel_pull(str(request.data.get("uid") or ""))
        except (model_pull.PullError, ValueError) as exc:
            return Response({"error": str(exc)}, status=getattr(exc, "status", 400))
        data = status.snapshot()
        data["pull"] = model_pull.job_view(job)
        data["message"] = "دانلود لغو شد؛ هر چه تا حالا گرفته شده بماند، دفعهٔ بعد از همان‌جا ادامه می‌دهد."
        return Response(data)


class AIPriorityResetView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        provider = request.data.get("provider")
        count = priority.reset(provider if provider in priority.PROVIDERS else None)
        data = status.snapshot()
        data["message"] = "مسیرهای کنارگذاشته دوباره آزاد شدند." if count else "مسیری کنار گذاشته نشده بود."
        return Response(data)
