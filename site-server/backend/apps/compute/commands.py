# -*- coding: utf-8 -*-
"""«دستورها» ِ سرورِ پردازش از پنل (۱۴۰۵/۰۸/۱۹).

خواستهٔ مالک: برای NMarketing یک دستور «توقف ⇐ Update ⇐ راه‌اندازیِ دوباره» (و ساخت/وضعیت/لاگ) از همین پنل.
از راهِ خودِ عاملِ NMarketing روی گره: پنل دستور را این‌جا می‌گذارد، گره با heartbeat ِ بعدی (هر ۲۰ ثانیه) می‌گیرد،
اجرا می‌کند و نتیجه را برمی‌گرداند — بی SSH، بی نصبِ جدا، بی دسترسیِ Administrator، فقط دستورهای ثابت.

دسترسیِ کامل به کامپیوتر («حالتِ VPS»، برای هر پروژه‌ای مثلِ InstAI) جداست و بیرون از NMarketing است: /opt/pc-remote.

ذخیره: <NM_DATA_DIR>/node-commands/<name>.json  = {"pending": {...} | null, "last": {...}}
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import services as SV
from .models import ComputeNode, ComputeNodeLog

ACTIONS = ("status", "update", "restart", "build", "logs")
LABEL = {
    "status": "وضعیت",
    "update": "به‌روزرسانی و راه‌اندازیِ دوباره",
    "restart": "راه‌اندازیِ دوباره",
    "build": "ساختِ ویرایشگرها",
    "logs": "لاگ‌ها",
}
#: عاملی که «دستورها» را می‌شناسد (caps["commands"])
MIN_AGENT = (2, 10)
#: دستوری که گره در این مدت برنداشت، کهنه می‌شود (گره خاموش شد)
PENDING_TTL_S = 30 * 60
#: «در حالِ اجرا» ای که بیش از این بی‌جواب ماند دیگر جلوی دستورِ تازه را نمی‌گیرد
RUNNING_STALE_S = {"build": 3 * 3600}
RUNNING_STALE_DEFAULT_S = 40 * 60


class CommandError(Exception):
    pass


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "")[:60] or "node"


def _path(node: ComputeNode):
    d = SV.data_root() / "node-commands"
    d.mkdir(parents=True, exist_ok=True)
    return d / ("%s.json" % _safe(node.name))


def _read(node: ComputeNode) -> dict:
    try:
        return json.loads(_path(node).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(node: ComputeNode, data: dict) -> None:
    p = _path(node)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _age(iso) -> float:
    t = parse_datetime(iso) if iso else None
    return (timezone.now() - t).total_seconds() if t else 1e9


def _agent_tuple(node: ComputeNode) -> tuple:
    try:
        return tuple(int(x) for x in str((node.capabilities or {}).get("agent") or "0").split(".")[:2])
    except ValueError:
        return (0,)


def supported(node: ComputeNode) -> bool:
    caps = node.capabilities or {}
    return _agent_tuple(node) >= MIN_AGENT and isinstance(caps.get("commands"), list)


def _settle(node: ComputeNode, data: dict) -> dict:
    """دستورِ برنداشته و «در حالِ اجرا» ی بی‌جواب را کهنه حساب می‌کند."""
    changed = False
    pending = data.get("pending")
    last = data.get("last") or {}
    if pending and _age(pending.get("at")) > PENDING_TTL_S:
        data["pending"] = None
        if last.get("id") == pending.get("id"):
            last.update(state="expired", ok=False, output="سرورِ پردازش در %d دقیقه دستور را برنداشت (خاموش بود)." % (PENDING_TTL_S // 60))
        changed = True
    if last.get("state") == "running":
        limit = RUNNING_STALE_S.get(last.get("action"), RUNNING_STALE_DEFAULT_S)
        if _age(last.get("started_at") or last.get("at")) > limit:
            last.update(state="expired", ok=False, output=(last.get("output") or "") + "\n(بی‌جواب ماند)")
            changed = True
    if changed:
        data["last"] = last
        _write(node, data)
    return data


def state(node: ComputeNode) -> dict:
    data = _settle(node, _read(node))
    last = data.get("last") or {}
    return {
        "supported": supported(node), "online": node.online, "agent": (node.capabilities or {}).get("agent") or "",
        "min_agent": ".".join(str(x) for x in MIN_AGENT),
        "busy": bool(data.get("pending")) or last.get("state") in ("sent", "running"),
        "last": last, "actions": [{"key": k, "label": LABEL[k]} for k in ACTIONS],
    }


def request(node: ComputeNode, action: str, by: str = "") -> dict:
    if action not in ACTIONS:
        raise CommandError("دستورِ ناشناخته: %s" % action)
    if not node.online:
        raise CommandError("سرورِ پردازش خاموش است (یا برنامه‌اش بسته است)؛ دستور فقط وقتی برنامه روشن است اجرا می‌شود.")
    if not supported(node):
        raise CommandError("عاملِ این سرور (%s) هنوز «دستورها» را نمی‌شناسد؛ با اولین اجرای START.bat خودش به‌روز می‌شود (نسخهٔ %s به بعد)."
                           % ((node.capabilities or {}).get("agent") or "?", ".".join(str(x) for x in MIN_AGENT)))
    data = _settle(node, _read(node))
    last = data.get("last") or {}
    if data.get("pending") or last.get("state") in ("sent", "running"):
        raise CommandError("دستورِ «%s» هنوز تمام نشده است." % LABEL.get(last.get("action"), last.get("action")))
    cmd = {"id": uuid.uuid4().hex, "action": action, "label": LABEL[action], "by": by, "at": timezone.now().isoformat()}
    data["pending"] = cmd
    data["last"] = dict(cmd, state="sent", output="", ok=None)
    _write(node, data)
    return data["last"]


def pending_for(node: ComputeNode) -> dict | None:
    """برای heartbeat/claim: دستوری که گره باید بگیرد (یا None)."""
    data = _read(node)
    p = data.get("pending")
    if not p:
        return None
    if _age(p.get("at")) > PENDING_TTL_S:
        _settle(node, data)
        return None
    return {"id": p["id"], "action": p["action"]}


def report(node: ComputeNode, cid: str, st: str, ok=None, output: str = "") -> bool:
    data = _read(node)
    last = data.get("last") or {}
    if not cid or last.get("id") != cid:
        return False
    now = timezone.now().isoformat()
    if st == "running":
        data["pending"] = None
        last.update(state="running", started_at=now)
    elif st == "done":
        data["pending"] = None
        last.update(state="done", ok=bool(ok), output=str(output or "")[-30000:], finished_at=now)
        try:
            ComputeNodeLog.objects.create(
                node=node, level="INFO" if ok else "ERROR", logged_at=timezone.now(),
                message=("command %s%s -> %s\n%s" % (last.get("action"), (" (%s)" % last["by"]) if last.get("by") else "",
                                                     "ok" if ok else "failed", str(output or "")[-2500:]))[:4000])
        except Exception:  # noqa: BLE001 — لاگ نباید نتیجه را از بین ببرد
            pass
    else:
        return False
    data["last"] = last
    _write(node, data)
    return True
