"""API ِ «چندزاویه» (پنل › فروشگاه › محتوا).

    GET  stores/<id>/multiangle/                     اجراها + منبع‌ها + انتخاب‌ها + وضعیتِ سرورِ پردازش
    GET  stores/<id>/multiangle/status/              فقط وضعیتِ سرورِ پردازش (برای پرس‌وجوی دوره‌ای)
    POST stores/<id>/multiangle/prepare/             نصبِ محیط و مدل‌ها روی سرورِ پردازش (خودکار هم انجام می‌شود)
    POST stores/<id>/multiangle/runs/                {mode: "virtual"|"move25d", source: "video:12", ...انتخاب‌ها}
    GET  stores/<id>/multiangle/runs/<pk>/           یک اجرا (وضعیتِ کارِ گره را تازه می‌کند؛ کارِ تمام‌شده را به رسانه می‌آورد)
    DELETE stores/<id>/multiangle/runs/<pk>/         حذفِ اجرا و فایل‌هایش
    POST stores/<id>/multiangle/runs/<pk>/<cancel|editor>/
    POST stores/<id>/multiangle/real/                {sources: ["video:1","video:2"], pace}   چند دوربینِ واقعی؛ هم‌گام با صدا + برشِ خودکار
    POST stores/<id>/multiangle/selftest/            (کارکنان) آزمونِ خودکارِ همهٔ سرورها
"""
from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import services
from .models import MultiAngleRun

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "multiangle", http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        for run in MultiAngleRun.objects.filter(store=store).order_by("-created_at")[:30]:
            if run.active:
                try:
                    services.refresh(run)
                except Exception:  # noqa: BLE001 — one bad run must not blank the page
                    logger.exception("multiangle refresh failed for run %s", run.pk)
        runs = MultiAngleRun.objects.filter(store=store).order_by("-created_at")[:30]
        return Response({"runs": [services.run_dict(r, detail=False) for r in runs], "sources": services.list_sources(store), "presets": services.presets(),
                         "status": services.status()})


class StatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(services.status())


class PrepareView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT)
        notes = {}
        for node in services.multiangle_nodes():
            notes[node.name] = services.prepare_node(node)
        return Response({"nodes": notes, "status": services.status()})


class RunListView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        mode = str(request.data.get("mode") or "virtual")
        try:
            if mode == "virtual":
                run = services.create_virtual(store, request.user, request.data)
            elif mode == "move25d":
                run = services.create_move(store, request.user, request.data)
            else:
                return _err("نوعِ کار نامعتبر است.")
        except services.MultiAngleError as exc:
            return _err(str(exc), exc.code, exc.status)
        return Response({"run": services.run_dict(run)}, status=status.HTTP_201_CREATED)


class RunView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        run = get_object_or_404(MultiAngleRun, pk=pk, store=store)
        if run.active:
            services.refresh(run)
            run.refresh_from_db()
        return Response({"run": services.run_dict(run)})

    def delete(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        run = get_object_or_404(MultiAngleRun, pk=pk, store=store)
        services.delete_run(run)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RunActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk, action):
        store = access.get_store(request.user, store_id, access.CONTENT)
        run = get_object_or_404(MultiAngleRun, pk=pk, store=store)
        if action == "cancel":
            services.cancel(run)
            return Response({"run": services.run_dict(run)})
        if action == "editor":
            try:
                project = services.build_project(run, request.user)
            except services.MultiAngleError as exc:
                return _err(str(exc), exc.code, exc.status)
            return Response({"project_id": project.pk, "run": services.run_dict(run)})
        return _err("کارِ نامعتبر.", http=status.HTTP_404_NOT_FOUND)


class RealCamerasView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        refs = request.data.get("sources")
        if not isinstance(refs, list):
            return _err("فهرستِ فیلم‌ها را بفرستید.")
        try:
            result = services.real_cameras(store, request.user, [str(r) for r in refs], str(request.data.get("pace") or "medium"))
        except services.MultiAngleError as exc:
            return _err(str(exc), exc.code, exc.status)
        return Response(result, status=status.HTTP_201_CREATED)


class SelfTestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        if not request.user.is_staff:
            return _err("فقط کارکنان.", "forbidden", status.HTTP_403_FORBIDDEN)
        runs = [services.request_selftest(n, request.user).pk for n in services.multiangle_nodes() if n.online]
        return Response({"runs": runs, "status": services.status()}, status=status.HTTP_201_CREATED)
