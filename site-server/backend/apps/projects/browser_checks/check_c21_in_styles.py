# -*- coding: utf-8 -*-
"""Real-browser check: do the INSERTED 21st.dev components stay readable inside themed pages? (review round 3, 2026-11-17)

The reviewer measured 40 random insertable components in four styles through the same render path the builder canvas uses and found text under 3:1 contrast
(a white FAQ card with white text on a dark style, ...). This script repeats exactly that: every sampled component is put alone into a page (c21 block ->
``chagher_draft.static_page`` = the renderer of the real site) with each requested style, opened in Chromium at 1280 px, and every visible text node is measured
against the pixels behind it (text made transparent, then screenshot) with ``c21_contrast.measure``.

    cd backend && ../venv/bin/python apps/projects/browser_checks/check_c21_in_styles.py [--n 40] [--seed 5] [--all] [--styles dark-luxury,bento-grid] [--ids id1,id2] [--hard 4.5] [--top 60] [--json out.json]
    ... --chagher [--layout] [--styles a,b]   the Chagher landing draft of every style instead (AA 4.5:1 on every text; the owner's own product); --layout = with each style's section layouts applied (hero/cta/faq variants)

Needs: the NM venv (Django + Pillow) and a Playwright python (NM_C21_PLAYWRIGHT_PY, default /opt/up3d-uitest/venv/bin/python; PLAYWRIGHT_BROWSERS_PATH respected).
Exit code 1 when any component has text under 3:1 (hard) in any style; the summary lists the worst ones. Soft (3:1..4.5:1) counts are reported, not failing.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from apps.projects.builder import c21_contrast as CC, c21_convert as CV, c21_embed as EM, c21_rtl, chagher_draft as D, c21st, styles, theme as T  # noqa: E402
from apps.projects.builder.clean import clean_doc, new_block  # noqa: E402

DEFAULT_STYLES = ["dark-luxury", "ux-cyberpunk-ui", "ux-modern-dark-cinema-mobile", "bento-grid"]       # the reviewer's four
EMPTY = {"v": 1, "blocks": []}


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def run_chagher(styles_list):
    """The Chagher landing draft of every style (the owner's own product): hard/soft text counts per style (AA = no soft). Pages are named chagher~<style>.html."""
    out = tempfile.mkdtemp(prefix="c21-chagher-")
    try:
        shutil.copytree(T.FONT_DIR, os.path.join(out, "fonts"))
        for style in styles_list:
            parts = D.build(style, logo=D.BRAND["logo_url"], layout="--layout" in sys.argv)
            with open(os.path.join(out, "chagher~%s.html" % style), "w", encoding="utf-8") as fh:
                fh.write(D.static_page(parts, fonts_prefix="fonts/"))
        py = os.environ.get("NM_C21_PLAYWRIGHT_PY") or c21_rtl.DEFAULT_PY
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or c21_rtl.DEFAULT_BROWSERS)
        r = subprocess.run([py, str(c21_rtl.SCRIPT), out, os.path.join(out, "rtl.json")], capture_output=True, text=True, env=env, timeout=3000)
        if r.returncode != 0:
            print("browser failed:", (r.stderr or "")[-300:])
            return 2
        bad, texts = [], 0
        for style in styles_list:
            name = "chagher~%s" % style
            try:
                data = json.load(open(os.path.join(out, name + ".json"), encoding="utf-8"))
            except (OSError, ValueError):
                print("NO RESULT", style)
                bad.append((style, "no result"))
                continue
            m = CC.measure(data.get("items") or [], os.path.join(out, name + ".png"))
            texts += m["n"] if m else 0
            if m and (m["hard"] or m["soft"]):
                bad.append((style, m["hard"], m["soft"], m["worst"], m["samples"][:1]))
        print("styles=%d texts=%d styles-with-text-under-4.5:1=%d" % (len(styles_list), texts, len(bad)))
        for b in bad[:40]:
            print("LOW", b)
        return 1 if bad else 0
    finally:
        shutil.rmtree(out, ignore_errors=True)


def main():
    if arg("--hard"):                                    # e.g. --hard 4.5 lists every text under AA, not only the invisible ones
        CC.HARD = float(arg("--hard"))
    if "--chagher" in sys.argv:
        return run_chagher([s for s in (arg("--styles") or ",".join(styles.ORDER)).split(",") if s in styles.STYLES])
    sel_styles = [s for s in (arg("--styles", ",".join(DEFAULT_STYLES))).split(",") if s in styles.STYLES]
    rows = [r for r in c21st.load() if c21st.insertable(r)]
    keys = [(r["id"], (r.get("conv") or {})["key"]) for r in rows]
    if arg("--ids"):                                     # exact components, e.g. --ids arihantcodes_1f7b8c4d/prompt-composer,cult-ui/texture-button
        want = set(arg("--ids").split(","))
        keys = [k for k in keys if k[0] in want]
    elif "--all" not in sys.argv:
        random.Random(int(arg("--seed", "5"))).shuffle(keys)
        keys = keys[: int(arg("--n", "40"))]
    out = tempfile.mkdtemp(prefix="c21-in-styles-")
    try:
        shutil.copytree(T.FONT_DIR, os.path.join(out, "fonts"))
        for style in sel_styles:
            th = T.clean_theme(styles.apply_to_theme(T.default_theme(), style))
            for cid, key in keys:
                rec = CV.get_record(key)
                parts = {"theme": th, "page": clean_doc({"v": 1, "blocks": [new_block(EM.TYPE, **EM.default_props(rec))]}, "page"),
                         "header": clean_doc(EMPTY, "header"), "footer": clean_doc(EMPTY, "footer"), "menu": []}
                with open(os.path.join(out, "%s~%s.html" % (key, style)), "w", encoding="utf-8") as fh:
                    fh.write(D.static_page(parts, fonts_prefix="fonts/"))
        py = os.environ.get("NM_C21_PLAYWRIGHT_PY") or c21_rtl.DEFAULT_PY
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or c21_rtl.DEFAULT_BROWSERS)
        r = subprocess.run([py, str(c21_rtl.SCRIPT), out, os.path.join(out, "rtl.json")], capture_output=True, text=True, env=env, timeout=3000)
        if r.returncode != 0:
            print("browser failed:", (r.stderr or "")[-300:])
            return 2
        report, hard_total, soft_total, worst = {}, 0, 0, []
        for cid, key in keys:
            for style in sel_styles:
                name = "%s~%s" % (key, style)
                try:
                    data = json.load(open(os.path.join(out, name + ".json"), encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                m = CC.measure(data.get("items") or [], os.path.join(out, name + ".png"))
                if m is None:
                    continue
                report.setdefault(cid, {})[style] = {k: m[k] for k in ("n", "hard", "soft", "worst")}
                hard_total += 1 if m["hard"] else 0
                soft_total += 1 if m["soft"] else 0
                if m["hard"]:
                    worst.append((m["worst"], cid, style, m["samples"][:1]))
        pages = sum(len(v) for v in report.values())
        print("components=%d styles=%d pages=%d  pages-with-text-under-3:1=%d  pages-with-text-under-4.5:1=%d" % (len(keys), len(sel_styles), pages, hard_total, soft_total))
        for w in sorted(worst)[:int(arg("--top", "25"))]:
            print("HARD", w)
        if arg("--json"):
            json.dump(report, open(arg("--json"), "w", encoding="utf-8"), ensure_ascii=False)
        return 1 if hard_total else 0
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
