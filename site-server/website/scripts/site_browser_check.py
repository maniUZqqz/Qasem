"""Browser test of the public website (nm_trendsweb): contact form, header on phones, branded 404.

usage: python site_test.py BASE_URL OUT_DIR [--submit]
  --submit  really submits the contact form (only against a throw-away backend, or the live one with the marked test lead)
"""
import json
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
OUT = sys.argv[2]
SUBMIT = "--submit" in sys.argv
ORIGIN = "{u.scheme}://{u.netloc}".format(u=urlparse(BASE))

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (("  | " + str(detail)) if detail else ""), flush=True)


def header_metrics(page):
    return page.evaluate(
        """() => {
          const bar = document.querySelector('header, .site-bar');
          if (!bar) return null;
          const hb = bar.getBoundingClientRect();
          const items = [...bar.querySelectorAll('a, button')].filter(e => {
            const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
            return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
          }).map(e => { const r = e.getBoundingClientRect();
            return {text: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 24), x: r.x, y: r.y, w: r.width, h: r.height, r: r.right, b: r.bottom}; });
          return {bar: {y: hb.y, h: hb.height, b: hb.bottom}, items,
                  scrollW: document.documentElement.scrollWidth, innerW: window.innerWidth};
        }"""
    )


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chromium")
        try:
            # ---------------------------------------------------------------- header on phones
            for width in (360, 390, 414, 1440):
                ctx = browser.new_context(viewport={"width": width, "height": 800}, locale="fa-IR")
                page = ctx.new_page()
                for path in ("/", "/pricing", "/contact", "/en", "/en/pricing"):
                    page.goto(BASE + path, wait_until="networkidle", timeout=60000)
                    m = header_metrics(page)
                    tag = f"header {width}px {path}"
                    if not m:
                        check(tag + " exists", False)
                        continue
                    cta = [i for i in m["items"] if i["text"] in ("شروع رایگان", "شروع", "Start free", "Start", "Get started")
                           or "رایگان" in i["text"] or "free" in i["text"].lower() or i["text"] in ("شروع", "Start")]
                    inside = all(i["y"] >= m["bar"]["y"] - 0.5 and i["b"] <= m["bar"]["b"] + 0.5 and i["x"] >= -0.5 and i["r"] <= m["innerW"] + 0.5
                                 for i in m["items"])
                    check(tag + " every control inside the bar and the screen", inside,
                          json.dumps({"bar": m["bar"], "bad": [i for i in m["items"] if not (i["y"] >= m["bar"]["y"] - 0.5 and i["b"] <= m["bar"]["b"] + 0.5 and i["r"] <= m["innerW"] + 0.5)]}, ensure_ascii=False)[:300])
                    check(tag + " no horizontal scroll", m["scrollW"] <= m["innerW"] + 1, f"{m['scrollW']} vs {m['innerW']}")
                    one_line = all(i["h"] <= 56 for i in m["items"])
                    check(tag + " no control is taller than 56px (nothing wraps)", one_line, [i for i in m["items"] if i["h"] > 56])
                    if width <= 414:
                        small = [i for i in m["items"] if i["h"] < 40]
                        check(tag + " controls are at least 40px tall", not small, small)
                    if path == "/" and width in (360, 1440):
                        page.screenshot(path=f"{OUT}/header-{width}.png", clip={"x": 0, "y": 0, "width": width, "height": 140})
                ctx.close()

            # ---------------------------------------------------------------- branded 404
            for width in (390, 1440):
                ctx = browser.new_context(viewport={"width": width, "height": 800}, locale="fa-IR")
                page = ctx.new_page()
                for path, lang, want_dir in (("/this-page-does-not-exist", "fa", "rtl"), ("/en/nope", "en", "ltr"),
                                             ("/blog/no-such-article-zz", "fa", "rtl")):
                    resp = page.goto(BASE + path, wait_until="networkidle", timeout=60000)
                    title = page.title()
                    html_lang = page.evaluate("document.documentElement.lang")
                    html_dir = page.evaluate("document.documentElement.dir")
                    has_header = page.locator("header").count() > 0
                    nf = page.locator('[data-testid="not-found"]').count() > 0
                    links = page.evaluate("[...document.querySelectorAll('[data-testid=not-found] a')].map(a => a.getAttribute('href'))")
                    tag = f"404 {width}px {path}"
                    check(tag + " HTTP 404", resp and resp.status == 404, resp.status if resp else None)
                    check(tag + " is not Next's English default", "could not be found" not in title.lower() or lang == "en", title)
                    check(tag + " has header and branded body", has_header and nf)
                    check(tag + f" lang={lang} dir={want_dir}", html_lang.split("-")[0] == lang and html_dir == want_dir, f"{html_lang}/{html_dir}")
                    prefix = "/en" if lang == "en" else ""
                    check(tag + " links to home, pricing and blog", all(any(l == (prefix + x if prefix + x else "/") for l in links) for x in ("/pricing", "/blog")) and any(l in ("/", "/en") for l in links), links)
                    if path == "/this-page-does-not-exist" or path == "/en/nope":
                        page.screenshot(path=f"{OUT}/404-{width}-{lang}.png")
                    m = header_metrics(page)
                    check(tag + " no horizontal scroll", m and m["scrollW"] <= m["innerW"] + 1)
                ctx.close()

            # ---------------------------------------------------------------- contact form
            ctx = browser.new_context(viewport={"width": 390, "height": 900}, locale="fa-IR")
            page = ctx.new_page()
            foreign, seen = [], []

            def on_request(req):
                u = req.url
                if "/api/" in u:
                    seen.append((req.method, u))
                    if not u.startswith(ORIGIN):
                        foreign.append(u)
                if "127.0.0.1" in u and not u.startswith(ORIGIN):
                    foreign.append(u)

            page.on("request", on_request)
            console_errors = []
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.goto(BASE + "/contact", wait_until="networkidle", timeout=60000)
            check("contact: form present", page.locator("form input[name=name]").count() == 1)
            if SUBMIT:
                page.fill("input[name=name]", "تست خودکار NM (حذف شود)")
                page.fill("input[name=email]", "nm-trendsweb-test@example.invalid")
                page.fill("input[name=business]", "NM-AUTOTEST")
                page.fill("textarea[name=message]", "این پیام آزمون خودکار است و باید حذف شود. NM-AUTOTEST-" + str(int(time.time())))
                with page.expect_response(lambda r: "/api/v1/leads/" in r.url and r.request.method == "POST", timeout=30000) as ri:
                    page.click("form button[type=submit]")
                r = ri.value
                check("contact: POST goes to the site's own origin", r.url.startswith(ORIGIN + "/api/v1/leads/"), r.url)
                check("contact: server accepted it (2xx)", 200 <= r.status < 300, r.status)
                page.wait_for_selector("text=پیام شما رسید", timeout=15000)
                check("contact: «پیام شما رسید» is shown", True)
                page.screenshot(path=f"{OUT}/contact-sent-390.png")
            else:
                # an empty submit must still be answered by the SITE'S backend with Persian errors (400), never by 127.0.0.1
                page.fill("input[name=name]", "ab")
                page.fill("input[name=email]", "x@example.invalid")
                page.fill("textarea[name=message]", "کوتاه است و باید رد شود، ولی فقط برای آزمون مسیر")
                with page.expect_response(lambda r: "/api/v1/leads/" in r.url and r.request.method == "POST", timeout=30000) as ri:
                    page.click("form button[type=submit]")
                check("contact: POST reached the site's own origin", ri.value.url.startswith(ORIGIN + "/api/v1/leads/"), ri.value.url)
            time.sleep(4)  # analytics flush
            check("no API request left the site's origin", not foreign, foreign)
            check("analytics posted same-origin (if any)", all(u.startswith(ORIGIN) for _, u in seen), seen[:4])
            check("no console errors on /contact", not [e for e in console_errors if "404" not in e], console_errors[:3])
            ctx.close()
        finally:
            browser.close()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)


main()
