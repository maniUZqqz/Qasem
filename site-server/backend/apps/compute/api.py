"""پروتکلِ گره‌های پردازش (همه با سرآیندِ Authorization: Node <token>) + API ِ کارکنان.

  POST /api/v1/compute/heartbeat/                اعلامِ حضور و توانایی‌ها
  POST /api/v1/compute/claim/                    گرفتنِ یک کار (یا هیچ)
  GET  /api/v1/compute/jobs/<uid>/package/       بستهٔ کار (payload.json + ورودی‌ها)
  POST /api/v1/compute/jobs/<uid>/progress/      پیشرفت؛ پاسخ ممکن است cancel=true باشد
  POST /api/v1/compute/jobs/<uid>/upload/        فایل‌های خروجی (multipart)
  POST /api/v1/compute/jobs/<uid>/finish/        پایان {ok, error, meta, outputs}
"""
import os

from django.contrib.auth.models import AnonymousUser
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import authentication, exceptions, permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response

from . import services as SV
from .models import ComputeJob, ComputeNode, ComputeNodeLog, ComputeSettings, new_token

#: سرویس‌هایی که گره بلد است روشن/خاموش کند (services.json روی خودِ گره دستورِ اجرایشان را دارد)
SERVICE_KEYS = ("ollama", "comfyui", "voice", "photo", "video", "worker3d")


class NodeAuth(authentication.BaseAuthentication):
    keyword = "Node"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Node "):
            return None
        node = ComputeNode.objects.filter(token=header.split(" ", 1)[1].strip(), enabled=True).first()
        if not node:
            raise exceptions.AuthenticationFailed("توکنِ سرورِ پردازش نامعتبر است یا غیرفعال شده.")
        node.last_seen = timezone.now()
        node.save(update_fields=["last_seen"])
        return (AnonymousUser(), node)

    def authenticate_header(self, request):
        return "Node"  # تا توکنِ غلط 401 بگیرد، نه 403


def _node(request) -> ComputeNode:
    if not isinstance(request.auth, ComputeNode):
        raise exceptions.NotAuthenticated("فقط سرورِ پردازش")
    return request.auth


def node_api(*methods):
    def deco(fn):
        return api_view(list(methods))(authentication_classes([NodeAuth])(
            permission_classes([permissions.AllowAny])(throttle_classes([])(fn))))
    return deco


def job_json(j: ComputeJob, with_payload=False) -> dict:
    d = {"uid": str(j.uid), "kind": j.kind, "state": j.state, "state_label": j.get_state_display(),
         "progress": round(j.progress, 3), "message": j.message, "error": j.error[-600:] if j.error else "",
         "node": j.node.name if j.node else None, "origin": j.origin, "attempts": j.attempts,
         "created": j.created_at, "claimed": j.claimed_at, "finished": j.finished_at, "final": j.final,
         "dedupe": bool(j.dedupe_of_id), "timeout_s": j.timeout_s,
         "outputs": [{**o, "url": SV.output_url(j, o["name"])} for o in j.outputs()],
         "meta": (j.result or {}).get("meta") or {}}
    if with_payload:
        d["payload"] = j.payload
        d["inputs"] = list((j.inputs or {}).keys())
    return d


def node_json(n: ComputeNode, with_token=False) -> dict:
    caps = n.capabilities or {}
    d = {"id": n.pk, "name": n.name, "enabled": n.enabled, "online": n.online, "last_seen": n.last_seen,
         "capabilities": caps, "stats": n.stats or {}, "jobs_done": n.jobs_done, "notes": n.notes,
         "agent": caps.get("agent"), "hostname": caps.get("hostname"), "gpu": caps.get("gpu"),
         "services": {k: bool(caps.get(k)) for k in ("comfyui", "comfy_bridge", "photo", "video", "voice", "ollama", "blender")},
         "last_error": (ComputeNodeLog.objects.filter(node=n, level__in=["ERROR", "CRITICAL"]).values_list("message", flat=True).first()
                        or ""),
         "desired": n.desired or {}, "auto_switch": n.auto_switch,
         "managed": caps.get("managed") or {},
         "resources": {k: caps.get(k) for k in ("ram_total_mb", "ram_free_mb", "vram_used_mb", "vram_total_mb") if caps.get(k) is not None}}
    if with_token:
        d["token"] = n.token
    return d


# ───────────────────────────── گره

@node_api("POST")
def heartbeat(request):
    node = _node(request)
    if isinstance(request.data, dict) and request.data:
        node.capabilities = dict(request.data)
        node.save(update_fields=["capabilities"])
    return Response({"ok": True, "name": node.name, "server_time": timezone.now(),
                     "desired": node.desired or {}, "auto_switch": node.auto_switch})


@node_api("POST")
def claim(request):
    node = _node(request)
    if isinstance(request.data, dict) and request.data.get("capabilities"):
        node.capabilities = dict(request.data["capabilities"])
        node.save(update_fields=["capabilities"])
    job = SV.claim(node)
    control = {"desired": node.desired or {}, "auto_switch": node.auto_switch}
    if not job:
        return Response({"job": None, **control})
    return Response({"job": {"uid": str(job.uid), "kind": job.kind, "payload": job.payload,
                             "inputs": list((job.inputs or {}).keys()), "timeout_s": job.timeout_s,
                             "attempt": job.attempts}, **control})


def _job_of(request, uid) -> tuple[ComputeNode, ComputeJob]:
    node = _node(request)
    job = get_object_or_404(ComputeJob, uid=uid)
    if job.node_id != node.pk:
        raise exceptions.PermissionDenied("این کار مالِ سرورِ پردازشِ دیگری است.")
    return node, job


@node_api("GET")
def package(request, uid):
    node, job = _job_of(request, uid)
    return FileResponse(open(SV.package(job), "rb"), as_attachment=True, filename="package.zip")


@node_api("POST")
def progress(request, uid):
    node, job = _job_of(request, uid)
    return Response(SV.progress(job, request.data if isinstance(request.data, dict) else {}))


@node_api("POST")
def upload(request, uid):
    node, job = _job_of(request, uid)
    saved = [SV.save_output(job, f.name, f) for f in request.FILES.values()]
    job.heartbeat_at = timezone.now()
    job.save(update_fields=["heartbeat_at"])
    return Response({"ok": True, "saved": saved})


@node_api("POST")
def finish(request, uid):
    node, job = _job_of(request, uid)
    data = request.data if isinstance(request.data, dict) else {}
    job = SV.finish(job, node, bool(data.get("ok")), str(data.get("error") or ""), data.get("meta") or {},
                    data.get("outputs") or [])
    return Response({"ok": True, "state": job.state})


# ───────────────────────────── کارکنان (پنل)

@api_view(["GET", "POST"])
@permission_classes([permissions.IsAdminUser])
def nodes(request):
    if request.method == "POST":
        name = (request.data.get("name") or "").strip()[:60]
        if not name:
            raise exceptions.ValidationError("نام لازم است")
        node, created = ComputeNode.objects.get_or_create(name=name)
        return Response(node_json(node, with_token=True), status=201 if created else 200)
    return Response([node_json(n, with_token=True) for n in ComputeNode.objects.all()])


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_action(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    action = request.data.get("action")
    if action == "toggle":
        node.enabled = not node.enabled
    elif action == "rotate":
        node.token = new_token()
    elif action == "delete":
        node.delete()
        return Response({"ok": True})
    node.save()
    return Response(node_json(node, with_token=True))


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def jobs(request):
    qs = ComputeJob.objects.select_related("node")
    if request.query_params.get("active"):
        qs = qs.exclude(state__in=ComputeJob.FINAL)
    try:
        limit = max(1, min(200, int(request.query_params.get("limit") or 60)))
    except (TypeError, ValueError):
        limit = 60
    return Response({"summary": SV.summary(), "jobs": [job_json(j) for j in qs[:limit]]})


@api_view(["GET", "DELETE"])
@permission_classes([permissions.IsAdminUser])
def job_detail(request, uid):
    job = get_object_or_404(ComputeJob, uid=uid)
    if request.method == "DELETE":
        SV.cancel(job)
    return Response(job_json(job, with_payload=True))


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def submit(request):
    """ثبتِ کارِ آزمایشی از پنل: kind + payload (JSON) + فایل‌های اختیاری."""
    import json as _json
    import shutil
    import tempfile

    kind = (request.data.get("kind") or "echo").strip()
    raw = request.data.get("payload") or "{}"
    try:
        payload = _json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        raise exceptions.ValidationError("payload باید JSON باشد")
    if not isinstance(payload, dict):
        raise exceptions.ValidationError("payload باید یک شیءِ JSON ({...}) باشد")
    try:
        timeout_s = int(request.data.get("timeout") or 1800)
    except (TypeError, ValueError):
        raise exceptions.ValidationError("timeout باید عدد (ثانیه) باشد")
    files = {}
    tmp = tempfile.mkdtemp(prefix="nm-submit-")
    try:
        for key, f in request.FILES.items():
            dest = os.path.join(tmp, os.path.basename(f.name))
            with open(dest, "wb") as fh:
                for chunk in f.chunks():
                    fh.write(chunk)
            files[os.path.basename(f.name)] = dest
            payload.setdefault("files", {})[key] = os.path.basename(f.name)
        try:
            job = SV.enqueue(kind, payload, files, origin="panel", dedupe=bool(request.data.get("dedupe", "1") == "1"),
                             node=(request.data.get("node") or "").strip(), timeout_s=timeout_s)
        except SV.ComputeUnavailable as exc:
            return Response({"error": str(exc)}, status=503)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # enqueue نسخهٔ خودش را در پوشهٔ کار کپی کرده؛ موقتی نماند
    return Response(job_json(job, with_payload=True), status=201)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def output_file(request, uid, name):
    """خروجیِ یک کار — فقط از همین نما (با JWT/سشن)؛ nginx پوشهٔ data/compute را سرو نمی‌کند."""
    job = get_object_or_404(ComputeJob, uid=uid)
    if not (request.user.is_authenticated or isinstance(request.auth, ComputeNode)):
        raise exceptions.NotAuthenticated()
    path = SV.output_path(job, name)
    if not path.is_file():
        raise Http404
    return FileResponse(open(path, "rb"))


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def node_bat(request, pk):
    """START-<name>.bat آمادهٔ همین گره: نشانیِ سایت و توکن داخلش نوشته شده (پنل با blob دانلود می‌کند)."""
    node = get_object_or_404(ComputeNode, pk=pk)
    server = request.build_absolute_uri("/").rstrip("/")
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "rem ===== UpMarket processing node: %s =====" % node.name,
        "rem این فایل را داخلِ پوشهٔ UpMarket-Processing (کنارِ START.bat) بگذارید و اجرا کنید.",
        'set "NM_SITE=%s"' % server,
        'set "NM_TOKEN=%s"' % node.token,
        'set "NM_NODE=%s"' % node.name,
        'call "%~dp0START.bat"',
        "",
    ]
    body = "\r\n".join(lines)
    resp = HttpResponse(body.encode("utf-8"), content_type="application/octet-stream")
    resp["Content-Disposition"] = 'attachment; filename="START-%s.bat"' % node.name
    return resp


# ───────────────────────────── لاگ و تنظیماتِ مسیر

@node_api("POST")
def node_log(request):
    """سرورِ پردازش خطاها/هشدارهایش را می‌فرستد: {"lines": [{"level","message","ts"}]}؛ فقط ۵۰۰ خطِ آخرِ هر گره می‌ماند."""
    from django.utils.dateparse import parse_datetime

    node = _node(request)
    lines = request.data.get("lines") if isinstance(request.data, dict) else None
    if not isinstance(lines, list):
        raise exceptions.ValidationError("lines لازم است")
    rows = []
    for line in lines[:200]:
        if not isinstance(line, dict) or not str(line.get("message", "")).strip():
            continue
        ts = parse_datetime(str(line.get("ts") or "")) if line.get("ts") else None
        rows.append(ComputeNodeLog(node=node, level=str(line.get("level") or "INFO")[:10].upper(),
                                   message=str(line["message"])[:4000], logged_at=ts))
    if rows:
        ComputeNodeLog.objects.bulk_create(rows)
        keep = list(ComputeNodeLog.objects.filter(node=node).order_by("-created_at").values_list("pk", flat=True)[:500])
        ComputeNodeLog.objects.filter(node=node).exclude(pk__in=keep).delete()
    return Response({"ok": True, "saved": len(rows)})


@api_view(["GET", "DELETE"])
@permission_classes([permissions.IsAdminUser])
def node_logs(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    if request.method == "DELETE":
        ComputeNodeLog.objects.filter(node=node).delete()
        return Response({"ok": True})
    try:
        limit = max(1, min(500, int(request.query_params.get("limit", 100))))
    except ValueError:
        limit = 100
    rows = ComputeNodeLog.objects.filter(node=node).order_by("-created_at")[:limit]
    return Response({"node": node.name, "lines": [
        {"level": r.level, "message": r.message, "ts": r.logged_at or r.created_at} for r in rows]})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def enroll(request):
    """ثبتِ خودکارِ سرورِ پردازش: {key, name} ⇐ {name, token}. کلید همان «کلیدِ ثبت» ِ پنل است؛ نام پیش‌فرض نامِ کامپیوتر.
    سرورِ هم‌نامِ موجود همان توکنِ قبلی‌اش را می‌گیرد (اجرای دوباره روی همان کامپیوتر = همان گره)."""
    data = request.data if isinstance(request.data, dict) else {}
    key = str(data.get("key") or "").strip()
    cfg = ComputeSettings.get()
    if not key or key != cfg.enroll_key:
        raise exceptions.PermissionDenied("enrollment key is wrong — copy it from the panel (Processing servers > Register a new server)")
    name = str(data.get("name") or data.get("hostname") or "").strip()[:60]
    name = "".join(ch for ch in name if ch.isalnum() or ch in "-_.") or "node"
    node, created = ComputeNode.objects.get_or_create(name=name)
    if not node.enabled:
        raise exceptions.PermissionDenied("this node is disabled in the panel")
    node.last_seen = timezone.now()
    node.save(update_fields=["last_seen"])
    return Response({"name": node.name, "token": node.token, "created": created}, status=201 if created else 200)


@api_view(["GET", "POST"])
@permission_classes([permissions.IsAdminUser])
def compute_settings(request):
    """مسیرِ تصویر/ویدیو: خالی = هر سرورِ ComfyUI‌دار، یا نامِ یک سرور. متن/بینایی از /ai/status/ خوانده می‌شود."""
    cfg = ComputeSettings.get()
    if request.method == "POST":
        if request.data.get("rotate_enroll_key"):
            cfg.enroll_key = SV.ComputeNode._meta.get_field("token").default()
        if "image_video_node" in request.data:
            name = str(request.data.get("image_video_node") or "").strip()
            if name and not ComputeNode.objects.filter(name=name).exists():
                raise exceptions.ValidationError({"image_video_node": "سروری با این نام نیست"})
            cfg.image_video_node = name
        cfg.save()
    return Response({"image_video_node": cfg.image_video_node, "updated_at": cfg.updated_at,
                     "enroll_key": cfg.enroll_key, "site": request.build_absolute_uri("/").rstrip("/"),
                     "nodes": list(ComputeNode.objects.filter(enabled=True).values_list("name", flat=True))})


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_desired(request, pk):
    """پنل می‌گوید روی این گره چه سرویس‌هایی روشن باشد و سوئیچِ خودکار روشن است یا نه.
    بدنه: {"services": {"ollama": true, "comfyui": false, ...}, "auto_switch": true} — هر دو اختیاری."""
    node = get_object_or_404(ComputeNode, pk=pk)
    data = request.data if isinstance(request.data, dict) else {}
    if "services" in data:
        services = data.get("services") or {}
        if not isinstance(services, dict):
            raise exceptions.ValidationError({"services": "باید شیء باشد"})
        bad = [k for k in services if k not in SERVICE_KEYS]
        if bad:
            raise exceptions.ValidationError({"services": "سرویسِ ناشناخته: " + ", ".join(bad)})
        desired = dict(node.desired or {})
        for k, v in services.items():
            if v is None:
                desired.pop(k, None)   # None = دست نزن (پیش‌فرضِ گره)
            else:
                desired[k] = bool(v)
        node.desired = desired
    if "auto_switch" in data:
        node.auto_switch = bool(data.get("auto_switch"))
    node.save(update_fields=["desired", "auto_switch"])
    return Response(node_json(node))
