"""«چندزاویه» — منطقِ سایت: انتخاب‌ها، ثبتِ کار روی سرورِ پردازش، همگام‌سازیِ وضعیت، آوردنِ نتیجه به رسانهٔ فروشگاه، ساختِ پروژهٔ ادیتور
و آماده‌سازیِ خودکارِ سرورِ پردازش.

جریان:
  create_virtual / create_move → یک MultiAngleRun + یک کارِ `multiangle.virtual|move` در صفِ ماندگارِ سرورِ پردازش (گره خاموش باشد کار می‌ماند)
  refresh(run)                 → وضعیتِ کارِ گره را می‌خواند؛ کارِ تمام‌شده را به رسانهٔ فروشگاه می‌آورد (ingest) — از همان درخواستِ پنل
  build_project(run)           → پروژهٔ ادیتور با توالیِ مولتی‌کم؛ «باز کردن در ادیتور»
  autocheck()                  → (beat هر دو دقیقه) گرهٔ روشنِ چندزاویه‌دار را آماده می‌کند (نصبِ خودکار) و آزمونِ خودکارش را می‌زند

سرورِ پردازش خودش هم محیط و مدل‌ها را نصب می‌کند (processing/multiangle_jobs.py)؛ این‌جا فقط اگر چیزی نصب نشده و گره خودش مشغولِ دانلود
نیست، همان را از سمتِ سایت هم درخواست می‌کنیم (voice_models.start_download با «همین الان»).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from services.editing import multiangle as ma

from .models import MultiAngleRun

logger = logging.getLogger(__name__)

KIND_VIRTUAL = "multiangle.virtual"
KIND_MOVE = "multiangle.move"
KIND_SELFTEST = "multiangle.selftest"
MAX_SECONDS = 180.0
MAX_MOVE_SECONDS = 12.0
MAX_BYTES = 700 * 1024 ** 2
MAX_RUNS = 60
#: بسته‌هایی که این قابلیت از گره می‌خواهد (processing/downloads/multiangle.json)
PACKAGES = ("multiangle-runtime", "multiangle-detect", "multiangle-depth")
SELFTEST_RETRY_HOURS = 6
INSTALL_GRACE_MIN = 20


class MultiAngleError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "multiangle"):
        super().__init__(message)
        self.status, self.code = status, code


# ------------------------------------------------------------------ small helpers

def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def media_url(rel: str | None) -> str | None:
    if not rel:
        return None
    return settings.MEDIA_URL.rstrip("/") + "/" + str(rel).replace("\\", "/").lstrip("/")


def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    return max(lo, min(hi, x))


def _choice(v, allowed, default):
    v = str(v or "").strip()
    return v if v in allowed else default


def presets() -> dict:
    """What the page offers (labels in Persian, keys English)."""
    c = ma.core()
    return {
        "angles": [{"key": k, "label": ma.ANGLE_FA[k], "hint": ma.ANGLE_HINT_FA[k], "needs_two": c.ANGLES[k]["subjects"] == 2, "default": k in ("wide", "medium", "close")}
                   for k in c.ANGLE_ORDER],
        "formats": [{"key": k, "label": ma.FORMAT_FA[k]} for k in c.FORMATS],
        "paces": [{"key": k, "label": ma.PACE_FA[k]} for k in c.PACE],
        "rhythms": [{"key": k, "label": v} for k, v in ma.RHYTHM_FA.items()],
        "moves": [{"key": k, "label": ma.MOVE_FA[k], "hint": ma.MOVE_HINT_FA[k]} for k in c.MOVE_ORDER],
        "limits": {"max_seconds": MAX_SECONDS, "max_move_seconds": MAX_MOVE_SECONDS},
        "defaults": {"format": "source", "pace": "medium", "handheld": 0.35, "rhythm": "auto", "amount": 0.5, "duration": 4.0},
    }


# ------------------------------------------------------------------ sources (what the owner can pick)

def _image_size(url: str | None) -> tuple[int, int]:
    """(width, height) read from the header of a media file (the bin does not probe pictures); (0, 0) when it cannot be read."""
    if not url:
        return 0, 0
    prefix = settings.MEDIA_URL.rstrip("/") + "/"
    if not str(url).startswith(prefix):
        return 0, 0
    try:
        from urllib.parse import unquote

        from PIL import Image

        path = media_root() / unquote(str(url)[len(prefix):].split("?", 1)[0])
        if not path.is_file():
            return 0, 0
        with Image.open(path) as im:
            return int(im.size[0]), int(im.size[1])
    except Exception:  # noqa: BLE001 — a broken picture must not blank the picker
        return 0, 0


def list_sources(store) -> dict:
    """{"videos": [...], "images": [...]} from the editor's media bin (so the refs are the same ones the editor uses).
    Pictures carry their real size (read from the file header - the bin itself leaves it 0), so the picker never shows «۰×۰»."""
    from apps.content import editor_project

    bin_ = editor_project.bin_items(store, limit=40)
    videos = [{"ref": v["ref"], "title": v["title"], "duration": v.get("duration") or 0, "width": v.get("width") or 0, "height": v.get("height") or 0,
               "has_audio": bool(v.get("has_audio")), "url": v.get("url"), "source": v.get("source")}
              for v in bin_.get("videos", []) if (v.get("duration") or 0) >= 1.0]
    images = []
    for i in bin_.get("images", []):
        if i.get("kind") != "image":
            continue
        w, h = int(i.get("width") or 0), int(i.get("height") or 0)
        if not (w and h):
            w, h = _image_size(i.get("url"))
        images.append({"ref": i["ref"], "title": i["title"], "width": w, "height": h, "url": i.get("url"), "source": i.get("source")})
    return {"videos": videos, "images": images}


def _locate_input(store, ref: str, want: tuple):
    """-> (context manager yielding a resolved dict) — the file's local path stays valid inside the `with` block."""
    from apps.content import editor_project

    ref = str(ref or "")
    if not re.fullmatch(r"(video|edited|script|photo|pimg|gimg):\d+", ref):
        raise MultiAngleError("منبع نامعتبر است؛ یکی از ویدیوها یا عکس‌های فروشگاه را انتخاب کنید.")
    try:
        found = editor_project.locate(store, ref)
    except Exception as exc:  # noqa: BLE001 — RefError / TimelineError: the ref is not the store's own
        raise MultiAngleError(str(exc) or "منبع پیدا نشد.") from exc
    if found.get("kind") not in want:
        raise MultiAngleError("این منبع برای این کار مناسب نیست.")
    return editor_project.sources(store), found


# ------------------------------------------------------------------ the nodes

def _nodes():
    from apps.compute.models import ComputeNode

    return [n for n in ComputeNode.objects.filter(enabled=True)]


def _caps(node) -> dict:
    return node.capabilities or {}


def multiangle_nodes():
    return [n for n in _nodes() if _caps(n).get("multiangle")]


def old_nodes():
    return [n for n in _nodes() if _caps(n).get("agent") and not _caps(n).get("multiangle")]


UPDATE_TEXT = ("نرم‌افزارِ سرورِ پردازش قدیمی است و «چندزاویه» را نمی‌شناسد: روی آن کامپیوتر Update.bat را اجرا کنید "
               "(یا در «سرورهای پردازش» دکمهٔ «به‌روزرسانی»). کارها تا آن موقع در صف می‌مانند و بعد از آن همه‌چیز خودکار نصب می‌شود.")
UPDATE_OFFLINE_AUTO = "سرورِ پردازش خاموش است؛ با روشن شدنش خودش به‌روز می‌شود و کار اجرا می‌شود."
UPDATE_ONLINE_AUTO = ("سرورِ پردازش روشن است و نرم‌افزارش خودکار به‌روز می‌شود؛ بعد از آن محیط و مدل‌ها هم خودکار نصب می‌شود و کارِ شما اجرا می‌شود. "
                      "لازم نیست کاری بکنید.")
UPDATE_OFFLINE_MANUAL = ("سرورِ پردازش خاموش است و نرم‌افزارش قدیمی است؛ بعد از روشن کردنش Update.bat را روی آن کامپیوتر اجرا کنید "
                         "(یا در «سرورهای پردازش» دکمهٔ «به‌روزرسانی»). کارها تا آن موقع در صف می‌مانند.")
UPDATE_NO_COMMAND = "سرورِ پردازش روشن است و نرم‌افزارش قدیمی است؛ با اجرای START.bat خودش به‌روز می‌شود. کارها تا آن موقع در صف می‌مانند."
UPDATE_TRIES_OUT = ("سه تلاشِ خودکارِ به‌روزرسانی انجام شد و سرورِ پردازش هنوز قدیمی است؛ در «سرورهای پردازش» دکمهٔ «به‌روزرسانی» را بزنید "
                    "(یا Update.bat را اجرا کنید). کارها در صف می‌مانند.")
NO_NODE_TEXT = ("هنوز هیچ سرورِ پردازشی ثبت نشده؛ روی کامپیوترِ گرافیکی START.bat را یک بار اجرا کنید تا ثبت شود. "
                "از آن به بعد کارها تا روشن شدنِ آن در صف می‌مانند.")


def update_text(old) -> str:
    """What the owner reads while every registered node still runs an agent that does not know «چندزاویه»: the job is queued and the node updates
    itself (autopilot) - the text says which of the situations it is (off, on and updating, auto-update disabled, ...)."""
    from apps.compute import autopilot
    from apps.compute.models import ComputeSettings

    online = [n for n in old if n.online]
    try:
        auto_on = bool(ComputeSettings.get().auto_update)
    except Exception:  # noqa: BLE001 — a settings problem must not blank the page
        auto_on = True
    if not online:
        return UPDATE_OFFLINE_AUTO if auto_on else UPDATE_OFFLINE_MANUAL
    if not auto_on:
        return UPDATE_TEXT
    try:
        wanted, why = autopilot.update_wanted(online[0])
    except Exception:  # noqa: BLE001
        wanted, why = True, ""
    if wanted or not why:
        return UPDATE_ONLINE_AUTO
    if "دستورِ به‌روزرسانی را نمی‌شناسد" in why:
        return UPDATE_NO_COMMAND
    if "سه تلاش" in why:
        return UPDATE_TRIES_OUT
    return UPDATE_ONLINE_AUTO


def node_row(node) -> dict:
    caps = _caps(node)
    rt = caps.get("multiangle_runtime") or {}
    models = caps.get("multiangle_models") or {}
    ready = caps.get("multiangle_ready") or {}
    labels = {"yunet": "YuNet — تشخیصِ چهره", "yolos": "YOLOS — تشخیصِ آدم", "depth": "Depth-Anything-V2-Small — عمق"}
    state_fa = {"installed": "نصب است", "downloading": "در حالِ دانلود", "queued": "در صفِ دانلود", "missing": "نصب نیست", "failed": "دانلود ناموفق بود"}
    rows = []
    for key in ("yunet", "yolos", "depth"):
        m = models.get(key) or {}
        st = m.get("state") or "missing"
        rows.append({"key": key, "label": labels[key], "state": st, "state_label": state_fa.get(st, st), "size_mb": m.get("size_mb"), "progress": m.get("progress"),
                     "error": m.get("error") or ""})
    installing = any(r["state"] in ("downloading", "queued") for r in rows) or bool((caps.get("models") or {}).get("running"))
    if not node.online:
        message = "سرورِ پردازش خاموش است؛ کارها در صف می‌مانند و با روشن شدنش خودکار اجرا می‌شوند."
    elif ready.get("virtual") and ready.get("move"):
        message = "آماده است" + (" (روی کارتِ گرافیک)" if rt.get("gpu") else " (روی پردازنده؛ با نصبِ درایورِ DirectX 12 سریع‌تر می‌شود)")
    elif rt.get("ok") is None:
        message = "در حالِ بررسیِ محیطِ اجرا…"
    elif installing or (rt.get("ok") is False):
        message = "در حالِ نصبِ خودکارِ محیطِ اجرا و مدل‌ها (حدود ۰٫۴ گیگابایت)؛ لازم نیست کاری بکنید."
    else:
        message = "در انتظارِ نصبِ خودکارِ مدل‌ها."
    return {"name": node.name, "online": node.online, "gpu": caps.get("gpu") or "", "ready": {k: bool(ready.get(k)) for k in ("virtual", "move", "selftest")},
            "runtime": {"ok": rt.get("ok"), "gpu": bool(rt.get("gpu")), "providers": rt.get("providers") or [], "message": rt.get("message") or ""},
            "models": rows, "installing": installing, "message": message, "version": caps.get("multiangle_version") or "",
            "selftest": selftest_summary(node.name)}


def status() -> dict:
    ns = multiangle_nodes()
    old = old_nodes()
    rows = [node_row(n) for n in sorted(ns, key=lambda n: (not n.online, n.name))]
    can_virtual = any(r["online"] and r["ready"]["virtual"] for r in rows)
    can_move = any(r["online"] and r["ready"]["move"] for r in rows)
    waiting_for_update = bool(old) and not rows
    if rows:
        message = next((r["message"] for r in rows if r["online"]), rows[0]["message"])
    elif old:
        message = update_text(old)
    else:
        message = NO_NODE_TEXT
    # «can_queue»: a job can be registered right now - a node that knows the feature exists, or an older one that will update itself;
    # only when no node was ever registered there is nothing for a job to wait for (the page then says so instead of promising a queue)
    return {"nodes": rows, "ready": {"virtual": can_virtual, "move": can_move}, "online": any(r["online"] for r in rows), "message": message,
            "can_queue": bool(rows) or bool(old), "needs_update": [n.name for n in old] if not rows else [],
            "update_text": message if waiting_for_update else "", "node_online": any(n.online for n in _nodes())}


# ------------------------------------------------------------------ the self-test

def selftest_summary(node_name: str) -> dict | None:
    run = _selftests(node_name).first()
    if run is None:
        return None
    return {"id": run.pk, "state": run.state, "ok": run.state == MultiAngleRun.State.READY, "at": run.updated_at, "checks": _checks_fa(run.checks),
            "error": run.error[:300]}


def _selftests(node_name: str):
    return MultiAngleRun.objects.filter(mode=MultiAngleRun.Mode.SELFTEST, params__node=node_name).order_by("-created_at")


def _checks_fa(checks) -> list[dict]:
    return [{"name": c.get("name"), "label": ma.CHECK_FA.get(c.get("name"), c.get("name")), "ok": bool(c.get("ok")), "detail": str(c.get("detail") or "")[:200]}
            for c in checks or []]


def _stamp(node) -> str:
    caps = _caps(node)
    return "%s|%s" % (caps.get("multiangle_version") or "", (caps.get("code") or {}).get("id") or caps.get("agent") or "")


def request_selftest(node, user=None) -> MultiAngleRun:
    """The acceptance run of one node: a synthetic clip and picture through both features + pass checks (payload {selftest: true})."""
    from apps.compute import services as SV

    run = MultiAngleRun.objects.create(mode=MultiAngleRun.Mode.SELFTEST, title=f"آزمونِ خودکارِ «{node.name}»", created_by=user,
                                       params={"node": node.name, "stamp": _stamp(node)})
    try:
        job = SV.enqueue(KIND_SELFTEST, {"selftest": True}, {}, store=None, origin="multiangle-selftest", priority=20, timeout_s=1500, node=node.name,
                         dedupe=False, require_online=False, max_attempts=2)
    except SV.ComputeError as exc:
        run.state, run.error = MultiAngleRun.State.FAILED, str(exc)
        run.save(update_fields=["state", "error", "updated_at"])
        return run
    run.job_uid = str(job.uid)
    run.message = "در صف"
    run.save(update_fields=["job_uid", "message", "updated_at"])
    return run


def _need_selftest(node) -> bool:
    last = _selftests(node.name).first()
    if last is None:
        return True
    if last.active:
        return False
    if last.params.get("stamp") != _stamp(node):
        return True                                           # a new node version: test again
    if last.state == MultiAngleRun.State.READY:
        return False
    return timezone.now() - last.updated_at > timedelta(hours=SELFTEST_RETRY_HOURS)


def _install_in_flight(node) -> bool:
    from apps.compute.models import ComputeJob

    caps = _caps(node)
    if (caps.get("models") or {}).get("running"):
        return True
    note = caps.get("multiangle_install") or {}
    if note.get("last") and timezone.now().timestamp() - float(note["last"]) < INSTALL_GRACE_MIN * 60:
        return True
    return ComputeJob.objects.filter(kind="node.models", node_wanted=node.name, state__in=["QUEUED", "CLAIMED", "RUNNING"]).exists()


def prepare_node(node) -> str:
    """Ask the node to fetch what the feature still lacks (immediately - the packages are small). Returns a short text for the log/page."""
    from apps.compute import voice_models

    caps = _caps(node)
    ready = caps.get("multiangle_ready") or {}
    if ready.get("virtual") and ready.get("move"):
        return "ready"
    if _install_in_flight(node):
        return "installing"
    rt = caps.get("multiangle_runtime") or {}
    models = caps.get("multiangle_models") or {}
    need = []
    if rt.get("ok") is False:
        need.append(PACKAGES[0])
    if any((models.get(k) or {}).get("state") != "installed" for k in ("yunet", "yolos")):
        need.append(PACKAGES[1])
    if (models.get("depth") or {}).get("state") != "installed":
        need.append(PACKAGES[2])
    if not need:
        return "waiting"
    try:
        voice_models.start_download(node, need, when={"mode": "now"})
    except voice_models.VoiceModelsError as exc:
        logger.info("multiangle: could not ask %s to install: %s", node.name, exc)
        return str(exc)
    return "requested: " + ", ".join(need)


def autocheck() -> dict:
    """Every two minutes (beat): a multi-angle node that is online is made ready (install) and then tested - nobody has to click."""
    out = {}
    for node in multiangle_nodes():
        if not node.online:
            continue
        ready = _caps(node).get("multiangle_ready") or {}
        if not (ready.get("virtual") and ready.get("move")):
            out[node.name] = prepare_node(node)
            continue
        if ready.get("selftest") and _need_selftest(node):
            run = request_selftest(node)
            out[node.name] = f"selftest #{run.pk}"
        else:
            out[node.name] = "ok"
    for run in MultiAngleRun.objects.filter(mode=MultiAngleRun.Mode.SELFTEST, state__in=MultiAngleRun.ACTIVE)[:10]:
        try:
            refresh(run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("multiangle selftest refresh failed: %s", exc)
    return out


# ------------------------------------------------------------------ requests

def clean_virtual(data: dict) -> dict:
    c = ma.core()
    angles = [a for a in (data.get("angles") or ["wide", "medium", "close"]) if a in c.ANGLES]
    angles = [a for a in c.ANGLE_ORDER if a in angles]
    if len(angles) < 2:
        raise MultiAngleError("دست‌کم دو زاویه انتخاب کنید.")
    return {
        "angles": angles, "format": _choice(data.get("format"), c.FORMATS, "source"), "pace": _choice(data.get("pace"), c.PACE, "medium"),
        "handheld": round(_num(data.get("handheld"), 0.0, 1.0, 0.35), 2), "rhythm": _choice(data.get("rhythm"), ("auto", "speech", "beat"), "auto"),
        "multicam": data.get("multicam") is not False, "max_upscale": round(_num(data.get("max_upscale"), 1.1, 3.0, 1.7), 2),
    }


def clean_move(data: dict) -> dict:
    c = ma.core()
    return {
        "move": _choice(data.get("move"), c.MOVES, "dolly_in"), "amount": round(_num(data.get("amount"), 0.0, 1.0, 0.5), 2),
        "duration": round(_num(data.get("duration"), 1.0, MAX_MOVE_SECONDS, 4.0), 1), "format": _choice(data.get("format"), c.FORMATS, "source"),
        "ease": _choice(data.get("ease"), ("inout", "sine", "out", "linear"), "inout"), "relief": round(_num(data.get("relief"), 0.4, 2.5, 1.0), 2),
        "inpaint": bool(data.get("inpaint")),
    }


def _sentences(obj) -> list[dict]:
    rows = []
    for row in getattr(obj, "transcript", None) or []:
        try:
            s, e = float(row.get("start")), float(row.get("end"))
        except (TypeError, ValueError, AttributeError):
            continue
        if e > s:
            rows.append({"start": round(s, 2), "end": round(e, 2)})
    return rows[:2000]


def _enqueue(run: MultiAngleRun, kind: str, payload: dict, name: str, path: Path, *, timeout_s: int):
    """Register the compute job and keep it in the durable queue.

    Normal case: a node that advertises «multiangle» is known (on or off) -> `enqueue_durable`. While every registered node still runs an agent
    from before the feature (no «multiangle» capability yet) the job is queued anyway: such an agent is never offered the kind
    (services.kind_unsupported / _kinds_q), it waits, and it runs as soon as the node has updated itself (autopilot) and reports the capability -
    nobody has to press anything. Only when no node was ever registered there is nothing to wait for (503 `no_node`, no run is left)."""
    from apps.compute import services as SV

    kw = dict(store=run.store, origin="multiangle", priority=60, timeout_s=timeout_s, dedupe=False)
    try:
        job = SV.enqueue_durable(kind, payload, {name: str(path)}, **kw)
    except SV.ComputeUnavailable as exc:
        old = old_nodes()
        if not old:
            run.delete()
            raise MultiAngleError(NO_NODE_TEXT, 503, "no_node") from exc
        try:
            job = SV.enqueue(kind, payload, {name: str(path)}, require_online=False, **kw)
        except Exception:
            run.delete()
            raise
    run.job_uid = str(job.uid)
    run.message = (waiting_text() or str(job.message or "در صف"))[:300]
    run.save(update_fields=["job_uid", "message", "updated_at"])
    return job


def waiting_text() -> str:
    """Why a queued run is not running yet, when the reason is the node's old software (else '')."""
    if multiangle_nodes():
        return ""
    old = old_nodes()
    return update_text(old) if old else ""


def _prune(store) -> None:
    keep = MAX_RUNS
    ids = list(MultiAngleRun.objects.filter(store=store).order_by("-created_at").values_list("pk", flat=True)[keep:])
    for run in MultiAngleRun.objects.filter(pk__in=ids).exclude(state__in=MultiAngleRun.ACTIVE):
        delete_run(run)


def create_virtual(store, user, data: dict) -> MultiAngleRun:
    """One video -> several virtual cameras (+ the auto-switched multicam edit)."""
    opts = clean_virtual(data)
    ctx, found = _locate_input(store, data.get("source"), ("video",))
    with ctx as resolve:
        info = resolve(str(data.get("source")))
        path = Path(info["path"])
        if not path.is_file():
            raise MultiAngleError("فایلِ ویدیو روی سرور پیدا نشد.")
        if path.stat().st_size > MAX_BYTES:
            raise MultiAngleError("حجمِ ویدیو بیش از ۷۰۰ مگابایت است؛ نسخهٔ کوچک‌تر یا کوتاه‌تری بسازید.")
        if float(info.get("duration") or 0) < 1.0:
            raise MultiAngleError("این ویدیو کوتاه‌تر از یک ثانیه است.")
        duration = float(info["duration"])
        title = str(found.get("title") or "ویدیو")
        run = MultiAngleRun.objects.create(store=store, created_by=user, mode=MultiAngleRun.Mode.VIRTUAL, title=f"{title} — چندزاویه", source_ref=str(data["source"]),
                                           params={**opts, "source_title": title, "duration": round(duration, 2), "trimmed": duration > MAX_SECONDS,
                                                   "size": [info.get("width"), info.get("height")]})
        payload = {"video": "source" + (path.suffix.lower() or ".mp4"), "angles": opts["angles"], "format": opts["format"], "pace": opts["pace"],
                   "handheld": opts["handheld"], "rhythm": opts["rhythm"], "seed": run.pk % 997 + 3, "multicam": opts["multicam"], "max_upscale": opts["max_upscale"],
                   "max_seconds": MAX_SECONDS}
        sent = _sentences(found.get("obj"))
        if sent:
            payload["sentences"] = sent
        timeout = int(min(7200, 900 + min(duration, MAX_SECONDS) * 30 * max(1, len(opts["angles"]) / 3)))
        _enqueue(run, KIND_VIRTUAL, payload, payload["video"], path, timeout_s=timeout)
    _prune(store)
    return run


def create_move(store, user, data: dict) -> MultiAngleRun:
    """One picture or clip -> a 2.5D camera move."""
    opts = clean_move(data)
    ctx, found = _locate_input(store, data.get("source"), ("video", "image"))
    with ctx as resolve:
        info = resolve(str(data.get("source")))
        path = Path(info["path"])
        if not path.is_file():
            raise MultiAngleError("فایلِ منبع روی سرور پیدا نشد.")
        if path.stat().st_size > MAX_BYTES:
            raise MultiAngleError("حجمِ منبع بیش از ۷۰۰ مگابایت است.")
        is_video = info.get("kind") == "video"
        title = str(found.get("title") or "تصویر")
        run = MultiAngleRun.objects.create(store=store, created_by=user, mode=MultiAngleRun.Mode.MOVE, title=f"{title} — {ma.MOVE_FA[opts['move']]}",
                                           source_ref=str(data["source"]), params={**opts, "source_title": title, "video": is_video})
        payload = {"input": "source" + (path.suffix.lower() or (".mp4" if is_video else ".jpg")), **opts, "fps": 30,
                   "max_seconds": MAX_MOVE_SECONDS}
        if data.get("focus"):
            f = str(data["focus"])
            if re.fullmatch(r"\d(\.\d+)?,\d(\.\d+)?", f):
                payload["focus"] = f
        _enqueue(run, KIND_MOVE, payload, payload["input"], path, timeout_s=int(900 + opts["duration"] * 90))
    _prune(store)
    return run


# ------------------------------------------------------------------ the status of a run

_ERR_FA = {
    "no_video": "ویدیو خوانده نشد (فایل خراب است یا فرمتش پشتیبانی نمی‌شود).",
    "no_image": "عکس خوانده نشد.",
    "too_short": "ویدیو کوتاه‌تر از یک ثانیه است.",
    "bad_move": "حرکتِ انتخاب‌شده را سرورِ پردازش نمی‌شناسد.",
    "no_model": "مدلِ لازم هنوز روی سرورِ پردازش نصب نشده؛ نصبِ خودکار ادامه دارد.",
    "memory": "حافظهٔ سرورِ پردازش کم آمد؛ ویدیوی کوتاه‌تر یا با کیفیتِ کمتر امتحان کنید.",
    "encode": "ساختنِ فایلِ ویدیو روی سرورِ پردازش ناموفق بود.",
    "decode": "بخشی از ویدیو خوانده نشد؛ فایل را دوباره بگیرید یا به MP4 تبدیلش کنید.",
}


def error_fa(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.search(r"\[(\w+)\]\s*$", raw.splitlines()[-1] if raw else "")
    if m and m.group(1) in _ERR_FA:
        return _ERR_FA[m.group(1)]
    tail = raw.splitlines()[-1][:160] if raw else ""
    return "ساخت روی سرورِ پردازش ناموفق بود" + (f": {tail}" if tail else ".")


def _label(message: str) -> str:
    """The node's short code («multiangle|render») -> what the owner reads."""
    head, _, rest = (message or "").partition("|")
    if head != "multiangle":
        return message or "سرورِ پردازش…"
    return {"prepare": "آماده‌سازی روی سرورِ پردازش", "analysis": "پیدا کردنِ سوژه و دنبال کردنش", "paths": "طراحیِ حرکتِ دوربین‌ها",
            "render": "ساختنِ زاویه‌ها", "depth": "محاسبهٔ عمقِ صحنه", "upload": "فرستادنِ نتیجه به سایت", "done": "تمام شد"}.get(rest.strip(), "در حالِ ساخت")


def _job(run):
    from apps.compute.models import ComputeJob

    return ComputeJob.objects.filter(uid=run.job_uid).first() if run.job_uid else None


def refresh(run: MultiAngleRun) -> MultiAngleRun:
    """Sync one run with its compute job; a finished job is brought home (once)."""
    from apps.compute import queue as QV
    from apps.compute.models import ComputeJob

    if not run.active:
        return run
    job = _job(run)
    if job is None:
        _fail(run, "کارِ سرورِ پردازش پیدا نشد (شاید پاک شده).")
        return run
    S = ComputeJob.State
    if job.state == S.COMPLETED:
        if run.state == MultiAngleRun.State.INGEST:
            return run                                                  # someone else is bringing it home
        won = MultiAngleRun.objects.filter(pk=run.pk, state__in=(MultiAngleRun.State.QUEUED, MultiAngleRun.State.RUNNING)).update(state=MultiAngleRun.State.INGEST)
        if won:
            run.refresh_from_db()
            try:
                ingest(run, job)
            except MultiAngleError as exc:
                _fail(run, str(exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception("multiangle ingest failed for run %s", run.pk)
                _fail(run, f"آوردنِ نتیجه به سایت ناموفق بود: {str(exc)[:160]}")
        run.refresh_from_db()
        return run
    if job.state == S.FAILED:
        _fail(run, error_fa(job.error))
    elif job.state == S.CANCELLED:
        run.state, run.message = MultiAngleRun.State.CANCELLED, "لغو شد"
        run.save(update_fields=["state", "message", "updated_at"])
    elif job.state == S.QUEUED:
        try:
            text = str(QV.one(job).get("status_text") or "")
        except Exception:  # noqa: BLE001
            text = ""
        run.state, run.progress, run.message = MultiAngleRun.State.QUEUED, 0.0, (waiting_text() or text or "در صف — منتظرِ سرورِ پردازش")[:300]
        run.save(update_fields=["state", "progress", "message", "updated_at"])
    else:
        run.state, run.progress, run.message = MultiAngleRun.State.RUNNING, float(job.progress or 0.0), _label(job.message)[:300]
        run.save(update_fields=["state", "progress", "message", "updated_at"])
    return run


def _fail(run: MultiAngleRun, message: str) -> None:
    run.state, run.error, run.message = MultiAngleRun.State.FAILED, message, "ناموفق"
    run.save(update_fields=["state", "error", "message", "updated_at"])


def cancel(run: MultiAngleRun) -> MultiAngleRun:
    from apps.compute import services as SV

    if not run.active:
        return run
    job = _job(run)
    if job is not None and not job.final:
        SV.cancel(job, "لغو از صفحهٔ چندزاویه")
    run.state, run.message = MultiAngleRun.State.CANCELLED, "لغو شد"
    run.save(update_fields=["state", "message", "updated_at"])
    return run


def delete_run(run: MultiAngleRun) -> None:
    """The run, its files and the clips it added to the store's media."""
    from apps.content.models import UploadedVideo

    cancel(run)
    ids = [v.get("upload") for v in (run.files.get("angles") or {}).values() if isinstance(v, dict) and v.get("upload")]
    for key in ("multicam", "move"):
        item = run.files.get(key)
        if isinstance(item, dict) and item.get("upload"):
            ids.append(item["upload"])
    if run.store_id and ids:
        UploadedVideo.objects.filter(store=run.store, pk__in=ids).delete()
    shutil.rmtree(media_root() / run.dir_rel, ignore_errors=True)
    run.delete()


# ------------------------------------------------------------------ bringing the result home

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _take(job, name: str, dest: Path, big: dict) -> Path:
    """Move one output of the node job into the run's folder (verified when the node sent its size and sha256)."""
    from apps.compute import services as SV

    src = SV.output_path(job, name)
    if not src.is_file() or src.stat().st_size <= 0:
        raise MultiAngleError(f"فایلِ «{name}» از سرورِ پردازش نرسید.")
    meta = big.get(name) or {}
    if meta.get("bytes") and int(meta["bytes"]) != src.stat().st_size:
        raise MultiAngleError(f"اندازهٔ «{name}» با اعلامِ سرورِ پردازش نمی‌خواند.")
    if meta.get("sha256") and _sha256(src) != str(meta["sha256"]).lower():
        raise MultiAngleError(f"فایلِ «{name}» سالم نرسید.")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / name
    shutil.move(str(src), str(out))
    return out


def _add_upload(store, title: str, path: Path, run: MultiAngleRun, role: str):
    """A finished clip -> a row of the store's uploaded videos (so it sits in the editor's bin)."""
    from apps.content.editor_project import _probe
    from apps.content.models import UploadedVideo
    from services.media import files as media

    facts = _probe(path)
    up = UploadedVideo(store=store, title=title[:200], state=UploadedVideo.State.READY, duration=float(facts.get("duration") or 0),
                       has_audio=bool(facts.get("has_audio")),
                       facts={"readable": True, "duration": facts.get("duration"), "has_audio": facts.get("has_audio"), "width": facts.get("width"),
                              "height": facts.get("height"), "fps": facts.get("fps"), "source": "multiangle", "run": run.pk, "role": role})
    media.store(up.video, path, name=f"{run.dir_rel}/{path.name}")
    up.save()
    return up, facts


def ingest(run: MultiAngleRun, job) -> None:
    """The node job is complete: move its files into media, add the clips to the store, keep the plan."""
    from apps.compute import services as SV

    meta = (job.result or {}).get("meta") or {}
    big = meta.get("big") or {}
    dest = media_root() / run.dir_rel
    if run.mode == MultiAngleRun.Mode.SELFTEST:
        p = SV.output_path(job, "selftest.json")
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {"ok": False, "checks": [{"name": "selftest", "ok": False, "detail": "selftest.json نرسید"}]}
        run.checks = doc.get("checks") or []
        run.plan = {"ok": bool(doc.get("ok")), "version": doc.get("version")}
        ok = bool(doc.get("ok"))
        run.state = MultiAngleRun.State.READY if ok else MultiAngleRun.State.FAILED
        run.error = "" if ok else "؛ ".join(f"{ma.CHECK_FA.get(c['name'], c['name'])}: {c.get('detail', '')}" for c in run.checks if not c.get("ok"))[:600]
        run.progress, run.message = 1.0, "گذشت ✓" if ok else "ناموفق"
        run.save()
        shutil.rmtree(SV.job_root(job), ignore_errors=True)
        return
    plan_path = SV.output_path(job, "plan.json")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MultiAngleError("گزارشِ ساخت (plan.json) از سرورِ پردازش نرسید.") from exc
    store = run.store
    files: dict = {}
    src_title = run.params.get("source_title") or "ویدیو"
    if run.mode == MultiAngleRun.Mode.VIRTUAL:
        angles = {}
        for a in plan.get("angles") or []:
            clip = _take(job, a["file"], dest, big)
            prev = _take(job, a["preview"], dest, big) if a.get("preview") else None
            up, facts = _add_upload(store, f"{src_title} — {ma.ANGLE_FA.get(a['key'], a['key'])}", clip, run, a["key"])
            angles[a["key"]] = {"rel": f"{run.dir_rel}/{clip.name}", "preview": f"{run.dir_rel}/{prev.name}" if prev else None, "upload": up.pk,
                                "duration": float(facts.get("duration") or 0), "has_audio": bool(facts.get("has_audio"))}
        files["angles"] = angles
        if plan.get("multicam"):
            clip = _take(job, plan["multicam"], dest, big)
            up, facts = _add_upload(store, f"{src_title} — مولتی‌کمِ خودکار", clip, run, "multicam")
            files["multicam"] = {"rel": f"{run.dir_rel}/{clip.name}", "upload": up.pk, "duration": float(facts.get("duration") or 0)}
    else:
        clip = _take(job, plan.get("file") or "move.mp4", dest, big)
        up, facts = _add_upload(store, f"{src_title} — {ma.MOVE_FA.get(plan.get('move'), 'حرکتِ دوربین')}", clip, run, "move")
        files["move"] = {"rel": f"{run.dir_rel}/{clip.name}", "upload": up.pk, "duration": float(facts.get("duration") or 0)}
        for key in ("preview", "depth"):
            if plan.get(key):
                try:
                    files[key] = f"{run.dir_rel}/{_take(job, plan[key], dest, big).name}"
                except MultiAngleError:
                    pass
    warnings = ma.warnings_fa(plan.get("warnings"))
    if run.params.get("trimmed"):
        warnings.insert(0, ma.warning_text({"code": "trimmed", "seconds": MAX_SECONDS}))
    run.plan, run.files, run.warnings = plan, files, warnings
    run.state, run.progress, run.message, run.error = MultiAngleRun.State.READY, 1.0, "آماده", ""
    run.save()
    shutil.rmtree(SV.job_root(job), ignore_errors=True)


# ------------------------------------------------------------------ the editor

def build_project(run: MultiAngleRun, user=None):
    """The editor project of a finished virtual run: the angles as a multicam group with the automatic cuts already placed."""
    from apps.content import editor_project
    from apps.content.models import VideoProject

    if run.mode != MultiAngleRun.Mode.VIRTUAL or run.state != MultiAngleRun.State.READY:
        raise MultiAngleError("اول ساختِ زاویه‌ها باید تمام شود.")
    angles_files = run.files.get("angles") or {}
    keys = [a["key"] for a in run.plan.get("angles") or [] if a["key"] in angles_files]
    if len(keys) < 2:
        raise MultiAngleError("برای مولتی‌کم دست‌کم دو زاویه لازم است.")
    if run.project_id:
        existing = VideoProject.objects.filter(pk=run.project_id, store=run.store).first()
        if existing is not None:
            return existing
    angles = [{"ref": f"video:{angles_files[k]['upload']}", "label": ma.ANGLE_FA.get(k, k), "duration": angles_files[k]["duration"],
               "has_audio": angles_files[k]["has_audio"]} for k in keys]
    cuts = [{"t": c["t"], "angle": keys.index(c["angle"])} for c in run.plan.get("cuts") or [] if c.get("angle") in keys]
    out = run.plan.get("output") or {}
    data = ma.build_project(angles, cuts, float(out.get("duration") or min(a["duration"] for a in angles)), int(out.get("width") or 1080), int(out.get("height") or 1920),
                            float(out.get("fps") or 30), audio_angle=0)
    verdict = editor_project.check(run.store, data)
    if not verdict.get("ok"):
        raise MultiAngleError("پروژهٔ ادیتور ساخته نشد: " + str(verdict.get("error") or ""))
    project = VideoProject.objects.create(store=run.store, title=(run.title or "چندزاویه")[:200], data=data)
    run.project_id = project.pk
    run.save(update_fields=["project_id", "updated_at"])
    return project


def real_cameras(store, user, refs: list[str], pace: str = "medium") -> dict:
    """Several REAL recordings of one event: lined up by sound, auto-switched on pauses, as an editor project (no processing node needed)."""
    from apps.content import editor_project
    from apps.content.models import VideoProject

    if not (2 <= len(refs) <= 4):
        raise MultiAngleError("دو تا چهار فیلم از یک رویداد انتخاب کنید.")
    for r in refs:
        if not re.fullmatch(r"(video|edited|script):\d+", str(r)):
            raise MultiAngleError("منبع نامعتبر است.")
    with editor_project.sources(store) as resolve:
        infos = [resolve(r) for r in refs]
        if not all(i.get("has_audio") for i in infos):
            raise MultiAngleError("هم‌گام‌سازی با صدا لازم است؛ همهٔ فیلم‌ها باید صدا داشته باشند.")
        paths = [i["path"] for i in infos]
        durations = [float(i["duration"]) for i in infos]
        try:
            plan = ma.plan_real_cameras(paths, durations, pace=_choice(pace, ("slow", "medium", "fast"), "medium"))
        except Exception as exc:  # noqa: BLE001 — multicam.TimelineError (Persian) or an ffmpeg problem
            raise MultiAngleError(str(exc) or "هم‌گام‌سازیِ صدا ناموفق بود.") from exc
    if not all(plan["ok"]):
        raise MultiAngleError("صدای مشترکی بینِ فیلم‌ها پیدا نشد؛ مطمئن شوید همه یک رویداد را ضبط کرده‌اند (و یک کف‌زدن یا صدای مشترک دارند).")
    first = infos[0]
    angles = [{"ref": r, "label": f"دوربین {i + 1}", "duration": durations[i], "has_audio": True, "offset": plan["offsets"][i]} for i, r in enumerate(refs)]
    data = ma.build_project(angles, plan["cuts"], plan["length"], int(first.get("width") or 1920), int(first.get("height") or 1080), 30.0, audio_angle=0)
    verdict = editor_project.check(store, data)
    if not verdict.get("ok"):
        raise MultiAngleError("پروژهٔ ادیتور ساخته نشد: " + str(verdict.get("error") or ""))
    project = VideoProject.objects.create(store=store, title="مولتی‌کمِ چند دوربین (خودکار)", data=data)
    return {"project_id": project.pk, "offsets": plan["offsets"], "cuts": len(plan["cuts"]), "length": plan["length"]}


# ------------------------------------------------------------------ the JSON the page reads

def run_dict(run: MultiAngleRun, *, detail: bool = True) -> dict:
    plan = run.plan or {}
    files = run.files or {}
    angles = []
    for a in plan.get("angles") or []:
        f = (files.get("angles") or {}).get(a["key"]) or {}
        angles.append({"key": a["key"], "label": ma.ANGLE_FA.get(a["key"], a["key"]), "url": media_url(f.get("rel")), "preview": media_url(f.get("preview")),
                       "upload": f.get("upload"), "upscale": (a.get("upscale") or {}).get("median"), "ref": f"video:{f['upload']}" if f.get("upload") else None})
    out = {
        "id": run.pk, "mode": run.mode, "mode_label": run.get_mode_display(), "state": run.state, "state_label": run.get_state_display(), "active": run.active,
        "title": run.title, "progress": round(run.progress or 0.0, 3), "message": run.message, "error": run.error, "created_at": run.created_at,
        "source": run.source_ref, "params": run.params, "project_id": run.project_id, "warnings": run.warnings or [],
        "node": (plan.get("device") or {}),
    }
    if not detail:
        out["thumb"] = next((a["preview"] for a in angles if a["preview"]), media_url(files.get("preview")))
        return out
    multicam = files.get("multicam") or {}
    out.update({
        "angles": angles, "multicam_url": media_url(multicam.get("rel")),
        "cuts": [{"t": s["t0"], "end": s["t1"], "angle": s["angle"], "label": ma.ANGLE_FA.get(s["angle"], s["angle"]), "reason": s.get("reason"),
                  "reason_label": ma.REASON_FA.get(s.get("reason"), "")} for s in plan.get("segments") or []],
        "subject": ma.SUBJECT_FA.get(plan.get("subject_mode") or "", ""), "output": plan.get("output"),
        "skipped": [{"key": k, "label": ma.ANGLE_FA.get(k, k), "why": v} for k, v in (plan.get("skipped_angles") or {}).items()],
        "move": {"url": media_url((files.get("move") or {}).get("rel")), "preview": media_url(files.get("preview")), "depth": media_url(files.get("depth")),
                 "label": ma.MOVE_FA.get(plan.get("move") or "", ""), "safe_zoom": plan.get("safe_zoom"), "upload": (files.get("move") or {}).get("upload"),
                 "ref": f"video:{(files.get('move') or {}).get('upload')}" if (files.get("move") or {}).get("upload") else None} if run.mode == MultiAngleRun.Mode.MOVE else None,
        "checks": _checks_fa(run.checks), "audio": plan.get("audio"), "cut_quality": plan.get("cut_quality"),
    })
    return out
