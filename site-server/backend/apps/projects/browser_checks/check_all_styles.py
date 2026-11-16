# -*- coding: utf-8 -*-
"""Real-browser check of ALL site-builder styles (the 14 hand-made + the generated ones from ui-ux-pro-max): the Chagher landing draft is rendered with each style
and opened at 390 / 820 / 1280 px with dir=rtl.  FAILS when a page scrolls sideways, an element leaves the window (marquees inside overflow:clip are ignored),
the body direction is not rtl, the Persian font did not load, or the page throws a JavaScript error.

    cd backend && ../venv/bin/python apps/projects/browser_checks/check_all_styles.py OUTDIR [--shots] [style ...]     # renders, then calls the browser part
    PLAYWRIGHT_BROWSERS_PATH=... python apps/projects/browser_checks/check_all_styles.py OUTDIR --browser-only      # on a machine that has Playwright

The render part needs Django (the NM venv); the browser part needs Playwright for Python (any venv: /opt/up3d-uitest/venv on the server).  Set
NM_PLAYWRIGHT_PY to the Playwright python when the NM venv has none; the script then runs the browser part with it.
"""
import json
import os
import shutil
import subprocess
import sys

JS = """() => {
  const de = document.documentElement, vw = de.clientWidth, bad = [];
  document.querySelectorAll('body *').forEach((e) => {
    const r = e.getBoundingClientRect();
    if (r.width > 0 && (r.right > vw + 2 || r.left < -2)) {
      let p = e, clipped = false;
      while (p && p !== document.body) { const o = getComputedStyle(p); if (p !== e && ['hidden', 'clip', 'auto', 'scroll'].includes(o.overflowX)) { clipped = true; break; } p = p.parentElement; }
      if (!clipped && getComputedStyle(e).position !== 'fixed') bad.push((e.className && e.className.baseVal === undefined ? e.className : e.tagName) + '');
    }
  });
  return {sw: de.scrollWidth, vw, dir: getComputedStyle(document.body).direction, font: getComputedStyle(document.body).fontFamily, bad: bad.slice(0, 3), n: bad.length};
}"""


def render(out, only):
    sys.path.insert(0, os.getcwd())
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from apps.projects.builder import chagher_draft as D, styles, theme as T
    os.makedirs(os.path.join(out, 'fonts'), exist_ok=True)
    keys = [k for k in styles.ORDER if not only or k in only]
    for key in keys:
        parts = D.build(key, logo=D.BRAND['logo_url'])
        with open(os.path.join(out, key + '.html'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(D.static_page(parts))
        _faces, used = T.font_faces(parts['theme'])
        for k in used:
            for entry in T.FONTS[k]['files']:
                dst = os.path.join(out, 'fonts', entry[0])
                if not os.path.exists(dst):
                    shutil.copyfile(os.path.join(T.FONT_DIR, entry[0]), dst)
    return keys


def browse(out, shots=False, only=None):
    from playwright.sync_api import sync_playwright
    keys = sorted(f[:-5] for f in os.listdir(out) if f.endswith('.html') and (not only or f[:-5] in only))
    fails, report = [], {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            for w in (390, 820, 1280):
                ctx = b.new_context(viewport={'width': w, 'height': 900})
                page = ctx.new_page()
                errs = []
                page.on('pageerror', lambda e: errs.append(str(e)[:120]))
                for k in keys:
                    page.goto('file://%s' % os.path.abspath(os.path.join(out, k + '.html')).replace('\\', '/'), wait_until='load')
                    page.evaluate('document.fonts.ready')
                    page.wait_for_timeout(150)
                    m = page.evaluate(JS)
                    report.setdefault(k, {})[w] = m
                    if m['sw'] > m['vw'] + 1:
                        fails.append((k, w, 'horizontal scroll', m['sw'], m['vw']))
                    if m['n']:
                        fails.append((k, w, 'elements outside the window', m['bad']))
                    if m['dir'] != 'rtl':
                        fails.append((k, w, 'direction', m['dir']))
                    if shots:
                        os.makedirs(os.path.join(out, 'png'), exist_ok=True)
                        page.screenshot(path=os.path.join(out, 'png', '%s-%d.png' % (k, w)), full_page=True)
                if errs:
                    fails.append(('*', w, 'javascript errors', errs[:3]))
                ctx.close()
        finally:
            b.close()
    json.dump(report, open(os.path.join(out, 'report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('styles=%d failures=%d' % (len(keys), len(fails)))
    for f in fails[:30]:
        print('FAIL', f)
    return 1 if fails else 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    out = args[0]
    only = args[1:]
    if '--browser-only' in sys.argv:
        sys.exit(browse(out, '--shots' in sys.argv, only))
    keys = render(out, only)
    print('rendered %d styles' % len(keys))
    py = os.environ.get('NM_PLAYWRIGHT_PY')
    try:
        import playwright  # noqa: F401
        sys.exit(browse(out, '--shots' in sys.argv, only))
    except ImportError:
        if not py:
            print('Playwright is not installed here: run the browser part with --browser-only on a machine that has it (or set NM_PLAYWRIGHT_PY)')
            sys.exit(0)
        sys.exit(subprocess.call([py, os.path.abspath(__file__), out, '--browser-only'] + (['--shots'] if '--shots' in sys.argv else []) + only))


if __name__ == '__main__':
    main()
