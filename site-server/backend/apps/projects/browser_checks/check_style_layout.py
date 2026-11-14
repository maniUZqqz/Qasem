# -*- coding: utf-8 -*-
"""Real-browser layout check of the 14 site-builder styles (Persian / RTL).

usage:  python check_style_layout.py DIR [--shots OUT] [--theme dark|light]
DIR holds <style>.html pages rendered by render_style_pages.py (fonts/ next to them).
For every style, at 1440 and 390 px, it FAILS on
  1. title/subtitle overlap: any .nb-title/.nb-hero-title and the next .nb-sub box overlap or touch (gap < 2 px)
  2. a drop-cap: a ::first-letter pseudo-element that floats or is larger than its parent on RTL text
and REPORTS (not fails) lone-word last lines of hero/section titles (orphans).
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

JS = r"""
() => {
  const out = {overlap: [], dropcap: [], orphans: []};
  const rect = el => el.getBoundingClientRect();
  // 1. title / subtitle pairs inside a head or hero copy
  document.querySelectorAll('.nb-head, .nb-hero-copy, .nb-cta-box').forEach(head => {
    const t = head.querySelector('.nb-title, .nb-hero-title');
    const s = head.querySelector('.nb-sub');
    if (!t || !s) return;
    const a = rect(t), b = rect(s);
    const inter = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
    const gap = b.top - a.bottom;
    if (inter > 0 || gap < 2) out.overlap.push({title: t.textContent.trim().slice(0, 30), gap: Math.round(gap * 10) / 10, inter: Math.round(inter), sub_display: getComputedStyle(s).display, title_display: getComputedStyle(t).display});
  });
  // 2. drop-caps on RTL text
  document.querySelectorAll('p, .nb-text, .nb-text > p, div').forEach(el => {
    if (!el.firstChild || (el.firstChild.nodeType !== 3 && el.firstElementChild)) return;
    const cs = getComputedStyle(el), fl = getComputedStyle(el, '::first-letter');
    const txt = (el.textContent || '').trim();
    if (!txt) return;
    if (fl.float !== 'none' || parseFloat(fl.fontSize) > parseFloat(cs.fontSize) * 1.05) {
      if (/[؀-ۿ]/.test(txt.slice(0, 3))) out.dropcap.push({text: txt.slice(0, 20), float: fl.float, fs: fl.fontSize, parent: cs.fontSize});
    }
  });
  // 3. title lines: split into words, group by line; report a lone last word
  document.querySelectorAll('h1, h2, .nb-hero-title, .nb-title').forEach(h => {
    if (h.closest('#nb-ui')) return;
    const walker = document.createTreeWalker(h, NodeFilter.SHOW_TEXT);
    const nodes = []; let n; while ((n = walker.nextNode())) nodes.push(n);
    const spans = [];
    nodes.forEach(tn => {
      const words = tn.textContent.split(/(\s+)/);
      const frag = document.createDocumentFragment();
      words.forEach(w => { if (!w.trim()) { frag.appendChild(document.createTextNode(w)); } else { const sp = document.createElement('span'); sp.textContent = w; sp.dataset.w = '1'; frag.appendChild(sp); spans.push(sp); } });
      tn.parentNode.replaceChild(frag, tn);
    });
    const lines = {};
    spans.forEach(sp => { const r = rect(sp); const k = Math.round(r.top / 4); (lines[k] = lines[k] || []).push(sp); });
    const keys = Object.keys(lines).map(Number).sort((a, b) => a - b);
    const info = keys.map(k => lines[k].length);
    if (keys.length > 1 && info[info.length - 1] === 1 && spans.length > 2) out.orphans.push({text: h.textContent.trim().slice(0, 40), lines: info});
  });
  return out;
}
"""


def main():
    d = sys.argv[1]
    shots = None
    theme = None
    if '--shots' in sys.argv:
        shots = sys.argv[sys.argv.index('--shots') + 1]
        os.makedirs(shots, exist_ok=True)
    if '--theme' in sys.argv:
        theme = sys.argv[sys.argv.index('--theme') + 1]
    pages = sorted(f for f in os.listdir(d) if f.endswith('.html'))
    fails, report = [], {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chromium')
        try:
            for width in (1440, 390):
                ctx = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=theme or 'light')
                try:
                    for name in pages:
                        page = ctx.new_page()
                        page.goto('file:///' + os.path.abspath(os.path.join(d, name)).replace('\\', '/'))
                        page.evaluate('document.fonts.ready')
                        page.wait_for_timeout(250)
                        if shots:
                            page.screenshot(path=os.path.join(shots, '%s-%d.png' % (name[:-5], width)), full_page=False)
                        res = page.evaluate(JS)
                        report['%s@%d' % (name[:-5], width)] = {'overlap': res['overlap'], 'dropcap': res['dropcap'], 'orphans': res['orphans']}
                        if res['overlap']:
                            fails.append((name, width, 'title/subtitle overlap', res['overlap']))
                        if res['dropcap']:
                            fails.append((name, width, 'drop-cap on RTL text', res['dropcap']))
                        page.close()
                finally:
                    ctx.close()
        finally:
            browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print('---')
    for f in fails:
        print('FAIL', f)
    print('RESULT', 'FAIL' if fails else 'PASS', len(fails))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
