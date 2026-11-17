# -*- coding: utf-8 -*-
"""Rendered-text contrast check of the site styles in a real browser (WCAG AA): every text node, worst contrast against the pixels actually behind it.

The palette tests only compare token pairs; this measures what the owner sees (gradients, translucent glass cards, opacity-dimmed text, brand colour kept on a
foreign style). Method: scroll once so reveal-on-scroll animations have played, freeze animations, read every text node (colour, opacity chain, size, weight),
repaint with all text transparent, screenshot, and sample a grid of pixels inside each text rectangle; text under 24 px (18.66 px bold) must reach 4.5:1,
large text 3:1. Text that is hidden until hover, or inside a closed <details>, is skipped.

    cd backend && ../venv/bin/python apps/projects/browser_checks/check_all_styles.py OUT          # renders the Chagher draft of every style (Django)
    python apps/projects/browser_checks/check_text_contrast.py OUT [1280 390] [--only key,key] [--json report.json]    # any machine with Playwright + Pillow
    ... or render_style_pages.py OUT (the default home starter of every style) and point this script at that folder.

Exit code 1 when any style has a failing text (the summary lists the element classes, the worst ratio and an example).
"""
import io, json, os, sys, glob, shutil, tempfile
from PIL import Image
from playwright.sync_api import sync_playwright

JS = r"""
() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const sx = window.scrollX, sy = window.scrollY;
  function chainOpacity(el) { let o = 1; while (el && el.nodeType === 1) { const v = parseFloat(getComputedStyle(el).opacity); o *= isNaN(v) ? 1 : v; el = el.parentElement; } return o; }
  let n;
  while ((n = walker.nextNode())) {
    const t = n.textContent.replace(/\s+/g, ' ').trim();
    if (t.length < 2) continue;
    const el = n.parentElement; if (!el) continue;
    if (['SCRIPT','STYLE','NOSCRIPT','TITLE'].includes(el.tagName)) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (el.closest('details:not([open])') && !el.closest('summary')) continue;   // closed accordion answers are not painted
    const rg = document.createRange(); rg.selectNodeContents(n);
    const rects = Array.from(rg.getClientRects()).filter(r => r.width > 1 && r.height > 1);
    if (!rects.length) continue;
    const fillc = cs.webkitTextFillColor && cs.webkitTextFillColor.startsWith('rgb') ? cs.webkitTextFillColor : cs.color;
    const m = fillc.match(/rgba?\(([^)]+)\)/); if (!m) continue;
    const p = m[1].split(',').map(parseFloat);
    if (p.length > 3 && p[3] < 0.05) continue;   // gradient / clipped text (painted by background-clip:text): measured separately
    const fs = parseFloat(cs.fontSize), fw = parseInt(cs.fontWeight) || 400;
    const large = fs >= 24 || (fs >= 18.66 && fw >= 700);
    const cls = (el.className && el.className.baseVal === undefined ? el.className : '') + '';
    out.push({text: t.slice(0, 40), tag: el.tagName.toLowerCase(), cls: cls.slice(0, 50), color: [p[0], p[1], p[2]], alpha: (p.length > 3 ? p[3] : 1) * chainOpacity(el),
              large, fs, rects: rects.slice(0, 3).map(r => [r.left + sx, r.top + sy, r.width, r.height]),
              parent: (el.parentElement && el.parentElement.className && el.parentElement.className.baseVal === undefined ? el.parentElement.className : '') + ''});
  }
  return out;
}
"""

HIDE = "*,*::before,*::after{color:transparent!important;-webkit-text-fill-color:transparent!important;text-shadow:none!important;caret-color:transparent!important;text-decoration-color:transparent!important}svg *{fill-opacity:1}"


def lum(c):
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def ratio(a, b):
    la, lb = lum(a), lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def audit_page(page, path, width, shots_dir=None):
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto('file://' + os.path.abspath(path).replace('\\', '/'), wait_until='load')
    page.evaluate('document.fonts.ready')
    page.wait_for_timeout(250)
    h = page.evaluate('document.documentElement.scrollHeight')
    y = 0
    while y < h:                                   # scroll-reveal animations (opacity:0 until seen) must have played before measuring
        page.evaluate('window.scrollTo(0,%d)' % y)
        page.wait_for_timeout(70)
        y += 500
    page.evaluate('window.scrollTo(0,0)')
    page.wait_for_timeout(500)
    page.add_style_tag(content='*,*::before,*::after{animation:none!important;transition:none!important}')
    page.wait_for_timeout(250)
    items = page.evaluate(JS)
    page.add_style_tag(content=HIDE)
    page.wait_for_timeout(120)
    png = page.screenshot(full_page=True)
    im = Image.open(io.BytesIO(png)).convert('RGB')
    W, H = im.size
    px = im.load()
    bad = []
    for it in items:
        if it['alpha'] < 0.05:                      # revealed on hover/focus only (bento links, hover menus)
            continue
        worst = 99.0
        wbg = None
        weff = None
        for (x, y, w, h) in it['rects']:
            for gx in (0.1, 0.35, 0.65, 0.9):
                for gy in (0.2, 0.5, 0.8):
                    X, Y = int(x + w * gx), int(y + h * gy)
                    if 0 <= X < W and 0 <= Y < H:
                        bg = px[X, Y]
                        a = min(1.0, max(0.0, it['alpha']))
                        eff = tuple(bg[i] * (1 - a) + it['color'][i] * a for i in range(3))
                        rr = ratio(eff, bg)
                        if rr < worst:
                            worst, wbg, weff = rr, bg, eff
        if worst == 99.0:
            continue
        need = 3.0 if it['large'] else 4.5
        if worst < need:
            bad.append({'text': it['text'], 'tag': it['tag'], 'cls': it['cls'], 'parent': it['parent'][:40], 'ratio': round(worst, 2), 'need': need, 'fs': it['fs'], 'fg': '#%02x%02x%02x' % tuple(int(v) for v in weff), 'bg': '#%02x%02x%02x' % tuple(wbg)})
    return len(items), bad


def main():
    args = sys.argv[1:]
    d = args[0]
    widths = [int(a) for a in args[1:] if a.isdigit()] or [1280, 390]
    only = None
    outjson = None
    if '--only' in args:
        only = args[args.index('--only') + 1].split(',')
    if '--json' in args:
        outjson = args[args.index('--json') + 1]
    files = sorted(glob.glob(os.path.join(d, '*.html')))
    if only:
        files = [f for f in files if os.path.basename(f)[:-5] in only]
    report = {}
    tmp = tempfile.mkdtemp(prefix='ctr_')
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel='chromium')
            try:
                ctx = b.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=1)
                page = ctx.new_page()
                for f in files:
                    key = os.path.basename(f)[:-5]
                    for w in widths:
                        try:
                            n, bad = audit_page(page, f, w)
                        except Exception as e:  # noqa
                            report.setdefault(key, {})[w] = {'error': str(e)[:100]}
                            continue
                        report.setdefault(key, {})[w] = {'n': n, 'bad': bad}
                ctx.close()
            finally:
                b.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    nfail = 0
    summary = {}
    for k, per in report.items():
        for w, r in per.items():
            if 'bad' in r and r['bad']:
                nfail += 1
                for x in r['bad']:
                    summary.setdefault((x['tag'], x['cls'] or x['parent']), []).append((k, w, x['ratio'], x['text']))
    print('styles with failures:', len({k for k, per in report.items() for w, r in per.items() if r.get('bad')}), 'of', len(report))
    for (tag, cls), rows in sorted(summary.items(), key=lambda kv: -len(kv[1])):
        mn = min(r[2] for r in rows)
        print('%4d  %-6s %-34s min=%.2f  e.g. %s %s' % (len(rows), tag, cls[:34], mn, rows[0][0], rows[0][3][:25]))
    if outjson:
        json.dump(report, open(outjson, 'w', encoding='utf-8'), ensure_ascii=False)
    return 1 if nfail else 0



if __name__ == '__main__':
    sys.exit(main())
