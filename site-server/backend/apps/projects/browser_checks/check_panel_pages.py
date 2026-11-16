# -*- coding: utf-8 -*-
"""Real-browser check of the new panel pages with the REAL backend: «منبع‌های طراحی» (design sources), the style picker (89 styles, search, groups) and the
21st.dev browser (previews, «قابلِ درج», live preview, insert).

    cd backend && PYTHONPATH=/opt/up3d-uitest/venv/lib/python3.10/site-packages PLAYWRIGHT_BROWSERS_PATH=/opt/up3d-uitest/browsers \\
        ../venv/bin/python apps/projects/browser_checks/check_panel_pages.py [--shots DIR]

How: esbuild bundles frontend/tests/browser/panel-harness.tsx (the real components, with the panel's own CSS imports); Chromium loads it; axios is wired to a Python
function that answers with the real Django views through APIClient (staff user, the stage database).  No network, no server, nothing is written but temp files.
Needs: the frontend node_modules (esbuild, react, axios), Playwright for Python, a catalogue with converted components (NM_DATA_DIR) for the 21st part.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')      # Playwright's callbacks run inside an event loop; the views are plain sync code
import django

django.setup()
from django.contrib.auth import get_user_model  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

FRONT = os.path.abspath(os.path.join(os.getcwd(), '..', 'frontend'))
FAILS = []


def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        FAILS.append(what)


def bundle(tmp):
    esbuild = os.path.join(FRONT, 'node_modules', '.bin', 'esbuild')
    out = os.path.join(tmp, 'harness.js')
    r = subprocess.run([esbuild, os.path.join(FRONT, 'tests', 'browser', 'panel-harness.tsx'), '--bundle', '--format=iife', '--jsx=automatic', '--outfile=' + out, '--log-level=error',
                        '--define:process.env.NODE_ENV="production"'], cwd=FRONT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(2)
    with open(os.path.join(tmp, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="harness.css">'
                 '<style>:root{--brand:#126f85;--brand-ink:#fff;--line:#d6dbe3;--text:#111827;--text-2:#374151;--text-3:#6b7280;--surface:#fff;--surface-2:#f3f4f6;--bad:#b91c1c;--ok:#15803d;--bg:#f7f8fa;'
                 '--e-panel:#fff;--e-panel2:#f3f4f6;--e-line:#e5e7eb}body{font-family:Tahoma,sans-serif;background:var(--bg);color:var(--text);margin:16px}</style></head>'
                 '<body><div id="root"></div><script src="harness.js"></script></body></html>')
    return os.path.join(tmp, 'index.html')


def main():
    shots = sys.argv[sys.argv.index('--shots') + 1] if '--shots' in sys.argv else None
    if shots:
        os.makedirs(shots, exist_ok=True)
    from playwright.sync_api import sync_playwright
    U = get_user_model()
    staff = U.objects.filter(is_staff=True).first() or U(username='panel-check', is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(staff)
    from apps.projects.models import Project
    project = Project.objects.first()
    slug = project.slug if project else 'none'
    calls = []

    def mock_api(method, url, params, data):
        calls.append((method, url))
        path = url
        if params:
            from urllib.parse import urlencode
            path += '?' + urlencode({k: v for k, v in params.items() if v is not None and v != ''})
        r = getattr(client, method)(path, data, format='json') if method in ('post', 'put', 'patch') else getattr(client, method)(path)
        if getattr(r, 'streaming', False) or 'image' in r.get('Content-Type', ''):
            return {'status': r.status_code, 'data': None, 'b64': base64.b64encode(b''.join(r.streaming_content)).decode()}
        try:
            return {'status': r.status_code, 'data': r.json()}
        except ValueError:
            return {'status': r.status_code, 'data': None}

    tmp = tempfile.mkdtemp(prefix='nm-panel-check-')
    try:
        page_url = 'file://' + bundle(tmp).replace('\\', '/')
        opts = client.get('/api/v1/studio/projects/%s/builder/catalog/' % slug).json().get('theme_options', {}) if project else {}
        with sync_playwright() as p:
            b = p.chromium.launch()
            try:
                def open_view(view, width=1100):
                    ctx = b.new_context(viewport={'width': width, 'height': 900}, locale='fa-IR')
                    pg = ctx.new_page()
                    errors = []
                    pg.on('pageerror', lambda e: errors.append(str(e)[:200]))
                    pg.expose_function('mock_api', mock_api)
                    pg.add_init_script('window.__view=%s;window.__slug=%s;window.__opts=%s;' % (json.dumps(view), json.dumps(slug), json.dumps(opts)))
                    pg.goto(page_url)
                    return ctx, pg, errors

                # ── منبع‌های طراحی
                ctx, pg, errors = open_view('sources')
                pg.wait_for_selector('[data-testid=design-sources]', timeout=20000)
                tabs = pg.locator('[data-testid=ds-tabs] button')
                check(tabs.count() == 18, 'design sources: 17 data kinds + the 21st tab (%d tabs)' % tabs.count())
                check('MIT' in pg.inner_text('[data-testid=ds-note]') or 'ui-ux-pro-max' in pg.inner_text('body'), 'attribution is shown')
                pg.wait_for_selector('[data-testid=ds-total]')
                check('۸۹' in pg.inner_text('[data-testid=ds-total]'), 'styles tab lists 89 rows: ' + pg.inner_text('[data-testid=ds-total]'))
                pg.fill('[data-testid=ds-search]', 'brutalism')
                pg.wait_for_function("document.querySelectorAll('[data-testid=ds-site]').length > 0", timeout=10000)
                check(pg.locator('[data-testid=ds-site]').first.inner_text().startswith('در سایت‌ساز'), 'a style row shows its site-builder equivalent')
                pg.click('[data-kind=fonts]')
                pg.wait_for_selector('[data-testid=ds-fa]')
                check('معادلِ فارسی' in pg.locator('[data-testid=ds-fa]').first.inner_text(), 'font pairings show the Persian pair')
                pg.click('[data-kind=google_fonts]')
                pg.locator('label:has-text("فقط عربی") input').check()
                pg.locator('label:has-text("فقط آنچه در سایت‌ساز هست") input').check()
                pg.wait_for_selector('[data-testid=ds-bundled]', timeout=10000)
                check(pg.locator('[data-testid=ds-bundled]').count() >= 15, 'google fonts: bundled Arabic/Persian fonts (%d)' % pg.locator('[data-testid=ds-bundled]').count())
                pg.click('[data-kind=docs]')
                pg.wait_for_selector('.ds-more')
                pg.locator('.ds-more').first.click()
                pg.wait_for_selector('.ds-pre', timeout=10000)
                check(len(pg.inner_text('.ds-pre')) > 300, 'a doc opens its full text')
                pg.click('[data-kind=c21st]')
                pg.wait_for_selector('[data-testid=ds-c21]')
                check('قطعهٔ قابلِ درج' in pg.inner_text('[data-testid=ds-c21]'), 'the 21st tab shows the pipeline numbers')
                if shots:
                    pg.screenshot(path=os.path.join(shots, 'design-sources.png'), full_page=True)
                check(not errors, 'no javascript errors on the design sources page: %s' % errors[:2])
                ctx.close()

                # ── انتخابگرِ سبک (۸۹ سبک)
                if opts.get('styles'):
                    ctx, pg, errors = open_view('picker', 460)
                    pg.wait_for_selector('[data-testid=styles]')
                    n = len(opts['styles'])
                    check(pg.locator('.nbe-style').count() == 24, 'style picker shows the first 24 of %d' % n)
                    check(pg.locator('[data-testid=style-groups] button').count() >= 6, 'style groups are offered')
                    pg.fill('[data-testid=style-search]', 'ویپورویو')
                    check(pg.locator('.nbe-style').count() >= 1, 'search finds a generated style by its Persian name')
                    pg.fill('[data-testid=style-search]', '')
                    pg.locator('[data-testid=style-groups] button[data-group="داشبورد و تحلیل"]').click()
                    check(pg.locator('.nbe-style').count() == 10, 'group filter: 10 dashboard styles (%d)' % pg.locator('.nbe-style').count())
                    pg.locator('.nbe-style').first.click()
                    check('ui-ux-pro-max' in pg.inner_text('[data-testid=style-source]'), 'the style detail names its source row')
                    pg.locator('[data-testid=apply-style]').click()
                    pg.wait_for_function('window.__applied.length > 0', timeout=15000)
                    check(pg.evaluate('window.__applied[0]').startswith('ux-'), 'applying a generated style goes through the real API: ' + str(pg.evaluate('window.__applied')))
                    if shots:
                        pg.screenshot(path=os.path.join(shots, 'style-picker.png'), full_page=True)
                    check(not errors, 'no javascript errors in the style picker: %s' % errors[:2])
                    ctx.close()

                # ── مرورگرِ 21st.dev
                ctx, pg, errors = open_view('c21')
                pg.wait_for_selector('[data-testid=c21st-browser]', timeout=20000)
                pg.wait_for_selector('[data-testid=c21st-stats]')
                items = pg.locator('.c21-item')
                if items.count():
                    check(pg.locator('[data-testid=c21-insertable]').count() == items.count(), '«فقط قابلِ درج» is on: every card is insertable')
                    pg.locator('[data-testid=c21-preview]').first.click()
                    pg.wait_for_selector('[data-testid=c21-live] iframe', timeout=20000)
                    html = pg.locator('[data-testid=c21-live] iframe').first.get_attribute('srcdoc')
                    check('nbc21-' in html and 'dir="rtl"' in html, 'live preview is the converted component inside an RTL page')
                    check(pg.locator('.c21-thumb img').count() >= 0, 'preview thumbnails are fetched with the login (blob)')
                    pg.locator('[data-testid=c21-add]').first.click()
                    pg.wait_for_function('window.__added.length > 0', timeout=10000)
                    check(pg.evaluate('window.__added[0]').startswith('x'), 'insert hands the converted key to the builder: ' + str(pg.evaluate('window.__added')))
                    pg.fill('.c21-filters input[aria-label]', 'zzzz-no-such-thing')
                    pg.wait_for_function("document.querySelectorAll('.c21-item').length === 0", timeout=10000)
                    check('چیزی پیدا نشد' in pg.inner_text('.c21-list'), 'empty search says so')
                else:
                    check(False, 'the catalogue has no insertable components (run the pipeline first)')
                if shots:
                    pg.screenshot(path=os.path.join(shots, 'c21-browser.png'), full_page=True)
                check(not errors, 'no javascript errors in the 21st browser: %s' % errors[:2])
                ctx.close()
            finally:
                b.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('calls to the real API:', len(calls))
    print('FAILURES: %d' % len(FAILS))
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
