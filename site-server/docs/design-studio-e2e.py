#!/usr/bin/env python3
"""مرورگرِ واقعی (Playwright، Chromium بی‌سر) روی «استودیوی طراحی»، دسکتاپ ۱۴۴۰×۹۰۰ و گوشی ۳۹۰×۸۴۴ — همان آزمونی که پیش از تحویل روی stage اجرا شد.

پیش‌نیاز: سرورِ API و ساختِ پنل (QA_BASE)، یک کاربرِ کارمند (متغیرهای QA_USER و QA_PASS؛ رمز در کد نیست)، و سه سندِ چغر (`manage.py design_chagher_drafts`؛ شناسهٔ
کاتالوگ/ارائه/طرح UI = ۱/۲/۳ — در همین فایل عوض کنید). هر گامِ شکست‌خورده یک عکس در QA_OUT می‌گذارد. QA_ONLY=phone|desktop فقط یک اندازه را اجرا می‌کند. اجرا:
    PLAYWRIGHT_BROWSERS_PATH=<مسیر> python docs/design-studio-e2e.py
"""
import json, os, sys, time, traceback, urllib.request
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:5261")
API = BASE + "/api/v1"
STORE = int(os.environ.get("QA_STORE", "34"))
OUT = os.environ.get("QA_OUT", "/tmp/design-studio-shots")
os.makedirs(OUT, exist_ok=True)
req = urllib.request.Request(API + "/auth/login/", data=json.dumps({"username": os.environ["QA_USER"], "password": os.environ["QA_PASS"]}).encode(), headers={"Content-Type": "application/json"})
TOK = json.loads(urllib.request.urlopen(req).read())
RESULTS, ISSUES = [], []


def step(name, fn, page, tag):
    t = time.time()
    try:
        fn()
        RESULTS.append((tag, name, "ok", round(time.time() - t, 1)))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((tag, name, "FAIL: " + str(e)[:300], round(time.time() - t, 1)))
        try:
            page.screenshot(path=f"{OUT}/{tag}-FAIL-{len(RESULTS)}.png")
        except Exception:
            pass


def new_page(browser, w, h, tag):
    ctx = browser.new_context(viewport={"width": w, "height": h}, locale="fa-IR", accept_downloads=True)
    ctx.add_init_script("try{localStorage.setItem('access','%s');localStorage.setItem('refresh','%s');localStorage.setItem('theme','light')}catch(e){}" % (TOK["access"], TOK["refresh"]))
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept("پاسخِ آزمون") if d.type == "prompt" else d.accept())
    page.on("pageerror", lambda e: ISSUES.append((tag, "pageerror", str(e)[:200])))
    page.on("console", lambda m: ISSUES.append((tag, "console." + m.type, m.text[:200])) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("response", lambda r: ISSUES.append((tag, f"http{r.status}", r.url[-110:])) if r.status >= 400 and r.status != 401 and "/auth/" not in r.url else None)
    return ctx, page


def goto(page, path):
    page.goto(BASE + "/panel" + path, wait_until="domcontentloaded")


def preview_loaded(page, sel=".ds-canvas img"):
    page.wait_for_function("(s) => { const i = document.querySelector(s); return i && i.complete && i.naturalWidth > 50; }", arg=sel, timeout=45000)


def no_hscroll(page):
    ok = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2")
    assert ok, "horizontal overflow: %s > %s" % (page.evaluate("document.documentElement.scrollWidth"), page.evaluate("window.innerWidth"))


def run(browser, w, h, tag, full):
    ctx, page = new_page(browser, w, h, tag)
    base = f"/stores/{STORE}/design"

    def home():
        goto(page, base)
        page.get_by_text("آخرین سندها").wait_for(timeout=30000)
        assert page.locator(".ds-kind").count() == 3, "three kinds"
        assert page.get_by_text("کاتالوگِ چغر").first.is_visible()
        no_hscroll(page)
        page.screenshot(path=f"{OUT}/{tag}-home.png")
    step("home", home, page, tag)

    def menu():
        goto(page, base)
        page.get_by_text("آخرین سندها").wait_for(timeout=30000)
        if w < 900:
            page.get_by_role("button", name="منو").first.click()
            page.wait_for_timeout(400)
        grp = page.locator("button.u-nav-group:visible", has_text="استودیوی طراحی").first
        grp.wait_for(state="visible", timeout=20000)
        if grp.get_attribute("aria-expanded") != "true":
            grp.click()
        for label in ("کاتالوگ محصولات", "ارائه (اسلاید)", "طراحی UI/UX", "راهنمای فایل‌ها"):
            assert page.locator("a.u-nav-item:visible", has_text=label).count() >= 1, label
        if w < 900:
            page.get_by_role("button", name="بستن منو").first.click()
    step("sidebar section present", menu, page, tag)

    def guide():
        goto(page, base + "/guide")
        page.get_by_text("کدام فایل را به چه کسی بدهیم").first.wait_for(timeout=30000)
        no_hscroll(page)
        page.screenshot(path=f"{OUT}/{tag}-guide.png", full_page=True)
    step("guide page", guide, page, tag)

    def catalog_list():
        goto(page, base + "/catalog")
        page.get_by_text("کاتالوگِ چغر").first.wait_for(timeout=30000)
        no_hscroll(page)
    step("catalog list", catalog_list, page, tag)

    def catalog_editor():
        goto(page, base + "/catalog/1")
        page.locator(".ds-thumb").first.wait_for(timeout=40000)
        preview_loaded(page)
        n = page.locator(".ds-thumb").count()
        assert n >= 8, f"{n} pages"
        no_hscroll(page)
        page.screenshot(path=f"{OUT}/{tag}-catalog.png")
        # open the grid page, select an element, edit its text
        page.locator(".ds-thumb").nth(4).click()
        preview_loaded(page)
        rects = page.locator("svg.ds-overlay rect.ds-hit")
        assert rects.count() > 5, "overlay rects"
        rects.nth(2).click(force=True)
        page.get_by_role("tab", name="عنصر").wait_for()
        ta = page.locator(".ds-panel textarea").first
        if ta.count():
            ta.fill("متنِ ویرایش‌شدهٔ آزمون")
            with page.expect_response(lambda r: "/ops/" in r.url and r.status == 200, timeout=30000):
                ta.blur()
        # drag the element
        box = rects.nth(2).bounding_box()
        if box and full:
            with page.expect_response(lambda r: "/ops/" in r.url and r.status == 200, timeout=30000):
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.mouse.down()
                page.mouse.move(box["x"] + box["width"] / 2 + 30, box["y"] + box["height"] / 2 + 20, steps=6)
                page.mouse.up()
        page.screenshot(path=f"{OUT}/{tag}-catalog-edit.png")
    step("catalog editor: thumbs, preview, select, edit, drag", catalog_editor, page, tag)

    def catalog_settings():
        page.get_by_role("tab", name="تنظیمات").click()
        page.get_by_text("فونت‌ها و مجوز").wait_for()
        assert "SIL OFL" in page.locator(".ds-fonts").inner_text()
        page.get_by_role("tab", name="چک‌لیست").click()
        page.get_by_text("چک‌لیستِ چاپخانه").first.wait_for()
        page.screenshot(path=f"{OUT}/{tag}-catalog-checks.png")
    step("catalog settings and print checklist", catalog_settings, page, tag)

    def export_dialog():
        page.get_by_role("button", name="خروجی و تحویل").click()
        page.get_by_text("کدام فایل را به چه کسی بده؟").wait_for()
        assert page.locator(".ds-recip").count() == 4, "catalog recipients"
        page.screenshot(path=f"{OUT}/{tag}-export.png")
        with page.expect_response(lambda r: r.url.endswith("/exports/") and r.request.method == "POST", timeout=120000):
            page.locator(".ds-recip").first.get_by_role("button").click()
        page.locator(".ds-exp.is-ready").first.wait_for(timeout=180000)
        with page.expect_download(timeout=60000) as d:
            page.locator(".ds-exp.is-ready").first.get_by_role("button", name="دانلود").click()
        path = d.value.path()
        assert os.path.getsize(path) > 10000, "pack size"
        RESULTS.append((tag, "downloaded pack", "ok", os.path.getsize(path)))
        if full:
            with page.expect_response(lambda r: r.url.endswith("/exports/") and r.request.method == "POST", timeout=120000):
                page.locator(".ds-single").first.get_by_role("button").click()
            page.wait_for_function("document.querySelectorAll('.ds-exp.is-ready').length >= 2", timeout=240000)
            page.screenshot(path=f"{OUT}/{tag}-export-done.png")
        page.get_by_role("button", name="بستن").first.click()
    step("export dialog: pack + pdf + download", export_dialog, page, tag)

    def designer_bridge():
        with page.expect_response(lambda r: "/designer/" in r.url, timeout=120000) as r:
            page.get_by_role("button", name="ویرایش در طراح").click()
        assert r.value.status == 201, r.value.status
    if full:
        step("edit in designer", designer_bridge, page, tag)

    def deck_editor():
        goto(page, base + "/deck/2")
        page.locator(".ds-thumb").first.wait_for(timeout=40000)
        preview_loaded(page)
        assert page.locator(".ds-thumb").count() >= 8
        no_hscroll(page)
        page.screenshot(path=f"{OUT}/{tag}-deck.png")
        page.get_by_role("tab", name="پیش‌نویس").click()
        page.get_by_text("پیش‌نویسِ ارائه از خلاصه").wait_for()
        page.get_by_role("tab", name="صفحه").click()
        page.locator(".ds-panel textarea").last.wait_for()
    step("deck editor", deck_editor, page, tag)

    def presenter():
        page.get_by_role("link", name="نمای ارائه‌دهنده").click()
        page.get_by_text("یادداشتِ گوینده").first.wait_for(timeout=30000)
        preview_loaded(page)
        before = page.locator(".ds-present-bar b").inner_text()
        page.keyboard.press("ArrowLeft")
        page.wait_for_function("(b) => document.querySelector('.ds-present-bar b').innerText !== b", arg=before, timeout=10000)
        page.screenshot(path=f"{OUT}/{tag}-presenter.png")
        page.keyboard.press("Escape")
    step("presenter view navigation", presenter, page, tag)

    def deck_video():
        goto(page, base + "/deck/2")
        page.get_by_role("button", name="خروجی و تحویل").wait_for(timeout=40000)
        page.get_by_role("button", name="خروجی و تحویل").click()
        page.get_by_text("ویدیو از ارائه (MP4)").wait_for()
        page.screenshot(path=f"{OUT}/{tag}-deck-video.png")
        page.get_by_role("button", name="بستن").first.click()
    step("deck export dialog has video section", deck_video, page, tag)

    def ui_editor():
        goto(page, base + "/ui/3")
        page.locator(".ds-thumb").first.wait_for(timeout=40000)
        preview_loaded(page)
        assert page.locator(".ds-thumb").count() == 3, "three frames"
        no_hscroll(page)
        page.screenshot(path=f"{OUT}/{tag}-ui.png")
        assert page.locator(".ds-layer").count() >= 7, "layers"
        page.locator(".ds-layer-name").nth(1).click()
        page.get_by_text("پیوندِ نمونهٔ اولیه").wait_for()
        page.screenshot(path=f"{OUT}/{tag}-ui-props.png")
    step("ui editor: frames, layers, props", ui_editor, page, tag)

    def ui_style():
        page.get_by_role("tab", name="سبک و توکن").click()
        page.get_by_text("سبکِ طراحی (از ۱۴ سبکِ ui-ux-pro-max)").wait_for()
        assert page.locator(".ds-style").count() >= 14
        with page.expect_response(lambda r: "/ops/" in r.url and r.status == 200, timeout=30000):
            page.locator(".ds-style").nth(1).click()
        page.screenshot(path=f"{OUT}/{tag}-ui-style.png")
        page.get_by_role("tab", name="راهنمای سبک").click()
        page.wait_for_function("() => { const i = document.querySelector('.ds-guide img'); return i && i.complete && i.naturalWidth > 100; }", timeout=45000)
        page.screenshot(path=f"{OUT}/{tag}-ui-guide.png")
    step("ui style switch and style guide", ui_style, page, tag)

    def ui_dark_and_proto():
        page.get_by_role("button", name="پیش‌نمایشِ تیره").click()
        preview_loaded(page)
        page.screenshot(path=f"{OUT}/{tag}-ui-dark.png")
        page.get_by_role("button", name="پیش‌نمایشِ روشن").click()
        page.get_by_role("tab", name="نمونهٔ اولیه").click()
        page.get_by_text("نمونهٔ کلیک‌پذیر").first.wait_for()
    step("ui dark preview + prototype tab", ui_dark_and_proto, page, tag)

    def ui_comment():
        page.get_by_role("tab", name="نظرها").click()
        page.get_by_text("برای نظر دادن روی جای دقیق کلیک کن").wait_for()
        ov = page.locator(".ds-canvas svg.ds-overlay").first
        bb = ov.bounding_box()
        ov.click(position={"x": bb["width"] * 0.4, "y": min(bb["height"] * 0.1, 120)})
        page.locator(".ds-panel textarea").first.fill("نظرِ آزمون: این بخش بزرگ‌تر شود")
        with page.expect_response(lambda r: "/comments/" in r.url and r.request.method == "POST" and r.status == 201, timeout=20000):
            page.get_by_role("button", name="ثبتِ نظر").click()
        page.get_by_text("نظرِ آزمون").first.wait_for()
    step("ui comment pin", ui_comment, page, tag)

    def ui_add_and_link():
        page.get_by_role("tab", name="لایه‌ها").click()
        sel = page.locator("select[aria-label='قطعه']")
        with page.expect_response(lambda r: "/ops/" in r.url and r.status == 200, timeout=30000):
            sel.select_option(index=3)
        page.get_by_role("tab", name="ویژگی").wait_for()
    if full:
        step("ui add component", ui_add_and_link, page, tag)

    def ui_to_site():
        with page.expect_response(lambda r: r.url.endswith("/site/") and r.request.method == "POST", timeout=60000) as r:
            page.get_by_role("button", name="ساختِ سایت از این طرح").click()
        assert r.value.status == 201, r.value.status
        page.get_by_text("پیش‌نویسِ سایت ساخته شد (منتشر نشده)").wait_for(timeout=20000)
        page.screenshot(path=f"{OUT}/{tag}-ui-site.png")
    if full:
        step("ui -> site builder draft", ui_to_site, page, tag)

    def ui_export():
        page.get_by_role("button", name="خروجی (PNG، SVG، PDF)").click()
        page.get_by_text("کدام فایل را به چه کسی بده؟").wait_for()
        with page.expect_response(lambda r: r.url.endswith("/exports/") and r.request.method == "POST", timeout=120000):
            page.locator(".ds-singles .ds-single").nth(1).get_by_role("button").click()   # svg
        page.locator(".ds-exp.is-ready").first.wait_for(timeout=180000)
        page.get_by_role("button", name="بستن").first.click()
    if full:
        step("ui export svg", ui_export, page, tag)
    ctx.close()


with sync_playwright() as p:
    br = p.chromium.launch()
    only = os.environ.get("QA_ONLY", "")
    if only != "phone":
        run(br, 1440, 900, "desktop", True)
    if only != "desktop":
        run(br, 390, 844, "phone", False)
    br.close()
for r in RESULTS:
    print(r)
bad = [r for r in RESULTS if not str(r[2]).startswith("ok")]
print("ISSUES", len(ISSUES))
seen = set()
for i in ISSUES:
    if i not in seen:
        seen.add(i)
        print(i)
print("RESULT", "FAIL" if bad else "PASS", len(RESULTS), "steps")
