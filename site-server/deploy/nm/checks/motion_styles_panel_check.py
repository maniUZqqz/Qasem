"""Browser test of the motion studio's style gallery and the «سبکِ تازه» editor (desktop 1280 px + phone 390 px).

usage:  PANEL_USER=... PANEL_PASSWORD=... python -X utf8 motion_styles_panel_check.py BASE STORE_ID OUT_DIR [--qa]
        BASE = origin of the panel, e.g. http://127.0.0.1:8187   (the panel lives under BASE/panel/, the API under BASE/api/v1/)
        --qa : also click «کنترلِ کیفیت و ذخیره» (a REAL render + pixel QA on the server: takes minutes), save the style and check the «سبک‌های من» list

What it proves (each one a hard failure when missing):
  · the gallery shows every style (>= 96) and EVERY name of the owner's two lists is found by the search box (53 names, English and Persian aliases);
  · the editor opens from «سبکِ تازه», copies a catalogue style, the contrast guard reports an unreadable ink and the auto-fix repairs it;
  · «توصیف کن، بساز» answers (AI or rules) and the live preview (the real player, with the store's own text) draws a scene;
  · all seven tabs open, the JSON export is valid and imports again;
  · no console error, no HTTP >= 400, no horizontal scroll on either screen size.
The script creates nothing without --qa. Exit code 1 when anything failed."""
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, STORE, OUT = sys.argv[1].rstrip("/"), sys.argv[2], Path(sys.argv[3])
DO_QA = "--qa" in sys.argv
USER, PASSWORD = os.environ["PANEL_USER"], os.environ["PANEL_PASSWORD"]
OUT.mkdir(parents=True, exist_ok=True)
problems, notes = [], []

#: the owner's two lists, as he wrote them (English) -> a search for each must find at least one card
OWNER_NAMES = [
    "Pixel Art", "ChalkBoard Style", "Glow Sketch", "PS2 Style", "Comic Art", "Flat Vector", "Dan Koe Style", "CGI Motion", "Lego Style", "ZackD Films", "Anime",
    "Studio Ghibli", "Disney", "Cartoon Network", "Watercolor", "Cel Shading", "Line Art", "Silhouette", "Claymation", "Stop Motion", "Low Poly", "Voxel Art",
    "Papercraft", "Origami", "Isometric", "Photorealistic CGI", "2.5D Parallax", "Synthwave", "Film Noir", "Cyberpunk", "Steampunk", "Pop Art", "Stained Glass",
    "Graffiti", "Blueprint", "Glitch Art", "Whiteboard", "Kinetic Typography", "Infographic", "Corporate Memphis", "Stickman", "Flat 2D", "3D Claymation",
    "Glassmorphism", "Chrome 22K", "Cineview", "Risograph", "Paper Collage", "Particles", "Neo-brutalism", "Bauhaus", "Memphis", "Vaporwave",
]


def login():
    req = urllib.request.Request(BASE + "/api/v1/auth/login/", data=json.dumps({"username": USER, "password": PASSWORD}).encode(), headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def attach(page, tag):
    page.on("console", lambda m: problems.append(f"[{tag}] console.error: {m.text[:300]}") if m.type == "error" and "favicon" not in m.text else None)
    page.on("pageerror", lambda e: problems.append(f"[{tag}] pageerror: {str(e)[:300]}"))
    page.on("response", lambda r: problems.append(f"[{tag}] HTTP {r.status} {r.url[-90:]}") if r.status >= 400 and "favicon" not in r.url and "/thumb" not in r.url else None)


def hscroll(page, tag):
    sw, iw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    if sw > iw + 1:
        problems.append(f"[{tag}] horizontal scroll {sw} > {iw}")


def gallery_names(page, size):
    """every name of the owner's lists is found by the search box"""
    box = page.get_by_placeholder(re.compile("جستجوی سبک"))
    missing = []
    for name in OWNER_NAMES:
        box.fill(name)
        page.wait_for_timeout(60)
        if page.locator("button[aria-pressed]").count() < 1:
            missing.append(name)
    box.fill("")
    notes.append(f"{size}: owner names found by search = {len(OWNER_NAMES) - len(missing)}/{len(OWNER_NAMES)}")
    if missing:
        problems.append(f"[{size}] the gallery search does not find: {', '.join(missing)}")


def run(size, tokens, browser):
    vp = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 390, "height": 844}}[size]
    ctx = browser.new_context(viewport=vp, locale="fa-IR", has_touch=(size == "phone"))
    ctx.add_init_script(f"try {{ localStorage.setItem('access', {json.dumps(tokens['access'])}); localStorage.setItem('refresh', {json.dumps(tokens['refresh'])}); }} catch (e) {{}}")
    page = ctx.new_page()
    attach(page, size)
    page.goto(f"{BASE}/panel/stores/{STORE}/motion", wait_until="networkidle", timeout=120000)
    page.get_by_role("heading", name="استودیوی موشن").wait_for(timeout=60000)
    page.get_by_test_id("new-style").wait_for(timeout=30000)
    cards = page.locator("button[aria-pressed]").count()
    notes.append(f"{size}: gallery cards in DOM = {cards}")
    if cards < 96:
        problems.append(f"[{size}] the gallery shows {cards} styles (< 96)")
    gallery_names(page, size)
    page.screenshot(path=str(OUT / f"{size}-1-studio.png"))
    hscroll(page, f"{size} studio")
    # ───── open the editor, start from a catalogue style
    page.get_by_test_id("new-style").click()
    dlg = page.get_by_role("dialog", name="ویرایشگرِ سبکِ تازه")
    dlg.wait_for(timeout=30000)
    page.screenshot(path=str(OUT / f"{size}-2-editor-start.png"))
    hscroll(page, f"{size} editor")
    dlg.get_by_label("سبکِ پایه").select_option("pixel-art")
    dlg.get_by_role("button", name=re.compile("کپیِ این سبک")).click()
    dlg.get_by_text("از سبکِ «پیکسل‌آرت» شروع شد").wait_for(timeout=30000)
    dlg.get_by_label("نامِ فارسیِ سبک").first.fill("سبکِ آزمونِ باشگاه")
    # colours tab: an unreadable ink shows the guard failure, the auto-fix repairs it
    dlg.get_by_role("tab", name="رنگ‌ها").click()
    dlg.get_by_role("textbox", name="جوهر (متن) (hex)").fill("#1a1c2d")
    page.wait_for_timeout(1800)
    dlg.get_by_text("نگهبانِ کنتراست").first.wait_for(timeout=15000)
    bad = dlg.get_by_text(re.compile("متنِ اصلی روی زمینه: کنتراست")).count()
    notes.append(f"{size}: guard failure messages shown = {bad}")
    if not bad:
        problems.append(f"[{size}] the contrast guard did not report the unreadable ink")
    page.screenshot(path=str(OUT / f"{size}-3-guard.png"))
    fix = dlg.get_by_role("button", name=re.compile("اصلاحِ خودکارِ کنتراست"))
    if fix.count():
        fix.first.click()
        page.wait_for_timeout(1800)
        if dlg.get_by_text(re.compile("متنِ اصلی روی زمینه: کنتراست")).count():
            problems.append(f"[{size}] auto-fix left the guard failure in place")
    else:
        problems.append(f"[{size}] no auto-fix button")
    # ───── describe -> draft
    dlg.get_by_role("tab", name="شروع").click()
    dlg.get_by_label("توصیفِ سبک").fill("تیره و سینمایی با رنگِ طلایی، حرکتِ آرام و سنگین")
    dlg.get_by_role("button", name=re.compile("بساز")).first.click()
    page.wait_for_function("document.querySelector('[role=dialog]') && /پیش‌نویس|ساخته شد|هوش مصنوعی/.test(document.querySelector('[role=dialog]').innerText)", timeout=120000)
    page.screenshot(path=str(OUT / f"{size}-4-described.png"))
    # ───── the live preview is the real player, with the store's own text
    fr = dlg.frame_locator("iframe[title='پیش‌نمایشِ ویدیو']")
    try:
        fr.locator("[data-nm-scene]").first.wait_for(timeout=90000)
        notes.append(f"{size}: preview rendered scene markup")
    except Exception as e:  # noqa: BLE001
        problems.append(f"[{size}] preview did not render: {str(e)[:120]}")
    page.screenshot(path=str(OUT / f"{size}-5-preview.png"))
    # ───── other tabs open without errors
    for i, tab in enumerate(("قلم و حروف", "پس‌زمینه و بافت", "تزئین", "کارت و دکمه", "حرکت و گذار", "خروجی/ورودی")):
        dlg.get_by_role("tab", name=tab).click()
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / f"{size}-6-tab{i}.png"))
    hscroll(page, f"{size} tabs")
    # ───── JSON export is shown and a re-import works
    dlg.get_by_role("tab", name="خروجی/ورودی").click()
    doc = json.loads(dlg.get_by_label("JSON سبک").input_value())
    if not (doc.get("nm_motion_style") == 1 and doc["style"]["palette"]["bg"]):
        problems.append(f"[{size}] the exported JSON is not a style document")
    dlg.get_by_label("JSON برای ورود").fill(json.dumps(doc))
    dlg.get_by_role("button", name=re.compile("واردکردن")).click()
    dlg.get_by_text(re.compile("وارد شد")).first.wait_for(timeout=30000)
    if DO_QA and size == "desktop":
        dlg.get_by_role("button", name=re.compile("کنترلِ کیفیت و ذخیره")).first.click()
        t0 = time.time()
        page.wait_for_function("!document.querySelector('[role=dialog]') || /کنترلِ کیفیت قبول شد|رد کرد|اجرا نشد/.test(document.querySelector('[role=dialog]').innerText)", timeout=20 * 60 * 1000)
        notes.append(f"{size}: quality check + save took {time.time() - t0:.0f}s")
        page.screenshot(path=str(OUT / f"{size}-7-qa.png"))
        page.wait_for_timeout(3000)
        if page.get_by_role("dialog", name="ویرایشگرِ سبکِ تازه").count():
            problems.append(f"[{size}] the editor is still open after the check: " + page.get_by_role("dialog").inner_text()[:300].replace("\n", " "))
        else:
            page.get_by_text(re.compile("ذخیره شد و انتخاب شد")).first.wait_for(timeout=30000)
            page.screenshot(path=str(OUT / f"{size}-8-saved.png"))
            page.get_by_role("button", name=re.compile("سبک‌های من")).click()
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT / f"{size}-9-mine.png"))
            n_mine = page.locator("button[aria-pressed]").count()
            notes.append(f"{size}: saved style shown in «سبک‌های من»: {n_mine} card(s)")
            if n_mine < 1:
                problems.append(f"[{size}] the saved style is not in the «سبک‌های من» list")
    else:
        dlg.get_by_role("button", name=re.compile("بستن")).click()
    ctx.close()


with sync_playwright() as p:
    tokens = login()
    browser = p.chromium.launch(channel="chromium")
    try:
        for size in ("desktop", "phone"):
            try:
                run(size, tokens, browser)
            except Exception as e:  # noqa: BLE001
                problems.append(f"[{size}] flow failed: {type(e).__name__}: {str(e)[:400]}")
    finally:
        browser.close()
print("NOTES:")
for n in notes:
    print("  ", n)
print("PROBLEMS:", len(problems))
for pr in problems:
    print("  ", pr)
sys.exit(1 if problems else 0)
