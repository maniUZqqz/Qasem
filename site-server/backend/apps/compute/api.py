"""پروتکلِ گره‌های پردازش (همه با سرآیندِ Authorization: Node <token>) + API ِ کارکنان.

  POST /api/v1/compute/heartbeat/                اعلامِ حضور و توانایی‌ها
  POST /api/v1/compute/claim/                    گرفتنِ یک کار (یا هیچ)
  GET  /api/v1/compute/jobs/<uid>/package/       بستهٔ کار (payload.json + ورودی‌ها)
  POST /api/v1/compute/jobs/<uid>/progress/      پیشرفت؛ پاسخ ممکن است cancel=true باشد
  POST /api/v1/compute/jobs/<uid>/upload/        فایل‌های خروجی (multipart)
  POST /api/v1/compute/jobs/<uid>/finish/        پایان {ok, error, meta, outputs}
"""
import functools
import logging
import os

from django.contrib.auth.models import AnonymousUser
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import authentication, exceptions, permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response

from . import queue as QV
from . import report as report_stats
from . import services as SV
from .dbretry import call_with_retry, is_lock_error
from .models import ComputeJob, ComputeNode, ComputeNodeLog, ComputeSettings, new_token

logger = logging.getLogger(__name__)

#: last_seen را بیش از هر این‌قدر ثانیه برای یک گره ننویس (هر درخواستِ گره یک نوشتن بود؛ «آنلاین» = ۹۰ ثانیه)
LAST_SEEN_EVERY_S = 8

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
        now = timezone.now()
        if not node.last_seen or (now - node.last_seen).total_seconds() >= LAST_SEEN_EVERY_S:
            node.last_seen = now
            try:
                call_with_retry(node.save, update_fields=["last_seen"], _what="last_seen")
            except Exception as exc:  # noqa: BLE001
                if not is_lock_error(exc):
                    raise
                logger.warning("compute: last_seen of %s not stored (database locked); the next call stores it", node.name)
        return (AnonymousUser(), node)

    def authenticate_header(self, request):
        return "Node"  # تا توکنِ غلط 401 بگیرد، نه 403


def _node(request) -> ComputeNode:
    if not isinstance(request.auth, ComputeNode):
        raise exceptions.NotAuthenticated("فقط سرورِ پردازش")
    return request.auth


def node_api(*methods):
    def deco(fn):
        @functools.wraps(fn)
        def guarded(request, *a, **kw):
            try:
                return fn(request, *a, **kw)
            except Exception as exc:  # noqa: BLE001
                if not is_lock_error(exc):
                    raise
                # SQLite پس از همهٔ تکرارها هم قفل بود: خطای واقعی نیست. ۵۰۳ + Retry-After ⇒ عامل «تکرارپذیر» می‌شمارد و دوباره می‌فرستد
                logger.warning("compute: %s answered 503 (database locked)", getattr(fn, "__name__", "view"))
                return Response({"error": "پایگاه‌داده لحظه‌ای مشغول است؛ چند ثانیهٔ دیگر دوباره بفرستید.", "retry": True},
                                status=503, headers={"Retry-After": "5"})
        return api_view(list(methods))(authentication_classes([NodeAuth])(
            permission_classes([permissions.AllowAny])(throttle_classes([])(guarded))))
    return deco


def job_json(j: ComputeJob, with_payload=False) -> dict:
    d = {"uid": str(j.uid), "kind": j.kind, "state": j.state, "state_label": j.get_state_display(),
         "progress": round(j.progress, 3), "message": j.message, "error": j.error[-600:] if j.error else "",
         "node": j.node.name if j.node else None, "origin": j.origin, "attempts": j.attempts,
         "created": j.created_at, "claimed": j.claimed_at, "finished": j.finished_at, "final": j.final,
         "dedupe": bool(j.dedupe_of_id), "timeout_s": j.timeout_s,
         "queued_at": j.queued_at, "waited_s": j.waited_s, "run_s": j.run_s, "lost_count": j.lost_count,
         "max_attempts": j.max_attempts, "scheduled_for": j.not_before, "window": j.window, "category": j.category,
         "outputs": [{**o, "url": SV.output_url(j, o["name"])} for o in j.outputs()],
         "meta": (j.result or {}).get("meta") or {},
         # پیشرفتِ زندهٔ کارهای طولانی (دانلودِ مدل: done/total بایت، سرعت، مرحله) که عامل با progress می‌فرستد
         "live": (j.result or {}).get("live") or {}}
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
         "resources": {k: caps.get(k) for k in ("ram_total_mb", "ram_free_mb", "vram_used_mb", "vram_total_mb") if caps.get(k) is not None},
         "gpu_info": caps.get("gpu_info") or {}, "bootstrap": (caps.get("bootstrap") or {}).get("summary") or {},
         "autostart": caps.get("autostart") or {}, "outbox": caps.get("outbox") or {}, "net": caps.get("net") or {},
         "lanes": caps.get("lanes") or {}}
    from .updates import update_state
    d.update(update_state(caps))          # agent_latest / update_waiting / can_remote_update (بستهٔ کدِ روی سایت)
    if with_token:
        d["token"] = n.token
    return d


# ───────────────────────────── گره

def _control(node) -> dict:
    """خواستهٔ پنل برای سرویس‌های گره + «رندرِ سه‌بعدی» وقتی کارِ سه‌بعدی منتظرِ کارگر است و پنل برای این گره
    دربارهٔ worker3d چیزی نگفته (سوئیچِ خودکار روشن) — گره worker-3d.bat را بالا می‌آورد (Blender را یک بار دانلود می‌کند)."""
    desired = dict(node.desired or {})
    if "worker3d" not in desired and node.auto_switch:
        try:
            from apps.up3d.services import wants_gpu_worker
            if wants_gpu_worker(node):
                desired["worker3d"] = True
        except Exception:  # noqa: BLE001 — بخشِ سه‌بعدی نباید سرورهای پردازش را بخواباند
            pass
    out = {"desired": desired, "auto_switch": node.auto_switch, "lanes": True}      # lanes: this site understands claim {lane: light}
    try:
        from . import commands as node_commands
        cmd = node_commands.pending_for(node)
        if cmd:
            out["command"] = cmd          # «دستورها» ِ پنل (عاملِ ۲٫۱۰ به بعد؛ عاملِ قدیمی کلیدِ ناشناخته را نادیده می‌گیرد)
    except Exception:  # noqa: BLE001 — دستورها نباید heartbeat را بیندازند
        pass
    try:
        # اولویتِ لوکال/متیس (apps.ai.AiPriority): مدلِ لوکالِ هر نوعِ کار را به گره می‌گوییم تا «ویرایشِ هوشمندِ عکس» (کیتِ عکس)
        # همان مدلِ بینایی را اول امتحان کند. عاملِ قدیمی این کلید را نمی‌شناسد و نادیده می‌گیرد.
        from services.ai import priority
        cfg = priority.config()
        out["ai"] = {"priority": cfg.priority, "vision_model": priority.local_model(priority.VISION, cfg),
                     "text_model": priority.local_model(priority.TEXT, cfg), "code_model": priority.local_model(priority.CODE, cfg),
                     "research_model": priority.local_model(priority.RESEARCH, cfg)}
    except Exception:  # noqa: BLE001 — این راهنما نباید heartbeat را بیندازد
        pass
    try:
        # زمانِ دانلودها (تنظیمِ کلی) و نسخهٔ سایت برای عامل (۲٫۶ به بعد؛ عاملِ قدیمی کلیدهای ناشناخته را نادیده می‌گیرد)
        from django.conf import settings as dj_settings

        from . import schedule
        out["downloads"] = schedule.control_block()
        out["site_version"] = getattr(dj_settings, "NM_VERSION", "") or ""
    except Exception:  # noqa: BLE001 — این هم نباید heartbeat را بیندازد
        pass
    return out


def _store_caps(node, incoming: dict) -> None:
    """گزارشِ تازهٔ گره را ذخیره می‌کند. فهرستِ مدل‌های Ollama را وقتی Ollama خاموش است عاملِ قدیمی نمی‌فرستد (و ذخیره‌شدهٔ
    قبلی پاک می‌شد ⇒ پنل «نامعلوم» می‌گفت)؛ آخرین فهرست می‌ماند و `ollama_models_stale` می‌گوید قدیمی است."""
    caps = dict(incoming)
    old = node.capabilities or {}
    if "ollama_models" not in caps and old.get("ollama_models"):
        caps["ollama_models"] = old["ollama_models"]
        caps["ollama_models_stale"] = True
    node.capabilities = caps
    call_with_retry(node.save, update_fields=["capabilities"], _what="capabilities")


@node_api("POST")
def heartbeat(request):
    node = _node(request)
    if isinstance(request.data, dict) and request.data:
        _store_caps(node, request.data)
    report_stats.record_heartbeat(node)       # نوبتِ اتصال + نمونهٔ منابع؛ هرگز خطا نمی‌دهد
    try:
        from . import autopilot

        autopilot.on_heartbeat(node)           # نسخهٔ تازهٔ عامل ⇒ آزمونِ خودکار؛ هرگز خطا نمی‌دهد
    except Exception:  # noqa: BLE001
        logger.exception("compute: autopilot.on_heartbeat failed")
    return Response({"ok": True, "name": node.name, "server_time": timezone.now(), **_control(node)})


@node_api("POST")
def claim(request):
    node = _node(request)
    if isinstance(request.data, dict) and request.data.get("capabilities"):
        _store_caps(node, request.data["capabilities"])
    report_stats.record_heartbeat(node)
    lane = str(request.data.get("lane") or "")[:12] if isinstance(request.data, dict) else ""
    job = SV.claim(node, lane=lane)
    control = _control(node)
    if not job:
        return Response({"job": None, **control})
    return Response({"job": {"uid": str(job.uid), "kind": job.kind, "payload": job.payload,
                             "inputs": list((job.inputs or {}).keys()), "timeout_s": job.timeout_s,
                             "attempt": job.attempts}, **control})


def _job_of(request, uid, adopt=True) -> tuple[ComputeNode, ComputeJob]:
    node = _node(request)
    job = get_object_or_404(ComputeJob, uid=uid)
    if job.node_id != node.pk:
        # کاری که همین گره وسطش قطع شد و هنوز کسی آن را نگرفته، دوباره به همین گره سپرده می‌شود (نتیجه‌اش گم نمی‌شود)
        if adopt and SV.adopt_orphan(job, node):
            job.refresh_from_db()
        else:
            raise exceptions.PermissionDenied("این کار مالِ سرورِ پردازشِ دیگری است.")
    return node, job


def _byte_range(header: str):
    """`Range: bytes=N-` (agent 2.11 resumes a package that broke on a bad line) -> N, or None if absent / not understood.
    Only an open-ended single range is served; anything else gets the whole file (a normal 200)."""
    import re

    m = re.fullmatch(r"\s*bytes=(\d+)-\s*", header or "")
    if not m:
        return None
    return int(m.group(1))


@node_api("GET")
def package(request, uid):
    node, job = _job_of(request, uid, adopt=False)
    path = SV.package(job)
    size = path.stat().st_size
    start = _byte_range(request.headers.get("Range", ""))
    if start is None or start == 0:
        return FileResponse(open(path, "rb"), as_attachment=True, filename="package.zip")
    if start >= size:
        resp = HttpResponse(status=416)
        resp["Content-Range"] = "bytes */%d" % size
        return resp

    def body():
        with open(path, "rb") as fh:
            fh.seek(start)
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                yield chunk

    resp = StreamingHttpResponse(body(), status=206, content_type="application/zip")
    resp["Content-Length"] = str(size - start)
    resp["Content-Range"] = "bytes %d-%d/%d" % (start, size - 1, size)
    resp["Accept-Ranges"] = "bytes"
    resp["Content-Disposition"] = 'attachment; filename="package.zip"'
    return resp


@node_api("POST")
def progress(request, uid):
    node, job = _job_of(request, uid)
    return Response(SV.progress(job, request.data if isinstance(request.data, dict) else {}))


@node_api("POST")
def upload(request, uid):
    node, job = _job_of(request, uid)
    saved = [SV.save_output(job, f.name, f) for f in request.FILES.values()]
    job.heartbeat_at = timezone.now()
    call_with_retry(job.save, update_fields=["heartbeat_at"], _what="upload heartbeat")
    return Response({"ok": True, "saved": saved})


@node_api("POST")
def finish(request, uid):
    node, job = _job_of(request, uid)
    data = request.data if isinstance(request.data, dict) else {}
    job = SV.finish(job, node, bool(data.get("ok")), str(data.get("error") or ""), data.get("meta") or {},
                    data.get("outputs") or [])
    if job.kind == "ollama.pull" and job.state == ComputeJob.State.COMPLETED:
        try:        # مدلِ تازه نصب شد: «نصب نیست»ِ احتمالیِ ثبت‌شده در مسیریابِ هوش مصنوعی پاک شود
            from services.ai import model_pull
            model_pull.pull_completed(job)
        except Exception:  # noqa: BLE001 — پاکسازیِ حافظهٔ شکست نباید پایانِ کار را بیندازد
            pass
    if job.kind == "ig.scrape":
        try:        # خواندنِ اینستاگرام تمام شد: نتیجه همین حالا وارد ترندها شود (apps.igtrends)
            from apps.igtrends import dispatch as ig_dispatch
            ig_dispatch.on_job_finished(job)
        except Exception:  # noqa: BLE001 — ذخیرهٔ ترندها نباید پایانِ کار را بیندازد؛ sync دورهٔ بعد دوباره می‌گیرد
            logger.exception("igtrends: could not take in the result of %s", job.uid)
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
        SV.cancel(job, "کاربر از پنل لغو کرد (%s)." % (getattr(request.user, "username", "") or "?"))
    return Response(job_json(job, with_payload=True))


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def submit(request):
    """ثبتِ کارِ آزمایشی از پنل: kind + payload (JSON) + فایل‌های اختیاری."""
    import json as _json
    import shutil
    import tempfile

    kind = (request.data.get("kind") or "echo").strip()
    if kind == "ollama.pull":
        # دانلودِ مدل فقط از کارتِ «اولویتِ هوش مصنوعی» و فقط برچسب‌های فهرستِ مجازِ سایت (services.ai.model_pull)
        return Response({"error": "دانلودِ مدل را از کارتِ «اولویتِ هوش مصنوعی» (ادمین ⇐ موتورهای AI) بزنید؛ فقط مدل‌های فهرستِ مجاز."},
                        status=400)
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
            job = SV.enqueue_durable(kind, payload, files, origin="panel", dedupe=bool(request.data.get("dedupe", "1") == "1"),
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
        call_with_retry(ComputeNodeLog.objects.bulk_create, rows, _what="node logs")
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


def _queue_settings_json(cfg) -> dict:
    return {"max_wait_hours": cfg.max_wait_hours, "download_mode": cfg.download_mode,
            "download_window": cfg.download_window, "retention_days": cfg.retention_days,
            "auto_update": cfg.auto_update, "auto_selftest": cfg.auto_selftest, "nightly_selftest": cfg.nightly_selftest,
            "nightly_time": cfg.nightly_time, "requeue_after_pass": cfg.requeue_after_pass, "short_burst": cfg.short_burst}


def _apply_queue_settings(cfg, data) -> None:
    """سقفِ انتظارِ کارها، زمانِ دانلودها و نگه‌داریِ آمار (همه اختیاری)."""
    if "max_wait_hours" in data:
        try:
            hours = int(data.get("max_wait_hours") or 0)
        except (TypeError, ValueError):
            raise exceptions.ValidationError({"max_wait_hours": "عدد (ساعت) بنویسید؛ ۰ یعنی بی‌پایان"})
        if not 0 <= hours <= 24 * 365:
            raise exceptions.ValidationError({"max_wait_hours": "بین ۰ تا ۸۷۶۰ ساعت"})
        cfg.max_wait_hours = hours
    if "download_mode" in data:
        mode = str(data.get("download_mode") or "now")
        if mode not in ("now", "window"):
            raise exceptions.ValidationError({"download_mode": "«الان» یا «در بازهٔ شبانه»"})
        cfg.download_mode = mode
    if "download_window" in data:
        window = str(data.get("download_window") or "").strip()
        if not SV.parse_window(window):
            raise exceptions.ValidationError({"download_window": "بازه را مثل ۰۲:۰۰-۰۷:۰۰ بنویسید (ساعتِ شروع و پایان فرق داشته باشد)"})
        cfg.download_window = window
    for flag in ("auto_update", "auto_selftest", "nightly_selftest", "requeue_after_pass"):
        if flag in data:
            setattr(cfg, flag, bool(data.get(flag)) and str(data.get(flag)).lower() not in ("0", "false", "no", "off"))
    if "nightly_time" in data:
        hhmm = str(data.get("nightly_time") or "").strip()
        if not SV.next_clock_time(hhmm):
            raise exceptions.ValidationError({"nightly_time": "ساعت را مثل ۰۳:۳۰ بنویسید"})
        cfg.nightly_time = hhmm[:5]
    if "short_burst" in data:
        try:
            burst = int(data.get("short_burst") or 0)
        except (TypeError, ValueError):
            raise exceptions.ValidationError({"short_burst": "عدد بنویسید"})
        if not 1 <= burst <= 100:
            raise exceptions.ValidationError({"short_burst": "بین ۱ تا ۱۰۰"})
        cfg.short_burst = burst
    if "retention_days" in data:
        try:
            days = int(data.get("retention_days") or 0)
        except (TypeError, ValueError):
            raise exceptions.ValidationError({"retention_days": "عدد (روز) بنویسید"})
        if not 1 <= days <= 365:
            raise exceptions.ValidationError({"retention_days": "بین ۱ تا ۳۶۵ روز"})
        cfg.retention_days = days


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
        _apply_queue_settings(cfg, request.data)
        cfg.save()
    from .updates import latest
    return Response({"image_video_node": cfg.image_video_node, "updated_at": cfg.updated_at, **_queue_settings_json(cfg),
                     "enroll_key": cfg.enroll_key, "site": request.build_absolute_uri("/").rstrip("/"),
                     "nodes": list(ComputeNode.objects.filter(enabled=True).values_list("name", flat=True)),
                     "package": latest()})


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


# ───────────────────────────── صفِ پردازش (پنل، فقط کارکنان)

def _int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _parse_dt(value):
    from django.utils.dateparse import parse_date, parse_datetime
    if not value:
        return None
    dt = parse_datetime(str(value))
    if dt is None:
        d = parse_date(str(value))
        if d is not None:
            from datetime import datetime, time as _t
            dt = datetime.combine(d, _t.min)
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def queue_list(request):
    qp = request.query_params
    state = qp.get("state") or "all"
    return Response(QV.listing(
        state=state, kind=(qp.get("kind") or "").strip(), q=(qp.get("q") or "").strip()[:80],
        limit=_int(qp.get("limit"), 100, 1, 500), offset=_int(qp.get("offset"), 0, 0, 100000),
        category=(qp.get("category") or "").strip(), since=_parse_dt(qp.get("since")), until=_parse_dt(qp.get("until"))))


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def queue_summary(request):
    return Response(QV.summary())


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def queue_cancel(request, uid):
    job = get_object_or_404(ComputeJob, uid=uid)
    SV.cancel(job, "کاربر از «صفِ پردازش» لغو کرد (%s)." % (getattr(request.user, "username", "") or "?"))
    job.refresh_from_db()
    return Response(QV.one(job))


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def queue_retry(request, uid):
    job = get_object_or_404(ComputeJob, uid=uid)
    try:
        job, notice = QV.retry_ex(job)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)
    return Response({**QV.one(job), "notice": notice})


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def queue_cancel_waiting(request):
    """همهٔ کارهای «در صف» (اختیاری: فقط یک نوع) را لغو می‌کند."""
    kind = str((request.data or {}).get("kind") or "").strip() if isinstance(request.data, dict) else ""
    qs = ComputeJob.objects.filter(state=ComputeJob.State.QUEUED)
    if kind:
        qs = qs.filter(kind__startswith=kind)
    n = 0
    for job in qs:
        SV.cancel(job, "کاربر همهٔ کارهای منتظر را لغو کرد (%s)." % (getattr(request.user, "username", "") or "?"))
        n += 1
    return Response({"cancelled": n})
