"""آزمون‌هایی که ویژگی‌های دیگر فقط با یک فایلِ `docs/selftests/<ویژگی>.md` اعلام کرده‌اند (بدونِ کدِ پایتون).

در فایل یک یا چند بلوکِ ```json می‌گذارند؛ هر بلوک یک شیء (یا فهرستی از شیءها):

    {"key": "motion_render", "label": "رندرِ موشن‌گرافیک", "group": "video", "kind": "motion.render",
     "payload": {...}, "files_b64": {"name.png": "<base64>"},          # اختیاری: فایل‌های ورودی
     "timeout_s": 900, "optional": false, "deep": false, "gpu_required": true,
     "requires": {"kinds": ["motion.render"], "caps": ["node_js"]},    # گره باید این نوع/قابلیت‌ها را اعلام کرده باشد، وگرنه «ردشده»
     "check": {"outputs_min": 1, "output_ext": [".mp4"], "min_bytes": 5000, "json_file": "result.json", "json_has": ["frames"],
               "text_contains": ["ok"], "forbid_device": ["cpu"]},
     "requeue_kinds": ["motion.render"]}

شرط‌های `check` همه با «و» می‌آیند. خطای ساختار در یک بلوک فقط همان بلوک را کنار می‌گذارد.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

from django.conf import settings

from . import SelfTest, Spec, Verdict, register

logger = logging.getLogger(__name__)
BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def docs_dir() -> Path:
    return Path(getattr(settings, "NM_SELFTEST_DOCS", "") or Path(settings.BASE_DIR).parent / "docs" / "selftests")


def _checker(rule: dict):
    def check(ctx, job):
        outs = job.outputs()
        exts = tuple(str(e).lower() for e in rule.get("output_ext") or ())
        picked = [o for o in outs if not exts or str(o.get("name", "")).lower().endswith(exts)]
        if len(picked) < int(rule.get("outputs_min", 1)):
            return Verdict.failed("خروجیِ لازم نرسید (%s)؛ خروجی‌ها: %s" % (", ".join(exts) or "فایل", ", ".join(o.get("name", "?") for o in outs) or "هیچ"))
        small = [o["name"] for o in picked if (o.get("size") or 0) < int(rule.get("min_bytes", 1))]
        if small:
            return Verdict.failed("خروجیِ خیلی کوچک یا خالی: %s" % ", ".join(small))
        if rule.get("json_file"):
            data = ctx.read_json(job, rule["json_file"])
            if not isinstance(data, dict):
                return Verdict.failed("%s خوانده نشد" % rule["json_file"])
            missing = [k for k in rule.get("json_has") or () if k not in data]
            if missing:
                return Verdict.failed("در %s این کلیدها نیست: %s" % (rule["json_file"], "، ".join(missing)))
        if rule.get("text_contains"):
            blob = ""
            for o in picked:
                if str(o.get("name", "")).lower().endswith((".json", ".txt", ".srt", ".vtt")):
                    raw = ctx.read_output(job, o["name"]) or b""
                    blob += raw.decode("utf-8", "replace")
            lacking = [t for t in rule["text_contains"] if t not in blob]
            if lacking:
                return Verdict.failed("در خروجی این متن‌ها نیست: %s" % "، ".join(lacking))
        device = ctx.meta(job).get("device", "")
        if device and device in (rule.get("forbid_device") or ()):
            return Verdict.failed("روی دستگاهِ نامجاز (%s) اجرا شد: %s" % (device, ctx.meta(job).get("device_note", "")), device=device)
        return Verdict.passed("%d خروجی · %s ثانیه" % (len(picked), job.run_s if job.run_s is not None else "؟"))
    return check


def _available(req: dict):
    def fn(node):
        caps = node.capabilities or {}
        kinds = caps.get("kinds")
        for k in req.get("kinds") or ():
            if not isinstance(kinds, list) or k not in kinds:
                return False, "عاملِ این سرور نوعِ «%s» را اعلام نکرده است" % k
        for c in req.get("caps") or ():
            if not caps.get(c):
                return False, "این سرور قابلیتِ «%s» را ندارد" % c
        return True, ""
    return fn


def from_block(obj: dict) -> SelfTest:
    if not isinstance(obj, dict) or not obj.get("key") or not obj.get("kind") or not isinstance(obj.get("payload", {}), dict):
        raise ValueError("block needs key, kind and payload")
    files = {name: base64.b64decode(b64) for name, b64 in (obj.get("files_b64") or {}).items()}
    key = re.sub(r"[^a-z0-9_]", "_", str(obj["key"]).lower())[:40]

    def build(ctx):
        return Spec(str(obj["kind"]), dict(obj.get("payload") or {}), dict(files), timeout_s=int(obj.get("timeout_s") or 900))
    rq = obj.get("requeue_kinds")
    return SelfTest(key=key, label=str(obj.get("label") or key)[:120], group=str(obj.get("group") or "docs"), kind=str(obj["kind"]),
                    build=build, check=_checker(obj.get("check") or {}), available=_available(obj.get("requires") or {}),
                    gpu_required=bool(obj.get("gpu_required")), optional=bool(obj.get("optional")), deep=bool(obj.get("deep")),
                    requeue={"kinds": tuple(rq)} if rq else None, order=int(obj.get("order") or 150),
                    describe=str(obj.get("describe") or "")[:200])


def register_all() -> list[str]:
    """همهٔ بلوک‌های docs/selftests/*.md را ثبت می‌کند؛ آزمونِ هم‌کلیدِ کدی را عوض نمی‌کند. فهرستِ کلیدهای ثبت‌شده."""
    from . import REGISTRY

    done = []
    folder = docs_dir()
    if not folder.is_dir():
        return done
    for path in sorted(folder.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in BLOCK_RE.findall(text):
            try:
                data = json.loads(raw)
                for obj in (data if isinstance(data, list) else [data]):
                    test = from_block(obj)
                    if test.key in REGISTRY and getattr(REGISTRY[test.key], "describe", "").startswith("[code]"):
                        continue
                    if test.key not in REGISTRY:
                        register(test)
                        done.append(test.key)
            except Exception as exc:  # noqa: BLE001 — بلوکِ خراب فقط خودش کنار می‌رود
                logger.warning("selftests: %s: a block was ignored: %s", path.name, exc)
    return done
