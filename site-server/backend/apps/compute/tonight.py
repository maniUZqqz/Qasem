# -*- coding: utf-8 -*-
"""«امشب: روشن کردنِ سرورِ پردازش» (۱۴۰۵/۰۸/۲۸) — یک گزارشِ زنده برای مالک: چه می‌شود، الان کجاییم، چه چیزی قرمز است.

سناریو: مالک شب کامپیوترِ گرافیکی را روشن می‌کند و همه‌چیز باید خودش پیش برود:

    ۱ روشن شدنِ گره  ⇒  ۲ به‌روزرسانیِ خودکارِ نرم‌افزارِ گره (از هر نسخهٔ قدیمی)  ⇒  ۳ نصبِ خودکارِ نیازمندی‌ها (requirements.d)
    ⇒  ۴ مدل‌های Ollama و ComfyUI  ⇒  ۵ آزمونِ خودکارِ هر ویژگی  ⇒  ۶ اجرای خودکارِ کارهای منتظر  ⇒  ۷ درخواست‌های هوشِ مصنوعیِ در صف

این ماژول هیچ‌چیز را عوض نمی‌کند و به گره درخواست نمی‌فرستد؛ فقط از داده‌های موجود (دستورِ آخر، caps ِ ضربان، اجرای آزمون، صف) یک تصویر می‌سازد
(`build`) و چند «تلاشِ دوباره» (`retry`) را به همان ابزارهای موجود می‌سپارد. هر بخش جدا try/except دارد: خرابیِ یکی بقیه را نمی‌اندازد.

هر ردیف: {"key", "title", "state": todo|doing|done|warn|fail|skip, "detail", ...}.
وضعیت‌ها: todo = هنوز شروع نشده · waiting = منتظرِ روشن شدنِ سرورِ پردازش (کار/درخواست در صف است یا چیزی برای انجام نبوده؛ هنوز «انجام شد» نیست) ·
doing = در جریان · done = تمام و سالم · warn = نیازِ شما یا نیمه‌کاره · fail = قرمز (دلیل و دکمهٔ «دوباره» دارد) · skip = برای این سیستم نیست.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from django.utils import timezone

from . import autopilot, bootstrap_fa
from . import commands as C
from . import queue as QV
from . import readiness
from . import services as SV
from . import updates as U
from .models import ComputeJob, ComputeNode, ComputeSettings, SelfTestRun

logger = logging.getLogger(__name__)

_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n) -> str:
    return str(n).translate(_FA)


def _mb(n) -> str:
    n = float(n or 0)
    if n >= 1e9:
        return "%s گیگابایت" % fa(("%.1f" % (n / 1e9)).replace(".", "٫"))
    return "%s مگابایت" % fa(int(round(n / 1e6)))


def _row(key, title, state, detail="", **extra) -> dict:
    return {"key": key, "title": title, "state": state, "detail": detail, **extra}


# ───────────────────────────── انتخابِ گره

def pick_node(pk=None) -> ComputeNode | None:
    """گرهٔ مالک: همان که خواسته شد؛ وگرنه آنلاین‌ترین (تازه‌ترین ضربان) بینِ گره‌های فعال."""
    if pk:
        return ComputeNode.objects.filter(pk=pk).first()
    nodes = list(ComputeNode.objects.filter(enabled=True))
    if not nodes:
        return None
    nodes.sort(key=lambda n: (not n.online, -(n.last_seen.timestamp() if n.last_seen else 0)))
    return nodes[0]


# ───────────────────────────── آنچه قرار است نصب شود (از requirements.d؛ حتی وقتی گره خاموش است)

def _declared_bytes(spec: dict) -> int:
    total = 0

    def walk(o):
        nonlocal total
        if isinstance(o, dict):
            if o.get("type") in ("archive", "files") and not o.get("files") and o.get("size"):
                total += int(o["size"])
            for f in o.get("files") or []:
                if isinstance(f, dict) and f.get("size"):
                    total += int(f["size"])
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for it in spec.get("items") or []:
        walk(it)
    return total


def planned_features(processing: Path | None = None) -> list[dict]:
    """[{feature, title, order, kinds, needs_gpu, platform, bytes, requires}] — همان فایل‌هایی که با بستهٔ کد به گره می‌رسند، به ترتیبِ نصب."""
    processing = processing or U.source_dir()
    out = []
    for path in sorted((processing / "requirements.d").glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        title = spec.get("title_fa") or spec.get("title") or spec.get("feature") or path.stem
        out.append({"feature": spec.get("feature") or path.stem, "title": title, "order": int(spec.get("order") or 100),
                    "kinds": list(spec.get("kinds") or []), "needs_gpu": bool(spec.get("needs_gpu")),
                    "platform": list(spec.get("platform") or []), "bytes": _declared_bytes(spec), "requires": list(spec.get("requires") or [])})
    motion = motion_planned()
    if motion:
        out.append(motion)
    out.sort(key=lambda f: (f["order"], f["feature"]))
    return out


MOTION_ORDER = 35          # بعد از Node.js قابل‌حمل (۳۰)؛ بستهٔ موشن Node.js ِ خودش را هم دارد


def motion_planned() -> dict | None:
    """بستهٔ موشن (رندرر Remotion + Node.js + مرورگرِ بی‌سر) که ماژولِ موشنِ خودِ گره (motion_jobs.py) با «اولین ضربان» خودش از آینهٔ سایت
    می‌گیرد؛ requirements.d نیست ولی همان نصبِ خودکار است و باید با بقیه در فهرستِ «چه نصب می‌شود» دیده شود (اندازه از nm-motion-pack.json)."""
    try:
        m = json.loads((U.downloads_dir() / "nm-motion-pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    total = sum(int((m.get(part) or {}).get("size") or 0) for part in ("pack", "node", "browser"))
    return {"feature": "motion", "title": MOTION_TITLE, "order": MOTION_ORDER, "kinds": ["motion.render"], "needs_gpu": False, "platform": ["win"], "bytes": total, "requires": []}


MOTION_TITLE = "استودیوی موشن: Node.js، رندرر و مرورگر"


# ───────────────────────────── بخش‌ها

def power_row(node) -> dict:
    if node is None:
        return _row("power", "روشن شدنِ سرورِ پردازش", "fail", "هیچ سرورِ پردازشی ثبت نیست (ابزارها ⇒ سرورهای پردازش ⇒ «ثبتِ سرورِ تازه»).")
    age = (timezone.now() - node.last_seen).total_seconds() if node.last_seen else None
    if node.online:
        return _row("power", "سرورِ پردازش «%s» روشن است" % node.name, "done", "آخرین ارتباط %s ثانیه پیش" % fa(int(age or 0)),
                    node=node.name, node_id=node.pk, last_seen=node.last_seen.isoformat() if node.last_seen else "")
    if age is None:
        detail = "هرگز وصل نشده؛ کامپیوترِ گرافیکی را روشن کنید و START.bat را یک بار اجرا کنید."
    else:
        days = age / 86400
        detail = "خاموش؛ آخرین ارتباط %s پیش" % (("%s روز" % fa(int(days))) if days >= 1 else ("%s ساعت" % fa(int(age // 3600))))
        detail += ". کامپیوتر را روشن کنید (برنامه با ورود به ویندوز خودش بالا می‌آید؛ اگر نیامد، START.bat را یک بار بزنید)."
    return _row("power", "سرورِ پردازش «%s» را روشن کنید" % node.name, "todo", detail, node=node.name, node_id=node.pk,
                last_seen=node.last_seen.isoformat() if node.last_seen else "")


def update_row(node) -> dict:
    title = "به‌روزرسانیِ خودکارِ نرم‌افزارِ گره"
    latest = U.latest()
    if node is None:
        return _row("update", title, "todo", "")
    caps = node.capabilities or {}
    have = caps.get("agent") or "؟"
    want = latest.get("version") or "؟"
    st = U.update_state(caps, latest)
    cfg = ComputeSettings.get()
    wanted, why = autopilot.update_wanted(node, cfg)
    if not node.online:
        if st.get("update_waiting"):
            return _row("update", title, "todo", "گره الان نسخهٔ %s دارد و بستهٔ سایت %s است؛ با روشن شدنِ گره، سایت خودش دستورِ به‌روزرسانی را می‌فرستد "
                        "(و START.bat هم هنگامِ شروع همین کار را می‌کند)." % (fa(have), fa(want)), have=have, want=want)
        return _row("update", title, "done" if caps.get("agent") else "todo",
                    ("گره آخرین بار با بستهٔ سایت یکی بود (%s)." % fa(have)) if caps.get("agent") else "", have=have, want=want)
    if not st.get("update_waiting"):
        return _row("update", title, "done", "نسخهٔ گره %s است و با بستهٔ سایت یکی است." % fa(have), have=have, want=want)
    auto = autopilot.NodeAuto.of(node)
    tries = auto.update_tries if auto.update_pkg == latest.get("id") else 0
    if wanted:
        return _row("update", title, "doing", "گره %s است و بستهٔ سایت %s؛ دستورِ به‌روزرسانی فرستاده شد/می‌شود (تلاش %s از %s). تا چند دقیقهٔ دیگر "
                    "گره خودش راه‌اندازی می‌شود." % (fa(have), fa(want), fa(tries), fa(autopilot.MAX_AUTO_TRIES)), have=have, want=want, tries=tries,
                    action="update")
    return _row("update", title, "fail", "%s. با «به‌روزرسانیِ دوباره» یا با Update.bat روی کامپیوترِ گرافیکی انجام دهید." % why, have=have, want=want, tries=tries,
                action="update")


_FSTATE = {"ready": "done", "installing": "doing", "waiting": "doing", "failed": "fail", "skipped": "skip", "idle": "todo"}
_MOTION = {"ready": "done", "installing": "doing", "waiting": "doing", "checking": "doing", "failed": "fail", "disabled": "skip"}


def extra_rows(caps: dict) -> list[dict]:
    """چیزهایی که خودِ گره نصب/روشن می‌کند ولی در requirements.d نیستند (هرکدام ماژولِ خودش را دارد و در ضربان گزارش می‌دهد):
    بستهٔ موشن (Node.js + رندرر + مرورگر)، بررسیِ FLUX برای شخصیتِ برند، ComfyUI و Ollama."""
    rows: list[dict] = []
    motion = caps.get("motion")
    if isinstance(motion, dict) and motion:
        state = _MOTION.get(str(motion.get("state") or ""), "todo")
        prog = motion.get("progress")
        rows.append(_row("install:motion", "استودیوی موشن: Node.js، رندرر و مرورگر", state,
                         str(motion.get("message") or motion.get("step") or ("آماده است" if state == "done" else "")), feature="motion", kinds=["motion.render"],
                         progress=prog if isinstance(prog, (int, float)) and state == "doing" else None))
    bc = caps.get("brandchar")
    if isinstance(bc, dict) and bc:
        ok = bc.get("ready") is True
        rows.append(_row("install:brandchar-flux", "شخصیتِ برند: پروفایلِ FLUX و فایلِ مدل برای ComfyUI", "done" if ok else "warn",
                         "آماده است" if ok else str(bc.get("note") or bc.get("message") or "پروفایل یا فایلِ مدلِ FLUX کنارِ ComfyUI پیدا نشد؛ کارهای brandchar.render در صف می‌مانند "
                                                   "(بسته‌های FLUX را از «دانلودِ مدل‌ها» به انتخابِ خودتان بیاورید)."), feature="brandchar-flux", kinds=["brandchar.render"]))
    if "comfyui" in caps:
        rows.append(_row("install:comfyui", "ComfyUI (تصویر و ویدیو)", "done" if caps.get("comfyui") else "warn",
                         "روشن است" if caps.get("comfyui") else "هنوز روشن نیست؛ برنامه run_nvidia_gpu.bat را خودش پیدا و اجرا می‌کند (یا NM_COMFY_BAT را بگذارید)", feature="comfyui"))
    if "ollama" in caps:
        models = caps.get("ollama_models") or []
        rows.append(_row("install:ollama", "Ollama (متن و بینایی)", "done" if caps.get("ollama") else "warn",
                         ("روشن است؛ مدل‌ها: " + "، ".join(models)) if caps.get("ollama") else "هنوز روشن نیست؛ برنامه `ollama serve` را خودش راه می‌اندازد", feature="ollama"))
    return rows


def installs_rows(node, planned: list[dict]) -> tuple[dict, list[dict]]:
    """(ردیفِ کلی، ردیفِ هر ویژگی). گره گزارشِ نصب داده ⇒ وضعیتِ واقعی؛ وگرنه فهرستِ برنامه‌ریزی‌شده."""
    caps = (node.capabilities or {}) if node else {}
    boot = bootstrap_fa.translate(caps.get("bootstrap") or {})
    feats = (boot or {}).get("features") or {}
    rows: list[dict] = []
    if feats and node is not None and node.online:
        order = {f["feature"]: f["order"] for f in planned}
        for name, f in sorted(feats.items(), key=lambda kv: (order.get(kv[0], 100), kv[0])):
            state = _FSTATE.get(f.get("state"), "todo")
            items = [{"id": i.get("id"), "title": i.get("title"), "state": _FSTATE.get(i.get("state"), "todo"), "progress": i.get("progress"),
                      "detail": i.get("detail") or "", "error": i.get("error") or "", "tries": i.get("tries") or 0, "tail": i.get("tail") or []}
                     for i in f.get("items") or []]
            prog = [i["progress"] for i in items if isinstance(i.get("progress"), (int, float))]
            detail = f.get("why") or ""
            bad = [i for i in items if i["state"] == "fail"]
            if bad:
                detail = "؛ ".join("%s: %s" % (i["title"], i["error"] or i["detail"] or "ناموفق") for i in bad)[:400]
            elif state == "doing":
                busy = [i for i in items if i["state"] == "doing"]
                detail = ("%s — %s" % (busy[0]["title"], busy[0]["detail"] or "در حال نصب")) if busy else (detail or "منتظرِ نوبت (پیش‌نیاز)")
            elif state == "done":
                detail = "آماده است"
            rows.append(_row("install:%s" % name, f.get("title") or name, state, detail, feature=name, items=items, kinds=f.get("kinds") or [],
                             progress=(sum(prog) / len(prog)) if prog and state == "doing" else None))
        rows += extra_rows(caps)
        if not any(r["key"] == "install:motion" for r in rows):
            mp = motion_planned()                          # عاملِ قدیمی هنوز ماژولِ موشن را گزارش نمی‌دهد؛ بعد از به‌روزرسانی با اولین ضربان شروع می‌شود
            if mp:
                rows.append(_row("install:motion", mp["title"], "todo", "بعد از به‌روزرسانیِ نرم‌افزارِ گره، با اولین ضربان خودش شروع می‌شود (حدود %s)." % _mb(mp["bytes"]),
                                 feature="motion", kinds=mp["kinds"], bytes=mp["bytes"]))
        c = Counter(r["state"] for r in rows)
        if rows and c.get("skip") == len(rows):
            return _row("installs", "نصبِ خودکارِ نیازمندی‌ها", "skip", "هیچ‌کدام از ویژگی‌ها برای سیستم‌عاملِ این گره نیست (نصبِ خودکار فقط روی ویندوز است)."), rows
        if c.get("fail"):
            head = _row("installs", "نصبِ خودکارِ نیازمندی‌ها", "fail", "%s مورد ناموفق (خودش بعد از ۱۰ دقیقه، ۳۰ دقیقه، ۹۰ دقیقه و ۴ ساعت دوباره تلاش می‌کند)." % fa(c["fail"]),
                        action="bootstrap")
        elif c.get("doing"):
            head = _row("installs", "نصبِ خودکارِ نیازمندی‌ها", "doing", "%s ویژگی در حالِ نصب یا منتظرِ نوبت، %s آماده." % (fa(c["doing"]), fa(c.get("done", 0))))
        else:
            head = _row("installs", "نصبِ خودکارِ نیازمندی‌ها", "done", "%s ویژگی آماده است." % fa(c.get("done", 0)))
        return head, rows
    # پیش از روشن شدن (یا عاملِ قدیمی که گزارشِ نصب نمی‌دهد): فهرستِ برنامه‌ریزی‌شده
    for f in planned:
        det = ""
        if f["bytes"]:
            det = "حدود %s دانلود" % _mb(f["bytes"])
        if f["requires"]:
            det += ("؛ " if det else "") + "بعد از: " + "، ".join(f["requires"])
        rows.append(_row("install:%s" % f["feature"], f["title"], "todo", det, feature=f["feature"], kinds=f["kinds"], bytes=f["bytes"]))
    total = sum(f["bytes"] for f in planned)
    old = bool(node and node.online and not caps.get("bootstrap"))
    head = _row("installs", "نصبِ خودکارِ نیازمندی‌ها", "todo",
                "%s ویژگی نصب می‌شود (حدودِ %s فایلِ ثابت از آینهٔ سایت؛ بسته‌های پایتون جدا از PyPI می‌آیند). %s" % (
                    fa(len(planned)), _mb(total), "گره هنوز گزارشِ نصب نداده (نسخهٔ قدیمی؛ بعد از به‌روزرسانی شروع می‌شود)." if old else ""))
    return head, rows


def models_row(node) -> dict:
    """مدل‌های Ollama برای چهار نوعِ کارِ هوش مصنوعی + ComfyUI. مدل‌های مالک تغییر نمی‌کنند؛ فقط می‌سنجیم کدام جواب می‌دهد."""
    title = "هوش مصنوعیِ روی کارت: مدل‌های Ollama و ComfyUI"
    caps = (node.capabilities or {}) if node else {}
    try:
        from services.ai import priority, routing
    except Exception as exc:  # noqa: BLE001
        return _row("models", title, "warn", "مسیریابِ هوش مصنوعی خوانده نشد (%s)." % exc.__class__.__name__)
    kinds = []
    ok_n = 0
    for kind in priority.KINDS:
        st = routing.node_state(kind)
        model = st.get("model") or st.get("wanted") or ""
        has = bool(st.get("has_model"))
        if has:
            ok_n += 1
        kinds.append({"kind": kind, "label": priority.KIND_LABEL.get(kind, kind), "model": model, "installed": has,
                      "substitute": st.get("substitute") or "", "reason": "" if has else (st.get("reason") or "")})
    models = list(caps.get("ollama_models") or [])
    comfy = bool(caps.get("comfyui"))
    online = bool(node and node.online)
    if not online:
        return _row("models", title, "todo", "پس از روشن شدن بررسی می‌شود. آخرین فهرستِ مدل‌های گره: %s." % ("، ".join(models) or "نامعلوم"),
                    kinds=kinds, models=models, comfyui=comfy)
    state = "done" if ok_n == len(kinds) and comfy else ("warn" if ok_n else "fail")
    parts = ["%s از %s نوعِ کارِ متنی/بینایی مدلِ آماده دارد" % (fa(ok_n), fa(len(kinds)))]
    parts.append("ComfyUI %s" % ("روشن است" if comfy else "هنوز روشن نیست (برنامه خودش سعی می‌کند بالایش بیاورد)"))
    return _row("models", title, state, "؛ ".join(parts) + ".", kinds=kinds, models=models, comfyui=comfy)


def selftests_rows(node) -> tuple[dict, list[dict]]:
    title = "آزمونِ خودکارِ هر ویژگی"
    run = None
    if node is not None:
        from .selftests import runner

        run = runner.latest_run(node)
    if run is None:
        head = _row("selftests", title, "todo", "پس از به‌روزرسانی و نصب، سایت خودش برای هر ویژگی یک کارِ واقعیِ کوچک به گره می‌فرستد و نتیجه را می‌سنجد.")
        return head, []
    results = {r.key: r for r in run.results.all()}
    rows = []
    for feature, keys in readiness.REQUIRED.items():
        have = [results[k] for k in keys if k in results]
        if not have:
            rows.append(_row("test:%s" % feature, feature, "todo", "در این اجرا نیست", keys=keys))
            continue
        states = [r.state for r in have]
        failed = [r for r in have if r.state == "FAILED" and not r.optional]
        if failed:
            state, detail = "fail", "؛ ".join("%s: %s" % (r.label, (r.detail or "رد شد")[:160]) for r in failed)
        elif any(s in ("PENDING", "WAITING", "QUEUED", "RUNNING") for s in states):
            waiting = [r for r in have if r.state in ("PENDING", "WAITING", "QUEUED", "RUNNING")]
            state, detail = "doing", "؛ ".join("%s: %s" % (r.label, (r.detail or r.get_state_display())[:120]) for r in waiting)
        elif all(s == "SKIPPED" for s in states):
            state, detail = "warn", "اجرا نشد: " + (have[0].detail or "")[:200]
        else:
            state = "done"
            detail = "؛ ".join("%s ✓" % r.label for r in have if r.state == "PASSED")[:300]
            skipped = [r for r in have if r.state == "SKIPPED"]
            if skipped:
                state = "warn"
                detail += (" — اجرا نشد: " + "؛ ".join("%s (%s)" % (r.label, (r.detail or "")[:90]) for r in skipped))[:300]
        rows.append(_row("test:%s" % feature, feature, state, detail, keys=keys, results=[{"key": r.key, "label": r.label, "state": r.state} for r in have]))
    c = Counter(r.state for r in results.values())
    bad = c.get("FAILED", 0)
    busy = sum(c.get(s, 0) for s in ("PENDING", "WAITING", "QUEUED", "RUNNING"))
    if run.state == SelfTestRun.State.RUNNING or busy:
        state = "doing"
    else:
        state = "fail" if bad else "done"
    detail = "اجرای %s (%s) با عاملِ %s — قبول %s، رد %s، در جریان %s، اجرا نشد %s" % (
        fa(run.pk), {"version": "پس از نسخهٔ تازه", "online": "پس از روشن شدن", "nightly": "شبانه", "manual": "دستی", "deep": "عمیق"}.get(run.trigger, run.trigger),
        fa(run.agent_version or "؟"), fa(c.get("PASSED", 0)), fa(bad), fa(busy), fa(c.get("SKIPPED", 0)))
    return _row("selftests", title, state, detail, run=run.pk, counts=dict(c), action="selftest"), rows


def queue_rows(node) -> tuple[dict, list[dict]]:
    """کارهای منتظر به تفکیکِ ویژگی: «با آمدنِ گره اجرا می‌شود» / «منتظرِ به‌روزرسانی» / «منتظرِ نصب» + شمارِ تمام‌شده و ناموفقِ ۲۴ ساعت."""
    title = "اجرای خودکارِ کارهای منتظر"
    from . import sched

    prog = sched.progress_by_kind().get("kinds") or {}
    off_line = node is None or not node.online
    fc = readiness._forecast(node) if node is not None else {"ready": Counter(), "needs_update": Counter(), "installing": Counter(), "parked": 0}
    kinds = sorted(set(prog) | set(fc["ready"]) | set(fc["needs_update"]) | set(fc["installing"]))
    rows = []
    for kind in kinds:
        if kind == "wait.node":
            continue
        p = prog.get(kind) or {}
        queued = p.get("queued", 0)
        running = p.get("running", 0)
        done = p.get("done", 0)
        failed = p.get("failed", 0)
        if not (queued or running or done or failed):
            continue
        parts = []
        if fc["ready"].get(kind):
            parts.append("%s کار با آمدنِ گره اجرا می‌شود" % fa(fc["ready"][kind]))
        if fc["needs_update"].get(kind):
            parts.append("%s کار منتظرِ به‌روزرسانیِ عامل" % fa(fc["needs_update"][kind]))
        if fc["installing"].get(kind):
            parts.append("%s کار منتظرِ پایانِ نصب" % fa(fc["installing"][kind]))
        if running:
            parts.append("%s در حالِ اجرا" % fa(running))
        if done:
            parts.append("%s تمام شد" % fa(done))
        if failed:
            parts.append("%s ناموفق" % fa(failed))
        state = "fail" if failed and not (queued or running) else ("doing" if queued or running else "done")
        if state == "doing" and not running and off_line:
            state = "waiting"                      # گره خاموش است: «در جریان» نیست، منتظرِ روشن شدن است
        rows.append(_row("queue:%s" % kind, QV.kind_label(kind), state, "؛ ".join(parts), kind=kind, queued=queued, running=running, done=done, failed=failed))
    tot = Counter()
    for r in rows:
        for k in ("queued", "running", "done", "failed"):
            tot[k] += r[k]
    parked = int(fc.get("parked") or 0)
    detail = "%s در صف، %s در حالِ اجرا، %s تمام‌شده و %s ناموفق (۲۴ ساعتِ اخیر)" % (fa(tot["queued"]), fa(tot["running"]), fa(tot["done"]), fa(tot["failed"]))
    if parked:
        detail += "؛ %s کارِ «منتظرِ روشن شدنِ گره» هم هر دقیقه بیدار می‌شوند" % fa(parked)
    if tot["queued"] or tot["running"] or parked:
        state = "doing" if (tot["running"] or not off_line) else "waiting"
        if state == "waiting":
            detail = "منتظرِ روشن شدنِ سرورِ پردازش — " + detail
    else:
        state = "fail" if tot["failed"] else ("waiting" if off_line and not tot["done"] else "done")
        if state == "waiting":
            detail = "منتظرِ روشن شدنِ سرورِ پردازش؛ هیچ کاری در صف نیست — " + detail
    return _row("queue", title, state, detail, totals=dict(tot), parked=parked, action="requeue" if tot["failed"] else ""), rows


def ai_row(node=None) -> dict:
    """درخواست‌های هوشِ مصنوعیِ متنی که «در صف تا روشن شدنِ سرورِ پردازش» مانده‌اند (ایده، پیش‌نویس، ترجمه، کپشن …).

    «انجام شد» (سبز) فقط وقتی درست است که واقعاً چیزی اجرا شده یا مسیرِ هوش مصنوعی آماده است؛ گره خاموش و هیچ درخواستی هم اجرا نشده ⇒ «منتظر»."""
    title = "درخواست‌های هوشِ مصنوعی که در صف مانده‌اند"
    try:
        from . import deferred

        n = deferred.pending_count()
        done_n = deferred.recent_done_count()
        ready, how = deferred.ai_ready()
    except Exception as exc:  # noqa: BLE001
        return _row("ai_queue", title, "warn", "خوانده نشد (%s)." % exc.__class__.__name__)
    try:
        from services.ai import priority

        order = "اول لوکال (گرهٔ پردازش)، بعد متیس" if priority.config().first_for(priority.TEXT) == priority.LOCAL else "اول متیس، بعد لوکال"
    except Exception:  # noqa: BLE001
        order = ""
    if n:
        state = "doing" if ready else "waiting"
        return _row("ai_queue", title, state, "%s درخواست در صف است و با روشن شدنِ گره (یا برگشتنِ اعتبارِ متیس) خودکار اجرا می‌شود. ترتیب: %s." % (fa(n), order), pending=n, done=done_n)
    if done_n or how == "local":
        # سبز: یا همین حالا گرهٔ پردازش (لوکال) جواب می‌دهد، یا درخواست‌هایی واقعاً از صف اجرا شده‌اند. «متیسِ تنظیم‌شده» به‌تنهایی سبز نیست: اعتبارش
        # تا اولین درخواست نامعلوم است (الان تمام شده؛ ۴۰۲) و گرهٔ پردازش هم خاموش است ⇒ هنوز چیزی اجرا نشده.
        return _row("ai_queue", title, "done", "درخواستی در صف نیست%s. ترتیب: %s." % ((" (%s درخواستِ صف‌شده تمام شد)" % fa(done_n)) if done_n else "", order), pending=0, done=done_n)
    return _row("ai_queue", title, "waiting", "درخواستی در صف نیست و هنوز چیزی اجرا نشده؛ گرهٔ پردازش خاموش است (و متیس هم اعتبارِ تازه نداشته است). "
                "هر درخواستی که بیاید و هیچ مسیری جواب ندهد «در صف تا روشن شدنِ سرورِ پردازش» می‌ماند و با روشن شدنِ گره خودکار اجرا می‌شود. ترتیب: %s." % order, pending=0, done=done_n)


def before_checklist(planned: list[dict]) -> list[dict]:
    """وقتی گره خاموش است: «وقتی روشنش کنید این‌ها خودشان اتفاق می‌افتد»."""
    cfg = ComputeSettings.get()
    total = sum(f["bytes"] for f in planned)
    items = [
        ("۱", "کامپیوترِ گرافیکی را روشن کنید", "برنامه با ورود به ویندوز خودش بالا می‌آید؛ اگر نیامد START.bat را یک بار اجرا کنید. کارِ دیگری از شما لازم نیست."),
        ("۲", "نرم‌افزارِ گره خودش به‌روز می‌شود", "نسخهٔ قدیمی (۲٫۱۰) بستهٔ تازه را از همین سایت می‌گیرد و خودش دوباره راه می‌افتد؛ اگر بد درآمد به نسخهٔ قبل برمی‌گردد. "
                                                 + ("به‌روزرسانیِ خودکار روشن است." if cfg.auto_update else "⚠ به‌روزرسانیِ خودکار خاموش است؛ START.bat هنگامِ شروع همین کار را می‌کند.")),
        ("۳", "نیازمندی‌ها خودشان نصب می‌شوند", "%s ویژگی (تشخیصِ گفتار، Piper، مرورگرِ خزنده، Blender، Node.js، ffmpeg با NVENC، …)؛ حدودِ %s فایلِ ثابت از سایت، بقیه از PyPI و hf-mirror. "
                                               "نصبِ اولِ هر ویژگی به بازهٔ دانلود بسته نیست." % (fa(len(planned)), _mb(total))),
        ("۴", "مدل‌های خودِ شما روی کارت کار می‌کنند", "Ollama و ComfyUI روشن می‌شوند؛ مدل‌های شما (qwen3 و qwq و …) تغییر نمی‌کنند؛ مسیرِ هوش مصنوعی همه‌جا اول گره است و بعد متیس."),
        ("۵", "هر ویژگی آزمایش می‌شود", ("آزمونِ خودکارِ هر ویژگی (یک کارِ واقعیِ کوچک) پس از به‌روزرسانی اجرا می‌شود" if cfg.auto_selftest else "⚠ آزمونِ خودکار خاموش است")
                                      + "؛ نتیجه همین‌جا سبز/قرمز با دلیل دیده می‌شود."),
        ("۶", "کارهای منتظر خودشان اجرا می‌شوند", "کارهایی که در صف مانده‌اند (تصویر، موشن، صدا، …) و درخواست‌های هوش مصنوعی که «در صف تا روشن شدنِ سرورِ پردازش» ماندند، بی‌هیچ کلیکی اجرا می‌شوند. "
                                                 "فقط انتشار و ارسال (اینستاگرام، پیامک، …) به تأییدِ خودِ شما بسته است."),
    ]
    return [{"n": n, "title": t, "detail": d} for n, t, d in items]


# ───────────────────────────── گزارشِ کامل

def _safe(fn, key, title, *a):
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tonight: section %s failed", key)
        return _row(key, title, "warn", "این بخش خوانده نشد (%s)." % exc.__class__.__name__)


def _phase(node, steps: dict) -> tuple[str, str]:
    """(کلید، جمله) — «الان کجاییم؟»"""
    if node is None or not node.online:
        return "off", "سرورِ پردازش خاموش است. روشنش کنید؛ بقیه خودش پیش می‌رود."
    if steps["update"]["state"] in ("doing", "fail") and steps["update"].get("have") != steps["update"].get("want"):
        return "update", "نرم‌افزارِ گره در حالِ به‌روزرسانی است."
    if steps["installs"]["state"] in ("doing", "todo"):
        return "installs", "نیازمندی‌ها در حالِ نصب‌اند."
    if steps["selftests"]["state"] in ("doing", "todo"):
        return "tests", "آزمونِ خودکارِ ویژگی‌ها در جریان است."
    if steps["queue"]["state"] == "doing" or steps["ai_queue"]["state"] == "doing":
        return "jobs", "کارهای منتظر در حالِ اجرایند."
    if any(s["state"] == "fail" for s in steps.values()):
        return "attention", "چند مورد قرمز است؛ دلیلشان پایین نوشته شده."
    return "done", "همه‌چیز آماده است."


def build(node_pk=None) -> dict:
    node = pick_node(node_pk)
    planned = planned_features()
    power = _safe(power_row, "power", "روشن شدنِ سرورِ پردازش", node)
    update = _safe(update_row, "update", "به‌روزرسانیِ خودکار", node)
    try:
        installs, install_rows = installs_rows(node, planned)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tonight: installs failed")
        installs, install_rows = _row("installs", "نصبِ خودکارِ نیازمندی‌ها", "warn", "خوانده نشد (%s)." % exc.__class__.__name__), []
    models = _safe(models_row, "models", "مدل‌های هوش مصنوعیِ روی کارت", node)
    try:
        tests, test_rows = selftests_rows(node)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tonight: selftests failed")
        tests, test_rows = _row("selftests", "آزمونِ خودکارِ هر ویژگی", "warn", "خوانده نشد (%s)." % exc.__class__.__name__), []
    try:
        queue, queue_detail = queue_rows(node)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tonight: queue failed")
        queue, queue_detail = _row("queue", "اجرای خودکارِ کارهای منتظر", "warn", "خوانده نشد (%s)." % exc.__class__.__name__), []
    ai = _safe(ai_row, "ai_queue", "درخواست‌های هوشِ مصنوعی در صف", node)
    steps = {"power": power, "update": update, "installs": installs, "models": models, "selftests": tests, "queue": queue, "ai_queue": ai}
    phase, phase_text = _phase(node, steps)
    try:
        from . import owner_steps

        mine = [s for s in owner_steps.build().get("steps", []) if s.get("state") in ("todo", "wait")]
    except Exception:  # noqa: BLE001
        mine = []
    cfg = ComputeSettings.get()
    counts = Counter(s["state"] for s in steps.values())
    return {
        "at": timezone.now().isoformat(timespec="seconds"), "phase": phase, "phase_text": phase_text,
        "node": ({"id": node.pk, "name": node.name, "online": node.online, "agent": (node.capabilities or {}).get("agent") or "",
                  "last_seen": node.last_seen.isoformat() if node.last_seen else ""} if node else None),
        "latest_agent": U.latest().get("version") or "",
        "steps": [power, update, installs, models, tests, queue, ai],
        "installs": install_rows, "tests": test_rows, "queue": queue_detail,
        "checklist": before_checklist(planned) if (node is None or not node.online) else [],
        "owner": mine,
        "auto": {"auto_update": cfg.auto_update, "auto_selftest": cfg.auto_selftest, "requeue_after_pass": cfg.requeue_after_pass},
        "counts": dict(counts),
    }


# ───────────────────────────── «دوباره»

RETRY = ("update", "bootstrap", "selftest", "requeue", "kick")


def retry(what: str, node_pk=None, by: str = "") -> dict:
    """ابزارِ موجود را صدا می‌زند؛ ⇒ {"ok", "message"}. چیزی از خودش نمی‌سازد."""
    node = pick_node(node_pk)
    if what not in RETRY:
        return {"ok": False, "message": "کارِ ناشناخته."}
    if node is None:
        return {"ok": False, "message": "سرورِ پردازشی ثبت نیست."}
    if what == "kick":
        from .tasks import maintenance

        out = maintenance()
        return {"ok": True, "message": "نوبتِ خودکارها همین الان اجرا شد.", "detail": out}
    if what in ("update", "bootstrap"):
        try:
            C.request(node, what, by)
        except C.CommandError as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "دستور فرستاده شد؛ گره در چند ثانیهٔ دیگر برمی‌دارد."}
    if what == "selftest":
        if not node.online:
            return {"ok": False, "message": "سرورِ پردازش خاموش است؛ آزمون فقط روی سرورِ روشن اجرا می‌شود."}
        from .selftests import runner

        run = runner.start_run(node, "manual", by)
        return {"ok": True, "message": "آزمونِ کامل شروع شد (اجرای %s)." % fa(run.pk)}
    if what == "requeue":
        out = QV.retry_many(state="FAILED")
        return {"ok": True, "message": "%s کارِ ناموفق دوباره به صف رفت (%s رد شد)." % (fa(out.get("retried", 0)), fa(out.get("skipped", 0))), "detail": out}
    return {"ok": False, "message": "کارِ ناشناخته."}
