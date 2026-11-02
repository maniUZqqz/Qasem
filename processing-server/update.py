#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Update this processing-server folder in place - no git, no command line, no questions (Update.bat runs it).

The site serves the current package of the processing server. This script compares it with this folder file by file
(sha256), downloads it once and checks it (size + sha256 of the zip and of every file in it), keeps every file it
replaces in <data folder>\\updates\\backup-<time>\\ and writes the new files in place. The data folder (models, Python
environments, node.json, the editors ...) is never touched.

A running START.bat notices the new code and restarts the node by itself when its current job is done. If the updated
node stops twice before it ever reached the site, START.bat puts the previous code back (and does not apply that
version again by itself).

    Update.bat                     check and update now (what you double-click; also works in a folder of agent 1.x:
                                   it stops a running old node, updates, and MOVES the downloads into the data folder)
    python update.py --check       only say whether an update is waiting
    python update.py --auto        what START.bat runs on every start (quiet, short timeouts, never asks;
                                   NM_AUTO_UPDATE=0 turns it off)
    python update.py --rollback    put back the code from before the last update

Options for Update.bat: --root <folder> (the folder to update; Update.bat passes its own), --stop-node (stop a running
old node without asking), --no-migrate (do not move the downloads of an old copy into the data folder).
A git checkout (with git installed) is updated with `git pull --ff-only` instead.
Python 3.8+ standard library only. Console text is English on purpose (the Windows console garbles Persian).
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))     # the folder being updated (Update.bat's --root replaces it)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import nm_data  # noqa: E402
import nm_fetch  # noqa: E402

VERSION = "1.1"
PREFIX = "processing-server/"
KEEP_LOCAL = {"site.json"}          # once this computer has one, its own copy wins (the site URL may be edited here)
MAX_FAILURES = 2
KEEP_BACKUPS = 5
UA = "nm-node-updater/" + VERSION
IS_WIN = sys.platform.startswith("win")
STALL_AUTO = 90                     # START.bat: a quiet check must not hold the node back
STALL_MANUAL = 1800                 # Update.bat: a bad line gets half an hour without a single byte before it gives up
STALL_PANEL = 600                   # the panel's update job (a job has its own time limit)


class UpdateError(Exception):
    pass


# ───────────────────────────────────────────── small helpers

def _root(root=None):
    return root or HERE


def data_dir(root=None):
    return nm_data.data_root(_root(root))


def upd_dir(root=None):
    return os.path.join(data_dir(root), "updates")


def state_path(root=None):
    return os.path.join(upd_dir(root), "state.json")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if v is not None else default
    except (OSError, ValueError):
        return {} if default is None else default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def sha256_file(path):
    return nm_fetch.sha256_file(path, 1 << 20)


def safe_join(root, rel):
    rel = str(rel).replace("\\", "/")
    parts = rel.split("/")
    if not rel or rel.startswith("/") or ":" in rel or ".." in parts or "" in parts:
        raise UpdateError("unsafe path in the package: %r" % rel)
    return os.path.join(root, *parts)


def _replace(tmp, dest, attempts=6):
    """os.replace with a few retries: an antivirus or an editor may hold the file for a moment."""
    for i in range(attempts):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.5 * (i + 1))


def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if IS_WIN:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def version_path(root=None):
    return os.path.join(_root(root), ".nm-version.json")


def local_version(root=None):
    return load_json(version_path(root), {})


def _vtuple(v):
    try:
        return tuple(int(x) for x in str(v or "0").split(".")[:3])
    except ValueError:
        return (0,)


def agent_version(root=None):
    """VERSION written in agent.py of the folder (None when there is no agent.py)."""
    try:
        with open(os.path.join(_root(root), "agent.py"), encoding="utf-8", errors="replace") as fh:
            m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', fh.read(200000), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


# ───────────────────────────────────────────── site

def site_and_token(root=None, default_site=""):
    """The site URL and this node's token: node.json in the data folder (an older layout kept it next to agent.py),
    NM_SITE / NM_TOKEN, site.json next to this file, then default_site (what Update.bat found out itself)."""
    root = _root(root)
    cfg = {}
    for p in (os.path.join(data_dir(root), "node.json"), os.path.join(root, "node.json")):
        cfg = load_json(p, {})
        if cfg.get("token"):
            break
    site = (os.environ.get("NM_SITE") or cfg.get("site") or load_json(os.path.join(root, "site.json"), {}).get("site")
            or default_site or "")
    token = os.environ.get("NM_TOKEN") or cfg.get("token") or ""
    return str(site).strip().rstrip("/"), str(token).strip()


def _open(url, token, timeout):
    req = urllib.request.Request(url, headers={"Authorization": "Node " + token, "User-Agent": UA,
                                               "Accept": "application/json, application/zip, */*"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_manifest(site, token, timeout=30, tries=1, out=None):
    """The package list. `tries` > 1 waits and asks again while the site is unreachable or answers 5xx (a restart of
    the site takes a few seconds); a refused token or any other HTTP answer stops at once."""
    last = None
    for i in range(max(1, tries)):
        try:
            with _open(site + "/api/v1/compute/update/", token, timeout) as r:
                m = json.loads(r.read().decode("utf-8"))
            if not isinstance(m, dict) or not isinstance(m.get("files"), list) or not m.get("zip_sha256") or not m.get("id"):
                raise UpdateError("the site's answer is not an update manifest")
            return m
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise UpdateError("the site did not accept this node's token (HTTP %s) - delete node.json in the data folder "
                                  "and run START.bat again with the enrollment key" % e.code)
            last = "the site answered HTTP %s" % e.code
            if e.code < 500:
                break
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = "site not reachable (%s)" % (getattr(e, "reason", None) or e)
        if i + 1 < tries:
            wait = min(60, 5 * 2 ** i)
            if out:
                out("  %s - asking again in %d s" % (last, wait))
            time.sleep(wait)
    raise UpdateError(last or "the site did not answer")


def enroll(site, key, out=print, root=None):
    """Register this computer with the enrollment key from the panel; node.json is written next to agent.py (the
    data folder takes it over when the downloads are moved there). Returns the token."""
    name = "".join(ch for ch in (os.environ.get("NM_NODE") or socket.gethostname()) if ch.isalnum() or ch in "-_.")[:60] or "node"
    body = json.dumps({"key": key, "name": name, "hostname": socket.gethostname()}).encode("utf-8")
    req = urllib.request.Request(site + "/api/v1/compute/enroll/", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise UpdateError("the enrollment key was refused (HTTP %s) - copy it again from the panel "
                          "(Tools > Processing servers > Register a new server)" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError("site not reachable (%s)" % (getattr(e, "reason", None) or e))
    path = os.path.join(_root(root), "node.json")
    save_json(path, {"site": site, "token": d["token"], "name": d["name"]})
    out("Registered as node '%s' (node.json saved)." % d["name"])
    return d["token"]


def download(site, token, manifest, folder, attempts=4, timeout=60, out=print, stall=STALL_MANUAL):
    """The package zip, checked: size and sha256 must be what the manifest says. Returns its path. Resumes (HTTP Range)
    after every break and retries with growing waits until `stall` seconds pass without a single byte."""
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, "package-%s.zip" % manifest["zip_sha256"][:16])
    url = site + (manifest.get("url") or "/api/v1/compute/update/package/") + "?zip=" + manifest["zip_sha256"]
    try:
        nm_fetch.fetch_with_progress(url, dest, out=out, headers={"Authorization": "Node " + token}, size=manifest.get("zip_size"),
                                     sha256=manifest["zip_sha256"], stall=stall, timeout=timeout, label="package",
                                     sleep=lambda s: time.sleep(s))
    except nm_fetch.FetchError as e:
        raise UpdateError("the package could not be downloaded: %s" % e)
    return dest


# ───────────────────────────────────────────── plan / apply / roll back

def plan(manifest, root=None):
    """(to_write, to_retire): package files that differ here, and files of the previous update that the package no
    longer has (they are moved into the backup, never deleted)."""
    root = _root(root)
    write = []
    for f in manifest["files"]:
        dest = safe_join(root, f["path"])
        if os.path.isfile(dest):
            if f["path"] in KEEP_LOCAL:
                continue
            if os.path.getsize(dest) == f["size"] and sha256_file(dest) == f["sha256"]:
                continue
        write.append(f)
    now = {f["path"] for f in manifest["files"]}
    retire = [p for p in local_version(root).get("files") or [] if p not in now and p not in KEEP_LOCAL
              and os.path.isfile(safe_join(root, p))]
    return write, retire


def _restore_from(backup, root=None, out=print):
    """Put the files of a backup back in place; files the update added go to <backup>\\rejected\\."""
    root = _root(root)
    info = load_json(os.path.join(backup, "rollback.json"), {})
    for rel in info.get("restore") or []:
        src = os.path.join(backup, "files", *rel.split("/"))
        dest = safe_join(root, rel)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".nm-old"
            shutil.copy2(src, tmp)
            _replace(tmp, dest)
    for rel in info.get("added") or []:
        dest = safe_join(root, rel)
        if os.path.isfile(dest):
            target = os.path.join(backup, "rejected", *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _replace(dest, target)
    old = info.get("version_file")
    if old:
        save_json(version_path(root), old)
    elif os.path.isfile(version_path(root)):
        _replace(version_path(root), os.path.join(backup, "rejected-version.json"))
    return info


def apply(manifest, zip_path, write, retire, root=None, out=print):
    """Check every file in the zip first, back up what changes, then write file by file (each write is atomic). A
    failure half-way puts back what was already written. Returns the backup folder."""
    root = _root(root)
    blobs = {}
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for f in write:
            member = PREFIX + f["path"]
            if member not in names:
                raise UpdateError("the package lacks %s" % f["path"])
            data = z.read(member)
            if len(data) != f["size"] or hashlib.sha256(data).hexdigest() != f["sha256"]:
                raise UpdateError("%s in the package does not match its checksum" % f["path"])
            blobs[f["path"]] = data
    backup = os.path.join(upd_dir(root), "backup-%s" % time.strftime("%Y%m%d-%H%M%S"))
    while os.path.exists(backup):
        backup += "x"
    have = local_version(root)
    info = {"from": have.get("version") or agent_version(root), "from_id": have.get("id"), "to": manifest.get("version"),
            "to_id": manifest["id"], "restore": [], "added": [], "retired": [], "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version_file": have or None, "root": root}
    for f in write:
        dest = safe_join(root, f["path"])
        if os.path.isfile(dest):
            b = os.path.join(backup, "files", *f["path"].split("/"))
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(dest, b)
            info["restore"].append(f["path"])
        else:
            info["added"].append(f["path"])
    for rel in retire:
        b = os.path.join(backup, "files", *rel.split("/"))
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.copy2(safe_join(root, rel), b)
        info["restore"].append(rel)
        info["retired"].append(rel)
    save_json(os.path.join(backup, "rollback.json"), info)
    written = []
    try:
        for f in write:
            dest = safe_join(root, f["path"])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".nm-new"
            with open(tmp, "wb") as fh:
                fh.write(blobs[f["path"]])
            _replace(tmp, dest)
            written.append(f["path"])
        for rel in retire:
            target = os.path.join(backup, "retired", *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _replace(safe_join(root, rel), target)
    except OSError as e:
        out("  writing failed (%s) - putting the previous files back" % e)
        partial = dict(info, restore=[r for r in info["restore"] if r in written or r in retire],
                       added=[a for a in info["added"] if a in written])
        save_json(os.path.join(backup, "rollback.json"), partial)
        _restore_from(backup, root, out)
        raise UpdateError("could not write the new code (%s); nothing was changed" % e)
    write_version(manifest, root)
    return backup


def write_version(manifest, root=None):
    save_json(version_path(root), {
        "version": manifest.get("version"), "agent": manifest.get("agent"), "id": manifest["id"],
        "built": manifest.get("built"), "applied": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": sorted(f["path"] for f in manifest["files"])})


def _prune_backups(keep=KEEP_BACKUPS, root=None):
    try:
        olds = sorted(d for d in os.listdir(upd_dir(root)) if d.startswith("backup-"))
    except OSError:
        return
    for d in olds[:-keep]:
        shutil.rmtree(os.path.join(upd_dir(root), d), ignore_errors=True)
    for f in os.listdir(upd_dir(root)):
        if f.startswith("package-") and (f.endswith(".zip") or ".zip." in f):
            p = os.path.join(upd_dir(root), f)
            if time.time() - os.path.getmtime(p) > 7 * 86400:
                try:
                    os.remove(p)
                except OSError:
                    pass


def rollback(out=print, reason="asked by hand", root=None):
    st = load_json(state_path(root), {})
    pending = st.get("pending") or st.get("last") or {}
    backup = pending.get("backup")
    if not backup or not os.path.isfile(os.path.join(backup, "rollback.json")):
        out("Nothing to roll back (no update backup found).")
        return 1
    info = _restore_from(backup, load_json(os.path.join(backup, "rollback.json"), {}).get("root") or _root(root), out)
    bad = list(dict.fromkeys((st.get("bad") or []) + [pending.get("id")]))
    st.update(pending=None, last=None, bad=[b for b in bad if b][-20:],
              rolled_back={"id": pending.get("id"), "version": pending.get("version"), "reason": reason,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S"), "backup": backup})
    save_json(state_path(root), st)
    out("Rolled back to the code from before the update (version %s). Run Update.bat to try the new version again."
        % (info.get("from") or "?"))
    if _vtuple(info.get("from")) < (2, 0) and pending.get("moved_data"):
        out("NOTE: that older version keeps its models next to the code, and they were moved into the data folder %s - "
            "the older version will not find them there." % data_dir(root))
    return 0


# ───────────────────────────────────────────── START.bat hooks

def restart_flag(root=None):
    return os.path.join(upd_dir(root), "restart.flag")


def request_restart(reason="code updated"):
    """The agent writes this before it exits to restart on new code, so START.bat does not count it as a crash."""
    try:
        save_json(restart_flag(), {"reason": reason, "at": time.time()})
    except OSError:
        pass


def confirm():
    """The updated agent reached the site (or ran for a while): this update is good."""
    st = load_json(state_path(), {})
    p = st.get("pending")
    if p and not p.get("confirmed"):
        p["confirmed"] = True
        p["confirmed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        st["last"], st["pending"] = p, None
        save_json(state_path(), st)
        return True
    return False


def agent_exited(out=print):
    """START.bat calls this every time the agent stops. An update that never reached the site and stops twice is
    rolled back."""
    if os.path.isfile(restart_flag()):
        try:
            os.remove(restart_flag())
        except OSError:
            pass
        out("Restarting the node on the updated code ...")
        return 0
    st = load_json(state_path(), {})
    p = st.get("pending")
    if not p or p.get("confirmed"):
        return 0
    p["failures"] = int(p.get("failures") or 0) + 1
    save_json(state_path(), st)
    if p.get("moved_data"):
        out("The updated node stopped before it reached the site (%d). It is NOT rolled back automatically: the "
            "previous version (1.x) could not find its models any more (they were moved to %s). Read the lines above; "
            "Update.bat --rollback puts the old code back by hand." % (p["failures"], data_dir()))
        return 0
    if p["failures"] >= MAX_FAILURES:
        out("The updated node (version %s) stopped %d times before it reached the site - putting the previous code back."
            % (p.get("version"), p["failures"]))
        return rollback(out, reason="the agent stopped %d times after the update" % p["failures"])
    out("The updated node stopped before it reached the site (%d of %d) - trying once more." % (p["failures"], MAX_FAILURES))
    return 0


# ───────────────────────────────────────────── a node that is running from this folder

def _norm(s):
    return os.path.normcase(str(s or "")).replace("/", "\\")


def _processes():
    """[{pid, ppid, name, cmd}] of every running process (Windows: CIM through PowerShell; elsewhere: ps)."""
    out = []
    try:
        if IS_WIN:
            ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process | "
                  "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress")
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                               timeout=90, text=True, encoding="utf-8", errors="replace")
            rows = json.loads(r.stdout) if r.stdout.strip() else []
            for p in rows if isinstance(rows, list) else [rows]:
                out.append({"pid": int(p["ProcessId"]), "ppid": int(p["ParentProcessId"] or 0), "name": p.get("Name") or "",
                            "cmd": p.get("CommandLine") or ""})
        else:
            r = subprocess.run(["ps", "-eo", "pid=,ppid=,comm=,args="], capture_output=True, text=True, timeout=30)
            for line in r.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 3 and parts[0].isdigit():
                    out.append({"pid": int(parts[0]), "ppid": int(parts[1]), "name": parts[2],
                                "cmd": parts[3] if len(parts) > 3 else ""})
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        pass
    return out


def running_nodes(root=None, procs=None):
    """Python processes that run <root>\\agent.py (the node), and the list of all processes they were found in."""
    procs = _processes() if procs is None else procs
    key = _norm(os.path.join(_root(root), "agent.py"))
    mine = [p for p in procs if p["pid"] != os.getpid() and "python" in p["name"].lower() and key in _norm(p["cmd"])]
    return mine, procs


def _taskkill(pid):
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=60)
    else:
        try:
            os.kill(int(pid), 15)
        except OSError:
            pass


def stop_nodes(mine, procs, out=print, root=None, wait_s=25):
    """Stop the node: first the window that runs START.bat (so its loop cannot start the agent again), then the agent.
    The job in progress is re-queued by the site. Returns True when nothing of it is left."""
    by_pid = {p["pid"]: p for p in procs}
    targets = []
    for p in mine:
        parent = by_pid.get(p["ppid"])
        if parent and parent["name"].lower().startswith("cmd"):
            targets.append(parent["pid"])
        targets.append(p["pid"])
    for pid in dict.fromkeys(targets):
        out("  stopping process %s" % pid)
        _taskkill(pid)
    t0 = time.time()
    while time.time() - t0 < wait_s:
        left, _ = running_nodes(root)
        if not left:
            time.sleep(1.0)                           # let Windows release the files the node had open
            return True
        time.sleep(1.0)
    return False


def _ask(question):
    if not (sys.stdin and sys.stdin.isatty()):
        return None
    try:
        return input(question).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def ensure_node_stopped(root, out, stop=False):
    """An agent 1.x cannot be replaced while it runs (it has no restart protocol and its START.bat would be rewritten
    under it); an agent 2.x restarts itself on new code. Returns True when it is fine to go on."""
    mine, procs = running_nodes(root)
    if not mine:
        return True
    ver = agent_version(root)
    if _vtuple(ver) >= (2, 0):
        out("A node (agent %s) is running from this folder: it restarts on the new code by itself when its job is done." % ver)
        return True
    out("")
    out("A processing node (agent %s, START.bat) is running from this folder (process %s)." % (ver or "1.x", mine[0]["pid"]))
    out("An old version cannot be replaced while it runs.")
    for attempt in range(6):
        if stop:
            out("Stopping it now (--stop-node); the job it is working on is given back to the site.")
            if stop_nodes(mine, procs, out, root):
                return True
            out("It did not stop.")
            return False
        ans = _ask("Close the START.bat window yourself (Ctrl+C there, then close it) and press Enter here - or type K and "
                   "press Enter to stop it from here (its current job is given back to the site): ")
        if ans is None:
            out("Nothing was changed: close the START.bat window first (or run this with --stop-node).")
            return False
        if ans.lower().startswith("k"):
            stop = True
            continue
        mine, procs = running_nodes(root)
        if not mine:
            return True
        out("It is still running (process %s)." % mine[0]["pid"])
    return False


# ───────────────────────────────────────────── moving the old downloads, local settings

def decide_data_root(root, out=print):
    """The data folder is chosen (and remembered) before anything is written, so the backups and the new identity go
    where the node will look for them."""
    chosen, _where = nm_data.configured(root)
    if chosen:
        return chosen
    chosen = nm_data.default_root(root, nm_data.find_old_installs(root))
    nm_data.remember(chosen)
    out("Data folder (models, Python environments, this node's identity): %s" % chosen)
    return chosen


def migrate_data(root, out=print):
    """Move what older copies of this node hold (including this very folder when it is an old 1.x copy) into the data
    folder - a rename, never a copy, never a delete - and keep the node's identity. Same code as START.bat's first step."""
    try:
        data, summary = nm_data.prepare(root, out=out)
    except Exception as e:  # noqa: BLE001 - START.bat repeats it; a problem here must not undo a good update
        out("NOTE: the downloads could not be moved now (%s); START.bat tries again on its next start." % e)
        return None
    return summary


def local_settings_note(backup, out=print):
    """START.bat is replaced by the new one; lines like `set NM_COMFY_BAT=...` the owner added are listed with where
    they belong now (START-local.bat is run by START.bat when it exists and is never replaced)."""
    old = os.path.join(backup, "files", "START.bat")
    try:
        with open(old, encoding="utf-8", errors="replace") as fh:
            lines = [ln.strip() for ln in fh if re.match(r'\s*set\s+"?NM_[A-Z_]+\s*=', ln, re.I)]
    except OSError:
        return
    if lines:
        out("Your old START.bat had these settings; put them in a file named START-local.bat next to START.bat "
            "(START.bat runs it and no update replaces it):")
        for ln in lines:
            out("    " + ln)


# ───────────────────────────────────────────── git checkout

def git_checkout(root=None):
    """(git, top folder) when this folder is a git checkout of the project and git is installed."""
    git = shutil.which("git")
    if not git:
        return None, None
    try:
        r = subprocess.run([git, "-C", _root(root), "rev-parse", "--show-toplevel", "--show-prefix"], capture_output=True,
                           text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None, None
    lines = [ln.strip() for ln in r.stdout.splitlines()]
    if r.returncode != 0 or not lines:
        return None, None
    prefix = lines[1] if len(lines) > 1 else ""
    if prefix not in ("", "processing-server/", "processing/"):
        return None, None
    return git, lines[0]


# ───────────────────────────────────────────── main

def run(auto=False, check_only=False, out=print, root=None, bat=False, stop_node=False, migrate=True, stall=None,
        default_site=""):
    """auto: START.bat's quiet check. bat: Update.bat by hand (asks questions, long retries, moves old downloads).
    The panel's node.update job and the tests call it with neither."""
    root = _root(root)
    if auto and os.environ.get("NM_AUTO_UPDATE", "").strip() == "0":
        return 0
    if stall is None:
        stall = STALL_AUTO if auto else (STALL_MANUAL if bat else STALL_PANEL)
    git, top = git_checkout(root)
    if git:
        if auto:
            return 0                                  # a developer's checkout: never pulled automatically
        out("This folder is a git checkout (%s): updating with git pull --ff-only" % top)
        if check_only:
            return subprocess.call([git, "-C", top, "fetch", "--dry-run"])
        return 0 if subprocess.call([git, "-C", top, "pull", "--ff-only"]) == 0 else 1
    if bat and not check_only:
        decide_data_root(root, out)
    site, token = site_and_token(root, default_site)
    if site and not token and bat:
        key = os.environ.get("NM_ENROLL_KEY", "").strip()
        if not key:
            out("This computer is not registered on %s yet." % site)
            key = _ask("Enrollment key (panel > Tools > Processing servers > Register a new server): ") or ""
        if key:
            try:
                token = enroll(site, key, out, root)
            except UpdateError as e:
                out("UPDATE FAILED: %s" % e)
                return 1
    if not site or not token:
        out("This computer is not registered yet - run START.bat once (it asks for the enrollment key), then Update.bat.")
        return 0 if auto else 1
    os.makedirs(upd_dir(root), exist_ok=True)
    lock = os.path.join(upd_dir(root), "update.lock")
    other = load_json(lock, {}).get("pid")
    if other and int(other) != os.getpid() and pid_alive(other):
        out("Another update is running right now (process %s) - nothing to do." % other)
        return 0
    save_json(lock, {"pid": os.getpid(), "since": time.time()})
    try:
        try:
            manifest = fetch_manifest(site, token, timeout=12 if auto else 40, tries=6 if bat else 1, out=out)
        except UpdateError as e:
            out(("Update check skipped: %s" if auto else "UPDATE FAILED: %s") % e)
            return 0 if auto else 1
        write, retire = plan(manifest, root)
        have = local_version(root)
        was = have.get("version") or agent_version(root)
        if not write and not retire:
            if have.get("id") != manifest["id"]:
                write_version(manifest, root)
            out("The code is up to date (version %s)." % manifest.get("version"))
            if bat and migrate and not check_only:
                _migrate_report(root, out)
            return 0
        st = load_json(state_path(root), {})
        if auto and manifest["id"] in (st.get("bad") or []):
            out("Version %s was rolled back on this computer before - not applied automatically (Update.bat applies it)."
                % manifest.get("version"))
            return 0
        out("Update: %s -> version %s (%d file(s) to replace%s)" % (
            ("version %s" % was) if was else "this copy", manifest.get("version"), len(write),
            (", %d to retire" % len(retire)) if retire else ""))
        if check_only:
            return 0
        if bat and not ensure_node_stopped(root, out, stop_node):
            out("UPDATE NOT DONE - nothing was changed.")
            return 1
        try:
            zpath = download(site, token, manifest, upd_dir(root), out=out, stall=stall)
            backup = apply(manifest, zpath, write, retire, root, out)
        except (UpdateError, OSError, zipfile.BadZipFile) as e:
            out(("Update not applied: %s" if auto else "UPDATE FAILED: %s") % e)
            return 0 if auto else 1
        st = load_json(state_path(root), {})
        old_layout = bool(bat and migrate and _vtuple(was) < (2, 0))
        st["pending"] = {"id": manifest["id"], "version": manifest.get("version"), "backup": backup, "failures": 0,
                         "confirmed": False, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "moved_data": old_layout}
        st["bad"] = [b for b in (st.get("bad") or []) if b != manifest["id"]]
        save_json(state_path(root), st)
        _prune_backups(root=root)
        out("Updated to version %s. The replaced files are kept in %s" % (manifest.get("version"), backup))
        local_settings_note(backup, out)
        if bat and migrate:
            _migrate_report(root, out)
        return 0
    finally:
        try:
            if load_json(lock, {}).get("pid") == os.getpid():
                os.remove(lock)
        except OSError:
            pass


def _migrate_report(root, out):
    summary = migrate_data(root, out)
    if summary is None:
        return
    if summary.get("busy") or summary.get("other_drive") or summary.get("failed"):
        out("Some downloads were not moved (see above); START.bat tries again on its next start.")
    elif summary.get("moved"):
        out("Moved %d item(s) into the data folder %s - nothing was downloaded again." % (len(summary["moved"]), summary["root"]))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    global HERE
    if "--root" in args:
        i = args.index("--root")
        HERE = os.path.abspath(args[i + 1])
        del args[i:i + 2]
    default_site = ""
    if "--default-site" in args:
        i = args.index("--default-site")
        default_site = args[i + 1].rstrip("/")
        del args[i:i + 2]
    if "--agent-exited" in args:
        return agent_exited()
    if "--rollback" in args:
        return rollback()
    if "--confirm" in args:
        confirm()
        return 0
    bat = "--bat" in args
    return run(auto="--auto" in args, check_only="--check" in args, bat=bat, stop_node="--stop-node" in args,
               migrate="--no-migrate" not in args, default_site=default_site)


if __name__ == "__main__":
    sys.exit(main())
