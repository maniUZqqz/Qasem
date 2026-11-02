#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One robust downloader for everything big this node fetches from the site (update package, editors, Blender ...).

Built for a flaky line (15 KB/s - 3 MB/s, resets, the site unreachable for a minute):

  * always resumes: the bytes already received are kept in <file>.part and the next try continues with an HTTP Range
    request (a server that ignores Range, or answers with a wrong range, makes it start again);
  * never gives up on a short outage: it retries with growing waits (3, 6, 12, 24, 48, then 60 s) and gives up only
    after STALL seconds (default 30 minutes) in which not one byte arrived; every received byte restarts that clock,
    so a long download on a bad line can still finish;
  * checks the result: the size (Content-Length, or the size the caller knows) and, when known, the sha256; a file
    that fails its checksum is set aside and fetched once more from the start;
  * a file that is already complete (size + sha256) is not fetched again; an older half-finished <file> (a curl run
    that wrote straight into it) is continued, not thrown away.

Python 3.8+ standard library only. Console text is English on purpose (the Windows console garbles Persian).

    python nm_fetch.py site-file <name on the site> <destination file>     {site}/3d/files/downloads/<name>, size and
                                                                           sha256 from {site}/api/v1/compute/downloads/
    python nm_fetch.py url <url> <destination file> [--size N] [--sha256 H]
    (NM_SITE / NM_TOKEN from the environment or --site / --token; --stall SECONDS; exit code 0 = file is complete)
"""
import hashlib
import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0"
STALL_DEFAULT = 1800          # seconds without a single new byte before giving up (about 30 minutes)
BACKOFF = (3, 6, 12, 24, 48, 60)
FATAL_HTTP = (400, 401, 403, 404, 405, 410)
UA = "nm-fetch/" + VERSION


class FetchError(Exception):
    """The download cannot succeed (or the stall budget is used up)."""


class _Retry(Exception):
    pass


def human(n):
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" if unit in ("B", "KB") else "%.1f %s") % (n, unit)
        n /= 1024.0
    return "%.1f GB" % n


def sha256_file(path, chunk=4 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def _replace(src, dst, attempts=8, sleep=time.sleep):
    """os.replace with a few retries: an antivirus scanning a fresh 400 MB file may hold it for a moment."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            sleep(1.0 + i)


def _open(url, headers, timeout, opener):
    h = {"User-Agent": UA}
    h.update(headers or {})
    return (opener or urllib.request.urlopen)(urllib.request.Request(url, headers=h), timeout=timeout)


def _total_of(content_range):
    """N of 'bytes a-b/N' or 'bytes */N'; None when absent or unknown ('*')."""
    if "/" in (content_range or ""):
        n = content_range.rsplit("/", 1)[1].strip()
        if n.isdigit():
            return int(n)
    return None


def probe_total(url, headers=None, timeout=30, opener=None):
    """Size of the file on the server (a 1-byte Range request), or None when it cannot be told right now."""
    try:
        with _open(url, dict(headers or {}, Range="bytes=0-0"), timeout, opener) as r:
            n = _total_of(r.headers.get("Content-Range"))
            if n is not None:
                return n
            if getattr(r, "status", 200) == 200 and (r.headers.get("Content-Length") or "").isdigit():
                return int(r.headers["Content-Length"])
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return _total_of(e.headers.get("Content-Range"))
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
        pass
    return None


def fetch(url, dest, headers=None, size=None, sha256=None, stall=STALL_DEFAULT, timeout=60, out=print, label=None,
          opener=None, sleep=time.sleep, clock=time.time):
    """Download url to dest (via dest.part). Returns "skipped" (it was already complete) or "downloaded".
    Raises FetchError when the file cannot be fetched (HTTP 4xx, a different file, or `stall` seconds without a byte)."""
    dest = os.path.abspath(dest)
    part = dest + ".part"
    label = label or os.path.basename(dest)
    sha256 = (sha256 or "").lower() or None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    if os.path.isfile(dest):
        have = os.path.getsize(dest)
        total = size if size is not None else probe_total(url, headers, 30, opener)
        if total is not None and have == total:
            if not sha256 or sha256_file(dest) == sha256:
                return "skipped"
            _replace(dest, "%s.bad-%s" % (dest, stamp), sleep=sleep)
        elif os.path.exists(part) or (total is not None and have > total):
            _replace(dest, "%s.old-%s" % (dest, stamp), sleep=sleep)      # never delete what we did not make
        else:
            out("  %s: continuing the unfinished copy (%s of %s)" % (label, human(have), human(total)))
            _replace(dest, part, sleep=sleep)

    total = size
    fails, restarts, waited = 0, 0, 0.0
    last_progress = clock()
    while True:
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if total is not None and have > total:
            open(part, "wb").close()
            have = 0
        complete = total is not None and have == total
        if not complete:
            before = have
            why = "?"
            try:
                total = _attempt(url, part, have, total, size, headers, timeout, opener)
                complete = True                  # the connection ended with everything the site promised
            except _Retry as e:
                why = str(e)
            except urllib.error.HTTPError as e:
                if e.code in FATAL_HTTP:
                    raise FetchError("%s: the site answered HTTP %s" % (label, e.code))
                why = "HTTP %s" % e.code
                if e.code == 416:
                    n = _total_of(e.headers.get("Content-Range"))
                    if n is not None and n == before:
                        total, complete = n, True                # we already have all of it
                    else:
                        open(part, "wb").close()                 # our partial no longer fits the file on the site
            except (urllib.error.URLError, socket.timeout, OSError, http.client.HTTPException, ValueError) as e:
                why = str(getattr(e, "reason", None) or e) or e.__class__.__name__
            now_have = os.path.getsize(part) if os.path.exists(part) else 0
            if now_have > before:
                last_progress, fails, waited = clock(), 0, 0.0
            if not complete:
                stalled = max(clock() - last_progress, waited)       # (waited also counts when sleep is faked)
                if stalled >= stall:
                    raise FetchError("%s: no progress for %d minutes (%s); %s of %s is kept in %s - run it again later "
                                     "and it continues" % (label, int(stall // 60), why, human(now_have), human(total),
                                                          os.path.basename(part)))
                wait = min(BACKOFF[min(fails, len(BACKOFF) - 1)], max(1.0, stall - stalled))
                fails += 1
                waited += wait
                out("  %s: connection problem at %s of %s (%s) - trying again in %d s (gives up after %d min "
                    "without progress)" % (label, human(now_have), human(total), why[:90], wait, max(1, int(stall // 60))))
                sleep(wait)
                continue
        # every byte is here: check it
        have = os.path.getsize(part)
        if total is not None and have != total:
            raise FetchError("%s: %s received, %s expected" % (label, human(have), human(total)))
        if sha256:
            if have > 200 << 20:
                out("  %s: checking sha256 (%s) ..." % (label, human(have)))
            got = sha256_file(part)
            if got != sha256:
                restarts += 1
                bad = "%s.bad-%s" % (part, stamp)
                _replace(part, bad, sleep=sleep)
                if restarts > 2:
                    raise FetchError("%s: the checksum is wrong again (got %s..., expected %s...); the copy is kept as "
                                     "%s" % (label, got[:12], sha256[:12], os.path.basename(bad)))
                out("  %s: checksum does not match - fetching it again from the start" % label)
                last_progress = clock()
                continue
        _replace(part, dest, sleep=sleep)
        return "downloaded"


def _attempt(url, part, have, total, size, headers, timeout, opener):
    """One connection. Returns the total size when the site delivered everything it promised; raises _Retry /
    URLError / OSError otherwise (what was received stays in part)."""
    h = dict(headers or {})
    if have:
        h["Range"] = "bytes=%d-" % have
    with _open(url, h, timeout, opener) as r:
        status = getattr(r, "status", None) or r.getcode()
        mode = "ab"
        if have and status != 206:
            mode, have = "wb", 0                  # the site ignored Range: start again
        cr = r.headers.get("Content-Range") or ""
        new_total = total
        if status == 206 and cr.startswith("bytes "):
            start = cr[6:].split("-", 1)[0].strip()
            if start.isdigit() and int(start) != have:
                open(part, "wb").close()
                raise _Retry("the site answered the wrong byte range")
            if _total_of(cr) is not None:
                new_total = _total_of(cr)
        elif (r.headers.get("Content-Length") or "").isdigit():
            new_total = have + int(r.headers["Content-Length"])
        if size is not None and new_total is not None and new_total != size:
            raise FetchError("the site has a different file (%s) than expected (%s)" % (human(new_total), human(size)))
        got = have
        with open(part, mode) as fh:
            while True:
                b = r.read(256 * 1024)
                if not b:
                    break
                fh.write(b)
                got += len(b)
    if new_total is not None and got < new_total:
        raise _Retry("the connection closed at %s of %s" % (human(got), human(new_total)))
    return new_total if new_total is not None else got


def fetch_with_progress(url, dest, out=print, every=10.0, **kw):
    """fetch() plus a progress line every `every` seconds (a watcher thread reads the size of the growing .part)."""
    stop = threading.Event()
    part = os.path.abspath(dest) + ".part"
    label = kw.get("label") or os.path.basename(dest)
    size = kw.get("size")

    def watch():
        last = None
        while not stop.wait(every):
            try:
                n = os.path.getsize(part)
            except OSError:
                continue
            now = time.time()
            rate = (n - last[1]) / max(0.001, now - last[0]) if last else 0
            last = (now, n)
            line = "  %s: %s" % (label, human(n))
            if size:
                line += " of %s (%d%%)" % (human(size), int(100.0 * n / size))
            if rate > 0:
                line += "   %s/s" % human(rate)
            out(line)
    th = threading.Thread(target=watch, daemon=True)
    th.start()
    try:
        return fetch(url, dest, out=out, **kw)
    finally:
        stop.set()


# ───────────────────────────────────────────── the site's own list of files, and the command line

def site_headers(token):
    return {"Authorization": "Node " + token} if token else {}


def site_file_info(site, token, name, timeout=30, tries=3, sleep=time.sleep):
    """(size, sha256) of a file in {site}/3d/files/downloads/ as the site states it, or (None, None)."""
    url = "%s/api/v1/compute/downloads/?name=%s" % (site.rstrip("/"), urllib.parse.quote(name))
    for i in range(tries):
        try:
            with _open(url, site_headers(token), timeout, None) as r:
                d = json.loads(r.read().decode("utf-8"))
            size = d.get("size")
            return (size if isinstance(size, int) else None), (d.get("sha256") or None)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                break
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
            pass
        if i + 1 < tries:
            sleep(5 * (i + 1))
    return None, None


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="resumable, verified download from the site")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("site-file")
    a.add_argument("name")
    a.add_argument("dest")
    b = sub.add_parser("url")
    b.add_argument("url")
    b.add_argument("dest")
    b.add_argument("--size", type=int)
    b.add_argument("--sha256")
    for p in (a, b):
        p.add_argument("--site", default=os.environ.get("NM_SITE", ""))
        p.add_argument("--token", default=os.environ.get("NM_TOKEN", ""))
        p.add_argument("--stall", type=int, default=int(os.environ.get("NM_STALL_S") or STALL_DEFAULT))
    args = ap.parse_args(argv)
    site = (args.site or "").rstrip("/")
    headers, size, sha = {}, None, None
    if args.cmd == "site-file":
        if not site:
            print("[!] NM_SITE is not set (run START.bat first, or pass --site)", flush=True)
            return 2
        url = "%s/3d/files/downloads/%s" % (site, urllib.parse.quote(args.name))
        size, sha = site_file_info(site, args.token, args.name)
        if size is None:
            print("  note: the site did not give the size / checksum of %s; it is checked against what the server "
                  "sends" % args.name, flush=True)
    else:
        url, size, sha = args.url, args.size, args.sha256
        if site and url.startswith(site):
            headers = site_headers(args.token)
    try:
        res = fetch_with_progress(url, args.dest, out=lambda m: print(m, flush=True), headers=headers, size=size,
                                  sha256=sha, stall=args.stall)
    except FetchError as e:
        print("[!] %s" % e, flush=True)
        return 1
    print("  %s: %s" % (os.path.basename(args.dest), "already complete" if res == "skipped" else "downloaded and verified"),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
