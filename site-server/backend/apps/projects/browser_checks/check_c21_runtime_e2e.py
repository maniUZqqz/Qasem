# -*- coding: utf-8 -*-
"""Real-browser end-to-end check of the PUBLISHED page of interactive 21st.dev parts (round 5, 2026-11-18).

The converted parts are static HTML; the site's tiny runtime (builder/c21_runtime.py) makes accordions, tabs, switches and banners work on the published site. This script builds
the page exactly as publishing does (``chagher_draft.static_page`` with ``canvas=False``: renderer + Django template rendering of the block HTML), opens it in Chromium and
clicks every control: the runtime script must be there exactly once, closed panels must be in the HTML (``hidden``), and every accordion row / tab must really toggle.

    cd backend && ../venv/bin/python apps/projects/browser_checks/check_c21_runtime_e2e.py [--ids a/b,c/d] [--style dark-luxury]

Read-only: nothing is written to any database (documents are built in memory); the pages go to a temp folder that is deleted at the end.
Needs: the NM venv and a Playwright python (NM_C21_PLAYWRIGHT_PY, default /opt/up3d-uitest/venv/bin/python; PLAYWRIGHT_BROWSERS_PATH respected). Exit 1 on any failure.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from apps.projects.builder import c21_convert as CV, c21_embed as EM, c21_rtl, chagher_draft as D, styles, theme as T  # noqa: E402
from apps.projects.builder.clean import clean_doc, new_block  # noqa: E402

DEFAULT_IDS = ["mohammadshehadeh/faq-05", "mohammadshehadeh/faq-06", "originui/accordion", "ekmas/accordion", "shadcn/collapsible", "originui/tabs", "shadcn/tabs"]
EMPTY = {"v": 1, "blocks": []}

PROBE = r"""
(args) => {
  const rt = window.__nbc21;
  const host = document.querySelector('.nbc21-host') || document.body;
  const out = {scripts: document.querySelectorAll('script[data-nbc21-rt]').length, runtime: !!rt, closed_at_load: host.querySelectorAll('[hidden]').length, triggers: 0, toggled: 0, tabs: 0, tab_ok: 0, texts: 0};
  out.texts = (host.innerText || '').trim().length;
  if (!rt) return out;
  const trig = Array.from(host.querySelectorAll('[aria-expanded]'));
  out.triggers = trig.length;
  for (const t of trig) {
    const p = rt.panelOf(t);
    if (!p) continue;
    const before = p.hidden;
    t.click();
    if (p.hidden !== before) out.toggled++;
  }
  const tabs = Array.from(host.querySelectorAll('[role=tab]'));
  out.tabs = tabs.length;
  const list = tabs[0] && tabs[0].closest('[role=tablist]');
  let root = list ? list.parentNode : null, panels = [];
  for (let k = 0; k < 4 && root && !panels.length; k++) { panels = Array.from(root.querySelectorAll('[role=tabpanel]')).filter((p) => !list.contains(p)); if (!panels.length) root = root.parentNode; }
  for (let j = 1; j < tabs.length && j < panels.length; j++) {
    tabs[j].click();
    if (!panels[j].hidden && panels[0].hidden && tabs[j].getAttribute('aria-selected') === 'true') out.tab_ok++;
  }
  out.tab_panels = panels.length;
  return out;
}
"""

RUNNER = r"""
import json, os, sys
from playwright.sync_api import sync_playwright
d = sys.argv[1]
probe = open(os.path.join(d, '__probe.js'), encoding='utf-8').read()
res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    try:
        c = b.new_context(viewport={'width': 1280, 'height': 900})
        pg = c.new_page()
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)[:160]))
        for f in sorted(os.listdir(d)):
            if not f.endswith('.html'):
                continue
            errors.clear()
            pg.goto('file://' + os.path.abspath(os.path.join(d, f)), wait_until='load', timeout=30000)
            pg.wait_for_timeout(150)
            r = pg.evaluate(probe)
            r['js_errors'] = list(errors)
            res[f[:-5]] = r
        c.close()
    finally:
        b.close()
json.dump(res, open(os.path.join(d, '__result.json'), 'w'))
"""


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    ids = [x for x in (arg("--ids") or ",".join(DEFAULT_IDS)).split(",") if x]
    style = arg("--style", "dark-luxury")
    idx = CV.load_index()
    out = tempfile.mkdtemp(prefix="c21-runtime-e2e-")
    fails = 0
    try:
        shutil.copytree(T.FONT_DIR, os.path.join(out, "fonts"))
        th = T.clean_theme(styles.apply_to_theme(T.default_theme(), style))
        want = {}
        for cid in ids:
            e = idx.get(cid)
            if not e or e.get("rtl") == "fail":
                print("skip  %s (not insertable on this data)" % cid)
                continue
            rec = CV.get_record(e["key"])
            parts = {"theme": th, "page": clean_doc({"v": 1, "blocks": [new_block(EM.TYPE, **EM.default_props(rec))]}, "page"), "header": clean_doc(EMPTY, "header"), "footer": clean_doc(EMPTY, "footer"), "menu": []}
            name = cid.replace("/", "__")
            with open(os.path.join(out, name + ".html"), "w", encoding="utf-8") as fh:
                fh.write(D.static_page(parts, fonts_prefix="fonts/"))
            want[name] = (cid, (e.get("interact") or ""))
        with open(os.path.join(out, "__probe.js"), "w", encoding="utf-8") as fh:
            fh.write(PROBE)
        with open(os.path.join(out, "__run.py"), "w", encoding="utf-8") as fh:
            fh.write(RUNNER)
        if not want:
            print("nothing to check")
            return 1
        py = os.environ.get("NM_C21_PLAYWRIGHT_PY") or c21_rtl.DEFAULT_PY
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or c21_rtl.DEFAULT_BROWSERS)
        r = subprocess.run([py, os.path.join(out, "__run.py"), out], capture_output=True, text=True, env=env, timeout=900)
        if r.returncode != 0:
            print("browser failed:", (r.stderr or "")[-300:])
            return 2
        res = json.load(open(os.path.join(out, "__result.json")))
        for name, (cid, inter) in want.items():
            row = res.get(name) or {}
            problems = []
            if row.get("scripts") != 1:
                problems.append("runtime script count %s (want 1)" % row.get("scripts"))
            if not row.get("runtime"):
                problems.append("window.__nbc21 missing")
            if row.get("js_errors"):
                problems.append("javascript errors %s" % row["js_errors"][:1])
            if row.get("triggers"):
                if row["toggled"] != row["triggers"]:
                    problems.append("only %s of %s accordion rows toggled" % (row["toggled"], row["triggers"]))
                if not row.get("closed_at_load") and row["triggers"] > 1:
                    problems.append("no closed panel in the published HTML")
            if row.get("tabs", 0) >= 2 and row.get("tab_ok", 0) != min(row["tabs"], row.get("tab_panels", 0)) - 1:
                problems.append("tabs: %s of %s switched (panels %s)" % (row.get("tab_ok"), row["tabs"] - 1, row.get("tab_panels")))
            if not row.get("triggers") and not row.get("tabs"):
                problems.append("no accordion row or tab found")
            print(("ok    " if not problems else "FAIL  ") + "%s [%s]: scripts=%s triggers=%s toggled=%s tabs=%s tab_ok=%s closed_at_load=%s %s" % (
                cid, inter or "-", row.get("scripts"), row.get("triggers"), row.get("toggled"), row.get("tabs"), row.get("tab_ok"), row.get("closed_at_load"), "; ".join(problems)))
            fails += 1 if problems else 0
    finally:
        shutil.rmtree(out, ignore_errors=True)
    print("FAILURES: %d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
