# -*- coding: utf-8 -*-
"""Automatic model downloads of the processing node (model catalog; no agent-version gate: an agent without this module simply does nothing).

The site decides WHAT: with every heartbeat it sends `models_auto` = {enabled, packages: [package keys of the features the owner
switched on, best first], reserve_gb, big_mb}. This module decides WHEN and WHETHER IT FITS, on the node:

* it only touches packages the node's own manifests mark `license_class: open` (a non-commercial / conditional model is never
  fetched automatically, whatever the site says);
* it checks the free disk first (free - reserve - what is already planned); a package that does not fit is skipped and reported
  as «no_disk» - never started and never left half-way;
* small packages start at once (they still obey the site's global download schedule), big ones (> big_mb, default 1.5 GB) wait for
  the NIGHT window even when the global mode is «now» - DownloadManager.start(window=...) parks them and starts them by itself
  when the window opens, pauses them cleanly when it closes and resumes later (partial files continue, sha256 is checked);
* a package that failed three times in a row is left alone for 24 hours (it is shown in the panel with the reason); one click
  in the panel, or the next day, tries again;
* one download run at a time: nothing is planned while DownloadManager is running or already holds a package for the window.

`plan()` is pure (tests/test_model_catalog_node.py). The agent calls absorb() with every answer of the site, tick() from its main loop and
report() when it builds the heartbeat; all three never raise.
"""
import json
import os
import re
import shutil
import time

CONFIG_FILE = "auto-models.json"
STATE_FILE = "auto-models-state.json"
INTERVAL_S = float(os.environ.get("NM_AUTO_MODELS_INTERVAL_S") or 600)
FIRST_DELAY_S = float(os.environ.get("NM_AUTO_MODELS_FIRST_S") or 45)
MAX_FAILS = 3
RETRY_AFTER_S = 24 * 3600
DEFAULT_RESERVE_GB = 25
DEFAULT_BIG_MB = 1536
PKG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_mem = {"cfg": None, "loaded": False, "last": 0.0, "born": time.time(), "force": False, "report": None}


def _data_dir():
    try:
        import nm_data

        here = os.path.dirname(os.path.abspath(__file__))
        return nm_data.data_root(here)
    except Exception:  # noqa: BLE001
        return os.environ.get("NM_DATA") or os.getcwd()


def _path(name, data_dir=None):
    return os.path.join(data_dir or _data_dir(), name)


def normalize(block):
    """What the site sent -> a clean config, or None when it is not a config at all."""
    if not isinstance(block, dict):
        return None
    pk = []
    for p in block.get("packages") or []:
        p = str(p).strip().lower()
        if PKG_RE.match(p) and p not in pk:
            pk.append(p)
    try:
        reserve = max(5, min(500, int(float(block.get("reserve_gb", DEFAULT_RESERVE_GB)))))
    except (TypeError, ValueError):
        reserve = DEFAULT_RESERVE_GB
    try:
        big = max(100, min(100000, int(float(block.get("big_mb", DEFAULT_BIG_MB)))))
    except (TypeError, ValueError):
        big = DEFAULT_BIG_MB
    return {"enabled": bool(block.get("enabled")), "packages": pk[:100], "reserve_gb": reserve, "big_mb": big}


def load(data_dir=None):
    """The saved config (survives a restart while the site is unreachable)."""
    if data_dir is None and _mem["loaded"]:
        return _mem["cfg"]
    cfg = None
    try:
        with open(_path(CONFIG_FILE, data_dir), encoding="utf-8") as fh:
            cfg = normalize(json.load(fh))
    except (OSError, ValueError):
        cfg = None
    if data_dir is None:
        _mem["cfg"], _mem["loaded"] = cfg, True
    return cfg


def absorb(answer, data_dir=None):
    """Every answer of the site (heartbeat / claim): keep its `models_auto` block. True when it changed. Never raises."""
    try:
        cfg = normalize((answer or {}).get("models_auto")) if isinstance(answer, dict) else None
        if cfg is None:
            return False
        if cfg == load(data_dir):
            return False
        os.makedirs(data_dir or _data_dir(), exist_ok=True)
        tmp = _path(CONFIG_FILE, data_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        os.replace(tmp, _path(CONFIG_FILE, data_dir))
        if data_dir is None:
            _mem["cfg"], _mem["loaded"], _mem["force"] = cfg, True, True
        return True
    except Exception:  # noqa: BLE001 - a failing note must never stop the heartbeat
        return False


def _load_state(data_dir=None):
    try:
        with open(_path(STATE_FILE, data_dir), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state, data_dir=None):
    try:
        os.makedirs(data_dir or _data_dir(), exist_ok=True)
        tmp = _path(STATE_FILE, data_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, _path(STATE_FILE, data_dir))
    except OSError:
        pass


# ───────────────────────────────────────────── the pure part

def need_bytes(pkg, rows, counted):
    """Bytes still to download for `pkg` plus the packages it needs (each package counted once per plan)."""
    total = 0
    stack = [pkg]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen or cur in counted:
            continue
        seen.add(cur)
        row = rows.get(cur)
        if row is None:
            continue
        if not row.get("installed"):
            total += int(row.get("bytes_missing") or 0)
        stack.extend(row.get("needs") or [])
    return total, seen


def plan(rows, cfg, free_bytes, fails=None, now=None, active=()):
    """rows = download_models --status "packages"; cfg = normalize(site block); free_bytes = the smaller free space of the
    data drive and the ComfyUI drive (None = unknown: nothing is started). -> {"small": [...], "big": [...], "states": {pkg: state}}

    states: installed | pending (will be started) | no_disk | failed | blocked_license | unknown_package | active (already running,
    queued or waiting for the window)."""
    now = time.time() if now is None else now
    fails = fails or {}
    out = {"small": [], "big": [], "states": {}}
    if not cfg or not cfg.get("enabled"):
        return out
    reserve = int(cfg.get("reserve_gb", DEFAULT_RESERVE_GB)) * 2 ** 30
    big = int(cfg.get("big_mb", DEFAULT_BIG_MB)) * 2 ** 20
    budget = None if free_bytes is None else free_bytes - reserve
    counted = set()
    for pkg in cfg.get("packages") or []:
        row = rows.get(pkg)
        if row is None:
            out["states"][pkg] = "unknown_package"
            continue
        if row.get("license_class", "open") != "open":
            out["states"][pkg] = "blocked_license"
            continue
        if row.get("installed"):
            out["states"][pkg] = "installed"
            continue
        if pkg in active:
            out["states"][pkg] = "active"
            continue
        f = fails.get(pkg) or {}
        if int(f.get("n") or 0) >= MAX_FAILS and now - float(f.get("at") or 0) < RETRY_AFTER_S:
            out["states"][pkg] = "failed"
            continue
        need, seen = need_bytes(pkg, rows, counted)
        if any((rows.get(d) or {}).get("license_class", "open") != "open" for d in seen):
            out["states"][pkg] = "blocked_license"          # a dependency that is not open is never pulled in silently
            continue
        if budget is None or need > budget:
            out["states"][pkg] = "no_disk"
            continue
        budget -= need
        counted |= seen
        out["states"][pkg] = "pending"
        (out["big"] if need > big else out["small"]).append(pkg)
    return out


def free_bytes_of(status):
    """The smaller of the free space where the models go (data folder, ComfyUI) - from download_models --status."""
    disk = (status or {}).get("disk") or {}
    vals = [v for v in (disk.get("data_free"), disk.get("comfy_free")) if isinstance(v, (int, float))]
    return min(vals) if vals else None


# ───────────────────────────────────────────── what the agent calls

def _record_run(manager, state, now):
    """A finished run: count failures per package (3 in a row = a day of rest), clear the counters of what is installed."""
    pr = manager.progress() or {}
    if pr.get("state") not in ("failed", "done") or not pr.get("started") or state.get("last_run") == pr.get("started"):
        return False
    state["last_run"] = pr["started"]
    fails = state.setdefault("fails", {})
    bad = {}
    for f in pr.get("failed") or []:
        bad.setdefault(f.get("package") or "", f.get("reason") or "")
    for pkg in pr.get("packages") or []:
        if pkg in bad:
            row = fails.setdefault(pkg, {"n": 0})
            row["n"] = int(row.get("n") or 0) + 1
            row["at"] = now
            row["why"] = str(bad[pkg])[:200]
        else:
            fails.pop(pkg, None)
    return True


def tick(manager, night="", log=None, now=None, data_dir=None):
    """One look: plan and start what is missing. Rate-limited (every 10 minutes, at once after the site changed the config).
    Returns what it started, or None. Never raises."""
    try:
        return _tick(manager, night, log or (lambda *_: None), time.time() if now is None else now, data_dir)
    except Exception as e:  # noqa: BLE001 - an optional feature must never stop the agent
        try:
            (log or print)("auto models: %s" % e)
        except Exception:  # noqa: BLE001
            pass
        return None


def _tick(manager, night, log, now, data_dir):
    cfg = load(data_dir)
    if not cfg:
        return None
    if not _mem["force"] and (now - _mem["last"] < INTERVAL_S or now - _mem["born"] < FIRST_DELAY_S):
        return None
    if not manager.available():
        return None
    _mem["last"], _mem["force"] = now, False
    state = _load_state(data_dir)
    if _record_run(manager, state, now):
        _save_state(state, data_dir)
    st = manager.refresh(force=True) or {}
    rows = st.get("packages") or {}
    active = {p for p in rows if manager.downloading(p) or manager.waiting_for(p)} | set(manager.queue)
    res = plan(rows, cfg, free_bytes_of(st), state.get("fails"), now, active)
    _mem["report"] = {"enabled": bool(cfg.get("enabled")), "reserve_gb": cfg["reserve_gb"], "states": dict(res["states"]),
                      "free_mb": None if free_bytes_of(st) is None else int(free_bytes_of(st) // 2 ** 20), "at": now,
                      "why": {p: f.get("why", "") for p, f in (state.get("fails") or {}).items() if f.get("n", 0) >= MAX_FAILS}}
    if not cfg.get("enabled") or manager.running():
        return None
    # one kind per tick: the next tick (after this run) starts the other kind with its own window
    if res["small"]:
        log("auto models: starting %s (needed by an enabled feature)" % ", ".join(res["small"]))
        manager.start(res["small"], "automatic: needed by an enabled feature")
        return res["small"]
    if res["big"]:
        log("auto models: %s are big - they wait for the night window (%s Tehran time)" % (", ".join(res["big"]), night or "any time"))
        manager.start(res["big"], "automatic: big package, night window", window=night or None)
        return res["big"]
    return None


def report(manager=None):
    """The `auto` block of the heartbeat: per package state for the panel. Never raises."""
    try:
        cfg = load()
        if not cfg:
            return None
        rep = dict(_mem["report"] or {"enabled": bool(cfg.get("enabled")), "reserve_gb": cfg["reserve_gb"], "states": {}})
        states = dict(rep.get("states") or {})
        if manager is not None:
            for p in cfg.get("packages") or []:
                if manager.downloading(p):
                    states[p] = "downloading"
                elif manager.waiting_for(p):
                    states[p] = "waiting_window"
                elif p in manager.queue:
                    states[p] = "queued"
        rep["states"] = states
        rep["wanted"] = len(cfg.get("packages") or [])
        return rep
    except Exception:  # noqa: BLE001
        return None
