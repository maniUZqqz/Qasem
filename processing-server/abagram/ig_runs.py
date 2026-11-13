"""Every finished job, kept for «فعالیت»: what ran, for whom, how it went, its steps and its whole log. One file per run in
data/runs/ plus a small index of the newest (data/runs/index.json), so a page of history never reads every log. Nothing here
holds a password: the job's options never carry it and its log never prints it."""
import json
import shutil
import time

import ig_profile as pr
from ig_common import DATA

DIR = DATA / "runs"
INDEX = DIR / "index.json"
KEEP = 500        # entries in the index (older run files stay on disk, unlisted)
LOG_KEEP = 600    # log lines kept per run


def _compact(value):
    """The result of a job made small: plain values as they are, lists and objects as their size."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value if not isinstance(value, str) else value[:200]
    if isinstance(value, list):
        return {"count": len(value)}
    if isinstance(value, dict):
        return {k: (_compact(v) if not isinstance(v, dict) else {"keys": len(v)}) for k, v in list(value.items())[:20]}
    return None


def _index():
    data = pr.read_json(INDEX, [], backup=True)
    return data if isinstance(data, list) else []


def summary(rec):
    return {k: rec.get(k) for k in ("id", "run", "mode", "username", "state", "started_at", "ended_at", "queued", "step", "kind", "message", "lines")}


def record(s, shot=None):
    """Called once when a job ends, with its whole snapshot. `shot`: the window's last picture taken in this run, kept with it
    (the one shared picture file is overwritten by the next job; a crashed page leaves only the picture taken before)."""
    started = s.get("started_at") or time.time()
    out = s.get("outcome") or {}
    opts = {k: v for k, v in (s.get("options") or {}).items() if k not in ("password",)}
    rec = {"id": f"{int(started)}-{s.get('run')}", "run": s.get("run"), "mode": s.get("mode"), "username": s.get("username"),
           "state": s.get("state"), "started_at": started, "ended_at": time.time(), "queued": s.get("queued"),
           "step": opts.get("_step"), "options": opts, "steps": s.get("steps") or [],
           "kind": out.get("kind"), "message": out.get("ig_message") or out.get("msg") or "", "outcome": _compact(out),
           "result": _compact(s.get("result")), "log": (s.get("log") or [])[-LOG_KEEP:]}
    rec["lines"] = len(rec["log"])
    DIR.mkdir(parents=True, exist_ok=True)
    if shot is not None:
        try:
            shutil.copyfile(shot, DIR / f"{rec['id']}.png")
            rec["picture_at"] = shot.stat().st_mtime
        except OSError:
            pass
    pr.write_atomic(DIR / f"{rec['id']}.json", json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    idx = [x for x in _index() if x.get("id") != rec["id"]] + [summary(rec)]
    pr.write_atomic(INDEX, json.dumps(idx[-KEEP:], ensure_ascii=False).encode("utf-8"), backup=True)
    return rec


def listing(limit=100, task=None):
    """Newest first; only the runs of one queue task when asked."""
    idx = [x for x in reversed(_index()) if task is None or x.get("queued") == task]
    return idx[: max(1, min(limit, KEEP))]


def picture(run_id):
    """The path of a run's own window picture, or None."""
    if not isinstance(run_id, str) or not run_id.replace("-", "").isdigit():
        return None
    path = DIR / f"{run_id}.png"
    return path if path.exists() else None


def get(run_id):
    if not isinstance(run_id, str) or not run_id.replace("-", "").isdigit():
        return None
    try:
        return json.loads((DIR / f"{run_id}.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
