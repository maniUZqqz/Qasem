#!/usr/bin/env python3
"""After the split of the separate remote-access tool from NM (2026-11-16): is nothing of it left in the live tree, in the
node update packages, in the panel build or in the public mirror?  Read-only, except with --purge-old-packages.

    python3 deploy/nm/checks/remote_split_check.py [--root /var/www/NM/upmarket] [--repo /root/qasem-repo] [--purge-old-packages]

Exit code 0 = everything clear, 1 = something is left (each line says what). The names are built from pieces so that this
file is not a hit of its own search.
"""
import argparse
import json
import os
import subprocess
import sys
import zipfile

N = ("pc" + "-remote", "pc" + "_remote", "pc" + " remote", "pc" + "remote")
POINTER = ("processing/README-FA.md", "https://github.com/maniUZqqz/" + "Remote" + "-d")
SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", ".next", "media", "staticfiles", "vendor", "logs", "data", "models",
        "server-state"}
EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".json", ".md", ".bat", ".cmd", ".ps1", ".sh", ".txt", ".html", ".css",
       ".service", ".timer", ".conf", ".cfg", ".toml", ".yml", ".yaml", ".env", ".cron", ".ini"}
bad = 0


def say(ok, msg):
    global bad
    print(("OK    " if ok else "FAIL  ") + msg)
    if not ok:
        bad += 1


def has_needle(s):
    s = s.lower()
    return any(n in s for n in N)


def names_zip(path):
    try:
        with zipfile.ZipFile(path) as z:
            return [n for n in z.namelist() if has_needle(n)]
    except (OSError, zipfile.BadZipFile) as e:
        return ["<unreadable: %s>" % e]


def scan_tree(root, me):
    """(file names that match, 'path:line' of text mentions) - the pointer line in the node README is allowed."""
    names, lines = [], []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith("dist.") and x != "dist"]
        for f in files:
            if ".bak" in f or f.endswith((".pyc", ".pyo")):
                continue
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if has_needle(f):
                names.append(rel)
            if os.path.splitext(f)[1].lower() not in EXT or os.path.realpath(p) == me:
                continue
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            if not (has_needle(text) or "remote" + "-d" in text.lower()):
                continue
            for no, line in enumerate(text.splitlines(), 1):
                ll = line.lower()
                if (has_needle(ll) or "remote" + "-d" in ll) and not (rel == POINTER[0] and POINTER[1].lower() in ll):
                    lines.append("%s:%d" % (rel, no))
    return names, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/var/www/NM/upmarket")
    ap.add_argument("--repo", default="/root/qasem-repo")
    ap.add_argument("--purge-old-packages", action="store_true",
                    help="delete built node packages (data/processing-update/*.zip) that still contain it; they are caches that are rebuilt on demand")
    a = ap.parse_args()
    root = a.root

    names, lines = scan_tree(root, os.path.realpath(__file__))
    say(not names, "no file in the tree is named after it" + ("" if not names else ": " + ", ".join(names[:5])))
    say(not lines, "no code, doc or panel text mentions it (except the pointer to the separate repository)"
        + ("" if not lines else ": " + ", ".join(lines[:8])))

    dist = os.path.join(root, "frontend", "dist")
    hits = []
    for d, _dirs, files in os.walk(dist):
        for f in files:
            if f.endswith((".js", ".html", ".css", ".json")):
                try:
                    with open(os.path.join(d, f), encoding="utf-8", errors="ignore") as fh:
                        if has_needle(fh.read()):
                            hits.append(f)
                except OSError:
                    pass
    say(not hits, "the built panel (frontend/dist) has no mention" + ("" if not hits else ": " + ", ".join(hits[:5])))

    pu = os.path.join(root, "data", "processing-update")
    cur = None
    try:
        with open(os.path.join(pu, "manifest.json"), encoding="utf-8") as fh:
            m = json.load(fh)
        cur = m.get("zip_name")
        bad_rows = [r["path"] for r in m.get("files", []) if has_needle(r["path"])]
        say(not bad_rows, "the current node-package manifest lists no such file (%d files, built %s)" % (len(m.get("files", [])), m.get("built")))
    except (OSError, ValueError):
        print("WARN  no built manifest yet (data/processing-update/manifest.json): it is built by the next node request or panel visit")
    stale = []
    if os.path.isdir(pu):
        for f in sorted(os.listdir(pu)):
            if f.endswith(".zip") and (f.startswith("package-") or f.startswith("bootstrap-")):
                found = names_zip(os.path.join(pu, f))
                if found:
                    stale.append(f)
                    if a.purge_old_packages and f != cur:
                        os.remove(os.path.join(pu, f))
                        print("PURGE removed old build %s (it contained %s)" % (f, ", ".join(found)))
    left = [f for f in stale if os.path.exists(os.path.join(pu, f))]
    say(not left, "no built node package (package-*.zip / bootstrap-*.zip) contains it"
        + ("" if not left else ": %s  (rerun with --purge-old-packages after the new package was built)" % ", ".join(left)))

    if os.path.isdir(os.path.join(a.repo, ".git")):
        tree = subprocess.run(["git", "-C", a.repo, "ls-tree", "-r", "--name-only", "HEAD"], capture_output=True, text=True).stdout.splitlines()
        found = [t for t in tree if has_needle(t)]
        say(not found, "the public mirror's HEAD (%s) has no such file%s" % (a.repo, "" if not found else ": " + ", ".join(found)
                                                                        + "  (run deploy/nm/git-autopush.sh)"))
        hist = subprocess.run(["git", "-C", a.repo, "log", "--all", "--oneline", "--", "processing-server/PC" + "-Remote-Setup.bat"],
                              capture_output=True, text=True).stdout.splitlines()
        if hist:
            print("WARN  the mirror's HISTORY still has the old setup file in %d commit(s); its invitation key must be treated as public "
                  "(the separate tool's server: `pc revoke <id>` once its setup file has been handed over)" % len(hist))
    else:
        print("WARN  no mirror checkout at %s: skipped" % a.repo)

    print("RESULT " + ("ALL CLEAR" if not bad else "%d problem(s)" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
