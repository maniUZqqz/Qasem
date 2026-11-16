#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crawl_jobs.py - the customer finder's heavy half on the processing node: job kinds crawl.run / crawl.render / crawl.selftest (agent 2.13).

WHY IT IS HERE: the site's server has 2 CPUs and a little RAM. Reading hundreds of business websites politely (a couple of seconds between two
requests to one host), and rendering the sites that are only a JavaScript shell, belongs on the GPU computer, which is on a good line and has a
real browser. The server keeps the small crawls; it hands the big ones (and every JavaScript site) to this node through the compute queue, which
holds them while the node is off.

WHAT THE NODE DOES BY ITSELF (nothing to click, nothing to install by hand)
  * requirements.d/crawl.json (agent 2.11 installer) builds <data>\\venvs\\crawl with Playwright (pinned, PyPI or the Iranian mirrors) and makes
    sure a browser exists: the Microsoft Edge every Windows 11 has (no download), else Chrome, else the Chromium pack Abagram already uses;
  * the heartbeat reports caps["crawl"] (the kind is advertised: an older agent never receives it) and caps["crawl_ready"] (browser + Playwright);
  * crawl.selftest starts a tiny web server on 127.0.0.1 with a static page and a JavaScript-only page and checks that BOTH are read - that is
    the automatic acceptance test the site runs as soon as the node is online.

crawl.run     payload {sites:[{id,url}], max_pages_per_site, render:"never"|"auto"|"always", domain_delay, max_html_bytes, total_bytes, run_id}
              for every site: robots.txt, the home page, then at most (max_pages_per_site-1) contact / about / support pages it links to - never an
              off-site link, never a login, never a form. A page that is only a JavaScript shell is rendered in the browser (render "auto") or always.
              Output pages.jsonl.gz, one JSON object per site: {id, url, status, reason, robots, pages:[{url, kind, status, outcome, rendered, html, note}]}.
              The SITE reads the pages (one parser for the server's own crawls and the node's): this node only fetches and renders.
crawl.render  the same, rendering every page in the browser.
crawl.selftest  payload {"selftest": true}  ->  selftest.json {ok, checks:[{name, ok, detail}]}.

Rules it keeps (the same as the server's SafeFetcher): only http/https and ordinary ports; every address a host resolves to must be public (an answer
that points into a private network is refused - checked again on every redirect, and the request is sent to the address that was checked);
robots.txt of every host (token NMarketingBot, 4xx = allowed, 401/403/5xx/unreachable = not allowed); a minimum delay per host; response-size caps;
GET only; same-site redirects only; no login, no forms, no captcha solving; an honest User-Agent.

Python 3.8+ standard library only (the agent's own interpreter); Playwright lives in its own virtual environment and is used through a child
process (`crawl_jobs.py render-urls`), so a crashed browser never takes the agent down. Console text is English on purpose (the Windows console garbles Persian).
"""
import glob
import gzip
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.robotparser
from html.parser import HTMLParser

VERSION = "1.0"
KINDS = ("crawl.run", "crawl.render", "crawl.selftest")
FEATURE = "crawl"
IS_WIN = sys.platform.startswith("win")
USER_AGENT = "NMarketingBot/1.0 (+http://87.107.160.17:8040/; business contact lookup; processing-node)"
ROBOTS_TOKEN = "NMarketingBot"
ALLOWED_PORTS = (80, 443, 8080, 8443)
MAX_REDIRECTS = 3
HTTP_TIMEOUT = 20.0
MAX_BODY = 1_500_000
RENDER_TIMEOUT_MS = 35_000
RENDER_BATCH = 12
STATE_TTL_S = 90.0
PIN_LOCK = threading.Lock()

HERE = os.path.dirname(os.path.abspath(__file__))


def say(msg):
    print("[crawl] %s" % msg, flush=True)


# ───────────────────────────────────────────── addresses and the SSRF guard

def is_public(addr):
    ip = ipaddress.ip_address(addr)
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool(ip.is_global and not ip.is_multicast)


def resolve_public(host, port, allow_private=False):
    """The addresses of host that are safe to talk to. Raises ValueError (with a code) when the name does not resolve or any address is private."""
    try:
        ipaddress.ip_address(host.strip("[]"))
        addrs = [host.strip("[]")]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            raise ValueError("dns_error")
        addrs = sorted(dict.fromkeys(i[4][0] for i in infos), key=lambda a: ":" in a)
    if not addrs:
        raise ValueError("dns_error")
    if not allow_private and not all(is_public(a) for a in addrs):
        raise ValueError("ssrf_blocked")
    return addrs


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, ip, **kw):
        http.client.HTTPConnection.__init__(self, host, **kw)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, **kw):
        http.client.HTTPSConnection.__init__(self, host, context=ssl.create_default_context(), **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _split(url):
    parts = urllib.parse.urlsplit(url)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower().strip(".")
    if scheme not in ("http", "https") or not host:
        raise ValueError("bad_url")
    port = parts.port or (443 if scheme == "https" else 80)
    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    if not host.isascii():
        host = host.encode("idna").decode("ascii")
    return scheme, host, port, path


def same_site(a, b):
    def key(u):
        h = (urllib.parse.urlsplit(u).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h

    return key(a) == key(b)


# ───────────────────────────────────────────── a polite fetcher

class Fetcher(object):
    """GET with robots.txt, per-host spacing, SSRF guard, pinned address, same-site redirects, size cap. Never raises for network problems."""

    def __init__(self, delay=2.0, allow_private=False, sleep=time.sleep, clock=time.monotonic):
        self.delay = float(delay)
        self.allow_private = allow_private
        self._sleep, self._clock = sleep, clock
        self._next = {}
        self._robots = {}

    def _wait(self, host):
        now = self._clock()
        ready = self._next.get(host, now)
        wait = max(0.0, ready - now)
        self._next[host] = now + wait + self.delay
        if wait:
            self._sleep(wait)

    def _raw(self, url, max_bytes=MAX_BODY, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"):
        """One request, no redirects. Returns dict(status, headers, body, outcome)."""
        out = {"status": 0, "headers": {}, "body": b"", "outcome": "ok", "url": url}
        try:
            scheme, host, port, path = _split(url)
            if port not in ALLOWED_PORTS and not self.allow_private:
                out["outcome"] = "blocked_port"
                return out
            ip = resolve_public(host, port, self.allow_private)[0]
        except ValueError as exc:
            out["outcome"] = str(exc)
            return out
        self._wait(host)
        conn = None
        try:
            cls = _PinnedHTTPS if scheme == "https" else _PinnedHTTP
            default = 443 if scheme == "https" else 80
            conn = cls(host, ip, port=port, timeout=HTTP_TIMEOUT)
            conn.request("GET", path, headers={"Host": host if port == default else "%s:%d" % (host, port), "User-Agent": USER_AGENT, "Accept": accept,
                                               "Accept-Language": "fa,en;q=0.8", "Accept-Encoding": "identity", "Connection": "close"})
            resp = conn.getresponse()
            out["status"] = resp.status
            out["headers"] = {k.lower(): v for k, v in resp.getheaders()}
            chunks, total = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                chunks.append(chunk)
                if total > max_bytes:
                    out["outcome"] = "too_large"
                    break
            out["body"] = b"".join(chunks)[:max_bytes]
        except socket.timeout:
            out["outcome"] = "timeout"
        except ssl.SSLError:
            out["outcome"] = "tls_error"
        except (OSError, http.client.HTTPException):
            out["outcome"] = "connect_error"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
        return out

    # -- robots.txt
    def allowed(self, url):
        """(allowed, state)"""
        try:
            scheme, host, port, path = _split(url)
        except ValueError:
            return False, "bad_url"
        key = (scheme, host, port)
        if key not in self._robots:
            r = self._raw("%s://%s%s/robots.txt" % (scheme, host, "" if port in (80, 443) else ":%d" % port), max_bytes=500_000, accept="text/plain,*/*")
            st = r["status"]
            if r["outcome"] in ("ssrf_blocked", "blocked_port", "bad_url", "dns_error"):
                self._robots[key] = (None, "unavailable")
            elif st in (401, 403):
                self._robots[key] = (None, "disallow_all")
            elif 400 <= st < 500:
                self._robots[key] = (None, "none")
            elif r["outcome"] in ("ok", "too_large") and 200 <= st < 300:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(r["body"].decode("utf-8", "replace").splitlines())
                self._robots[key] = (parser, "ok")
            else:
                self._robots[key] = (None, "unavailable")
        parser, state = self._robots[key]
        if state in ("unavailable", "disallow_all"):
            return False, state
        if parser is None:
            return True, state
        return bool(parser.can_fetch(ROBOTS_TOKEN, path) and parser.can_fetch("*", path)), state

    def get_page(self, url):
        """dict(url, final_url, status, outcome, html) - robots-checked, same-site redirects only."""
        current, origin = url, url
        for _hop in range(MAX_REDIRECTS + 1):
            ok, state = self.allowed(current)
            if not ok:
                return {"url": url, "final_url": current, "status": 0, "outcome": "robots_unavailable" if state == "unavailable" else "robots_blocked", "html": "", "robots": state}
            r = self._raw(current)
            if 300 <= r["status"] < 400 and r["headers"].get("location"):
                nxt = urllib.parse.urljoin(current, r["headers"]["location"])
                if not same_site(origin, nxt):
                    return {"url": url, "final_url": nxt, "status": r["status"], "outcome": "redirect_offsite", "html": "", "robots": state}
                current = nxt
                continue
            ctype = r["headers"].get("content-type", "").lower()
            outcome = r["outcome"]
            html = ""
            if outcome in ("ok", "too_large") and 200 <= r["status"] < 300:
                if "html" not in ctype and "xml" not in ctype and ctype:
                    outcome = "non_html"
                else:
                    charset = re.search(r"charset=([\w-]+)", ctype) or re.search(rb"charset=[\"']?([\w-]+)", r["body"][:3000], re.I)
                    enc = (charset.group(1).decode("ascii", "ignore") if charset and isinstance(charset.group(1), bytes) else (charset.group(1) if charset else "utf-8"))
                    try:
                        html = r["body"].decode(enc, "replace")
                    except LookupError:
                        html = r["body"].decode("utf-8", "replace")
                    outcome = "ok" if outcome == "ok" else "too_large"
            elif outcome == "ok":
                outcome = "http_error"
            return {"url": url, "final_url": current, "status": r["status"], "outcome": outcome, "html": html, "robots": state}
        return {"url": url, "final_url": current, "status": 0, "outcome": "redirect_loop", "html": "", "robots": ""}


# ───────────────────────────────────────────── reading a page's links and telling a JavaScript shell

class _Scan(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.links, self.text, self.scripts, self.shell_root = [], [], 0, False
        self._a = None
        self._skip = 0
        self.lang = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = (a.get("lang") or "")[:8]
        if tag in ("script", "style", "noscript", "svg", "template"):
            self._skip += 1
            if tag == "script":
                self.scripts += 1
        if tag == "div" and (a.get("id") or "") in ("root", "app", "__next", "__nuxt", "react-root", "q-app"):
            self.shell_root = True
        if tag == "a" and a.get("href"):
            self._a = {"url": a["href"], "text": ""}

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "template") and self._skip:
            self._skip -= 1
        if tag == "a" and self._a is not None:
            self.links.append(self._a)
            self._a = None

    def handle_data(self, data):
        if self._skip:
            return
        data = data.strip()
        if data:
            self.text.append(data)
            if self._a is not None:
                self._a["text"] += " " + data


def scan(html):
    s = _Scan()
    try:
        s.feed(html or "")
    except Exception:  # noqa: BLE001 - broken markup: use what was read
        pass
    return s


def looks_like_shell(html):
    s = scan(html)
    visible = len(" ".join(s.text))
    return (visible < 300 and (s.shell_root or s.scripts >= 2)) or (visible < 80 and s.scripts >= 1)


_CONTACT_FA = ("تماس", "ارتباط")
_ABOUT_FA = ("درباره", "معرفی")
_SUPPORT_FA = ("پشتیبانی", "تیکت")
_PATHS = {"contact": ("contact", "contact-us", "contactus", "tamas", "ertebat", "تماس", "ارتباط"), "about": ("about", "about-us", "aboutus", "darbare", "درباره"), "support": ("support", "ticket", "help", "پشتیبانی")}
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".rar", ".doc", ".docx", ".xls", ".xlsx", ".mp4", ".mp3", ".css", ".js", ".xml", ".ico")


def classify(url, text):
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower().strip("/")
    last = path.split("/")[-1] if path else ""
    t = (text or "").strip()
    if len(t) > 28:
        t = ""
    for cat, words in _PATHS.items():
        if last in words or any(last.startswith(w + "-") or last.endswith("-" + w) for w in words):
            return cat
    for cat, fa in (("contact", _CONTACT_FA), ("about", _ABOUT_FA), ("support", _SUPPORT_FA)):
        if any(w in t for w in fa):
            return cat
    low = t.lower()
    if re.search(r"\bcontact\b", low):
        return "contact"
    if re.search(r"\babout\b", low):
        return "about"
    return ""


def pick_pages(links, home_url, budget):
    """Up to `budget` same-site pages the home page links to: contact first, then about, then support; at most two of a kind."""
    order = {"contact": 0, "about": 1, "support": 2}
    seen = {home_url.rstrip("/")}
    scored = []
    for i, link in enumerate(links):
        href = link.get("url", "")
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "sms:")):
            continue
        url = urllib.parse.urldefrag(urllib.parse.urljoin(home_url, href))[0]
        if not same_site(home_url, url) or url.lower().split("?")[0].endswith(_SKIP_EXT):
            continue
        cat = classify(url, link.get("text", ""))
        if not cat or url.rstrip("/") in seen:
            continue
        seen.add(url.rstrip("/"))
        scored.append((order[cat], i, url, cat))
    scored.sort()
    taken, out = {}, []
    for _o, _i, url, cat in scored:
        if taken.get(cat, 0) >= 2 or len(out) >= budget:
            continue
        taken[cat] = taken.get(cat, 0) + 1
        out.append((url, cat))
    return out


GUESS = (("contact", "/contact"), ("contact", "/contact-us"), ("about", "/about"))


def clean_html(html, limit):
    """Drop what a reader never needs (scripts except JSON-LD, styles, svg, comments, iframes) and cap the size at a tag boundary."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<script\b(?![^>]*ld\+json)[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<(style|svg|noscript|iframe|template)\b[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r"\s{2,}", " ", html)
    if len(html.encode("utf-8")) <= limit:
        return html
    cut = html.encode("utf-8")[:limit].decode("utf-8", "ignore")
    k = cut.rfind(">")
    return cut[: k + 1] if k > limit // 2 else cut


# ───────────────────────────────────────────── the browser (a child process in the crawl venv)

def data_root():
    try:
        import nm_data

        return nm_data.data_root(HERE)
    except Exception:  # noqa: BLE001
        return os.environ.get("NM_DATA") or os.path.join(HERE, "data")


def venv_python(root=None):
    base = os.path.join(root or data_root(), "venvs", "crawl")
    return os.path.join(base, "Scripts", "python.exe") if IS_WIN else os.path.join(base, "bin", "python")


def playwright_installed(root=None):
    base = os.path.join(root or data_root(), "venvs", "crawl")
    pats = [os.path.join(base, "Lib", "site-packages", "playwright"), os.path.join(base, "lib", "python*", "site-packages", "playwright")]
    return any(glob.glob(p) for p in pats)


def find_browser():
    """{'channel': 'msedge'|'chrome', 'path'} / {'exe': path} / {} - the same search Abagram does (Edge first: Windows 11 has it)."""
    try:
        import abagram_jobs as AJ

        found = AJ.find_browser(AJ._layout_from_here())
        if found:
            return found
    except Exception:  # noqa: BLE001 - Abagram may be absent: look ourselves
        pass
    env = os.environ
    cands = []
    for base in (env.get("PROGRAMFILES(X86)"), env.get("PROGRAMFILES"), env.get("LOCALAPPDATA")):
        if base:
            cands.append(("msedge", os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")))
            cands.append(("chrome", os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")))
    for channel, path in cands:
        if os.path.isfile(path):
            return {"channel": channel, "path": path}
    return {}


_STATE = {"at": 0.0, "value": None}


def state(force=False):
    """What the heartbeat reports: is rendering possible here, and why not."""
    now = time.monotonic()
    if not force and _STATE["value"] is not None and now - _STATE["at"] < STATE_TTL_S:
        return _STATE["value"]
    root = data_root()
    py = venv_python(root)
    browser = find_browser()
    pw = playwright_installed(root) and os.path.isfile(py)
    value = {"static": True, "playwright": bool(pw), "browser": (browser.get("channel") or ("chromium" if browser.get("exe") else "")), "render": bool(pw and browser)}
    value["ready"] = value["render"]
    if not pw:
        value["problem"] = "playwright_not_installed"
    elif not browser:
        value["problem"] = "no_browser"
    _STATE["value"], _STATE["at"] = value, now
    return value


def render_urls(items, timeout_ms=RENDER_TIMEOUT_MS, allow_private=False, say_fn=say):
    """Render [{key, url}] in the browser (child process). Returns {key: {final_url, status, html, links, error}}. {} when rendering is impossible."""
    st = state(force=True)
    if not st["render"]:
        say_fn("render not possible here: %s" % st.get("problem", "unknown"))
        return {}
    out = {}
    py = venv_python()
    browser = find_browser()
    for i in range(0, len(items), RENDER_BATCH):
        chunk = items[i:i + RENDER_BATCH]
        with tempfile.TemporaryDirectory(prefix="nm-crawl-") as tmp:
            fin, fout = os.path.join(tmp, "in.json"), os.path.join(tmp, "out.json")
            with open(fin, "w", encoding="utf-8") as fh:
                json.dump({"items": chunk, "timeout_ms": timeout_ms, "ua": USER_AGENT, "browser": browser, "allow_private": allow_private}, fh)
            try:
                subprocess.run([py, os.path.abspath(__file__), "render-urls", fin, fout], timeout=60 + len(chunk) * (timeout_ms / 1000.0 + 8), check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=0x08000000 if IS_WIN else 0)
            except (subprocess.TimeoutExpired, OSError) as exc:
                say_fn("browser worker did not finish: %s" % type(exc).__name__)
                continue
            try:
                with open(fout, encoding="utf-8") as fh:
                    for row in json.load(fh):
                        out[row["key"]] = row
            except (OSError, ValueError):
                say_fn("browser worker left no answer")
    return out


def worker_render(infile, outfile):
    """Runs INSIDE the crawl venv: Playwright renders each url; navigations are limited to the page's own site."""
    from playwright.sync_api import sync_playwright  # noqa: WPS433 - only importable in the venv

    with open(infile, encoding="utf-8") as fh:
        spec = json.load(fh)
    results = []
    with sync_playwright() as pw:
        b = spec.get("browser") or {}
        launch = {"headless": True}
        if b.get("channel"):
            launch["channel"] = b["channel"]
        elif b.get("exe"):
            launch["executable_path"] = b["exe"]
        browser = pw.chromium.launch(**launch)
        try:
            for item in spec["items"]:
                row = {"key": item["key"], "final_url": item["url"], "status": 0, "html": "", "links": [], "error": ""}
                context = browser.new_context(user_agent=spec.get("ua"), locale="fa-IR", java_script_enabled=True, ignore_https_errors=False)
                page = context.new_page()
                start_host = (urllib.parse.urlsplit(item["url"]).hostname or "").lower()

                def guard(route, request, _host=start_host):
                    if request.resource_type in ("image", "media", "font"):
                        return route.abort()
                    if request.is_navigation_request() and request.frame == request.frame.page.main_frame:
                        host = (urllib.parse.urlsplit(request.url).hostname or "").lower()
                        if host.replace("www.", "") != _host.replace("www.", ""):
                            return route.abort()
                    return route.continue_()

                try:
                    page.route("**/*", guard)
                    resp = page.goto(item["url"], wait_until="domcontentloaded", timeout=int(spec.get("timeout_ms") or RENDER_TIMEOUT_MS))
                    try:
                        page.wait_for_load_state("networkidle", timeout=6000)
                    except Exception:  # noqa: BLE001 - some sites never go idle: take what is there
                        pass
                    page.wait_for_timeout(600)
                    row["status"] = resp.status if resp else 200
                    row["final_url"] = page.url
                    row["html"] = page.content()
                    row["links"] = page.evaluate("Array.from(document.querySelectorAll('a[href]')).slice(0,400).map(a => ({url: a.href, text: (a.innerText || '').trim().slice(0,60)}))")
                except Exception as exc:  # noqa: BLE001
                    row["error"] = type(exc).__name__ + ": " + str(exc)[:160]
                finally:
                    try:
                        context.close()
                    except Exception:  # noqa: BLE001
                        pass
                results.append(row)
        finally:
            browser.close()
    with open(outfile, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False)
    return 0


# ───────────────────────────────────────────── crawling the sites

def _page(url, kind, res, rendered=False, limit=150_000, note=""):
    return {"url": res.get("final_url") or url, "kind": kind, "status": res.get("status", 0), "outcome": res.get("outcome", "ok"), "rendered": rendered,
            "html": clean_html(res.get("html", ""), limit) if res.get("html") else "", "note": note}


def crawl_sites(sites, opts, progress=lambda f, m: None, fetcher=None, renderer=None):
    """Read the sites. `renderer(items)` -> {key: row} defaults to the browser child process. Returns a list of per-site dicts (see the module doc)."""
    fetcher = fetcher or Fetcher(delay=opts.get("domain_delay", 2.0), allow_private=opts.get("allow_private", False))
    renderer = renderer or (lambda items: render_urls(items, allow_private=opts.get("allow_private", False)))
    mode = opts.get("render", "auto")
    per_site = max(1, int(opts.get("max_pages_per_site", 5)))
    limit = int(opts.get("max_html_bytes", 150_000))
    total_cap = int(opts.get("total_bytes", 40_000_000))
    used = 0
    results = []
    # phase A: static home pages
    state_rows = []
    for n, site in enumerate(sites):
        progress(0.05 + 0.4 * n / max(1, len(sites)), "static %d/%d" % (n + 1, len(sites)))
        url = site.get("url", "")
        row = {"id": site.get("id"), "url": url, "status": "failed", "reason": "", "robots": "", "pages": []}
        info = {"row": row, "need_render": mode == "always", "home": None}
        if mode != "always":
            home = fetcher.get_page(url)
            info["home"] = home
            row["robots"] = home.get("robots", "")
            if home["outcome"] == "ok" and home["html"]:
                if mode == "auto" and looks_like_shell(home["html"]):
                    info["need_render"] = True
            elif home["outcome"] in ("robots_blocked", "robots_unavailable"):
                row["reason"] = home["outcome"]
                row["pages"].append(_page(url, "home", home, limit=limit))
                state_rows.append(info)
                continue
            else:
                row["reason"] = "fetch_failed"
                row["pages"].append(_page(url, "home", home, limit=limit))
                state_rows.append(info)
                continue
        else:
            ok, rstate = fetcher.allowed(url)
            row["robots"] = rstate
            if not ok:
                row["reason"] = "robots_unavailable" if rstate == "unavailable" else "robots_blocked"
                state_rows.append(info)
                continue
        state_rows.append(info)
    # phase B: render the homes that need it
    shells = [i for i in state_rows if i["need_render"] and not i["row"]["reason"]]
    rendered = renderer([{"key": "h%d" % k, "url": i["row"]["url"]} for k, i in enumerate(shells)]) if shells else {}
    for k, info in enumerate(shells):
        r = rendered.get("h%d" % k)
        info["rendered_home"] = r
    # phase C: choose the contact / about pages, fetch them (static, or rendered for rendered sites)
    to_render = []
    for n, info in enumerate(state_rows):
        row = info["row"]
        progress(0.45 + 0.45 * n / max(1, len(state_rows)), "pages %d/%d" % (n + 1, len(state_rows)))
        if row["reason"]:
            continue
        home_rendered = info.get("rendered_home")
        if info["need_render"] and home_rendered and home_rendered.get("html"):
            res = {"final_url": home_rendered["final_url"], "status": home_rendered["status"], "outcome": "ok" if int(home_rendered["status"] or 200) < 400 else "http_error", "html": home_rendered["html"]}
            row["pages"].append(_page(row["url"], "home", res, rendered=True, limit=limit))
            links = home_rendered.get("links") or []
            home_url = home_rendered["final_url"]
            use_render = True
        elif info["need_render"]:
            row["reason"] = "render_unavailable" if not state()["render"] else "render_failed"
            if info.get("home"):
                row["pages"].append(_page(row["url"], "home", info["home"], limit=limit, note="JavaScript shell; the browser could not render it"))
            continue
        else:
            home = info["home"]
            row["pages"].append(_page(row["url"], "home", home, limit=limit))
            s = scan(home["html"])
            links = s.links
            home_url = home.get("final_url") or row["url"]
            use_render = False
        row["status"] = "ok"
        chosen = pick_pages(links, home_url, per_site - 1)
        guessed = False
        if not chosen and per_site > 1:
            base = "%s://%s" % urllib.parse.urlsplit(home_url)[:2]
            chosen = [(base + path, cat) for cat, path in GUESS[:min(2, per_site - 1)]]
            guessed = True
        for url, cat in chosen:
            if used > total_cap:
                break
            if use_render:
                ok, _s = fetcher.allowed(url)
                if ok:
                    to_render.append((info, url, "guess" if guessed else cat))
                else:
                    row["pages"].append({"url": url, "kind": cat, "status": 0, "outcome": "robots_blocked", "rendered": True, "html": "", "note": ""})
                continue
            res = fetcher.get_page(url)
            used += len(res.get("html", ""))
            if res["outcome"] == "ok" or not guessed:
                row["pages"].append(_page(url, "guess" if guessed else cat, res, limit=limit))
    if to_render:
        got = renderer([{"key": "p%d" % k, "url": u} for k, (_i, u, _c) in enumerate(to_render)])
        for k, (info, url, cat) in enumerate(to_render):
            r = got.get("p%d" % k)
            if r and r.get("html"):
                info["row"]["pages"].append(_page(url, cat, {"final_url": r["final_url"], "status": r["status"], "outcome": "ok" if int(r["status"] or 200) < 400 else "http_error", "html": r["html"]}, rendered=True, limit=limit))
            else:
                info["row"]["pages"].append({"url": url, "kind": cat, "status": 0, "outcome": "connect_error", "rendered": True, "html": "", "note": (r or {}).get("error", "")})
    for info in state_rows:
        results.append(info["row"])
    progress(0.95, "done")
    return results


# ───────────────────────────────────────────── the job handlers

def _opts(p, kind):
    return {
        "render": "always" if kind == "crawl.render" else (p.get("render") if p.get("render") in ("never", "auto", "always") else "auto"),
        "max_pages_per_site": max(1, min(10, int(p.get("max_pages_per_site") or 5))), "domain_delay": max(1.0, min(30.0, float(p.get("domain_delay") or 2.0))),
        "max_html_bytes": max(20_000, min(400_000, int(p.get("max_html_bytes") or 150_000))), "total_bytes": int(p.get("total_bytes") or 40_000_000),
    }


def run(job, agent=None, kind="crawl.run"):
    p = job.payload or {}
    if kind == "crawl.selftest" or p.get("selftest"):
        return selftest(job)
    sites = [s for s in (p.get("sites") or []) if isinstance(s, dict) and s.get("url")][:200]
    opts = _opts(p, kind)
    say("%s: %d site(s), render=%s" % (kind, len(sites), opts["render"]))

    def progress(f, m):
        job.progress(max(0.02, min(0.97, f)), m[:100])

    results = crawl_sites(sites, opts, progress=progress)
    with gzip.open(job.out("pages.jsonl.gz"), "wt", encoding="utf-8") as fh:
        for row in results:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"primary": "pages.jsonl.gz", "engine": "crawl", "sites": len(results), "ok": sum(1 for r in results if r["status"] == "ok"),
            "rendered": sum(1 for r in results for pg in r["pages"] if pg.get("rendered")), "run_id": p.get("run_id"), "state": state()}


# ───────────────────────────────────────────── the automatic acceptance test

def selftest(job=None):
    """A static page and a JavaScript-only page on 127.0.0.1; both must be read (the second one needs the browser)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    pages = {
        "/": '<html lang="fa"><body><h1>باشگاه نمونه</h1><p>تلفن: <a href="tel:+989121234567">۰۹۱۲ ۱۲۳ ۴۵۶۷</a></p><a href="/contact">تماس با ما</a></body></html>',
        "/contact": "<html lang='fa'><body><h1>تماس با ما</h1><p>ایمیل: <a href='mailto:info@example.ir'>info@example.ir</a></p></body></html>",
        "/js/": '<html><head><title>app</title></head><body><div id="root"></div><script>document.getElementById("root").innerHTML="<h1>باشگاه جاوا</h1><p>تلفن 09125550000</p><a href=\'/js/contact\'>تماس با ما</a>";</script><script>1</script></body></html>',
        "/js/contact": "<html><body><div id='root'></div><script>document.getElementById('root').innerHTML='<p>info@js-gym.ir</p>';</script><script>1</script></body></html>",
    }

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = pages.get(self.path.split("?")[0])
            if self.path == "/robots.txt":
                self.send_response(404)
                self.end_headers()
                return
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # noqa: D401
            return

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    checks = []
    try:
        base = "http://127.0.0.1:%d" % port
        # loopback is "private": the guard must refuse it in normal mode
        try:
            resolve_public("127.0.0.1", port)
            checks.append({"name": "ssrf_guard", "ok": False, "detail": "loopback was not refused"})
        except ValueError as exc:
            checks.append({"name": "ssrf_guard", "ok": str(exc) == "ssrf_blocked", "detail": str(exc)})
        opts = {"render": "auto", "max_pages_per_site": 3, "domain_delay": 1.0, "max_html_bytes": 100_000, "allow_private": True}
        fetcher = Fetcher(delay=0.0, allow_private=True)
        rows = crawl_sites([{"id": 1, "url": base + "/"}, {"id": 2, "url": base + "/js/"}], opts, fetcher=fetcher, renderer=lambda items: render_urls(items, allow_private=True))
        by_id = {r["id"]: r for r in rows}
        static_html = " ".join(pg["html"] for pg in by_id[1]["pages"])
        checks.append({"name": "static_site", "ok": by_id[1]["status"] == "ok" and "9121234567" in static_html and "info@example.ir" in static_html,
                       "detail": "%d page(s)" % len(by_id[1]["pages"])})
        st = state(force=True)
        checks.append({"name": "browser_ready", "ok": bool(st["render"]), "detail": json.dumps(st, ensure_ascii=False)})
        js_html = " ".join(pg["html"] for pg in by_id[2]["pages"])
        checks.append({"name": "javascript_site_rendered", "ok": by_id[2]["status"] == "ok" and "09125550000" in js_html and any(pg.get("rendered") for pg in by_id[2]["pages"]),
                       "detail": by_id[2].get("reason") or "%d page(s), rendered" % len(by_id[2]["pages"])})
    finally:
        srv.shutdown()
    ok = all(c["ok"] for c in checks)
    report = {"ok": ok, "checks": checks, "version": VERSION}
    if job is not None:
        with open(job.out("selftest.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False)
        return {"primary": "selftest.json", "engine": "crawl", "ok": ok}
    return report


# ───────────────────────────────────────────── registration into agent.py (one guarded line there)

def caps(agent=None):
    st = state()
    return {"crawl": True, "crawl_ready": bool(st.get("ready")), "crawl_runtime": st}


def register(handlers, agent):
    """The ONE call agent.py makes: the three kinds, the capability in every heartbeat (so the site routes the kinds here and nowhere else), and
    'no GPU slot' (a crawl uses the network and the browser, not the card)."""
    handlers["crawl.run"] = lambda job: run(job, agent, "crawl.run")
    handlers["crawl.render"] = lambda job: run(job, agent, "crawl.render")
    handlers["crawl.selftest"] = lambda job: selftest(job)
    try:
        agent.BACKGROUND_KINDS = tuple(agent.BACKGROUND_KINDS) + tuple(k for k in KINDS if k not in agent.BACKGROUND_KINDS)
    except Exception:  # noqa: BLE001
        pass
    cls = getattr(agent, "Capabilities", None)
    orig = getattr(cls, "probe", None)
    if orig is not None and not getattr(orig, "_crawl", False):
        def probe(self):
            out = orig(self)
            try:
                out.update(caps(agent))
            except Exception as e:  # noqa: BLE001 - an optional module must never keep the heartbeat from going out
                out["crawl"] = True
                out["crawl_ready"] = False
                say("capabilities could not be read: %s" % e)
            return out

        probe._crawl = True
        cls.probe = probe
    return True


# ───────────────────────────────────────────── command line (the install list uses check-browser; render-urls is the child process)

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "render-urls" and len(argv) == 3:
        return worker_render(argv[1], argv[2])
    if cmd == "check-browser":
        b = find_browser()
        print("browser: %s" % (b.get("channel") or ("chromium" if b.get("exe") else "none found")), flush=True)
        return 0 if b else 1
    if cmd == "selftest":
        rep = selftest(None)
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0 if rep["ok"] else 1
    print(json.dumps(state(force=True), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
