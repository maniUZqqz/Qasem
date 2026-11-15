"""تصویرِ نمونهٔ واقعیِ هر سبک: یک موضوعِ ثابتِ بی‌طرف (یک بطریِ ساده، نه آدم) با FLUX روی سرورِ پردازش.

SOURCE: the idea (one fixed neutral subject, queued in chunks, resumable, stored once) is ported from InstAI:instai/styles/previews.py @ 2f8aa90
(``auto_queue``، ``pending``، ``prompt_hash``)، rewritten for NMarketing's compute queue (``comfy.graph`` + صفِ ماندگار) instead of InstAI's own worker.

* کتابخانه همیشه یک «نمونهٔ رنگی» (SVG، ``preview_svg``) دارد؛ این‌جا همان نمونه را با عکسِ واقعیِ مدلِ خودِ مالک جایگزین می‌کنیم تا ببیند سبک واقعاً چه می‌دهد.
* فایل‌ها زیرِ ``data/looks/samples/<سبک>.jpg`` و فهرستِ ``index.json`` (هش دستور ⇒ عکسِ کهنه خودکار دوباره ساخته می‌شود).
* ``auto_step()`` هر ۵ دقیقه از beat: نتیجهٔ کارهای تمام‌شده را برمی‌دارد و اگر چیزی مانده، **دسته‌های ۱۲تایی** در صفِ ماندگار می‌گذارد.
  گره خاموش ⇒ کارها در صف می‌مانند و با روشن‌شدنش خودکار ساخته می‌شوند؛ هیچ دکمه‌ای لازم نیست. اولویتشان از کارهای مالک پایین‌تر است.
* هیچ نوعِ کارِ تازه‌ای در عاملِ گره لازم نیست: همان ``comfy.graph`` ِ تامنیل‌ساز (گرافِ FLUX از توانایی‌های گره).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import time
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import compose, library

logger = logging.getLogger(__name__)

ORIGIN = "looksample"
JOB_KIND = "comfy.graph"
#: بزرگ‌تر = دیرتر (کارهای مالک ۱۰۰ و آزمون‌ها ۴۰ دارند)؛ نمونه‌ها هرگز جلوی کارِ واقعیِ مالک را نمی‌گیرند
PRIORITY = 160
SIZE = (640, 512)                    # مضربِ ۱۶؛ کارتِ منتخب‌گر ۵:۴ است
MIN_STEPS, MAX_STEPS = 12, 22        # FLUX dev روی RTX 3060: حدود یک دقیقه برای هر تصویر؛ ۱۱۶ سبک ≈ دو ساعت، شبانه و بی‌دخالت
TIMEOUT_S = 1500
CHUNK = 12                           # دسته‌ای که هم‌زمان در صف می‌نشیند (حدودِ ۱۰ تا ۱۵ دقیقهٔ GPU)
AUTO_RETRY_H = 6                     # سبکی که ساختنش شکست خورد تا این‌قدر دوباره امتحان نمی‌شود
MIN_STD = 6.0                        # تصویرِ یک‌رنگ/خالی را نپذیر
FILENAME_PREFIX = "nm/looksample"
#: «یک بطریِ ساده»: بدونِ برچسب و نوشته تا فقط سبک‌ها مقایسه شوند، نه موضوع‌ها
SUBJECT = ("a plain unbranded matte white bottle with a plain cap standing on a simple surface, centered, the whole bottle in frame, "
           "no label, no printed text")


class SampleError(Exception):
    """متنش برای کاربر است (فارسی)."""


# ───────────────────────────── مسیرها و فهرست

def root() -> Path:
    return Path(settings.NM_DATA_DIR) / "looks" / "samples"


def sample_path(key: str) -> Path | None:
    if key not in library.STYLES:
        return None
    p = root() / f"{key}.jpg"
    return p if p.is_file() else None


def _index_path() -> Path:
    return root() / "index.json"


def load_index() -> dict:
    try:
        data = json.loads(_index_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_index(index: dict) -> None:
    root().mkdir(parents=True, exist_ok=True)
    tmp = _index_path().with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, _index_path())


def sample_urls() -> dict[str, str]:
    """سبک ⇒ نشانیِ عکسِ واقعی (فقط برای سبک‌هایی که عکسشان ساخته شده)؛ ``?v=`` برای تازه‌شدنِ کَشِ مرورگر."""
    idx = load_index()
    out = {}
    for key in library.STYLES:
        row = idx.get(key)
        if isinstance(row, dict) and row.get("file") and (root() / row["file"]).is_file():
            out[key] = f"{library.API_PREFIX}/{key}/sample.jpg?v={str(row.get('hash', ''))[:8]}"
    return out


# ───────────────────────────── دستور

def seed_for(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % (2 ** 31 - 1) + 1


def prompt_for(key: str) -> tuple[str, str, dict]:
    """(مثبت، منفی، راهنمای گام/هدایت) ⇐ موضوعِ ثابت + دستورِ سبک (نوعِ SAMPLE: بدونِ واژه‌های آدم/چهره/نوشته)."""
    c = compose.compose(key, "SAMPLE")
    return library.join(SUBJECT, c["positive"]), c["negative"], c["hints"]


def steps_for(hints: dict) -> int:
    try:
        n = int(hints.get("steps") or 24)
    except (TypeError, ValueError):
        n = 24
    return max(MIN_STEPS, min(MAX_STEPS, n))


def guidance_for(hints: dict) -> float:
    try:
        g = float(hints.get("guidance") or 3.5)
    except (TypeError, ValueError):
        g = 3.5
    return max(2.0, min(5.0, g or 3.5))


def prompt_hash(key: str) -> str:
    pos, neg, hints = prompt_for(key)
    return hashlib.sha256(f"flux|{pos}|{neg}|{steps_for(hints)}|{guidance_for(hints)}|{SIZE}".encode()).hexdigest()[:20]


def build_payload(key: str, caps=None) -> dict:
    """بارِ کارِ ``comfy.graph`` برای نمونهٔ یک سبک. ``GraphError`` (فارسی) اگر روی گره مدلِ FLUX dev نیست."""
    from apps.thumbs import aibg

    pos, neg, hints = prompt_for(key)
    choice = aibg.txt2img_choice(caps if caps is not None else aibg.node_caps())
    graph = aibg.build_graph(choice, pos, seed_for(key), SIZE, steps=steps_for(hints), guidance=guidance_for(hints), prefix=FILENAME_PREFIX)
    return {"graph": graph, "uploads": [],
            "x_looksample": {"key": key, "hash": prompt_hash(key), "seed": seed_for(key), "size": list(SIZE), "engine": choice["label"],
                             "prompt": pos, "negative": neg}}


# ───────────────────────────── وضعیت و صف

def _jobs():
    from apps.compute.models import ComputeJob

    return ComputeJob.objects.filter(origin=ORIGIN)


def active_jobs():
    from apps.compute.models import ComputeJob

    return _jobs().filter(state__in=(ComputeJob.State.QUEUED, ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING))


def _recently_failed(row, now_ts: float) -> bool:
    return bool(isinstance(row, dict) and row.get("failed_at") and now_ts - float(row["failed_at"]) < AUTO_RETRY_H * 3600)


def pending(keys: list[str] | None = None, force: bool = False) -> list[str]:
    """سبک‌هایی که هنوز عکسِ واقعی ندارند (یا از روی دستورِ کهنه ساخته شده‌اند)؛ همان ترتیبِ مرورِ کتابخانه."""
    idx = load_index()
    now_ts = time.time()
    out = []
    for key in library.STYLES:
        if keys and key not in keys:
            continue
        row = idx.get(key) if isinstance(idx.get(key), dict) else {}
        have = bool(row.get("file")) and (root() / row["file"]).is_file()
        fresh = have and row.get("hash") == prompt_hash(key)
        if fresh and not force:
            continue
        if not force and _recently_failed(row, now_ts):
            continue
        out.append(key)
    return out


def summary() -> dict:
    """شمارشِ سبک (بدونِ پرس‌وجو از سرورِ پردازش؛ برای فهرستِ سبک‌ها): چندتا عکسِ واقعی دارند."""
    done = len(sample_urls())
    return {"total": len(library.STYLES), "done": done, "pending": len(library.STYLES) - done}


def node_state() -> dict:
    """گرهٔ ComfyUI: ثبت‌شده؟ آنلاین؟ مدلِ FLUX dev دارد؟ (برای پنل و برای تصمیمِ صف‌گذاشتن)"""
    try:
        from apps.thumbs import aibg

        return aibg.availability()
    except Exception as exc:  # noqa: BLE001 — اپِ تامنیل‌ساز نیست یا خراب است
        return {"possible": False, "online": False, "model": "", "message": f"ساختِ نمونه ممکن نیست: {str(exc)[:160]}"}


def status() -> dict:
    total = len(library.STYLES)
    todo = pending()
    done = len([k for k in library.STYLES if sample_path(k) is not None])
    act = active_jobs().count()
    node = node_state()
    if not todo:
        msg = "همهٔ تصویرهای نمونه ساخته شده است."
    elif not node.get("possible"):
        msg = node.get("message", "")
    elif act:
        msg = f"{act} تصویرِ نمونه در صفِ سرورِ پردازش است."
    elif node.get("online"):
        msg = "تصویرهای نمونه تا چند دقیقهٔ دیگر خودکار در صف گذاشته می‌شوند."
    else:
        msg = "سرورِ پردازش خاموش است؛ با روشن‌شدنش تصویرهای نمونه خودکار ساخته می‌شوند."
    return {"total": total, "done": done, "pending": len(todo), "active": act, "chunk": CHUNK, "online": bool(node.get("online")),
            "possible": bool(node.get("possible")), "model": node.get("model", ""), "message": msg}


def enqueue_one(key: str, caps=None):
    from apps.compute import services as compute
    from apps.photoedit import inpaint_graph as ig

    payload = build_payload(key, caps)
    have = (caps if caps is not None else _node_caps()).get("comfy_nodes")
    missing = ig.check_nodes(payload["graph"], have)
    if missing:
        raise SampleError("روی سرورِ پردازش این نودهای ComfyUI نصب نیست: " + "، ".join(missing))
    try:
        return compute.enqueue_durable(JOB_KIND, payload, {}, origin=ORIGIN, priority=PRIORITY, timeout_s=TIMEOUT_S, dedupe=False)
    except compute.ComputeUnavailable as exc:
        raise SampleError(str(exc)) from exc


def _node_caps() -> dict:
    from apps.thumbs import aibg

    return aibg.node_caps()


def queue_chunk(keys: list[str] | None = None, *, limit: int = CHUNK, force: bool = False) -> dict:
    """تا ``limit`` تصویرِ نمونه را در صفِ ماندگار می‌گذارد. ⇒ {queued: [...], skipped: why}."""
    from apps.photoedit import inpaint_graph as ig

    todo = pending(keys, force=force)[:max(1, int(limit))]
    if not todo:
        return {"queued": [], "skipped": "nothing"}
    try:
        from apps.thumbs import aibg

        caps = aibg.node_caps()
        aibg.txt2img_choice(caps)
    except ig.GraphError as exc:
        return {"queued": [], "skipped": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"queued": [], "skipped": f"ساختِ نمونه ممکن نیست: {str(exc)[:160]}"}
    queued, errors = [], []
    for key in todo:
        try:
            queued.append({"look": key, "job": str(enqueue_one(key, caps).uid)})
        except (SampleError, ig.GraphError) as exc:
            errors.append(str(exc))
            break
    return {"queued": queued, "skipped": errors[0] if errors and not queued else ""}


# ───────────────────────────── برداشتنِ نتیجه

def _store_image(key: str, src: Path, meta: dict, job) -> dict:
    """عکسِ خروجیِ گره ⇒ JPEG در data/looks/samples؛ ``SampleError`` اگر خراب/یک‌رنگ است."""
    import numpy as np
    from PIL import Image

    try:
        with Image.open(src) as im:
            im.load()
            img = im.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise SampleError(f"فایلِ تصویر خوانده نشد: {exc}") from exc
    if float(np.asarray(img.convert("L"), dtype=np.float32).std()) < MIN_STD:
        raise SampleError("تصویرِ ساخته‌شده خالی یا یک‌رنگ است.")
    if img.width > SIZE[0]:
        img = img.resize((SIZE[0], round(img.height * SIZE[0] / img.width)), Image.Resampling.LANCZOS)
    root().mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88, optimize=True)
    out = root() / f"{key}.jpg"
    tmp = out.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, out)
    took = (job.finished_at - job.claimed_at).total_seconds() if (job.finished_at and job.claimed_at) else None
    return {"file": out.name, "hash": meta.get("hash", ""), "job": str(job.uid), "at": timezone.now().isoformat(), "bytes": len(buf.getvalue()),
            "engine": meta.get("engine", ""), "seconds": round(took, 1) if took is not None else None, "size": list(img.size)}


def harvest(limit: int = 400) -> dict:
    """کارهای تمام‌شده ⇒ فایلِ نمونه؛ کارهای ناموفق ⇒ ثبتِ شکست (تا چند ساعت دوباره امتحان نمی‌شود). تکرارپذیر."""
    from apps.compute.models import ComputeJob
    from apps.photoedit import services as photo

    idx = load_index()
    stored, failed = [], []
    rows = _jobs().filter(state__in=(ComputeJob.State.COMPLETED, ComputeJob.State.FAILED)).order_by("-finished_at", "-created_at")[:limit]
    for job in rows:
        meta = (job.payload or {}).get("x_looksample") or {}
        key = meta.get("key")
        if key not in library.STYLES:
            continue
        row = idx.get(key) if isinstance(idx.get(key), dict) else {}
        if job.state == ComputeJob.State.FAILED:
            if row.get("failed_job") != str(job.uid) and row.get("job") != str(job.uid):
                have_newer = row.get("file") and row.get("at") and job.finished_at and row["at"] >= job.finished_at.isoformat()
                if not have_newer:
                    row = {**row, "failed_at": time.time(), "failed_job": str(job.uid), "error": (job.error or "")[:240]}
                    idx[key] = row
                    failed.append(key)
            continue
        if row.get("job") == str(job.uid) or (row.get("file") and row.get("hash") == meta.get("hash") and (root() / row["file"]).is_file()):
            continue
        _out, path = photo._image_output(job)
        if path is None or not Path(path).is_file():
            continue
        try:
            idx[key] = _store_image(key, Path(path), meta, job)
            stored.append(key)
        except SampleError as exc:
            idx[key] = {**row, "failed_at": time.time(), "failed_job": str(job.uid), "error": str(exc)[:240]}
            failed.append(key)
    if stored or failed:
        save_index(idx)
    return {"stored": stored, "failed": failed}


def auto_step() -> dict:
    """یک گامِ خودکار (beat هر ۵ دقیقه): نتیجه‌ها را بردار؛ اگر کاری در صف نیست و نمونه‌ای مانده، دستهٔ بعدی را بگذار."""
    if os.environ.get("NM_LOOKS_SAMPLES_AUTO", "1") == "0":
        return {"action": "off"}
    got = harvest()
    if active_jobs().exists():
        return {"action": "wait", **got}
    todo = pending()
    if not todo:
        return {"action": "idle", **got}
    res = queue_chunk(limit=CHUNK)
    return {"action": "enqueued" if res["queued"] else "skip", "why": res.get("skipped", ""), "queued": len(res["queued"]), **got}


# ───────────────────────────── آزمون / توسعه

def finish_for_test(job, node=None, *, size=None, error: str = "", flat: bool = False):
    """آزمون/توسعه: نقشِ گرهٔ ComfyUI را بازی می‌کند (مثلِ ``thumbs.aibg.finish_for_test``): کار را برمی‌دارد، یک تصویرِ رنگیِ
    بافت‌دار (یا ``flat``: یک‌رنگ) با اندازهٔ خواسته می‌سازد و مثلِ عامل تمامش می‌کند."""
    import numpy as np
    from PIL import Image

    from apps.compute import services as compute
    from apps.compute.models import ComputeNode
    from apps.thumbs import aibg

    node = node or ComputeNode.objects.filter(enabled=True).first() or ComputeNode.objects.create(
        name="gpu-fake", last_seen=timezone.now(), capabilities=aibg.fake_caps())
    job.node, job.state, job.attempts = node, job.State.RUNNING, job.attempts + 1
    job.claimed_at = job.heartbeat_at = timezone.now()
    job.save()
    if error:
        return compute.finish(job, node, False, error=error, meta={"retryable": False})
    meta = (job.payload or {}).get("x_looksample") or {}
    w, h = size or tuple(meta.get("size") or (512, 512))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if flat:
        arr = np.full((h, w, 3), 128, dtype=np.uint8)
    else:
        arr = np.stack([60 + 150 * xx / w, 40 + 120 * yy / h, 160 - 90 * xx / w], axis=2)
        arr = (arr + np.random.RandomState(7).randint(-9, 10, size=arr.shape)).clip(0, 255).astype(np.uint8)       # دانهٔ تصویر: PNG واقعی‌تر (بزرگ‌تر از ۱۰ کیلوبایت)
    name = "looksample_00001_.png"
    Image.fromarray(arr).save(compute.output_path(job, name), "PNG")
    return compute.finish(job, node, True, meta={"primary": name, "engine": "comfyui"})
