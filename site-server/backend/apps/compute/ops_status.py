"""«آخرین بکاپ» و «آزمون‌های شبانهٔ سایت» برای پنل — فقط خواندنِ فایل‌هایی که اسکریپت‌های سرور می‌نویسند.

* ``<NM_BACKUP_DIR>/status.json`` را ``deploy/nm/ops/nm-backup`` می‌نویسد (پیش‌فرض /root/backups/nm-daily).
* ``<NM_DATA_DIR>/test-report.json`` را ``deploy/nm/ops/nm-nightly-tests`` می‌نویسد؛ ``test-report.json.running`` یعنی اجرا در جریان است.

هیچ‌چیزِ این‌جا چیزی را نمی‌نویسد یا اجرا نمی‌کند؛ فایلِ نبود/خراب ⇒ «هنوز نیست»، نه خطا.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

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


def test_status() -> dict:
    running = _running()
    data = _read_json(test_report_path())
    if not data:
        return {"present": False, "state": "missing", "running": running}
    age = _age_hours(data.get("finished_at"))
    totals = data.get("totals") or {}
    red = bool(totals.get("red_apps") or totals.get("failures") or totals.get("errors"))
    if age is not None and age > TESTS_STALE_HOURS:
        state = "stale"
    else:
        state = "red" if red else "green"
    return {**data, "present": True, "state": state, "age_hours": age, "running": running}


def ops_status() -> dict:
    return {"backup": backup_status(), "tests": test_status()}
