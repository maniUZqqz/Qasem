#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Node-side kind `crawl21.run` (the site builder's 21st.dev crawler, with a real browser).

The site crawls 21st.dev by itself over plain HTTP (sitemap, `.md` pages, og images). This job is the way around when the server cannot (it was
blocked, or a page needs a real browser): the GPU computer opens the same PUBLIC pages in a headless browser and sends back what the page shows -
the `.md` text (licence, tags, dependencies, library) and the usage demo code - for the site to parse and store (apps/projects/builder/c21_node.py).

Rules the job obeys (robots.txt of 21st.dev, `Allow: /` but `Disallow: /api/ /r/ /preview/ /auth/ /admin/ /sign-in /community/bookmarks/`):
  * every URL is checked against robots.txt BEFORE it is opened, and every request the page makes itself (XHR, scripts) is checked again; a disallowed
    one is aborted, so the browser never touches /api/ or /r/ (the component's own source is not public: «comes with a free account»);
  * one page at a time, `delay_s` (default 1.5 s) between pages, retries with a growing pause; 403 four times in a row stops the job;
  * nothing is trained on, nothing is posted; only public pages are read.

Payload  {"ids": ["author/slug", ...] (<= 40), "urls": [...], "want": "md,page", "delay_s": 1.5, "robots": "<robots.txt the site has>", "selftest": false}
Output   results.json  {"results": [{"id", "ok", "md", "page": {"title", "demo": {"file", "code"}, "text"}, "error"}], "browser", "seconds", "robots_ok"}

The browser is the Microsoft Edge that every Windows 11 has (Playwright `channel="msedge"`; then Chrome; then Playwright's own Chromium) - nothing big is
downloaded. The install list `requirements.d/crawl21.json` creates the environment `venvs/crawl21` (pip: playwright) and runs `--check` (which, if no browser
works, runs `playwright install chromium` as the last resort). Python 3.8+ standard library at import time; Playwright only inside the venv.

By hand on the node (the same code):
    <data>\\venvs\\crawl21\\Scripts\\python.exe crawl21_jobs.py --run ids.txt results.json      (ids.txt: one `author/slug` per line)
    <data>\\venvs\\crawl21\\Scripts\\python.exe crawl21_jobs.py --check
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

KIND = "crawl21.run"
FEATURE = "crawl21"
BASE = "https://21st.dev"
UA_TOKEN = "NMarketingBot"
MAX_IDS = 40
RETRY_WAITS = (2.0, 6.0, 18.0)
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,60}/[A-Za-z0-9._-]{1,120}$")


# ───────────────────────────── robots.txt (RFC 9309: the longest matching rule wins; equal length -> Allow)

class Robots(object):
    def __init__(self, text="", ok=True):
        self.groups = []
        self.ok = ok                      # False = robots.txt could not be read -> everything is refused
        self._parse(text or "")

    def _parse(self, text):
        agents, rules, seen_rule = [], [], False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key, val = key.strip().lower(), val.strip()
            if key == "user-agent":
                if seen_rule:
                    self.groups.append((agents, rules))
                    agents, rules, seen_rule = [], [], False
                agents.append(val.lower())
            elif key in ("allow", "disallow"):
                seen_rule = True
                if val or key == "allow":
                    rules.append((key == "allow", val))
        if agents:
            self.groups.append((agents, rules))

    def _rules(self, ua):
        ua = ua.lower()
        best, best_len = None, -1
        for agents, rules in self.groups:
            for a in agents:
                if a != "*" and a in ua and len(a) > best_len:
                    best, best_len = rules, len(a)
        if best is not None:
            return best
        for agents, rules in self.groups:
            if "*" in agents:
                return rules
        return []

    @staticmethod
    def _match(pattern, path):
        if not pattern:
            return -1
        anchored = pattern.endswith("$")
        pat = pattern[:-1] if anchored else pattern
        rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pat)
        return len(pat) if re.match(rx + ("$" if anchored else ""), path) else -1

    def allowed(self, url, ua=UA_TOKEN):
        if not self.ok:
            return False
        m = re.match(r"^(?:[a-z]+://[^/]+)?(/[^#]*)?", url)
        path = (m.group(1) if m and m.group(1) else "/")
        best_len, best_allow = -1, True
        for allow, pat in self._rules(ua):
            n = self._match(pat, path)
            if n > best_len or (n == best_len and allow and not best_allow):
                best_len, best_allow = n, allow
        return best_allow if best_len >= 0 else True


def is_21st(url):
    return bool(re.match(r"^https://(www\.)?21st\.dev(/|$)", url))


# ───────────────────────────── the browser

PAGE_JS = """() => {
  const out = {title: '', demo: null, text: ''};
  const h1 = document.querySelector('h1'); out.title = h1 ? h1.innerText.trim() : document.title;
  for (const pre of document.querySelectorAll('pre')) {
    const code = pre.innerText || '';
    if (!/\\b(import|export)\\b/.test(code)) continue;
    let name = 'Usage.tsx'; let p = pre.parentElement;
    for (let i = 0; i < 3 && p; i++, p = p.parentElement) { const f = p.querySelector('p'); if (f && /\\.(tsx|jsx|ts|js)\\s*$/.test(f.innerText)) { name = f.innerText.trim(); break; } }
    out.demo = {file: name, code: code}; break;
  }
  const main = document.querySelector('main') || document.body; out.text = (main.innerText || '').slice(0, 1500);
  return out;
}"""


def launch_browser(p, log=None):
    """-> (browser, name). Edge and Chrome come with Windows; Playwright's own Chromium is the last resort."""
    last = None
    for channel in ("msedge", "chrome", None):
        try:
            b = p.chromium.launch(channel=channel, headless=True) if channel else p.chromium.launch(headless=True)
            return b, channel or "chromium"
        except Exception as exc:  # noqa: BLE001
            last = exc
            if log:
                log("browser %s not usable: %s" % (channel or "chromium", str(exc)[:120]))
    raise RuntimeError("no browser could be started (%s)" % str(last)[:200])


def crawl(payload, out_path, progress=None, say=print, sync_playwright=None):
    """Run the crawl (worker side). Returns the dict that is written to out_path."""
    if sync_playwright is None:
        from playwright.sync_api import sync_playwright  # noqa: WPS433 - only inside the venv
    ids = [i for i in (payload.get("ids") or []) if isinstance(i, str) and ID_RE.match(i)][:MAX_IDS]
    delay = max(1.0, min(10.0, float(payload.get("delay_s") or 1.5)))
    want = str(payload.get("want") or "md,page")
    started = time.time()
    results = []
    forbidden = 0
    with sync_playwright() as p:
        browser, bname = launch_browser(p, say)
        try:
            ctx = browser.new_context(user_agent="%s/1.0 (reference and catalogue reader)" % UA_TOKEN, locale="en-US", viewport={"width": 1280, "height": 900})
            robots_text = str(payload.get("robots") or "")
            robots_ok = True
            if not robots_text:
                try:
                    r = ctx.request.get(BASE + "/robots.txt", timeout=30000)
                    robots_text, robots_ok = (r.text(), True) if r.status == 200 else ("", 400 <= r.status < 500)
                except Exception as exc:  # noqa: BLE001
                    say("robots.txt unreadable: %s" % exc)
                    robots_ok = False
            robots = Robots(robots_text, ok=robots_ok)

            def gate(route):
                req = route.request
                if req.resource_type in ("image", "media", "font"):
                    return route.abort()
                if is_21st(req.url) and not robots.allowed(req.url):
                    return route.abort()
                return route.continue_()

            for n, cid in enumerate(ids):
                row = {"id": cid, "ok": False, "md": "", "page": None, "error": ""}
                author, slug = cid.split("/")
                page_url = "%s/@%s/components/%s" % (BASE, author, slug)
                if not robots.allowed(page_url):
                    row["error"] = "robots"
                    results.append(row)
                    continue
                for attempt in range(len(RETRY_WAITS) + 1):
                    try:
                        if "md" in want:
                            r = ctx.request.get(page_url + ".md", headers={"Accept": "text/markdown"}, timeout=30000)
                            if r.status == 200:
                                row["md"] = r.text()
                            elif r.status == 403:
                                forbidden += 1
                                raise RuntimeError("http_403")
                            elif r.status in (429, 500, 502, 503, 504):
                                raise RuntimeError("http_%d" % r.status)
                        if "page" in want:
                            pg = ctx.new_page()
                            try:
                                pg.route("**/*", gate)
                                pg.goto(page_url, wait_until="domcontentloaded", timeout=45000)
                                pg.wait_for_timeout(2500)
                                row["page"] = pg.evaluate(PAGE_JS)
                            finally:
                                pg.close()
                        row["ok"] = bool(row["md"] or row["page"])
                        forbidden = 0
                        break
                    except Exception as exc:  # noqa: BLE001
                        row["error"] = str(exc)[:160]
                        if forbidden >= 4:
                            break
                        if attempt < len(RETRY_WAITS):
                            time.sleep(RETRY_WAITS[attempt])
                results.append(row)
                if progress:
                    progress((n + 1) / float(len(ids)), "%d / %d  %s" % (n + 1, len(ids), cid))
                if forbidden >= 4:
                    say("403 four times in a row: stopping")
                    break
                time.sleep(delay)
        finally:
            browser.close()
    out = {"results": results, "browser": bname, "seconds": round(time.time() - started, 1), "robots_ok": robots_ok, "count": len(results),
           "ok": sum(1 for r in results if r["ok"])}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


# ───────────────────────────── the agent side

def venv_python(agent):
    import gpu
    return gpu.venv_python(os.path.join(agent.DATA, "venvs", "crawl21"))


def run(job, agent):
    """Handler of crawl21.run: the work happens in the venv (Playwright), this process only supervises it."""
    p = job.payload or {}
    ids = [i for i in (p.get("ids") or []) if isinstance(i, str) and ID_RE.match(i)]
    if not ids:
        raise agent.JobError("payload.ids is empty (author/slug, up to %d)" % MAX_IDS, retryable=False)
    py = venv_python(agent)
    if not py:
        raise agent.JobError("DOWNLOADING: the crawler environment is still being installed on this node (see the install panel) | "
                             "محیطِ خزنده هنوز نصب نشده است")
    out = job.out("results.json")
    pay = os.path.join(job.dir, "payload.json")
    os.makedirs(job.dir, exist_ok=True)
    with open(pay, "w", encoding="utf-8") as fh:
        json.dump(p, fh, ensure_ascii=False)
    cmd = [py, os.path.abspath(__file__), "--worker", pay, out]
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    job.progress(0.05, "crawl21: starting the browser")
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, universal_newlines=True, encoding="utf-8", errors="replace")
    lines = []
    import threading

    th = threading.Thread(target=lambda: [lines.append(ln.rstrip()) for ln in proc.stdout], daemon=True)
    th.start()
    limit = max(180, int(job.timeout_s or 1800) - 30)
    last = 0.0
    while proc.poll() is None:
        time.sleep(1.0)
        if job.cancelled or time.time() - t0 > limit:
            proc.kill()
            if job.cancelled:
                raise agent.Cancelled()
            raise agent.JobError("the crawl did not finish in %d s" % limit)
        if time.time() - last >= 10:
            last = time.time()
            done = 0
            for ln in lines[::-1]:
                m = re.match(r"^PROGRESS ([0-9.]+) (.*)$", ln)
                if m:
                    done = float(m.group(1))
                    job.progress(0.05 + 0.9 * done, "crawl21: " + m.group(2)[:100])
                    break
    th.join(timeout=5)
    if proc.returncode != 0 or not os.path.isfile(out):
        raise agent.JobError("crawl21 failed (exit %s): %s" % (proc.returncode, " | ".join(lines[-4:])[:400]))
    with open(out, encoding="utf-8") as fh:
        res = json.load(fh)
    return {"primary": "results.json", "engine": "playwright", "device": "cpu", "device_note": "browser: %s" % res.get("browser"), "pages": res.get("count"),
            "ok_pages": res.get("ok"), "seconds": res.get("seconds")}


def install(agent):
    agent.HANDLERS[KIND] = lambda job: run(job, agent)


# ───────────────────────────── command line (worker / check / install / by hand)

def check(say=print):
    """Exit-code check used by requirements.d/crawl21.json: a headless browser opens a blank page."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        say("playwright is not importable: %s" % exc)
        return 2
    try:
        with sync_playwright() as p:
            b, name = launch_browser(p, say)
            try:
                pg = b.new_page()
                pg.goto("about:blank")
                pg.set_content("<p>ok</p>")
                assert pg.inner_text("p") == "ok"
            finally:
                b.close()
        say("browser ok: %s" % name)
        return 0
    except Exception as exc:  # noqa: BLE001
        say("no working browser: %s" % str(exc)[:200])
        return 3


def install_browser(say=print):
    """Last resort when neither Edge nor Chrome starts: Playwright's own Chromium (several mirrors, the first that works)."""
    env_hosts = [None, "https://registry.npmmirror.com/-/binary/playwright", "https://cdn.npmmirror.com/binaries/playwright"]
    for host in env_hosts:
        env = dict(os.environ)
        if host:
            env["PLAYWRIGHT_DOWNLOAD_HOST"] = host
        say("playwright install chromium (%s)" % (host or "default"))
        r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                           timeout=3000)
        say((r.stdout or "")[-300:])
        if r.returncode == 0:
            return 0
    return 4


def main(argv):
    if len(argv) >= 2 and argv[1] == "--check":
        rc = check()
        if rc == 3:                      # no browser at all: try to fetch Chromium, then check again
            if install_browser() == 0:
                rc = check()
        return rc
    if len(argv) >= 2 and argv[1] == "--install-browser":
        return install_browser()
    if len(argv) >= 4 and argv[1] == "--worker":
        with open(argv[2], encoding="utf-8") as fh:
            payload = json.load(fh)
        crawl(payload, argv[3], progress=lambda f, m: print("PROGRESS %.3f %s" % (f, m), flush=True), say=lambda m: print(m, flush=True))
        return 0
    if len(argv) >= 4 and argv[1] == "--run":
        with open(argv[2], encoding="utf-8") as fh:
            ids = [ln.strip() for ln in fh if ID_RE.match(ln.strip())]
        out = crawl({"ids": ids[:MAX_IDS]}, argv[3], progress=lambda f, m: print(m, flush=True))
        print("ok: %s of %s pages (%s)" % (out["ok"], out["count"], out["browser"]))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
