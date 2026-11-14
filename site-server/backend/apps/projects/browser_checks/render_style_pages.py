# -*- coding: utf-8 -*-
"""Renders the HOME starter of every site style as a standalone HTML page (no database) and copies the fonts next to it.

    cd backend && ../venv/bin/python apps/projects/browser_checks/render_style_pages.py OUTDIR [style ...]
    python apps/projects/browser_checks/check_style_layout.py OUTDIR            # real-browser check (Playwright, any machine)

Why a script and not only a unit test: the bugs it guards (title/subtitle collision, a drop cap that tears Persian letters, tight Amiri lines)
only exist in a real layout engine, with the real Persian fonts. tests_style_layout.py runs both automatically where Playwright is installed.
"""
import os, shutil, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from apps.projects.builder import starters, styles, theme as T, chagher_draft as CD
from apps.projects.builder.clean import clean_doc

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
fonts = os.path.join(out, 'fonts')
if not os.path.isdir(fonts):
    shutil.copytree(T.FONT_DIR, fonts)
only = sys.argv[2:]
for key in styles.ORDER:
    if only and key not in only:
        continue
    th = styles.apply_to_theme(T.default_theme(), key)
    th = T.clean_theme(th)
    page = styles.apply_to_doc(clean_doc(starters.starter_doc('home'), 'page'), key)
    parts = {'theme': th, 'page': page, 'header': clean_doc(starters.header_doc(None), 'header'),
             'footer': clean_doc(starters.footer_doc(None), 'footer'),
             'menu': [{'id': 'm1', 'url': '/', 'label': 'خانه'}, {'id': 'm2', 'url': '/about/', 'label': 'دربارهٔ ما'}]}
    html = CD.static_page(parts, fonts_prefix='fonts/')
    open(os.path.join(out, key + '.html'), 'w', encoding='utf-8').write(html)
    print('ok', key, len(html))
