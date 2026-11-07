"""جداسازیِ پس‌زمینهٔ عکس روی سرورِ پردازش — سه مدل (u2netp، isnet، birefnet-lite) که **فقط روی گره** اجرا می‌شوند.

قرارداد با ادیتورِ عکس (`apps.photoedit`)؛ همهٔ ورودی‌ها فارسی‌اند ولی نام‌ها و کلیدها انگلیسی:

  کار:      kind `photo.matting`، توانایی `photo_matting` (نه `photo`: به سرویسِ .NET ِ عکس وابسته نیست)
  payload:  {"image": "<نامِ فایلِ ورودی>", "model": "u2netp"|"isnet"|"birefnet-lite", "feather": 0, "keep_size": true}
  خروجی:   cutout.png (RGBA، همان اندازه؛ meta.primary)، mask.png (۸بیتی)، photo-matting.json {model, seconds, size, device}
  گزارشِ گره: caps["photo_matting"], caps["matting_models"][key] = {state: installed|downloading|queued|missing|failed,
              size_mb, progress?, error?}, caps["matting_runtime"] = {ok, providers, message?}

مدلی که روی گره نصب نیست **ناموفق نمی‌شود**: `services.claim` کار را تا نصب شدنِ مدل (و آماده بودنِ محیطِ اجرا) به آن گره
نمی‌دهد و کار در صف می‌ماند («منتظرِ دانلودِ مدل»). دانلود از `start_download` (پنلِ کارکنان یا ادیتورِ عکس) و با زمان‌بندیِ
عادیِ دانلودها (پیش‌فرض: بازهٔ شبانه) انجام می‌شود.
"""
from __future__ import annotations

from . import services as SV
from .models import ComputeJob, ComputeNode

KIND = "photo.matting"
CAPABILITY = "photo_matting"
RUNTIME_PACKAGE = "matting-runtime"
MIN_AGENT = (2, 7)

MODELS = {
    "u2netp": {"label": "U²-Net سبک (u2netp)", "mb": 5, "license": "Apache-2.0", "package": "matting-u2netp",
               "note": "خیلی سریع؛ لبه‌ها ساده‌تر"},
    "isnet": {"label": "IS-Net همه‌کاره (isnet-general-use)", "mb": 170, "license": "Apache-2.0", "package": "matting-isnet",
              "note": "حالتِ میانه؛ برای بیشترِ عکس‌ها خوب است"},
    "birefnet-lite": {"label": "BiRefNet سبک (birefnet-lite)", "mb": 224, "license": "MIT", "package": "photo-background",
                      "note": "دقیق‌ترین لبه‌ها (مو، لباسِ نازک)؛ کندتر و رم‌خور"},
}
ORDER = ("u2netp", "isnet", "birefnet-lite")
STATE_LABEL = {"installed": "نصب است", "downloading": "در حالِ دانلود", "queued": "در صفِ دانلود", "missing": "نصب نیست",
               "failed": "دانلود ناموفق بود"}
UPDATE_TEXT = ("نرم‌افزارِ سرورِ پردازش باید به نسخهٔ ۲٫۷ یا بالاتر به‌روز شود: روی آن کامپیوتر Update.bat را اجرا کنید "
               "(یا در پنل «سرورهای پردازش» دکمهٔ «به‌روزرسانی»).")


class MattingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _agent_tuple(node: ComputeNode) -> tuple:
    raw = str((node.capabilities or {}).get("agent") or "")
    out = []
    for part in raw.split(".")[:2]:
        try:
            out.append(int("".join(ch for ch in part if ch.isdigit()) or 0))
        except ValueError:
            out.append(0)
    return tuple(out + [0] * (2 - len(out)))


def node_models(node: ComputeNode) -> dict:
    return (node.capabilities or {}).get("matting_models") or {}


def node_runtime_ok(node: ComputeNode):
    """True / False / None (= the node is still probing its Pythons)."""
    return ((node.capabilities or {}).get("matting_runtime") or {}).get("ok")


def nodes() -> list[ComputeNode]:
    """Enabled nodes whose agent can do photo.matting (2.7+)."""
    return [n for n in ComputeNode.objects.filter(enabled=True) if (n.capabilities or {}).get(CAPABILITY)]


def old_agents() -> list[ComputeNode]:
    return [n for n in ComputeNode.objects.filter(enabled=True)
            if (n.capabilities or {}).get("agent") and not (n.capabilities or {}).get(CAPABILITY) and _agent_tuple(n) < MIN_AGENT]


def status() -> dict:
    """What the photo editor's panel reads: per model installed/downloading/queued/missing/failed (best state over all nodes),
    where it is installed, whether a job could run right now, and what the node still has to do."""
    ns = nodes()
    old = old_agents()
    rank = {"installed": 4, "downloading": 3, "queued": 2, "failed": 1, "missing": 0}
    models = {}
    for key in ORDER:
        meta = MODELS[key]
        best, row = "missing", {}
        installed_on, ready_on = [], []
        for n in ns:
            r = node_models(n).get(key) or {}
            st = r.get("state") or "missing"
            if st == "installed":
                installed_on.append(n.name)
                if n.online and node_runtime_ok(n) is True:
                    ready_on.append(n.name)
            if rank.get(st, 0) > rank[best]:
                best, row = st, r
        out = {"key": key, "label": meta["label"], "size_mb": meta["mb"], "license": meta["license"], "note": meta["note"],
               "state": best, "state_label": STATE_LABEL[best], "installed_on": installed_on, "ready_on": ready_on,
               "ready_now": bool(ready_on), "package": meta["package"]}
        if best == "downloading" and row.get("progress") is not None:
            out["progress"] = row.get("progress")
        if best == "failed":
            out["error"] = str(row.get("error") or "")[:200]
        if best == "missing" and not ns:
            out["state_label"] = "در انتظارِ دانلود روی سرورِ پردازش"
        models[key] = out
    runtime_ok = [n.name for n in ns if node_runtime_ok(n) is True]
    return {
        "models": models, "node_online": any(n.online for n in ns), "nodes": [n.name for n in ns],
        "runtime": {"ok": bool(runtime_ok), "nodes": runtime_ok,
                    "message": "" if runtime_ok else ("محیطِ اجرا (onnxruntime) هنوز روی سرورِ پردازش نیست؛ با دانلودِ مدل خودکار نصب می‌شود."
                                                      if ns else "")},
        "needs_update": [n.name for n in old], "update_text": UPDATE_TEXT if old and not ns else "",
        "message": ("" if ns else (UPDATE_TEXT if old else "هیچ سرورِ پردازشیِ آماده‌ای برای جداسازی ثبت نشده؛ روی کامپیوترِ گرافیکی START.bat را اجرا کنید.")),
    }


def _model(key: str) -> dict:
    if key not in MODELS:
        raise MattingError("مدلِ «%s» را نمی‌شناسم؛ یکی از %s." % (key, "، ".join(ORDER)))
    return MODELS[key]


def request(model: str, source_path: str, *, name: str = "", store=None, feather: float = 0, keep_size: bool = True,
            origin: str = "photomatting", priority: int = 60, dedupe: bool = True) -> ComputeJob:
    """A matting job for one photo; it waits in the queue until a node has the model (never fails because of that)."""
    import os

    meta = _model(model)
    name = os.path.basename(name or source_path) or "photo.jpg"
    try:
        feather = max(0.0, min(40.0, float(feather or 0)))
    except (TypeError, ValueError):
        raise MattingError("feather باید عدد باشد")
    payload = {"image": name, "model": model, "feather": feather, "keep_size": bool(keep_size)}
    try:
        job = SV.enqueue_durable(KIND, payload, {name: str(source_path)}, store=store, origin=origin, priority=priority,
                                 dedupe=dedupe)
    except SV.ComputeUnavailable as exc:
        raise MattingError(UPDATE_TEXT if old_agents() else str(exc), 503) from exc
    _note_wait(job, model)
    return job


def _note_wait(job: ComputeJob, model: str) -> None:
    """The queue message that says what the job waits for (the panel's queue page also derives it live)."""
    if job.state != ComputeJob.State.QUEUED:
        return
    st = status()["models"][model]
    if st["ready_now"]:
        return
    text = ("در صف — منتظرِ دانلودِ مدلِ «%s» روی سرورِ پردازش" % MODELS[model]["label"]) if not st["installed_on"] else \
        "در صف — منتظرِ آماده شدنِ محیطِ اجرای جداسازی روی سرورِ پردازش"
    ComputeJob.objects.filter(pk=job.pk, state=ComputeJob.State.QUEUED).update(message=text)
    job.message = text


def start_test(model: str, node: str = "", origin: str = "photomatting-test") -> ComputeJob:
    """«تست»: the node times the model on a test picture and returns it (waits for the model like any other job)."""
    _model(model)
    try:
        return SV.enqueue_durable(KIND, {"model": model, "bench": True}, {}, origin=origin, priority=40, dedupe=False, node=node or "")
    except SV.ComputeUnavailable as exc:
        raise MattingError(UPDATE_TEXT if old_agents() else str(exc), 503) from exc


def result(job: ComputeJob) -> dict:
    """Paths of a finished job's outputs: {"cutout": Path, "mask": Path, "info": dict|{}}; raises MattingError otherwise."""
    import json

    if job.state != ComputeJob.State.COMPLETED:
        raise MattingError("کار هنوز تمام نشده است")
    out = {}
    for key, fname in (("cutout", "cutout.png"), ("mask", "mask.png")):
        p = SV.output_path(job, fname)
        if not p.is_file():
            raise MattingError("خروجیِ %s پیدا نشد" % fname)
        out[key] = p
    info = {}
    p = SV.output_path(job, "photo-matting.json")
    if p.is_file():
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
    out["info"] = info
    return out


def start_download(models, node: str = "", when=None) -> ComputeJob:
    """دانلودِ مدل‌ها (و محیطِ اجرا، فقط اگر هیچ گره‌ای onnxruntime ندارد) روی گره؛ `when` مثلِ بقیهٔ دانلودها
    ({"mode": "default|now|at|window", "time": "03:30"}؛ پیش‌فرض = بازهٔ شبانه اگر در «زمان‌بندیِ دانلود» روشن باشد)."""
    from . import voice_models

    models = [str(m).strip() for m in (models or []) if str(m).strip()]
    if not models:
        raise MattingError("کدام مدل؟")
    packages = []
    for m in models:
        pkg = _model(m)["package"]
        if pkg not in packages:
            packages.append(pkg)
    ns = nodes()
    if node:
        target = next((n for n in ns if n.name == node), None)
        if target is None:
            raise MattingError("سرورِ «%s» این قابلیت را ندارد (به‌روزرسانی به ۲٫۷ لازم است)" % node, 404)
    else:
        target = next((n for n in ns if n.online), None) or (ns[0] if ns else None)
    if target is None:
        raise MattingError(UPDATE_TEXT if old_agents() else "سرورِ پردازشِ آماده‌ای ثبت نشده؛ START.bat را روی کامپیوترِ گرافیکی اجرا کنید.", 503)
    if node_runtime_ok(target) is False:
        packages.insert(0, RUNTIME_PACKAGE)              # no Python on that node has onnxruntime: make the small environment first
    try:
        return voice_models.start_download(target, packages, when=when)
    except voice_models.VoiceModelsError as exc:
        raise MattingError(str(exc), getattr(exc, "status", 400)) from exc
