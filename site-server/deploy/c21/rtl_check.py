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


def main():
    d = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(d, 'rtl.json')
    from playwright.sync_api import sync_playwright
    keys = sorted(f[:-5] for f in os.listdir(d) if f.endswith('.html'))
    res = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
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
