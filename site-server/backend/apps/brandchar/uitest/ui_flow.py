import json, os, sys, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BC_BASE", "http://127.0.0.1:5184")
USER, PWD = os.environ["BC_USER"], os.environ["BC_PWD"]
STORE = os.environ.get("BC_STORE", "34")
OUT = os.environ.get("BC_OUT", "/tmp/bc_ui")
os.makedirs(OUT, exist_ok=True)
report = []


def check(name, ok, detail=""):
    report.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" :: " + str(detail) if detail else ""), flush=True)


def run(p, vw, vh, theme, tag):
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": vw, "height": vh}, color_scheme=theme, locale="fa-IR")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
    page.on("console", lambda m: errors.append("console: " + m.text[:200]) if m.type == "error" and "favicon" not in m.text else None)
    try:
        r = page.request.post(BASE + "/api/v1/auth/login/", data={"username": USER, "password": PWD})
        tok = r.json()
        page.goto(BASE + "/panel/login")
        page.evaluate("t => { localStorage.setItem('access', t.access); localStorage.setItem('refresh', t.refresh); localStorage.setItem('upmarket-theme', '%s'); }" % theme, tok)

        def go(path, wait_sel, name):
            page.goto(f"{BASE}/panel/stores/{STORE}/brand-character{path}")
            page.wait_for_selector(wait_sel, timeout=30000)
            time.sleep(0.8)
            page.screenshot(path=f"{OUT}/{tag}-{name}.png", full_page=False)
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            check(f"{tag} {name}: no horizontal scroll", overflow <= 2, overflow)

        go("", "[data-testid=overview-page]", "overview")
        check(f"{tag} overview: tabs", page.locator(".bc-tab").count() == 6)
        check(f"{tag} overview: section in sidebar", page.get_by_text("شخصیتِ برند").count() >= 1)

        go("/persona", "[data-testid=persona-page]", "persona")
        page.get_by_role("button", name="پیش‌نویس بساز").click()
        page.wait_for_selector("[data-testid=wizard-result]", timeout=60000)
        check(f"{tag} persona: wizard result with sources", "brand-facts-fa.md" in (page.locator("[data-testid=wizard-result]").text_content() or ""))
        check(f"{tag} persona: tagline filled from facts", "با چغر چغر تر شو" in page.locator("input").evaluate_all("els => els.map(e => e.value).join('|')"))
        page.get_by_role("button", name="ذخیره", exact=True).click()
        page.wait_for_selector("text=شخصیتِ گفتار ذخیره شد", timeout=30000)
        page.wait_for_selector("[data-testid=persona-prompt]", timeout=30000)
        page.wait_for_function("document.querySelector('[data-testid=persona-prompt]').textContent.includes('BRAND PERSONA')", timeout=30000)
        check(f"{tag} persona: injected block preview", "BRAND PERSONA" in page.inner_text("[data-testid=persona-prompt]"))
        page.screenshot(path=f"{OUT}/{tag}-persona-saved.png", full_page=True)

        go("/studio", "[data-testid=studio-page]", "studio")
        if page.locator("[data-testid=create-form]").count():
            page.get_by_role("button", name="بساز", exact=True).click()
        page.wait_for_selector("[data-testid=character-editor]", timeout=60000)
        page.wait_for_function("document.querySelector('[data-testid=editor-canvas] svg g[pointer-events=none]') && document.querySelector('[data-testid=editor-canvas] svg g[pointer-events=none]').innerHTML.length > 500", timeout=60000)
        check(f"{tag} editor: server figure drawn in canvas", True)
        # a rectangle layer by dragging; undo / redo; symmetry
        page.get_by_role("tab", name="لایه‌ها").click()
        rows = lambda: page.locator(".bce-layers [role=option]").count()

        def draw(tool, fx, fy, w, h):
            page.get_by_role("button", name=tool, exact=True).click()
            page.locator(".bce-canvas svg").scroll_into_view_if_needed()
            time.sleep(0.4)
            b = page.locator(".bce-canvas svg").bounding_box()
            x, y = b["x"] + b["width"] * fx, max(b["y"], 0) + fy
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + w, y + h, steps=5)
            page.mouse.up()
            time.sleep(0.4)

        n0 = rows()
        draw("مستطیل", 0.12, 40, 60, 50)
        n1 = rows()
        check(f"{tag} editor: layer created by drawing", n1 == n0 + 1, (n0, n1))
        page.get_by_role("button", name="برگشت").first.click()
        time.sleep(0.3)
        check(f"{tag} editor: undo removes it", rows() == n0, rows())
        page.get_by_role("button", name="جلو").first.click()
        time.sleep(0.3)
        check(f"{tag} editor: redo brings it back", rows() == n0 + 1, rows())
        draw("بیضی", 0.55, 40, 60, 60)
        check(f"{tag} editor: second shape (ellipse)", rows() == n0 + 2, rows())
        page.get_by_role("button", name="قرینه").click()      # symmetry on
        n_before = rows()
        draw("مستطیل", 0.3, 120, 40, 40)
        n2 = rows()
        check(f"{tag} editor: symmetry adds a mirrored twin", n2 == n_before + 2, (n_before, n2))
        page.keyboard.press("Control+z")
        time.sleep(0.3)
        check(f"{tag} editor: Ctrl+Z undoes the pair at once", rows() == n_before, rows())
        page.get_by_role("tab", name="سبک و بدن").click()
        page.get_by_role("button", name="گردِ کوچک (چیبی)", exact=True).click()
        time.sleep(1.5)
        page.screenshot(path=f"{OUT}/{tag}-editor-chibi.png", full_page=True)
        page.get_by_role("button", name="ذخیره", exact=True).click()
        page.wait_for_selector("text=ذخیره شد", timeout=30000)
        check(f"{tag} editor: saved", True)

        go("/scenes", "[data-testid=scenes-page]", "scenes")
        page.wait_for_selector("[data-testid=scene-preview] img", timeout=60000)
        check(f"{tag} scenes: live preview", True)
        check(f"{tag} scenes: colour key shown", page.locator("[data-testid=scene-qa]").count() == 1)
        page.get_by_role("button", name="بساز و ذخیره کن").click()
        page.wait_for_selector("text=ساخته‌شده‌ها", timeout=60000)
        check(f"{tag} scenes: render registered", True)
        check(f"{tag} scenes: 10 templates", page.locator("[data-testid=templates] .bc-use").count() == 10, page.locator("[data-testid=templates] .bc-use").count())

        go("/gallery", "[data-testid=gallery-page]", "gallery")
        check(f"{tag} gallery: six use cards", page.locator(".bc-use[data-testid^=use-]").count() == 6, page.locator(".bc-use[data-testid^=use-]").count())
        page.wait_for_selector("[data-testid=gallery] .bc-shot", timeout=30000)
        check(f"{tag} gallery: renders listed", True)

        go("/export", "[data-testid=export-page]", "export")
        check(f"{tag} export: five export cards", page.locator(".bc-use").count() == 5)

        page.goto(f"{BASE}/panel/stores/{STORE}/inbox")
        page.wait_for_selector("[data-testid=agent-voice]", timeout=30000)
        check(f"{tag} inbox: agent voice banner", True)
        page.screenshot(path=f"{OUT}/{tag}-inbox.png")
    except Exception as exc:  # noqa: BLE001
        check(f"{tag} flow", False, repr(exc)[:300])
        try:
            page.screenshot(path=f"{OUT}/{tag}-FAIL.png")
        except Exception:  # noqa: BLE001
            pass
    finally:
        real = [e for e in errors if "ResizeObserver" not in e and "403" not in e]
        check(f"{tag} no console/page errors", not real, real[:3])
        browser.close()


with sync_playwright() as p:
    for vw, vh, theme, tag in ((1366, 900, "light", "desk-light"), (390, 844, "dark", "phone-dark"), (1366, 900, "dark", "desk-dark"), (390, 844, "light", "phone-light")):
        run(p, vw, vh, theme, tag)
bad = [r for r in report if not r[1]]
print("RESULT", len(report) - len(bad), "passed,", len(bad), "failed")
json.dump(report, open(OUT + "/report.json", "w"), ensure_ascii=False)
sys.exit(1 if bad else 0)
