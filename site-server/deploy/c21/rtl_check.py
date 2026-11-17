#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RTL / mobile check of converted components in a real browser.

    python rtl_check.py <dir-with-html-files> [<out.json>]

Every <key>.html in the directory is opened with dir="rtl" (the component host is forced to rtl too: Persian texts make dir=auto resolve to rtl) at 390 and 1280 px; the script reports, per key,
  overflow_390 / overflow_1280   the page scrolls sideways (document wider than the window)
  escapes                       elements whose box leaves the window by more than 2 px (decorative marquees inside overflow:clip are ignored)
  rtl                           the computed direction of the host is rtl
  status                        ok | warn (only desktop overflows, or an element leaves the window) | fail (the phone view overflows sideways) | error
  text_<w> / visual_<w>         visible characters / visible images, svgs, inputs, buttons (both 0 = only an empty frame: canvas or script-driven animation)
  <key>-<width>.png             a screenshot of the top of each page (390 and 1280 px); the caller measures how much is actually visible (components that render empty
                                as static HTML - typing animations, canvases, sliders at 0 - are blank: c21_rtl.ink_of)
Readability (review round 3, 2026-11-17): every <name>~<ctx>.html (the caller writes <key>~tl|td|il|id.html = light theme, dark theme, light island, dark island; any other page can be named
<anything>~<anything>.html) is opened at 1280 px (viewport height 1400) and the script writes
  <name>.json   {items: every visible text node with colour, opacity chain, size, rectangles (clipped by overflow ancestors), occ = covered by something that is not its own box,
                chars, height}
  <name>.png    the full page with ALL text transparent: the caller measures the real pixels behind each text (c21_contrast.measure, Pillow) - no Pillow is needed here.
Needs Playwright for Python and a Chromium (the headless shell is enough). PLAYWRIGHT_BROWSERS_PATH is respected.
"""
import json
import os
import sys

JS = """() => {
  const de = document.documentElement, vw = de.clientWidth, esc = [];
  document.querySelectorAll('body *').forEach((e) => {
    const r = e.getBoundingClientRect();
    if (r.width > 0 && (r.right > vw + 2 || r.left < -2)) {
      let p = e, clipped = false;
      while (p && p !== document.body) { const o = getComputedStyle(p); if (['hidden', 'clip', 'auto', 'scroll'].includes(o.overflowX) && p !== e) { clipped = true; break; } p = p.parentElement; }
      if (!clipped) esc.push((e.className && e.className.baseVal === undefined ? e.className : e.tagName) + '');
    }
  });
  const host = document.querySelector('.nbc21-host > div') || document.body;
  // «محتوا»: متنِ دیدنی یا یک عنصرِ تصویری/ورودیِ دیدنی (تصویر، svg، فیلد، دکمه، ویدیو …). فقط یک قابِ خالی (canvas/انیمیشنِ بی‌جاوااسکریپت) محتوا ندارد؛ حاشیهٔ قاب «جوهر» حساب می‌شود ولی محتوا نیست.
  const seen = (e) => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width >= 8 && r.height >= 8 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0.05; };
  let visual = 0;
  document.querySelectorAll('body img, body svg, body input, body textarea, body select, body button, body video, body progress, body meter').forEach((e) => { if (seen(e)) visual++; });
  const text = (document.body.innerText || '').replace(/\s+/g, '').length;
  return { sw: de.scrollWidth, vw, dir: getComputedStyle(host).direction, escapes: esc.slice(0, 5), n: esc.length, h: de.scrollHeight, text, visual };
}"""


TEXT_JS = r"""
() => {
  // every visible text node: colour, opacity chain, size and rectangles (the caller measures the real pixels behind it in the text-less screenshot)
  const out = [], sx = window.scrollX, sy = window.scrollY;
  // Tailwind v4 colours are oklch()/color-mix(): getComputedStyle returns them as written (oklch(0.87 0 0), color(srgb ...)), not as rgb(). The old rgb()-only regex silently SKIPPED every such
  // text (text-neutral-300, text-red-500 ...), so the readability gate never saw the dim texts that were the actual problem (review round 4). A 1x1 canvas converts any CSS colour to sRGB.
  const cvs = document.createElement('canvas'); cvs.width = cvs.height = 1;
  const g2 = cvs.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    const m = String(c || '').match(/^rgba?\(([^)]+)\)$/);
    if (m) { const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    if (!g2) return null;
    g2.clearRect(0, 0, 1, 1); g2.fillStyle = 'rgba(1,2,3,0.004)'; g2.fillStyle = String(c); g2.fillRect(0, 0, 1, 1);
    const d = g2.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const chain = (el) => { let o = 1; while (el && el.nodeType === 1) { const v = parseFloat(getComputedStyle(el).opacity); o *= isNaN(v) ? 1 : v; el = el.parentElement; } return o; };
  let n;
  while ((n = walker.nextNode())) {
    const t = n.textContent.replace(/\s+/g, ' ').trim();
    if (t.length < 2) continue;
    const el = n.parentElement; if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE'].includes(el.tagName)) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (el.closest('details:not([open])') && !el.closest('summary')) continue;
    const rg = document.createRange(); rg.selectNodeContents(n);
    let rects = Array.from(rg.getClientRects()).filter((r) => r.width > 1 && r.height > 1).map((r) => [r.left, r.top, r.right, r.bottom]);
    // text clipped away by an ancestor (marquees, carousels, scroll areas: overflow hidden/clip/auto/scroll) is not seen: keep only the visible part
    for (let a = el; a && a !== document.body && rects.length; a = a.parentElement) {
      const o = getComputedStyle(a);
      const cx = o.overflowX !== 'visible', cy = o.overflowY !== 'visible';
      if (!cx && !cy) continue;
      const b = a.getBoundingClientRect();
      rects = rects.map((r) => [cx ? Math.max(r[0], b.left) : r[0], cy ? Math.max(r[1], b.top) : r[1], cx ? Math.min(r[2], b.right) : r[2], cy ? Math.min(r[3], b.bottom) : r[3]])
        .filter((r) => r[2] - r[0] > 1 && r[3] - r[1] > 1);
    }
    rects = rects.map((r) => ({ left: r[0], top: r[1], width: r[2] - r[0], height: r[3] - r[1] }));
    if (!rects.length) continue;
    const fill = cs.webkitTextFillColor || cs.color;          // transparent fill (bg-clip-text gradients) = not measurable, skipped below
    const p = rgba(fill); if (!p) continue;
    if (p[3] < 0.05) continue;
    const fs = parseFloat(cs.fontSize), fw = parseInt(cs.fontWeight) || 400;
    // text covered by something that is NOT its own box (a badge over a label, two labels on top of each other, an icon over text): elementFromPoint skips pointer-events:none decorations
    let occ = 0;
    if (parseFloat(cs.opacity) > 0.05) {
      const r0 = rects[0];
      for (const gx of [0.06, 0.3, 0.5, 0.7, 0.94]) for (const gy of [0.3, 0.7]) {
        const x = r0.left + r0.width * gx, y = r0.top + r0.height * gy;
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
        const top = document.elementFromPoint(x, y);
        if (!top || top === el || el.contains(top) || top.contains(el)) continue;
        const tcs = getComputedStyle(top), bg = rgba(tcs.backgroundColor);
        const solid = bg && bg[3] >= 0.9;
        const own = Array.from(top.childNodes).some((c) => c.nodeType === 3 && c.textContent.trim().length > 0);
        if (solid || own || ['IMG', 'CANVAS', 'VIDEO'].includes(top.tagName)) { occ++; }
      }
    }
    out.push({ text: t.slice(0, 40), color: [p[0], p[1], p[2]], alpha: p[3] * chain(el), large: fs >= 24 || (fs >= 18.66 && fw >= 700), occ,
               rects: rects.slice(0, 3).map((r) => [r.left + sx, r.top + sy, r.width, r.height]) });
  }
  return out;
}
"""
HIDE = "*,*::before,*::after{color:transparent!important;-webkit-text-fill-color:transparent!important;text-shadow:none!important;caret-color:transparent!important;text-decoration-color:transparent!important}"
FREEZE = "*,*::before,*::after{animation:none!important;transition:none!important}"


def capture_contrast(b, d, ctx_files):
    """<key>~<ctx>.html (ctx = tl td il id) at 1280: <key>~<ctx>.json = text items, <key>~<ctx>.png = full page with all text transparent (c21_rtl.measure reads both)."""
    ctx = b.new_context(viewport={'width': 1280, 'height': 1400})
    page = ctx.new_page()
    try:
        for name in ctx_files:
            try:
                page.goto('file://%s/%s.html' % (os.path.abspath(d), name), wait_until='load', timeout=30000)
                page.evaluate("document.querySelectorAll('.nbc21-host > div').forEach((e) => e.setAttribute('dir', 'rtl'))")
                page.add_style_tag(content=FREEZE)
                page.wait_for_timeout(250)
                items = page.evaluate(TEXT_JS)
                chars = page.evaluate("(document.body.innerText || '').replace(/\\s+/g, '').length")
                # the component's own height (host box), NOT the page: documentElement.scrollHeight is never below the 1400 px viewport, which made every component look 'tall'
                height = page.evaluate("(() => { const h = document.querySelector('.nbc21-host'); if (!h) return document.documentElement.scrollHeight; const r = h.getBoundingClientRect(); return Math.round(Math.max(r.height, h.scrollHeight)); })()")
                page.add_style_tag(content=HIDE)
                page.wait_for_timeout(100)
                page.screenshot(path='%s/%s.png' % (os.path.abspath(d), name), full_page=True)
                with open('%s/%s.json' % (os.path.abspath(d), name), 'w', encoding='utf-8') as fh:
                    json.dump({'items': items, 'chars': chars, 'height': height}, fh, ensure_ascii=False)
            except Exception as exc:  # noqa: BLE001
                with open('%s/%s.json' % (os.path.abspath(d), name), 'w', encoding='utf-8') as fh:
                    json.dump({'error': str(exc)[:160]}, fh)
    finally:
        ctx.close()


def main():
    d = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(d, 'rtl.json')
    from playwright.sync_api import sync_playwright
    allhtml = sorted(f[:-5] for f in os.listdir(d) if f.endswith('.html'))
    keys = [f for f in allhtml if '~' not in f]
    ctx_files = [f for f in allhtml if '~' in f]
    res = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            if ctx_files:
                capture_contrast(b, d, ctx_files)
            for w in (390, 1280):
                ctx = b.new_context(viewport={'width': w, 'height': 900})
                page = ctx.new_page()
                for k in keys:
                    try:
                        page.goto('file://%s/%s.html' % (os.path.abspath(d), k), wait_until='load', timeout=30000)
                        page.evaluate("document.querySelectorAll('.nbc21-host > div').forEach((e) => e.setAttribute('dir', 'rtl'))")      # متنِ فارسی ⇒ dir=auto همین می‌شود
                        page.wait_for_timeout(150)
                        m = page.evaluate(JS)
                        page.wait_for_timeout(250)                                   # animations/transitions settle (the screenshot is what the owner would see)
                        page.screenshot(path='%s/%s-%d.png' % (os.path.abspath(d), k, w), full_page=False)
                        row = res.setdefault(k, {})
                        row['overflow_%d' % w] = m['sw'] > m['vw'] + 1
                        row['escapes_%d' % w] = m['n']
                        row['escape_sample'] = m['escapes'] or row.get('escape_sample', [])
                        row['rtl'] = row.get('rtl', True) and m['dir'] == 'rtl'
                        row['text_%d' % w] = m['text']
                        row['visual_%d' % w] = m['visual']
                        if w == 1280:
                            row['height'] = m['h']
                    except Exception as exc:  # noqa: BLE001
                        res.setdefault(k, {})['error'] = str(exc)[:160]
                ctx.close()
        finally:
            b.close()
    for k, row in res.items():
        if row.get('error'):
            row['status'] = 'error'
        elif row.get('overflow_390'):
            row['status'] = 'fail'                    # a phone scrolls sideways (RTL: content that leaves on the left is cut off, not scrollable; see escapes_*)
        elif row.get('overflow_1280') or row.get('escapes_390') or row.get('escapes_1280') or not row.get('rtl'):
            row['status'] = 'warn'
        else:
            row['status'] = 'ok'
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: v['status'] for k, v in res.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
