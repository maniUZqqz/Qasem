"""Account health for the monitoring tab: a log of the things that matter (Instagram said «wait», the line dropped, the
session went bad, a read finished well) and a quick connection test. Small and pure: a file in data/, no browser of its own.
The connection test uses httpx (so it never fights the one-browser-at-a-time lock), through the saved proxy when there is one."""
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

import ig_prefs
from ig_common import DATA
from ig_profile import read_json, write_atomic

FILE = DATA / "health.json"
HOUR, DAY, WEEK = 3600, 86400, 7 * 86400
KEEP = 200
# what a finished job's outcome means for the account's health
BAD = {"rate_limit": "«صبر کن» اینستاگرام", "cooldown": "مکث بعد از «صبر کن»", "network": "اینستاگرام در دسترس نبود",
       "session_invalid": "نشست باطل شد", "challenge": "اینستاگرام تأیید هویت خواست", "automated": "اینستاگرام رفتار خودکار دید",
       "not_found": "صفحه پیدا نشد", "unreadable": "جواب روشن نبود"}


def now():
    return time.time()


def _read():
    data = read_json(FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("events", [])
    return data


def _write(data):
    data["events"] = data["events"][-KEEP:]
    DATA.mkdir(parents=True, exist_ok=True)
    write_atomic(FILE, json.dumps(data, ensure_ascii=False).encode("utf-8"))


def record(snapshot):
    """Note one finished job: a concern (its kind) or a plain success. Called for every job (ig_queue.finished)."""
    outcome = snapshot.get("outcome") or {}
    kind = outcome.get("kind")
    state = snapshot.get("state")
    if state == "success":
        tag, concern = "ok", False
    elif kind in BAD:
        tag, concern = kind, True
    else:
        return                       # cancelled, budget, a soft empty result: not about health
    data = _read()
    data["events"].append({"at": round(now(), 1), "kind": tag, "concern": concern, "mode": snapshot.get("mode"),
                           "username": snapshot.get("username"), "msg": outcome.get("ig_message") or outcome.get("note") or BAD.get(kind, "")})
    _write(data)


def _count(events, kinds, window):
    cut = now() - window
    return sum(1 for e in events if e["at"] > cut and (kinds is None or e["kind"] in kinds))


def summary():
    """What the monitoring tab shows: how many concerns and successes in the last day and week, the last few incidents, and
    a traffic-light the person can read at a glance."""
    data = _read()
    events = data["events"]
    concerns = [e for e in events if e.get("concern")]
    day_bad, week_bad = _count(concerns, None, DAY), _count(concerns, None, WEEK)
    hour_wait = _count(events, ("rate_limit", "cooldown"), HOUR)
    last_ok = next((e["at"] for e in reversed(events) if e["kind"] == "ok"), None)
    light = "bad" if hour_wait >= 3 or _count(events, ("session_invalid", "challenge", "automated"), DAY) else "warn" if day_bad else "ok"
    recent = [{"at": e["at"], "kind": e["kind"], "concern": e.get("concern", False), "mode": e.get("mode"),
               "username": e.get("username"), "msg": e.get("msg", ""),
               "at_iso": datetime.fromtimestamp(e["at"], timezone.utc).isoformat(timespec="seconds")} for e in events[-12:][::-1]]
    return {"light": light, "day_concerns": day_bad, "week_concerns": week_bad, "hour_waits": hour_wait,
            "day_ok": _count(events, ("ok",), DAY), "last_ok": last_ok, "recent": recent}


async def test_connection(proxy=None):
    """One request to Instagram (through the saved proxy unless another is given): does the line/proxy reach it?"""
    proxy = (proxy if proxy is not None else ig_prefs.load()["proxy"]) or None
    server = None
    if proxy:
        u = urlparse(proxy)
        server = f"{u.scheme}://{u.hostname}" + (f":{u.port}" if u.port else "")
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(proxy=proxy or None, timeout=12, follow_redirects=False) as c:
            r = await c.get("https://www.instagram.com/", headers={"user-agent": "Mozilla/5.0"})
        return {"ok": r.status_code < 500, "status": r.status_code, "ms": round((time.perf_counter() - start) * 1000),
                "proxy": server, "via": "proxy" if proxy else "direct"}
    except Exception as e:
        return {"ok": False, "status": None, "error": type(e).__name__, "proxy": server, "via": "proxy" if proxy else "direct",
                "ms": round((time.perf_counter() - start) * 1000)}
