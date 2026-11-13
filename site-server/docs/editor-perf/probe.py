#!/usr/bin/env python3
"""Editor smoothness probe: scripted playback / scrubbing / drag / shortcuts on the manual video editor, printing numbers as JSON.

usage:  NM_PROBE_BASE=http://127.0.0.1:8124 NM_PROBE_USER=... NM_PROBE_PASS=... python probe.py LABEL [cpu_throttle] [scenarios,comma]
        (a STAGING copy of the site with a test user and a test project that has clips named v1c2 / v1c3 on the first video track; never the live site)

Opens /panel/stores/34/editor?mode=manual, then runs scripted scenarios:
  load      time to a usable workspace + JS bytes
  play      6 s of playback (selected clip, colour tab, scopes open = the heavy case)
  scrub     3 s of ruler scrubbing at ~125 Hz mouse events
  drag      3 s drag of one clip at ~125 Hz, then undo/redo check
  keys      keyboard shortcuts + autosave + undo/redo functional check
Numbers: React commits (devtools hook), dev counters (window.__nmPerf), CDP Task/Script durations, long tasks, frame pacing.
"""
import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

import os

LABEL = sys.argv[1]
CPU = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
ONLY = sys.argv[3].split(',') if len(sys.argv) > 3 else ['load', 'play', 'scrub', 'drag', 'keys']
BASE = os.environ.get('NM_PROBE_BASE', 'http://127.0.0.1:8124').rstrip('/')
URL = BASE + '/panel/stores/34/editor?mode=manual'


def login():
    req = urllib.request.Request(BASE + '/api/v1/auth/login/', data=json.dumps({'username': os.environ['NM_PROBE_USER'], 'password': os.environ['NM_PROBE_PASS']}).encode(), headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=30))


INIT = """
(() => {
  window.__nmPerf = {};
  window.__commits = 0;
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
    supportsFiber: true, isDisabled: false, renderers: new Map(),
    inject(r) { this.renderers.set(1, r); return 1; },
    onCommitFiberRoot() { window.__commits++; }, onCommitFiberUnmount() {}, onPostCommitFiberRoot() {}, checkDCE() {},
  };
  window.__long = { n: 0, total: 0, max: 0 };
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) { window.__long.n++; window.__long.total += e.duration; window.__long.max = Math.max(window.__long.max, e.duration); } }).observe({ entryTypes: ['longtask'] });
  } catch (e) {}
  window.__fr = { on: false, last: 0, d: [] };
  const loop = (t) => { if (window.__fr.on) { if (window.__fr.last) window.__fr.d.push(t - window.__fr.last); window.__fr.last = t; } else window.__fr.last = 0; requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
})();
"""


def pct(xs, q):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


class Probe:
    def __init__(self, page, cdp):
        self.p = page
        self.cdp = cdp

    def metrics(self):
        m = {x['name']: x['value'] for x in self.cdp.send('Performance.getMetrics')['metrics']}
        return m

    def start(self):
        self.m0 = self.metrics()
        self.p.evaluate("() => { window.__c0 = window.__commits; window.__n0 = Object.assign({}, window.__nmPerf); window.__l0 = Object.assign({}, window.__long); window.__fr.d = []; window.__fr.on = true; }")
        self.t0 = time.time()

    def stop(self):
        r = self.p.evaluate("""() => { window.__fr.on = false; const n = {}; for (const k of Object.keys(window.__nmPerf)) n[k] = window.__nmPerf[k] - (window.__n0[k] || 0);
          return { commits: window.__commits - window.__c0, counters: n, long: { n: window.__long.n - window.__l0.n, ms: window.__long.total - window.__l0.total, max: window.__long.max }, frames: window.__fr.d.slice() }; }""")
        m1 = self.metrics()
        secs = time.time() - self.t0
        fr = r['frames']
        out = {
            'seconds': round(secs, 2),
            'commits': r['commits'],
            'commits_per_s': round(r['commits'] / secs, 1),
            'counters': {k: v for k, v in r['counters'].items() if v},
            'task_ms': round((m1['TaskDuration'] - self.m0['TaskDuration']) * 1000),
            'script_ms': round((m1['ScriptDuration'] - self.m0['ScriptDuration']) * 1000),
            'layout_ms': round((m1['LayoutDuration'] - self.m0['LayoutDuration']) * 1000),
            'style_ms': round((m1['RecalcStyleDuration'] - self.m0['RecalcStyleDuration']) * 1000),
            'layouts': int(m1['LayoutCount'] - self.m0['LayoutCount']),
            'longtasks': r['long']['n'], 'longtask_ms': round(r['long']['ms']), 'longest_ms': round(r['long']['max']),
            'frames': len(fr), 'fps': round(len(fr) / secs, 1) if secs else 0,
            'frame_p50': round(pct(fr, 0.5), 1), 'frame_p95': round(pct(fr, 0.95), 1), 'frame_max': round(max(fr), 1) if fr else 0,
            'frames_over_50ms': sum(1 for x in fr if x > 50),
        }
        out['busy_pct'] = round(100 * out['task_ms'] / 1000 / secs, 1)
        return out


def txt(page, sel):
    try:
        return page.inner_text(sel, timeout=2000)
    except Exception:
        return None


def clip_left(page, cid):
    return page.evaluate("(id) => { const e = document.querySelector('[data-clip=\"' + id + '\"]'); return e ? parseFloat(e.style.left) : null; }", cid)


def playhead_left(page):
    return page.evaluate("() => { const e = document.querySelector('[data-testid=\"playhead\"]'); return e ? parseFloat(e.style.left) : null; }")


def main():
    tok = login()
    res = {'label': LABEL, 'cpu_throttle': CPU}
    with sync_playwright() as p:
        b = p.chromium.launch(channel='chromium')
        try:
            ctx = b.new_context(viewport={'width': 1600, 'height': 900})
            ctx.add_init_script("try{localStorage.setItem('access','%s');localStorage.setItem('refresh','%s');localStorage.setItem('nm.video.mode','manual');localStorage.setItem('nm.video.inspector.full','1')}catch(e){}" % (tok['access'], tok['refresh']))
            ctx.add_init_script(INIT)
            pg = ctx.new_page()
            if os.environ.get('NOMEDIA'):
                # isolates the React/app cost: video files are not served, so no seeks/decodes/drawImage of video frames
                pg.route('**/media/**', lambda r: r.abort())
            cdp = ctx.new_cdp_session(pg)
            cdp.send('Performance.enable')
            if CPU > 1:
                cdp.send('Emulation.setCPUThrottlingRate', {'rate': CPU})
            reqs = []
            pg.on('request', lambda r: reqs.append((r.method, r.url.replace(BASE, ''))))
            errors = []
            pg.on('pageerror', lambda e: errors.append(str(e)[:300]))
            pg.on('console', lambda m: errors.append('console.error: ' + m.text[:300]) if m.type == 'error' else None)
            P = Probe(pg, cdp)

            # ───── load
            t0 = time.time()
            pg.goto(URL, wait_until='commit')
            pg.wait_for_selector('[data-testid="video-workspace"]', timeout=120000)
            t_ws = time.time() - t0
            pg.wait_for_selector('[data-clip]', timeout=120000)
            t_clips = time.time() - t0
            pg.wait_for_selector('[data-testid="program-canvas"]', timeout=60000)
            time.sleep(1.5)
            nav = pg.evaluate("""() => { const r = performance.getEntriesByType('resource'); const js = r.filter(x => x.name.endsWith('.js')); const n = performance.getEntriesByType('navigation')[0];
              return { js_files: js.length, js_decoded_kb: Math.round(js.reduce((a, x) => a + x.decodedBodySize, 0) / 1024), js_transfer_kb: Math.round(js.reduce((a, x) => a + x.transferSize, 0) / 1024), dcl_ms: Math.round(n.domContentLoadedEventEnd), load_ms: Math.round(n.loadEventEnd),
                heap_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null }; }""")
            res['load'] = {'workspace_visible_s': round(t_ws, 2), 'first_clips_s': round(t_clips, 2), **nav, 'clips': pg.evaluate("document.querySelectorAll('[data-clip]').length")}
            res['page_errors_on_load'] = list(errors)
            if ONLY == ['load']:
                print(json.dumps(res, ensure_ascii=False, indent=1))
                return

            # select a clip so the inspector / gizmo / look thumbnails are live
            pg.click('[data-clip="v1c2"]')
            time.sleep(0.3)
            if 'play' in ONLY:
                # heavy case: colour tab (look thumbnails) + scopes open
                try:
                    pg.click('button:text-is("رنگ")', timeout=3000)
                    pg.click('[data-testid="color-looks"] .ws-acc-head', timeout=3000)   # the look thumbnails (LookGrid) are only built while this section is open
                except Exception:
                    pass
                try:
                    pg.click('[data-testid="toggle-scopes"]', timeout=3000)
                except Exception:
                    pass
                time.sleep(1.0)
                pg.evaluate("() => { document.querySelector('[data-testid=\"vw-prev-frame\"]'); }")
                ph0 = playhead_left(pg)
                P.start()
                pg.click('[data-testid="vw-play"]')
                time.sleep(6.0)
                r = P.stop()
                pg.click('[data-testid="vw-play"]')
                time.sleep(0.4)
                r['playhead_px_moved'] = round((playhead_left(pg) or 0) - (ph0 or 0), 1)
                r['vw_time'] = txt(pg, '[data-testid="vw-time"]')
                res['play'] = r
                pg.click('[data-testid="toggle-scopes"]')
                pg.click('button:text-is("قطعه")', timeout=3000)
                time.sleep(0.5)

            if 'scrub' in ONLY:
                box = pg.locator('[data-testid="ruler"]').bounding_box()
                x0 = box['x'] + 40
                y = box['y'] + box['height'] / 2
                P.start()
                pg.mouse.move(x0, y)
                pg.mouse.down()
                n = 360
                for i in range(n):
                    frac = (i % 120) / 120.0
                    x = x0 + (frac if (i // 120) % 2 == 0 else 1 - frac) * 700
                    pg.mouse.move(x, y)
                    time.sleep(0.008)
                pg.mouse.up()
                r = P.stop()
                r['moves'] = n
                r['move_call_ms_avg'] = round(sum(lat) / max(1, len(lat)), 1)
                r['move_call_ms_p95'] = round(pct(lat, 0.95), 1)
                r['playhead_px'] = playhead_left(pg)
                r['vw_time'] = txt(pg, '[data-testid="vw-time"]')
                res['scrub'] = r

            if 'drag' in ONLY:
                el = pg.locator('[data-clip="v1c3"]')
                bx = el.bounding_box()
                left0 = clip_left(pg, 'v2c1')
                sx, sy = bx['x'] + bx['width'] / 2, bx['y'] + bx['height'] / 2
                P.start()
                pg.mouse.move(sx, sy)
                pg.mouse.down()
                n = 360
                for i in range(1, n + 1):
                    pg.mouse.move(sx + 80.0 * i / n, sy)
                    time.sleep(0.008)
                pg.mouse.up()
                r = P.stop()
                time.sleep(0.4)
                left1 = clip_left(pg, 'v2c1')
                r['moves'] = n
                r['clip_left_before'] = left0
                r['clip_left_after'] = left1
                pg.keyboard.press('Control+z')
                time.sleep(0.4)
                r['clip_left_after_undo'] = clip_left(pg, 'v2c1')
                pg.keyboard.press('Control+y')
                time.sleep(0.4)
                r['clip_left_after_redo'] = clip_left(pg, 'v2c1')
                pg.keyboard.press('Control+z')
                time.sleep(0.4)
                res['drag'] = r


            if 'ip' in ONLY:
                # in-page synthetic pointer events (no CDP/OS latency): one event per frame, N events. Robust CPU cost per interaction step.
                IPJS = """async ({ n, target, x0, y, path }) => {
                  const watch = document.querySelector(target.indexOf('ruler') >= 0 ? '[data-testid="playhead"]' : target);
                  const seen = new Set();
                  const frame = () => new Promise((r) => requestAnimationFrame(() => r()));
                  const mk = (type, x) => new PointerEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, buttons: type === 'pointerup' ? 0 : 1, pointerId: 1, pointerType: 'mouse', isPrimary: true });
                  const t0 = performance.now();
                  document.querySelector(target).dispatchEvent(mk('pointerdown', x0));
                  await frame(); await frame();
                  let x = x0;
                  for (let i = 1; i <= n; i++) {
                    x = x0 + path(i / n);
                    window.dispatchEvent(mk('pointermove', x));
                    await frame();
                    seen.add(watch.style.left);
                  }
                  window.dispatchEvent(mk('pointerup', x));
                  await frame();
                  return { ms: performance.now() - t0, distinct_positions: seen.size };
                }"""
                box = pg.locator('[data-testid="ruler"]').bounding_box()
                n = 90
                P.start()
                ev = pg.evaluate(IPJS.replace('path }) =>', '}) =>').replace('path(i / n)', '(Math.abs(((i / n) * 4) % 2 - 1) * 700)'), {'n': n, 'target': '[data-testid="ruler"]', 'x0': box['x'] + 40, 'y': box['y'] + box['height'] / 2})
                r = P.stop()
                r['steps'] = n
                r['ms_per_step'] = round(ev['ms'] / n, 1)
                r['distinct_positions'] = ev['distinct_positions']
                r['cpu_ms_per_step'] = round(r['task_ms'] / n, 1)
                r['js_ms_per_step'] = round(r['script_ms'] / n, 1)
                r['vw_time'] = txt(pg, '[data-testid="vw-time"]')
                res['ip_scrub'] = r
                if os.environ.get('NOSNAP'):
                    pg.click('[data-testid="tl-snap"]')   # snapping makes the dragged clip jump between a few magnet points; off = every step moves it
                pg.locator('[data-clip="v2c1"]').scroll_into_view_if_needed()
                cb = pg.locator('[data-clip="v2c1"]').bounding_box()
                left0 = clip_left(pg, 'v2c1')
                P.start()
                ev = pg.evaluate(IPJS.replace('path }) =>', '}) =>').replace('path(i / n)', '(80 * i / n)'), {'n': n, 'target': '[data-clip="v2c1"]', 'x0': cb['x'] + cb['width'] / 2, 'y': cb['y'] + cb['height'] / 2})
                r = P.stop()
                time.sleep(0.4)
                r['steps'] = n
                r['ms_per_step'] = round(ev['ms'] / n, 1)
                r['distinct_positions'] = ev['distinct_positions']
                r['cpu_ms_per_step'] = round(r['task_ms'] / n, 1)
                r['js_ms_per_step'] = round(r['script_ms'] / n, 1)
                r['clip_left_before'] = left0
                r['clip_left_after'] = clip_left(pg, 'v2c1')
                pg.keyboard.press('Control+z')
                time.sleep(0.4)
                r['clip_left_after_undo'] = clip_left(pg, 'v2c1')
                res['ip_drag'] = r

            if 'keys' in ONLY:
                k = {}
                pg.click('[data-testid="ruler"]', position={'x': 220, 'y': 8})
                time.sleep(0.3)
                n0 = pg.evaluate("document.querySelectorAll('[data-clip]').length")
                k['clips_before'] = n0
                k['time_before'] = txt(pg, '[data-testid="vw-time"]')
                pg.keyboard.press('ArrowRight')
                time.sleep(0.2)
                k['time_after_arrow'] = txt(pg, '[data-testid="vw-time"]')
                pg.keyboard.press('Space')
                time.sleep(1.2)
                k['time_after_space_1s'] = txt(pg, '[data-testid="vw-time"]')
                pg.keyboard.press('Space')
                time.sleep(0.3)
                k['playing_after_second_space'] = pg.evaluate("document.querySelector('[data-testid=\"vw-play\"]').getAttribute('aria-pressed')")
                reqs.clear()
                pg.click('[data-testid="ruler"]', position={'x': 260, 'y': 8})
                time.sleep(0.2)
                pg.keyboard.press('s')
                time.sleep(0.4)
                n1 = pg.evaluate("document.querySelectorAll('[data-clip]').length")
                k['clips_after_split'] = n1
                pg.keyboard.press('Control+z')
                time.sleep(0.4)
                k['clips_after_undo'] = pg.evaluate("document.querySelectorAll('[data-clip]').length")
                pg.keyboard.press('Control+y')
                time.sleep(0.4)
                k['clips_after_redo'] = pg.evaluate("document.querySelectorAll('[data-clip]').length")
                time.sleep(2.6)
                k['autosave_requests'] = [f'{m} {u}' for m, u in reqs if '/editor/projects/' in u and m in ('PUT', 'PATCH', 'POST')]
                k['non_get_requests'] = [f'{m} {u}' for m, u in reqs if m != 'GET'][:8]
                pg.keyboard.press('Control+z')
                time.sleep(2.6)
                k['clips_final'] = pg.evaluate("document.querySelectorAll('[data-clip]').length")
                pg.keyboard.press('m')
                time.sleep(0.3)
                k['markers'] = pg.evaluate("document.querySelectorAll('[data-marker]').length")
                pg.keyboard.press('Control+z')
                pg.keyboard.press('?')
                time.sleep(0.4)
                k['shortcut_sheet_opens'] = pg.evaluate("!!document.querySelector('.ws-modal, [data-testid=\"shortcut-sheet\"], .sq-modal, [role=\"dialog\"]')")
                pg.keyboard.press('Escape')
                res['keys'] = k
            res['page_errors'] = errors[:8]
        finally:
            b.close()
    print(json.dumps(res, ensure_ascii=False, indent=1))


main()
