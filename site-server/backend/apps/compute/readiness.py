"""«آمادگیِ صبحِ مالک» — فقط‌خواندنی، بی‌دست‌زدن به گره (۱۴۰۵/۰۸/۲۳).

یک گزارشِ واحد که می‌گوید اگر همین حالا گره را روشن کنند همه‌چیز خودش پیش می‌رود یا چه چیزی گیر می‌کند:

  بسته       بستهٔ کدِ سایت (نسخه) هر فایلِ requirements.d و ماژول‌های نصبِ خودکار را دارد؛ نسخهٔ بسته با agent.py یکی است
  آینه       هر فایلِ بزرگی که گره از خودِ سایت می‌گیرد (Blender، Node.js، مدل‌ها، بستهٔ آباگرام و موشن …) روی سایت هست و اندازه‌اش می‌خورد
  دانلود     تنظیمِ زمانِ دانلود؛ نصبِ نخستِ هر ویژگی (requirements.d) به آن بسته نیست
  خودکارها   به‌روزرسانیِ خودکار، آزمونِ خودکار پس از هر نسخه، آزمونِ شبانه، بازگرداندنِ کارهای ناموفق
  آزمون‌ها   هر ویژگیِ درخواستِ مالک آزمونِ پذیرش دارد (REQUIRED)
  گره        روشن؟ نسخه؟ به‌روزرسانی در راه است؟ آخرین اجرای آزمون؟ نصب‌های ناموفق؟
  صف         کارهای منتظر: کدام با آمدنِ گره خودشان اجرا می‌شوند، کدام منتظرِ به‌روزرسانی یا نصب‌اند

`python manage.py node_readiness [--json]` و `GET /api/v1/compute/readiness/` (کارکنان) همین را می‌دهند.
هر ردیف: {"key", "label", "state": ok|warn|fail|info, "detail"}؛ `ok` کلِ گزارش = هیچ ردیفِ fail نیست."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from django.utils import timezone

from . import autopilot
from . import services as SV
from . import updates as U
from .models import ComputeJob, ComputeNode, ComputeSettings

#: ویژگی‌های درخواستِ مالک ⇐ کلیدِ آزمون‌هایی که باید در فهرستِ آزمونِ پذیرش باشند (tests_catalog.py هم همین را می‌سنجد)
REQUIRED = {
    "اتصال صف ⇒ گره": ["echo"],
    "کارت گرافیک": ["gpu"],
    "ffmpeg / NVENC": ["ffmpeg_nvenc"],
    "Ollama (متن و بینایی)": ["ollama_text", "ollama_vision"],
    "ComfyUI / FLUX": ["comfy_flux"],
    "جداسازیِ پس‌زمینهٔ عکس": ["matting"],
    "ویرایشگرِ عکس": ["photo_edit"],
    "گفتار (TTS)": ["tts_piper", "tts_moss"],
    "تشخیصِ گفتار (ASR)": ["asr_vosk", "asr_gpu"],
    "رندرِ نهاییِ ویرایشگر": ["edit_render"],
    "چندزاویه": ["multiangle"],
    "استودیوی موشن (رندرِ ۳ ثانیه‌ای)": ["motion_studio"],
    "تدوینِ خودکار": ["autoedit_words", "autoedit_mix", "autoedit_matte"],
    "تامنیل‌ساز (پس‌زمینهٔ هوش مصنوعی)": ["thumbs_bg"],
    "ترندیاب اینستاگرام (آباگرام)": ["ig_health"],
    "ویدیوی سه‌بعدی (up3d)": ["up3d_stage"],
    "محتوای چغر": ["chagher_content"],
    "سایت‌ساز (سبک‌ها و قطعه‌ها)": ["site_styles_ai", "site_styles_render"],
    "دانلودِ مدل‌ها": ["model_catalog", "model_catalog_download"],
    "نصبِ خودکار و به‌روزرسانی": ["bootstrap", "update_flow"],
}

#: ماژول‌هایی که نصبِ خودکار و به‌روزرسانی به آن‌ها تکیه دارد و باید در بسته باشند
MUST_SHIP = ("agent.py", "update.py", "bootstrap.py", "nm_fetch.py", "autostart.py", "instance_lock.py", "selftest_jobs.py", "START.bat")

SITE_NAME = re.compile(r"3d/files/downloads/([A-Za-z0-9][A-Za-z0-9._-]{2,120}\.[A-Za-z0-9]{2,5})")


def _row(key, label, state, detail="", **extra):
    return {"key": key, "label": label, "state": state, "detail": detail, **extra}


def _version_of(processing: Path) -> str:
    try:
        for line in (processing / "agent.py").read_text(encoding="utf-8").splitlines():
            if line.startswith("VERSION = "):
                return line.split('"')[1]
    except (OSError, IndexError):
        pass
    return ""


def mirror_names(processing: Path) -> dict:
    """{نامِ فایل: اندازهٔ اعلام‌شده یا None} برای هر فایلی که گره از خودِ سایت می‌گیرد (از requirements.d، مانیفست‌های مدل و بستهٔ موشن)."""
    names: dict = {}
    for path in sorted((processing / "requirements.d").glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        def walk(o):
            if isinstance(o, dict):
                for k in ("site", "from_site"):
                    if isinstance(o.get(k), str):
                        names.setdefault(o[k], None)
                for src in o.get("sources") or []:                       # the size of an archive / file is declared next to its sources
                    if isinstance(src, dict) and isinstance(src.get("site"), str) and o.get("size"):
                        names[src["site"]] = o["size"]
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(spec)
        for it in spec.get("items") or []:
            if it.get("type") == "ffmpeg-nvenc" and not it.get("sources"):
                names.setdefault(it.get("from_site") or "kit-ffmpeg.zip", None)
    for path in list((processing / "downloads").glob("*.json")) + list((processing / "requirements.d").glob("*.json")) + [processing / "abagram_jobs.py"]:
        try:
            for name in SITE_NAME.findall(path.read_text(encoding="utf-8")):
                names.setdefault(name, None)
        except OSError:
            pass
    try:                                                                 # abagram: WHEEL_PACK / CHROMIUM_PACK are constants
        text = (processing / "abagram_jobs.py").read_text(encoding="utf-8")
        for name in re.findall(r'(?:WHEEL_PACK|CHROMIUM_PACK)\s*=\s*"([^"]+)"', text):
            names.setdefault(name, None)
    except OSError:
        pass
    motion = U.downloads_dir() / "nm-motion-pack.json"
    try:
        m = json.loads(motion.read_text(encoding="utf-8"))
        names.setdefault("nm-motion-pack.json", None)
        for part in ("pack", "node", "browser"):
            if (m.get(part) or {}).get("name"):
                names[m[part]["name"]] = m[part].get("size")
    except (OSError, ValueError):
        pass
    return {k: v for k, v in names.items() if k and not k.endswith("...")}


def package_rows(processing: Path) -> list:
    rows = []
    try:
        manifest = U.current_manifest(max_age=60.0)
    except Exception as exc:  # noqa: BLE001
        return [_row("package", "بستهٔ کدِ گره", "fail", "بسته ساخته نشد: %s" % exc)]
    files = {f["path"] for f in manifest.get("files") or []}
    version = _version_of(processing)
    state = "ok" if manifest.get("version") == version else "fail"
    rows.append(_row("package", "بستهٔ کدِ گره", state, "نسخهٔ %s · %s فایل · %.1f مگابایت%s" % (
        manifest.get("version"), manifest.get("count"), (manifest.get("zip_size") or 0) / 1e6,
        "" if state == "ok" else " — نسخهٔ agent.py %s است" % version)))
    missing = [n for n in MUST_SHIP if n not in files]
    wanted = sorted(p.name for p in (processing / "requirements.d").glob("*.json"))
    missing += ["requirements.d/%s" % n for n in wanted if "requirements.d/%s" % n not in files]
    rows.append(_row("package_files", "بسته شاملِ نصبِ خودکار و نیازمندی‌هاست", "fail" if missing else "ok",
                     ("در بسته نیست: " + "، ".join(missing)) if missing else "%d فایلِ requirements.d و %d ماژولِ نصب/به‌روزرسانی" % (len(wanted), len(MUST_SHIP))))
    return rows


def mirror_rows(processing: Path) -> list:
    have = {r["name"]: r["size"] for r in U.list_downloads()}
    names = mirror_names(processing)
    missing = sorted(n for n in names if n not in have)
    wrong = sorted(n for n, size in names.items() if n in have and size and int(size) != int(have[n]))
    detail = "%d فایل روی سایت" % (len(names) - len(missing))
    state = "ok"
    if missing or wrong:
        state = "fail"
        detail = "؛ ".join(x for x in (("روی سایت نیست: " + "، ".join(missing)) if missing else "", ("اندازه نمی‌خواند: " + "، ".join(wrong)) if wrong else "") if x)
    return [_row("mirror", "فایل‌های بزرگی که گره از خودِ سایت می‌گیرد (آینه)", state, detail, files=len(names))]


def download_rows() -> list:
    cfg = ComputeSettings.get()
    if cfg.download_mode == "window":
        return [_row("download", "زمانِ دانلود", "info", "فقط در بازهٔ %s (وقتِ تهران) — ولی نصبِ نخستِ هر ویژگیِ requirements.d به بازه بسته نیست؛ "
                                                       "فقط مدل‌های چندگیگابایتی و نصبِ دوباره منتظرِ بازه می‌مانند" % cfg.download_window)]
    return [_row("download", "زمانِ دانلود", "ok", "هر وقت (بدونِ بازه)؛ نصبِ نخستِ هر ویژگی در هر حال فوری است")]


def automation_rows() -> list:
    cfg = ComputeSettings.get()
    rows = []
    for key, label, on in (("auto_update", "به‌روزرسانیِ خودکارِ گره", cfg.auto_update), ("auto_selftest", "آزمونِ پذیرش پس از هر نسخهٔ تازه", cfg.auto_selftest),
                           ("nightly_selftest", "آزمونِ شبانه (%s)" % cfg.nightly_time, cfg.nightly_selftest),
                           ("requeue_after_pass", "بازگرداندنِ کارهای ناموفقِ ناشی از گره پس از قبولیِ آزمون", cfg.requeue_after_pass)):
        rows.append(_row(key, label, "ok" if on else "warn", "روشن" if on else "خاموش — صبحِ مالک این کار دستی می‌شود"))
    return rows


def catalog_rows() -> list:
    from .selftests import REGISTRY, load_all

    load_all()
    gaps = {f: [k for k in keys if k not in REGISTRY] for f, keys in REQUIRED.items()}
    gaps = {f: ks for f, ks in gaps.items() if ks}
    return [_row("catalog", "هر ویژگی آزمونِ پذیرش دارد", "fail" if gaps else "ok",
                 ("بی‌آزمون: " + "؛ ".join("%s (%s)" % (f, "، ".join(ks)) for f, ks in gaps.items())) if gaps else "%d آزمون، %d ویژگی پوشیده است" % (len(REGISTRY), len(REQUIRED)))]


def _forecast(node: ComputeNode) -> dict:
    """کارهای منتظرِ این گره: چند تا با آمدنِ گره اجرا می‌شوند، چند تا منتظرِ به‌روزرسانی یا نصب‌اند."""
    out = {"ready": Counter(), "needs_update": Counter(), "installing": Counter(), "parked": 0}
    qs = ComputeJob.objects.filter(state=ComputeJob.State.QUEUED)
    for job in qs.iterator():
        if job.kind == "wait.node":
            out["parked"] += 1
            continue
        if job.node_wanted and job.node_wanted != node.name:
            continue
        if SV.kind_unsupported(node, job):
            out["needs_update"][job.kind] += 1
        elif SV.job_blocked(node, job):
            out["installing"][job.kind] += 1
        else:
            out["ready"][job.kind] += 1
    return out


def node_rows(node: ComputeNode) -> list:
    from .models_platform import SelfTestRun

    caps = node.capabilities or {}
    rows = []
    age = (timezone.now() - node.last_seen).total_seconds() if node.last_seen else None
    if node.online:
        rows.append(_row("node_online", "گره «%s» روشن است" % node.name, "ok", "آخرین ارتباط %d ثانیه پیش" % age))
    else:
        rows.append(_row("node_online", "گره «%s» روشن است" % node.name, "warn",
                         ("خاموش؛ آخرین ارتباط %.1f ساعت پیش" % (age / 3600)) if age is not None else "هرگز وصل نشده",
                         last_seen=node.last_seen.isoformat() if node.last_seen else ""))
    latest = U.latest()
    wanted, why = autopilot.update_wanted(node)
    state = U.update_state(caps, latest)
    if not caps.get("agent"):
        rows.append(_row("node_agent", "نسخهٔ عاملِ گره", "warn", "گره هنوز نسخه‌اش را نگفته است"))
    elif state.get("update_waiting"):
        sendable = wanted and node.online
        rows.append(_row("node_agent", "نسخهٔ عاملِ گره", "warn" if not sendable else "info",
                         "گره %s است و بستهٔ سایت %s؛ %s" % (caps.get("agent"), latest.get("version"),
                                                           "به‌محضِ روشن بودن، سایت خودش دستورِ به‌روزرسانی را می‌فرستد" if wanted else why)))
    else:
        rows.append(_row("node_agent", "نسخهٔ عاملِ گره", "ok", "%s، با بستهٔ سایت یکی است" % caps.get("agent")))
    boot = caps.get("bootstrap") or {}
    summary = boot.get("summary") or {}
    failed = sorted(name for name, f in (boot.get("features") or {}).items() if f.get("state") == "failed")
    if failed:
        rows.append(_row("node_bootstrap", "نصبِ خودکارِ نیازمندی‌ها", "fail", "ناموفق: " + "، ".join(failed)))
    elif boot:
        rows.append(_row("node_bootstrap", "نصبِ خودکارِ نیازمندی‌ها", "ok" if not (summary.get("installing") or summary.get("waiting")) else "info",
                         ", ".join("%s=%s" % kv for kv in sorted(summary.items())) or "گزارش رسیده"))
    else:
        rows.append(_row("node_bootstrap", "نصبِ خودکارِ نیازمندی‌ها", "info", "گره هنوز گزارشِ نصب نداده (عاملِ پیش از ۲٫۱۱ یا خاموش)"))
    run = SelfTestRun.objects.filter(node=node).order_by("-id").first()
    if run is None:
        rows.append(_row("node_selftest", "آخرین آزمونِ پذیرش", "info", "هنوز اجرا نشده؛ با روشن شدنِ گره (نسخهٔ تازه) خودکار شروع می‌شود"))
    else:
        counts = Counter(run.results.values_list("state", flat=True))
        bad = counts.get("FAILED", 0)
        rows.append(_row("node_selftest", "آخرین آزمونِ پذیرش", "fail" if bad else ("info" if run.state == "RUNNING" else "ok"),
                         "اجرای %s (%s) با عاملِ %s — %s" % (run.pk, run.trigger, run.agent_version or "؟", "، ".join("%s %d" % kv for kv in sorted(counts.items())))))
    fc = _forecast(node)
    parts = []
    if fc["ready"]:
        parts.append("%d کار با آمدنِ گره اجرا می‌شود (%s)" % (sum(fc["ready"].values()), "، ".join("%s×%d" % kv for kv in sorted(fc["ready"].items()))))
    if fc["needs_update"]:
        parts.append("%d کار منتظرِ به‌روزرسانیِ عامل است (%s)" % (sum(fc["needs_update"].values()), "، ".join("%s×%d" % kv for kv in sorted(fc["needs_update"].items()))))
    if fc["installing"]:
        parts.append("%d کار منتظرِ پایانِ نصب است (%s)" % (sum(fc["installing"].values()), "، ".join("%s×%d" % kv for kv in sorted(fc["installing"].items()))))
    if fc["parked"]:
        parts.append("%d کارِ «منتظرِ روشن شدنِ گره» (هر دقیقه بیدار می‌شوند)" % fc["parked"])
    rows.append(_row("node_queue", "کارهای منتظرِ گره", "info", "؛ ".join(parts) or "صف خالی است",
                     ready=dict(fc["ready"]), needs_update=dict(fc["needs_update"]), installing=dict(fc["installing"]), parked=fc["parked"]))
    return rows


def report(node: ComputeNode | None = None) -> dict:
    processing = U.source_dir()
    rows = []
    rows += package_rows(processing)
    rows += mirror_rows(processing)
    rows += download_rows()
    rows += automation_rows()
    rows += catalog_rows()
    nodes = [node] if node is not None else list(ComputeNode.objects.filter(enabled=True))
    for n in nodes:
        rows += [dict(r, node=n.name) for r in node_rows(n)]
    counts = Counter(r["state"] for r in rows)
    return {"ok": not counts.get("fail"), "summary": dict(counts), "checks": rows, "at": timezone.now().isoformat()}
