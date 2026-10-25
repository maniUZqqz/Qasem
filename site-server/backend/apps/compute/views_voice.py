"""«سرورهای پردازش › مدل‌های صدا» (staff): switches, «تست», status and «دانلود» per node.

    GET  PATCH  /api/v1/compute/nodes/<pk>/audio/            the card · {speech, clone, sfx, music: bool, idle_min}
    POST        /api/v1/compute/nodes/<pk>/audio/test/       {model} -> a node.bench job (waits while the node is off)
    GET         /api/v1/compute/nodes/<pk>/audio/tests/      history (?model=)
    POST        /api/v1/compute/nodes/<pk>/models/download/  {packages: [...]} -> a node.models job
"""
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import voice_models as vm
from .bench_models import AudioBenchmark
from .models import ComputeNode


def _err(exc):
    return Response({"error": str(exc)}, status=getattr(exc, "status", 400))


@api_view(["GET", "PATCH"])
@permission_classes([permissions.IsAdminUser])
def node_audio(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    if request.method == "PATCH":
        try:
            vm.set_settings(node, request.data if isinstance(request.data, dict) else {})
        except vm.VoiceModelsError as exc:
            return _err(exc)
    return Response(vm.card(node))


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_audio_test(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    try:
        b = vm.start_test(node, str(request.data.get("model") or ""), request.user)
    except vm.VoiceModelsError as exc:
        return _err(exc)
    return Response(vm.test_json(b, node), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def node_audio_tests(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    rows = AudioBenchmark.objects.filter(node=node)
    if request.query_params.get("model"):
        rows = rows.filter(model=request.query_params["model"])
    return Response({"tests": [vm.test_json(vm.sync_test(b), node) for b in rows[:30]]})


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_models_download(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    try:
        job = vm.start_download(node, request.data.get("packages") or [])
    except vm.VoiceModelsError as exc:
        return _err(exc)
    return Response({"job": str(job.uid), "packages": job.payload.get("packages"), **vm.card(node)},
                    status=status.HTTP_202_ACCEPTED)
