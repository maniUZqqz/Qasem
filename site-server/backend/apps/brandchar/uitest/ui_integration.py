import json, os, sys, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BC_BASE", "http://127.0.0.1:5184")
OUT = "/tmp/bc_ui"
os.makedirs(OUT, exist_ok=True)
report = []


def check(name, ok, detail=""):
    report.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" :: " + str(detail) if detail else ""), flush=True)


with sync_playwright() as p:
    b = p.chromium.launch()
    for vw, vh, theme, tag in ((1366, 900, "light", "desk"), (390, 844, "dark", "phone")):
        ctx = b.new_context(viewport={"width": vw, "height": vh}, color_scheme=theme, locale="fa-IR")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        tok = page.request.post(BASE + "/api/v1/auth/login/", data={"username": os.environ["BC_USER"], "password": os.environ["BC_PWD"]}).json()
        hdr = {"Authorization": "Bearer " + tok["access"]}
        page.goto(BASE + "/panel/login")
        page.evaluate("t => { localStorage.setItem('access', t.access); localStorage.setItem('refresh', t.refresh); localStorage.setItem('upmarket-theme', '%s'); }" % theme, tok)
        try:
            # chat: agent voice + greeting
            page.goto(BASE + "/panel/stores/34/chat")
            page.wait_for_selector("[data-testid=agent-voice]", timeout=40000)
            check(f"{tag} chat: agent voice banner", True)
            page.wait_for_selector("[data-testid=agent-greeting]", timeout=10000)
            check(f"{tag} chat: persona greeting shown with avatar", page.locator("[data-testid=agent-greeting] img").count() == 1)
            page.screenshot(path=f"{OUT}/{tag}-chat.png")

            # thumbnails: subject from the brand character
            page.goto(BASE + "/panel/stores/34/thumbnails")
            page.get_by_role("button", name="انتخابِ عکس").first.click(timeout=40000)
            page.wait_for_selector("[data-testid=pick-brand-character]", timeout=20000)
            page.click("[data-testid=pick-brand-character]")
            page.wait_for_selector(".th-slot img", timeout=60000)
            check(f"{tag} thumbnails: brand character becomes the subject", page.locator(".th-slot img").count() >= 1)
            page.screenshot(path=f"{OUT}/{tag}-thumbs.png")

            # image studio of a product: templates card
            rows = [{"id": int(os.environ.get("BC_PRODUCT", "20"))}]
            if rows:
                pid = rows[0]["id"]
                page.goto(BASE + f"/panel/products/{pid}/images")
                page.wait_for_selector("[data-testid=brand-templates]", timeout=40000)
                check(f"{tag} image studio: brand templates card", page.locator("[data-testid=brand-templates] button").count() >= 10, page.locator("[data-testid=brand-templates] button").count())
                page.locator("[data-testid=brand-templates] button").first.click()
                page.wait_for_selector("[data-testid=brand-templates] img", timeout=60000)
                check(f"{tag} image studio: a template renders in one click", True)
                page.screenshot(path=f"{OUT}/{tag}-imagestudio.png")
            else:
                check(f"{tag} image studio: product exists", False, "store has no product")

            # gallery -> motion hand-over
            page.goto(BASE + "/panel/stores/34/brand-character/gallery")
            page.wait_for_selector("[data-testid=use-motion]", timeout=40000)
            page.get_by_role("button", name="افزودن به استودیوی موشن").click()
            page.wait_for_url("**/motion", timeout=60000)
            page.wait_for_selector("text=قطعهٔ «شخصیتِ برند» به صحنه‌ها اضافه شد", timeout=60000)
            check(f"{tag} motion: scene handed over from the gallery", True)
            page.screenshot(path=f"{OUT}/{tag}-motion.png")

            # motion: the component picker offers the brand character
            page.get_by_role("button", name="افزودنِ صحنه از کتابخانهٔ قطعه‌ها").click(timeout=30000)
            page.wait_for_selector(".u-card:has-text('کدام قطعه؟') button:has-text('شخصیتِ برند')", timeout=20000)
            check(f"{tag} motion: component library lists «شخصیتِ برند»", True)

            # gallery: director + inbox cards and the tools
            page.goto(BASE + "/panel/stores/34/brand-character/gallery")
            page.wait_for_selector("[data-testid=use-director]", timeout=40000)
            page.get_by_role("button", name="ساختِ استیکرهای ویدیو").click()
            page.wait_for_selector("[data-testid=use-director] img", timeout=60000)
            check(f"{tag} gallery: five director stickers", page.locator("[data-testid=use-director] img").count() == 5, page.locator("[data-testid=use-director] img").count())
        except Exception as exc:  # noqa: BLE001
            check(f"{tag} flow", False, repr(exc)[:300])
            try:
                page.screenshot(path=f"{OUT}/{tag}-ui2-FAIL.png")
            except Exception:  # noqa: BLE001
                pass
        check(f"{tag} no page errors", not errors, errors[:3])
        ctx.close()
    b.close()
bad = [r for r in report if not r[1]]
print("RESULT", len(report) - len(bad), "passed,", len(bad), "failed")
sys.exit(1 if bad else 0)
