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

    Update.bat                     check and update now
    python update.py --check       only say whether an update is waiting
    python update.py --auto        what START.bat runs on every start (quiet, short timeouts, never asks;
                                   NM_AUTO_UPDATE=0 turns it off)
    python update.py --rollback    put back the code from before the last update

A git checkout (with git installed) is updated with `git pull --ff-only` instead.
Python 3.8+ standard library only. Console text is English on purpose (the Windows console garbles Persian).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import nm_data  # noqa: E402

VERSION = "1.0"
PREFIX = "processing-server/"
KEEP_LOCAL = {"site.json"}          # once this computer has one, its own copy wins (the site URL may be edited here)
MAX_FAILURES = 2
KEEP_BACKUPS = 5
UA = "nm-node-updater/" + VERSION


class UpdateError(Exception):
    pass


# ───────────────────────────────────────────── small helpers

def data_dir():
    return nm_data.data_root(HERE)


def upd_dir():
    return os.path.join(data_dir(), "updates")


def state_path():
    return os.path.join(upd_dir(), "state.json")


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
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


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
    if sys.platform.startswith("win"):
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


def version_path(root=HERE):
    return os.path.join(root, ".nm-version.json")


def local_version(root=HERE):
    return load_json(version_path(root), {})


# ───────────────────────────────────────────── site

def site_and_token():
    """The site URL and this node's token: node.json in the data folder (an older layout kept it next to agent.py),
    NM_SITE / NM_TOKEN, site.json next to this file."""
    cfg = {}
    for p in (os.path.join(data_dir(), "node.json"), os.path.join(HERE, "node.json")):
        cfg = load_json(p, {})
        if cfg.get("token"):
            break
    site = (os.environ.get("NM_SITE") or cfg.get("site") or load_json(os.path.join(HERE, "site.json"), {}).get("site") or "")
    token = os.environ.get("NM_TOKEN") or cfg.get("token") or ""
    return str(site).strip().rstrip("/"), str(token).strip()


def _open(url, token, timeout):
    req = urllib.request.Request(url, headers={"Authorization": "Node " + token, "User-Agent": UA,
                                               "Accept": "application/json, application/zip, */*"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_manifest(site, token, timeout=30):
    try:
        with _open(site + "/api/v1/compute/update/", token, timeout) as r:
            m = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise UpdateError("the site did not accept this node's token (HTTP %s) - delete node.json in the data folder "
                              "and run START.bat again with the enrollment key" % e.code)
        raise UpdateError("the site answered HTTP %s" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError("site not reachable (%s)" % (getattr(e, "reason", None) or e))
    if not isinstance(m, dict) or not isinstance(m.get("files"), list) or not m.get("zip_sha256") or not m.get("id"):
        raise UpdateError("the site's answer is not an update manifest")
    return m


def download(site, token, manifest, folder, attempts=4, timeout=60, out=print):
    """The package zip, checked: size and sha256 must be what the manifest says. Returns its path."""
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, "package-%s.zip" % manifest["zip_sha256"][:16])
    if os.path.isfile(dest) and os.path.getsize(dest) == manifest.get("zip_size") and sha256_file(dest) == manifest["zip_sha256"]:
        return dest
    url = site + (manifest.get("url") or "/api/v1/compute/update/package/") + "?zip=" + manifest["zip_sha256"]
    last = None
    for attempt in range(1, attempts + 1):
        part = dest + ".part"
        try:
            with _open(url, token, timeout) as r, open(part, "wb") as fh:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    fh.write(b)
            size = os.path.getsize(part)
            if size != manifest.get("zip_size"):
                raise UpdateError("download incomplete: %d of %s bytes" % (size, manifest.get("zip_size")))
            got = sha256_file(part)
            if got != manifest["zip_sha256"]:
                raise UpdateError("checksum mismatch (got %s..., expected %s...)" % (got[:12], manifest["zip_sha256"][:12]))
            os.replace(part, dest)
            return dest
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code in (401, 403, 404, 410):
                break
        except (UpdateError, urllib.error.URLError, OSError) as e:
            last = str(getattr(e, "reason", None) or e)
        try:
            os.remove(part)
        except OSError:
            pass
        if attempt < attempts:
            out("  download attempt %d/%d failed (%s) - trying again" % (attempt, attempts, last))
            time.sleep(min(20, 3 * attempt))
    raise UpdateError("the package could not be downloaded: %s" % last)


# ───────────────────────────────────────────── plan / apply / roll back

def plan(manifest, root=HERE):
    """(to_write, to_retire): package files that differ here, and files of the previous update that the package no
    longer has (they are moved into the backup, never deleted)."""
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


def _restore_from(backup, root=HERE, out=print):
    """Put the files of a backup back in place; files the update added go to <backup>\\rejected\\."""
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


def apply(manifest, zip_path, write, retire, root=HERE, out=print):
    """Check every file in the zip first, back up what changes, then write file by file (each write is atomic). A
    failure half-way puts back what was already written. Returns the backup folder."""
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
    backup = os.path.join(upd_dir(), "backup-%s" % time.strftime("%Y%m%d-%H%M%S"))
    while os.path.exists(backup):
        backup += "x"
    have = local_version(root)
    info = {"from": have.get("version"), "from_id": have.get("id"), "to": manifest.get("version"),
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


def write_version(manifest, root=HERE):
    save_json(version_path(root), {
        "version": manifest.get("version"), "agent": manifest.get("agent"), "id": manifest["id"],
        "built": manifest.get("built"), "applied": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": sorted(f["path"] for f in manifest["files"])})


def _prune_backups(keep=KEEP_BACKUPS):
    try:
        olds = sorted(d for d in os.listdir(upd_dir()) if d.startswith("backup-"))
    except OSError:
        return
    for d in olds[:-keep]:
        shutil.rmtree(os.path.join(upd_dir(), d), ignore_errors=True)
    for f in os.listdir(upd_dir()):
        if f.startswith("package-") and f.endswith(".zip"):
            p = os.path.join(upd_dir(), f)
            if time.time() - os.path.getmtime(p) > 7 * 86400:
                try:
                    os.remove(p)
                except OSError:
                    pass


def rollback(out=print, reason="asked by hand"):
    st = load_json(state_path(), {})
    pending = st.get("pending") or st.get("last") or {}
    backup = pending.get("backup")
    if not backup or not os.path.isfile(os.path.join(backup, "rollback.json")):
        out("Nothing to roll back (no update backup found).")
        return 1
    info = _restore_from(backup, load_json(os.path.join(backup, "rollback.json"), {}).get("root") or HERE, out)
    bad = list(dict.fromkeys((st.get("bad") or []) + [pending.get("id")]))
    st.update(pending=None, last=None, bad=[b for b in bad if b][-20:],
              rolled_back={"id": pending.get("id"), "version": pending.get("version"), "reason": reason,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S"), "backup": backup})
    save_json(state_path(), st)
    out("Rolled back to the code from before the update (version %s). Run Update.bat to try the new version again."
        % (info.get("from") or "?"))
    return 0


# ───────────────────────────────────────────── START.bat hooks

def restart_flag():
    return os.path.join(upd_dir(), "restart.flag")


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
    if p["failures"] >= MAX_FAILURES:
        out("The updated node (version %s) stopped %d times before it reached the site - putting the previous code back."
            % (p.get("version"), p["failures"]))
        return rollback(out, reason="the agent stopped %d times after the update" % p["failures"])
    out("The updated node stopped before it reached the site (%d of %d) - trying once more." % (p["failures"], MAX_FAILURES))
    return 0


# ───────────────────────────────────────────── git checkout

def git_checkout():
    """(git, top folder) when this folder is a git checkout of the project and git is installed."""
    git = shutil.which("git")
    if not git:
        return None, None
    try:
        r = subprocess.run([git, "-C", HERE, "rev-parse", "--show-toplevel", "--show-prefix"], capture_output=True,
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

def run(auto=False, check_only=False, out=print, root=HERE):
    if auto and os.environ.get("NM_AUTO_UPDATE", "").strip() == "0":
        return 0
    git, top = git_checkout() if root == HERE else (None, None)
    if git:
        if auto:
            return 0                                  # a developer's checkout: never pulled automatically
        out("This folder is a git checkout (%s): updating with git pull --ff-only" % top)
        if check_only:
            return subprocess.call([git, "-C", top, "fetch", "--dry-run"])
        return 0 if subprocess.call([git, "-C", top, "pull", "--ff-only"]) == 0 else 1
    site, token = site_and_token()
    if not site or not token:
        out("This computer is not registered yet - run START.bat once (it asks for the enrollment key), then Update.bat.")
        return 0 if auto else 1
    os.makedirs(upd_dir(), exist_ok=True)
    lock = os.path.join(upd_dir(), "update.lock")
    other = load_json(lock, {}).get("pid")
    if other and int(other) != os.getpid() and pid_alive(other):
        out("Another update is running right now (process %s) - nothing to do." % other)
        return 0
    save_json(lock, {"pid": os.getpid(), "since": time.time()})
    try:
        try:
            manifest = fetch_manifest(site, token, timeout=12 if auto else 40)
        except UpdateError as e:
            out(("Update check skipped: %s" if auto else "UPDATE FAILED: %s") % e)
            return 0 if auto else 1
        write, retire = plan(manifest, root)
        have = local_version(root)
        if not write and not retire:
            if have.get("id") != manifest["id"]:
                write_version(manifest, root)
            out("The code is up to date (version %s)." % manifest.get("version"))
            return 0
        st = load_json(state_path(), {})
        if auto and manifest["id"] in (st.get("bad") or []):
            out("Version %s was rolled back on this computer before - not applied automatically (Update.bat applies it)."
                % manifest.get("version"))
            return 0
        out("Update: %s -> version %s (%d file(s) to replace%s)" % (
            ("version %s" % have["version"]) if have.get("version") else "this copy", manifest.get("version"), len(write),
            (", %d to retire" % len(retire)) if retire else ""))
        if check_only:
            return 0
        try:
            zpath = download(site, token, manifest, upd_dir(), out=out)
            backup = apply(manifest, zpath, write, retire, root, out)
        except (UpdateError, OSError, zipfile.BadZipFile) as e:
            out(("Update not applied: %s" if auto else "UPDATE FAILED: %s") % e)
            return 0 if auto else 1
        st = load_json(state_path(), {})
        st["pending"] = {"id": manifest["id"], "version": manifest.get("version"), "backup": backup, "failures": 0,
                         "confirmed": False, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        st["bad"] = [b for b in (st.get("bad") or []) if b != manifest["id"]]
        save_json(state_path(), st)
        _prune_backups()
        out("Updated to version %s. The replaced files are kept in %s" % (manifest.get("version"), backup))
        return 0
    finally:
        try:
            if load_json(lock, {}).get("pid") == os.getpid():
                os.remove(lock)
        except OSError:
            pass


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--agent-exited" in args:
        return agent_exited()
    if "--rollback" in args:
        return rollback()
    if "--confirm" in args:
        confirm()
        return 0
    return run(auto="--auto" in args, check_only="--check" in args)


if __name__ == "__main__":
    sys.exit(main())
