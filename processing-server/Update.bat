@echo off&title UpMarket - update to the newest version&set "PYTHONIOENCODING=utf-8"&set "NM_PY=python"&where python >nul 2>nul||(set "NM_PY=py -3"&where py >nul 2>nul||(echo [!] Python was not found. Install Python 3.10 or newer from python.org and tick "Add python to PATH", then double-click this file again.&pause&exit /b 1))&call %%NM_PY%% -x "%~f0" %*&pause&exit /b 0
"""UpMarket / NMarketing - Update.bat: bring this processing-server folder to the NEWEST version from the site.

HOW TO USE: put this one file in the folder that has START.bat (or in an old copy, e.g. "Main V4\\processing-server") and
double-click it. Run it again whenever you want the newest version. It needs Python 3.8+ (the same Python START.bat uses).

What it does, every time:
  1. asks the site for the newest update tool (a few KB) and runs it - so even a very old folder gets the newest logic;
  2. downloads the newest code from the site (the site builds it from the same files that go to GitHub, so it is never
     older than GitHub's main) - resumable, retried with growing waits for up to 30 minutes, size + sha256 checked;
  3. replaces only the code files in place (every replaced file is kept in <data folder>\\updates\\backup-<time>\\),
     keeps node.json / site.json / your settings; models and Python environments are NOT downloaded again;
  4. in an old copy (agent 1.x, everything downloaded inside the folder) it MOVES those downloads into the data folder
     %USERPROFILE%\\NMarketing-data (a rename: instant, nothing copied, nothing deleted) and keeps the node's identity;
  5. a node that is still running from an old folder must be closed first (it asks; or run Update.bat --stop-node).
Options: --check (only say if an update waits), --stop-node, --no-migrate, --rollback.
This file is ONE batch line + this Python text. The batch line is read in full before anything runs, so an update may
replace this very file while it works. Two rules for whoever edits line 1: it must never contain an `if` (cmd skips the
rest of the line, including `exit /b`, when an `if` is false and would then read the Python text below as batch commands),
and nothing may come after `exit /b 0`. tests\\test_data_and_update.py runs it for real in cmd.exe.
Console text is ASCII on purpose (the Windows console garbles Persian).
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

DEFAULT_SITE = "http://87.107.160.17:8040"
ROOT = os.path.dirname(os.path.abspath(__file__))
UA = "nm-update-bat/1.0"
BOOT_FILES = ("update.py", "nm_data.py", "nm_fetch.py")


def say(msg=""):
    print(msg, flush=True)


def read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def first_line(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                if line.strip() and not line.strip().startswith("#"):
                    return line.strip().strip('"')
    except OSError:
        pass
    return ""


def data_folders():
    """Where this computer may keep node.json: NM_DATA, the folder remembered by an earlier start, the default."""
    home = os.path.expanduser("~")
    out = []
    if os.environ.get("NM_DATA", "").strip():
        out.append(os.path.expandvars(os.environ["NM_DATA"].strip().strip('"')))
    mark = first_line(os.path.join(ROOT, "nm-data.txt"))
    if mark:
        out.append(mark if os.path.isabs(mark) else os.path.join(ROOT, mark))
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    pointed = first_line(os.path.join(local, "NMarketing", "data-root.txt"))
    if pointed:
        out.append(os.path.expandvars(pointed))
    out.append(os.path.join(home, "NMarketing-data"))
    return out


def find_site():
    if os.environ.get("NM_SITE", "").strip():
        return os.environ["NM_SITE"].strip().rstrip("/")
    for folder in data_folders() + [ROOT]:
        site = read_json(os.path.join(folder, "node.json")).get("site")
        if site:
            return str(site).strip().rstrip("/")
    site = read_json(os.path.join(ROOT, "site.json")).get("site")
    return str(site or DEFAULT_SITE).strip().rstrip("/")


def get(url, timeout=40, start=0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=%d-" % start} if start else {"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def get_bundle(site, minutes=6):
    """The newest update tool (update.py, nm_data.py, nm_fetch.py: a few dozen KB) from the site, checked by sha256.
    Resumes and waits (3, 6, 12, 24, 30 s ...) up to `minutes` while the site is not reachable."""
    base = os.path.join(tempfile.gettempdir(), "nm-bootstrap")
    os.makedirs(base, exist_ok=True)
    deadline = time.time() + minutes * 60
    wait, last = 3, "?"
    while True:
        try:
            with get(site + "/api/v1/compute/update/bootstrap/?info=1") as r:
                info = json.loads(r.read().decode("utf-8"))
            sha, size = info["sha256"], int(info["size"])
            folder = os.path.join(base, sha[:16])
            if all(os.path.isfile(os.path.join(folder, n)) for n in BOOT_FILES):
                return folder
            part = os.path.join(base, "bootstrap-%s.zip.part" % sha[:16])
            have = os.path.getsize(part) if os.path.isfile(part) else 0
            if have > size:
                have = 0
            if have < size:
                with get(site + "/api/v1/compute/update/bootstrap/", start=have) as r, open(part, "ab" if have and r.status == 206 else "wb") as fh:
                    for chunk in iter(lambda: r.read(64 * 1024), b""):
                        fh.write(chunk)
            h = hashlib.sha256()
            with open(part, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if os.path.getsize(part) != size or h.hexdigest() != sha:
                os.remove(part)
                raise OSError("the update tool arrived damaged")
            os.makedirs(folder, exist_ok=True)
            with zipfile.ZipFile(part) as z:
                for name in BOOT_FILES:
                    with open(os.path.join(folder, name), "wb") as out:
                        out.write(z.read(name))
            os.remove(part)
            return folder
        except (urllib.error.URLError, OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
            last = str(getattr(e, "reason", None) or e)
        if time.time() + wait > deadline:
            raise RuntimeError("the site %s could not be reached (%s)" % (site, last))
        say("  the site is not answering (%s) - trying again in %d s" % (last[:80], wait))
        time.sleep(wait)
        wait = min(30, wait * 2)


def main():
    say("UpMarket update - folder: %s" % ROOT)
    site = find_site()
    say("Site: %s" % site)
    try:
        folder = get_bundle(site)
    except RuntimeError as e:
        if all(os.path.isfile(os.path.join(ROOT, n)) for n in BOOT_FILES):
            say("NOTE: %s - using the update tool already in this folder." % e)
            folder = ROOT
        else:
            say("[!] %s" % e)
            say("Nothing was changed. Check the internet connection (the site must open in a browser) and run this file again.")
            return 1
    sys.path.insert(0, folder)
    import update
    rc = update.main(["--bat", "--root", ROOT, "--default-site", site] + sys.argv[1:])
    say("")
    if rc == 0 and "--check" in sys.argv:
        pass
    elif rc == 0:
        say("Finished. Now start the node with START.bat (if its window is already open it restarts on the new code by itself).")
    else:
        say("The update did not finish - read the lines above. Nothing was broken; run this file again later (it continues).")
    return rc


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        say("Stopped by you.")
        code = 1
    sys.exit(code)
