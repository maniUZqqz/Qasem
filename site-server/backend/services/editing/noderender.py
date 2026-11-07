"""The final render — and, when it is heavy and cheap to move, the quick draft — on the processing node (the owner's GPU PC) when it is
online. §23.4 (which drafts go there is decided by `placement.py`; a draft that is not worth the trip is rendered on the site)

The site builds the SAME filtergraph it would run itself — `compose.build_graph(..., portable=True)` — and hands the node a
job (`edit.render`, kind prefix `edit.` ⇒ capability «ffmpeg»):

    payload = {graph, inputs: [{file, args}], texts: {token: ASS}, assets: {token: file id}, fonts: [file ids],
               audio, audio_args, encode: {cpu, nvenc}, files: {id: {name, size, sha256}}, selftest, out}

The node downloads every file it does not already hold (HTTP Range, resumes after each break, size + sha256 checked,
cached by sha256 so the second export of a project downloads nothing), substitutes the tokens with its own paths, runs
ffmpeg (NVENC when its card can, else x264/x265) and uploads the result in resumable chunks. Titles come out identical
because the node renders with the same Vazirmatn (and the other bundled families) and proves it first: it lays a Persian
test line out with libass and compares the ink pixels with the number the site measured.

This module is the SITE half: choosing the node, building the payload, waiting (mirroring progress, honouring cancel,
giving up when the node is silent or never picks the job up) and bringing the file home. Whatever goes wrong raises
`NodeUnavailable` / `NodeFailed` and `render_project_task` renders on the site instead — a node that is off or broken
never costs the shop their video.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import compose, export, placement, titles
from .errors import TimelineError

logger = logging.getLogger(__name__)

KIND = "edit.render"
OUT_NAME = "render.mp4"
#: a job the node has not picked up after this long is taken back (it is busy, or its agent is old)
QUEUE_GRACE = 75.0
#: a running job whose node has been silent this long is given up
SILENT_LIMIT = 300.0
POLL = 1.5
#: how often the waiting render asks the queue what to tell the owner
QUEUE_LABEL_EVERY = 5.0
_SHA_CACHE: dict[tuple, str] = {}


class NodeUnavailable(Exception):
    """No node can take this render now (offline, too old, missing a filter, never picked it up) — render on the site."""


class NodeFailed(Exception):
    """The node took the job and it failed, timed out or came back wrong — render on the site."""


def _sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _SHA_CACHE:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if len(_SHA_CACHE) > 400:
            _SHA_CACHE.clear()
        _SHA_CACHE[key] = h.hexdigest()
    return _SHA_CACHE[key]


def queue_text(cjob) -> str:
    """The Persian status of a render that waits in the processing queue («در صف — منتظرِ روشن شدنِ سرورِ پردازش»، «در صف — نفرِ ۲ام»…)."""
    try:
        from apps.compute import queue as QV

        return str(QV.one(cjob).get("status_text") or "") or "در صف — منتظرِ سرورِ پردازش"
    except Exception:  # noqa: BLE001 — the label is a courtesy
        return "در صف — منتظرِ سرورِ پردازش"


# ------------------------------------------------------------------ choosing the node

def pick_node():
    """→ (node | None, reason). A node qualifies when it is online, has ffmpeg with every filter the editor uses and
    reports `edit.render`."""
    try:
        from apps.compute import services as compute
    except Exception:  # noqa: BLE001
        return None, "بخشِ سرورهای پردازش در این فرایند نیست."
    nodes = compute.online_nodes("ffmpeg")
    if not nodes:
        return None, "هیچ سرورِ پردازشی روشن نیست."
    for node in nodes:
        edit = (node.capabilities or {}).get("edit") or {}
        if edit.get("render"):
            return node, ""
    edit = (nodes[0].capabilities or {}).get("edit") or {}
    if edit.get("missing"):
        return None, "ffmpegِ سرورِ پردازش این فیلترها را ندارد: " + "، ".join(edit["missing"][:6])
    return None, "سرورِ پردازش هنوز آماده نیست (نسخهٔ عاملش قدیمی است یا ffmpeg پیدا نشد)؛ Update.bat را اجرا کنید."


def status() -> dict:
    node, why = pick_node()
    if node is None:
        return {"online": False, "message": why, "node": "", "nvenc": False}
    edit = (node.capabilities or {}).get("edit") or {}
    return {"online": True, "message": "", "node": node.name, "nvenc": bool((edit.get("nvenc") or {}).get("h264")),
            "gpu": (node.capabilities or {}).get("gpu", "")}


# ------------------------------------------------------------------ fonts

_FONT_FILES: list[Path] | None = None


def font_files() -> list[Path]:
    """The font files the titles may use: the bundled Vazirmatn plus whatever the other families resolve to here
    (`fc-match`). Shipped with the job so Windows lays the text out with the same glyphs."""
    global _FONT_FILES
    if _FONT_FILES is not None:
        return _FONT_FILES
    found: dict[str, Path] = {}
    for p in sorted(Path(titles.FONTS_DIR).glob("*.ttf")):
        found[p.name] = p
    for spec in titles.FONTS.values():
        for style in ("", ":bold"):
            try:
                out = subprocess.run(["fc-match", "-f", "%{file}", spec["family"] + style], capture_output=True, text=True, timeout=10,
                                     stdin=subprocess.DEVNULL).stdout.strip()
            except Exception:  # noqa: BLE001 — no fontconfig (a dev machine): the bundled fonts only
                continue
            if out and Path(out).is_file() and Path(out).suffix.lower() in (".ttf", ".otf") and Path(out).name not in found:
                found[Path(out).name] = Path(out)
    _FONT_FILES = list(found.values())
    return _FONT_FILES


# ------------------------------------------------------------------ the ASS self-test (does the node lay text out like the site?)

SELFTEST_ITEM = {"text": "سلام دنیا ABC ۱۲۳", "at": 0, "duration": 1, "size": 30, "bold": True, "color": "#ffffff", "box": False,
                 "x": 0.5, "y": 0.5, "stroke": 0, "shadow": 0}
_SELFTEST: dict | None = None


def ink(raw: bytes, w: int, h: int) -> dict:
    """{"count", "x0", "x1", "y0", "y1"} of the pixels brighter than 128 in a raw gray frame."""
    xs0, xs1, ys0, ys1, n = w, -1, h, -1, 0
    for i, b in enumerate(raw[: w * h]):
        if b > 128:
            n += 1
            x, y = i % w, i // w
            if x < xs0:
                xs0 = x
            if x > xs1:
                xs1 = x
            if y < ys0:
                ys0 = y
            if y > ys1:
                ys1 = y
    return {"count": n, "x0": xs0, "x1": xs1, "y0": ys0, "y1": ys1}


def selftest() -> dict | None:
    """The test line laid out by THIS machine's libass (cached): the ASS text and the ink it must produce on the node."""
    global _SELFTEST
    if _SELFTEST is not None:
        return _SELFTEST or None
    from services.video.ffmpeg import FFMPEG, filter_path

    W, H = 320, 120
    ass = titles.build_ass([SELFTEST_ITEM], W, H)
    with tempfile.TemporaryDirectory(prefix="nm-selftest-") as tmp:
        f = Path(tmp) / "t.ass"
        f.write_text(ass, encoding="utf-8")
        try:
            raw = subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r=10:d=1",
                                  "-vf", f"ass=filename={filter_path(f)}:fontsdir={filter_path(titles.FONTS_DIR)},format=gray",
                                  "-ss", "0.3", "-frames:v", "1", "-f", "rawvideo", "-"],
                                 capture_output=True, timeout=60, stdin=subprocess.DEVNULL).stdout
        except Exception:  # noqa: BLE001
            raw = b""
    if len(raw) < W * H:
        _SELFTEST = {}
        return None
    _SELFTEST = {"ass": ass, "w": W, "h": H, "expect": ink(raw, W, H), "count_tol": 0.12, "width_tol": 0.04, "at": 0.3}
    return _SELFTEST


# ------------------------------------------------------------------ the job

@dataclasses.dataclass
class Bundle:
    payload: dict
    files: dict            # fid -> {"path", "size", "sha256", "name"}  (kept on the site, never sent)
    length: float
    size: tuple
    spec: object | None


def build(timeline, export_block: dict | None, *, profile: str = "final") -> Bundle:
    """The job for this timeline, built exactly like `export.render` builds its command. `profile="draft"` is the quick draft:
    the project's own size, x264 veryfast crf 27 and 160 kbit/s sound — what `export.render(quality="draft")` does on the site."""
    from services.video.ffmpeg import AUDIO_DELIVERY, VIDEO_DELIVERY

    draft = profile == "draft"
    spec = export.resolve(export_block, timeline) if export_block and not draft else None
    work = timeline
    if spec is not None:
        w, h = export.size_for(timeline, spec.short_side)
        work = dataclasses.replace(timeline, width=w, height=h, fps=spec.fps or timeline.fps)
    built = compose.build_graph(work, portable=True, alpha=bool(spec is not None and spec.codec == "prores4444"))
    files: dict[str, dict] = {}
    by_path: dict[str, str] = {}

    def fid_for(path, *, name: str | None = None) -> str:
        key = str(path)
        if key in by_path:
            return by_path[key]
        p = Path(path)
        if not p.is_file():
            raise TimelineError(f"فایلِ «{p.name}» برای رندر روی سرورِ پردازش پیدا نشد.")
        fid = f"f{len(files)}"
        files[fid] = {"path": str(p), "size": p.stat().st_size, "sha256": _sha256(p), "name": name or p.name}
        by_path[key] = fid
        return fid

    inputs = [{"file": fid_for(src), "args": list(args)} for src, args in zip(built.inputs, built.input_args)]
    assets = {token: fid_for(path) for token, path in built.assets.items()}
    fonts = [fid_for(p) for p in font_files()] if built.texts else []
    spec_for_encode = spec or export.ExportSpec()
    out_name = "render.mov" if export.is_prores(spec_for_encode) else OUT_NAME      # ProRes lives in a .mov
    if draft:
        spec_for_encode = export.ExportSpec(preset="veryfast", crf=27, audio_kbps=160)
        audio_args = ["-c:a", "aac", "-b:a", f"{spec_for_encode.audio_kbps}k", "-ar", "48000"]
        cpu = export.encode_args(spec_for_encode, draft=True)
    elif spec is not None:
        audio_args = export.audio_args_for(spec)
        cpu = export.encode_args(spec)
    else:
        audio_args, cpu = list(AUDIO_DELIVERY), list(VIDEO_DELIVERY)
    payload = {
        "v": 1, "graph": built.graph, "inputs": inputs, "texts": built.texts, "assets": assets, "fonts": fonts,
        "audio": built.has_audio, "audio_args": audio_args, "length": built.length, "out": out_name,
        "encode": {"cpu": cpu, "nvenc": cpu if export.is_prores(spec_for_encode) else export.nvenc_args(spec_for_encode), "codec": spec_for_encode.codec},
        "files": {fid: {"name": f["name"], "size": f["size"], "sha256": f["sha256"]} for fid, f in files.items()},
        "notes": list(built.notes), "size": [work.width, work.height],
    }
    if built.texts:
        test = selftest()
        if test:
            payload["selftest"] = test
    return Bundle(payload, files, built.length, (work.width, work.height), spec)


def _label(message: str) -> str:
    """The node's short status code → what the shop reads («پیام|…»)."""
    head, _, rest = (message or "").partition("|")
    parts = rest.split("|") if rest else []
    if head == "download":
        return f"سرورِ پردازش در حالِ دریافتِ فایل‌ها ({parts[0]} از {parts[1]})" if len(parts) >= 2 else "سرورِ پردازش در حالِ دریافتِ فایل‌هاست"
    if head == "render":
        return "رندر روی سرورِ پردازش" + (f" ({parts[0]})" if parts else "")
    if head == "upload":
        return "ارسالِ خروجی از سرورِ پردازش به سایت"
    if head == "selftest":
        return "سنجشِ هم‌شکلی متنِ فارسی روی سرورِ پردازش"
    if head == "prepare":
        return "آماده‌سازیِ سرورِ پردازش"
    return message or "سرورِ پردازش…"


def node_busy(node) -> bool:
    """The node is working on (or has just claimed) a job: a draft sent now would wait behind it."""
    try:
        return node.jobs.filter(state__in=("CLAIMED", "RUNNING")).exists()
    except Exception:  # noqa: BLE001 — a doubt means «busy»: the draft stays on the site
        return True


def node_cache(node) -> list | None:
    """The 16-hex sha256 prefixes of the originals the node says it holds, or None when its agent does not report them yet."""
    cache = ((node.capabilities or {}).get("edit") or {}).get("cache")
    return list(cache) if isinstance(cache, list) else None


def plan_draft(timeline):
    """Where should this quick draft be rendered? → (placement.Decision, Bundle | None). Cheap first: a light draft (or no usable
    node) is decided without reading a single file; only a heavy one builds the job (which hashes the originals) to learn what
    the node would still have to download."""
    est = placement.estimate_site_seconds(timeline)
    node, _why = pick_node()
    if node is None:
        return placement.decide(est, node_online=False), None
    if est <= placement.HEAVY_SITE_SECONDS:
        return placement.decide(est, node_online=True), None
    if node_busy(node):
        return placement.decide(est, node_online=True, node_busy=True), None
    try:
        bundle = build(timeline, None, profile="draft")
    except TimelineError:
        return placement.Decision("server", "unreadable", est), None
    out_bytes = placement.estimate_output_bytes(bundle.length, bundle.size[0], bundle.size[1], timeline.fps)
    left = placement.uncached_bytes(bundle.files, node_cache(node))
    return placement.decide(est, node_online=True, uncached_bytes=left, out_bytes=out_bytes), bundle


def render_on_node(job_row, timeline, export_block, dest, *, progress=None, cancel=None, store=None, profile: str = "final",
                   bundle: Bundle | None = None, budget: float | None = None, queue_grace: float | None = None, patient: bool = False) -> dict:
    """Render `timeline` on a node into `dest`. `progress(fraction, label)` / `cancel()` as in `export.render`.
    `profile="draft"` renders the quick draft (a `bundle` already built by `plan_draft`, a `budget` in seconds and a short
    `queue_grace` may be given). → {"where": "node", "node", "encoder", "seconds", "ffmpeg"}.
    `patient=True` is the FINAL render: it waits in the durable queue for as long as it takes for a node to claim it (no give-up, no fall-back to
    the site); once claimed the run clock starts and a node that goes away just sends the job back to the queue.
    Raises NodeUnavailable / NodeFailed / export.RenderCancelled."""
    from apps.compute import services as compute
    from apps.compute import transfer

    node, why = pick_node()
    if node is None:
        raise NodeUnavailable(why)
    if bundle is None:
        try:
            bundle = build(timeline, export_block, profile=profile)
        except TimelineError as exc:
            raise NodeUnavailable(str(exc)) from exc
    length = max(1.0, bundle.length)
    total_bytes = sum(f["size"] for f in bundle.files.values())
    budget = int(budget) if budget else int(900 + length * 40 + total_bytes / 1_000_000 * 4)
    grace = QUEUE_GRACE if queue_grace is None else queue_grace
    try:
        # held for a moment (node_wanted names nobody) so the node cannot claim it before its files are registered
        cjob = compute.enqueue(KIND, bundle.payload, None, store=store, origin="video-editor-render", timeout_s=budget,
                               node="__hold__", dedupe=False, require_online=False)
    except compute.ComputeError as exc:
        raise NodeUnavailable(str(exc)) from exc
    cjob.max_attempts = 1                       # the site falls back by itself; the node must not retry a render
    cjob.node_wanted = node.name
    transfer.register_assets(cjob, bundle.files)
    cjob.save(update_fields=["max_attempts", "node_wanted"])
    started = time.monotonic()
    last_p, last_msg = -1.0, ""
    claim_stamp, run_started, queue_label_t, queue_label = None, started, 0.0, ""
    try:
        while True:
            cjob.refresh_from_db()
            if cancel is not None and cancel():
                compute.cancel(cjob)
                raise export.RenderCancelled()
            state = cjob.state
            now = time.monotonic()
            if state == cjob.State.COMPLETED:
                break
            if state == cjob.State.FAILED:
                raise NodeFailed(cjob.error or "رندر روی سرورِ پردازش ناموفق بود.")
            if state == cjob.State.CANCELLED:
                raise NodeFailed("کار روی سرورِ پردازش لغو شد.")
            if state == cjob.State.QUEUED and patient:
                if progress is not None and now - queue_label_t > QUEUE_LABEL_EVERY:         # «در صف — منتظرِ روشن شدنِ سرور» / «نفرِ ۲ام»
                    queue_label_t = now
                    text = queue_text(cjob)
                    if text != queue_label:
                        queue_label = text
                        progress(0.0, text)
            elif state == cjob.State.QUEUED and now - started > grace:
                compute.cancel(cjob)
                raise NodeUnavailable("سرورِ پردازش کار را برنداشت (مشغول است یا عاملش جواب نمی‌دهد).")
            if state != cjob.State.QUEUED:
                silent = (cjob.heartbeat_at and (time.time() - cjob.heartbeat_at.timestamp())) or 0
                if patient:
                    if cjob.claimed_at != claim_stamp:                       # a (new) node took it: the run clock starts now
                        claim_stamp, run_started = cjob.claimed_at, now
                    alive = bool(cjob.node is not None and cjob.node.online)
                    if alive and (silent > SILENT_LIMIT or now - run_started > budget):
                        compute.cancel(cjob)
                        raise NodeFailed("سرورِ پردازش در زمانِ مقرر رندر را تمام نکرد.")
                    # the node is gone: the queue takes the job back (apps.compute requeue) and it waits for the next one
                elif silent > SILENT_LIMIT or now - started > budget:
                    compute.cancel(cjob)
                    raise NodeFailed("سرورِ پردازش در زمانِ مقرر رندر را تمام نکرد.")
            if progress is not None and (cjob.progress != last_p or cjob.message != last_msg):
                last_p, last_msg = cjob.progress, cjob.message
                progress(min(0.99, max(0.0, cjob.progress)), _label(cjob.message))
            time.sleep(POLL)
        out = compute.output_path(cjob, str(bundle.payload.get("out") or OUT_NAME))
        meta = (cjob.result or {}).get("meta") or {}
        if not out.is_file() or out.stat().st_size <= 0:
            raise NodeFailed("سرورِ پردازش خروجی نفرستاد.")
        if meta.get("bytes") and int(meta["bytes"]) != out.stat().st_size:
            raise NodeFailed("اندازهٔ خروجیِ رسیده با اعلامِ سرورِ پردازش نمی‌خواند.")
        if meta.get("sha256") and _sha256(out) != str(meta["sha256"]).lower():
            raise NodeFailed("خروجیِ رسیده از سرورِ پردازش سالم نیست (sha256).")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dest))
        return {"where": "node", "node": node.name, "encoder": str(meta.get("encoder") or ""), "seconds": meta.get("render_seconds"),
                "ffmpeg": str(meta.get("ffmpeg") or ""), "bytes": dest.stat().st_size}
    except (NodeUnavailable, NodeFailed, export.RenderCancelled):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("node render failed")
        compute.cancel(cjob)
        raise NodeFailed(str(exc)) from exc
    finally:
        try:                                    # the job's folder holds copies/links of nothing big; drop it either way
            shutil.rmtree(compute.job_root(cjob), ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
