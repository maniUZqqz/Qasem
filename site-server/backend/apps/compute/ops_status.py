"""«آخرین بکاپ» و «آزمون‌های شبانهٔ سایت» برای پنل — فقط خواندنِ فایل‌هایی که اسکریپت‌های سرور می‌نویسند.

* ``<NM_BACKUP_DIR>/status.json`` را ``deploy/nm/ops/nm-backup`` می‌نویسد (پیش‌فرض /root/backups/nm-daily).
* ``<NM_DATA_DIR>/test-report.json`` را ``deploy/nm/ops/nm-nightly-tests`` می‌نویسد؛ ``test-report.json.running`` یعنی اجرا در جریان است.

هیچ‌چیزِ این‌جا چیزی را نمی‌نویسد یا اجرا نمی‌کند؛ فایلِ نبود/خراب ⇒ «هنوز نیست»، نه خطا.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

NIGHTLY_SCRIPT = "/usr/local/bin/nm-nightly-tests"
BACKUP_STALE_HOURS = 36
TESTS_STALE_HOURS = 48
RUNNING_STALE_HOURS = 8  # نشانهٔ «در حالِ اجرا» که قدیمی‌تر از این باشد، بازمانده است


def backup_dir() -> Path:
    return Path(os.getenv("NM_BACKUP_DIR", "/root/backups/nm-daily"))


def test_report_path() -> Path:
    base = getattr(settings, "NM_DATA_DIR", None) or Path(settings.MEDIA_ROOT).parent
    return Path(base) / "test-report.json"


def _read_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return round(max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 3600), 2)


def backup_status() -> dict:
    data = _read_json(backup_dir() / "status.json")
    if not data:
        return {"present": False, "state": "missing"}
    age = _age_hours(data.get("at"))
    if not data.get("ok"):
        state = "failed"
    elif age is not None and age > BACKUP_STALE_HOURS:
        state = "stale"
    else:
        state = "ok"
    return {**data, "present": True, "state": state, "age_hours": age}


def _running() -> dict | None:
    path = test_report_path().with_name("test-report.json.running")
    try:
        if time.time() - path.stat().st_mtime > RUNNING_STALE_HOURS * 3600:
            return None
    except OSError:
        return None
    data = _read_json(path)
    return {"app": str(data.get("app", "")), "since": str(data.get("since", ""))} if data else None


def current_version() -> str:
    try:
        from apps.common import versioning

        return str(versioning.read_version() or "")
    except Exception:  # noqa: BLE001 — نسخه خوانده نشد ⇒ «نسخهٔ قدیمی» تشخیص داده نمی‌شود، نه خطا
        return ""


def _red_apps(data: dict) -> list[dict]:
    apps = [a for a in (data.get("apps") or []) if isinstance(a, dict) and not a.get("ok", True)]
    ver = str(data.get("version") or "")
    for a in apps:
        a.setdefault("version", ver)
    return apps


def outdated(data: dict, cur: str | None = None) -> bool:
    """گزارش قرمز است ولی هر اپِ قرمزش با نسخه‌ای قدیمی‌تر از نسخهٔ فعلیِ سایت آزموده شده (⇒ با اجرای دوباره احتمالاً سبز می‌شود)."""
    cur = current_version() if cur is None else cur
    if not cur:
        return False
    red = _red_apps(data)
    if not red:
        totals = data.get("totals") or {}
        return bool((totals.get("red_apps") or totals.get("failures") or totals.get("errors")) and str(data.get("version") or "") not in ("", cur))
    return all(str(a.get("version") or "") not in ("", cur) for a in red)


def test_status() -> dict:
    running = _running()
    data = _read_json(test_report_path())
    if not data:
        return {"present": False, "state": "missing", "running": running}
    age = _age_hours(data.get("finished_at"))
    totals = data.get("totals") or {}
    red = bool(totals.get("red_apps") or totals.get("failures") or totals.get("errors"))
    cur = current_version()
    if age is not None and age > TESTS_STALE_HOURS:
        state = "stale"
    elif red and outdated(data, cur):
        state = "outdated"            # قرمزِ نسخهٔ قدیمی: سایت خودش همان اپ‌ها را دوباره می‌آزماید (maybe_rerun_red)
    else:
        state = "red" if red else "green"
    out = {**data, "present": True, "state": state, "age_hours": age, "running": running, "current_version": cur}
    if state == "outdated":
        marker = _read_json(_rerun_path())
        out["rerun"] = {"apps": [a["app"] for a in _red_apps(data)], "started": bool(marker and marker.get("version") == cur), "at": (marker or {}).get("at", "")}
    return out


# ───────────────────────────── اجرای دوبارهٔ خودکارِ اپ‌های قرمزِ «نسخهٔ قدیمی»

def _rerun_path() -> Path:
    return test_report_path().with_name("test-rerun.json")


def maybe_rerun_red(now: float | None = None) -> dict:
    """گزارشِ شبانه فقط به‌خاطرِ نسخهٔ قدیمی قرمز است (مثلاً آزمونی که بعد از آن رفع شد) ⇒ همان اپ‌ها (فقط خودشان) را، یک بار برای هر نسخه،
    با همان اسکریپتِ شبانه دوباره می‌آزماید؛ نتیجه در گزارش ادغام می‌شود و قرمزِ کهنه خودش پاک می‌شود. چیزی از مالک نمی‌خواهد.

    فقط روی سرورِ واقعی (اسکریپتِ nm-nightly-tests نصب است)، فقط وقتی اجرایی در جریان نیست و فقط یک بار برای هر نسخه. ⇒ {"started": bool, "why": str}"""
    from django.conf import settings

    if getattr(settings, "IS_TEST", False) and not getattr(settings, "OPS_RERUN_FORCE", False):
        return {"started": False, "why": "test-mode"}
    script = os.getenv("NM_NIGHTLY_SCRIPT", NIGHTLY_SCRIPT)
    if not os.path.isfile(script):
        return {"started": False, "why": "no-script"}
    data = _read_json(test_report_path())
    if not data:
        return {"started": False, "why": "no-report"}
    cur = current_version()
    if not cur or not outdated(data, cur):
        return {"started": False, "why": "not-outdated"}
    if _running() or test_report_path().with_name("test-report.json.running").exists():
        return {"started": False, "why": "running"}
    marker = _read_json(_rerun_path()) or {}
    if marker.get("version") == cur:
        return {"started": False, "why": "already-tried"}
    apps = [a["app"] for a in _red_apps(data) if str(a.get("app") or "").replace("_", "").isalnum()]
    if not apps:
        return {"started": False, "why": "no-apps"}
    try:
        _rerun_path().write_text(json.dumps({"version": cur, "apps": apps, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")
    except OSError as exc:
        return {"started": False, "why": "marker: %s" % exc}
    env = {"NM_NIGHTLY_APPS": " ".join(apps)}
    sd = shutil.which("systemd-run")
    try:
        if sd:
            # واحدِ جدا از سرویسِ Celery: با ری‌استارتِ سرویس‌ها (استقرار) اجرای آزمون کشته نمی‌شود
            cmd = [sd, "--no-block", "--collect", "--unit=nm-test-rerun-%d" % int(time.time() if now is None else now), "--nice=10"]
            cmd += ["--setenv=%s=%s" % kv for kv in env.items()] + [script]
            subprocess.run(cmd, check=True, timeout=20, capture_output=True)
        else:
            subprocess.Popen([script], env={**os.environ, **env}, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001 — اجرا نشد ⇒ علامت را پاک کن تا دقیقهٔ بعد دوباره امتحان شود
        logger.warning("ops: could not start the re-run of %s: %s", apps, exc)
        try:
            _rerun_path().unlink()
        except OSError:
            pass
        return {"started": False, "why": "spawn: %s" % exc.__class__.__name__}
    logger.info("ops: re-running the nightly tests of %s (they were red on an older version)", apps)
    return {"started": True, "apps": apps}


def ops_status() -> dict:
    return {"backup": backup_status(), "tests": test_status()}
