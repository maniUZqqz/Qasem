#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where this node keeps everything that is downloaded, built or personal - apart from the code.

A processing-server folder is only CODE: a new copy (the GitHub zip, a zip from the panel) or Update.bat replaces it.
Everything heavy or personal lives in ONE data folder that every copy of the code finds again:

    %USERPROFILE%\\NMarketing-data\\
        python312\\  venvs\\  models\\  vendor\\ (MOSS-TTS, ACE-Step, Blender)  pip-cache\\  downloads-cache\\
        tools\\PersianAiKit\\   the photo / video / voice editors: their builds, models, Python env and YOUR cloned voices
        node.json (this computer's name + token)  services.json  downloads-local.json  logs\\  work\\  data\\  updates\\

Which folder (first match wins):
    1. the environment variable NM_DATA
    2. nm-data.txt next to this file (one line: the folder; relative = relative to this folder)
    3. the folder chosen the first time, remembered in %LOCALAPPDATA%\\NMarketing\\data-root.txt (so a new copy of the
       code anywhere on the computer finds it)
    4. %USERPROFILE%\\NMarketing-data - or <drive>:\\NMarketing-data when the downloads of an older copy sit on another
       drive (a move inside one drive is instant; nothing is ever copied)

The first start after the change MOVES the downloads of older copies (this folder, its neighbours, the Desktop,
Downloads, Documents, the top of each drive) into the data folder instead of downloading them again, keeps the node's
identity (node.json) and prints what was moved. Nothing is deleted; whatever cannot be moved stays where it is.

    python nm_data.py            data folder + move what older copies have (what START.bat does first)
    python nm_data.py --print    only print the data folder
    python nm_data.py --scan     list the older copies that were found (nothing is moved)

Python 3.8+ standard library only. Console text is English on purpose (the Windows console garbles Persian).
"""
import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import time

CODE = os.path.dirname(os.path.abspath(__file__))
IS_WIN = sys.platform.startswith("win")
DEFAULT_NAME = "NMarketing-data"
LOCAL_FILE = "nm-data.txt"
AGENT_MARK = b"UpMarket processing node"          # in the first lines of agent.py of every version
MOVED_MARK = ".nm-moved-to-data.json"             # written into an older copy after its downloads were moved

#: what belongs in the data folder, by its place in the old one-folder layout
TOP_ITEMS = ("python3*", "venvs", "models", "vendor", "pip-cache", "downloads-cache", "logs", "data",
             "node.json", "services.json", "downloads-local.json")
KIT = os.path.join("tools", "PersianAiKit")
#: kit folders an older copy made (builds, models, Python env, your recordings) - used when the code itself has no
#: kit to compare with; normally everything under tools\PersianAiKit that the code does not ship is moved
KIT_GENERATED = ("*/app", "*/models", "*/data", "Video/tools/ffmpeg", "Voice/voice/.venv", "Voice/voice/config.json")
#: moved as one piece or not at all (two halves of a Python environment or of a build never mix)
ATOMIC = ("python3*", "venvs/*", "vendor/*", "pip-cache", "downloads-cache", "data", "*/.venv", "*/.venv/*",
          "tools/PersianAiKit/*/app", "tools/PersianAiKit/Video/tools/ffmpeg")
SKIP = {"__pycache__"}


def _load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else ({} if default is None else default)
    except (OSError, ValueError):
        return {} if default is None else default


def _dump_json(path, obj, indent=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=indent)
    os.replace(tmp, path)


# ───────────────────────────────────────────── which folder

def pointer_path():
    """Remembers the chosen data folder for every copy of the code on this computer (per user)."""
    if os.environ.get("NM_DATA_POINTER"):
        return os.environ["NM_DATA_POINTER"]
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "NMarketing", "data-root.txt")
    return os.path.join(os.path.expanduser("~"), ".config", "nmarketing", "data-root.txt")


def _clean(path, base=CODE):
    path = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
    if not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    return os.path.normpath(os.path.abspath(path))


def _first_line(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                if line.strip() and not line.strip().startswith("#"):
                    return line.strip()
    except OSError:
        pass
    return None


def configured(code=CODE):
    """(folder, where it was set) or (None, None) when nothing chose a folder yet."""
    if os.environ.get("NM_DATA", "").strip():
        return _clean(os.environ["NM_DATA"]), "NM_DATA"
    line = _first_line(os.path.join(code, LOCAL_FILE))
    if line:
        return _clean(line, code), LOCAL_FILE
    line = _first_line(pointer_path())
    if line:
        return _clean(line), pointer_path()
    return None, None


def _drive(path):
    return os.path.splitdrive(os.path.abspath(path))[0].upper()


def default_root(code=CODE, sources=None):
    """%USERPROFILE%\\NMarketing-data, or the same name on the drive that holds an older copy's downloads."""
    base = os.path.join(os.path.expanduser("~"), DEFAULT_NAME)
    if not IS_WIN:
        return base
    for src in (find_old_installs(code) if sources is None else sources):
        if any(os.path.exists(os.path.join(src, n)) for n in ("models", "venvs")) or glob.glob(os.path.join(src, "python3*")):
            d = _drive(src)
            if d and d != _drive(base) and not d.startswith("\\\\"):
                return d + "\\" + DEFAULT_NAME
            break
    return base


def data_root(code=CODE):
    """The data folder (nothing is created or written here; prepare() does that)."""
    root, _where = configured(code)
    return root or default_root(code)


def remember(root):
    path = pointer_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(root + "\n")
        return True
    except OSError:
        return False


# ───────────────────────────────────────────── older copies

def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _inside(path, folder):
    p, f = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


def looks_like_install(folder):
    try:
        with open(os.path.join(folder, "agent.py"), "rb") as fh:
            return AGENT_MARK in fh.read(4000)
    except OSError:
        return False


def search_patterns(code=CODE):
    home = os.path.expanduser("~")
    parent = os.path.dirname(code)
    grand = os.path.dirname(parent)
    pats = [os.path.join(parent, "*"), os.path.join(grand, "*"), os.path.join(grand, "*", "*")]
    for name in ("Desktop", "Downloads", "Documents"):
        base = os.path.join(home, name)
        pats += [os.path.join(base, "*"), os.path.join(base, "*", "*"), os.path.join(base, "*", "*", "*")]
    pats += [os.path.join(home, "*"), os.path.join(home, "*", "*")]
    if IS_WIN:
        for letter in "CDEFG":
            root = letter + ":\\"
            if os.path.isdir(root):
                pats += [os.path.join(root, "*"), os.path.join(root, "*", "*")]
    return pats


def heavy_items(folder, code=CODE):
    """Relative paths in an older copy that belong in the data folder (top level + what its kit made)."""
    out = []
    for pat in TOP_ITEMS:
        for p in sorted(glob.glob(os.path.join(folder, pat))):
            if pat == "python3*" and not (os.path.isfile(os.path.join(p, "python.exe"))
                                          or os.path.isfile(os.path.join(p, "bin", "python3"))):
                continue                                  # python3* = a Python the downloader installed, nothing else
            out.append(os.path.basename(p))
    out += kit_extras(folder, code)
    return out


def kit_extras(folder, code=CODE):
    """What the kit of an older copy made by itself: everything under its tools\\PersianAiKit that the code does not
    ship (builds, models, Python env, recordings). The topmost such entry is returned (a folder stays one piece)."""
    src = os.path.join(folder, KIT)
    ref = os.path.join(code, KIT)
    if not os.path.isdir(src):
        return []
    if _same(folder, code) or not os.path.isdir(ref):
        out = []
        for pat in KIT_GENERATED:
            for p in sorted(glob.glob(os.path.join(src, *pat.split("/")))):
                out.append(os.path.relpath(p, folder))
        return out
    out = []

    def walk(rel):
        try:
            entries = sorted(os.listdir(os.path.join(src, rel)))
        except OSError:
            return
        for name in entries:
            if name in SKIP:
                continue
            r = os.path.join(rel, name) if rel else name
            mine, theirs = os.path.join(src, r), os.path.join(ref, r)
            if not os.path.exists(theirs):
                out.append(os.path.join(KIT, r))
            elif os.path.isdir(mine) and os.path.isdir(theirs) and not os.path.islink(mine):
                walk(r)
    walk("")
    return out


def find_old_installs(code=CODE, data=None, extra=()):
    """Folders that look like a processing-server copy and still hold downloads: this folder first, then the most
    recently used first."""
    seen, found = set(), []
    cands = [code] + list(extra)
    for pat in search_patterns(code):
        try:
            cands += [os.path.dirname(p) for p in glob.glob(os.path.join(pat, "agent.py"))]
        except OSError:
            pass
    for c in cands:
        key = os.path.normcase(os.path.abspath(c))
        if key in seen:
            continue
        seen.add(key)
        if data and (_inside(c, data) or _inside(data, c)):
            continue                                      # never move a folder into itself
        if not looks_like_install(c):
            continue
        if heavy_items(c, code):
            found.append(os.path.abspath(c))

    def mtime(*parts):
        try:
            return os.path.getmtime(os.path.join(*parts))
        except OSError:
            return 0

    def recency(f):                  # last used: its agent log / its registration, then the age of its code
        return max(mtime(f, "logs", "agent.log"), mtime(f, "node.json")), mtime(f, "agent.py")
    head = [f for f in found if _same(f, code)]
    rest = sorted((f for f in found if not _same(f, code)), key=recency, reverse=True)
    return head + rest


# ───────────────────────────────────────────── moving

def _atomic(rel):
    rel = rel.replace("\\", "/")
    return any(fnmatch.fnmatch(rel, pat) for pat in ATOMIC)


def _move(src, dst, rel, res):
    """Move src to dst: a rename (instant on one drive). An existing destination is never overwritten: folders are
    merged entry by entry (unless they must stay one piece), files that are already there stay in the older copy."""
    if os.path.lexists(dst):
        if os.path.isdir(src) and os.path.isdir(dst) and not os.path.islink(src) and not _atomic(rel):
            try:
                names = sorted(os.listdir(src))
            except OSError as e:
                res["failed"].append((src, str(e)))
                return
            for name in names:
                if name not in SKIP:
                    _move(os.path.join(src, name), os.path.join(dst, name), rel + "/" + name, res)
            return
        res["kept"].append(src)
        return
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)
        res["moved"].append((src, dst))
    except OSError as e:
        if getattr(e, "winerror", None) == 17 or getattr(e, "errno", None) == 18:   # another drive: never copy
            res["other_drive"].append(src)
        elif getattr(e, "winerror", None) in (5, 32) or isinstance(e, PermissionError):
            res["busy"].append(src)
        else:
            res["failed"].append((src, str(e)))


def _variants(path):
    p = os.path.abspath(path)
    return list(dict.fromkeys([p, p.replace("\\", "/"), p.replace("/", "\\")]))


def replace_prefix(text, old, new):
    """Every spelling of the old folder (any case on Windows, / or \\) -> the new one."""
    for o in _variants(old):
        sep = "/" if "/" in o and "\\" not in o else "\\"
        n = new.replace("\\", sep).replace("/", sep) if IS_WIN else new
        flags = re.IGNORECASE if IS_WIN else 0
        text = re.sub(re.escape(o), lambda _m: n, text, flags=flags)
    return text


def fix_venv(venv, old_root, new_root):
    """A moved Python environment still names its old place in pyvenv.cfg (its base Python) and in .pth / editable
    finder files; those few text files are rewritten. Returns the files changed."""
    changed = []
    files = [os.path.join(venv, "pyvenv.cfg")]
    for sp in glob.glob(os.path.join(venv, "Lib", "site-packages")) + glob.glob(os.path.join(venv, "lib", "python3*", "site-packages")):
        files += glob.glob(os.path.join(sp, "*.pth")) + glob.glob(os.path.join(sp, "__editable__*.py"))
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="surrogateescape") as fh:
                text = fh.read()
        except OSError:
            continue
        new = replace_prefix(text, old_root, new_root)
        if new != text:
            tmp = f + ".nm-tmp"
            with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as fh:
                fh.write(new)
            os.replace(tmp, f)
            changed.append(f)
    return changed


def _venvs_under(path):
    out = []
    for pat in ("pyvenv.cfg", "*/pyvenv.cfg", "*/*/pyvenv.cfg"):
        out += [os.path.dirname(p) for p in glob.glob(os.path.join(path, pat))]
    return out


def merge_download_state(old_root, data):
    """logs\\download-state.json remembers files whose sha256 was already checked, by full path: entries of an older
    copy are carried over under their new path (so 30 GB are not hashed again)."""
    target = os.path.join(data, "logs", "download-state.json")
    old_key = os.path.normcase(os.path.abspath(old_root))
    new_key = os.path.normcase(os.path.abspath(data))

    def rekey(k):
        return new_key + k[len(old_key):] if k.startswith(old_key + os.sep) else k

    load = _load_json
    before = load(target)
    mine = {rekey(k): v for k, v in before.items()}          # it may have just arrived with the older logs folder
    for k, v in load(os.path.join(old_root, "logs", "download-state.json")).items():
        mine.setdefault(rekey(k), v)                          # the older copy kept its own (logs already here)
    if mine == before:
        return 0
    try:
        _dump_json(target, mine, indent=0)
    except OSError:
        return 0
    return sum(1 for k in mine if k not in before)


def migrate(data, sources=None, code=CODE, out=print):
    """Move what older copies hold into the data folder. Returns a summary dict (moved, kept, busy, other_drive,
    failed, fixed_venvs, sources)."""
    res = {"moved": [], "kept": [], "busy": [], "other_drive": [], "failed": [], "fixed_venvs": [], "sources": []}
    if sources is None:
        sources = find_old_installs(code, data)
    for src in sources:
        if _inside(data, src) or _inside(src, data):
            continue                                      # never move a folder into itself
        done = _load_json(os.path.join(src, MOVED_MARK))
        items = heavy_items(src, code)
        if done and _same(done.get("data", ""), data):
            # already handled once: only what is missing in the data folder as a whole (no deep merge every start)
            items = [i for i in items if not os.path.lexists(os.path.join(data, i))]
        if not items:
            continue
        before = len(res["moved"])
        for rel in items:
            _move(os.path.join(src, rel), os.path.join(data, rel), rel.replace("\\", "/"), res)
        moved_here = res["moved"][before:]
        if moved_here:
            res["sources"].append(src)
            for _s, dst in moved_here:
                for venv in _venvs_under(dst):
                    if fix_venv(venv, src, data):
                        res["fixed_venvs"].append(venv)
            merge_download_state(src, data)
            try:
                _dump_json(os.path.join(src, MOVED_MARK), {"data": data, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                           "moved": [os.path.relpath(s, src) for s, _d in moved_here]})
            except OSError:
                pass
    return res


def folder_size(path, limit_s=20.0):
    total, t0 = 0, time.time()
    if os.path.isfile(path):
        return os.path.getsize(path)
    for d, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
        if time.time() - t0 > limit_s:
            return None
    return total


def human(n):
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" if unit in ("B", "KB") else "%.1f %s") % (n, unit)
        n /= 1024.0
    return "%.1f GB" % n


# ───────────────────────────────────────────── the kit runs from the data folder

def sync_kit(data, code=CODE):
    """The editors run from <data>\\tools\\PersianAiKit (their builds, models and recordings stay there); the code's
    tools\\PersianAiKit brings the source. New or changed source files are copied in; nothing is deleted.
    Returns the number of files copied (0 when nothing changed since the last time)."""
    src = os.path.join(code, KIT)
    dst = os.path.join(data, KIT)
    if not os.path.isdir(src) or _same(src, dst):
        return 0
    rows = []
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x not in SKIP and x not in ("bin", "obj"))
        for f in sorted(files):
            if f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            rows.append((os.path.relpath(p, src), st.st_size, int(st.st_mtime)))
    stamp = hashlib.sha1(json.dumps(rows).encode("utf-8")).hexdigest()[:16] + ":%d" % len(rows)
    marker = os.path.join(dst, ".nm-kit-sync.json")
    if _load_json(marker).get("stamp") == stamp and os.path.isdir(dst):
        return 0
    copied = 0
    for rel, size, mtime in rows:
        a, b = os.path.join(src, rel), os.path.join(dst, rel)
        try:
            if os.path.isfile(b):
                st = os.stat(b)
                if st.st_size == size and (int(st.st_mtime) == mtime or _same_bytes(a, b)):
                    continue
            os.makedirs(os.path.dirname(b), exist_ok=True)
            tmp = b + ".nm-tmp"
            shutil.copy2(a, tmp)
            os.replace(tmp, b)
            copied += 1
        except OSError:
            pass
    try:
        _dump_json(marker, {"stamp": stamp, "files": len(rows), "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    except OSError:
        pass
    return copied


def _same_bytes(a, b):
    import filecmp
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


# ───────────────────────────────────────────── one call for START.bat / the agent / the downloader

def prepare(code=CODE, out=print, quiet_if_nothing=True, sizes=True):
    """Choose and remember the data folder, move what older copies hold, bring the kit source. Fast when there is
    nothing to do. Returns (data folder, summary)."""
    root, where = configured(code)
    sources = None
    if not root:
        sources = find_old_installs(code)
        root = default_root(code, sources)
        remember(root)
        out("Data folder (models, Python environments, this node's identity): %s" % root)
    os.makedirs(root, exist_ok=True)
    if _inside(root, code) and not _same(root, code):
        out("NOTE: the data folder %s is inside the code folder; a new copy of the code will not see it" % root)
    summary = {"moved": [], "kept": [], "busy": [], "other_drive": [], "failed": [], "fixed_venvs": [], "sources": []}
    if not _same(root, code):
        if sources is None:
            sources = find_old_installs(code, root)
        summary = migrate(root, sources, code, out)
        report(summary, root, out, sizes=sizes)
        for src in sources:
            log = os.path.join(src, "logs", "agent.log")
            try:
                if not _same(src, code) and time.time() - os.path.getmtime(log) < 120:
                    out("WARNING: another copy seems to be running: %s (its log is fresh). Close its START.bat window -"
                        " two copies of one node must not run together." % src)
            except OSError:
                pass
    summary["kit_copied"] = sync_kit(root, code)
    summary["root"] = root
    return root, summary


def report(res, root, out=print, sizes=True):
    if not (res["moved"] or res["busy"] or res["other_drive"] or res["failed"]):
        return
    out("")
    out("Moving the downloads of older copies into %s (nothing is downloaded again, nothing is deleted):" % root)
    for src, dst in res["moved"]:
        size = folder_size(dst) if sizes else None
        out("  moved  %-48s %s" % (os.path.relpath(dst, root), ("(%s)" % human(size)) if size is not None else ""))
    if res["sources"]:
        out("  from   %s" % "; ".join(res["sources"]))
    if res["fixed_venvs"]:
        out("  Python environments re-pointed to the new place: %d" % len(res["fixed_venvs"]))
    for src in res["busy"]:
        out("  IN USE %s - close the older START.bat window (and ComfyUI / editors started by it), then run START.bat again" % src)
    for src in res["other_drive"]:
        out("  OTHER DRIVE %s - not moved (that would be a 40 GB copy). Either move it yourself, or put the drive's folder"
            " in nm-data.txt (e.g. D:\\NMarketing-data) and start again" % src)
    for src, why in res["failed"]:
        out("  FAILED %s: %s" % (src, why))
    if res["kept"]:
        olds = sorted({os.path.dirname(k) for k in res["kept"]})[:3]
        out("  %d item(s) were already in the data folder and stay in the older copy (%s ...): delete that folder"
            " yourself when you want the space back." % (len(res["kept"]), "; ".join(olds)))
    out("")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--print" in argv:
        print(data_root())
        return 0
    if "--scan" in argv:
        root = data_root()
        print("data folder: %s (%s)" % (root, configured()[1] or "default"))
        for f in find_old_installs(CODE, root):
            print("older copy: %s  ->  %s" % (f, ", ".join(heavy_items(f)) or "-"))
        return 0
    root, _s = prepare()
    print("Data folder: %s" % root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
