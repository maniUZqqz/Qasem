#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A result that is finished is never lost because the site was briefly unreachable (agent 2.11). Python 3.8+ stdlib only.

The log the owner pasted (11/11 10:52): `WARNING: site unreachable (...) [WinError 10060] - retrying in 5s` and
`[log shipping failed: site unreachable ...]`. Before 2.11 the agent asked again for about five minutes and then dropped the
finished job (the site put it back in the queue after the lease and the work was done twice). Now:

  * the outputs of a finished job and its report are first put in <data>/outbox/<uid>/ (a move on the same drive - instant);
  * `Outbox.deliver()` sends them: small files in the multipart upload, big ones in resumable 8 MB chunks (PUT ...?offset=N, the
    site says how much it already has, so a break continues from there), then the `finish` call. What reached the site is
    remembered in manifest.json, so a second try never repeats a finished file;
  * if the site is unreachable the result simply stays in the outbox and a background `Flusher` retries with growing waits
    (15 s -> 5 min) until it is delivered; the site accepts the result of a job it had put back in the queue as long as nobody
    else took it (apps.compute.api, `last_node_name`);
  * a refusal (the job belongs to somebody else now, HTTP 4xx) removes the entry with a log line - never an endless retry;
  * log lines that could not be shipped are spooled to <data>/logs/unsent.jsonl and shipped first when the link is back.

`Connectivity` turns a flood of "site unreachable ... retrying" lines into one line when the link drops, a reminder every
minute and one line when it returns (with how long it was down); its waits grow 5 -> 60 s with a little jitter.
"""
import hashlib
import json
import os
import random
import shutil
import threading
import time
import urllib.parse

VERSION = "1.0"
SMALL_FILE = 4 << 20                      # up to here a file travels in the multipart upload, above it in resumable chunks
CHUNK = 8 << 20
KEEP_S = 3 * 86400                        # an undeliverable entry is dropped after three days
FLUSH_WAITS = (15, 30, 60, 120, 300)
SPOOL_MAX_LINES = 2000


def _jwrite(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _jread(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


class Connectivity:
    """The state of the link to the site: when it dropped, how long to wait, when to say something."""

    def __init__(self, now=time.time, rnd=random.random):
        self.now = now
        self.rnd = rnd
        self.down_since = None
        self.fails = 0
        self.last_said = 0.0
        self.last_error = ""

    def fail(self, err):
        """Returns (seconds to wait, message or None). The message is for the log: the first failure, then once a minute."""
        t = self.now()
        self.fails += 1
        self.last_error = str(err)[:200]
        if self.down_since is None:
            self.down_since = t
        wait = min(60.0, 5.0 * (2 ** min(self.fails - 1, 4)))
        wait *= 0.85 + 0.3 * self.rnd()
        msg = None
        if self.fails == 1:
            msg = "the site is unreachable (%s) - the node keeps working and retries (next try in %ds)" % (self.last_error, wait)
            self.last_said = t
        elif t - self.last_said >= 60:
            msg = "the site is still unreachable after %d min (%s) - retrying every %ds" % (
                int((t - self.down_since) // 60), self.last_error, wait)
            self.last_said = t
        return wait, msg

    def ok(self):
        """Call after any success. Returns how many seconds the link was down (None if it was not)."""
        if self.down_since is None:
            return None
        down = self.now() - self.down_since
        self.down_since, self.fails, self.last_said = None, 0, 0.0
        return down

    @property
    def offline(self):
        return self.down_since is not None


class LogSpool:
    """Warning/error lines that could not be shipped wait in a file (they survive a restart) and go first next time."""

    def __init__(self, path, max_lines=SPOOL_MAX_LINES):
        self.path = path
        self.max_lines = max_lines
        self.lock = threading.Lock()

    def add(self, lines):
        if not lines:
            return
        with self.lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                old = self.read_all()
                allv = (old + list(lines))[-self.max_lines:]
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    for ln in allv:
                        fh.write(json.dumps(ln, ensure_ascii=False) + "\n")
                os.replace(tmp, self.path)
            except OSError:
                pass

    def read_all(self):
        out = []
        try:
            with open(self.path, encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        out.append(json.loads(ln))
                    except ValueError:
                        continue
        except OSError:
            pass
        return out

    def drain(self, send, batch=100):
        """Send the spooled lines with send(list) (raises when the site is unreachable); returns how many were shipped."""
        with self.lock:
            lines = self.read_all()
        if not lines:
            return 0
        sent = 0
        while sent < len(lines):
            send(lines[sent:sent + batch])
            sent += batch
        with self.lock:
            now_lines = self.read_all()
            rest = now_lines[len(lines):] if len(now_lines) >= len(lines) else []
            try:
                if rest:
                    tmp = self.path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        for ln in rest:
                            fh.write(json.dumps(ln, ensure_ascii=False) + "\n")
                    os.replace(tmp, self.path)
                else:
                    os.remove(self.path)
            except OSError:
                pass
        return len(lines)


class Delivered(Exception):
    pass


class Outbox:
    """<root>/<uid>/manifest.json + outputs/. `agent` supplies SiteError, JobLost, log, warn (a module or a stand-in)."""

    def __init__(self, root, agent):
        self.root = root
        self.agent = agent
        self.lock = threading.Lock()
        self.busy = set()

    # ---- writing
    def entry_dir(self, uid):
        return os.path.join(self.root, uid)

    def stash(self, uid, kind, ok, error, meta, outputs_dir=None):
        """Put the end of a job in the outbox (moves `outputs_dir` in). Returns the entry folder."""
        d = self.entry_dir(uid)
        os.makedirs(d, exist_ok=True)
        files = []
        out = os.path.join(d, "outputs")
        if outputs_dir and os.path.isdir(outputs_dir):
            if os.path.isdir(out):
                shutil.rmtree(out, ignore_errors=True)
            try:
                os.replace(outputs_dir, out)
            except OSError:
                shutil.copytree(outputs_dir, out)
            for name in sorted(os.listdir(out)):
                p = os.path.join(out, name)
                if os.path.isfile(p):
                    files.append({"name": name, "size": os.path.getsize(p)})
        _jwrite(os.path.join(d, "manifest.json"), {"uid": uid, "kind": kind, "ok": bool(ok), "error": error or "", "meta": meta or {},
                                                   "files": files, "uploaded": [], "created": time.time(), "tries": 0})
        return d

    def pending(self):
        try:
            names = sorted(os.listdir(self.root))
        except OSError:
            return []
        return [n for n in names if os.path.isfile(os.path.join(self.root, n, "manifest.json"))]

    def count(self):
        return len(self.pending())

    # ---- sending
    def _upload_chunks(self, site, uid, name, path, say=None):
        total = os.path.getsize(path)
        sha = sha256_file(path)
        base = "/api/v1/compute/jobs/%s/chunks/%s/" % (uid, urllib.parse.quote(name))
        try:
            have = int((site.get_json(base, timeout=60) or {}).get("size") or 0)
        except self.agent.SiteError:
            raise
        offset = have if 0 <= have <= total else 0
        with open(path, "rb") as fh:
            while True:
                fh.seek(offset)
                chunk = fh.read(CHUNK)
                q = urllib.parse.urlencode({"offset": offset, "total": total, "sha256": sha})
                try:
                    r = site._req("PUT", base + "?" + q, chunk, {"Content-Type": "application/octet-stream"}, timeout=300)
                except self.agent.SiteError as e:
                    if "HTTP 409" in str(e):               # the site has a different amount: ask again and continue from there
                        r = site.get_json(base, timeout=60)
                        offset = int((r or {}).get("size") or 0)
                        continue
                    if "HTTP 422" in str(e):               # checksum: the site threw the part away, start again
                        offset = 0
                        continue
                    raise
                offset = int((r or {}).get("size") or offset + len(chunk))
                if say:
                    say("upload %s %d%%" % (name, int(100 * offset / max(1, total))))
                if (r or {}).get("complete") or offset >= total:
                    return

    def deliver(self, site, uid, say=None):
        """Try to send one entry. Returns 'done' | 'retry' | 'dropped'. Never raises for network trouble."""
        a = self.agent
        with self.lock:
            if uid in self.busy:
                return "retry"
            self.busy.add(uid)
        try:
            d = self.entry_dir(uid)
            mpath = os.path.join(d, "manifest.json")
            m = _jread(mpath)
            if not m:
                shutil.rmtree(d, ignore_errors=True)
                return "dropped"
            if time.time() - m.get("created", time.time()) > KEEP_S:
                a.warn("outbox: the result of job %s could not be delivered for 3 days - dropped" % uid[:8])
                shutil.rmtree(d, ignore_errors=True)
                return "dropped"
            m["tries"] = m.get("tries", 0) + 1
            try:
                uploaded = set(m.get("uploaded") or [])
                small = [f for f in m.get("files", []) if f["name"] not in uploaded and f["size"] <= SMALL_FILE]
                big = [f for f in m.get("files", []) if f["name"] not in uploaded and f["size"] > SMALL_FILE]
                for i in range(0, len(small), 4):
                    batch = small[i:i + 4]
                    files = {}
                    for f in batch:
                        with open(os.path.join(d, "outputs", f["name"]), "rb") as fh:
                            files["file_" + f["name"]] = (f["name"], fh.read())
                    site.upload("/api/v1/compute/jobs/%s/upload/" % uid, files, attempts=1)
                    uploaded.update(f["name"] for f in batch)
                    m["uploaded"] = sorted(uploaded)
                    _jwrite(mpath, m)
                for f in big:
                    self._upload_chunks(site, uid, f["name"], os.path.join(d, "outputs", f["name"]), say)
                    uploaded.add(f["name"])
                    m["uploaded"] = sorted(uploaded)
                    _jwrite(mpath, m)
                site.post("/api/v1/compute/jobs/%s/finish/" % uid,
                          {"ok": m["ok"], "error": (m.get("error") or "")[:4000], "meta": m.get("meta") or {}}, timeout=120)
            except a.JobLost:
                a.warn("outbox: job %s belongs to another attempt now - its result is dropped" % uid[:8])
                shutil.rmtree(d, ignore_errors=True)
                return "dropped"
            except a.SiteError as e:
                text = str(e)
                if "rejected the node token" in text:
                    _jwrite(mpath, m)
                    return "retry"
                if "HTTP 4" in text and "HTTP 409" not in text and "HTTP 429" not in text:
                    a.warn("outbox: the site refused the result of job %s (%s) - dropped" % (uid[:8], text[:160]))
                    shutil.rmtree(d, ignore_errors=True)
                    return "dropped"
                _jwrite(mpath, m)
                return "retry"
            except OSError as e:                    # a file vanished: report what we can
                a.warn("outbox: job %s: %s" % (uid[:8], e))
                _jwrite(mpath, m)
                return "retry"
            shutil.rmtree(d, ignore_errors=True)
            a.log("outbox: the result of job %s was delivered (try %d)" % (uid[:8], m["tries"]))
            return "done"
        finally:
            with self.lock:
                self.busy.discard(uid)

    def flush(self, site, say=None):
        """Deliver everything; returns (done, left). Stops at the first 'retry' (the link is probably down)."""
        done = 0
        for uid in self.pending():
            r = self.deliver(site, uid, say)
            if r == "retry":
                break
            done += 1
        return done, self.count()


class Flusher(threading.Thread):
    """Background thread: delivers the outbox and the spooled log lines whenever there is something and the site answers."""

    def __init__(self, outbox, site, conn=None, spool=None, ship_logs=None, sleep=time.sleep):
        super().__init__(daemon=True, name="outbox-flusher")
        self.outbox, self.site, self.conn = outbox, site, conn or Connectivity()
        self.spool, self.ship_logs = spool, ship_logs
        self.stop_flag = threading.Event()
        self.wake = threading.Event()          # poked when the site answers again: deliver now, do not wait out the backoff
        self.step = 0
        self.sleep = sleep

    def once(self):
        """One pass; returns seconds until the next one."""
        did = False
        if self.outbox.count():
            done, left = self.outbox.flush(self.site)
            did = True
            if left:
                self.step = min(self.step + 1, len(FLUSH_WAITS) - 1)
                return FLUSH_WAITS[self.step]
            self.step = 0
        if self.spool is not None and self.ship_logs is not None and self.spool.read_all():
            try:
                self.spool.drain(self.ship_logs)
                did = True
            except Exception:  # noqa: BLE001 - still offline
                self.step = min(self.step + 1, len(FLUSH_WAITS) - 1)
                return FLUSH_WAITS[self.step]
        self.step = 0
        return 20 if not did else 10

    def run(self):
        while not self.stop_flag.is_set():
            try:
                wait = self.once()
            except Exception:  # noqa: BLE001 - never die
                wait = 60
            self.wake.wait(wait)
            self.wake.clear()

    def stop(self):
        self.stop_flag.set()
        self.wake.set()
