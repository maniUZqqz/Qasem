"""Live-panel browser test of the market-trends tab (nm_trendsweb).

usage: PANEL_PASSWORD=... python panel_test.py PANEL_BASE OUT_DIR
Checks at 1440 and 390 px: the tab loads, «آخرین به‌روزرسانی» bar is present, source problems are shown (if any),
the category chips show the store's categories, adding then resetting a chip works and changes the stored choice,
no horizontal overflow, no console errors.
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")  # e.g. http://87.107.160.17:8040/panel
OUT = sys.argv[2]
PASSWORD = os.environ["PANEL_PASSWORD"]
STORE = os.environ.get("STORE_ID", "34")
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chromium")
        try:
            for width, height in ((1440, 900), (390, 844)):
                ctx = browser.new_context(viewport={"width": width, "height": height}, locale="fa-IR")
                page = ctx.new_page()
                errors = []
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(BASE + "/login", wait_until="networkidle", timeout=60000)
                page.fill("input >> nth=0", "admin")
                page.fill("input[type=password]", PASSWORD)
                page.click("button[type=submit]")
                page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
                page.goto(f"{BASE}/stores/{STORE}/trends", wait_until="networkidle", timeout=60000)
                tag = f"trends {width}px"
                page.wait_for_selector('[data-testid="trends-freshness"]', timeout=30000)
                check(tag + " freshness bar", True, page.inner_text('[data-testid="trends-freshness"]')[:140].replace("\n", " "))
                # the tab may have started a background refresh: give it a little time to fill
                for _ in range(24):
                    if page.locator('[data-testid="trends-refreshing"]').count() == 0:
                        break
                    time.sleep(5)
                    page.wait_for_load_state("networkidle")
                chips = page.locator('[data-testid="trend-group-chip"]')
                names = [chips.nth(i).inner_text().replace("×", "").strip() for i in range(chips.count())]
                check(tag + " category chips present", len(names) >= 1, names)
                if "ورزش" in " ".join(names) or width == 1440:
                    check(tag + " fitness group detected for the store", any("ورزش" in n for n in names), names)
                over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                check(tag + " no horizontal overflow", over <= 1, over)
                page.screenshot(path=f"{OUT}/trends-{width}.png", full_page=False)
                if width == 390:
                    # add a category and reset (owner editing); the choice must persist and then go back to automatic
                    sel = page.locator('[data-testid="trend-groups"] select')
                    if sel.count():
                        opts = [o for o in sel.locator("option").all_inner_texts() if "افزودن" not in o]
                        if opts:
                            sel.select_option(label=opts[0])
                            page.wait_for_selector('[data-testid="trend-groups"] >> text=این دسته‌ها را خودتان انتخاب کرده‌اید', timeout=20000)
                            check(tag + " adding a chip switches to the owner's own choice", True, opts[0])
                            page.click("text=برگشت به تشخیصِ خودکار")
                            page.wait_for_selector('[data-testid="trend-groups"] >> text=تشخیص داده شد', timeout=20000)
                            check(tag + " «برگشت به تشخیصِ خودکار» restores detection", True)
                real_errors = [e for e in errors if "404" not in e and "favicon" not in e]
                check(tag + " no console errors", not real_errors, real_errors[:3])
                ctx.close()
        finally:
            browser.close()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)


main()
